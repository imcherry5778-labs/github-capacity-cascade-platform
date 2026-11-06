"""P10 Local pair harness boundaries; no cluster. Cluster effects are faked, the protocol bytes are not."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('pair', ROOT / 'scripts/local-isolation-pair.py')
pair = importlib.util.module_from_spec(spec); spec.loader.exec_module(pair)
spec_t = importlib.util.spec_from_file_location('p10tests', ROOT / 'tests/e2e/test-critical-bulk-isolation.py')
t10 = importlib.util.module_from_spec(spec_t); spec_t.loader.exec_module(t10)
m = pair.m
F = {'owner': 'dev', 'repo': 'journey', 'issue': 7}
SHA = 'b' * 40


class FakeIngress(ThreadingHTTPServer):
    """Stands in for ingress+HAProxy+Forgejo only to exercise the client's request shape and result mapping."""
    daemon_threads = True

    def __init__(self, behaviour):
        self.behaviour, self.requests = behaviour, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass

            def respond(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                outer.requests.append((self.command, self.path, dict(self.headers), body))
                status, payload = outer.behaviour(self.command, self.path, self.headers)
                self.send_response(status); self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)
            do_GET = do_POST = respond
        super().__init__(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def close(self):
        self.shutdown(); self.server_close()


def forgejo(status_for=None, refs_status=200, pack_status=200):
    routes = m.routes(F)
    issue = json.dumps({'number': 7, 'title': 'T', 'state': 'open', 'pull_request': None}).encode()
    def behave(method, path, headers):
        if (method, path) == ('GET', routes['critical'][0][1]):
            return (404, b'{}') if 'Authorization' not in headers else (status_for or 200, issue)
        if (method, path) == ('GET', routes['bulk'][0][1]):
            return refs_status, b'000eversion 2\n0013ls-refs=unborn\n0000'
        if (method, path) == ('POST', routes['bulk'][1][1]):
            return pack_status, ('0040%s refs/heads/main\n0000' % SHA).encode()
        return 403, b''
    return behave


class FakeCluster:
    """Model of the shared-gate namespace: objects by (kind, name) and the few mutable fixture fields run_pair touches."""
    PLURAL = {'deployments': 'Deployment', 'services': 'Service', 'sidecars.networking.istio.io': 'Sidecar'}

    def __init__(self, apply_fail_after=None, delete_failures=0, rollout_failure=False, haproxy_failure_once=False, identify_failure=False,
                 patch_failure=False, ghost=False, interrupt_in=None, objects=None, unlabeled=False):
        self.objects, self.calls, self.deleted_names = set(objects or ()), [], []
        self.apply_fail_after, self.delete_failures, self.rollout_failure = apply_fail_after, delete_failures, rollout_failure
        self.haproxy_failure_once, self.identify_failure, self.patch_failure, self.ghost = haproxy_failure_once, identify_failure, patch_failure, ghost
        self.interrupt_in, self.unlabeled = interrupt_in, unlabeled
        self.haproxy, self.hold, self.replicas, self.base = 'ORIGINAL ext-authz-sim.shared-gate', '0', 1, None

    @staticmethod
    def key(item): return (item['kind'], item['metadata']['name'])

    def apply_list(self, items):
        self.calls.append('apply')
        for index, item in enumerate(items):
            if self.apply_fail_after is not None and index >= self.apply_fail_after:
                raise subprocess.CalledProcessError(1, 'kubectl apply')
            self.objects.add(self.key(item))

    def delete_list(self, items):
        self.calls.append('delete')
        if self.delete_failures:
            self.delete_failures -= 1
            raise subprocess.CalledProcessError(1, 'kubectl delete')
        for item in items:
            self.deleted_names.append('%s/%s' % self.key(item))
            if not self.ghost: self.objects.discard(self.key(item))

    def present(self, items): return ['%s/%s' % self.key(i) for i in items if self.key(i) in self.objects]

    def wait_gone(self, selector, timeout): pass

    def rollout(self, name, seconds):
        if self.rollout_failure and 'ext-authz-sim' not in name: raise subprocess.CalledProcessError(1, 'kubectl rollout')

    def haproxy_apply(self, config, checkpoint):
        if self.haproxy_failure_once and 'ext-authz-sim' not in config:
            self.haproxy_failure_once = False; self.haproxy = config
            raise ValueError('ingress HAProxy endpoint did not converge')
        self.haproxy = config

    def kube(self, *args):
        if 'patch' in args:
            if self.patch_failure: self.patch_failure = False; raise subprocess.CalledProcessError(1, 'kubectl patch')
            self.hold = json.loads(args[args.index('-p') + 1])['data']['hold-ms']
        if 'scale' in args:
            self.replicas = int([a for a in args if a.startswith('--replicas=')][0].split('=')[1])
        return ''

    def kj(self, *args):
        if 'configmap/haproxy' in args: return {'data': {'haproxy.cfg': self.haproxy}}
        if 'configmap/ext-authz-hold' in args: return {'data': {'hold-ms': self.hold}}
        if 'deployment/ext-authz-sim' in args: return {'spec': {'replicas': self.replicas}, 'status': {'readyReplicas': self.replicas}}
        if 'pods' in args: return {'items': [{'metadata': {'name': 'pool-pod'}}] if self.ghost and self.objects else []}
        kind = self.PLURAL.get(args[args.index('get') + 1])
        labeled = [] if self.unlabeled else [n for k, n in sorted(self.objects) if k == kind]
        return {'items': [{'metadata': {'name': n}} for n in labeled]}


class PairTests(unittest.TestCase):
    def client(self, server):
        return pair.Client(F, 'tok', SHA, 'T', port=server.server_address[1])

    def test_ls_refs_request_is_the_protocol_v2_message_real_git_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, work = Path(directory) / 'repo.git', Path(directory) / 'w'
            git = lambda *a, cwd=None, **k: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True, **k)
            git('init', '--bare', '-q', str(repo)); git('init', '-q', str(work))
            git('-c', 'user.email=a@b', '-c', 'user.name=n', 'commit', '-q', '--allow-empty', '-m', 'x', cwd=work)
            git('branch', '-M', 'main', cwd=work); git('push', '-q', str(repo), 'main', cwd=work)
            sha = git('rev-parse', 'HEAD', cwd=work).stdout.decode().strip()
            env = dict(os.environ, GIT_PROTOCOL='version=2')
            answer = subprocess.run(['git', 'upload-pack', '--stateless-rpc', str(repo)], input=pair.ls_refs_body(), env=env, capture_output=True, check=True)
            self.assertIn((sha + ' refs/heads/main').encode(), answer.stdout)
            advertisement = subprocess.run(['git', 'upload-pack', '--stateless-rpc', '--advertise-refs', str(repo)], env=env, capture_output=True, check=True)
            self.assertTrue(b'version 2' in advertisement.stdout and b'ls-refs' in advertisement.stdout)

    def test_probes_map_native_results_without_hiding_failures(self):
        server = FakeIngress(forgejo())
        try:
            probes = self.client(server).probes()
            self.assertEqual(probes['critical']('critical-1', 1), {'semantic_result': True, 'status': 200, 'error_class': 'none', 'overload': False})
            self.assertEqual(probes['bulk']('bulk-1', 1), {'semantic_result': True, 'status': 200, 'error_class': 'none', 'overload': False})
        finally:
            server.close()
        for overload in (403, 503):
            server = FakeIngress(forgejo(status_for=overload))
            try:
                r = self.client(server).probes()['critical']('critical-2', 1)
                self.assertEqual((r['semantic_result'], r['status'], r['error_class'], r['overload']), (False, overload, 'http_status', overload == 403))
            finally:
                server.close()

    def test_requests_are_exact_counted_per_http_request_and_carry_only_correlation(self):
        server = FakeIngress(forgejo()); client = self.client(server)
        try:
            client.probes()['critical']('critical-3', 1); client.probes()['bulk']('bulk-3', 2)
            self.assertEqual(client.counts, {'critical': 1, 'bulk': 2})              # a Git read is two HTTP checks
            (m1, p1, h1, _), (m2, p2, h2, _), (m3, p3, h3, body) = server.requests
            self.assertEqual([(m1, p1), (m2, p2), (m3, p3)], [('GET', m.routes(F)['critical'][0][1])] + [(a, b) for a, b in m.routes(F)['bulk']])
            self.assertEqual((h1['x-operation-id'], h1['x-attempt-id']), ('critical-3', 'critical-3-attempt-1'))
            self.assertEqual((h2['x-attempt-id'], h3['x-attempt-id']), ('bulk-3-attempt-2-http-1', 'bulk-3-attempt-2-http-2'))
            self.assertTrue(h1['Authorization'].startswith('token ') and h2['Authorization'].startswith('Basic '))
            self.assertEqual((h2['Git-Protocol'], h3['Content-Type']), ('version=2', 'application/x-git-upload-pack-request'))
            self.assertEqual(body, pair.ls_refs_body())
            # Class is never a client input: no priority/class header exists on any request.
            self.assertFalse(any(k.lower() in {'x-priority', 'x-traffic-class', 'x-p10-class'} for h in (h1, h2, h3) for k in h))
        finally:
            server.close()

    def test_git_read_failure_stops_at_the_failing_check_and_is_reported_once(self):
        for refs, pack, issued in ((403, 200, 1), (200, 403, 2), (200, 200, 2)):
            server = FakeIngress(forgejo(refs_status=refs, pack_status=pack)); client = self.client(server)
            try:
                r = client.probes()['bulk']('bulk-4', 1)
                self.assertEqual(client.counts['bulk'], issued)
                self.assertEqual(r['semantic_result'], (refs, pack) == (200, 200))
                if not r['semantic_result']:
                    self.assertEqual((r['status'], r['error_class'], r['overload']), (403, 'http_status', True))
            finally:
                server.close()
        # Wrong content with HTTP 200 is a semantic failure, not a pass.
        server = FakeIngress(lambda *a: (200, b'garbage')); client = self.client(server)
        try:
            r = client.probes()['bulk']('bulk-5', 1)
            self.assertEqual((r['semantic_result'], r['error_class']), (False, 'semantic_error'))
        finally:
            server.close()

    def test_transport_failure_is_visible_and_never_retried(self):
        server = FakeIngress(forgejo()); port = server.server_address[1]; server.close()
        client = pair.Client(F, 'tok', SHA, 'T', port=port)
        r = client.probes()['critical']('critical-6', 1)
        self.assertEqual((r['semantic_result'], r['status'], r['error_class'], r['overload']), (False, None, 'transport', False))
        self.assertEqual(client.counts['critical'], 1)

    def test_native_stat_parsing_and_filter(self):
        prefixes = ['cluster.inbound|8080||.', 'cluster.inbound|8080||;.']
        text = '\n'.join(['cluster.xds-grpc;.upstream_rq_total: 9', 'cluster.inbound|8080||;.upstream_rq_active: 2',
                          'cluster.inbound|8080||;.upstream_rq_active_overflow: 5', 'cluster.inbound|8080||;.upstream_rq_pending_active: 0',
                          'cluster.inbound|8080||;.upstream_rq_pending_overflow: 0', 'cluster.inbound|8080||;.upstream_rq_total: 11',
                          'cluster.inbound|8080||;.upstream_cx_total: 4'])
        self.assertEqual(pair.parse_stats(text, prefixes), {'upstream_rq_active': 2, 'upstream_rq_active_overflow': 5,
                         'upstream_rq_pending_active': 0, 'upstream_rq_pending_overflow': 0, 'upstream_rq_total': 11})
        for bad in (text.replace('upstream_rq_total: 11', 'upstream_rq_total: x'), text.replace('cluster.inbound|8080||;.upstream_rq_total: 11\n', ''),
                    text + '\ncluster.inbound|8080||;.upstream_rq_total: 12', '', 'cluster.xds-grpc;.upstream_rq_total: 9'):
            with self.assertRaises(ValueError): pair.parse_stats(bad, prefixes)    # absent/duplicate/non-integer is never zero
        path = pair.stat_path(prefixes)
        self.assertTrue(path.startswith('/stats?filter=') and 'inbound' in path and '%7C' in path and ' ' not in path)

    def test_sampler_rows_gaps_and_missed_ticks(self):
        targets = [{'uid': 'a', 'pool': 'shared', 'name': 'pod-a', 'prefixes': ['x'], 'endpoints': ['a', 'b'], 'capacity': 2},
                   {'uid': 'b', 'pool': 'shared', 'name': 'pod-b', 'prefixes': ['x'], 'endpoints': ['a', 'b'], 'capacity': 2}]
        now = [100.0]
        clock = lambda: now[0]
        stats = {'upstream_rq_active': 1, 'upstream_rq_active_overflow': 2, 'upstream_rq_total': 3, 'upstream_rq_pending_active': 0, 'upstream_rq_pending_overflow': 0}
        def fetch(target):
            now[0] += .01
            if target['uid'] == 'b' and now[0] > 100.5: raise OSError('port-forward lost')
            return dict(stats)
        sampler = pair.Sampler(targets, .25, fetch, lambda: {'a': {'ready': True, 'restarts': 0}, 'b': {'ready': True, 'restarts': 1}}, clock=clock)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            sampler.tick(executor)
            now[0] = 100.6; sampler.tick(executor)
        self.assertEqual((len(sampler.rows), sampler.failures), (1, 1))               # a failed read leaves a gap, never a zero row
        row = sampler.rows[0]
        self.assertTrue(row['sample_at'] < row['at'] and 100.0 <= row['sample_at'])
        self.assertEqual([t['uid'] for t in row['targets']], ['a', 'b'])
        self.assertEqual(row['targets'][1]['restarts'], 1)
        for t in row['targets']:
            self.assertFalse({'name', 'prefixes', 'endpoints'} & set(t)); self.assertEqual(t['stats'], stats)

    def pod(self, uid, pool, restarts=0, proxy_ready=True):
        status = lambda name, extra=None: {'name': name, 'imageID': 'sha256:' + name, 'containerID': 'containerd://%s-%s' % (name, uid), 'ready': proxy_ready,
                                          'restartCount': restarts} | (extra or {})
        return {'metadata': {'uid': uid, 'name': 'pod-' + uid, 'labels': {'p10.pool': pool}},
                'spec': {'containers': [{'name': 'app', 'resources': {'requests': {'cpu': '50m'}}}],
                         'initContainers': [{'name': 'istio-proxy', 'restartPolicy': 'Always', 'resources': {'limits': {'cpu': '2'}}}]},
                'status': {'containerStatuses': [status('app')], 'initContainerStatuses': [status('istio-proxy')]}}

    def test_target_identity_binds_pod_service_endpoints_and_effective_capacity(self):
        v = m.plan(t10.plan())
        clusters = [{'name': 'inbound|8080||', 'altStatName': 'inbound|8080||;', 'type': 'ORIGINAL_DST',
                     'circuitBreakers': {'thresholds': [{'maxRequests': 2}]}}]
        service = {'metadata': {'name': 'ext-authz-critical', 'uid': 'svc-1'}}
        slices = lambda *uids: [{'endpoints': [{'conditions': {'ready': True}, 'targetRef': {'kind': 'Pod', 'uid': u}} for u in uids]}]
        t = pair.target_identity(self.pod('u1', 'critical'), v, service, slices('u1'), clusters, 1000)
        self.assertEqual((t['uid'], t['pool'], t['service'], t['service_uid'], t['endpoint_pod_uid'], t['capacity'], t['hold_ms']),
                         ('u1', 'critical', 'ext-authz-critical', 'svc-1', 'u1', 2, 1000))
        self.assertEqual(t['sidecar_id'], 'containerd://istio-proxy-u1')
        self.assertEqual(t['prefixes'], ['cluster.inbound|8080||.', 'cluster.inbound|8080||;.'])
        other = pair.target_identity(self.pod('u2', 'bulk'), v, {'metadata': {'name': 'ext-authz-bulk', 'uid': 'svc-2'}}, slices('u2'), clusters, 1000)
        self.assertEqual((t['mapping_sha256'], t['resources_sha256'], t['image_id']), (other['mapping_sha256'], other['resources_sha256'], other['image_id']))
        self.assertEqual(pair.target_identity(self.pod('u1', 'critical'), v, service, slices('u9'), clusters, 1000)['endpoint_pod_uid'], None)   # not an endpoint
        with self.assertRaises(ValueError): pair.target_identity(self.pod('u1', 'bulk'), v, service, slices('u1'), clusters, 1000)           # Service/pool mismatch
        with self.assertRaises(ValueError):
            pair.target_identity(self.pod('u1', 'critical'), v, service, slices('u1'), [dict(clusters[0], circuitBreakers={'thresholds': [{'maxRequests': 1024}]})], 1000)
        bare = self.pod('u1', 'critical'); bare['status']['initContainerStatuses'] = []; bare['spec']['initContainers'] = []
        with self.assertRaises(ValueError): pair.target_identity(bare, v, service, slices('u1'), clusters, 1000)                              # no sidecar

    def guard_inputs(self, mutate=None, snapshots=6):
        pod = lambda uid, containers=('main',), **kw: {'name': 'n-' + uid, 'uid': uid, 'phase': 'Running', 'reason': None, 'ready': True,
                                                      'containers': [{'name': c, 'ready': True, 'restarts': 0, 'last_termination': None} for c in containers]} | kw
        def snapshot():
            return {'pods': {'forgejo': pod('f'), 'postgres': pod('p'), 'haproxy': pod('h'), 'ingress': pod('i'),
                             'target-t1': pod('t1', ('app', 'istio-proxy')), 'target-t2': pod('t2', ('app', 'istio-proxy'))},
                    'nodes': [{'name': 'n', 'conditions': {'Ready': 'True', 'MemoryPressure': 'False', 'DiskPressure': 'False', 'PIDPressure': 'False'}}],
                    'postgres': {'query_ok': True, 'connections': 10, 'max_connections': 100, 'reserved': 0, 'superuser_reserved': 3}}
        shots = [{'begin': 90 + i * 2, 'end': 90.5 + i * 2, 'snapshot': snapshot()} for i in range(snapshots)]
        sentinels = [{'read': {'semantic_result': True, 'start_monotonic': 89.5 + i, 'end_monotonic': 89.7 + i},
                      'health': {'semantic_result': True, 'start_monotonic': 89.7 + i, 'end_monotonic': 89.8 + i}} for i in range(14)]
        if mutate: mutate(shots, sentinels)
        facts = {'haproxy': {'queue': 0}, 'native_auth': True, 'ingress': {'rows': 1}, 'span': (92.0, 100.0)}
        return shots, sentinels, facts

    def test_guards_pass_only_with_same_window_stable_inputs(self):
        shots, sentinels, facts = self.guard_inputs()
        guards = pair.guards_from(shots, (91.0, 100.0), sentinels, True, facts)
        self.assertEqual(set(guards), m.GUARDS)
        self.assertTrue(all(g['observed'] and not g['competing_bottleneck'] and len(g['evidence_sha256']) == 64 for g in guards.values()))
        self.assertEqual(guards['forgejo_sidecar']['competing_bottleneck'], False)    # absent in Local; its absence is the observation
        def restarted(shots, _): shots[3]['snapshot']['pods']['target-t1']['containers'][1]['restarts'] = 1
        def replaced(shots, _): shots[3]['snapshot']['pods']['target-t2']['uid'] = 'new'
        def pressure(shots, _): shots[2]['snapshot']['nodes'][0]['conditions']['MemoryPressure'] = 'True'
        def exhausted(shots, _): shots[2]['snapshot']['postgres']['connections'] = 99
        def failing(shots, sentinels): sentinels[5]['read']['semantic_result'] = False
        def hole(shots, _): del shots[1:5]    # one snapshot gap of ten seconds against a two-second cadence
        def late(shots, sentinels): del sentinels[-4:]
        def pending(shots, _): shots[4]['snapshot']['pods']['haproxy']['ready'] = False
        def gap(_, sentinels): del sentinels[3:11]    # eight seconds without a direct read against a one-second cadence
        for mutate, failed in ((restarted, ['scheduling']), (replaced, ['scheduling']), (pressure, ['node']), (exhausted, ['postgres']),
                               (failing, ['sentinel']), (hole, ['forgejo', 'forgejo_sidecar', 'postgres', 'node', 'scheduling', 'haproxy', 'ingress']),
                               (late, ['sentinel']), (gap, ['sentinel']), (pending, ['haproxy', 'scheduling'])):
            shots, sentinels, facts = self.guard_inputs(mutate)
            guards = pair.guards_from(shots, (91.0, 100.0), sentinels, True, facts)
            self.assertEqual(sorted(k for k, g in guards.items() if g['competing_bottleneck']), sorted(failed), mutate.__name__)
        shots, sentinels, facts = self.guard_inputs()
        self.assertTrue(pair.guards_from(shots, (91.0, 100.0), sentinels, False, facts)['haproxy']['competing_bottleneck'])
        self.assertTrue(pair.guards_from(shots, (91.0, 100.0), sentinels, False, facts)['ingress']['competing_bottleneck'])
        self.assertTrue(pair.guards_from(shots, (91.0, 100.0), sentinels, True, facts | {'native_auth': False})['tls_native_auth']['competing_bottleneck'])

    def test_haproxy_snapshot_rejects_a_ring_that_moved_around_the_counters(self):
        # CI 42189313574: a probe row logged between the ring and stats execs skewed frontend vs ring by one.
        rings = iter(['r0', 'r1', 'r1', 'r1'])
        def kube(*args):
            return next(rings) if 'show events p10' in args[-1] else 'x'
        saved = pair.haproxy_pod, pair.gate.kube, m.parse_ring, m.parse_haproxy_info, m.parse_haproxy_stats
        try:
            pair.haproxy_pod, pair.gate.kube = (lambda: ('haproxy-0', 'id')), kube
            m.parse_ring, m.parse_haproxy_info, m.parse_haproxy_stats = (lambda s: [s]), (lambda s: {}), (lambda s: {})
            self.assertEqual(pair.haproxy_snapshot()['ring'], ['r1'])
            rings = iter(['a', 'b', 'c', 'd', 'e', 'f'])
            with self.assertRaisesRegex(ValueError, 'ring changed'):
                pair.haproxy_snapshot()
        finally:
            pair.haproxy_pod, pair.gate.kube, m.parse_ring, m.parse_haproxy_info, m.parse_haproxy_stats = saved

    def test_expected_log_counts_ignore_connections_that_carried_no_request(self):
        probe = m.parse_ring(t10.PROBE_ROW)[0]
        rows = [t10.ring_row('critical', 200, 'shared', 1), t10.ring_row('bulk', 503, 'shared', 2), probe, t10.ring_row('bulk', 200, 'shared', 3)]
        self.assertEqual(pair.expected_log_counts(rows), {'ingress': 3, 'target': 3, 'app': 2})
        self.assertEqual(pair.expected_log_counts([dict(rows[0], termination='SC', status=502)]), {'ingress': 1, 'target': 0, 'app': 0})

    # --- owned cleanup: the real setup/run_pair/restore code against a cluster model with injectable failures -----------

    def environment(self, directory, cluster):
        """Files, env and patches for run_pair. Only cluster effects and the measurement itself are replaced."""
        out = Path(directory)
        sha = 'a' * 40
        m.save(out / 'source.json', {'sha': sha, 'dirty': False})
        m.save(out / 'p10-healthy.json', {'source_sha': sha, 'experiment_haproxy_restored': True, 'classification': 'healthy-path-verified',
                                          'forgejo_native_auth': True})
        m.save(out / 'app-image.json', {'config_digest': 'sha256:' + 'f' * 64})
        (out / 'marker').write_text('d' * 64 + '\n')
        base = {'haproxy_config': 'ORIGINAL ext-authz-sim.shared-gate', 'hold_ms': '0', 'replicas': 1,
                'stable': [{'kind': 'Deployment', 'uid': 'u', 'spec': {}}], 'template': t10.TEMPLATE}
        cluster.base = base
        env = {'DEV_USER': 'dev', 'DEV_TOKEN': 'tok', 'ISSUE_NUMBER': '7', 'ISSUE_TITLE': 'T', 'MAIN_SHA': SHA,
               'LOCAL_CLUSTER_OWNERSHIP_MARKER': str(out / 'marker')}
        def identify(arm, v):
            if cluster.identify_failure: raise ValueError('effective inbound capacity/hold did not converge')
            return [{'uid': str(i), 'pool': 'shared' if arm == 'shared' else m.CLASSES[i], 'name': 'pod-%d' % i} for i in range(2)]
        def measure(run, arm, targets):
            if cluster.interrupt_in == arm: raise KeyboardInterrupt()
            (run.out / arm).mkdir()
            return t10.synthetic(arm)
        patches = [mock.patch.dict(os.environ, env), mock.patch.object(pair.gate, 'owned_image_node'), mock.patch.object(pair, 'baseline', lambda: base),
                   mock.patch.object(pair, 'kj', cluster.kj), mock.patch.object(pair, 'apply_list', cluster.apply_list),
                   mock.patch.object(pair, 'delete_list', cluster.delete_list), mock.patch.object(pair, 'present', cluster.present),
                   mock.patch.object(pair, 'wait_gone', cluster.wait_gone), mock.patch.object(pair, 'rollout', cluster.rollout),
                   mock.patch.object(pair, 'stable_snapshot', lambda: base['stable']), mock.patch.object(pair.gate, 'kube', cluster.kube),
                   mock.patch.object(pair.local, 'apply', cluster.haproxy_apply), mock.patch.object(pair, 'identify', identify),
                   mock.patch.object(pair.Run, 'measure', measure)]
        return patches

    def run_pair(self, cluster):
        directory = tempfile.mkdtemp()
        patches = self.environment(directory, cluster)
        for patch in patches: patch.start()
        try:
            try: code = pair.run_pair(directory)
            except BaseException as exc: code = type(exc).__name__
        finally:
            for patch in reversed(patches): patch.stop()
        read = lambda name: json.loads((Path(directory) / 'p10-pair' / name).read_text()) if (Path(directory) / 'p10-pair' / name).exists() else None
        return code, read('restoration.json'), read('failure.json'), read('result.json')

    def assert_pristine(self, cluster, restoration):
        self.assertEqual(cluster.objects, set())
        self.assertEqual((cluster.haproxy, cluster.hold, cluster.replicas), (cluster.base['haproxy_config'], '0', 1))
        self.assertIs(restoration['restored'], True)
        self.assertEqual((restoration['owned_pending'], restoration['p10_resources'], restoration['problems']), (0, [], []))

    def test_clean_run_releases_ownership_and_leaves_the_cluster_pristine(self):
        cluster = FakeCluster()
        code, restoration, failure, result = self.run_pair(cluster)
        self.assertEqual((code, failure, result['status']), (0, None, 'positive'))
        self.assert_pristine(cluster, restoration)
        self.assertEqual(cluster.calls.count('apply'), 2)   # one inventory per arm, the first removed before the second is admitted

    def test_failure_at_every_setup_step_still_removes_what_may_exist(self):
        cases = {'partial apply (first object only)': FakeCluster(apply_fail_after=1), 'apply fails before any object': FakeCluster(apply_fail_after=0),
                 'rollout never completes': FakeCluster(rollout_failure=True), 'HAProxy swap fails after pools exist': FakeCluster(haproxy_failure_once=True),
                 'mapping/identify fails': FakeCluster(identify_failure=True), 'hold patch fails before apply': FakeCluster(patch_failure=True)}
        for name, cluster in cases.items():
            code, restoration, failure, result = self.run_pair(cluster)
            self.assertEqual((code, result), (1, None), name)
            self.assertIsNotNone(failure, name)
            self.assert_pristine(cluster, restoration)

    def test_a_pool_object_created_by_the_failed_apply_is_removed_by_exact_name(self):
        cluster = FakeCluster(apply_fail_after=2)
        code, restoration, failure, _ = self.run_pair(cluster)
        self.assertEqual(code, 1)
        self.assertEqual(sorted(cluster.deleted_names), sorted(['Deployment/ext-authz-shared', 'Service/ext-authz-shared', 'Sidecar/p10-capacity']))
        self.assert_pristine(cluster, restoration)

    def test_transition_delete_failure_keeps_ownership_and_restoration_retries(self):
        cluster = FakeCluster(delete_failures=1)    # the arm transition's delete fails once; the restoration delete succeeds
        code, restoration, failure, result = self.run_pair(cluster)
        self.assertEqual((code, result, failure['class']), (1, None, 'ValueError'))
        self.assertEqual(cluster.calls, ['apply', 'delete', 'delete'])   # not re-applied; the shared inventory was still owned
        self.assert_pristine(cluster, restoration)

    def test_incomplete_cleanup_is_nonzero_and_reported(self):
        for name, cluster in {'delete keeps failing': FakeCluster(delete_failures=99),
                              'delete succeeds but the objects remain': FakeCluster(ghost=True)}.items():
            code, restoration, failure, result = self.run_pair(cluster)
            self.assertEqual((code, result), (1, None), name)
            self.assertIs(restoration['restored'], False, name)
            self.assertGreater(restoration['owned_pending'], 0, name)
            self.assertTrue(any(p.startswith('pools:') for p in restoration['problems']), name)
            self.assertTrue(cluster.objects, name)           # nothing claims they are gone
        # A run that measured fine but could not clean up must not pass either.
        cluster = FakeCluster(ghost=True, delete_failures=0)
        cluster.ghost_after = 'apply'
        code, restoration, _, result = self.run_pair(cluster)
        self.assertEqual((code, result), (1, None)); self.assertIs(restoration['restored'], False)

    def test_interrupt_still_runs_the_owned_cleanup(self):
        cluster = FakeCluster(interrupt_in='isolated')
        code, restoration, failure, result = self.run_pair(cluster)
        self.assertEqual((code, failure, result), ('KeyboardInterrupt', None, None))   # propagates, after cleanup
        self.assert_pristine(cluster, restoration)

    def test_existing_object_with_a_p10_name_is_never_adopted_or_deleted(self):
        for existing in ({('Deployment', 'ext-authz-bulk')}, {('Service', 'ext-authz-shared')}, {('Sidecar', 'p10-capacity')}):
            cluster = FakeCluster(objects=set(existing), unlabeled=True)    # present, but not labeled as a P10 pool
            code, restoration, failure, result = self.run_pair(cluster)
            self.assertEqual((code, result), ('ValueError', None))
            self.assertEqual(cluster.calls, [])             # no apply, no delete, no scale
            self.assertEqual(cluster.objects, existing)     # untouched

    def test_restore_is_idempotent_and_only_claims_what_it_read_back(self):
        cluster = FakeCluster()
        cluster.base = {'haproxy_config': 'ORIGINAL', 'hold_ms': '0', 'replicas': 1, 'stable': [{'kind': 'Deployment'}]}
        cluster.haproxy = 'EXPERIMENT'
        with mock.patch.dict(os.environ, {'DEV_TOKEN': 'tok', 'MAIN_SHA': SHA, 'ISSUE_TITLE': 'T'}):
            run = pair.Run(Path(tempfile.mkdtemp()), {'sha': SHA}, F, t10.plan(), cluster.base, {}, {})
        for patch in (mock.patch.object(pair, 'kj', cluster.kj), mock.patch.object(pair, 'delete_list', cluster.delete_list),
                      mock.patch.object(pair, 'present', cluster.present), mock.patch.object(pair, 'wait_gone', cluster.wait_gone),
                      mock.patch.object(pair, 'rollout', cluster.rollout), mock.patch.object(pair, 'stable_snapshot', lambda: cluster.base['stable']),
                      mock.patch.object(pair.gate, 'kube', cluster.kube), mock.patch.object(pair.local, 'apply', cluster.haproxy_apply)):
            patch.start(); self.addCleanup(patch.stop)
        self.assertTrue(run.restore()['restored']); self.assertTrue(run.restore()['restored'])      # nothing owned: still proves the state
        cluster.hold, cluster.replicas = '1000', 0
        for broken, key in (('haproxy', 'haproxy_restored'), ('stable', 'stable_forgejo_unchanged')):
            cluster.base['stable'] = [{'kind': 'Deployment'}]; cluster.haproxy = 'ORIGINAL'
            if broken == 'stable':
                cluster.base['stable'] = [{'kind': 'Deployment'}]
                with mock.patch.object(pair, 'stable_snapshot', lambda: [{'kind': 'changed'}]):
                    result = run.restore()
            else:
                with mock.patch.object(cluster, 'haproxy_apply', lambda config, checkpoint: None):
                    with mock.patch.object(pair.local, 'apply', cluster.haproxy_apply):
                        cluster.haproxy = 'DRIFTED'; result = run.restore()
            self.assertIs(result['restored'], False, broken); self.assertIs(result[key], False, broken)

    def test_saved_pair_is_revalidated_from_raw_files(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory); pair_dir = out / 'p10-pair'
            runs = {arm: t10.synthetic(arm) for arm in m.ARMS}
            for arm, run in runs.items():
                (pair_dir / arm).mkdir(parents=True); m.save(pair_dir / arm / 'run.json', run)
            source = {'sha': 'a' * 40, 'dirty': False}
            m.save(out / 'source.json', source); m.save(pair_dir / 'restoration.json', {'restored': True})
            self.assertEqual(pair.finish(pair_dir, runs, source), 0)
            saved = json.loads((pair_dir / 'result.json').read_text())
            self.assertEqual((saved['status'], saved['completed'], saved['limitations'] == pair.LIMITATIONS), ('positive', True, True))
            pair.verify(out)
            def overwrite(path, value): Path(path).write_text(json.dumps(value))
            for path, changed in ((out / 'source.json', {'sha': 'c' * 40, 'dirty': False}),
                                  (pair_dir / 'restoration.json', {'restored': False}),
                                  (pair_dir / 'result.json', saved | {'status': 'valid-negative'})):
                before = path.read_text(); overwrite(path, changed)
                with self.assertRaises(ValueError): pair.verify(out)
                path.write_text(before)
            pair.verify(out)
            # An invalid or inconclusive pair is a failing exit, never a quiet pass.
            insufficient = copy.deepcopy(runs); insufficient['shared']['samples'] = [s for s in insufficient['shared']['samples'] if s['at'] < 1 or s['at'] > 9]
            with tempfile.TemporaryDirectory() as other:
                (Path(other) / 'p10-pair').mkdir()
                self.assertEqual(pair.finish(Path(other) / 'p10-pair', insufficient, source), 1)
                self.assertEqual(json.loads((Path(other) / 'p10-pair' / 'result.json').read_text())['status'], 'observation-insufficient')


if __name__ == '__main__': unittest.main()
