"""Cost-free P9 safety, schedule, ownership and recovery boundary regressions."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
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
                       'counter_semantics': 'per-pod-active-overflow-counter-rate-per-second', 'controller_ownership_verified': True,
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
        baseline = {'scenario': {'max_requests': 2, 'hold_ms': 1000},
                    'targets': [{'uid': 'target', 'name': 'ext-authz-sim-abc', 'mapping': {'capacity': 2}}]}
        manifest = {'source_sha': identity['source_sha'], 'identity': identity, 'plan': v,
                    'transport': m.p8.p7.operations.transport('https://forgejo.example.com', 'azure-aks', None), 'fixture_sha256': 'a' * 64, 'arm': 'C0', 'phase': 'measured',
                    'schedule_sha256': m.digest(m.schedule(v)), 'slo_sha256': m.hashlib.sha256(m.SLO.read_bytes()).hexdigest(),
                    'render_sha256': {a: m.digest(m.render(identity, v, a)) for a in m.ARMS}, 'baseline': baseline}
        rows = events(v)
        snapshots = []
        for at in range(-5, 366, 5):
            guard = t8.metric_guard()
            guard['admission'] = {'pods': [{}], 'conservative_sum': {'requests': {'cpu': .15, 'memory': 1}, 'limits': {'cpu': .5, 'memory': 1}}}
            guard['runtime_images'] = {'target': {'app': 'sha'}}
            actual = copy.deepcopy(baseline)
            healthy = at >= 185
            if healthy:
                actual['scenario'].update(max_requests=1024, hold_ms=0);actual['targets'][0]['mapping']['capacity'] = 1024
            snapshots.append({'record': 'snapshot', 'at': at, 'end': at + .1, 'epoch': at + 1000, 'healthy': healthy,
                'timestamp_utc': '2026-10-29T00:00:00Z', 'configuration': actual, 'guard': guard,
                'signal': {'status': 'observed', 'query_sha256': m.digest(m.scale_query(v)),
                           'pods': [{'pod_uid': 'target', 'pod': 'ext-authz-sim-abc', 'status': 'observed', 'rate': 0,
                                     'active': 0, 'samples': 4, 'timestamp': at + 1000}]}})
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
        for case in ('missing', 'stale', 'warmup-existing', 'controller-error'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                rows = self.fixture(directory)
                snapshot = next(e for e in rows if e['record'] == 'snapshot')
                if case == 'missing': snapshot['signal']['pods'] = []
                elif case == 'stale': snapshot['signal']['pods'][0]['timestamp'] -= 1000
                elif case == 'warmup-existing': snapshot['signal'].update(status='warming-new-pod', missing_uids=['target'])
                else: snapshot['guard']['events'] = [{'reason': 'FailedComputeMetricsReplicas'}]
                (Path(directory) / 'events.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
                with patch.object(m, 'path_accounting', side_effect=lambda *_: {'admitted_checks': [], 'checks': 1800}), self.assertRaises(ValueError):
                    m.validate(directory)


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
