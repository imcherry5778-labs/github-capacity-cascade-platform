"""Cost-free P9 safety, schedule, ownership and recovery boundary regressions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import tarfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mitigation', ROOT / 'scripts/azure-mitigation.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
spec8 = importlib.util.spec_from_file_location('p8_test', ROOT / 'tests/e2e/test-azure-cascade.py')
t8 = importlib.util.module_from_spec(spec8); spec8.loader.exec_module(t8)


def plan():
    v = m.load(ROOT / 'experiments/fixtures/shared-gate/mitigation-candidate.json')
    return v | {'identity_client_id': 'a' * 8 + '-aaaa-aaaa-aaaa-' + 'a' * 12}


def approval():
    identity, v = t8.identity(), plan()
    return {'source_sha': identity['source_sha'], 'identity': identity, 'plan_sha256': m.digest(v), 'approved': True,
            'approval_url': 'https://github.com/example/repo/pull/1#issuecomment-1', 'normal_test_passed': True,
            'healthy_gate_passed': True, 'runtime_preflight_passed': True,
            'limits': {'calibration': 2, 'measured_per_arm': 1, 'pod': 4, 'cpu_m': 1500, 'memory_mi': 2048}}


def events(v=None):
    v = v or plan()
    items = m.schedule(v)
    e = [{'record': 'schedule', 'origin': 0, 'items': items, 'sha256': m.digest(items)},
         {'record': 'release', 'at': v['mitigation_seconds']},
         {'record': 'convergence', 'at': v['mitigation_seconds'] + 1, 'healthy': True}]
    for item in items:
        at = item['at']
        e.append({'record': 'operation', **item, 'scheduled': at, 'issued': at, 'completed': at + .05,
                  'outcome': 'completed', 'backoff_seconds': 0, 'attempts': [
                      {'index': 1, 'started': at, 'ended': at + .05, 'semantic_result': True,
                       'error_class': 'none', 'status': 200, 'duration_seconds': .05}]})
    return e


class PlanTests(unittest.TestCase):
    def test_four_arms_only_allowed_delta_and_same_demand(self):
        identity, v = t8.identity(), plan()
        rendered = {a: m.render(identity, v, a) for a in m.ARMS}
        self.assertEqual(rendered['C0'], rendered['C1'])
        hp = lambda a: next(o['data']['haproxy.cfg'] for o in rendered[a]['fixtures.json']['items'] if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'haproxy')
        self.assertIn('maxconn 2 maxqueue 12', hp('C2'))
        self.assertIn('timeout queue 250ms', hp('C2'))
        self.assertNotIn('maxconn', hp('C0'))
        self.assertEqual(hp('C0'), hp('C3'))
        c3 = rendered['C3']['fixtures.json']['items']
        self.assertNotIn('HorizontalPodAutoscaler', {o['kind'] for o in c3})
        self.assertEqual(next(o['spec']['maxReplicaCount'] for o in c3 if o['kind'] == 'ScaledObject'), 2)
        self.assertEqual(len(m.schedule(v)), 1800)
        with self.assertRaises(ValueError): m.render(identity, v, 'C4')

    def test_exact_hostname_and_resource_boundary_reused(self):
        for arm in m.ARMS:
            r = m.render(t8.identity(), plan(), arm)
            hosts = r['policy.json']['spec']['rules'][0]['to'][0]['operation']['hosts']
            self.assertEqual(hosts, ['forgejo.example.com', 'forgejo.example.com:443'])
            quota = next(o for o in r['fixtures.json']['items'] if o['kind'] == 'ResourceQuota')['spec']['hard']
            self.assertEqual(quota['pods'], '4'); self.assertEqual(quota['limits.cpu'], '1500m')
        for hostname in ('*', '*.example.com', 'other.example.com/evil'):
            with self.assertRaises(ValueError): m.render(t8.identity() | {'forgejo_hostname': hostname}, plan(), 'C0')
        # Actual injected native sidecars/init exceed source estimates -> fail.
        pod = {'metadata': {'name': 'hp', 'uid': 'hp', 'namespace': m.NS, 'labels': {'p8.campaign': t8.identity()['campaign']}},
               'spec': {'containers': [{'name': 'hp', 'resources': {'requests': {'cpu': '2', 'memory': '1Gi'}, 'limits': {'cpu': '2', 'memory': '1Gi'}}}]}}
        with self.assertRaises(ValueError): m.p8.admission(t8.identity(), [pod])

    def test_calibration_bounds_and_freeze(self):
        v, identity = plan(), t8.identity()
        for delta in ({'mitigation_seconds': 610}, {'recovery_seconds': 20}, {'threshold': 10}, {'queue_limit': 100}, {'backoff_ms': [0, 10000]}, {'freshness_seconds': 1}):
            with self.assertRaises(ValueError): m.plan(v | delta)
        calibration = {'source_sha': identity['source_sha'], 'plan_sha256': m.digest(v), 'reviewed': True,
                       'missing_required_signals': [], 'cadence_observed': True, 'all_pod_series_observed': True,
                       'counter_semantics': 'per-pod-active-overflow-counter-rate-per-second', 'controller_ownership_verified': True, 'metric_contract': m.metric_contract(),
                       'transport': m.p8.p7.operations.transport('https://forgejo.example.com', 'azure-aks', None), 'fixture_sha256': 'a' * 64}
        f = m.frozen(identity, v, [calibration])
        self.assertEqual(f['schedule_sha256'], m.digest(m.schedule(v)))
        for values in ([], [calibration] * 3, [calibration | {'cadence_observed': False}], [calibration | {'missing_required_signals': ['pod2']}]):
            with self.assertRaises(ValueError): m.frozen(identity, v, values)

    def test_explicit_p9_not_p8_approval_and_retention_reserve(self):
        identity, v = t8.identity(), plan()
        now = m.datetime(2026, 10, 29, tzinfo=m.timezone.utc)
        with patch.dict(os.environ, {'P8_AZURE_APPROVED': identity['source_sha']}, clear=True), patch.object(m.p8.p7, 'command') as command:
            with self.assertRaises(ValueError): m.Runtime(identity, v, 'C0', approval(), [])
            command.assert_not_called()
        with patch.dict(os.environ, {'P9_AZURE_APPROVED': identity['source_sha']}, clear=True):
            m.execution_gate(identity, v, approval(), [], now)
            with self.assertRaises(ValueError): m.execution_gate(identity, v, approval(), [], m.DEADLINE - m.timedelta(minutes=20))
            for delta in ({'approved': False}, {'runtime_preflight_passed': False}, {'source_sha': 'f' * 40}, {'identity': identity | {'forgejo_hostname': 'other.example.com'}}):
                with self.assertRaises(ValueError): m.execution_gate(identity, v, approval() | delta, [], now)
            entry = {'source_sha': identity['source_sha'], 'plan_sha256': m.digest(v), 'phase': 'measured', 'arm': 'C0'}
            with self.assertRaises(ValueError): m.execution_gate(identity, v, approval(), [entry] * 2, now)
            with self.assertRaises(ValueError): m.execution_gate(identity, v, approval(), [entry | {'phase': 'calibration'}] * 3, now)

    def test_backoff_deterministic_bounded_and_native_denial_not_retryable(self):
        v, item = plan(), m.schedule(plan())[0]
        self.assertEqual(m.retry_delay(v, 'C0', item), 0)
        d = m.retry_delay(v, 'C1', item)
        self.assertTrue(.25 <= d <= .75)
        self.assertEqual(d, m.retry_delay(v, 'C1', item))
        self.assertFalse(m.retryable({'status': 403, 'semantic_result': False}))
        self.assertFalse(m.retryable({'status': 401, 'semantic_result': False, 'overload': True}))


class OwnershipTelemetryTests(unittest.TestCase):
    def test_controller_switch_and_return_fail_closed(self):
        hpa = {'metadata': {'name': 'hpa-app-cpu'}, 'spec': {'scaleTargetRef': {'name': 'ext-authz-sim'}, 'minReplicas': 1, 'maxReplicas': 2}}
        scaled = {'metadata': {'name': m.HPA, 'uid': 'so'}, 'spec': {'scaleTargetRef': {'name': 'ext-authz-sim'}}}
        generated = copy.deepcopy(hpa); generated['metadata'] = {'name': m.HPA, 'ownerReferences': [{'kind': 'ScaledObject', 'uid': 'so', 'controller': True}]}
        m.controller_guard('C0', [hpa], [])
        m.controller_guard('C3', [generated], [scaled])
        for arm, hpas, sos in [('C3', [hpa, generated], [scaled]), ('C0', [generated], [scaled]), ('C3', [generated], []), ('C0', [], [])]:
            with self.assertRaises(ValueError): m.controller_guard(arm, hpas, sos)
        for target in ('C0', 'C3'):
            with tempfile.TemporaryDirectory() as d:
                m.transition(t8.identity(), plan(), target, Path(d) / 'plan.json', approval())
                steps = m.load(Path(d) / 'plan.json')['steps']
                self.assertIn('delete', steps[0]); self.assertTrue(steps[0]['wait_absent'])
                self.assertIn('zero HPA/ScaledObject', str(steps))

    def test_missing_stale_error_nan_partial_pod_not_idle(self):
        row = {'pod_uid': 'u1', 'pod': 'p1', 'status': 'observed', 'rate': 0, 'active': 0, 'timestamp': 100, 'samples': 4}
        self.assertEqual(m.telemetry([row], {'u1': 'p1'}, 110, 60), 0)
        for rows, pods in [([], {'u1': 'p1'}), ([row], {'u1': 'p1', 'u2': 'p2'}), ([row | {'status': 'query-failed'}], {'u1': 'p1'}), ([row | {'timestamp': 0}], {'u1': 'p1'}), ([row | {'rate': float('nan')}], {'u1': 'p1'}), ([row | {'samples': 1}], {'u1': 'p1'})]:
            with self.assertRaises(ValueError): m.telemetry(rows, pods, 110, 60)
        q = m.scale_query(plan())
        self.assertIn('rate(', q); self.assertIn('timestamp(', q); self.assertIn('kube_pod_info', q)
        self.assertNotIn('vector(0)', q)

    def test_c3_uid_delta_only_and_other_drift_not_relaxed(self):
        target = {'uid': 'u1', 'name': 'p1', 'images': {'app': 'sha'}, 'mapping': {'capacity': 2}}
        b = {'targets': [target], 'scenario': {'max_requests': 2, 'hold_ms': 1000}, 'stable': 'fixed', 'hostname': 'forgejo.example.com'}
        after = copy.deepcopy(b); after['targets'].append(target | {'uid': 'u2', 'name': 'p2'})
        m.config_guard(b, after, 'C3')
        with self.assertRaises(ValueError): m.config_guard(b, after, 'C0')
        for key, value in [('stable', 'changed'), ('hostname', 'other.example.com')]:
            with self.assertRaises(ValueError): m.config_guard(b, after | {key: value}, 'C3')
        after['targets'][1]['images'] = {'app': 'wrong'}
        with self.assertRaises(ValueError): m.config_guard(b, after, 'C3')

    def test_shedding_queue_and_target_overflow_separate_including_residual(self):
        v = {'checks': 100, 'target_admitted': 10, 'target_rejected': 40, 'admission_shed': 20, 'queue_timeout': 15,
             'queue_start': 0, 'queue_end': 10, 'inflight_start': 0, 'inflight_end': 5, 'path_errors': 0}
        self.assertEqual(m.accounting('C2', v)['target_rejected'], 40)
        with self.assertRaises(ValueError): m.accounting('C0', v)
        with self.assertRaises(ValueError): m.accounting('C2', v | {'target_rejected': 60})


class PathEvidenceTests(unittest.TestCase):
    def fixture(self):
        stat = {'cluster.actual.' + key: 0 for key in m.p8.p4.SUFFIXES}
        hp = {'status': 'no check'} | {k: 0 for k in m.p8.p4.HAPROXY_FIELDS}
        hp['backend'] = copy.deepcopy(hp)
        first = {'stats': {'u1': copy.deepcopy(stat)}, 'haproxy': copy.deepcopy(hp), 'haproxy_logs': [],
                 'logs': {'checks': [], 'proxies': {'target': {'u1': []}, 'ingress': {'g1': []}}}}
        last = copy.deepcopy(first)
        last['stats']['u1']['cluster.actual.upstream_rq_total'] = 4
        last['stats']['u1']['cluster.actual.upstream_rq_active_overflow'] = 8
        check = {'record': 'authorization_check', 'timestamp_utc': '2026-10-29T00:00:00Z', 'decision': 'ALLOW',
                 'header_names': ['authorization'], 'credential_values_absent': True, 'body_absent': True,
                 'haproxy_hop': True, 'controlled_deny': False}
        last['logs']['checks'] = [check | {'check_id': str(i), 'operation_id': 'op' + str(i), 'attempt_id': 'op' + str(i) + '-attempt-1'} for i in range(4)]
        last['logs']['proxies']['target']['u1'] = [{'status': 200, 'detail': 'via_upstream'}] * 4 + [{'status': 503, 'detail': 'overflow'}] * 8
        last['logs']['proxies']['ingress']['g1'] = [{'status': 200, 'detail': 'via_upstream'}] * 4 + [{'status': 403, 'detail': 'ext_authz_error'}] * 8
        last['haproxy'].update(hrsp_2xx=4, hrsp_5xx=8)
        last['haproxy']['backend'].update(hrsp_2xx=4, hrsp_5xx=8)
        last['haproxy_logs'] = [{'status': 200, 'termination': '--', 'queue_ms': 0}] * 4 + [{'status': 503, 'termination': '--', 'queue_ms': 0}] * 8
        return first, last

    def test_actual_aggregation_keeps_shedding_separate(self):
        first, last = self.fixture()
        self.assertEqual(m.path_accounting('C0', [first, last])['target_rejected'], 8)
        last['haproxy_logs'] += [{'status': 429, 'termination': 'PR', 'queue_ms': -1}] * 2
        last['logs']['proxies']['ingress']['g1'] += [{'status': 429, 'detail': 'ext_authz_denied'}] * 2
        report = m.path_accounting('C2', [first, last])
        self.assertEqual(report['checks'], 14)
        self.assertEqual(report['admission_shed'], 2)
        self.assertEqual(report['target_rejected'], 8)
        last['haproxy_logs'] += [{'status': 503, 'termination': 'sQ', 'queue_ms': 250}] * 2
        last['haproxy']['backend']['hrsp_5xx'] += 2
        last['logs']['proxies']['ingress']['g1'] += [{'status': 403, 'detail': 'ext_authz_error'}] * 2
        queued = m.path_accounting('C2', [first, last])
        self.assertEqual(queued['queue_timeout'], 2)
        self.assertEqual(queued['target_rejected'], 8)
        with self.assertRaises(ValueError): m.path_accounting('C0', [first, last])

    def test_reset_missing_native_denial_rotated_log_and_path_errors(self):
        for case in ('reset', 'missing', 'native-denial', 'rotation', 'path-error', 'misclassified-shed'):
            first, last = self.fixture()
            if case == 'reset': first['stats']['u1']['cluster.actual.upstream_rq_active_overflow'] = 10
            elif case == 'missing': last['stats']['u1'].pop('cluster.actual.upstream_rq_total')
            elif case == 'native-denial': last['logs']['proxies']['ingress']['g1'][0] = {'status': 403, 'detail': 'via_upstream'}
            elif case == 'rotation': first['haproxy_logs'] = [{'status': 201}]
            elif case == 'path-error': last['haproxy_logs'][0] = {'status': 503, 'termination': 'SC', 'queue_ms': 0}
            else: last['haproxy_logs'][0] = {'status': 429, 'termination': 'PR', 'queue_ms': -1}
            with self.subTest(case=case), self.assertRaises(ValueError): m.path_accounting('C2', [first, last])


class CompleteEvidenceTests(unittest.TestCase):
    def fixture(self, directory):
        v, identity = plan(), t8.identity()
        with patch.dict(os.environ, {'FORGEJO_URL': 'https://forgejo.example.com'}, clear=True):
            live = LiveFixture('C0')
            baseline = live.baseline
            snapshots = []
            for at in range(-5, 366, 5):
                if at >= 185:
                    name = live.pods[0]['metadata']['name']
                    live.holds[name], live.capacities[name] = 0, 1024
                snapshots += [e for e in live.collect(at, released=at >= 185) if e['record'] == 'snapshot']
        manifest = {'source_sha': identity['source_sha'], 'identity': identity, 'plan': v, 'metric_contract': m.metric_contract(),
                    'transport': m.p8.p7.operations.transport('https://forgejo.example.com', 'azure-aks', None), 'fixture_sha256': 'a' * 64, 'arm': 'C0', 'phase': 'measured',
                    'schedule_sha256': m.digest(m.schedule(v)), 'slo_sha256': m.hashlib.sha256(m.SLO.read_bytes()).hexdigest(),
                    'render_sha256': {a: m.digest(m.render(identity, v, a)) for a in m.ARMS}, 'baseline': baseline}
        rows = events(v)
        start = {'record': 'run_start', 'timestamp_utc': '2026-10-29T00:00:00Z', 'transport': m.p8.p7.operations.transport('https://forgejo.example.com', 'azure-aks', None)}
        sentinel = [{'record': 'sentinel', 'at': at, 'result': {'semantic_result': True}} for at in range(361)]
        rows = [start] + rows + snapshots + sentinel + [{'record': 'run_end', 'completed': True, 'timestamp_utc': '2026-10-29T00:06:05Z'}]
        m.save(Path(directory) / 'configuration.json', manifest)
        (Path(directory) / 'events.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        return rows

    def test_validator_requires_cloud_review_and_rejects_real_drift(self):
        # Path conservation is tested above with full raw snapshots. Here only
        # that independent path collector is stubbed to exercise complete demand,
        # recovery, live resource/controller/metric guards and review boundaries.
        with tempfile.TemporaryDirectory() as directory:
            rows = self.fixture(directory)
            with patch.object(m, 'path_accounting', side_effect=lambda *_: {'admitted_checks': [], 'checks': 1800}):
                result = m.validate(directory)
                self.assertEqual(result['validity'], 'pending-cloud-confounder-review')
                self.assertEqual(result['recovery']['status'], 'recovered')
                with self.assertRaises(FileNotFoundError): m.reviewed(directory)
                snap = next(e for e in rows if e['record'] == 'snapshot')
                snap['guard']['admission']['conservative_sum']['limits']['cpu'] = 1.6
                (Path(directory) / 'events.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
                with self.assertRaisesRegex(ValueError, 'cap exceeded'): m.validate(directory)

    def test_missing_stale_and_wrong_uid_warmup_never_become_idle(self):
        for case in ('missing', 'stale', 'warmup-existing', 'controller-error', 'empty-query'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                rows = self.fixture(directory)
                snapshot = next(e for e in rows if e['record'] == 'snapshot')
                if case == 'missing': snapshot['signal']['pods'] = []
                elif case == 'stale': snapshot['signal']['pods'][0]['timestamp'] -= 1000
                elif case == 'warmup-existing': snapshot['signal'].update(status='warming-new-pod', missing_uids=['target'])
                elif case == 'controller-error': snapshot['guard']['events'] = [{'reason': 'FailedComputeMetricsReplicas'}]
                else: snapshot['signal']['query'] = []
                (Path(directory) / 'events.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
                with patch.object(m, 'path_accounting', side_effect=lambda *_: {'admitted_checks': [], 'checks': 1800}), self.assertRaises(ValueError):
                    m.validate(directory)


class LiveFixture:
    """Synthetic positives only, never Azure evidence; real config/signal/collection."""
    def __init__(self, arm='C3'):
        self.runtime = r = m.Runtime.__new__(m.Runtime)
        r.value, r.v, r.arm = t8.identity(), plan(), arm
        r.initial_uids, r.first_seen_uid = {'target'}, {}
        r.collection_deadline = threading.local()
        r.hpa_name = m.HPA if arm == 'C3' else 'hpa-app-cpu'
        objects = m.render(r.value, r.v, arm)['fixtures.json']['items']
        r.hp_config = next(o['data']['haproxy.cfg'] for o in objects if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'haproxy')
        self.hpa = {'metadata': {'name': r.hpa_name}, 'spec': t8.hpa_spec()}
        self.scaled = []
        if arm == 'C3':
            so = copy.deepcopy(next(o for o in objects if o['kind'] == 'ScaledObject'))
            so['metadata']['uid'] = 'so'
            self.scaled = [so]
            self.hpa['metadata']['ownerReferences'] = [{'kind': 'ScaledObject', 'uid': 'so', 'controller': True}]
        self.policy, self.listeners, filters, _ = t8.gateway_fixture()
        filters[-1]['typed_config'].update(http_service={'server_uri': {'cluster': 'haproxy.' + m.NS + '.svc.cluster.local'},
            'authorization_request': {'headers_to_add': [{'key': 'authorization', 'value': 'p4-check-without-credentials'}]}})
        self.pods = [self.pod('target', 'ext-authz-sim-abc')]
        self.capacities, self.holds = {}, {}
        self.missing, self.stale, self.one_sample = set(), set(), set()
        self.no_admin = set()
        self.extra_series = False
        self.epoch = None
        self.queries = []
        self.rate, self.traffic = 0, 0
        self.config = {'max_requests': 2, 'hold_ms': 1000, 'logical_operations': 24, 'concurrency': 12,
                       'waves': 72, 'wave_interval_seconds': 5}
        r.pods, r.j, r.k, r.admin, r.prom = self.get_pods, self.j, self.k, self.admin, self.prom
        r.guard = self.guard
        r.haproxy = lambda: {}
        self.baseline = r.configuration(self.config)

    def pod(self, uid, name, ready=True):
        return {'metadata': {'uid': uid, 'name': name, 'namespace': m.NS,
                             'labels': {'app': 'ext-authz-sim', 'p8.campaign': self.runtime.value['campaign']}},
                'spec': {'containers': [{'name': 'app', 'image': self.runtime.value['ext_authz_image'],
                    'resources': {'requests': {'cpu': '50m', 'memory': '64Mi'}, 'limits': {'cpu': '100m', 'memory': '128Mi'}}}]},
                'status': {'phase': 'Running' if ready else 'Pending',
                           'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False'}],
                           'containerStatuses': [{'name': 'app', 'imageID': 'sha', 'ready': ready, 'restartCount': 0}] if ready else []}}

    def get_pods(self, ns, selector):
        if selector == 'app=ext-authz-sim': return self.pods
        if selector == 'app=haproxy':
            return [{'metadata': {'name': 'hp', 'uid': 'hp'}, 'spec': {'containers': [{'name': 'haproxy', 'image': m.p8.PINS['HAPROXY_IMAGE']}]}}]
        if ns == 'forgejo': return [{'metadata': {'name': 'forgejo', 'uid': 'stable'}, 'status': {}}]
        if ns == 'aks-istio-ingress': return [{'metadata': {'name': 'ingress', 'uid': 'ingress'}}]
        raise AssertionError((ns, selector))

    def j(self, *args):
        if 'authorizationpolicy' in args: return self.policy
        if 'scaledobjects' in args: return {'items': self.scaled}
        if 'hpa' in args: return self.hpa | {'status': {'desiredReplicas': len(self.pods)}} if self.runtime.hpa_name in args else {'items': [self.hpa]}
        if 'deployment' in args: return {'spec': {'template': 'fixed'}}
        raise AssertionError(args)

    def k(self, *args):
        if 'logs' in args: return ''
        if 'stats/prometheus' in args:
            uid = next(p['metadata']['uid'] for p in self.pods if p['metadata']['name'] == args[3])
            if uid in self.no_admin: return ''
            c = m.metric_contract()
            return '# TYPE ' + c['overflow'] + ' counter\n# TYPE ' + c['active'] + ' gauge\n' + \
                c['overflow'] + '{cluster_name="inbound|8080||"} 0\n' + c['active'] + '{cluster_name="inbound|8080||"} 0\n'
        if '/config/hold-ms' in args: return str(self.holds.get(args[3], 1000))
        if '/config/haproxy.cfg' in args: return self.runtime.hp_config.rstrip('\n')
        raise AssertionError(args)

    def admin(self, ns, name, path):
        if path.startswith('config_dump?resource=dynamic_active_clusters'):
            return {'cluster': {'name': 'inbound|8080||', 'type': 'ORIGINAL_DST', 'alt_stat_name': 'inbound|8080||;',
                                'circuit_breakers': {'thresholds': [{'max_requests': self.capacities.get(name, 2)}]}}}
        if path.startswith('stats?'):
            if next(p['metadata']['uid'] for p in self.pods if p['metadata']['name'] == name) in self.no_admin: return {'stats': []}
            return {'stats': [{'name': 'cluster.inbound|8080||;.' + k, 'value': self.traffic if k == 'upstream_rq_total' else 0} for k in m.p8.p4.SUFFIXES]}
        if path == 'config_dump?resource=dynamic_listeners': return self.listeners if ns == 'aks-istio-ingress' else {'filter_chain_match': {'destination_port': 8080}, 'route': {'cluster': 'inbound|8080||'}}
        if path == 'config_dump?resource=dynamic_route_configs': return {'route': {'cluster': 'forgejo-http.forgejo.svc'}}
        if path == 'server_info': return {'version': 'test'}
        if path == 'runtime?format=json': return {'entries': {m.p8.p4.GUARD: 'fixed'}}
        if path == 'config_dump?mask=bootstrap.stats_config': return {'stats_matcher': 'fixed', 'stats_tags': [{'tag_name': 'cluster_name', 'regex': m.metric_contract()['tag_regex']}], 'use_all_default_tags': False}
        raise AssertionError((ns, name, path))

    def prom(self, query):
        self.queries.append(query)
        if query == m.scale_query(self.runtime.v):
            # Real guard is empty while live inventory exceeds rate coverage.
            return [] if any(not m.p8.p4.pod_guard(p)['ready'] or p['metadata']['uid'] in self.missing | self.one_sample for p in self.pods) else [{'metric': {}, 'value': [0, str(self.rate * len(self.pods))]}]
        values = []
        for p in self.pods:
            uid, name = p['metadata']['uid'], p['metadata']['name']
            if not m.p8.p4.pod_guard(p)['ready']: continue
            if uid in self.missing and query.startswith('rate('): continue
            value = self.rate if query.startswith('rate(') else 0
            if query.startswith('timestamp('): value = (time.time() if self.epoch is None else self.epoch) - (1000 if uid in self.stale else 0)
            if query.startswith('count_over_time('): value = 1 if uid in self.one_sample else 4
            values.append({'metric': {'pod': name, 'cluster': self.runtime.v['prometheus_cluster'], 'namespace': m.NS, 'job': 'p9-envoy', 'cluster_name': 'inbound|8080||'}, 'value': [0, str(value)]})
        if self.extra_series: values.append({'metric': {'pod': 'unknown-pod'}, 'value': [0, '0']})
        return values

    def guard(self):
        guard = t8.metric_guard()
        guard['pods'] = [m.p8.p4.pod_guard(p) for p in self.pods]
        guard['runtime_images'] = {p['metadata']['uid']: {c['name']: c['imageID'] for c in p['status'].get('containerStatuses', [])} for p in self.pods}
        guard['pod_metrics'] = [copy.deepcopy(guard['pod_metrics'][0]) | {'metadata': {'name': p['metadata']['name'], 'namespace': m.NS}}
                                for p in self.pods if m.p8.p4.pod_guard(p)['ready']]
        guard['admission'] = m.p8.admission(self.runtime.value, self.pods)
        guard['hpa'].update(currentReplicas=len(self.pods), desiredReplicas=len(self.pods))
        return guard

    def collect(self, at, released=False):
        rows, started = [], threading.Event()
        if released: started.set()
        self.epoch = 1000 + at
        with patch.object(m.time, 'monotonic', return_value=at), patch.object(m.time, 'time', return_value=self.epoch):
            m.collect_snapshot(self.runtime, self.config, self.baseline, rows.append, started)
        return rows


class CollectionGateTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'FORGEJO_URL': 'https://forgejo.example.com'}, clear=True)
        env.start(); self.addCleanup(env.stop)

    def test_pending_ready_rate_warmup_collected_and_saved_validator(self):
        f = LiveFixture()
        # Establish existing series, then admit the second UID as Pending.
        f.rate = 1
        initial = f.collect(-5)
        f.pods.append(f.pod('new', 'ext-authz-sim-new', ready=False))
        pending = f.collect(185)
        self.assertEqual([p['metadata']['uid'] for p in f.runtime.targets()], ['target', 'new'])
        snapshot = next(e for e in pending if e['record'] == 'snapshot')
        self.assertEqual(snapshot['signal']['status'], 'warming-new-pod')
        self.assertEqual(snapshot['signal']['missing_uids'], ['new'])
        self.assertEqual(snapshot['signal']['query'], [])
        self.assertFalse(snapshot['healthy'])
        self.assertEqual(len(snapshot['configuration']['targets']), 1)
        # Pending time does not consume the separate Ready -> series budget.
        f.pods[1] = f.pod('new', 'ext-authz-sim-new')
        f.missing = {'new'}; f.no_admin = {'new'}
        f.traffic = 1  # Ready/traffic during warmup still cannot prove scaling.
        ready = f.collect(270)
        self.assertEqual(next(e for e in ready if e['record'] == 'snapshot')['signal']['status'], 'warming-new-pod')
        no_admin = next(e for e in ready if e['record'] == 'snapshot')
        self.assertNotIn('new', no_admin['stats'])
        self.assertEqual(no_admin['admin_stats']['new']['values'], {})
        self.assertEqual(no_admin['admin_stats']['new']['status'], 'uninitialized')
        self.assertIn('new', no_admin['logs']['proxies']['target'])
        f.no_admin.clear(); f.missing.clear(); f.one_sample = {'new'}
        sample = f.collect(275)
        self.assertEqual(next(e for e in sample if e['record'] == 'snapshot')['signal']['status'], 'warming-new-pod')
        f.one_sample.clear()
        f.capacities = {p['metadata']['name']: 1024 for p in f.pods}
        f.holds = {p['metadata']['name']: 0 for p in f.pods}
        observed = f.collect(280, released=True)
        snap = next(e for e in observed if e['record'] == 'snapshot')
        self.assertTrue(snap['healthy']); self.assertEqual(snap['signal']['status'], 'observed')
        self.assertEqual(len(snap['signal']['query']), 1)
        # Feed actual collected snapshots through the whole saved-run validator.
        with tempfile.TemporaryDirectory() as directory:
            rows = CompleteEvidenceTests().fixture(directory)
            manifest = m.load(Path(directory) / 'configuration.json')
            manifest.update(arm='C3', baseline=f.baseline)
            Path(directory, 'configuration.json').write_text(json.dumps(manifest))
            collected = {e['at']: e for e in initial + pending + ready + sample + observed if e['record'] == 'snapshot'}
            timeline = [(-5, collected[-5]), (185, collected[185]), (270, collected[270]), (275, collected[275]), (280, collected[280])]
            for i, row in enumerate(rows):
                if row['record'] != 'snapshot': continue
                source_at, source = max((x for x in timeline if x[0] <= row['at']), key=lambda x: x[0])
                replacement = copy.deepcopy(source)
                replacement.update(at=row['at'], end=row['end'], epoch=row['epoch'])
                for r in replacement['signal']['pods']: r['timestamp'] = row['epoch']
                rows[i] = replacement
            # Preserve the collector's convergence and release-gap events.
            rows[-1:-1] = [e for e in initial + pending + ready + sample + observed if e['record'] in {'convergence', 'replica_timeline'}]
            path = Path(directory, 'events.jsonl')
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            with patch.object(m, 'path_accounting', return_value={'admitted_checks': [], 'checks': 1800}):
                result = m.validate(directory)
                self.assertEqual(result['recovery']['first_good_window'], 290)
                self.assertEqual(result['scaling']['signal_to_desired_ready_traffic'][-1], 280)
                self.assertFalse(any(w['good'] for w in result['recovery']['windows'] if w['start'] < 280))
                for case in ('existing-missing', 'unknown-uid', 'startup-timeout', 'series-timeout', 'stale-existing', 'existing-admin-loss', 'unknown-admin', 'fabricated-new-zero', 'saved-label', 'native-negative'):
                    changed = copy.deepcopy(rows)
                    warm = next(e for e in changed if e['record'] == 'snapshot' and e['at'] == 190)
                    if case in {'existing-admin-loss', 'unknown-admin', 'fabricated-new-zero', 'saved-label', 'native-negative'}:
                        warm = next(e for e in changed if e['record'] == 'snapshot' and e['at'] == 270)
                    if case == 'existing-admin-loss':
                        obs = warm['admin_stats']['target']
                        obs.update(status='uninitialized', missing=list(obs['values']), values={})
                        warm['stats'].pop('target')
                    elif case == 'unknown-admin': warm['admin_stats']['unknown'] = copy.deepcopy(warm['admin_stats']['target'])
                    elif case == 'fabricated-new-zero': warm['stats']['new'] = {k: 0 for k in warm['configuration']['targets'][1]['mapping']['stat_names']}
                    elif case == 'saved-label': warm['signal']['pods'][0]['metric_contract']['cluster_label'] = 'envoy_cluster_name'
                    elif case == 'native-negative': warm['admin_stats']['target']['native'][m.metric_contract()['active']] = -1
                    elif case == 'existing-missing': warm['signal']['pods'] = []
                    elif case == 'unknown-uid': warm['signal']['missing_uids'] = ['unknown']
                    elif case == 'stale-existing': warm['signal']['pods'][0]['timestamp'] -= 1000
                    elif case == 'startup-timeout':
                        for e in changed:
                            if e['record'] == 'snapshot' and 185 <= e['at'] <= 280:
                                at, end, epoch = e['at'], e['end'], e['epoch']
                                e.update(copy.deepcopy(warm), at=at, end=end, epoch=epoch)
                                e['signal']['pods'][0]['timestamp'] = epoch
                    elif case == 'series-timeout':
                        # Ready at185 with no series through270 exceeds75s.
                        for e in changed:
                            if e['record'] == 'snapshot' and 185 <= e['at'] <= 275:
                                e['target_inventory'][1] = copy.deepcopy(collected[270]['target_inventory'][1])
                                e['guard'] = copy.deepcopy(collected[270]['guard'])
                                e['configuration'] = copy.deepcopy(collected[275]['configuration'])
                                e['admin_stats'] = copy.deepcopy(collected[275]['admin_stats'])
                                e['stats'] = copy.deepcopy(collected[275]['stats'])
                    path.write_text(''.join(json.dumps(r) + '\n' for r in changed))
                    expected = {'existing-missing': 'missing telemetry', 'unknown-uid': 'missing telemetry',
                                'startup-timeout': 'Pod lifecycle failure', 'series-timeout': 'series startup timeout',
                                'stale-existing': 'stale/error', 'existing-admin-loss': 'unapproved missing admin',
                                'unknown-admin': 'unknown admin UID', 'fabricated-new-zero': 'stats fabricated',
                                'saved-label': 'metric contract drift', 'native-negative': 'invalid native metric'}[case]
                    with self.subTest(case=case), self.assertRaisesRegex(ValueError, expected): m.validate(directory)

    def test_collection_fails_existing_loss_unknown_series_and_timeouts(self):
        for case in ('missing', 'stale', 'one-sample', 'unknown', 'pending-timeout', 'ready-too-late', 'series-timeout', 'observed-new-loss'):
            with self.subTest(case=case):
                f = LiveFixture(); f.collect(0)
                f.pods.append(f.pod('new', 'ext-authz-sim-new', ready=False)); f.collect(1)
                at = 2
                if case == 'missing': f.missing = {'target'}
                elif case == 'stale': f.stale = {'target'}
                elif case == 'one-sample': f.one_sample = {'target'}
                elif case == 'unknown': f.extra_series = True
                elif case == 'pending-timeout': at = 92
                elif case == 'ready-too-late': f.pods[1] = f.pod('new', 'ext-authz-sim-new'); at = 92
                elif case == 'series-timeout':
                    f.pods[1] = f.pod('new', 'ext-authz-sim-new'); f.missing = {'new'}; f.collect(2); at = 78
                else:
                    f.pods[1] = f.pod('new', 'ext-authz-sim-new'); f.collect(2); f.missing = {'new'}; at = 3
                with self.assertRaises(ValueError): f.collect(at)

    def test_release_partial_convergence_checks_invariants_and_records_gap(self):
        for order in ('hold-first', 'capacity-first'):
            with self.subTest(order=order):
                f = LiveFixture(); f.collect(0)
                name = f.pods[0]['metadata']['name']
                (f.holds if order == 'hold-first' else f.capacities)[name] = 0 if order == 'hold-first' else 1024
                rows = f.collect(185, released=True)
                gap = next(e for e in rows if e['record'] == 'snapshot_gap')
                self.assertEqual(gap['reason'], 'release-not-converged')
                self.assertIn('fault_state', gap)
                snap = next(e for e in rows if e['record'] == 'snapshot')
                self.assertFalse(snap['healthy']); self.assertFalse(snap['fault_healthy'])
                self.assertFalse(any(e['record'] == 'convergence' for e in rows))
                f.holds[name], f.capacities[name] = 0, 1024
                rows = f.collect(190, released=True)
                self.assertFalse(any(e['record'] == 'snapshot_gap' for e in rows))
                self.assertTrue(next(e for e in rows if e['record'] == 'snapshot')['healthy'])

    def test_fault_values_outside_release_boundary_fail(self):
        for released, hold, capacity in ((False, 0, 2), (False, 1000, 1024), (True, 250, 2), (True, 0, 64)):
            with self.subTest(released=released, hold=hold, capacity=capacity):
                f = LiveFixture(); f.collect(0)
                name = f.pods[0]['metadata']['name']
                f.holds[name], f.capacities[name] = hold, capacity
                with self.assertRaises(ValueError): f.collect(185, released=released)

    def test_partial_release_gaps_excluded_by_saved_recovery_validator(self):
        for order in ('hold-first', 'capacity-first'):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as directory:
                f = LiveFixture()
                rows = CompleteEvidenceTests().fixture(directory)
                manifest = m.load(Path(directory, 'configuration.json'))
                manifest.update(arm='C3', baseline=f.baseline)
                Path(directory, 'configuration.json').write_text(json.dumps(manifest))
                extra = []
                for i, e in enumerate(rows):
                    if e['record'] != 'snapshot': continue
                    at, name = e['at'], f.pods[0]['metadata']['name']
                    if at >= 185:
                        (f.holds if order == 'hold-first' else f.capacities)[name] = 0 if order == 'hold-first' else 1024
                    if at >= 195: f.holds[name], f.capacities[name] = 0, 1024
                    collected = f.collect(at, released=at >= 180)
                    rows[i] = next(r for r in collected if r['record'] == 'snapshot')
                    extra += [r for r in collected if r['record'] in {'snapshot_gap', 'convergence'}]
                rows = [e for e in rows if e['record'] != 'convergence']
                rows[-1:-1] = extra
                Path(directory, 'events.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
                with patch.object(m, 'path_accounting', return_value={'admitted_checks': [], 'checks': 1800}):
                    result = m.validate(directory)
                self.assertEqual(result['recovery']['first_good_window'], 210)
                self.assertFalse(any(w['good'] for w in result['recovery']['windows'] if w['start'] < 195))

    def test_release_drift_and_unknown_failure_reach_monitor_cancel_and_release(self):
        for case in ('hostname', 'provider', 'selector', 'controller', 'image', 'unknown'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                f = LiveFixture('C0')
                real_config = f.runtime.configuration
                drift_at = []
                def drift(config, **kwargs):
                    if released.is_set():
                        drift_at.append(time.monotonic())
                        if case == 'hostname': f.policy['spec']['rules'][0]['to'][0]['operation']['hosts'] = ['other.example.com']
                        elif case == 'provider': f.policy['spec']['provider']['name'] = 'unknown'
                        elif case == 'selector': f.policy['spec']['selector'] = {'matchLabels': {'app': 'unknown'}}
                        elif case == 'controller': f.hpa['metadata']['ownerReferences'] = [{'kind': 'Unknown'}]
                        elif case == 'image': f.pods[0]['spec']['containers'][0]['image'] = 'wrong'
                        else: raise ValueError('unknown validation failure')
                    return real_config(config, **kwargs)
                f.runtime.configuration = drift
                released = threading.Event()
                def release(emit):
                    f.holds[f.pods[0]['metadata']['name']] = 0
                    emit({'record': 'release', 'at': time.monotonic()}); released.set()
                f.runtime.release = release
                real_drive = m.drive
                def drive(v, arm, issue, git, emit, release, **kwargs):
                    # Start release, let the real monitor observe drift, then
                    # verify the real driver sees failure and stops demand.
                    release(0)
                    deadline = time.monotonic() + 3
                    while not kwargs['monitor_error']() and time.monotonic() < deadline: time.sleep(.01)
                    self.assertTrue(kwargs['monitor_error']())
                    arrivals = [{'id': 'pending', 'kind': 'issue', 'at': 0, 'wave': 0}]
                    with patch.object(m, 'schedule', return_value=arrivals):
                        real_drive({'mitigation_seconds': 1, 'recovery_seconds': 1}, arm, issue, git, emit, lambda _: None, **kwargs)
                output = Path(directory, 'run')
                v = plan()
                m.save(Path(directory, 'approval.json'), approval())
                with patch.dict(os.environ, {'FORGEJO_URL': 'https://forgejo.example.com', 'DEV_USER': 'test', 'ISSUE_NUMBER': '1', 'ISSUE_TITLE': 'fixture', 'EXPECTED_MAIN_SHA': 'a' * 40, 'DEV_TOKEN': 'test'}), \
                     patch.object(m, 'execution_gate'), patch.object(m, 'Runtime', return_value=f.runtime), \
                     patch.object(m, 'drive', side_effect=drive), \
                     patch.object(m.p8, 'request', return_value={'semantic_result': True}):
                    with self.assertRaises(ValueError):
                        m._measure(t8.identity(), v, 'C0', 'calibration', output, Path(directory, 'approval.json'), '-', Path(directory, 'ledger'))
                rows = [json.loads(line) for line in Path(output, 'events.jsonl').read_text().splitlines()]
                self.assertTrue(released.is_set())
                self.assertTrue(any(e['record'] == 'monitor_failure' for e in rows))
                self.assertTrue(any(e['record'] == 'run_failure' for e in rows))
                self.assertFalse(any(e['record'] == 'snapshot_gap' and e['at'] >= drift_at[0] for e in rows))
                self.assertEqual(next(e for e in rows if e['record'] == 'operation')['outcome'], 'not-issued')


class MetricInitializationTests(unittest.TestCase):
    """Archived negatives + explicitly synthetic positives; all I/O is mocked."""
    def setUp(self):
        env = patch.dict(os.environ, {'FORGEJO_URL': 'https://forgejo.example.com'}, clear=True)
        env.start(); self.addCleanup(env.stop)

    def archived(self, name):
        with tarfile.open(ROOT / 'docs/evidence/p9-mitigation-preflight-20261029/raw-evidence.tar.gz') as archive:
            return json.load(archive.extractfile(name))

    def test_archived_bootstrap_samples_are_not_inbound_positive(self):
        negative = self.archived('target-admin-initial-required-stat-negative.json')
        self.assertEqual(m.native_samples('\n'.join(negative['prometheus_selected_lines'])), {})
        # P8 remains strict on the original absent-stat payload.
        f = LiveFixture()
        dump = f.admin(m.NS, 'ext-authz-sim-abc', 'config_dump?resource=dynamic_active_clusters')
        listeners = f.admin(m.NS, 'ext-authz-sim-abc', 'config_dump?resource=dynamic_listeners')
        with self.assertRaisesRegex(ValueError, 'required actual target stats'):
            m.p8.target_mapping(dump, negative['raw_stats'], 2, listeners)
        mapping, values = m.p8.target_mapping(dump, negative['raw_stats'], 2, listeners, allow_uninitialized=True)
        self.assertEqual(values, {})
        self.assertEqual(m.metric_mapping(mapping, negative['bootstrap_stats_config'])['cluster_label'], 'cluster_name')
        actual = self.archived('ingested-envoy-cluster-label.json')
        self.assertNotIn('inbound|8080||', json.dumps(actual))
        self.assertIn('cluster_name', json.dumps(actual))
        self.assertNotIn('envoy_cluster_name', json.dumps(actual))

    def test_all_queries_render_collection_and_freeze_share_selected_label(self):
        v, f = plan(), LiveFixture()
        queries = list(m.signal_queries(v).values()) + [m.scale_query(v)]
        for query in queries:
            self.assertIn('cluster_name="inbound|8080||"', query)
            self.assertNotIn('envoy_cluster_name', query)
            self.assertNotIn(' or ', query)
        trigger = next(o for o in m.render(t8.identity(), v, 'C3')['fixtures.json']['items'] if o['kind'] == 'ScaledObject')['spec']['triggers'][0]
        self.assertEqual(trigger['metadata']['query'], m.scale_query(v))
        f.collect(0)
        self.assertEqual(set(f.queries), set(queries) - {m.signal_queries(v)['raw']})
        c = {'source_sha': t8.identity()['source_sha'], 'plan_sha256': m.digest(v), 'reviewed': True,
             'missing_required_signals': [], 'cadence_observed': True, 'all_pod_series_observed': True,
             'counter_semantics': 'per-pod-active-overflow-counter-rate-per-second', 'controller_ownership_verified': True,
             'transport': m.p8.p7.operations.transport('https://forgejo.example.com', 'azure-aks', None),
             'fixture_sha256': 'a' * 64, 'metric_contract': m.metric_contract()}
        self.assertEqual(m.frozen(t8.identity(), v, [c])['metric_contract'], m.metric_contract())
        c['metric_contract']['cluster_label'] = 'envoy_cluster_name'
        with self.assertRaises(ValueError): m.frozen(t8.identity(), v, [c])
        original = f.prom
        def wrong_label(query):
            rows = original(query)
            for r in rows:
                if 'cluster_name' in r['metric']: r['metric']['envoy_cluster_name'] = r['metric'].pop('cluster_name')
            return rows
        f.runtime.prom = wrong_label
        with self.assertRaisesRegex(ValueError, 'metric label drift'): f.collect(1)

    def test_mapping_tag_port_duplicate_and_native_drift_fail_before_warmup(self):
        for case in ('cluster', 'alt', 'port', 'tag', 'duplicate', 'native-label'):
            with self.subTest(case=case):
                f = LiveFixture(); original_admin, original_k = f.admin, f.k
                f.collect(0); f.pods.append(f.pod('new', 'ext-authz-sim-new')); f.no_admin = {'new'}
                def admin(ns, name, path):
                    data = copy.deepcopy(original_admin(ns, name, path))
                    if name.endswith('-new'):
                        if path.startswith('config_dump?resource=dynamic_active_clusters'):
                            if case == 'cluster': data['cluster']['name'] = 'inbound|9090||'
                            elif case == 'alt': data['cluster']['alt_stat_name'] = 'wrong'
                            elif case == 'duplicate': data = {'clusters': [data['cluster'], copy.deepcopy(data['cluster'])]}
                        if case == 'port' and path.endswith('dynamic_listeners'): data['filter_chain_match']['destination_port'] = 9090
                        if case == 'tag' and path.endswith('bootstrap.stats_config'): data['stats_tags'][0]['tag_name'] = 'envoy_cluster_name'
                    return data
                def k(*args):
                    if case == 'native-label' and 'stats/prometheus' in args and 'ext-authz-sim-new' in args:
                        return '# TYPE envoy_cluster_upstream_rq_active gauge\nenvoy_cluster_upstream_rq_active{envoy_cluster_name="inbound|8080||"} 0\n'
                    return original_k(*args)
                f.runtime.admin, f.runtime.k = admin, k
                with self.assertRaises(ValueError): f.collect(1)

    def test_admin_numeric_zero_is_observed_absence_is_not_zero(self):
        f = LiveFixture(); observed = next(e for e in f.collect(0) if e['record'] == 'snapshot')
        self.assertTrue(observed['stats']['target'])
        self.assertEqual(set(observed['stats']['target'].values()), {0})
        paths, original = [], f.admin
        def traced(ns, name, path):
            paths.append(path); return original(ns, name, path)
        f.runtime.admin = traced
        f.pods.append(f.pod('new', 'ext-authz-sim-new')); f.no_admin = {'new'}
        warming = next(e for e in f.collect(1) if e['record'] == 'snapshot')
        self.assertNotIn('new', warming['stats'])
        self.assertEqual(warming['admin_stats']['new']['native'], {})
        self.assertIn('stats?format=json', paths)
        self.assertFalse(any('usedonly' in p or 'filter=' in p for p in paths))

    def test_existing_observed_admin_loss_and_new_startup_timeout_fail(self):
        for case in ('existing', 'observed-new', 'timeout'):
            with self.subTest(case=case):
                f = LiveFixture(); f.collect(0)
                f.pods.append(f.pod('new', 'ext-authz-sim-new'))
                if case == 'existing': f.no_admin = {'target'}; at = 1
                elif case == 'observed-new': f.collect(1); f.no_admin = {'new'}; at = 2
                else: f.no_admin = {'new'}; f.collect(1); at = 77
                with self.assertRaises(ValueError): f.collect(at)

    def preparation(self):
        f = LiveFixture('C0'); f.runtime.preparation = True
        name = f.pods[0]['metadata']['name']; f.capacities[name], f.holds[name] = 1024, 0
        f.no_admin = {'target'}
        # Explicit synthetic CPU/HPA positive, separate from archived runtime data.
        base = []
        def cpu_guard():
            epoch = m.time.time()
            if not base: base.append(epoch)
            stamp = lambda at: m.datetime.fromtimestamp(at, m.timezone.utc).isoformat()
            pod = f.pods[0]
            pod['metadata']['creationTimestamp'] = stamp(base[0] - 60)
            pod['status']['conditions'][0]['lastTransitionTime'] = stamp(base[0] - 40)
            f.hpa['metadata'].update(uid='cpu-hpa', namespace=m.NS, generation=1, creationTimestamp=stamp(base[0] - 65))
            guard = f.guard()
            guard['timestamp_utc'] = stamp(epoch)
            guard['cpu_preparation_pods'] = [{**{k: pod['metadata'].get(k) for k in
                ('namespace', 'name', 'uid', 'creationTimestamp', 'deletionTimestamp')},
                'ready_conditions': [{'status': c['status'], 'lastTransitionTime': c.get('lastTransitionTime')}
                    for c in pod['status']['conditions'] if c['type'] == 'Ready']}]
            guard['cpu_hpa'] = copy.deepcopy(f.hpa) | {'status': copy.deepcopy(guard['hpa'])}
            guard['cpu_hpa']['status'].update(observedGeneration=1)
            for c in guard['cpu_hpa']['status']['conditions']:
                c['lastTransitionTime'] = stamp(base[0] - 20)
            guard['cpu_hpa']['status']['currentMetrics'][0]['containerResource']['current']['averageValue'] = '1m'
            for sample in guard['pod_metrics']:
                sample.update(timestamp=stamp(epoch), window='15s')
            return guard
        f.runtime.guard = cpu_guard
        return f

    def positive_journey(self, f):
        """Synthetic client/server positives, never runtime evidence or new load."""
        temporary = tempfile.TemporaryDirectory(prefix='p9-healthy-unit-')
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name, 'events.jsonl')
        run, stamp = 'healthy-unit', '2026-10-29T00:00:01Z'
        client = [{'record': 'run_start', 'schema_version': 1, 'run_id': run, 'phase': 'warmup',
                   'started_at_utc': '2026-10-29T00:00:00Z', 'scenario': 'local_healthy_developer_journey',
                   'parameters': {'concurrency': 1, 'max_attempts': 1, 'client_retry': False, 'api_timeout_seconds': 60,
                                  'git_timeout_seconds': 60, 'git_kill_after_seconds': 5},
                   'measurement_boundary': m.p8.p7.operations.AZURE_BOUNDARY,
                   'source_sha': f.runtime.value['source_sha'], 'dirty': False, 'environment': {'kind': 'azure-aks'},
                   'tool_versions': {}, 'argo_values_revision': 'a' * 40, 'forgejo_chart_version': 'synthetic',
                   'forgejo_chart_digest': 'sha256:synthetic', 'runtime_images': {},
                   'transport': m.p8.measurement_transport(f.runtime.value)},
                  {'record': 'auxiliary_event', 'run_id': run, 'event_id': run + '-event-1', 'kind': 'fixture',
                   'name': 'shared_gate_auxiliary_scope', 'outcome': 'success', 'operation_id': None,
                   'attempt_id': None, 'timestamp_utc': stamp}]
        pairs = []
        for index, typ in enumerate(sorted(m.p8.p7.operations.OP_TYPES), 1):
            op = run + '-operation-' + str(index)
            aid = op + '-attempt-1'
            client += [{'record': 'operation_start', 'run_id': run, 'operation_id': op, 'operation_type': typ, 'timestamp_utc': stamp},
                       {'record': 'attempt', 'run_id': run, 'attempt_id': aid, 'operation_id': op, 'attempt_index': 1,
                        'timestamp_utc': stamp, 'duration_seconds': .01, 'exit_code': 0, 'http_status': None if typ.startswith('git_') else 200, 'error_class': 'none'},
                       {'record': 'operation', 'run_id': run, 'operation_id': op, 'operation_type': typ,
                        'outcome': 'success', 'attempt_count': 1, 'duration_seconds': .01, 'semantic_result': True}]
            pairs.extend([(op, aid)] * (3 if typ == 'git_clone' else 1))
        client += [{'record': 'run_end', 'run_id': run, 'completion': 'success', 'validity': 'valid', 'ended_at_utc': '2026-10-29T00:00:02Z'}]
        path.write_text(''.join(json.dumps(r) + '\n' for r in client))
        auxiliary = run + '-auxiliary'
        pairs += [(auxiliary, auxiliary + '-attempt-1')] * 3
        checks = [{'record': 'authorization_check', 'check_id': 'check-' + str(i), 'timestamp_utc': stamp,
                   'operation_id': op, 'attempt_id': aid, 'decision': 'ALLOW', 'header_names': ['authorization'],
                   'credential_values_absent': True, 'body_absent': True, 'haproxy_hop': True, 'controlled_deny': False}
                  for i, (op, aid) in enumerate(pairs)]
        logs = {'checks': [], 'proxies': {'target': {'target': []}, 'ingress': {'ingress': []}}}
        f.runtime.logs = lambda _: copy.deepcopy(logs)
        def journey(_):
            logs['checks'] += copy.deepcopy(checks)
            logs['proxies']['target']['target'] += [{'status': 200, 'detail': 'via_upstream', 'cluster': 'inbound|8080||', 'duration_ms': 1}] * len(checks)
            # Existing private-repo native-deny checks still receive gate ALLOW.
            logs['proxies']['ingress']['ingress'] += [{'status': status, 'detail': 'via_upstream',
                'cluster': 'outbound|3000||forgejo-http.forgejo.svc.cluster.local', 'duration_ms': 1}
                for status in [200] * (len(checks) - 2) + [401, 404]]
            f.traffic += len(checks)
            return path
        return journey, path, logs

    def startup_archive(self):
        """Real admission/guard projections; synthetic clock isolates Ready window.

        Actual stop export was later; this does not assert live freshness/recovery.
        """
        runtime, owned = self.archived_cpu_runtime()
        events = runtime.j('get', 'events', '-A', '-o', 'json')
        events['items'] = [e for e in events['items'] if e.get('firstTimestamp') == '2026-10-29T05:55:53Z']
        guard = m.Runtime.guard(runtime)
        target = next(p for p in owned['items'] if p['metadata']['labels'].get('app') == 'ext-authz-sim')
        guard['timestamp_utc'] = '2026-10-29T05:56:25Z'
        guard['pod_metrics'] = [p for p in guard['pod_metrics'] if p['metadata']['name'] == target['metadata']['name']]
        guard['events'] = [e for e in guard['events'] if e['timestamp_utc'] == '2026-10-29T05:56:23Z']
        actual = {'targets': [{'uid': target['metadata']['uid'], 'name': target['metadata']['name']}],
                  'hpa_spec': guard['cpu_hpa']['spec']}
        return runtime, actual, guard

    def valid_cpu_recovery(self, runtime, seconds):
        # Synthetic positive continuation, never historical/runtime recovery proof.
        stamp = f'2026-10-29T05:56:{seconds:02d}Z'
        metrics = runtime.j('get', '--raw', '/apis/metrics.k8s.io/v1beta1/pods')
        sample = next(p for p in metrics['items'] if p['metadata']['labels'].get('app') == 'ext-authz-sim')
        sample.update(timestamp=stamp, window='15s')
        next(c for c in sample['containers'] if c['name'] == 'app')['usage']['cpu'] = '10m'
        hpa = runtime.j('-n', m.NS, 'get', 'hpa', 'hpa-app-cpu', '-o', 'json')
        hpa['metadata']['generation'] = 1
        hpa['status'].update(observedGeneration=1,
            conditions=[{'type': 'AbleToScale', 'status': 'True'},
                        {'type': 'ScalingActive', 'status': 'True', 'lastTransitionTime': '2026-10-29T05:56:39Z'}],
            currentMetrics=[{'type': 'ContainerResource', 'containerResource': {'name': 'cpu', 'container': 'app',
                'current': {'averageUtilization': 20, 'averageValue': '10m'}}}])
        with patch.object(m.p8, 'utc', return_value=stamp):
            return m.Runtime.guard(runtime)  # Positive payload also goes through real projections.

    def test_archived_cpu_window_is_pending_and_only_synthetic_recovery_passes(self):
        runtime, actual, g = self.startup_archive(); rows = []
        cpu = m.CPUStartup(actual)
        target = next(p for p in runtime.j('-n', m.NS, 'get', 'pods', '-o', 'json')['items'] if p['metadata']['uid'] == cpu.target)
        self.assertEqual(next(c for c in target['status']['conditions'] if c['type'] == 'Ready')['lastTransitionTime'], '2026-10-29T05:55:54Z')
        self.assertEqual(g['pod_metrics'][0]['timestamp'], '2026-10-29T05:56:18Z')
        self.assertEqual(g['pod_metrics'][0]['window'], '38.03202016s')
        self.assertFalse(m.initialization_safety(g, cpu_startup=cpu, emit=rows.append, at=0))
        self.assertFalse(rows[-1]['valid_ready_window'])
        self.assertEqual(rows[-1]['sample']['window_seconds'], 38.03202016)
        g = self.valid_cpu_recovery(runtime, 40)
        self.assertFalse(m.initialization_safety(g, cpu_startup=cpu, emit=rows.append, at=15))
        g = self.valid_cpu_recovery(runtime, 55)
        self.assertTrue(m.initialization_safety(g, cpu_startup=cpu, emit=rows.append, at=30))
        self.assertEqual(rows[-1]['hpa_current_cpu']['container'], 'app')
        self.assertEqual(rows[-1]['sample']['app_cpu'], '10m')
        self.assertEqual(len(cpu.history), 2)
        self.assertTrue(any(r['record'] == 'cpu_preparation_warning' for r in rows))
        with self.assertRaises(m.InitializationGuardError): m.initialization_safety(g)  # Default remains strict.
        g['events'][0]['count'] += 1
        with self.assertRaisesRegex(ValueError, 'warning recurred'):
            m.initialization_safety(g, cpu_startup=cpu, emit=rows.append, at=31)

    def archived_cpu_runtime(self):
        with tarfile.open(ROOT / 'docs/evidence/p9-mitigation-third-20261029/raw-evidence.tar.gz') as t:
            read = lambda n: json.load(t.extractfile(n))
            r = m.Runtime.__new__(m.Runtime); r.value = read('identity.json'); r.preparation = True; r.hpa_name = 'hpa-app-cpu'
            r.since = '2026-10-29T05:56:40Z'
            hpa = next(x for x in read('experiment-terminal.json')['items'] if x['kind'] == 'HorizontalPodAutoscaler')
            objects = {'nodes': read('nodes-before.json'), 'events': read('fixture-events-stop.json'),
                       'application': read('argo-before.json'), 'hpa': hpa}
            owned, all_pods = read('initial-pods.json'), read('all-pods-before.json')
            metrics = read('pod-metrics-stop.json')
            stable = read('forgejo-pods-before.json')['items'][0]
        def j(*args):
            if '/apis/metrics.k8s.io/v1beta1/pods' in args: return metrics
            if '/apis/metrics.k8s.io/v1beta1/nodes' in args: return {'items': []}
            if 'pods' in args: return all_pods if '-A' in args else owned
            return next(v for key, v in objects.items() if key in args)
        r.j = j; r.pod = lambda *a: stable
        r.k = lambda *a: '{"query_ok":true,"connections":4,"max_connections":100,"reserved":5}'
        return r, owned

    def test_cpu_settling_collector_keeps_owner_time_count_without_p8_default_change(self):
        r, owned = self.archived_cpu_runtime()
        hpa = r.j('-n', m.NS, 'get', 'hpa', 'hpa-app-cpu', '-o', 'json')
        collected = m.Runtime.guard(r)
        admitted = m.p8.admission(r.value, owned['items'])
        self.assertEqual(collected['admission'], admitted)
        self.assertTrue(all(set(p) == {'name', 'uid', 'containers'} for p in admitted['pods']))
        target = next(p for p in owned['items'] if p['metadata']['labels'].get('app') == 'ext-authz-sim')
        lifecycle = collected['cpu_preparation_pods']
        self.assertEqual(len(lifecycle), 1)
        self.assertEqual(set(lifecycle[0]), {'namespace', 'name', 'uid', 'creationTimestamp', 'deletionTimestamp', 'ready_conditions'})
        self.assertEqual(lifecycle[0]['uid'], target['metadata']['uid'])
        self.assertIsNone(lifecycle[0]['deletionTimestamp'])
        self.assertEqual(lifecycle[0]['ready_conditions'], [{'status': 'True', 'lastTransitionTime': '2026-10-29T05:55:54Z'}])
        self.assertEqual(collected['cpu_hpa']['metadata']['uid'], hpa['metadata']['uid'])
        historic = [e for e in collected['events'] if e['timestamp_utc'] == '2026-10-29T05:56:23Z']
        self.assertEqual(len(historic), 2)
        self.assertTrue(all(e['owner']['uid'] == hpa['metadata']['uid'] and e['count'] == 3 for e in historic))
        self.assertNotIn('message', json.dumps(collected['events']))
        strict = m.p8.Runtime.guard(r)
        self.assertNotIn('cpu_hpa', strict)
        self.assertNotIn('cpu_preparation_pods', strict)
        self.assertEqual(strict['admission'], admitted)
        self.assertTrue(all(set(e) == {'type', 'reason'} for e in strict['events']))

    def test_real_guard_lifecycle_missing_fields_and_drift_fail_closed(self):
        cases = ('creation-absent', 'ready-time-absent', 'not-ready', 'uid-drift', 'name-drift', 'ready-transition', 'terminating',
                 'projection-absent', 'namespace-field', 'name-field', 'uid-field', 'creation-field', 'deletion-field', 'ready-field',
                 'extra-uid', 'duplicate-uid', 'invalid-deletion')
        for case in cases:
            with self.subTest(case=case):
                runtime, actual, baseline = self.startup_archive()
                cpu = m.CPUStartup(actual)
                self.assertFalse(cpu.observe(baseline, lambda _: None, 0))
                owned = runtime.j('-n', m.NS, 'get', 'pods', '-o', 'json')['items']
                target = next(p for p in owned if p['metadata']['uid'] == cpu.target)
                ready = next(c for c in target['status']['conditions'] if c['type'] == 'Ready')
                if case == 'creation-absent': target['metadata'].pop('creationTimestamp')
                elif case == 'ready-time-absent': ready.pop('lastTransitionTime')
                elif case == 'not-ready': ready['status'] = 'False'
                elif case == 'uid-drift': target['metadata']['uid'] = 'different-uid'
                elif case == 'name-drift': target['metadata']['name'] = 'different-name'
                elif case == 'ready-transition': ready['lastTransitionTime'] = '2026-10-29T05:55:55Z'
                elif case == 'terminating': target['metadata']['deletionTimestamp'] = '2026-10-29T05:56:24Z'
                elif case == 'invalid-deletion': target['metadata']['deletionTimestamp'] = False
                guard = m.Runtime.guard(runtime)  # Run real admission + opt-in projection again.
                guard['timestamp_utc'] = baseline['timestamp_utc']
                if case == 'projection-absent': guard.pop('cpu_preparation_pods')
                elif case in {'extra-uid', 'duplicate-uid'}:
                    extra = copy.deepcopy(guard['cpu_preparation_pods'][0])
                    if case == 'extra-uid': extra['uid'] = 'unknown-uid'
                    guard['cpu_preparation_pods'].append(extra)
                elif case.endswith('-field'):
                    key = {'namespace-field': 'namespace', 'name-field': 'name', 'uid-field': 'uid',
                           'creation-field': 'creationTimestamp', 'deletion-field': 'deletionTimestamp', 'ready-field': 'ready_conditions'}[case]
                    guard['cpu_preparation_pods'][0].pop(key)
                with self.assertRaises(ValueError): cpu.observe(guard, lambda _: None, 1)

    def test_cpu_settling_timeout_other_warning_and_bad_metrics_never_start_journey(self):
        cases = ('persistent', 'pre-ready', 'missing', 'stale', 'zero', 'unknown', 'metric-container', 'metric-duplicate',
                 'hpa-metric', 'hpa-value-zero', 'owner', 'spec', 'other-warning', 'other-hpa', 'wrong-uid', 'no-owner',
                 'pod-unready', 'db', 'node', 'resource', 'ready-transition', 'generation', 'hpa-replaced', 'history-lost',
                 'no-active', 'no-current', 'no-able')
        for case in cases:
            with self.subTest(case=case):
                f = self.preparation(); guard = f.runtime.guard; rows, calls, clock = [], [], [0]
                def snapshot():
                    g = guard(); pod = g['cpu_preparation_pods'][0]; hpa = g['cpu_hpa']
                    e = {'type': 'Warning', 'reason': 'FailedComputeMetricsReplicas', 'uid': 'event', 'count': 1,
                         'first_timestamp_utc': hpa['metadata']['creationTimestamp'], 'timestamp_utc': hpa['metadata']['creationTimestamp'],
                         'owner': {'kind': 'HorizontalPodAutoscaler', 'name': 'hpa-app-cpu', 'namespace': m.NS, 'uid': hpa['metadata']['uid']}}
                    if case == 'persistent':
                        e.update(timestamp_utc=g['timestamp_utc'], count=1 + int(clock[0])); g['events'] = [e]
                    elif case == 'pre-ready': g['pod_metrics'][0]['timestamp'] = pod['ready_conditions'][0]['lastTransitionTime']
                    elif case == 'missing': g['pod_metrics'] = []
                    elif case == 'stale': g['pod_metrics'][0]['timestamp'] = pod['creationTimestamp']
                    elif case in {'zero', 'unknown'}: g['pod_metrics'][0]['containers'][0]['usage']['cpu'] = '0' if case == 'zero' else 'unknown'
                    elif case == 'metric-container': g['pod_metrics'][0]['containers'][0]['name'] = 'other'
                    elif case == 'metric-duplicate': g['pod_metrics'] *= 2
                    elif case == 'hpa-metric': hpa['status']['currentMetrics'][0]['containerResource']['container'] = 'other'
                    elif case == 'hpa-value-zero': hpa['status']['currentMetrics'][0]['containerResource']['current']['averageValue'] = '0'
                    elif case == 'owner': hpa['metadata']['ownerReferences'] = [{'kind': 'ScaledObject'}]
                    elif case == 'spec': hpa['spec']['maxReplicas'] = 3
                    elif case in {'other-warning', 'other-hpa', 'wrong-uid', 'no-owner'}:
                        if case == 'other-warning': e['reason'] = 'Unhealthy'
                        elif case == 'other-hpa': e['owner']['name'] = 'other'
                        elif case == 'wrong-uid': e['owner']['uid'] = 'other'
                        else: e.pop('owner')
                        g['events'] = [e]
                    elif case == 'pod-unready': g['pods'][0]['ready'] = False
                    elif case == 'db': g['postgres']['query_ok'] = False
                    elif case == 'node': g['nodes'][0]['conditions']['MemoryPressure'] = 'True'
                    elif case == 'resource': g['admission']['conservative_sum']['limits']['cpu'] = 2
                    elif case == 'ready-transition':
                        g['pod_metrics'] = []
                        if clock[0]: pod['ready_conditions'][0]['lastTransitionTime'] = g['timestamp_utc']
                    elif case == 'generation': hpa['status']['observedGeneration'] = 2
                    elif case == 'hpa-replaced':
                        g['pod_metrics'] = []
                        if clock[0]: hpa['metadata']['uid'] = 'replaced'
                    elif case == 'history-lost':
                        g['pod_metrics'] = []
                        if not clock[0]: g['events'] = [e]
                    elif case == 'no-active': hpa['status']['conditions'] = [c for c in hpa['status']['conditions'] if c['type'] != 'ScalingActive']
                    elif case == 'no-current': hpa['status']['currentMetrics'] = []
                    elif case == 'no-able': hpa['status']['conditions'] = [c for c in hpa['status']['conditions'] if c['type'] != 'AbleToScale']
                    return g
                f.runtime.guard = snapshot
                with patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(m.time, 'time', side_effect=lambda: 1000 + clock[0]):
                    with self.assertRaises((ValueError, KeyError)):
                        m.healthy_initialize(f.runtime, plan(), lambda _: calls.append(1), rows.append,
                                             clock=lambda: clock[0], wait=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
                self.assertEqual(calls, [])
                self.assertLessEqual(clock[0], 90)
                self.assertFalse(rows[-1]['runtime_preflight_passed'])
                self.assertFalse(any(r['record'] in {'healthy_journey_intent', 'healthy_initialization_complete'} for r in rows))
                if case in {'other-warning', 'other-hpa', 'wrong-uid', 'no-owner', 'pod-unready', 'db', 'node', 'resource', 'owner', 'spec', 'generation'}:
                    self.assertEqual(clock[0], 0)  # No settling exemption for other failures.

    def test_cpu_settling_then_journey_preserves_history_and_rejects_recurrence(self):
        for case in ('success', 'new-warning', 'count-recurred', 'hpa-regressed'):
            with self.subTest(case=case):
                f, now, rows, calls = self.preparation(), [0], [], []
                guard = f.runtime.guard; positive, _, _ = self.positive_journey(f)
                stamp = lambda at: m.datetime.fromtimestamp(at, m.timezone.utc).isoformat()
                def snapshot():
                    g = guard(); g['cpu_preparation_pods'][0]['creationTimestamp'] = stamp(970)
                    g['cpu_preparation_pods'][0]['ready_conditions'][0]['lastTransitionTime'] = stamp(980)
                    g['cpu_hpa']['metadata']['creationTimestamp'] = stamp(970)
                    for c in g['cpu_hpa']['status']['conditions']: c['lastTransitionTime'] = stamp(995)
                    g['events'] = [{'type': 'Warning', 'reason': 'FailedGetContainerResourceMetric', 'uid': 'startup-warning',
                        'first_timestamp_utc': stamp(985), 'timestamp_utc': stamp(990), 'count': 1,
                        'owner': {'kind': 'HorizontalPodAutoscaler', 'name': 'hpa-app-cpu', 'namespace': m.NS, 'uid': 'cpu-hpa'}}]
                    if now[0] == 0: g['pod_metrics'][0]['timestamp'] = stamp(980)  # Pre-Ready window.
                    if calls:
                        if case == 'new-warning': g['events'][0]['uid'] = 'new-warning'
                        if case == 'count-recurred': g['events'][0]['count'] += 1
                        if case == 'hpa-regressed':
                            g['cpu_hpa']['status']['conditions'][1].update(status='False', reason='FailedGetContainerResourceMetric')
                    self.assertLessEqual(f.runtime.collection_deadline.at - now[0], 30)
                    return g
                def journey(timeout):
                    self.assertEqual(now[0], 30)
                    self.assertEqual(rows[-1]['record'], 'healthy_journey_intent')
                    calls.append(1); f.no_admin.clear()
                    return positive(timeout)
                f.runtime.guard = snapshot
                with patch.object(m.time, 'monotonic', side_effect=lambda: now[0]), patch.object(m.time, 'time', side_effect=lambda: 1000 + now[0]):
                    kwargs = {'clock': lambda: now[0], 'wait': lambda s: now.__setitem__(0, now[0] + s)}
                    if case == 'success':
                        result = m.healthy_initialize(f.runtime, plan(), journey, rows.append, **kwargs)
                        self.assertTrue(result['ready_for_keda_authentication'])
                        self.assertFalse(result['runtime_preflight_passed'])
                    else:
                        with self.assertRaises(ValueError): m.healthy_initialize(f.runtime, plan(), journey, rows.append, **kwargs)
                        self.assertFalse(any(e['record'] == 'healthy_initialization_complete' for e in rows))
                self.assertEqual(calls, [1])
                self.assertEqual([e['status'] for e in rows if e['record'] == 'cpu_preparation_poll'][:3], ['pending', 'pending', 'ready'])

    def test_preparation_authority_does_not_claim_full_preflight_or_keda_auth(self):
        v = plan() | {'identity_client_id': '00000000-0000-0000-0000-000000000000'}
        a = approval() | {'healthy_gate_passed': False, 'runtime_preflight_passed': False, 'plan_sha256': m.digest(v)}
        now = m.datetime(2026, 10, 29, tzinfo=m.timezone.utc)
        with patch.dict(os.environ, {'P9_AZURE_APPROVED': t8.identity()['source_sha']}):
            m.preparation_gate(t8.identity(), v, a, [], now)
            with self.assertRaises(ValueError): m.execution_gate(t8.identity(), v, a, [], now)
            with self.assertRaises(ValueError): m.preparation_gate(t8.identity(), v, a | {'normal_test_passed': False}, [], now)

    def test_healthy_journey_once_then_readonly_admin_native_ingestion_rate_polling(self):
        f, now, rows, journeys = self.preparation(), [0], [], []
        f.missing = {'target'}
        positive, _, _ = self.positive_journey(f)
        def journey(timeout):
            self.assertEqual(rows[-1]['record'], 'healthy_journey_intent')
            self.assertEqual(f.runtime.admin_observations['target']['status'], 'uninitialized')
            journeys.append(timeout)
            return positive(timeout)
        def wait(seconds):
            now[0] += seconds
            f.no_admin.clear(); f.missing.clear()
            f.one_sample = {'target'} if now[0] == f.runtime.v['scrape_seconds'] else set()
        with patch.object(m.time, 'monotonic', side_effect=lambda: now[0]), patch.object(m.time, 'time', side_effect=lambda: 1000 + now[0]):
            result = m.healthy_initialize(f.runtime, plan(), journey, rows.append, clock=lambda: now[0], wait=wait)
        self.assertEqual(journeys, [90])
        self.assertEqual([r['signal']['status'] for r in rows if r['record'] == 'healthy_telemetry_poll'], ['uninitialized', 'uninitialized', 'observed'])
        self.assertFalse(result['runtime_preflight_passed'])
        self.assertTrue(result['ready_for_keda_authentication'])
        self.assertGreater(result['ingress_http_records'], 0)
        self.assertEqual(result['authorization_checks'], result['ingress_http_records'])
        self.assertEqual(len(result['correlated_attempt_checks']), 9)
        self.assertIn(3, result['correlated_attempt_checks'].values())  # Git is not HTTP1/check1.
        self.assertEqual(result['auxiliary_checks'], 3)

    def test_archived_p8_normal_cluster_suffix_and_wrong_ingress_rejection(self):
        # Replay only archived normal log shapes into the synthetic journey;
        # this is a source regression, not new P9 Azure positive evidence.
        with tarfile.open(ROOT / 'docs/evidence/p8-controlled-cascade-20261029/raw-evidence.tar.gz') as archive:
            raw = json.load(archive.extractfile('calibration-05/path.json'))
        normal = {label: next(r for r in raw['proxies'][label] if r['status'] == 200 and r['detail'] == 'via_upstream')
                  for label in ('target', 'ingress')}
        self.assertEqual(normal['target']['cluster'], 'inbound|8080||;')
        cluster = normal['ingress']['cluster']
        self.assertEqual(cluster, 'outbound|3000||forgejo-http.forgejo.svc.cluster.local;')
        cases = [('archived-normal', cluster, 200, 'via_upstream', True),
                 ('wrong-service', cluster.replace('forgejo-http', 'other'), 200, 'via_upstream', False),
                 ('wrong-namespace', cluster.replace('.forgejo.svc', '.other.svc'), 200, 'via_upstream', False),
                 ('wrong-port', cluster.replace('|3000|', '|3001|'), 200, 'via_upstream', False),
                 ('double-semicolon', cluster + ';', 200, 'via_upstream', False),
                 ('extra-suffix', cluster + 'other', 200, 'via_upstream', False),
                 ('denied', cluster, 403, 'ext_authz_denied', False),
                 ('error', cluster, 403, 'ext_authz_error', False)]
        for name, ingress_cluster, status, detail, accepted in cases:
            with self.subTest(case=name):
                f, rows, calls = self.preparation(), [], []
                positive, _, logs = self.positive_journey(f)
                def journey(timeout):
                    calls.append(1)
                    path = positive(timeout)
                    f.no_admin.clear()
                    for r in logs['proxies']['target']['target']: r.update(normal['target'])
                    for r in logs['proxies']['ingress']['ingress']:
                        r.update(normal['ingress'], cluster=ingress_cluster, status=status, detail=detail)
                    return path
                if accepted:
                    result = m.healthy_initialize(f.runtime, plan(), journey, rows.append)
                    self.assertTrue(result['ready_for_keda_authentication'])
                    self.assertFalse(result['runtime_preflight_passed'])
                    self.assertEqual(result['authorization_checks'], result['ingress_http_records'])
                    self.assertEqual(len(result['correlated_attempt_checks']), 9)
                    self.assertIn(3, result['correlated_attempt_checks'].values())
                    self.assertEqual(result['target_requests'], result['authorization_checks'])
                else:
                    with self.assertRaisesRegex(ValueError, 'healthy ingress path denied/mismapped'):
                        m.healthy_initialize(f.runtime, plan(), journey, rows.append)
                    self.assertFalse(any(r['record'] == 'healthy_initialization_complete' for r in rows))
                self.assertEqual(calls, [1])

    def test_observed_telemetry_without_new_shared_checks_is_rejected(self):
        f, rows, calls = self.preparation(), [], []
        f.no_admin.clear(); f.traffic = 7  # Pre-existing observed series/counters.
        _, path, _ = self.positive_journey(f)
        def no_traffic(_):
            calls.append(1)
            return path
        with self.assertRaisesRegex(ValueError, 'shared path missing/zero'):
            m.healthy_initialize(f.runtime, plan(), no_traffic, rows.append)
        self.assertEqual(calls, [1])
        self.assertTrue(any(r['record'] == 'healthy_telemetry_poll' and r['signal']['status'] == 'observed' for r in rows))
        self.assertFalse(any(r['record'] == 'healthy_initialization_complete' for r in rows))

    def test_existing_observed_series_requires_and_accepts_new_correlated_path(self):
        f, rows = self.preparation(), []
        f.no_admin.clear(); f.traffic = 7
        positive, _, logs = self.positive_journey(f)
        def journey(timeout):
            path = positive(timeout)
            logs['proxies']['ingress']['ingress'].append({'status': 0, 'detail': 'filter_chain_not_found', 'cluster': None, 'duration_ms': 0})
            return path
        result = m.healthy_initialize(f.runtime, plan(), journey, rows.append)
        self.assertEqual(result['authorization_checks'], result['ingress_http_records'])
        self.assertGreater(result['authorization_checks'], 9)
        self.assertTrue(result['ready_for_keda_authentication'])
        self.assertFalse(result['runtime_preflight_passed'])
        self.assertEqual(len(result['log_delta']['proxies']['ingress']), result['ingress_http_records'] + 1)

    def test_healthy_positive_evidence_rejects_missing_denied_rotated_unattributed(self):
        cases = ('no-checks', 'no-target', 'no-ingress', 'check-mismatch', 'target-mismatch', 'missing-attempt',
                 'denied-check', 'controlled-deny', 'credential-leak', 'body-leak', 'bypassed-haproxy', 'duplicate-check',
                 'unknown-attempt', 'unknown-operation', 'null-correlation', 'old-check', 'target-deny', 'target-cluster',
                 'ingress-deny', 'ingress-cluster', 'counter-mismatch', 'lost-aligned-records', 'app-rotation', 'target-rotation', 'ingress-rotation',
                 'client-failure', 'client-missing-attempt', 'client-source', 'client-no-auxiliary-scope')
        for case in cases:
            with self.subTest(case=case):
                f, rows, calls = self.preparation(), [], []
                if case != 'lost-aligned-records': f.no_admin.clear()
                positive, path, logs = self.positive_journey(f)
                if case.endswith('-rotation'):
                    if case == 'app-rotation': logs['checks'] = [{'check_id': 'before'}]
                    else: logs['proxies'][case.split('-')[0]][case.split('-')[0]] = [{'status': 999}]
                def journey(timeout):
                    calls.append(1)
                    if case.endswith('-rotation'):
                        if case == 'app-rotation': logs['checks'] = []
                        else: logs['proxies'][case.split('-')[0]][case.split('-')[0]] = []
                    positive(timeout)
                    checks = logs['checks']; target = logs['proxies']['target']['target']; ingress = logs['proxies']['ingress']['ingress']
                    if case == 'no-checks': checks.clear()
                    elif case == 'no-target': target.clear()
                    elif case == 'no-ingress': ingress.clear()
                    elif case == 'check-mismatch': checks.pop()
                    elif case == 'target-mismatch': target.pop()
                    elif case == 'missing-attempt':
                        missing = checks[0]['attempt_id']
                        for c in checks:
                            if c['attempt_id'] == missing: c.update(operation_id=checks[-1]['operation_id'], attempt_id=checks[-1]['attempt_id'])
                    elif case == 'denied-check': checks[0]['decision'] = 'DENY'
                    elif case == 'controlled-deny': checks[0]['controlled_deny'] = True
                    elif case == 'credential-leak': checks[0]['credential_values_absent'] = False
                    elif case == 'body-leak': checks[0]['body_absent'] = False
                    elif case == 'bypassed-haproxy': checks[0]['haproxy_hop'] = False
                    elif case == 'duplicate-check': checks[1]['check_id'] = checks[0]['check_id']
                    elif case == 'unknown-attempt': checks[-1]['attempt_id'] = 'foreign-attempt-1'
                    elif case == 'unknown-operation': checks[-1]['operation_id'] = 'foreign'
                    elif case == 'null-correlation': checks[-1].update(operation_id=None, attempt_id=None)
                    elif case == 'old-check': checks[0]['timestamp_utc'] = '2026-10-28T00:00:00Z'
                    elif case == 'target-deny': target[0]['status'] = 403
                    elif case == 'target-cluster': target[0]['cluster'] = 'inbound|9090||'
                    elif case == 'ingress-deny': ingress[0].update(status=403, detail='ext_authz_denied')
                    elif case == 'ingress-cluster': ingress[0]['cluster'] = 'outbound|3000||other.example.com'
                    elif case == 'counter-mismatch': f.traffic = 0
                    elif case == 'lost-aligned-records':
                        f.no_admin.clear()
                        checks.pop(0); target.pop(0); ingress.pop(0)
                    elif case.startswith('client-'):
                        client = m.p8.p4.rows(path)
                        if case == 'client-failure': client[-1]['completion'] = 'failed'
                        elif case == 'client-missing-attempt': client = [r for r in client if r.get('record') != 'attempt']
                        elif case == 'client-source': client[0]['source_sha'] = 'f' * 40
                        else: client = [r for r in client if r.get('record') != 'auxiliary_event']
                        path.write_text(''.join(json.dumps(r) + '\n' for r in client))
                    return path
                with self.assertRaises(ValueError): m.healthy_initialize(f.runtime, plan(), journey, rows.append)
                self.assertEqual(calls, [1])
                self.assertFalse(any(r['record'] == 'healthy_initialization_complete' for r in rows))

    def test_auxiliary_correlation_is_opt_in_for_existing_curl_and_git(self):
        import subprocess
        script = (ROOT / 'tests/e2e/forgejo-developer-journey.sh').read_text()
        curl = script[script.index('gate_curl() {'):script.index('# request CURL_CONFIG_LINE')]
        git = script[script.index('dev_git() {'):script.index('\nexpect_remote_ref()')]
        with tempfile.TemporaryDirectory() as directory:
            bindir = Path(directory, 'bin'); bindir.mkdir()
            git_stub = bindir / 'git'
            git_stub.write_text('#!/usr/bin/env bash\nprintf "%s|%s\\n" "${GIT_CONFIG_VALUE_2:-none}" "${GIT_CONFIG_VALUE_3:-none}"\n')
            git_stub.chmod(0o755)
            body = '''
set -euo pipefail
curl() { printf '%s\\n' "$*"; }
mono() { echo 1; }
fail() { exit 1; }
RUN_ID=synthetic-run
DEV_USER=test DEV_TOKEN=private-test
ENDPOINT=https://example.invalid FORGEJO_URL=https://example.invalid
GIT_TRANSPORT_ARGS=()
GIT_TIMEOUT_SECONDS=1 GIT_KILL_AFTER_SECONDS=1
'''
            calls = '''
gate_curl -q https://example.invalid
dev_git ls-remote https://example.invalid
JOURNEY_GATE_CORRELATION=1 JOURNEY_GATE_AUX_CORRELATION=1
gate_curl -q https://example.invalid
dev_git ls-remote https://example.invalid
OP_ACTIVE=1 ATTEMPT_ACTIVE=1 OP_ID=synthetic-run-operation-1
gate_curl -q https://example.invalid
dev_git ls-remote https://example.invalid
ATTEMPT_ACTIVE=0
gate_curl -q https://example.invalid
dev_git ls-remote https://example.invalid
'''
            result = subprocess.run(['bash'], input=body + curl + git + calls, text=True, capture_output=True, check=True,
                                    env=dict(os.environ, JOURNEY_DIR=directory, PATH=str(bindir) + ':' + os.environ.get('PATH', os.defpath)))
            lines = result.stdout.splitlines()
            self.assertNotIn('x-operation-id', lines[0]); self.assertEqual(lines[1], 'none|none')
            for i in (2, 3, 6, 7): self.assertIn('synthetic-run-auxiliary-attempt-1', lines[i])
            for i in (4, 5): self.assertIn('synthetic-run-operation-1-attempt-1', lines[i])
            self.assertNotIn('private-test', result.stdout)

    def test_initialize_prejourney_failures_publish_safe_distinct_diagnostics(self):
        cases = [('configuration', 'configuration', 'ValueError', 'validation_failed'),
                 ('warning', 'readiness_resource_guard', 'InitializationGuardError', 'warning_event'),
                 ('command-timeout', 'configuration', 'TimeoutExpired', 'command_timeout'),
                 ('command-failed', 'configuration', 'CalledProcessError', 'command_failed'),
                 ('budget', 'configuration', 'SnapshotBudgetExceeded', 'snapshot_command_budget_exceeded'),
                 ('stats', 'baseline_stats', 'RuntimeError', 'runtime_failure'),
                 ('logs', 'baseline_logs', 'RuntimeError', 'runtime_failure'),
                 ('unknown', 'configuration', 'BaseException', 'unknown_failure')]
        for case, stage, exception_class, code in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as d:
                f, a = self.preparation(), approval()
                a.update(healthy_gate_passed=False, runtime_preflight_passed=False)
                private = Path(d, 'private'); private.mkdir(mode=0o700)
                output, ledger = Path(d, 'output'), Path(d, 'ledger.jsonl')
                retained = {'record': 'retained-negative'}
                ledger.write_text(json.dumps(retained) + '\n')
                secret = 'Bearer private-test-token credential=private-test-body ' + str(private)
                f.runtime.prom_token = secret
                def failed(*args, **kwargs):
                    raise ValueError(secret)
                if case == 'configuration': f.runtime.configuration = failed
                elif case == 'warning':
                    guard = f.runtime.guard()
                    # Actual archived HPA reason/timestamp, synthetic guard payload.
                    guard['events'] = [{'type': 'Warning', 'reason': 'FailedComputeMetricsReplicas',
                                        'timestamp_utc': '2026-10-29T02:44:27Z', 'message': secret}]
                    f.runtime.guard = lambda: guard
                elif case in {'command-timeout', 'command-failed', 'budget'}:
                    runtime_k = m.Runtime.k
                    def command(*args, **kwargs):
                        return runtime_k(f.runtime, 'get', 'pods', secret)
                    f.runtime.configuration = command
                elif case in {'stats', 'logs'}:
                    def unavailable(*args, **kwargs):
                        raise RuntimeError(secret)
                    if case == 'stats': f.runtime.stats = unavailable
                    else:
                        # Exercise the inherited baseline log collector through k().
                        def unavailable_logs(actual):
                            with patch.object(f.runtime, 'k', side_effect=RuntimeError(secret)):
                                return m.p8.Runtime.logs(f.runtime, actual)
                        f.runtime.logs = unavailable_logs
                else:
                    def unknown(*args, **kwargs):
                        raise type('PrivateClass' + secret, (Exception,), {})(secret)
                    f.runtime.configuration = unknown
                with patch.object(m, 'Runtime', return_value=f.runtime), patch.object(m.p8.subprocess, 'run') as process:
                    if case == 'command-timeout':
                        process.side_effect = m.p8.subprocess.TimeoutExpired(['kubectl', secret], 15, output=secret, stderr=secret)
                    elif case == 'command-failed':
                        process.side_effect = m.p8.subprocess.CalledProcessError(1, ['kubectl', secret], output=secret, stderr=secret)
                    if case == 'budget':
                        # The real k() rejects the existing shared 30s budget before executing.
                        with patch.object(m.time, 'monotonic', side_effect=lambda: f.runtime.collection_deadline.at + 1):
                            with self.assertRaises(ValueError):
                                m.initialize(t8.identity(), plan(), a, Path(d, 'context'), private, output, ledger)
                        process.assert_not_called()
                    else:
                        with self.assertRaises(Exception):
                            m.initialize(t8.identity(), plan(), a, Path(d, 'context'), private, output, ledger)
                    commands = [c.args[0] for c in process.call_args_list]
                    self.assertFalse(any('forgejo-developer-journey.sh' in ' '.join(c) for c in commands))
                    if case == 'command-timeout':
                        self.assertGreater(process.call_args.kwargs['timeout'], 0)
                        self.assertLessEqual(process.call_args.kwargs['timeout'], 15)
                rows = [json.loads(line) for line in (output / 'events.jsonl').read_text().splitlines()]
                failures = [r for r in rows if r['record'] == 'healthy_initialization_failure']
                self.assertEqual(len(failures), 1)
                failure = failures[0]
                self.assertEqual(failure['record'], 'healthy_initialization_failure')
                self.assertEqual((failure['stage'], failure['exception_class'], failure['error_code']),
                                 (stage, exception_class, code))
                self.assertGreaterEqual(failure['elapsed_seconds'], failure['stage_elapsed_seconds'])
                self.assertGreaterEqual(failure['stage_elapsed_seconds'], 0)
                self.assertFalse(failure['runtime_preflight_passed'])
                self.assertFalse(failure['ready_for_keda_authentication'])
                self.assertFalse(failure['measured_denominator'])
                self.assertFalse(a['runtime_preflight_passed']); self.assertFalse(a['healthy_gate_passed'])
                self.assertIsNone(f.runtime.prom_token)
                self.assertEqual([json.loads(line) for line in ledger.read_text().splitlines()], [retained] + rows)
                public = json.dumps(rows) + ledger.read_text()
                for sensitive in (secret, str(private), 'private-test-token', 'private-test-body', 'PrivateClass'):
                    self.assertNotIn(sensitive, public)
                trace = private / 'initialization-failure.txt'
                self.assertEqual(trace.stat().st_mode & 0o777, 0o600)
                self.assertIn('Traceback', trace.read_text())
                if case in {'configuration', 'command-timeout', 'command-failed', 'unknown'}:
                    self.assertIn(secret, trace.read_text())

    def test_initialization_elapsed_and_private_diagnostic_write_failure(self):
        f, now, rows = self.preparation(), [10], []
        def configuration(*args, **kwargs):
            self.assertEqual(f.runtime.collection_deadline.at, 40)  # Unchanged 30s budget.
            now[0] = 12
            raise ValueError('private detail')
        f.runtime.configuration = configuration
        with self.assertRaises(ValueError):
            m.healthy_initialize(f.runtime, plan(), lambda _: self.fail('journey must not run'), rows.append,
                                 clock=lambda: now[0])
        self.assertEqual(rows[0]['elapsed_seconds'], 2)
        self.assertEqual(rows[0]['stage_elapsed_seconds'], 2)
        with tempfile.TemporaryDirectory() as d:
            private = Path(d, 'private'); private.mkdir(mode=0o700)
            trace = private / 'initialization-failure.txt'
            trace.write_text('retained private diagnostic')
            output, ledger = Path(d, 'output'), Path(d, 'ledger')
            a = approval() | {'healthy_gate_passed': False, 'runtime_preflight_passed': False}
            with patch.object(m, 'Runtime', return_value=f.runtime), patch.object(m.p8.subprocess, 'run') as workload:
                # Use a separate failure without depending on the real monotonic clock.
                with patch.object(f.runtime, 'configuration', side_effect=ValueError('private detail')):
                    with self.assertRaisesRegex(ValueError, 'private detail'):
                        m.initialize(t8.identity(), plan(), a, Path(d, 'context'), private, output, ledger)
                workload.assert_not_called()
            self.assertEqual(trace.read_text(), 'retained private diagnostic')
            published = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertEqual(published[0]['error_code'], 'validation_failed')
            self.assertEqual(published[1]['error_code'], 'private_diagnostic_write_failed')
            self.assertNotIn('private detail', ledger.read_text())
            self.assertFalse(published[0]['runtime_preflight_passed'])

    def test_initialize_entrypoint_binds_once_ledger_and_existing_warmup_journey(self):
        f, a, invoked = self.preparation(), approval(), []
        a.update(healthy_gate_passed=False, runtime_preflight_passed=False)
        positive, path, _ = self.positive_journey(f)
        def subprocess_run(command, **kwargs):
            invoked.append((command, kwargs))
            f.no_admin.clear()
            positive(90)
            destination = Path(kwargs['env']['RESULTS_ROOT'], 'healthy-unit', 'events.jsonl')
            destination.parent.mkdir(parents=True)
            destination.write_bytes(path.read_bytes())
        with tempfile.TemporaryDirectory() as d:
            private = Path(d, 'private'); private.mkdir(mode=0o700)
            output, ledger = Path(d, 'output'), Path(d, 'initialization.jsonl')
            with patch.object(m, 'Runtime', return_value=f.runtime) as constructor, patch.object(m.p8.subprocess, 'run', side_effect=subprocess_run):
                m.initialize(t8.identity(), plan(), a, Path(d, 'context.json'), private, output, ledger)
                self.assertEqual(constructor.call_args.kwargs, {'preparation': True})
                with self.assertRaisesRegex(ValueError, 'already consumed'):
                    m.initialize(t8.identity(), plan(), a, Path(d, 'context.json'), private, Path(d, 'retry'), ledger)
            self.assertEqual(len(invoked), 1)
            self.assertEqual(invoked[0][0], ['timeout', '--signal=TERM', '--kill-after=5s', '90s', 'bash', str(ROOT / 'tests/e2e/forgejo-developer-journey.sh'), 'create'])
            self.assertEqual(invoked[0][1]['env']['RESULT_PHASE'], 'warmup')
            self.assertEqual(invoked[0][1]['env']['JOURNEY_GATE_AUX_CORRELATION'], '1')
            self.assertEqual(invoked[0][1]['timeout'], 100)
            self.assertFalse(a['runtime_preflight_passed']); self.assertFalse(a['healthy_gate_passed'])
            rows = [json.loads(r) for r in ledger.read_text().splitlines()]
            self.assertFalse(rows[0]['measured_denominator'])
            self.assertEqual(rows[-1]['record'], 'healthy_initialization_complete')

    def test_healthy_poll_timeout_and_invariant_failure_never_repeat_workload(self):
        for case in ('timeout', 'hostname', 'image', 'controller', 'headroom'):
            with self.subTest(case=case):
                f, now, journeys, rows = self.preparation(), [0], [], []
                positive, _, _ = self.positive_journey(f)
                def journey(timeout):
                    journeys.append(1)
                    return positive(timeout)
                def wait(seconds):
                    now[0] += seconds
                    if case == 'hostname': f.policy['spec']['rules'][0]['to'][0]['operation']['hosts'] = ['other.example.com']
                    if case == 'image': f.pods[0]['spec']['containers'][0]['image'] = 'wrong'
                    if case == 'controller': f.hpa['metadata']['ownerReferences'] = [{'kind': 'Unknown'}]
                    if case == 'headroom':
                        old = f.guard; f.runtime.guard = lambda: old() | {'node_headroom': []}
                with patch.object(m.time, 'monotonic', side_effect=lambda: now[0]), self.assertRaises(ValueError):
                    m.healthy_initialize(f.runtime, plan(), journey, rows.append, clock=lambda: now[0], wait=wait)
                self.assertEqual(journeys, [1])
                self.assertLessEqual(now[0], plan()['ingestion_seconds'] + 3 * plan()['scrape_seconds'])
                self.assertFalse(any(r['record'] == 'healthy_initialization_complete' for r in rows))

    def test_failed_journey_preserves_request_logs_without_polling_or_retry(self):
        f, rows, calls = self.preparation(), [], []
        def failed(_):
            calls.append(1)
            raise RuntimeError('synthetic journey failure')
        with self.assertRaisesRegex(RuntimeError, 'synthetic journey failure'):
            m.healthy_initialize(f.runtime, plan(), failed, rows.append)
        self.assertEqual(calls, [1])
        self.assertEqual([r['record'] for r in rows], ['cpu_preparation_poll', 'healthy_journey_intent', 'healthy_journey_accounting', 'healthy_initialization_failure'])
        self.assertFalse(rows[-1]['measured_denominator'])
        self.assertIn('log_delta', rows[-2])
        self.assertEqual(rows[-1]['stage'], 'healthy_journey')
        self.assertEqual(rows[-1]['error_code'], 'runtime_failure')

    def test_unsafe_preparation_prevents_journey(self):
        f = self.preparation(); f.pods[0]['spec']['containers'][0]['image'] = 'wrong'
        with patch.object(m.p8.subprocess, 'run') as workload, self.assertRaises(ValueError):
            m.healthy_initialize(f.runtime, plan(), workload, lambda _: None)
        workload.assert_not_called()

    def test_new_uid_lifetime_counters_include_pre_first_observation_traffic(self):
        first, last = PathEvidenceTests().fixture()
        # Move all lifetime evidence to a new UID, whose first stat snapshot is
        # already nonzero after planned traffic. No synthetic zero snapshot.
        last['stats']['new'] = last['stats'].pop('u1')
        last['stats']['u1'] = copy.deepcopy(first['stats']['u1'])
        last['logs']['proxies']['target']['new'] = last['logs']['proxies']['target'].pop('u1')
        last['logs']['proxies']['target']['u1'] = []
        missing = copy.deepcopy(first); missing['logs']['proxies']['target']['new'] = []
        missing['target_inventory'] = [{'uid': 'u1'}, {'uid': 'new'}]
        report = m.path_accounting('C3', [first, missing, last])
        self.assertEqual((report['target_admitted'], report['target_rejected']), (4, 8))
        self.assertNotIn('new', missing['stats'])
        last['logs']['proxies']['target']['new'].pop()
        with self.assertRaises(ValueError): m.path_accounting('C3', [first, missing, last])
        with self.assertRaisesRegex(ValueError, 'final counters'): m.path_accounting('C3', [first, missing])

    def test_query_http501_body_preserved_and_bearer_redacted(self):
        import io
        f, rows = LiveFixture(), []
        f.runtime.emit, f.runtime.prom_token = rows.append, 'secret-test-bearer'
        error = m.urllib.error.HTTPError('https://example.invalid', 501, 'unsupported', {}, io.BytesIO(b'{"error":"unsupported secret-test-bearer"}'))
        with patch.object(m.p8.p7, 'http_json', side_effect=error), self.assertRaises(m.urllib.error.HTTPError):
            m.Runtime.prom(f.runtime, m.scale_query(plan()))
        self.assertEqual(rows[0]['record'], 'prometheus_query_intent')
        self.assertEqual(rows[1]['http_status'], 501)
        self.assertIn('unsupported', rows[1]['body']); self.assertNotIn('secret-test-bearer', json.dumps(rows))
        error.close()
        f.runtime.collection_deadline.at = 100
        with patch.object(m.time, 'monotonic', return_value=100), patch.object(m.p8.p7, 'http_json') as request:
            with self.assertRaisesRegex(ValueError, 'query budget exceeded'):
                m.Runtime.prom(f.runtime, m.scale_query(plan()))
            request.assert_not_called()

    def test_existing_request_helper_records_delete_id_before_empty204(self):
        import subprocess
        script = (ROOT / 'tests/e2e/forgejo-developer-journey.sh').read_text()
        request = script[script.index('gate_curl() {'):script.index('\nexpect_json()')]
        with tempfile.TemporaryDirectory() as directory:
            # Fake curl asserts intent already durable before touching response.
            fake = '''
set -euo pipefail
utc() { echo timestamp; }
mono() { echo 1; }
fail() { exit 1; }
curl() {
  jq -e 'select(.record=="request_intent" and .path=="/users/dev/tokens/17" and .method=="DELETE")' "$JOURNEY_DIR/request-events.jsonl" >/dev/null
  : >"$JOURNEY_DIR/response.json"
  printf 204
}
CURL_TRANSPORT_ARGS=()
API=https://example.invalid/api/v1
'''
            subprocess.run(['bash'], input=fake + request + '\nrequest \'header = "Authorization: token private-test"\' DELETE /users/dev/tokens/17 204\n',
                           env=dict(os.environ, JOURNEY_DIR=directory), text=True, capture_output=True, check=True)
            rows = [json.loads(r) for r in Path(directory, 'request-events.jsonl').read_text().splitlines()]
            self.assertEqual(rows[-1]['http_status'], 204)
            self.assertEqual(rows[-1]['response_bytes'], 0)
            self.assertNotIn('private-test', json.dumps(rows))
        token_id = script.index('TOKEN_ID="$(jq -er')
        self.assertLess(token_id, script.index('user_json="$(request "$DEV_AUTH" GET /user'))
        self.assertIn('TOKEN_ID=%q', script)


class DemandRecoveryTests(unittest.TestCase):
    def test_open_loop_does_not_wait_for_previous_wave(self):
        rows = []
        items = [{'id': f'w{i}-issue-0', 'kind': 'issue', 'at': i * .01, 'wave': i} for i in range(3)]
        def issue(*_):
            time.sleep(.05)
            return {'semantic_result': True, 'status': 200, 'duration_seconds': .05}
        with patch.object(m, 'schedule', return_value=items):
            m.drive({'mitigation_seconds': .01, 'recovery_seconds': .1}, 'C0', issue, issue, rows.append, lambda _: None)
        ops = sorted([r for r in rows if r['record'] == 'operation'], key=lambda r: r['at'])
        self.assertLess(ops[-1]['issued'], ops[0]['completed'])
        self.assertAlmostEqual(ops[-1]['scheduled'] - ops[0]['scheduled'], .02)

    def test_three_windows_with_new_issue_and_git_demand(self):
        result = m.recovery(plan(), events(), lambda *_: True)
        self.assertEqual(result['status'], 'recovered')
        self.assertEqual(result['release_command'], 180)
        self.assertEqual(result['converged'], 181)
        self.assertEqual(result['first_good_window'], 190)
        self.assertEqual(result['confirmation'], 220)
        self.assertEqual(result['campaign']['scheduled'], 1800)

    def test_fast_denial_low_cpu_or_rejection_not_recovery(self):
        e = events()
        for row in e:
            if row['record'] == 'operation':
                row['attempts'][0].update(semantic_result=False, status=403, duration_seconds=.001)
        self.assertEqual(m.recovery(plan(), e, lambda *_: True)['status'], 'not recovered within observation window')

    def test_no_observations_or_fault_convergence_not_recovery(self):
        self.assertEqual(m.recovery(plan(), events(), lambda *_: False)['status'], 'not recovered within observation window')
        e = [x for x in events() if x['record'] != 'convergence']
        self.assertEqual(m.recovery(plan(), e, lambda *_: True)['status'], 'not recovered within observation window')

    def test_paused_reduced_missing_cancelled_git_or_lag_not_recovery(self):
        for case in ('cancel', 'lag', 'git-fail', 'slow-command'):
            e = events()
            for row in e:
                if row['record'] != 'operation' or row['at'] < 180:
                    continue
                if case == 'cancel': row.update(issued=None, outcome='not-issued', attempts=[])
                elif case == 'lag':
                    row.update(issued=row['issued'] + 1, completed=row['completed'] + 1)
                    row['attempts'][0]['started'] += 1; row['attempts'][0]['ended'] += 1
                elif case == 'git-fail' and row['kind'] == 'git': row['attempts'][0]['semantic_result'] = False
                elif case == 'slow-command' and row['kind'] == 'issue':
                    row['completed'] += .2; row['attempts'][0]['ended'] += .2; row['attempts'][0]['duration_seconds'] += .2
            with self.subTest(case=case):
                self.assertEqual(m.recovery(plan(), e, lambda *_: True)['status'], 'not recovered within observation window')
        for change in ('missing-row', 'changed-schedule'):
            e = events()
            if change == 'missing-row': e.pop()
            else: e[0]['items'] = e[0]['items'][:-25]
            with self.assertRaises(ValueError): m.recovery(plan(), e, lambda *_: True)

    def test_p7_command_vs_end_to_end_queue_backoff_latency(self):
        e = events(); row = next(x for x in e if x['record'] == 'operation')
        row['issued'] += .1; row['attempts'][0]['started'] += .1; row['attempts'][0]['ended'] += .1; row['completed'] += .1
        report, *_ = m.demand_report(plan(), e)
        self.assertAlmostEqual(report['command_seconds'][0], .05)
        self.assertAlmostEqual(report['end_to_end_seconds'][0], .15)
        row['completed'] = row['issued']
        with self.assertRaises(ValueError): m.demand_report(plan(), e)


if __name__ == '__main__':
    unittest.main()
