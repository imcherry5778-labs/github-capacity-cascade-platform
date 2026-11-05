"""P10 cost-free boundaries; synthetic inputs are NOT runtime evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('isolation', ROOT / 'scripts/critical-bulk-isolation.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
spec8 = importlib.util.spec_from_file_location('p8tests', ROOT / 'tests/e2e/test-azure-cascade.py')
t8 = importlib.util.module_from_spec(spec8); spec8.loader.exec_module(t8)
F = {'owner': 'fixture', 'repo': 'journey', 'issue': 1}
LOCAL_IDENTITY = {'source_sha': 'a' * 40, 'cluster_uid': 'd' * 64, 'stable_revision': 'e' * 64, 'ext_authz_image_id': 'sha256:' + 'f' * 64}
TEMPLATE = {'metadata': {'annotations': {'sidecar.istio.io/inject': 'true'}}, 'spec': {'containers': [{'name': 'app', 'image': 'ext-authz-sim:test'}]}}
CLOCK = {'start': {'wall': 1000.0, 'monotonic': 0.0, 'uncertainty': .001}, 'end': {'wall': 1060.0, 'monotonic': 60.0, 'uncertainty': .001}}


def plan():
    return m.load(ROOT / 'experiments/fixtures/critical-bulk/candidate.json')


def synthetic(arm, environment='local'):
    v = plan() | {'duration_seconds': 10}
    scheduled = m.schedule(v)
    events = [{'record': 'schedule', 'origin': 0, 'items': scheduled, 'sha256': m.digest(scheduled)}]
    counts = {k: {'checks': 0, 'admitted': 0, 'rejected': 0, 'queue': 0, 'other': 0, 'app': 0,
                  'ingress': 0, 'backend': 0, 'target_total': 0, 'pool': 'shared' if arm == 'shared' else k} for k in m.CLASSES}
    for item in scheduled:
        success = item['kind'] == 'critical' and arm == 'isolated'
        events.append({'record': 'operation', **item, 'scheduled': item['at'], 'submitted': item['at'], 'issued': item['at'],
                       'completed': item['at'] + .01, 'attempts': [{'index': 1, 'started': item['at'], 'ended': item['at'] + .01,
                           'semantic_result': success, 'error_class': 'none' if success else 'http_status', 'status': 200 if success else 403}]})
        c = counts[item['kind']]
        for k in ('checks', 'ingress', 'backend', 'target_total'): c[k] += 1
        c['admitted' if success else 'rejected'] += 1
        c['app'] += int(success)
    events.append({'record': 'end', 'at': 10, 'expected_end': 10})
    targets = [{'uid': str(i), 'sidecar_id': 'envoy-' + str(i), 'pool': 'shared' if arm == 'shared' else m.CLASSES[i],
                'image_id': 'sha256:fixture', 'resources_sha256': 'c' * 64,
                'service': 'ext-authz-' + ('shared' if arm == 'shared' else m.CLASSES[i]),
                'service_uid': 'svc-shared' if arm == 'shared' else 'svc-' + str(i), 'endpoint_pod_uid': str(i), 'capacity': 2, 'hold_ms': 1000, 'mapping_sha256': 'a' * 64,
                'ready': True, 'restarts': 0,
                'stats': {k: 0 for k in m.COUNTERS + ('upstream_rq_active', 'upstream_rq_pending_active')}} for i in range(2)]
    samples = []
    for index in range(43):
        at = -.25 + index * .25
        ts = copy.deepcopy(targets)
        if 0 <= at <= 10:
            for t in ts:
                if t['pool'] != 'critical': t['stats']['upstream_rq_active'] = 2
        if at >= 10:
            for pool in {t['pool'] for t in ts}:
                target = next(t for t in ts if t['pool'] == pool)
                relevant = [c for c in counts.values() if c['pool'] == pool]
                target['stats']['upstream_rq_total'] = sum(c['admitted'] for c in relevant)
                target['stats']['upstream_rq_active_overflow'] = sum(c['rejected'] for c in relevant)
        samples.append({'at': at, 'sample_at': at, 'targets': ts})
    invariants = {k: 'c' * 64 for k in ('ingress_config_sha256', 'native_route_sha256', 'tls_auth_sha256', 'target_resources_sha256',
                  'proxy_retries_sha256', 'sentinel_sha256', 'confounder_policy_sha256')}
    invariants.update(haproxy_image_id='sha256:fixture', haproxy_processes=1, haproxy_threads=1, haproxy_maxconn=256)
    if environment == 'azure':
        identity = t8.identity() | {'source_sha': 'a' * 40}
        invariants.update(stable_revision=identity['stable_revision'])
        binding = m.binding(identity, v, F, invariants)
    else:
        invariants.update(stable_revision=LOCAL_IDENTITY['stable_revision'])
        binding = m.binding(LOCAL_IDENTITY, v, F, invariants, 'local', TEMPLATE)
    return {'plan': v, 'arm': arm, 'source_sha': 'a' * 40, 'binding': binding, 'binding_sha256': m.digest(binding),
            'runtime_before': copy.deepcopy(invariants), 'runtime_after': copy.deepcopy(invariants),
            'events': events, 'samples': samples, 'environment': environment, 'healthy_classification': True,
            'tls': True if environment == 'azure' else m.LOCAL_TLS, 'native_auth': True,
            'guards': {k: {'observed': True, 'competing_bottleneck': False, 'start': 0, 'end': 10, 'evidence_sha256': 'b' * 64} for k in m.GUARDS},
            'accounting': {'classes': counts, 'classifier_escapes': 0, 'dropped_logs': 0, 'counter_lifetime_unchanged': True,
                           'frontend': len(scheduled), 'queue_start': 0, 'queue_end': 0, 'inflight_start': 0, 'inflight_end': 0, 'haproxy_retries': 0}}


def managed(run, times=(-1, 5, 11)):
    """Harness-projected managed rows for the run's actual UID/pool series (synthetic).

    A managed counter follows the native trajectory: zero until the drained boundary at t=10.
    """
    final = {t['uid']: t['stats'] for t in run['samples'][-1]['targets']}
    return [{'at': at, 'sample_at': at, 'targets': [
        {'uid': t['uid'], 'pool': t['pool'], 'sample_at': at,
         'stats': {k: final[t['uid']][k] if at >= 10 and k in m.COUNTERS else 0 for k in m.STATS}}
        for t in run['samples'][0]['targets']]} for at in times]


def azure(arm, **overrides):
    r = synthetic(arm, 'azure'); r['managed_samples'] = managed(r); r['managed_clock'] = copy.deepcopy(CLOCK)
    return r | overrides


def burst(run, active, until=.25):
    """Native cadence rows stay; 200 extra snapshots land inside the first 0.2s."""
    for s in run['samples']:
        if s['at'] > until:
            for t in s['targets']: t['stats']['upstream_rq_active'] = 0
    extra = []
    for i in range(1, 201):
        targets = copy.deepcopy(run['samples'][0]['targets'])
        for t in targets: t['stats']['upstream_rq_active'] = active if t['pool'] != 'critical' else 0
        extra.append({'at': i * .001, 'sample_at': i * .001, 'targets': targets})
    run['samples'] = sorted(run['samples'] + extra, key=lambda s: s['sample_at'])
    return run

# Captured from the pinned HAProxy 3.4.6 (isolated arm, 1 critical + 2 bulk + 1 denied request).
REAL_RING = """{"status":200,"termination":"--","class":"critical","backend":"critical","server":"pool","request_counter":0,"pid":8,"accept_time":"1793875738.660","queue_ms":0,"connect_ms":1,"response_ms":26,"total_ms":27}
{"status":200,"termination":"--","class":"bulk","backend":"bulk","server":"pool","request_counter":1,"pid":8,"accept_time":"1793875738.691","queue_ms":0,"connect_ms":0,"response_ms":2,"total_ms":2}
{"status":200,"termination":"--","class":"bulk","backend":"bulk","server":"pool","request_counter":2,"pid":8,"accept_time":"1793875738.702","queue_ms":0,"connect_ms":0,"response_ms":1,"total_ms":1}
{"status":403,"termination":"PR","class":"deny","backend":"check","server":"<NOSRV>","request_counter":3,"pid":8,"accept_time":"1793875738.704","queue_ms":-1,"connect_ms":-1,"response_ms":-1,"total_ms":0}
"""
REAL_STATS = """# pxname,svname,qcur,qmax,scur,smax,stot,econ,eresp,wretr,wredis,status,hrsp_2xx,hrsp_3xx,hrsp_4xx,hrsp_5xx,hrsp_other,req_tot,cli_abrt,srv_abrt
check,FRONTEND,,,0,1,4,,,,,OPEN,3,0,1,0,0,4,,
critical,pool,0,0,0,1,1,0,0,0,0,no check,1,0,0,0,0,1,0,0
critical,BACKEND,0,0,0,1,1,0,0,0,0,UP,1,0,0,0,0,1,0,0
bulk,pool,0,0,0,1,2,0,0,0,0,no check,2,0,0,0,0,2,0,0
bulk,BACKEND,0,0,0,1,2,0,0,0,0,UP,2,0,0,0,0,2,0,0
local_stats,FRONTEND,,,1,1,1,,,,,OPEN,0,0,0,0,0,1,,
local_stats,BACKEND,0,0,0,0,0,0,0,0,0,UP,0,0,0,0,0,0,0,0
"""
REAL_INFO = """Name: HAProxy
Version: 3.4.6-56332c5
Nbthread: 1
Nbproc: 1
Process_num: 1
Pid: 8
Uptime: 0d 0h00m02s
Uptime_sec: 2
Maxconn: 256
Hard_maxconn: 256
CumReq: 6
DroppedLogs: 0
Start_time_sec: 1793875710
MaxconnReached: 0
"""
# Captured from the live shared arm in the Local cluster: the kubelet TCP probe connects and closes without a request.
PROBE_ROW = '{"status":400,"termination":"CR","class":"-","backend":"check","server":"<NOSRV>","request_counter":0,"pid":8,"accept_time":"1793877364.645","queue_ms":-1,"connect_ms":-1,"response_ms":-1,"total_ms":0}'
STATS_HEADER = REAL_STATS.splitlines()[0]


def ring_row(kind, status, arm, index, queue=0, termination='--', pid=8):
    return {'status': status, 'termination': termination, 'class': kind, 'backend': 'shared' if arm == 'shared' else kind, 'server': 'pool',
            'request_counter': index, 'pid': pid, 'accept_time': '1793875738.%03d' % (index % 1000), 'queue_ms': queue,
            'connect_ms': 0, 'response_ms': 5, 'total_ms': 5}


def stats_text(rows, arm):
    """HAProxy CSV whose counters follow the cumulative ring rows (real header columns).

    As in the real process, the frontend counts every logged request (including the no-request 400s) while a
    backend counts only requests it served.
    """
    def line(name, side, mine):
        ok = lambda lo, hi: sum(lo <= r['status'] < hi for r in mine)
        return '%s,%s,0,0,0,1,%d,0,0,0,0,UP,%d,0,%d,%d,0,%d,0,0' % (name, side, len(mine), ok(200, 300), ok(400, 500), ok(500, 600), len(mine))
    lines = [STATS_HEADER, 'check,FRONTEND,,,0,1,%d,,,,,OPEN,%d,0,%d,%d,0,%d,,' % (
        len(rows), sum(r['status'] == 200 for r in rows), sum(400 <= r['status'] < 500 for r in rows), sum(r['status'] >= 500 for r in rows), len(rows))]
    for pool in (('shared',) if arm == 'shared' else m.CLASSES):
        lines.append(line(pool, 'BACKEND', [r for r in rows if r['backend'] == pool and r['class'] != '-']))
    return '\n'.join(lines) + '\n'


def observation(arm, outcomes, warmup=3):
    """Consistent multi-source observations for [(kind, status)] checks after `warmup` earlier ones (synthetic)."""
    pool = lambda kind: 'shared' if arm == 'shared' else kind
    targets = [{'uid': 'u0', 'pool': pool('critical')}, {'uid': 'u1', 'pool': pool('bulk')}]
    early = [ring_row('critical' if i == 0 else 'bulk', 200, arm, i) for i in range(warmup)]
    rows = [ring_row(kind, status, arm, warmup + i) for i, (kind, status) in enumerate(outcomes)]
    pod = {'critical': 'u0', 'bulk': 'u1'}
    target_rows = {'u0': [], 'u1': []}; app = {'u0': [], 'u1': []}; ingress = []
    for i, (kind, status) in enumerate(outcomes):
        uid = pod[kind] if arm == 'isolated' else 'u%d' % (i % 2)
        target_rows[uid].append({'status': status, 'details': 'via_upstream' if status == 200 else 'upstream_reset_before_response_started{overflow}'})
        ingress.append({'status': 200 if status == 200 else 403, 'details': 'via_upstream' if status == 200 else 'ext_authz_error'})
        if status == 200:
            app[uid].append({'operation_id': '%s-%d' % (kind, i), 'decision': 'ALLOW'})
    info = lambda n: {'Pid': 8, 'Start_time_sec': 1793875710, 'Uptime_sec': 3 + n, 'Nbthread': 1, 'Nbproc': 1, 'Maxconn': 256,
                      'DroppedLogs': 0, 'MaxconnReached': 0}
    return {'ring_before': early, 'ring_after': early + rows, 'info_before': info(0), 'info_after': info(130),
            'stats_before': m.parse_haproxy_stats(stats_text(early, arm)), 'stats_after': m.parse_haproxy_stats(stats_text(early + rows, arm)),
            'client_requests': {k: sum(kind == k for kind, _ in outcomes) for k in m.CLASSES}, 'ingress_rows': ingress,
            'target_rows': target_rows, 'app_checks': app, 'targets': targets}


def prometheus(pods, stamps, trajectory, namespace='shared-gate', **drop):
    """Prometheus HTTP API range-vector response (raw scrape samples; each Pod has its own scrape phase)."""
    result = []
    for pod in pods:
        for name, key in sorted(m.MANAGED_METRICS.items()):
            if drop.get('metric') == (pod['name'], key): continue
            result.append({'metric': {'__name__': name, 'envoy_cluster_name': 'inbound|8080||', 'job': 'p10-envoy', 'namespace': namespace,
                                      'pod': pod['name'], 'container': 'istio-proxy', 'instance': '10.42.0.%d:15090' % len(result)},
                           'values': [[1000 + t, str(trajectory(pod['uid'], key, t))] for t in stamps[pod['uid']]]})
    return {'status': 'success', 'data': {'resultType': 'matrix', 'result': result}}


class IsolationTests(unittest.TestCase):
    def test_selected_local_istioctl_camel_case_filter_contract(self):
        spec = importlib.util.spec_from_file_location('p10_local', ROOT / 'scripts/local-isolation-check.py')
        local = importlib.util.module_from_spec(spec); spec.loader.exec_module(local)
        config = {'allowedHeaders': {'patterns': [{'exact': h} for h in ('x-operation-id', 'x-attempt-id', 'x-gate-test-deny')]},
                  'httpService': {'serverUri': {'cluster': 'outbound|8080||haproxy.shared-gate.svc.cluster.local'},
                                  'authorizationRequest': {'headersToAdd': [{'key': 'authorization', 'value': 'p4-check-without-credentials'}]}}}
        listeners = [{'filterChains': [{'filters': [{'typedConfig': {'httpFilters': [
            {'name': 'envoy.filters.http.ext_authz', 'typedConfig': config}]}}]}]}]
        self.assertEqual(local.effective_check(listeners), [config])
        for change in ({'withRequestBody': {'maxRequestBytes': 1}}, {'failureModeAllow': True},
                       {'httpService': config['httpService'] | {'pathPrefix': '/auth'}}):
            bad = copy.deepcopy(listeners)
            bad[0]['filterChains'][0]['filters'][0]['typedConfig']['httpFilters'][0]['typedConfig'].update(change)
            with self.assertRaises(ValueError): local.effective_check(bad)

    def test_local_haproxy_swap_waits_for_actual_ingress_endpoint(self):
        spec = importlib.util.spec_from_file_location('p10_local', ROOT / 'scripts/local-isolation-check.py')
        local = importlib.util.module_from_spec(spec); spec.loader.exec_module(local)
        ready = {'type': 'Ready', 'status': 'True'}
        new = {'metadata': {}, 'status': {'podIP': '10.0.0.2', 'conditions': [ready]}}
        old = {'metadata': {'deletionTimestamp': 'x'}, 'status': {'podIP': '10.0.0.1', 'conditions': [ready]}}
        def clusters(ip, health='HEALTHY'):
            return {'cluster_statuses': [{'name': local.HAPROXY_CLUSTER, 'host_statuses': [
                {'address': {'socket_address': {'address': ip, 'port_value': 8080}}, 'health_status': {'eds_health_status': health}}]}]}
        def run(states):
            states = iter(states); current = {}; marks = []
            def kube(*args):
                if 'pods' in args:
                    current.update(next(states)); return json.dumps({'items': current['pods']})
                return json.dumps(current['clusters'])
            with mock.patch.object(local, 'k', kube), mock.patch.object(local.time, 'sleep'), \
                    mock.patch.object(local.gate, 'pod', lambda _l: {'metadata': {'name': 'ingress'}}):
                local.converge(lambda phase, **safe: marks.append((phase, safe)))
            return marks
        marks = run([{'pods': [old, new], 'clusters': clusters('10.0.0.1')},
                     {'pods': [new], 'clusters': clusters('10.0.0.2', 'UNHEALTHY')},
                     {'pods': [new], 'clusters': clusters('10.0.0.2')}])
        self.assertEqual(marks[-1][0], 'haproxy-converged')
        with self.assertRaises(ValueError):
            run([{'pods': [new], 'clusters': clusters('10.0.0.1')}] * 60)

    def test_exact_routes_no_identity_or_header_inputs(self):
        for kind, pairs in m.routes(F).items():
            for method, uri in pairs:
                self.assertEqual(m.classify(method, uri, F), kind)
                for altered in [uri + '/', uri + '&token=x', uri + '?', uri.upper(), uri.replace('/', '//', 1),
                                'https://example.org' + uri, uri + '#x', uri.replace('/journey', '/%6aourney')]:
                    self.assertEqual(m.classify(method, altered, F), 'deny')
        critical = m.routes(F)['critical'][0][1]
        for method in ('POST', 'HEAD', 'OPTIONS', 'get', 'PUT', 'DELETE'):
            self.assertEqual(m.classify(method, critical, F), 'deny')
        for uri in ('/api/v1/repos/fixture/journey/./issues/1', '/api/v1/repos/fixture/journey/%2e/issues/1',
                    '/api/v1/repos/fixture/journey/issues/01', critical + '?priority=critical'):
            self.assertEqual(m.classify('GET', uri, F), 'deny')

    def test_untrusted_fixture_values_cannot_inject_haproxy(self):
        for owner in ('../fixture', 'fixture\nbackend injected', 'Fixture', 'fixture?x', 'x' * 41):
            with self.assertRaises(ValueError): m.haproxy(F | {'owner': owner}, 'shared')

    def test_topology_same_total_capacity_no_controller_or_stable_resource(self):
        configs = []
        for arm in m.ARMS:
            r = m.render(t8.identity(), plan(), F, arm)
            items = r['fixtures.json']['items']
            targets = [o for o in items if o['kind'] == 'Deployment' and o['metadata']['name'].startswith('ext-authz-')]
            self.assertEqual(sum(t['spec']['replicas'] for t in targets), 2)
            self.assertEqual(len(targets), 1 if arm == 'shared' else 2)
            self.assertFalse(any(o['kind'] in {'HorizontalPodAutoscaler', 'ScaledObject', 'EnvoyFilter', 'PersistentVolumeClaim', 'Gateway', 'VirtualService'} for o in items))
            self.assertEqual(r['policy.json'], m.p8.render(t8.identity())['policy.json'])
            monitors = [o for o in items if o['kind'] == 'PodMonitor']
            self.assertEqual(len(monitors), 1)
            self.assertEqual(monitors[0]['spec']['selector']['matchLabels'], {'app': 'ext-authz-sim'})
            self.assertEqual(monitors[0]['spec']['podMetricsEndpoints'][0]['interval'], '15s')
            configs += [t['spec']['template']['spec']['containers'][0] for t in targets]
            hp = m.haproxy(F, arm)
            self.assertIn('retries 0', hp)
            self.assertNotIn('req.hdr', hp)
            self.assertNotIn('src ', hp)
        self.assertTrue(all(c == configs[0] for c in configs))

    def test_cross_arm_actual_image_or_resource_drift_invalid(self):
        for field in ('image_id', 'resources_sha256'):
            a, b = synthetic('shared'), synthetic('isolated')
            for sample in b['samples']:
                for target in sample['targets']: target[field] = 'd' * 64
            with self.assertRaises(ValueError): m.compare(a, b)

    def test_schedule_identical_counts_separate_operations(self):
        s = m.schedule(plan())
        self.assertEqual(len(s), 540)
        self.assertEqual(sum(r['kind'] == 'critical' for r in s), 60)
        self.assertEqual(len({r['id'] for r in s}), 540)

    def test_positive_and_valid_negative_are_distinct(self):
        a, b = synthetic('shared'), synthetic('isolated')
        self.assertEqual(m.compare(a, b)['status'], 'positive')
        # All critical attempts succeed in the shared pool, without changing demand.
        for row in a['events']:
            if row['record'] == 'operation' and row['kind'] == 'critical':
                row['attempts'][0].update(semantic_result=True, error_class='none', status=200)
        c = a['accounting']['classes']['critical']
        c['admitted'] = c['app'] = c['checks']; c['rejected'] = 0
        for s in a['samples']:
            if s['at'] >= 10:
                s['targets'][0]['stats']['upstream_rq_total'] = c['checks']
                s['targets'][0]['stats']['upstream_rq_active_overflow'] -= c['checks']
        self.assertEqual(m.compare(a, b)['status'], 'valid-negative')

    def test_observation_insufficient_not_negative_or_zero(self):
        a, b = synthetic('shared'), synthetic('isolated')
        a['samples'] = [s for s in a['samples'] if s['at'] < 1 or s['at'] > 9]
        self.assertEqual(m.compare(a, b)['status'], 'observation-insufficient')
        b = azure('isolated'); b['managed_samples'] = []
        with self.assertRaises(ValueError): m.validate(b)
        # Only a structurally valid managed series with a coverage gap is insufficient.
        b['managed_samples'] = managed(b, (-1, 10, 50))
        self.assertEqual(m.validate(b)['status'], 'observation-insufficient')
        a, b = azure('shared'), azure('isolated')
        a['managed_samples'] = managed(a, (-1, 5, 50))
        self.assertEqual(m.compare(a, b)['status'], 'observation-insufficient')

    def test_local_tls_is_never_asserted_and_azure_requires_it(self):
        for tls in (True, False, None, 'local-https'):
            r = synthetic('shared'); r['tls'] = tls
            with self.assertRaises(ValueError): m.validate(r)
        r = azure('shared'); r['tls'] = m.LOCAL_TLS
        with self.assertRaises(ValueError): m.validate(r)
        self.assertEqual(m.validate(synthetic('shared'))['status'], 'valid')
        # A Local binding cannot masquerade as Azure, nor an Azure identity as Local.
        r = synthetic('shared'); r['environment'] = 'azure'; r['tls'] = True; r['managed_samples'] = managed(r); r['managed_clock'] = CLOCK
        with self.assertRaises(ValueError): m.validate(r)
        r = azure('shared'); r['environment'] = 'local'; r['tls'] = m.LOCAL_TLS
        with self.assertRaises(ValueError): m.validate(r)

    def test_local_render_is_deterministic_same_template_two_topologies(self):
        v = plan()
        shared, isolated = (m.local_render(LOCAL_IDENTITY, v, F, arm, TEMPLATE) for arm in m.ARMS)
        again = m.local_render(LOCAL_IDENTITY, v, F, 'shared', copy.deepcopy(TEMPLATE))
        self.assertEqual(m.digest(shared), m.digest(again))
        self.assertNotEqual(m.digest(shared), m.digest(isolated))
        for arm, rendered in (('shared', shared), ('isolated', isolated)):
            items = rendered['pools.json']['items']
            deployments = [o for o in items if o['kind'] == 'Deployment']
            self.assertEqual(sum(o['spec']['replicas'] for o in deployments), 2)
            self.assertEqual(len(deployments), 1 if arm == 'shared' else 2)
            self.assertEqual({o['kind'] for o in items}, {'Deployment', 'Service', 'Sidecar'})
            sidecar = next(o for o in items if o['kind'] == 'Sidecar')
            self.assertEqual(sidecar['spec']['inboundConnectionPool']['http']['http2MaxRequests'], 2)
            self.assertEqual(sidecar['spec']['workloadSelector']['labels'], {'app': 'ext-authz-pool'})
            for o in deployments:   # one pod template for every pool; only the pool label differs
                pod = o['spec']['template']
                self.assertEqual(pod['spec'], {**TEMPLATE['spec'], 'terminationGracePeriodSeconds': 2}); self.assertEqual(pod['metadata']['annotations'], TEMPLATE['metadata']['annotations'])
                self.assertEqual(pod['metadata']['labels'], o['spec']['selector']['matchLabels'])
            self.assertIn('ext-authz-' + ('shared' if arm == 'shared' else 'critical') + '.shared-gate.svc.cluster.local', rendered['haproxy.cfg'])
        self.assertNotIn('ext-authz-critical', shared['haproxy.cfg'])
        # The template is part of the binding: changing it is source/demand drift.
        r = synthetic('shared'); r['binding']['template'] = {'metadata': {}, 'spec': {'containers': []}}; r['binding_sha256'] = m.digest(r['binding'])
        with self.assertRaises(ValueError): m.validate(r)

    def test_timestamp_only_or_unreconciled_managed_signal_never_positive_or_negative(self):
        a, b = azure('shared'), azure('isolated')
        self.assertEqual(m.compare(a, b)['status'], 'positive')
        for arm_index in range(2):
            for rows in ([{'at': i, 'sample_at': i} for i in (-.25, 0, 10)],
                         [{'at': i, 'sample_at': i, 'targets': []} for i in (-1, 5, 11)]):
                a, b = azure('shared'), azure('isolated')
                (a, b)[arm_index]['managed_samples'] = rows
                with self.assertRaises(ValueError): m.compare(a, b)
        mutations = [lambda r: r['targets'].pop(),
                     lambda r: r['targets'][0].update(uid='other-pod'),
                     lambda r: r['targets'][0].update(pool='bulk' if r['targets'][0]['pool'] != 'bulk' else 'critical'),
                     lambda r: r['targets'][0].pop('sample_at'),
                     lambda r: r['targets'][0].update(sample_at=float('nan')),
                     lambda r: r['targets'][0].update(sample_at=r['sample_at'] + 30),
                     lambda r: r['targets'][0]['stats'].pop('upstream_rq_active'),
                     lambda r: r['targets'][0]['stats'].pop('upstream_rq_total'),
                     lambda r: r['targets'][0]['stats'].update(upstream_rq_active=True),
                     lambda r: r['targets'][0]['stats'].update(upstream_rq_active=1.0),
                     lambda r: r['targets'][0]['stats'].update(upstream_rq_active=-1),
                     lambda r: r['targets'][0]['stats'].update(upstream_rq_active=3),   # above inbound capacity
                     lambda r: r['targets'][0]['stats'].update(extra=0),
                     lambda r: r['targets'][0]['stats'].update(upstream_rq_pending_overflow=1),
                     lambda r: r['targets'][0]['stats'].update(upstream_rq_pending_active=1),
                     lambda r: r.update(extra=0),
                     lambda r: r.update(sample_at=float('nan'))]
        for arm in m.ARMS:
            for index in (0, 1, 2):
                for mutation in mutations:
                    run = azure(arm); mutation(run['managed_samples'][index])
                    with self.assertRaises(ValueError): m.validate(run)
            # A counter that actually advanced in the native drained boundary.
            final = azure(arm)['samples'][-1]['targets']
            index, counter = next((i, c) for i, t in enumerate(final) for c in m.COUNTERS if t['stats'][c] > 0)
            full = final[index]['stats'][counter]
            def series(times, values):
                run = azure(arm); run['managed_samples'] = managed(run, times)
                for row, value in zip(run['managed_samples'], values): row['targets'][index]['stats'][counter] = value
                return run
            # Within the clock allowance of the native step (t=10) a snapshot may already show the drained value.
            self.assertEqual(m.validate(series((-1, 5, 8, 11), (0, 0, full, full)))['status'], 'valid')
            for run in (series((-1, 5, 8, 11), (0, 0, full, full - 1)),    # counter reset
                        series((-1, 5, 11), (0, 0, full + 1)),             # beyond the drained native counter
                        series((-1, 5, 11), (0, full, full)),              # ahead of the native trajectory at its own time
                        series((-1, 5, 13), (0, 0, full - 1)),             # drained boundary != native
                        series((-1, 5, 13), (0, 0, 0))):                   # stale zero after the drained boundary
                with self.assertRaises(ValueError): m.validate(run)
            # A clock offset the native bracket cannot absorb is invalid, not a quiet time shift.
            late = azure(arm); late['managed_samples'] = managed(late, (-1, 5, 11))
            for row in late['managed_samples']:
                row['sample_at'] -= 5
                for t in row['targets']: t['sample_at'] -= 5
            with self.assertRaises(ValueError): m.validate(late)

    def test_managed_clock_pair_and_step(self):
        pair = m.clock_pair(wall=iter([100.0, 100.1]).__next__, monotonic=lambda: 7.0)
        self.assertEqual(set(pair), {'wall', 'monotonic', 'uncertainty'})
        self.assertAlmostEqual(pair['wall'], 100.05); self.assertAlmostEqual(pair['uncertainty'], .05); self.assertEqual(pair['monotonic'], 7.0)
        self.assertAlmostEqual(m.to_monotonic(CLOCK, 1012.5), 12.5)
        self.assertGreater(m.clock_bound(CLOCK), m.MANAGED_CLOCK_TOLERANCE)
        for mutate in (lambda c: c['end'].update(wall=c['end']['wall'] + 1),            # wall clock stepped
                       lambda c: c['end'].update(monotonic=c['start']['monotonic']),    # not later
                       lambda c: c['start'].update(uncertainty=1),                      # unbracketed read
                       lambda c: c['start'].update(wall=float('nan')),
                       lambda c: c.pop('end')):
            clock = copy.deepcopy(CLOCK); mutate(clock)
            with self.assertRaises(ValueError): m.clock_bound(clock)
        run = azure('shared'); run['managed_clock']['end']['wall'] += 1
        with self.assertRaises(ValueError): m.validate(run)

    def test_oversampled_native_burst_cannot_create_saturation(self):
        # 0.25s of 10s is at cap. Row-count would report 202/241; elapsed-time must not.
        a, b = burst(azure('shared'), 2), burst(azure('isolated'), 2)
        rows = [s for s in a['samples'] if 0 <= s['sample_at'] <= 10]
        self.assertGreater(sum(any(t['stats']['upstream_rq_active'] >= 2 for t in s['targets']) for s in rows) / len(rows), .8)
        result = m.compare(a, b)
        self.assertEqual(result['status'], 'valid-negative')
        self.assertFalse(result['bulk_saturation'])
        self.assertAlmostEqual(result['arms'][0]['saturation_fraction']['shared'], .0375)
        self.assertAlmostEqual(result['arms'][1]['saturation_fraction']['bulk'], .0375)
        # Burst of not-at-cap rows inside a fully saturated window must not hide it.
        a, b = burst(azure('shared'), 0, 10), burst(azure('isolated'), 0, 10)
        result = m.compare(a, b)
        self.assertEqual(result['status'], 'positive')
        self.assertGreaterEqual(result['arms'][1]['saturation_fraction']['bulk'], .95)

    def test_drift_missing_signal_early_stop_and_accounting_invalid(self):
        mutations = [lambda r: r['samples'][1]['targets'][0].update(uid='new'),
                     lambda r: r['samples'][1]['targets'][0].update(sidecar_id='restarted'),
                     lambda r: r['samples'][1]['targets'][0].update(endpoint_pod_uid='wrong-pod'),
                     lambda r: r['samples'][1]['targets'][0]['stats'].pop('upstream_rq_total'),
                     lambda r: r['accounting']['classes']['bulk'].update(checks=1),
                     lambda r: r['accounting'].update(classifier_escapes=1),
                     lambda r: r['guards']['postgres'].update(observed=False),
                     lambda r: r.update(native_auth=False),
                     lambda r: r['events'].pop(),
                     lambda r: r['events'][1].update(issued=None)]
        for mutation in mutations:
            r = synthetic('shared'); mutation(r)
            with self.assertRaises((ValueError, KeyError)): m.validate(r)

    def test_reset_demand_or_binding_drift_invalid(self):
        for mutate in (lambda r: r['binding'].update(source_sha='b' * 40),
                       lambda r: r['events'][0]['items'].pop(),
                       lambda r: r['samples'][-2]['targets'][0]['stats'].update(upstream_rq_total=99)):
            r = synthetic('shared'); mutate(r)
            with self.assertRaises(ValueError): m.validate(r)

    def test_real_driver_schedule_retry_and_sensitive_callback_projection(self):
        v = plan() | {'duration_seconds': 10, 'bulk_interval_seconds': 2, 'max_attempts': 2}
        rows = []
        def probe(op, index):
            time.sleep(.005)
            ok = index == 2 or op.startswith('bulk')
            return {'semantic_result': ok, 'status': 200 if ok else 403,
                    'error_class': 'none' if ok else 'http_status', 'overload': not ok,
                    'raw_credential': 'private-callback-sentinel'}
        m.drive(v, {k: probe for k in m.CLASSES}, rows.append)
        clients, _, _ = m.client_report(v, rows)
        self.assertEqual(clients['critical']['logical_operations'], 5)
        self.assertEqual(clients['critical']['attempts'], 10)
        self.assertEqual(clients['bulk']['attempts'], 5)
        self.assertNotIn('private-callback-sentinel', repr(rows))
        self.assertTrue(all(c['good_fraction'] == 1 for c in clients.values()))

    def test_native_denial_and_false_success_invalid(self):
        for status, semantic, error in ((404, False, 'http_status'), (200, False, 'semantic_error'), (403, True, 'none')):
            r = synthetic('shared')
            r['events'][1]['attempts'][0].update(status=status, semantic_result=semantic, error_class=error)
            with self.assertRaises(ValueError): m.validate(r)

    def test_last_completion_and_sample_timestamp_need_full_coverage(self):
        r = synthetic('shared')
        r['events'][1]['completed'] = 12
        with self.assertRaises(ValueError): m.validate(r)
        v = plan()
        # Late query responses alone cannot establish the end of the window.
        samples = [{'at': -.25, 'sample_at': -.25}, {'at': 120, 'sample_at': 119.75}]
        self.assertFalse(m.coverage(v, samples, 0, 120))

    def test_long_scrape_cannot_establish_second_scale_native_signal(self):
        v = plan()
        samples = [{'at': at, 'sample_at': at} for at in (-1, 0, 60, 120)]
        self.assertFalse(m.coverage(v, samples, 0, 120))
        self.assertFalse(m.coverage(v, samples, 0, 120, managed=True))

    def test_real_haproxy_output_parsers(self):
        rows = m.parse_ring(REAL_RING)
        self.assertEqual([r['class'] for r in rows], ['critical', 'bulk', 'bulk', 'deny'])
        self.assertEqual(rows[3]['server'], '<NOSRV>')
        stats = m.parse_haproxy_stats(REAL_STATS)
        self.assertEqual(stats['frontend']['check']['req_tot'], 4)
        self.assertIsNone(stats['frontend']['check']['econ'])                # not applicable to a frontend, never zero
        self.assertEqual((stats['backend']['bulk']['req_tot'], stats['backend']['bulk']['hrsp_2xx']), (2, 2))
        self.assertEqual(m.parse_haproxy_info(REAL_INFO), {'Pid': 8, 'Start_time_sec': 1793875710, 'Uptime_sec': 2, 'Nbthread': 1,
                                                          'Nbproc': 1, 'Maxconn': 256, 'DroppedLogs': 0, 'MaxconnReached': 0})
        first = json.loads(REAL_RING.splitlines()[0])
        for mutate in (lambda r: r.pop('class'), lambda r: r.update(extra=1), lambda r: r.update(status='200'), lambda r: r.update(status=True),
                       lambda r: r.update(**{'class': 'priority'}), lambda r: r.update(accept_time='1793875738'), lambda r: r.update(queue_ms=-2)):
            row = dict(first); mutate(row)
            with self.assertRaises(ValueError): m.parse_ring(json.dumps(row))
        with self.assertRaises(ValueError): m.parse_ring(REAL_RING + REAL_RING.splitlines()[0])   # duplicate request counter
        with self.assertRaises(ValueError): m.parse_ring('{"status":200')                           # truncated row
        with self.assertRaises(ValueError): m.parse_haproxy_info(REAL_INFO.replace('DroppedLogs: 0\n', ''))

    def test_tcp_probe_connections_are_not_checks_but_lookalikes_are_not_hidden(self):
        probe = m.parse_ring(PROBE_ROW)[0]
        self.assertTrue(m.no_request(probe))
        for change in ({'status': 403}, {'termination': 'PR'}, {'backend': 'shared'}, {'server': 'pool'}, {'queue_ms': 0}, {'class': 'critical'}):
            self.assertFalse(m.no_request(dict(probe, **change)))
        outcomes = [('critical', 200), ('bulk', 200), ('bulk', 503)]
        for arm in m.ARMS:
            obs = observation(arm, outcomes)
            # One probe connection before the idle boundary and one inside the window; HAProxy's request counters are unchanged.
            earlier = [dict(probe, request_counter=899)] + obs['ring_before']
            window = obs['ring_after'][len(obs['ring_before']):]
            obs['ring_before'], obs['ring_after'] = earlier, earlier + [window[0], dict(probe, request_counter=900)] + window[1:]
            obs['stats_before'], obs['stats_after'] = (m.parse_haproxy_stats(stats_text(r, arm)) for r in (obs['ring_before'], obs['ring_after']))
            evidence = m.window_accounting(arm, obs)
            self.assertEqual((evidence['no_request_connections'], evidence['frontend'], evidence['classifier_escapes']), (1, 3, 0))
            # The same row with any request-like attribute is an unexplained row, never absorbed.
            odd = observation(arm, outcomes); odd['ring_after'].append(dict(probe, request_counter=901, status=403))
            with self.assertRaises(ValueError): m.window_accounting(arm, odd)

    def test_window_accounting_conserves_independent_sources(self):
        outcomes = [('critical', 200), ('bulk', 200), ('bulk', 503), ('bulk', 503), ('critical', 503), ('bulk', 200)]
        for arm in m.ARMS:
            evidence = m.window_accounting(arm, observation(arm, outcomes))
            self.assertEqual({k: evidence['classes'][k]['checks'] for k in m.CLASSES}, {'critical': 2, 'bulk': 4})
            self.assertEqual({k: evidence['classes'][k]['rejected'] for k in m.CLASSES}, {'critical': 1, 'bulk': 2})
            self.assertEqual((evidence['classifier_escapes'], evidence['frontend'], evidence['dropped_logs']), (0, 6, 0))
            self.assertEqual({c['pool'] for c in evidence['classes'].values()}, {'shared'} if arm == 'shared' else {'critical', 'bulk'})
            # The same evidence is accepted by the run validator's accounting contract.
            clients = {k: {'attempts': evidence['classes'][k]['checks']} for k in m.CLASSES}
            self.assertEqual(set(m.accounting(arm, evidence, clients)), set(m.CLASSES))

    def test_window_accounting_rejects_unlogged_phantom_and_misrouted_checks(self):
        outcomes = [('critical', 200), ('bulk', 200), ('bulk', 503), ('critical', 503)]
        def broken(arm, mutate):
            obs = observation(arm, outcomes); mutate(obs); return obs
        for arm in m.ARMS:
            for mutate in (lambda o: o['ring_after'].pop(),                                     # a logged check lost from the ring (counters disagree)
                           lambda o: o.update(ring_before=o['ring_before'][:-1] + [dict(o['ring_before'][-1], status=500)]),   # ring rewritten
                           lambda o: o['ingress_rows'].pop(),
                           lambda o: o['target_rows']['u1'].pop() if o['target_rows']['u1'] else o['target_rows']['u0'].pop(),
                           lambda o: o['app_checks']['u0'].append({'operation_id': 'sentinel-1', 'decision': 'ALLOW'}),
                           lambda o: o['app_checks']['u1'].append({'operation_id': 'bulk-9', 'decision': 'DENY'}),
                           lambda o: o['stats_after']['frontend']['check'].update(req_tot=o['stats_after']['frontend']['check']['req_tot'] + 1),
                           lambda o: o['stats_after']['backend'][next(iter(o['stats_after']['backend']))].update(econ=1),
                           lambda o: o['client_requests'].update(critical=o['client_requests']['critical'] + 1)):
                with self.assertRaises(ValueError): m.window_accounting(arm, broken(arm, mutate))
            # Observed-but-forbidden outcomes are kept as evidence and fail accounting(), never absorbed.
            clients = lambda e: {k: {'attempts': e['classes'][k]['checks']} for k in m.CLASSES}
            queued = observation(arm, outcomes); queued['ring_after'][-1] = dict(queued['ring_after'][-1], queue_ms=40)
            queued['stats_after'] = m.parse_haproxy_stats(stats_text(queued['ring_after'], arm))
            evidence = m.window_accounting(arm, queued)
            self.assertEqual(sum(c['queue'] for c in evidence['classes'].values()), 1)
            with self.assertRaises(ValueError): m.accounting(arm, evidence, clients(evidence))
            for field, value in (('pid', 9), ('uptime', 0)):
                obs = observation(arm, outcomes)
                obs['info_after'] = dict(obs['info_after'], **({'Pid': 9} if field == 'pid' else {'Uptime_sec': 0}))
                evidence = m.window_accounting(arm, obs)
                self.assertFalse(evidence['counter_lifetime_unchanged'])
                with self.assertRaises(ValueError): m.accounting(arm, evidence, clients(evidence))
            dropped = observation(arm, outcomes); dropped['info_after'] = dict(dropped['info_after'], DroppedLogs=1)
            with self.assertRaises(ValueError): m.accounting(arm, m.window_accounting(arm, dropped), clients(evidence))
            other = observation(arm, outcomes)
            other['ring_after'][-1] = dict(other['ring_after'][-1], status=502, termination='SC')
            other['stats_after'] = m.parse_haproxy_stats(stats_text(other['ring_after'], arm))
            other['target_rows']['u0'] = other['target_rows']['u0'][:-1] if other['ring_after'][-1]['class'] == 'critical' else other['target_rows']['u0']
            with self.assertRaises(ValueError):
                evidence = m.window_accounting(arm, other)
                m.accounting(arm, evidence, clients(evidence))

    def test_mocked_prometheus_collector_projection_and_clock(self):
        a = azure('shared')
        pods = [{'name': 'ext-authz-shared-%s' % uid, 'uid': t['uid'], 'pool': t['pool']}
                for uid, t in ((t['uid'], t) for t in a['samples'][0]['targets'])]
        final = {t['uid']: t['stats'] for t in a['samples'][-1]['targets']}
        trajectory = lambda uid, key, t: final[uid][key] if t >= 10 and key in m.COUNTERS else 0
        stamps = {pods[0]['uid']: [-12, 3, 18, 33], pods[1]['uid']: [-5, 10, 25, 40]}   # two scrape phases, 15s apart
        calls = []
        def fetch(path, params):
            calls.append((path, params)); return prometheus(pods, stamps, trajectory)
        selector = m.managed_selector('shared-gate')
        self.assertIn('job="p10-envoy"', selector); self.assertIn('envoy_cluster_name="inbound|8080||"', selector)
        poll = m.poll_managed(fetch, selector, 600, clock=lambda: 125.0)
        self.assertEqual(calls, [('/api/v1/query', {'query': selector + '[600s]'})])     # raw samples, not evaluation steps
        self.assertEqual(poll['at'], 125.0)
        rows = m.project_managed([poll], pods, CLOCK, namespace='shared-gate', scrape_seconds=15)
        self.assertEqual(len(rows), 4)
        for row in rows:
            self.assertEqual({t['uid']: t['pool'] for t in row['targets']}, {p['uid']: p['pool'] for p in pods})   # inventory, not series labels
            self.assertEqual(row['sample_at'], max(t['sample_at'] for t in row['targets']))
            self.assertEqual(row['at'], 125.0)
        self.assertAlmostEqual(rows[0]['targets'][0]['sample_at'], -12.0)           # wall 1000 -> monotonic 0
        # Late ingestion is measured per sample: a later poll never makes an earlier-visible sample fresher.
        early = {'at': 20.0, 'data': prometheus(pods, {u: [t for t in ts if t <= 3] for u, ts in stamps.items()}, trajectory)}
        again = m.project_managed([early, poll], pods, CLOCK, namespace='shared-gate', scrape_seconds=15)
        self.assertEqual([r['at'] for r in again], [20.0, 125.0, 125.0, 125.0])
        # Harness-projected rows pass the run validator when polling observed each sample soon after it was stamped.
        polls = [{'at': 20.0, 'data': prometheus(pods, {u: [x for x in ts if x <= 18] for u, ts in stamps.items()}, trajectory)},
                 {'at': 45.0, 'data': prometheus(pods, stamps, trajectory)}]
        a['managed_samples'] = m.project_managed(polls, pods, CLOCK, namespace='shared-gate', scrape_seconds=15)
        self.assertEqual([r['at'] for r in a['managed_samples']], [20.0, 20.0, 45.0, 45.0])
        self.assertEqual(m.validate(a)['status'], 'valid')
        # Too-late visibility is a freshness gap (insufficient), not a value.
        slow = copy.deepcopy(a); slow['managed_samples'] = m.project_managed([dict(poll, at=500.0)], pods, CLOCK, namespace='shared-gate', scrape_seconds=15)
        self.assertEqual(m.validate(slow)['status'], 'observation-insufficient')
        # A scrape round some Pod lacks leaves a gap; it is never filled with zero.
        gap = {pods[0]['uid']: [-12, 3, 18, 33], pods[1]['uid']: [-5, 40]}
        thin = m.project_managed([{'at': 125.0, 'data': prometheus(pods, gap, trajectory)}], pods, CLOCK, namespace='shared-gate', scrape_seconds=15)
        self.assertLess(len(thin), len(rows))
        c = copy.deepcopy(a); c['managed_samples'] = thin
        self.assertEqual(m.validate(c)['status'], 'observation-insufficient')

    def test_mocked_prometheus_structural_failures_are_invalid(self):
        a = azure('isolated')
        pods = [{'name': 'ext-authz-%s-x' % t['pool'], 'uid': t['uid'], 'pool': t['pool']} for t in a['samples'][0]['targets']]
        trajectory = lambda uid, key, t: 0
        stamps = {p['uid']: [0, 15, 30] for p in pods}
        def project(response, inventory=pods, **kw):
            return m.project_managed([{'at': 60.0, 'data': response}], inventory, CLOCK, namespace='shared-gate', scrape_seconds=15, **kw)
        self.assertEqual(len(project(prometheus(pods, stamps, trajectory))), 3)
        good = lambda: prometheus(pods, stamps, trajectory)
        def edit(fn):
            r = good(); fn(r['data']['result']); return r
        for response in (
                {'status': 'error', 'data': {}},
                {'status': 'success', 'data': {'resultType': 'vector', 'result': []}},
                prometheus([], {}, trajectory),                                                          # empty result: not zero
                prometheus(pods[:1], stamps, trajectory),                                                # one Pod's series absent
                prometheus(pods, stamps, trajectory, metric=(pods[1]['name'], 'upstream_rq_total')),     # partial scrape
                edit(lambda rs: rs[0]['metric'].update(pod='someone-else')),                             # unmapped Pod
                edit(lambda rs: rs[0]['metric'].update(envoy_cluster_name='outbound|8080||x')),
                edit(lambda rs: rs[0]['metric'].update(namespace='other')),
                edit(lambda rs: rs[0]['metric'].update(job='other')),
                edit(lambda rs: rs[0]['metric'].update(__name__='envoy_cluster_upstream_cx_total')),
                edit(lambda rs: rs[0]['values'].__setitem__(0, [1000, 'NaN'])),
                edit(lambda rs: rs[0]['values'].__setitem__(0, [1000, '-1'])),
                edit(lambda rs: rs[0]['values'].__setitem__(0, [1000, '1.5'])),
                edit(lambda rs: rs[0]['values'].__setitem__(0, [1000, 3])),
                edit(lambda rs: rs[0]['values'].__setitem__(0, [float('nan'), '0'])),
                edit(lambda rs: rs.append(dict(rs[0], values=[[1000, '7']])))):                          # same sample, different value
            with self.assertRaises((ValueError, KeyError)): project(response)
        with self.assertRaises(ValueError): project(good(), pods + [dict(pods[0])])                    # duplicate inventory
        with self.assertRaises(ValueError): project(good(), [dict(p, extra=1) for p in pods])
        # A rewritten sample across polls (same Pod/time, different value) is invalid.
        later = prometheus(pods, stamps, lambda uid, key, t: 1 if t == 15 and key == 'upstream_rq_total' else 0)
        with self.assertRaises(ValueError):
            m.project_managed([{'at': 60.0, 'data': good()}, {'at': 70.0, 'data': later}], pods, CLOCK, namespace='shared-gate', scrape_seconds=15)

    def test_managed_visibility_is_not_required_before_the_window(self):
        v = plan()
        # Samples bracket the window; they only became visible after ingestion (within scrape+ingestion).
        rows = [{'at': t + 40, 'sample_at': t} for t in (-5, 10, 25, 40, 55, 70, 85, 100, 115, 125)]
        self.assertTrue(m.coverage(v, rows, 0, 120, managed=True))
        self.assertFalse(m.coverage(v, [dict(r, at=r['sample_at'] + 76) for r in rows], 0, 120, managed=True))   # beyond scrape+ingestion
        self.assertFalse(m.coverage(v, [dict(r, at=r['sample_at'] - 1) for r in rows], 0, 120, managed=True))    # visible before sampled
        self.assertFalse(m.coverage(v, rows[1:], 0, 120, managed=True))                                            # window start not bracketed
        # Native samples must also have been received inside the window.
        native = [{'at': t + .01, 'sample_at': t} for t in [i * .25 - .25 for i in range(0, 483)]]
        self.assertTrue(m.coverage(v, native, 0, 120))
        self.assertFalse(m.coverage(v, [dict(r, at=r['at'] + 1) for r in native[:1]] + native[1:], 0, 120))


if __name__ == '__main__': unittest.main()
