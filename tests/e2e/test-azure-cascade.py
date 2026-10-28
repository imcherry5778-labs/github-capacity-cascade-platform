"""Cost-free Azure ownership, admission, real stat mapping and evidence failure cases."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('cascade', ROOT / 'scripts/azure-cascade.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def identity():
    root = '/subscriptions/' + 'a' * 8 + '-aaaa-aaaa-aaaa-' + 'a' * 12 + '/resourceGroups/test/providers/'
    return {'campaign': 'p8test', 'source_sha': 'a' * 40, 'cluster_resource_id': root + 'Microsoft.ContainerService/managedClusters/test',
            'cluster_uid': 'a' * 8 + '-aaaa-aaaa-aaaa-' + 'a' * 12, 'revision': 'asm-1-30', 'stable_revision': 'b' * 40,
            'ext_authz_image': 'test.azurecr.io/ext-authz-sim@sha256:' + 'c' * 64,
            'ingress_selector': {'istio': 'aks-istio-ingressgateway-external'}, 'pg_resource_id': root + 'Microsoft.DBforPostgreSQL/flexibleServers/test',
            'forgejo_hostname': 'forgejo.example.com'}


def metric_guard():
    hpa = {'currentReplicas': 1, 'desiredReplicas': 1, 'conditions': [
        {'type': 'AbleToScale', 'status': 'True'}, {'type': 'ScalingActive', 'status': 'True'},
        {'type': 'ScalingLimited', 'status': 'True', 'reason': 'TooFewReplicas'}], 'currentMetrics': [{
        'type': 'ContainerResource', 'containerResource': {'name': 'cpu', 'container': 'app', 'current': {'averageUtilization': 1}}}]}
    pod = {'name': 'ext-authz-sim-abc', 'uid': 'target', 'ready': True, 'phase': 'Running', 'reason': None,
           'containers': [{'name': 'app', 'ready': True, 'restarts': 0, 'last_termination': None}]}
    return {'timestamp_utc': '2026-10-28T15:00:00Z', 'pods': [pod], 'nodes': [{'conditions': {'Ready': 'True', 'MemoryPressure': 'False', 'DiskPressure': 'False', 'PIDPressure': 'False'}}],
            'node_metrics': [{'usage': {'cpu': '1m'}}], 'node_headroom': [{'schedulable': True, 'cpu_free': 1, 'memory_free': 1024**3}],
            'pod_metrics': [{'metadata': {'namespace': a.NS, 'name': pod['name']}, 'timestamp': '2026-10-28T15:00:00Z', 'window': '15s',
                             'containers': [{'name': 'app', 'usage': {'cpu': '1m', 'memory': '10Mi'}}]}],
            'postgres': {'query_ok': True, 'connections': 4, 'max_connections': 100, 'reserved': 5}, 'hpa': hpa, 'events': []}


def hpa_spec():
    return next(x['spec'] for x in a.render(identity())['fixtures.json']['items'] if x['kind'] == 'HorizontalPodAutoscaler')


def guards():
    values = [metric_guard() for _ in range(3)]
    for i, v in enumerate(values):
        v['pod_metrics'][0]['timestamp'] = f'2026-10-28T15:0{i}:00Z'
        v['timestamp_utc'] = v['pod_metrics'][0]['timestamp']
    return values


class SourceTests(unittest.TestCase):
    def test_azure_boundary_and_reuse(self):
        rendered = a.render(identity())
        items = rendered['fixtures.json']['items']
        self.assertEqual({o['metadata'].get('namespace') for o in items if o['kind'] != 'Namespace'}, {a.NS})
        self.assertFalse({'PersistentVolumeClaim', 'Gateway', 'VirtualService', 'EnvoyFilter', 'ScaledObject'} & {o['kind'] for o in items})
        app = next(o for o in items if o['kind'] == 'Deployment' and o['metadata']['name'] == 'ext-authz-sim')
        self.assertEqual(app['spec']['template']['spec']['containers'][0]['imagePullPolicy'], 'IfNotPresent')
        self.assertNotIn('proxy.istio.io/config', app['spec']['template']['metadata']['annotations'])
        self.assertEqual(hpa_spec()['metrics'][0]['type'], 'ContainerResource')
        self.assertEqual(rendered['policy.json']['metadata']['namespace'], 'aks-istio-ingress')
        self.assertEqual(rendered['policy.json']['spec']['action'], 'CUSTOM')
        self.assertNotIn('forgejo', {o['metadata']['name'] for o in items})

    def test_haproxy_config_has_required_final_newline_and_two_targets_fit_with_validation_init(self):
        items = a.render(identity())['fixtures.json']['items']
        config = next(o['data']['haproxy.cfg'] for o in items if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'haproxy')
        self.assertTrue(config.endswith('\n'))
        self.assertIn('frontend check\n  option httpclose\n', config)
        self.assertIn('ext-authz-sim.p8-shared-gate.svc.cluster.local:8080', config)
        pods = []
        for obj in items:
            if obj['kind'] not in {'Deployment', 'Pod'}: continue
            template = obj['spec']['template'] if obj['kind'] == 'Deployment' else obj
            for index in range(2 if obj['metadata']['name'] == 'ext-authz-sim' else 1):
                pod = copy.deepcopy(template)
                pod['metadata'].update(namespace=a.NS, name=obj['metadata']['name'] + str(index), uid=obj['metadata']['name'] + str(index))
                if obj['metadata']['name'] == 'ext-authz-sim':
                    annotations = template['metadata']['annotations']
                    resources = {'requests': {'cpu': annotations['sidecar.istio.io/proxyCPU'], 'memory': annotations['sidecar.istio.io/proxyMemory']},
                                 'limits': {'cpu': annotations['sidecar.istio.io/proxyCPULimit'], 'memory': annotations['sidecar.istio.io/proxyMemoryLimit']}}
                    pod['spec']['initContainers'] = [{'name': 'istio-validation', 'resources': resources},
                                                     {'name': 'istio-proxy', 'restartPolicy': 'Always', 'resources': resources}]
                pods.append(pod)
        admitted = a.admission(identity(), pods)
        self.assertEqual(len(admitted['pods']), 4)
        self.assertAlmostEqual(admitted['conservative_sum']['limits']['cpu'], 1.45)

    def test_unpinned_or_non_acr_image_rejected(self):
        for image in ('test.azurecr.io/ext-authz-sim:latest', 'docker.io/test@sha256:' + 'a' * 64):
            value = identity(); value['ext_authz_image'] = image
            with self.assertRaises(ValueError): a.render(value)

    def test_mesh_merge_preserves_original_and_rejects_managed_or_argo_owner(self):
        original = {'metadata': {'name': 'istio-shared-configmap-asm-1-30', 'namespace': 'aks-istio-system'},
                    'data': {'other': 'preserve', 'mesh': json.dumps({'defaultConfig': {'holdApplicationUntilProxyStarts': True}, 'extensionProviders': [{'name': 'other'}]})}}
        before = copy.deepcopy(original)
        result = a.mesh_overlay(original, identity())
        self.assertEqual(original, before)
        self.assertEqual(result['data']['other'], 'preserve')
        merged = json.loads(result['data']['mesh'])
        self.assertTrue(merged['defaultConfig']['holdApplicationUntilProxyStarts'])
        self.assertEqual(merged['extensionProviders'][0], {'name': 'other'})
        for change in ({'name': 'istio-asm-1-30'}, {'ownerReferences': [{}]}, {'labels': {'argocd.argoproj.io/instance': 'stable'}}):
            modified = copy.deepcopy(original); modified['metadata'].update(change)
            with self.assertRaises(ValueError): a.mesh_overlay(modified, identity())

    def test_native_sidecar_and_init_admission_includes_limits_overhead(self):
        c = lambda name, cpu, memory: {'name': name, 'resources': {'requests': {'cpu': cpu, 'memory': memory}, 'limits': {'cpu': cpu, 'memory': memory}}}
        pod = {'metadata': {'namespace': a.NS, 'name': 'target', 'uid': 'uid', 'labels': {'p8.campaign': 'p8test'}},
               'spec': {'containers': [c('app', '50m', '64Mi')], 'initContainers': [c('istio-proxy', '100m', '128Mi') | {'restartPolicy': 'Always'}],
                        'overhead': {'cpu': '10m', 'memory': '16Mi'}}}
        result = a.admission(identity(), [pod])
        self.assertAlmostEqual(result['conservative_sum']['requests']['cpu'], .16)
        self.assertEqual(result['conservative_sum']['requests']['memory'], 208 * 1024**2)
        pod['spec']['initContainers'][0]['resources']['limits']['cpu'] = '2'
        with self.assertRaises(ValueError): a.admission(identity(), [pod])

    def test_unowned_or_unbounded_admission_rejected(self):
        pod = {'metadata': {'namespace': 'forgejo', 'labels': {'p8.campaign': 'p8test'}}, 'spec': {}}
        with self.assertRaises(ValueError): a.admission(identity(), [pod])
        with self.assertRaises(ValueError): a.admission(identity(), [])

    def test_actual_alt_stat_name_and_endpoint_mapping(self):
        cluster = {'name': 'inbound|unusual||', 'alt_stat_name': 'actual.inbound_8080',
                   'load_assignment': {'endpoints': [{'socket_address': {'port_value': 8080}}]},
                   'circuit_breakers': {'thresholds': [{'max_requests': 2}]}}
        stats = {'stats': [{'name': 'cluster.actual.inbound_8080.' + suffix, 'value': 0} for suffix in a.p4.SUFFIXES] + [{'histograms': {}}]}
        mapping, values = a.target_mapping({'configs': [{'cluster': cluster}]}, stats, 2)
        self.assertEqual(mapping['cluster_name'], cluster['name'])
        self.assertEqual(len(values), 5)
        for dump, payload, capacity in (({}, stats, 2), ({'configs': [{'cluster': cluster}]}, {'stats': []}, 2),
                                        ({'configs': [{'cluster': cluster}]}, stats, 3)):
            with self.assertRaises(ValueError): a.target_mapping(dump, payload, capacity)

    def test_original_dst_requires_actual_8080_listener_route_binding(self):
        cluster = {'name': 'inbound|8080||', 'alt_stat_name': 'inbound|8080||;', 'type': 'ORIGINAL_DST',
                   'circuit_breakers': {'thresholds': [{'max_requests': 2}]}}
        dump = {'configs': [{'cluster': cluster}]}
        stats = {'stats': [{'name': 'cluster.inbound|8080||;.' + suffix, 'value': 0} for suffix in a.p4.SUFFIXES]}
        listener = {'filter_chain_match': {'destination_port': 8080}, 'route_config': {'route': {'cluster': cluster['name']}}}
        mapping, _ = a.target_mapping(dump, stats, 2, listener)
        self.assertEqual(mapping['endpoint_mapping'], 'listener-port-8080-to-ORIGINAL_DST')
        for binding in (None, {'filter_chain_match': {'destination_port': 3000}, 'route': {'cluster': cluster['name']}},
                        {'filter_chain_match': {'destination_port': 8080}, 'route': {'cluster': 'other'}}):
            with self.assertRaises(ValueError): a.target_mapping(dump, stats, 2, binding)

    def test_proxy_log_deltas_use_independent_pod_streams(self):
        before = {'checks': [], 'proxies': {'target': {'target1': [200]}, 'ingress': {'gateway1': [200], 'gateway2': [201]}}}
        after = {'checks': [], 'proxies': {'target': {'target1': [200, 503, 503]}, 'ingress': {'gateway1': [200, 403], 'gateway2': [201, 403]}}}
        delta = a.path_delta(before, after)
        self.assertEqual(delta['proxies']['ingress'], [403, 403])
        self.assertEqual(delta['proxies']['target'], [503, 503])
        self.assertEqual(delta['proxy_streams']['ingress']['gateway2'], {'before': 1, 'after': 2})

    def test_log_rotation_or_pod_change_is_not_silently_sliced(self):
        before = {'checks': [], 'proxies': {'ingress': {'gateway1': [201]}}}
        for streams in ({'gateway1': [200, 403]}, {'gateway2': [201, 403]}):
            with self.assertRaises(ValueError): a.path_delta(before, {'checks': [], 'proxies': {'ingress': streams}})

    def test_window_and_bounded_demand(self):
        value = a.load(ROOT / 'experiments/fixtures/shared-gate/azure-saturation.json')
        a.plan(value)
        for change in ({'waves': 1}, {'waves': 121}, {'wave_interval_seconds': 0}, {'concurrency': 100}, {'hold_ms': 3000}):
            with self.assertRaises(ValueError): a.plan(value | change)

    def test_no_runtime_without_explicit_source_acknowledgement(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(a.p7, 'command') as command:
            with self.assertRaises(ValueError): a.Runtime(identity())
            command.assert_not_called()

    def test_runtime_uses_supported_aks_show_target_arguments(self):
        value = identity()
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'kubeconfig'; config.touch(mode=0o600)
            def command(args):
                if args[0] == 'git': return value['source_sha'] if args[-1] == 'HEAD' else ''
                if args[0] == 'az': return json.dumps({'fqdn': 'actual.aks.example.com', 'serviceMeshProfile': {'istio': {'revisions': [value['revision']]}}, 'agentPoolProfiles': [{'enableAutoScaling': False}]})
                return 'https://actual.aks.example.com' if 'config' in args else value['cluster_uid']
            with patch.dict(os.environ, {'P8_AZURE_APPROVED': value['source_sha'], 'KUBECONFIG': str(config)}), patch.object(a.p7, 'command', side_effect=command) as mocked, patch.object(a, 'datetime', wraps=a.datetime) as clock:
                clock.now.return_value = a.datetime(2026, 10, 29, tzinfo=a.timezone.utc)
                a.Runtime(value)
            az_args = next(c.args[0] for c in mocked.call_args_list if c.args[0][0] == 'az')
            self.assertEqual(az_args, ['az', 'aks', 'show', '--resource-group', 'test', '--name', 'test', '-o', 'json'])

    def test_exclusive_evidence_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'negative.json'
            a.save(path, {'status': 'failed'})
            with self.assertRaises(FileExistsError): a.save(path, {'status': 'passed'})
            self.assertEqual(a.load(path), {'status': 'failed'})


def gateway_fixture():
    policy = a.render(identity())['policy.json']
    policy['metadata']['uid'] = 'live-policy-uid'
    policy_id = 'istio-ext-authz-p8-shared-gate-ns[aks-istio-ingress]-policy[p8-shared-gate]-rule[0]'
    # Istio 1.30 CUSTOM output: RBAC shadow matcher followed by metadata-gated ext_authz.
    rule = {'permissions': [{'and_rules': {'rules': [{'or_rules': {'rules': [
        {'header': {'name': ':authority', 'string_match': {'exact': host, 'ignore_case': True}}}
        for host in ('forgejo.example.com', 'forgejo.example.com:443')]}}]}}], 'principals': [{'any': True}]}
    filters = [{'name': 'envoy.filters.http.rbac', 'typed_config': {
        'shadow_rules_stat_prefix': 'istio_ext_authz_', 'shadow_rules': {'action': 'DENY', 'policies': {policy_id: rule}}}},
        {'name': 'envoy.filters.http.ext_authz', 'typed_config': {'filter_enabled_metadata': {
            'filter': 'envoy.filters.http.rbac', 'path': [{'key': 'istio_ext_authz_shadow_effective_policy_id'}],
            'value': {'string_match': {'prefix': 'istio-ext-authz-p8-shared-gate'}}}}}]
    return policy, {'configs': [{'listener': {'filter_chains': [{'http_filters': filters}]}}]}, filters, rule


class HostnameScopeTests(unittest.TestCase):
    def test_render_exact_hostname_and_https_port_suffix_only(self):
        policy = a.render(identity())['policy.json']['spec']
        self.assertEqual(policy['rules'], [{'to': [{'operation': {'hosts': ['forgejo.example.com', 'forgejo.example.com:443']}}]}])
        hosts = policy['rules'][0]['to'][0]['operation']['hosts']
        for authority in ('forgejo.example.com', 'forgejo.example.com:443', 'FORGEJO.EXAMPLE.COM:443'):
            self.assertIn(authority.lower(), hosts)
        for authority in ('other.example.com', 'forgejo.example.com.evil.test', 'forgejo.example.com-extra',
                          'sub.forgejo.example.com', 'forgejo.example.com:444'):
            self.assertNotIn(authority.lower(), hosts)

    def test_identity_rejects_wildcard_port_url_and_non_normalized_hostname(self):
        for hostname in ('*', '*.example.com', 'forgejo.example.com*', 'forgejo.example.com:443',
                         'https://forgejo.example.com', 'Forgejo.example.com', 'forgejo.example.com.', 'forgejo..example.com'):
            with self.subTest(hostname=hostname), self.assertRaises(ValueError):
                a.render(identity() | {'forgejo_hostname': hostname})

    def test_normalized_url_hostname_with_optional_443_and_dns_override(self):
        for endpoint in ('https://forgejo.example.com', 'https://FORGEJO.EXAMPLE.COM:443'):
            with patch.dict(os.environ, {'FORGEJO_URL': endpoint, 'JOURNEY_DNS_OVERRIDE': '1.2.3.4'}, clear=True):
                self.assertEqual(a.measurement_transport(identity())['endpoint'], endpoint)

    def test_hostname_mismatch_stops_before_runtime_or_probe(self):
        for endpoint in ('https://other.example.com', 'https://forgejo.example.com.evil.test'):
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'FORGEJO_URL': endpoint}, clear=True), \
                 patch.object(a, 'Runtime') as runtime:
                with self.assertRaisesRegex(ValueError, 'hostname differs'):
                    a.measure(identity(), a.load(ROOT / 'experiments/fixtures/shared-gate/azure-saturation.json'),
                              Path(directory) / 'run', 'calibration', 1)
                runtime.assert_not_called()
                self.assertTrue((Path(directory) / 'run/invocation-failure.json').is_file())

    def test_live_policy_and_effective_scope(self):
        policy, listeners, _, _ = gateway_fixture()
        scope = a.gateway_scope(identity(), policy, listeners)
        self.assertEqual(scope['hosts'], ['forgejo.example.com', 'forgejo.example.com:443'])
        self.assertEqual(scope['policy_uid'], 'live-policy-uid')
        self.assertEqual(scope['filter_chains'], 1)

    def test_live_unrestricted_wrong_host_selector_provider_or_extra_rule_rejected(self):
        for kind in ('empty', 'wildcard', 'prefix', 'other_host', 'selector', 'provider', 'extra_rule'):
            policy, listeners, _, _ = gateway_fixture()
            if kind == 'empty': policy['spec']['rules'] = [{}]
            if kind in {'wildcard', 'prefix', 'other_host'}:
                policy['spec']['rules'][0]['to'][0]['operation']['hosts'] = [{'wildcard': '*', 'prefix': 'forgejo.example.com*', 'other_host': 'other.example.com'}[kind]]
            if kind == 'selector': policy['spec']['selector']['matchLabels'] = {'istio': 'other-gateway'}
            if kind == 'provider': policy['spec']['provider']['name'] = 'other-provider'
            if kind == 'extra_rule': policy['spec']['rules'].append({})
            with self.subTest(kind=kind), self.assertRaises(ValueError): a.gateway_scope(identity(), policy, listeners)

    def test_effective_unrestricted_wrong_host_match_or_provider_gate_rejected(self):
        for kind in ('any', 'prefix', 'suffix', 'present', 'other_host', 'extra_permission', 'extra_policy', 'ungated', 'provider', 'missing_rbac'):
            policy, listeners, filters, rule = gateway_fixture()
            if kind == 'any': rule['permissions'] = [{'any': True}]
            if kind in {'prefix', 'suffix', 'present', 'other_host'}:
                matcher = {'prefix': {'string_match': {'prefix': 'forgejo.example.com', 'ignore_case': True}},
                           'suffix': {'string_match': {'suffix': '.example.com', 'ignore_case': True}},
                           'present': {'present_match': True}, 'other_host': {'string_match': {'exact': 'other.example.com', 'ignore_case': True}}}[kind]
                rule['permissions'] = [{'header': {'name': ':authority', **matcher}}]
            if kind == 'extra_permission': rule['permissions'].append({'any': True})
            if kind == 'extra_policy': filters[0]['typed_config']['shadow_rules']['policies']['istio-ext-authz-p8-shared-gate-other'] = {'permissions': [{'any': True}]}
            if kind == 'ungated': del filters[1]['typed_config']['filter_enabled_metadata']
            if kind == 'provider': filters[1]['typed_config']['filter_enabled_metadata']['value']['string_match']['prefix'] = 'istio-ext-authz-other'
            if kind == 'missing_rbac': filters.pop(0)
            with self.subTest(kind=kind), self.assertRaises(ValueError): a.gateway_scope(identity(), policy, listeners)


class GuardTests(unittest.TestCase):
    def test_lower_minimum_is_not_upper_replica_cap(self):
        result = a.guard_validation(guards(), hpa_spec())
        self.assertEqual(result['metric_update_span_seconds'], 120)

    def test_freshness_uses_reported_metric_window_and_still_requires_updates(self):
        values = guards()
        for v in values:
            v['pod_metrics'][0]['window'] = '1m3.442s'
            stamp = a.p7.utc(v['timestamp_utc'])
            v['timestamp_utc'] = (stamp + a.p7.dt.timedelta(seconds=70)).isoformat()
        result = a.guard_validation(values, hpa_spec())
        self.assertEqual(result['resource_metric_age_max_seconds'], 70)
        for window in ('15s', '0s', '5m', 'unknown'):
            bad = copy.deepcopy(values)
            bad[1]['pod_metrics'][0]['window'] = window
            with self.assertRaises(ValueError): a.guard_validation(bad, hpa_spec())

    def test_metric_errors_upper_cap_and_low_window_rejected(self):
        for kind in ('missing_metric', 'upper_cap', 'stale', 'scale', 'wrong_container'):
            values = guards()
            if kind == 'missing_metric': values[1]['hpa']['currentMetrics'] = []
            if kind == 'upper_cap': values[1]['hpa']['conditions'][2]['reason'] = 'TooManyReplicas'
            if kind == 'stale':
                for v in values: v['pod_metrics'][0]['timestamp'] = values[0]['pod_metrics'][0]['timestamp']
            if kind == 'scale': values[1]['hpa']['currentReplicas'] = 2
            if kind == 'wrong_container': values[1]['hpa']['currentMetrics'][0]['containerResource']['container'] = 'istio-proxy'
            with self.subTest(kind=kind), self.assertRaises(ValueError): a.guard_validation(values, hpa_spec())

    def test_competing_resource_scheduling_db_restart_fail_closed(self):
        for kind in ('pressure', 'headroom', 'db', 'restart', 'sidecar_metric'):
            values = guards()
            if kind == 'pressure': values[1]['nodes'][0]['conditions']['MemoryPressure'] = 'True'
            if kind == 'headroom': values[1]['node_headroom'][0]['cpu_free'] = 0
            if kind == 'db': values[1]['postgres']['connections'] = 100
            if kind == 'restart': values[1]['pods'][0]['containers'][0]['restarts'] = 1
            if kind == 'sidecar_metric': values[1]['pod_metrics'][0]['containers'] = []
            with self.subTest(kind=kind), self.assertRaises(ValueError): a.guard_validation(values, hpa_spec())

    def test_pod_resource_hpa_is_rejected(self):
        spec = hpa_spec(); spec['metrics'][0]['type'] = 'Resource'
        with self.assertRaises(ValueError): a.guard_validation(guards(), spec)


def run_fixture(directory):
    config = {'max_requests': 1, 'hold_ms': 100, 'logical_operations': 2, 'concurrency': 2, 'waves': 4, 'wave_interval_seconds': 30}
    actual = {'forgejo_hostname': identity()['forgejo_hostname'], 'scenario': config, 'targets': [{'uid': 'target', 'mapping': {'stat_names': sorted('cluster.actual.' + k for k in a.p4.SUFFIXES)}}], 'hpa_spec': hpa_spec()}
    fingerprint = {'source_sha': 'a' * 40, 'configuration': actual, 'identity': identity()}
    stats = {'target': {'cluster.actual.' + k: 0 for k in a.p4.SUFFIXES}}
    hp = {'status': 'no check'} | {k: 0 for k in a.p4.HAPROXY_FIELDS}
    before = {'stats': copy.deepcopy(stats), 'haproxy': copy.deepcopy(hp), 'guard': guards()[0], 'timestamp_utc': '2026-10-28T15:00:00Z'}
    events = [{'record': 'run_start', 'run_id': 'run', 'phase': 'no-retry', 'max_attempts': 1,
               'fingerprint': a.digest(fingerprint), 'timestamp_utc': before['timestamp_utc'], 'transport': a.p7.operations.transport('https://forgejo.example.com', 'azure-aks', None)}]
    checks = []
    for wave in range(4):
        for i in range(2):
            op = f'op{wave}-{i}'
            result = {'start_monotonic': 1, 'end_monotonic': 2, 'duration_seconds': 1, 'status': 200 if i == 0 else 403,
                      'semantic_result': i == 0, 'error_class': 'none' if i == 0 else 'http_status'}
            events += [{'record': 'attempt', 'operation_id': op, 'attempt_id': op + '-attempt-1', 'attempt_index': 1, **result},
                       {'record': 'operation', 'operation_id': op, 'attempt_count': 1, 'success': i == 0, 'duration_seconds': 1}]
            if i == 0:
                checks.append({'record': 'authorization_check', 'check_id': op, 'timestamp_utc': before['timestamp_utc'],
                               'operation_id': op, 'attempt_id': op + '-attempt-1', 'decision': 'ALLOW', 'header_names': ['authorization'],
                               'credential_values_absent': True, 'body_absent': True, 'haproxy_hop': True, 'controlled_deny': False})
        events.append({'record': 'git_read', 'operation_id': f'git{wave}', 'attempt_id': f'git{wave}-attempt-1', 'semantic_result': False})
    active = copy.deepcopy(stats); active['target']['cluster.actual.upstream_rq_active'] = 1
    events += [{'record': 'guard', 'snapshot': guards()[1]}, {'record': 'target', 'stats': active},
               {'record': 'sentinel', 'result': {'semantic_result': True, 'start_monotonic': 1, 'end_monotonic': 2}},
               {'record': 'run_end', 'run_id': 'run', 'completed': True, 'timestamp_utc': '2026-10-28T15:02:00Z'}]
    stats['target']['cluster.actual.upstream_rq_total'] = 4
    stats['target']['cluster.actual.upstream_rq_active_overflow'] = 8
    hp.update(hrsp_2xx=4, hrsp_5xx=8)
    proxy = lambda code, detail: {'status': str(code), 'detail': detail, 'cluster': 'selected', 'duration_ms': '1'}
    path = {'checks': checks, 'proxies': {'target': [proxy(200, 'via_upstream')] * 4 + [proxy(503, 'upstream_reset{overflow}')] * 8,
                                        'ingress': [proxy(200, 'via_upstream')] * 4 + [proxy(403, 'ext_authz_error')] * 8}}
    for name, value in {'configuration.json': fingerprint, 'before.json': before,
                        'after.json': {'stats': stats, 'haproxy': hp, 'guard': guards()[2], 'timestamp_utc': '2026-10-28T15:02:00Z'}, 'path.json': path}.items():
        a.save(Path(directory) / name, value)
    (Path(directory) / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))


class EvidenceTests(unittest.TestCase):
    def test_mechanism_does_not_self_certify_missing_cloud_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            run_fixture(directory)
            result = a.validate_run(directory)
            self.assertEqual(result['logical_operations'], 8)
            self.assertEqual(result['dispatched_checks'], 12)
            self.assertEqual(result['admitted_checks'], 4)
            self.assertEqual(result['active_rejections'], 8)
            self.assertEqual(result['validity'], 'pending-cloud-confounder-review')
            with self.assertRaises(FileNotFoundError): a.reviewed_run(directory)

    def test_missing_signal_cannot_be_boolean_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            run_fixture(directory)
            result = a.validate_run(directory)
            a.save(Path(directory) / 'confounder-review.json', {'source_sha': result['source_sha'], 'fingerprint': result['fingerprint'],
                   'window_utc': result['window_utc'], 'competing_bottleneck': False, 'missing_required_signals': [], 'signals': {}})
            with self.assertRaises(ValueError): a.reviewed_run(directory)

    def test_review_requires_exact_source_window_and_immutable_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            run_fixture(directory)
            result = a.validate_run(directory)
            events = Path(directory) / 'events.jsonl'
            review = {'source_sha': result['source_sha'], 'fingerprint': result['fingerprint'], 'window_utc': result['window_utc'],
                      'competing_bottleneck': False, 'missing_required_signals': [], 'signals': {signal: {
                          'file': 'events.jsonl', 'sha256': a.hashlib.sha256(events.read_bytes()).hexdigest(), 'samples': 3,
                          'status': 'observed', 'start_utc': result['window_utc']['start'], 'end_utc': result['window_utc']['end'],
                          'interpretation': 'synthetic unit-test observation only'} for signal in a.REVIEW_SIGNALS}}
            a.save(Path(directory) / 'confounder-review.json', review)
            self.assertEqual(a.reviewed_run(directory)['validity'], 'valid')
            with events.open('a') as stream: stream.write('\n')
            with self.assertRaises(ValueError): a.reviewed_run(directory)

    def test_cloud_queries_use_measured_window_and_actual_cluster(self):
        with tempfile.TemporaryDirectory() as directory:
            run_fixture(directory)
            query_identity = {'cluster_resource_id': identity()['cluster_resource_id'], 'prometheus_cluster': 'actual-aks',
                              'prometheus_endpoint': 'https://actual.koreacentral.prometheus.monitor.azure.com', 'log_workspace_id': 'a' * 8 + '-aaaa-aaaa-aaaa-' + 'a' * 12}
            plan = a.cloud_plan(directory, query_identity)
            self.assertEqual(plan['service_active_window_utc']['start'], '2026-10-28T15:00:00Z')
            self.assertIn('cluster="actual-aks"', plan['promql']['forgejo_scrape'])
            self.assertNotIn('or vector(0)', str(plan))
            query_identity['cluster_resource_id'] = query_identity['cluster_resource_id'] + '-other'
            with self.assertRaises(ValueError): a.cloud_plan(directory, query_identity)

    def test_retry_failures_cannot_skip_second_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            run_fixture(directory)
            path = Path(directory) / 'events.jsonl'
            rows = a.p4.rows(path)
            rows[0].update(phase='retry', max_attempts=2)
            path.write_text(''.join(json.dumps(e) + '\n' for e in rows))
            with self.assertRaises(ValueError): a.validate_run(directory)

    def test_pair_rejects_replica_config_drift(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            run_fixture(first); run_fixture(second)
            path = Path(second) / 'events.jsonl'
            rows = a.p4.rows(path); rows[0].update(phase='retry', max_attempts=2)
            path.write_text(''.join(json.dumps(e) + '\n' for e in rows))
            frozen = a.load(Path(first) / 'configuration.json')
            changed = copy.deepcopy(frozen); changed['configuration']['targets'].append({'uid': 'second-replica'})
            (Path(second) / 'configuration.json').write_text(json.dumps(changed))
            with patch.object(a, 'reviewed_run', side_effect=[{'logical_operations': 8}, {'logical_operations': 8}]), self.assertRaises(ValueError):
                a.paired(first, second, frozen)

    def test_unmatched_tls_is_retained_outside_scoped_http_check_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            run_fixture(directory)
            path = Path(directory) / 'path.json'; value = a.load(path)
            value['proxies']['ingress'].append({'status': 0, 'detail': 'filter_chain_not_found', 'cluster': '-', 'duration_ms': '0'})
            path.write_text(json.dumps(value)); result = a.validate_run(directory)
            self.assertEqual(result['non_http_ingress_records_retained'], 1)
            self.assertEqual(result['dispatched_checks'], 12)
            self.assertEqual(len(a.load(path)['proxies']['ingress']), 13)

    def test_other_zero_status_or_client_transport_failure_is_not_excluded(self):
        for detail in ('upstream_reset', 'connection_termination'):
            with tempfile.TemporaryDirectory() as directory:
                run_fixture(directory)
                path = Path(directory) / 'path.json'; value = a.load(path)
                value['proxies']['ingress'].append({'status': 0, 'detail': detail, 'cluster': '-', 'duration_ms': '0'})
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): a.validate_run(directory)

    def test_frozen_hostname_must_match_recorded_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            run_fixture(directory)
            path = Path(directory) / 'configuration.json'
            fingerprint = a.load(path)
            fingerprint['identity']['forgejo_hostname'] = 'other.example.com'
            fingerprint['configuration']['forgejo_hostname'] = 'other.example.com'
            path.write_text(json.dumps(fingerprint))
            events = Path(directory) / 'events.jsonl'
            rows = a.p4.rows(events); rows[0]['fingerprint'] = a.digest(fingerprint)
            events.write_text(''.join(json.dumps(e) + '\n' for e in rows))
            with self.assertRaisesRegex(ValueError, 'hostname differs'): a.validate_run(directory)

    def test_counter_mapping_and_orphan_attempt_failure(self):
        for kind in ('overflow', 'haproxy_retry', 'unknown_check', 'pending', 'failed_run'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                run_fixture(directory)
                name = 'after.json' if kind in {'overflow', 'haproxy_retry', 'pending'} else 'path.json'
                path = Path(directory) / name
                value = a.load(path)
                if kind == 'overflow': value['stats']['target']['cluster.actual.upstream_rq_active_overflow'] = 0
                if kind == 'pending': value['stats']['target']['cluster.actual.upstream_rq_pending_overflow'] = 1
                if kind == 'haproxy_retry': value['haproxy']['wretr'] = 1
                if kind == 'unknown_check': value['checks'][0]['attempt_id'] = 'unknown'
                if kind == 'failed_run':
                    with (Path(directory) / 'events.jsonl').open('a') as stream: stream.write(json.dumps({'record': 'run_failure'}) + '\n')
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): a.validate_run(directory)


class TransportTests(unittest.TestCase):
    def test_verified_curl_keeps_hostname_under_dns_override(self):
        result = Mock(returncode=0, stdout=b'{}\n200')
        env = {'FORGEJO_URL': 'https://forgejo.example.com', 'JOURNEY_DNS_OVERRIDE': '1.2.3.4'}
        with patch.dict(os.environ, env, clear=True), patch.object(a.subprocess, 'run', return_value=result) as run:
            a.request('/private/path', {'Authorization': 'token secret'})
        args = run.call_args.args[0]
        self.assertEqual(args[:2], ['curl', '-q'])
        self.assertIn('forgejo.example.com:443:1.2.3.4', args)
        self.assertIn('https://forgejo.example.com/private/path', args)
        self.assertFalse({'-k', '--insecure', '-L', '--location', '--retry'} & set(args))
        self.assertNotIn('secret', ' '.join(args))
        self.assertIn(b'token secret', run.call_args.kwargs['input'])

    def test_private_issue_semantics_and_no_body_in_evidence(self):
        response = Mock(returncode=0, stdout=json.dumps({'number': 2, 'title': 'private', 'state': 'open'}).encode() + b'\n200')
        env = {'FORGEJO_URL': 'https://forgejo.example.com'}
        with patch.dict(os.environ, env, clear=True), patch.object(a.subprocess, 'run', return_value=response):
            result = a.request('/private/path', {'Authorization': 'token secret'}, (2, 'private'))
            self.assertTrue(result['semantic_result'])
            self.assertNotIn('private', json.dumps(result)); self.assertNotIn('secret', json.dumps(result))
            response.stdout = b'{}\n200'
            self.assertFalse(a.request('/private/path', {}, (2, 'private'))['semantic_result'])


if __name__ == '__main__':
    unittest.main()
