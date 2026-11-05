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


def plan():
    return m.load(ROOT / 'experiments/fixtures/critical-bulk/candidate.json')


def synthetic(arm):
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
    invariants.update(stable_revision=t8.identity()['stable_revision'], haproxy_image_id='sha256:fixture', haproxy_processes=1, haproxy_threads=1, haproxy_maxconn=256)
    identity = t8.identity() | {'source_sha': 'a' * 40}
    binding = m.binding(identity, v, F, invariants)
    return {'plan': v, 'arm': arm, 'source_sha': 'a' * 40, 'binding': binding, 'binding_sha256': m.digest(binding),
            'runtime_before': copy.deepcopy(invariants), 'runtime_after': copy.deepcopy(invariants),
            'events': events, 'samples': samples, 'environment': 'local', 'healthy_classification': True, 'tls': True, 'native_auth': True,
            'guards': {k: {'observed': True, 'competing_bottleneck': False, 'start': 0, 'end': 10, 'evidence_sha256': 'b' * 64} for k in m.GUARDS},
            'accounting': {'classes': counts, 'classifier_escapes': 0, 'dropped_logs': 0, 'counter_lifetime_unchanged': True,
                           'frontend': len(scheduled), 'queue_start': 0, 'queue_end': 0, 'inflight_start': 0, 'inflight_end': 0, 'haproxy_retries': 0}}


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
        b['environment'] = 'azure'; b['managed_samples'] = []
        with self.assertRaises(ValueError): m.validate(b)
        b['managed_samples'] = [{'at': at, 'sample_at': at} for at in (-1, 10, 50)]
        self.assertEqual(m.validate(b)['status'], 'observation-insufficient')

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


if __name__ == '__main__': unittest.main()
