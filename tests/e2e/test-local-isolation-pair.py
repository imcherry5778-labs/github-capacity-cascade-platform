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

    def test_expected_log_counts_ignore_connections_that_carried_no_request(self):
        probe = m.parse_ring(t10.PROBE_ROW)[0]
        rows = [t10.ring_row('critical', 200, 'shared', 1), t10.ring_row('bulk', 503, 'shared', 2), probe, t10.ring_row('bulk', 200, 'shared', 3)]
        self.assertEqual(pair.expected_log_counts(rows), {'ingress': 3, 'target': 3, 'app': 2})
        self.assertEqual(pair.expected_log_counts([dict(rows[0], termination='SC', status=502)]), {'ingress': 1, 'target': 0, 'app': 0})

    def restore_environment(self, **override):
        base = {'haproxy_config': 'ORIGINAL', 'hold_ms': '0', 'replicas': 1, 'stable': [{'kind': 'Deployment'}]}
        state = {'haproxy': 'ORIGINAL', 'hold': '0', 'ready': 1, 'stable': [{'kind': 'Deployment'}], 'resources': [], 'pods': []} | override
        def kj(*args):
            if 'configmap/haproxy' in args: return {'data': {'haproxy.cfg': state['haproxy']}}
            if 'configmap/ext-authz-hold' in args: return {'data': {'hold-ms': state['hold']}}
            if 'deployment/ext-authz-sim' in args: return {'spec': {'replicas': 1}, 'status': {'readyReplicas': state['ready']}}
            if 'pods' in args: return {'items': [{'metadata': {'name': p}} for p in state['pods']]}
            return {'items': [{'metadata': {'name': r}} for r in state['resources']]}
        return base, kj, state

    def test_restoration_is_proven_not_assumed(self):
        with mock.patch.dict(os.environ, {'DEV_TOKEN': 'tok', 'MAIN_SHA': SHA, 'ISSUE_TITLE': 'T'}):
            run = pair.Run(Path(tempfile.mkdtemp()), {'sha': SHA}, F, t10.plan(), {}, {}, {})
        def restore(**override):
            base, kj, state = self.restore_environment(**override)
            run.base = base
            with mock.patch.object(pair, 'kj', kj), mock.patch.object(pair, 'delete_list'), mock.patch.object(pair, 'wait_gone'), \
                    mock.patch.object(pair.local, 'apply'), mock.patch.object(pair, 'stable_snapshot', lambda: state['stable']), \
                    mock.patch.object(pair.gate, 'kube'), mock.patch.object(pair, 'rollout'):
                return run.restore([[{'kind': 'Deployment'}]])
        self.assertTrue(restore()['restored'])
        for override in ({'haproxy': 'EXPERIMENT'}, {'hold': '1000'}, {'ready': 0}, {'stable': [{'kind': 'changed'}]},
                         {'resources': ['ext-authz-shared']}, {'pods': ['ext-authz-shared-x']}):
            self.assertFalse(restore(**override)['restored'], override)
        # A failing step is reported and still lets the remaining steps run.
        base, kj, state = self.restore_environment(); run.base = base
        with mock.patch.object(pair, 'kj', kj), mock.patch.object(pair, 'delete_list', side_effect=RuntimeError), mock.patch.object(pair, 'wait_gone'), \
                mock.patch.object(pair.local, 'apply') as apply, mock.patch.object(pair, 'stable_snapshot', lambda: state['stable']), \
                mock.patch.object(pair.gate, 'kube'), mock.patch.object(pair, 'rollout'):
            result = run.restore([[{'kind': 'Deployment'}]])
        self.assertEqual(result['problems'], ['pools:RuntimeError']); self.assertFalse(result['restored']); apply.assert_called_once()

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
