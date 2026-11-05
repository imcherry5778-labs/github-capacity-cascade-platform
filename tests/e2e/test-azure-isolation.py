"""P10 Azure source gates against mocked live contracts and failure injection; NOT runtime evidence."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


az = load('p10_azure', 'scripts/azure-isolation.py')
t8 = load('p10_azure_t8', 'tests/e2e/test-azure-cascade.py')
t10 = load('p10_azure_t10', 'tests/e2e/test-critical-bulk-isolation.py')
m = az.m
SHA = 'a' * 40
F = {'owner': 'fixture', 'repo': 'journey', 'issue': 1}
HOST = 'forgejo.example.com'
NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)
FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)


def manifest():
    return {'identity': t8.identity() | {'source_sha': SHA}, 'plan': m.load(az.CANDIDATE), 'fixture': dict(F),
            'prometheus': {'endpoint': 'https://amw-test-abcd.koreacentral.prometheus.monitor.azure.com', 'cluster': 'aks-test'}}


def approval(value):
    return {'approved': True, 'approval_url': 'https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-1',
            'source_sha': SHA, 'manifest_sha256': m.digest(value), 'frozen_plan_sha256': m.digest(value['plan']), 'limits': dict(az.LIMITS)}


class BindingTests(unittest.TestCase):
    def test_manifest_binds_unchanged_candidate_fixture_and_amw_identity(self):
        az.manifest(manifest())
        self.assertEqual((az.run_seconds(manifest()['plan']), az.total_seconds(manifest()['plan'])), (210, 3840))
        for change in (lambda v: v['plan'].update(duration_seconds=60), lambda v: v['plan'].update(protection_fraction=.9),
                       lambda v: v.update(extra=1), lambda v: v['fixture'].update(issue=0),
                       lambda v: v['prometheus'].update(endpoint='http://amw.koreacentral.prometheus.monitor.azure.com'),
                       lambda v: v['prometheus'].update(endpoint='https://evil.example.com'),
                       lambda v: v['prometheus'].update(cluster='a b'), lambda v: v['identity'].update(revision='1.30')):
            value = manifest(); change(value)
            with self.assertRaises((ValueError, KeyError)): az.manifest(value)

    def test_approval_requires_exact_env_url_scope_frozen_plan_fresh_ledger_and_reserve(self):
        value = manifest()
        with mock.patch.dict(os.environ, {'P10_AZURE_APPROVED': SHA}):
            az.approval_gate(value, approval(value), False, NOW)
            az.approval_gate(value, approval(value), False, az.DEADLINE - timedelta(seconds=3841))
            cases = {'reserve': (approval(value), False, az.DEADLINE - timedelta(seconds=3840)),
                     'used ledger': (approval(value), True, NOW)}
            for key, change in {'approved': False, 'source_sha': 'b' * 40, 'manifest_sha256': 'c' * 64, 'frozen_plan_sha256': None,
                                'approval_url': 'https://example.com/approval', 'limits': dict(az.LIMITS, fault_runs=5)}.items():
                cases[key] = (approval(value) | {key: change}, False, NOW)
            cases['extra field'] = (approval(value) | {'note': 'x'}, False, NOW)
            for name, (a, ledger, now) in cases.items():
                with self.assertRaises(ValueError, msg=name): az.approval_gate(value, a, ledger, now)
        for env in ({}, {'P10_AZURE_APPROVED': 'b' * 40}):
            with mock.patch.dict(os.environ, env, clear=True), self.assertRaises(ValueError):
                az.approval_gate(value, approval(value), False, NOW)

    def test_step_budget_is_append_only_and_bounded(self):
        value = manifest()
        row = lambda step, arm: {'step': step, 'arm': arm, 'source_sha': SHA, 'manifest_sha256': m.digest(value)}
        rows = []
        for step, arm in [('setup', 'shared')] + [s for pair in az.sequence(True) for s in (('setup', pair[1]), pair)]:
            az.step_gate(value, rows, step, arm, NOW); rows.append(row(step, arm))
        self.assertEqual(sum(r['step'] in {'calibration', 'measured'} for r in rows), 4)
        for step, arm in (('healthy', 'shared'), ('measured', 'shared'), ('calibration', 'isolated')):
            with self.assertRaises(ValueError): az.step_gate(value, rows, step, arm, NOW)
        with self.assertRaises(ValueError): az.step_gate(value, [], 'measured', 'shared', NOW)           # before healthy
        with self.assertRaises(ValueError): az.step_gate(value, [row('healthy', 'shared') | {'source_sha': 'b' * 40}], 'setup', 'shared', NOW)
        healthy = [row('healthy', 'shared')]
        az.step_gate(value, healthy, 'measured', 'shared', az.DEADLINE - timedelta(seconds=2011))
        with self.assertRaises(ValueError): az.step_gate(value, healthy, 'measured', 'shared', az.DEADLINE - timedelta(seconds=2010))
        with self.assertRaises(ValueError): az.step_gate(value, [], 'teardown', 'shared', NOW)

    def test_ledger_is_exclusive_and_records_before_the_action(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'ledger.jsonl'
            ledger = az.Ledger(path, manifest())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError): az.Ledger(path, manifest())
            ledger.start('healthy', 'shared', NOW)
            with self.assertRaises(ValueError): ledger.start('healthy', 'shared', NOW)
            self.assertEqual([r['step'] for r in ledger.rows()], ['healthy'])

    def test_sequence_is_healthy_first_and_never_repeats(self):
        self.assertEqual(az.sequence(False), [('healthy', 'shared'), ('healthy', 'isolated'), ('measured', 'isolated'), ('measured', 'shared')])
        self.assertEqual([s for s, _ in az.sequence(True)], ['healthy', 'healthy', 'calibration', 'calibration', 'measured', 'measured'])


# --- actual target mapping -------------------------------------------------------------------------------

def target_pod(uid, pool, *, ready=True, sidecar_id='containerd://sidecar-'):
    return {'metadata': {'name': 'ext-authz-%s-%s' % (pool, uid), 'uid': uid, 'namespace': az.NS,
                         'labels': {'app': 'ext-authz-sim', 'p10.pool': pool, 'p8.campaign': 'p8test'}},
            'spec': {'containers': [{'name': 'app', 'resources': {'requests': {'cpu': '50m', 'memory': '64Mi'}, 'limits': {'cpu': '100m', 'memory': '128Mi'}}}],
                     'initContainers': [{'name': 'istio-proxy', 'restartPolicy': 'Always', 'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'},
                                                                                                         'limits': {'cpu': '225m', 'memory': '256Mi'}}}]},
            'status': {'containerStatuses': [{'name': 'app', 'imageID': 'test.azurecr.io/ext-authz-sim@sha256:' + 'c' * 64, 'ready': True}],
                       'initContainerStatuses': [{'name': 'istio-proxy', 'containerID': sidecar_id + uid if sidecar_id else '', 'ready': ready}]}}


def admin(capacity=2, alt='inbound|8080||;', tag='cluster_name'):
    cluster = {'name': 'inbound|8080||', 'alt_stat_name': alt, 'type': 'ORIGINAL_DST',
               'circuit_breakers': {'thresholds': [{'max_requests': capacity}]}}
    listeners = {'filter_chain_match': {'destination_port': 8080}, 'route_config': {'route': {'cluster': 'inbound|8080||'}}}
    bootstrap = {'stats_tags': [{'tag_name': tag, 'regex': az.p9.metric_contract()['tag_regex']}], 'use_all_default_tags': False}
    return {'configs': [{'cluster': cluster}]}, listeners, {'stats': []}, bootstrap


def service(pool):
    return {'metadata': {'name': 'ext-authz-' + pool, 'uid': 'svc-' + pool}, 'spec': {'selector': {'app': 'ext-authz-sim', 'p10.pool': pool}}}


def slices(pool, uids, ready=True):
    return [{'metadata': {'labels': {'kubernetes.io/service-name': 'ext-authz-' + pool}}, 'ports': [{'name': 'http-check', 'port': 8080}],
             'endpoints': [{'conditions': {'ready': ready}, 'targetRef': {'kind': 'Pod', 'uid': u}} for u in uids]}]


def targets(arm):
    pools = {'u1': 'shared', 'u2': 'shared'} if arm == 'shared' else {'u1': 'critical', 'u2': 'bulk'}
    v = m.load(az.CANDIDATE)
    return [az.azure_target(target_pod(u, p), v, service(p), slices(p, sorted(x for x, q in pools.items() if q == p)), *admin(), 1000)
            for u, p in pools.items()]


class TargetTests(unittest.TestCase):
    def test_actual_uid_sidecar_capacity_endpoint_pool_chain(self):
        for arm in m.ARMS:
            result = az.pool_targets(arm, targets(arm))
            self.assertEqual({t['capacity'] for t in result}, {2})
            self.assertEqual([t['endpoint_pod_uid'] for t in result], ['u1', 'u2'])
            self.assertIn('cluster.inbound|8080||;.', result[0]['prefixes'])
        self.assertEqual(targets('shared')[0]['endpoints'], ['u1', 'u2'])

    def test_unconverged_or_drifted_mapping_fails_closed(self):
        v = m.load(az.CANDIDATE)
        good = lambda: [target_pod('u1', 'critical'), v, service('critical'), slices('critical', ['u1']), *admin(), 1000]
        cases = {'capacity not converged': lambda a: a.__setitem__(4, admin(capacity=1024)[0]),
                 'unselected alt stat name': lambda a: a.__setitem__(4, admin(alt='other')[0]),
                 'default Envoy tag': lambda a: a.__setitem__(7, admin(tag='envoy_cluster_name')[3]),
                 'sidecar not ready': lambda a: a.__setitem__(0, target_pod('u1', 'critical', ready=False)),
                 'no sidecar container ID': lambda a: a.__setitem__(0, target_pod('u1', 'critical', sidecar_id='')),
                 'Service selects another pool': lambda a: a.__setitem__(2, service('bulk')),
                 'slice of another Service': lambda a: a.__setitem__(3, slices('bulk', ['u1'])),
                 'hold differs': lambda a: a.__setitem__(8, 0),
                 'terminating Pod': lambda a: a[0]['metadata'].update(deletionTimestamp='now'),
                 'pool label absent': lambda a: a[0]['metadata']['labels'].pop('p10.pool')}
        for name, change in cases.items():
            args = good(); change(args)
            with self.assertRaises((ValueError, KeyError), msg=name): az.azure_target(*args)
        for name, broken in {'endpoint not ready': lambda ts: ts[0].update(endpoint_pod_uid=None),
                             'shared Service misses a Pod': lambda ts: ts[0].update(endpoints=['u1']),
                             'isolated Service selects both': None,
                             'image drift': lambda ts: ts[1].update(image_id='other'),
                             'one pool only': lambda ts: ts[1].update(pool=ts[0]['pool'])}.items():
            ts = targets('shared' if name.startswith('shared') else 'isolated')
            if broken is None:
                ts[0]['endpoints'] = ['u1', 'u2']
            else:
                broken(ts)
            with self.assertRaises(ValueError, msg=name): az.pool_targets('shared' if name.startswith('shared') else 'isolated', ts)


def admitted_pods(arm, *, extra=False):
    identity = t8.identity()
    items = m.render(identity, m.load(az.CANDIDATE), F, arm)['fixtures.json']['items']
    pods = []
    for obj in items:
        if obj['kind'] not in {'Deployment', 'Pod'}: continue
        template = obj['spec']['template'] if obj['kind'] == 'Deployment' else obj
        for index in range(obj['spec'].get('replicas', 1) if obj['kind'] == 'Deployment' else 1):
            pod = copy.deepcopy(template)
            pod['metadata'].update(namespace=az.NS, name=obj['metadata']['name'] if obj['kind'] == 'Pod' else obj['metadata']['name'] + str(index),
                                   uid=obj['metadata']['name'] + str(index))
            annotations = template['metadata'].get('annotations', {})
            if annotations.get('sidecar.istio.io/inject') == 'true':
                resources = {'requests': {'cpu': annotations['sidecar.istio.io/proxyCPU'], 'memory': annotations['sidecar.istio.io/proxyMemory']},
                             'limits': {'cpu': annotations['sidecar.istio.io/proxyCPULimit'], 'memory': annotations['sidecar.istio.io/proxyMemoryLimit']}}
                pod['spec']['initContainers'] = [{'name': 'istio-validation', 'resources': resources},
                                                 {'name': 'istio-proxy', 'restartPolicy': 'Always', 'resources': resources}]
            pods.append(pod)
    if extra:
        pods.append(copy.deepcopy(pods[-1]) | {'metadata': dict(pods[-1]['metadata'], name='extra', uid='extra')})
    return pods


def node(name, cpu='3860m', memory='12Gi', ready=True, taints=()):
    return {'metadata': {'name': name}, 'spec': {'taints': list(taints)},
            'status': {'allocatable': {'cpu': cpu, 'memory': memory}, 'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False'}]}}


def running(node_name, cpu, memory):
    return {'spec': {'nodeName': node_name, 'containers': [{'resources': {'requests': {'cpu': cpu, 'memory': memory}}}]}, 'status': {'phase': 'Running'}}


class AdmissionTests(unittest.TestCase):
    def test_actual_admission_includes_validation_init_native_sidecar_and_composition(self):
        for arm in m.ARMS:
            result = az.pool_admission(t8.identity(), arm, admitted_pods(arm))
            self.assertAlmostEqual(result['conservative_sum']['limits']['cpu'], 1.45)
        cases = {'fifth Pod': admitted_pods('isolated', extra=True),
                 'shared Pods on isolated arm': admitted_pods('shared'),
                 'db client absent': [p for p in admitted_pods('shared') if p['metadata']['name'] != 'p8-db-client']}
        oversized = admitted_pods('shared'); oversized[-1]['spec']['initContainers'] = [{'name': 'istio-validation', 'resources': {
            'requests': {'cpu': '1', 'memory': '1Gi'}, 'limits': {'cpu': '1', 'memory': '1Gi'}}}]
        cases['init over the approved aggregate'] = oversized
        foreign = admitted_pods('shared'); foreign[0]['metadata']['labels']['p8.campaign'] = 'other'
        cases['unowned Pod'] = foreign
        for name, pods in cases.items():
            with self.assertRaises(ValueError, msg=name): az.pool_admission(t8.identity(), 'isolated' if 'isolated' in name else 'shared', pods)

    def test_headroom_estimate_uses_current_requests_and_schedulable_nodes(self):
        needed = az.demand(t8.identity(), m.load(az.CANDIDATE), F)
        self.assertEqual(len(needed), 4)
        self.assertAlmostEqual(sum(p['cpu'] for p in needed), .45)          # 50m HAProxy + 100m DB + 2x(50m app + 100m sidecar)
        nodes = [node('n1'), node('n2')]
        self.assertTrue(az.headroom(nodes, [running('n1', '3500m', '1Gi')], needed)['fits'])
        self.assertFalse(az.headroom(nodes, [running('n1', '3700m', '1Gi'), running('n2', '3700m', '1Gi')], needed)['fits'])   # 160m free each: no bin-pack
        self.assertFalse(az.headroom([node('n1', ready=False), node('n2', taints=[{'effect': 'NoSchedule'}])], [], needed)['fits'])
        done = running('n1', '3800m', '1Gi'); done['status']['phase'] = 'Succeeded'
        self.assertTrue(az.headroom([node('n1')], [done], needed)['fits'])


# --- managed ingress -------------------------------------------------------------------------------------

def ingress_listeners(provider=False, names=(HOST,), **hcm):
    filters = []
    if provider:
        filters.append({'name': 'envoy.filters.http.ext_authz', 'typed_config': {'http_service': {'server_uri': {'cluster': az.HAPROXY_CLUSTER}}}})
    config = {'normalize_path': True, 'http_filters': filters + [{'name': 'envoy.filters.http.router'}]} | hcm
    return {'configs': [{'dynamic_listeners': [{'active_state': {'listener': {'filter_chains': [
        {'filter_chain_match': {'server_names': list(names)},
         'transport_socket': {'name': 'envoy.transport_sockets.tls', 'typed_config': {'@type': 'type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.DownstreamTlsContext'}},
         'filters': [{'name': 'envoy.filters.network.http_connection_manager', 'typed_config': config}]}]}}}]}]}


def ingress_routes(**route):
    return {'configs': [{'route_config': {'virtual_hosts': [{'routes': [{'match': {'prefix': '/'}, 'route': {'cluster': az.FORGEJO_CLUSTER} | route}]}]}}]}


class IngressTests(unittest.TestCase):
    def test_base_normalization_tls_chain_and_unrewritten_route(self):
        result = az.ingress_contract(ingress_listeners(), ingress_routes(), HOST)
        self.assertEqual(result['normalization'], [{'normalize_path': True, 'merge_slashes': False, 'escaped_slashes': 'KEEP_UNCHANGED'}])
        az.ingress_contract(ingress_listeners(names=('*.example.com',)), ingress_routes(), HOST)
        az.ingress_contract(ingress_listeners(provider=True), ingress_routes(), HOST, provider=True)
        az.ingress_contract(ingress_listeners(path_with_escaped_slashes_action='KEEP_UNCHANGED'), ingress_routes(), HOST)

    def test_normalization_tls_provider_and_route_drift_fail_closed(self):
        tls = ingress_listeners(); chain = tls['configs'][0]['dynamic_listeners'][0]['active_state']['listener']['filter_chains'][0]
        chain['transport_socket'] = {'name': 'envoy.transport_sockets.raw_buffer'}
        provider = lambda **change: ingress_listeners(provider=True) if not change else (lambda l: (
            l['configs'][0]['dynamic_listeners'][0]['active_state']['listener']['filter_chains'][0]['filters'][0]['typed_config']['http_filters'][0]
            ['typed_config'].update(change), l)[1])(ingress_listeners(provider=True))
        cases = [(ingress_listeners(normalize_path=None), ingress_routes(), False),
                 (ingress_listeners(merge_slashes=True), ingress_routes(), False),
                 (ingress_listeners(path_with_escaped_slashes_action='UNESCAPE_AND_FORWARD'), ingress_routes(), False),
                 (tls, ingress_routes(), False),
                 (ingress_listeners(names=('other.example.com',)), ingress_routes(), False),
                 (ingress_listeners(names=('*.com',)), ingress_routes(), False),
                 (ingress_listeners(provider=True), ingress_routes(), False),            # leftover filter before the campaign
                 (ingress_listeners(), ingress_routes(), True),                         # provider absent inside the campaign
                 (provider(failure_mode_allow=True), ingress_routes(), True),
                 (provider(with_request_body={'max_request_bytes': 1}), ingress_routes(), True),
                 (provider(http_service={'server_uri': {'cluster': 'outbound|8080||other'}, 'path_prefix': ''}), ingress_routes(), True),
                 (provider(http_service={'server_uri': {'cluster': az.HAPROXY_CLUSTER}, 'path_prefix': '/check'}), ingress_routes(), True),
                 (ingress_listeners(), ingress_routes(retry_policy={'num_retries': 2}), False),
                 (ingress_listeners(), ingress_routes(prefix_rewrite='/x'), False),
                 (ingress_listeners(), {'configs': []}, False)]
        for index, (listeners, routes, inside) in enumerate(cases):
            with self.assertRaises((ValueError, KeyError), msg=str(index)): az.ingress_contract(listeners, routes, HOST, provider=inside)

    def test_mesh_shared_configmap_keeps_default_normalization_and_no_provider(self):
        original = {'metadata': {'name': 'istio-shared-configmap-asm-1-30', 'namespace': 'aks-istio-system', 'uid': 'cm-uid'},
                    'data': {'mesh': json.dumps({'defaultConfig': {}})}}
        self.assertEqual(az.mesh_contract(original, t8.identity())['uid'], 'cm-uid')
        for mesh in ({'pathNormalization': {'normalization': 'MERGE_SLASHES'}},
                     {'extensionProviders': [{'name': 'p8-shared-gate'}]}):
            bad = copy.deepcopy(original); bad['data']['mesh'] = json.dumps(mesh)
            with self.assertRaises(ValueError): az.mesh_contract(bad, t8.identity())
        argo = copy.deepcopy(original); argo['metadata']['labels'] = {'argocd.argoproj.io/instance': 'x'}
        with self.assertRaises(ValueError): az.mesh_contract(argo, t8.identity())


# --- evidence projection ---------------------------------------------------------------------------------

def raw_log(status, detail, cluster=az.FORGEJO_CLUSTER):
    return json.dumps({'status': status, 'detail': detail, 'duration_ms': 3, 'cluster': cluster})


class EvidenceTests(unittest.TestCase):
    def test_selected_access_log_rows_only(self):
        text = '\n'.join(['plain text', raw_log(200, 'via_upstream'), json.dumps({'status': 200}), raw_log(0, 'filter_chain_not_found', None)])
        rows = az.proxy_rows(text)
        self.assertEqual([r['status'] for r in rows], [200, 0])
        self.assertEqual([az.non_http(r) for r in rows], [False, True])
        self.assertFalse(az.non_http({'status': 0, 'details': 'filter_chain_not_found', 'cluster': az.FORGEJO_CLUSTER}))

    def test_multi_replica_ingress_and_target_streams_feed_the_w1_accounting(self):
        outcomes = [('critical', 200), ('bulk', 503), ('bulk', 200), ('critical', 503)]
        for arm in m.ARMS:
            expected = t10.observation(arm, outcomes)
            parse = lambda rows, cluster='x': [az.proxy_rows(raw_log(r['status'], r['details'], cluster))[0] for r in rows]
            ingress = parse(expected['ingress_rows'], az.FORGEJO_CLUSTER)
            before = {'ingress': {'i1': parse([{'status': 200, 'details': 'via_upstream'}]), 'i2': []},
                      'target': {u: [] for u in expected['target_rows']}, 'app': {u: [] for u in expected['app_checks']}}
            tls_probe = az.proxy_rows(raw_log(0, 'filter_chain_not_found', None))
            after = {'ingress': {'i1': before['ingress']['i1'] + ingress[:2] + tls_probe, 'i2': ingress[2:]},
                     'target': {u: parse(rows) for u, rows in expected['target_rows'].items()}, 'app': expected['app_checks']}
            snap = lambda ring, stats, info: {'ring': ring, 'stats': stats, 'info': info}
            obs, non_http = az.azure_observation(expected['targets'], snap(expected['ring_before'], expected['stats_before'], expected['info_before']),
                                                 snap(expected['ring_after'], expected['stats_after'], expected['info_after']), before, after, expected['client_requests'])
            self.assertEqual((obs['ingress_rows'], obs['target_rows'], non_http), (expected['ingress_rows'], expected['target_rows'], 1))
            m.window_accounting(arm, obs)
            rotated = copy.deepcopy(after); rotated['ingress']['i1'] = rotated['ingress']['i1'][1:]
            scaled = copy.deepcopy(after); scaled['ingress']['i3'] = []
            for bad in (rotated, scaled):
                with self.assertRaises(ValueError): az.azure_observation(expected['targets'], {}, {}, before, bad, {})

    def test_amw_rows_are_scoped_to_the_campaign_cluster_label(self):
        pods = [{'name': 'ext-authz-shared-a', 'uid': 'u0', 'pool': 'shared'}, {'name': 'ext-authz-shared-b', 'uid': 'u1', 'pool': 'shared'}]
        stamps = {'u0': [0, 15, 30], 'u1': [1, 16, 31]}
        response = t10.prometheus(pods, stamps, lambda uid, key, t: 0, namespace=az.NS)
        rows = az.managed_rows(manifest(), [{'at': 60.0, 'data': response}], pods, t10.CLOCK)
        self.assertEqual(len(rows), 3)
        for r in response['data']['result']: r['metric']['cluster'] = 'other-aks'
        with self.assertRaises(ValueError): az.managed_rows(manifest(), [{'at': 60.0, 'data': response}], pods, t10.CLOCK)
        for name, selector in m.managed_selectors(az.NS, 'aks-test').items():
            self.assertEqual(selector, name + '{cluster="aks-test",namespace="p8-shared-gate",job="p10-envoy",cluster_name="inbound|8080||"}')

    def test_preflight_amw_uses_the_campaign_five_query_path(self):
        up = observations()['prometheus']['up']
        def fake(p10, calls):
            p10_fetch = t10.amw(p10, calls)
            def fetch(path, params):
                if params['query'].startswith('up{'):
                    calls.append((path, params)); return copy.deepcopy(up)
                return p10_fetch(path, params)
            return fetch
        calls = []
        observed = az.amw_preflight(fake(lambda: t10.prometheus([], {}, None, namespace=az.NS), calls), 'aks-test')
        self.assertEqual([c[1]['query'] for c in calls], ['up{cluster="aks-test",namespace="forgejo"}'] +
                         ['%s[%ds]' % (s, m.MANAGED_LOOKBACK_SECONDS) for _, s in sorted(m.managed_selectors(az.NS, 'aks-test').items())])
        self.assertFalse(any('__name__' in c[1]['query'] for c in calls))
        obs = observations(); obs['prometheus'] = observed
        self.assertEqual(az.preflight_verdict(manifest(), obs, PRICE, NOW)['status'], 'ready-for-approval-request')
        pods = [{'name': 'ext-authz-shared-a', 'uid': 'u0'}]
        present = az.amw_preflight(fake(lambda: t10.prometheus(pods, {'u0': [0]}, lambda *a: 0, namespace=az.NS), []), 'aks-test')
        obs['prometheus'] = present
        self.assertIn('amw-p10-series-present-before-campaign', az.preflight_verdict(manifest(), obs, PRICE, NOW)['blockers'])
        # A refused or partial P10 query is no observation (unobserved:prometheus), never an empty result.
        legacy = lambda path, params: (_ for _ in ()).throw(t10.refused(path, 501))
        with self.assertRaises(t10.urllib.error.HTTPError) as raised:
            az.amw_preflight(lambda path, params: copy.deepcopy(up) if params['query'].startswith('up{') else legacy(path, params), 'aks-test')
        raised.exception.close()


# --- read-only preflight ---------------------------------------------------------------------------------

def observations():
    value = manifest(); identity = value['identity']
    key = lambda k: '|'.join(map(str, k))
    argo = {'spec': {'sources': [{}, {'targetRevision': identity['stable_revision']}, {'targetRevision': identity['stable_revision']}]},
            'status': {'sync': {'status': 'Synced'}, 'health': {'status': 'Healthy'}}}
    up = {'status': 'success', 'data': {'resultType': 'vector', 'result': [{'metric': {'job': 'forgejo'}, 'value': [1, '1']}]}}
    return {'source': {'head': SHA, 'clean': True},
            'access': {'read': {key(k): True for k in az.READ_ACCESS}, 'campaign': {key(k): True for k in az.CAMPAIGN_ACCESS}},
            'cluster': {'id': identity['cluster_resource_id'].replace('resourceGroups', 'resourcegroups'), 'cluster_uid': identity['cluster_uid'],
                        'currentKubernetesVersion': '1.36.4', 'serviceMeshProfile': {'istio': {'revisions': [identity['revision']]}},
                        'agentPoolProfiles': [{'count': 2, 'vmSize': 'Standard_D4s_v4', 'enableAutoScaling': False}]},
            'capacity': {'nodes': [node('n1'), node('n2')], 'pods': [running('n1', '2', '4Gi')]},
            'mesh': {'metadata': {'name': 'istio-shared-configmap-asm-1-30', 'namespace': 'aks-istio-system', 'uid': 'cm'}, 'data': {'mesh': '{}'}},
            'ingress': [{'uid': 'i1', 'listeners': ingress_listeners(), 'routes': ingress_routes()}],
            'leftovers': {'namespace': False, 'policy': False}, 'crd': True, 'argo': argo, 'image': True,
            'prometheus': {'up': up, 'p10': {'status': 'success', 'data': {'resultType': 'matrix', 'result': []}}},
            'https': {'status': 200, 'error_class': 'none', 'semantic_result': True}}


PRICE = {'node_hour_usd': .236, 'amw_per_10m_samples_usd': .11, 'retrieved_utc': '2026-11-05T00:00:00Z'}


class PreflightTests(unittest.TestCase):
    def test_ready_is_only_a_request_readiness_with_unknown_budget(self):
        result = az.preflight_verdict(manifest(), observations(), PRICE, NOW)
        self.assertEqual((result['status'], result['blockers']), ('ready-for-approval-request', []))
        self.assertEqual(result['facts']['cost']['existing_shared_node_hold_usd'], round(2 * 3840 / 3600 * .236, 4))
        self.assertEqual(result['facts']['cost']['budget_and_headroom'], 'UNKNOWN')
        self.assertIn('budget (UNKNOWN)', result['decisions_required'])

    def test_current_rbac_blocker_is_exact_and_nothing_else_is_inferred(self):
        obs = observations()
        obs['access'] = {'read': {k: False for k in obs['access']['read']}, 'campaign': {k: False for k in obs['access']['campaign']}}
        for section in ('capacity', 'mesh', 'ingress', 'leftovers', 'crd', 'argo'):
            obs[section] = None
        obs['cluster']['cluster_uid'] = None
        result = az.preflight_verdict(manifest(), obs, PRICE, NOW)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['facts']['read_access_missing'], [list(k) for k in az.READ_ACCESS])
        for code in ('kubernetes-read-rbac', 'campaign-rbac-decision', 'unobserved:capacity', 'unobserved:ingress', 'podmonitor-crd', 'cluster-identity'):
            self.assertIn(code, result['blockers'])

    def test_every_failed_or_missing_observation_blocks(self):
        def edit(path, value):
            def change(o):
                target = o
                for k in path[:-1]: target = target[k]
                target[path[-1]] = value
            return change
        cases = {'source-not-exact-clean-head': edit(('source', 'clean'), False),
                 'campaign-rbac-decision': edit(('access', 'campaign', 'create|pods/portforward|forgejo'), False),
                 'mesh-revision': edit(('cluster', 'serviceMeshProfile', 'istio', 'revisions'), ['asm-1-29']),
                 'fixed-nodes': lambda o: o['cluster']['agentPoolProfiles'][0].update(enableAutoScaling=True),
                 'node-headroom': edit(('capacity', 'pods'), [running('n1', '3800m', '1Gi'), running('n2', '3800m', '1Gi')]),
                 'mesh-shared-configmap': edit(('mesh', 'data', 'mesh'), json.dumps({'pathNormalization': {'normalization': 'NONE'}})),
                 'ingress-https-normalization-contract': lambda o: o['ingress'].append({'uid': 'i2', 'listeners': ingress_listeners(merge_slashes=True), 'routes': ingress_routes()}),
                 'p10-leftover-objects': edit(('leftovers', 'policy'), True), 'podmonitor-crd': edit(('crd',), None),
                 'stable-argo': edit(('argo', 'status', 'sync', 'status'), 'OutOfSync'),
                 'ext-authz-image-absent-or-unreadable': edit(('image',), None),
                 'amw-stable-scrape': edit(('prometheus', 'up', 'data', 'result'), []),
                 'amw-p10-series-present-before-campaign': edit(('prometheus', 'p10', 'data', 'result'), [{'metric': {}, 'values': []}]),
                 'https-healthz-tls': edit(('https', 'error_class'), 'transport'),
                 'unobserved:prometheus': edit(('prometheus',), None), 'unobserved:cluster': edit(('cluster',), None)}
        for code, change in cases.items():
            obs = observations(); change(obs)
            result = az.preflight_verdict(manifest(), obs, PRICE, NOW)
            self.assertEqual(result['status'], 'blocked', code); self.assertIn(code, result['blockers'], code)
        result = az.preflight_verdict(manifest(), observations(), PRICE, az.DEADLINE - timedelta(seconds=3000))
        self.assertIn('retention-reserve', result['blockers'])
        with self.assertRaises(ValueError): az.preflight_verdict(manifest(), observations(), PRICE | {'node_hour_usd': 0}, NOW)

    def test_empty_partial_or_malformed_sections_never_reach_readiness(self):
        cases = {'ingress': [[], [{}], [{'uid': 'i1', 'listeners': {}, 'routes': {}}], {}],      # empty ingress Pod list, partial, contract-less
                 'capacity': [{}, {'nodes': [], 'pods': []}, {'nodes': [node('n1')]}, []],
                 'argo': [{}, {'spec': {}, 'status': {}}, []],
                 'prometheus': [{}, {'up': {}, 'p10': {}}, {'up': observations()['prometheus']['up']},
                                {'up': observations()['prometheus']['up'], 'p10': {'status': 'error', 'data': {'resultType': 'matrix', 'result': []}}}],
                 'leftovers': [{}, {'namespace': False}, {'namespace': None, 'policy': False}, {'namespace': 0, 'policy': 0}, []],
                 'cluster': [{}, {'id': 'x', 'agentPoolProfiles': [], 'serviceMeshProfile': {}}],
                 'access': [{}, {'read': [], 'campaign': {}}],
                 'source': [{}, []], 'mesh': [{}, {'metadata': {}, 'data': {}}]}
        for name, values in cases.items():
            for value in values:
                obs = observations(); obs[name] = value
                result = az.preflight_verdict(manifest(), obs, PRICE, NOW)
                self.assertEqual(result['status'], 'blocked', (name, value))
                self.assertTrue(any(b in {'malformed:' + name, 'unobserved:' + name} or b.startswith(('kubernetes-read', 'campaign-rbac', 'source-', 'p10-leftover',
                                    'amw-', 'stable-argo', 'ingress-', 'node-', 'cluster-', 'mesh-'))
                                    for b in result['blockers']), (name, value, result['blockers']))
        # Allowed emptiness: no P10 series before the campaign, and explicitly known-absent leftovers.
        obs = observations()
        self.assertEqual((obs['prometheus']['p10']['data']['result'], obs['leftovers']), ([], {'namespace': False, 'policy': False}))
        self.assertEqual(az.preflight_verdict(manifest(), obs, PRICE, NOW)['status'], 'ready-for-approval-request')

    def test_price_retrieval_time_is_recorded_not_capped(self):
        result = az.preflight_verdict(manifest(), observations(), PRICE | {'retrieved_utc': '2026-10-01T00:00:00Z'}, NOW)
        self.assertEqual((result['status'], result['facts']['cost']['price_age_hours']), ('ready-for-approval-request', 864.0))
        for bad in ('2026-11-07T00:00:00Z', '2026-11-05T00:00:00+09:00', 'yesterday'):
            with self.assertRaises(ValueError, msg=bad): az.preflight_verdict(manifest(), observations(), PRICE | {'retrieved_utc': bad}, NOW)
        for bad in (float('nan'), float('inf'), -1, True):
            with self.assertRaises(ValueError, msg=str(bad)): az.preflight_verdict(manifest(), observations(), PRICE | {'node_hour_usd': bad}, NOW)

    def test_preflight_kubectl_is_read_only(self):
        for args in (('get', 'pods'), ('-n', 'x', 'get', 'configmap', 'y', '-o', 'json'), ('auth', 'can-i', 'create', 'pods/exec', '-n', 'x'),
                     ('-n', 'x', 'exec', 'p', '-c', 'istio-proxy', '--', 'pilot-agent', 'request', 'GET', 'config_dump')):
            az.readonly_args(args)
        for args in (('apply', '-f', '-'), ('-n', 'x', 'patch', 'configmap', 'y'), ('delete', 'namespace', 'x'), ('port-forward', 'pod/x', '1:2'),
                     ('-n', 'x', 'exec', 'p', '-c', 'istio-proxy', '--', 'pilot-agent', 'request', 'POST', 'quitquitquit'),
                     ('-n', 'x', 'exec', 'p', '-c', 'app', '--', 'sh'), ('-n', 'x', 'exec', 'p', '-c', 'istio-proxy', '--', 'pilot-agent', 'request', 'GET', 'a', 'b'),
                     ('auth', 'reconcile'), ()):
            with self.assertRaises(ValueError, msg=str(args)): az.readonly_args(args)
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            az.Preflight(manifest())


# --- owned campaign rollback (fake cluster) --------------------------------------------------------------

class FakeAzure:
    """Namespace/policy/mesh/ingress model with failure injection. Every mutation is recorded."""
    def __init__(self, **faults):
        self.faults = dict(faults)
        self.namespace = None; self.policy = None; self.provider_sticky = False
        self.mesh = {'uid': 'cm-uid', 'data': {'mesh': json.dumps({'defaultConfig': {}})}}
        self.original_mesh = copy.deepcopy(self.mesh)
        self.calls = []
        self.stable = {'pod': 'forgejo-uid', 'spec': {'replicas': 1}}
        self.healthy = True

    def fault(self, name):
        if self.faults.get(name, 0) > 0:
            self.faults[name] -= 1
            raise ValueError('injected ' + name)

    def provider(self):
        return self.policy is not None or self.provider_sticky

    def k(self, *args):
        a = list(args)
        if a[:3] == ['get', 'namespace', az.NS]:
            if '-o' in a and a[a.index('-o') + 1] == 'json':
                return json.dumps({'metadata': {'labels': self.namespace or {}}})
            return 'namespace/' + az.NS if self.namespace is not None else ''
        if a[:4] == ['-n', az.INGRESS_NS, 'get', 'authorizationpolicy']:
            if self.policy is None: return ''
            return json.dumps({'metadata': self.policy}) if a[-1] == 'json' else 'authorizationpolicy/p8-shared-gate'
        if a[:4] == ['-n', az.INGRESS_NS, 'delete', 'authorizationpolicy']:
            self.calls.append('delete-policy'); self.fault('policy_delete'); self.policy = None; return ''
        if a[:4] == ['-n', az.MESH_NS, 'get', 'configmap']:
            return json.dumps({'metadata': {'name': a[4], 'namespace': az.MESH_NS, 'uid': self.mesh['uid']}, 'data': self.mesh['data']})
        if a[:4] == ['-n', az.MESH_NS, 'patch', 'configmap']:
            self.calls.append('patch-mesh'); self.fault('mesh_patch'); self.mesh['data'] = json.loads(a[-1])['data']; return ''
        if a[:4] == ['-n', 'forgejo', 'get', 'deployment']:
            return json.dumps({'spec': self.stable['spec']})
        if a[:4] == ['-n', 'argocd', 'get', 'application']:
            return json.dumps(observations()['argo'])
        raise AssertionError('unexpected kubectl ' + ' '.join(a))

    def j(self, *args):
        return json.loads(self.k(*args))

    def pod(self, ns, selector):
        return {'metadata': {'uid': self.stable['pod'], 'name': 'forgejo-0'}, 'status': {'podIP': '10.0.0.9'}}

    def pods(self, ns, selector):
        return [{'metadata': {'name': 'ingress-0', 'uid': 'i0'}}]

    def admin(self, ns, pod, path):
        return ingress_listeners(provider=self.provider()) if 'listeners' in path else ingress_routes()

    def run(self, args, **kw):
        if 'apply' in args:
            value = json.loads(kw['input'])
            self.calls.append('apply')
            for index, item in enumerate(value.get('items', [value])):
                if index == self.faults.get('apply_fails_at'):     # objects before this one already exist
                    raise ValueError('injected partial apply')
                self.fault('apply')
                if item['kind'] == 'Namespace': self.namespace = item['metadata']['labels']
                if item['kind'] == 'AuthorizationPolicy': self.policy = {'uid': 'policy-uid', 'labels': item['metadata']['labels']}
        elif args[-5:-3] == ['namespace', az.NS] or 'namespace' in args and 'delete' in args:
            self.calls.append('delete-namespace'); self.fault('namespace_delete')
            if not self.faults.get('ghost'): self.namespace = None
        elif 'rollout' in args:
            self.fault('rollout')
        else:
            raise AssertionError('unexpected subprocess ' + ' '.join(args))
        return mock.Mock(returncode=0, stdout='')

    def request(self, path, headers, expected=None, direct=False):
        return {'semantic_result': self.healthy, 'status': 200 if self.healthy else 503}


CLI_RESOURCE = {'namespace': 'namespaces', 'authorizationpolicy': 'authorizationpolicies.security.istio.io', 'configmap': 'configmaps',
                'deployment': 'deployments.apps', 'service': 'services', 'endpointslices': 'endpointslices.discovery.k8s.io', 'pods': 'pods',
                'nodes': 'nodes', 'application': 'applications.argoproj.io'}
KIND_RESOURCE = {'Namespace': 'namespaces', 'ResourceQuota': 'resourcequotas', 'ConfigMap': 'configmaps', 'Secret': 'secrets',
                 'Deployment': 'deployments.apps', 'Service': 'services', 'Pod': 'pods', 'Sidecar': 'sidecars.networking.istio.io',
                 'PodMonitor': 'podmonitors.azmonitoring.coreos.com', 'AuthorizationPolicy': 'authorizationpolicies.security.istio.io'}


class RbacCluster:
    """Records the Kubernetes verb/resource/namespace each campaign kubectl command needs.

    Client-side `apply` = get + create (new) or patch (existing); `rollout restart` = get + patch; `rollout status` and
    `--wait` = get/list/watch; exec/logs/port-forward read the Pod first. Responses are minimal but well-formed.
    """
    def __init__(self):
        self.needs = set(); self.objects = {}; self.pools = None; self.policy = None
        self.mesh = {'mesh': json.dumps({'defaultConfig': {}})}
        self.selector = t8.identity()['ingress_selector']

    def need(self, verb, resource, ns):
        self.needs.add((verb, resource, ns))

    def ns_pods(self):
        if self.pools is None: return []
        pods = [p for p in admitted_pods(self.pools or 'shared') if p['metadata']['labels'].get('app') != 'ext-authz-sim' or self.pools]
        for pod in pods:
            if pod['metadata']['labels'].get('app') == 'ext-authz-sim':
                pod['status'] = target_pod(pod['metadata']['uid'], pod['metadata']['labels']['p10.pool'])['status']
                for c in pod['status']['containerStatuses'] + pod['status']['initContainerStatuses']: c['restartCount'] = 0
                pod['status'].update(phase='Running', conditions=[{'type': 'Ready', 'status': 'True'}])
            else:
                pod['status'] = {'containerStatuses': [{'name': c['name'], 'imageID': 'sha256:x', 'ready': True, 'restartCount': 0}
                                                       for c in pod['spec']['containers']], 'phase': 'Running',
                                 'conditions': [{'type': 'Ready', 'status': 'True'}], 'podIP': '10.0.0.5'}
        return pods

    def all_pods(self):
        stable = {'metadata': {'name': 'forgejo-0', 'uid': 'forgejo-uid', 'namespace': 'forgejo', 'labels': {'app.kubernetes.io/name': 'forgejo'}},
                  'spec': {'containers': [{'name': 'forgejo'}]}, 'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}],
                  'containerStatuses': [{'name': 'forgejo', 'ready': True, 'restartCount': 0, 'imageID': 'sha256:f'}]}}
        ingress = copy.deepcopy(stable); ingress['metadata'].update(name='ingress-0', uid='ingress-uid', namespace=az.INGRESS_NS, labels=dict(self.selector))
        return [stable, ingress] + self.ns_pods()

    def k(self, *args):
        a = list(args); ns = None
        if a[:1] == ['-n']: ns, a = a[1], a[2:]
        verb = a[0]
        if verb == 'get':
            if '-A' in a:
                self.need('list', 'pods', None); return json.dumps({'items': self.all_pods()})
            resource = CLI_RESOURCE[a[1].split('/')[0]]
            named = len(a) > 2 and not a[2].startswith('-')
            self.need('get' if named else 'list', resource, None if resource in {'namespaces', 'nodes'} else ns)
            return self.get(resource, ns, a[2] if named else None, a)
        if verb == 'exec':
            self.need('get', 'pods', ns); self.need('create', 'pods/exec', ns)
            command = a[a.index('--') + 1:]
            if command[:3] == ['pilot-agent', 'request', 'GET']:
                path = command[3]
                if ns == az.INGRESS_NS:
                    return json.dumps(ingress_listeners(provider=self.policy is not None) if 'listeners' in path else ingress_routes())
                clusters, listeners, stats, bootstrap = admin()
                return json.dumps(clusters if 'clusters' in path else listeners if 'listeners' in path else bootstrap if 'bootstrap' in path else stats)
            if command[:2] == ['cat', '/config/hold-ms']: return '1000'
            if command[0] == 'psql': return json.dumps({'query_ok': True, 'connections': 1, 'max_connections': 100, 'reserved': 3})
            if command[0] == 'wget': return t10.REAL_STATS
            return t10.REAL_INFO if 'show info' in command[-1] else ''
        if verb == 'logs':
            self.need('get', 'pods', ns); self.need('get', 'pods/log', ns); return ''
        if verb == 'patch':
            self.need('patch', CLI_RESOURCE[a[1]], ns)
            if a[1] == 'configmap' and ns == az.MESH_NS: self.mesh = json.loads(a[-1])['data']
            return ''
        if a[:2] == ['rollout', 'restart']:
            self.need('get', 'deployments.apps', ns); self.need('patch', 'deployments.apps', ns); return ''
        if verb == 'delete' and a[1] == 'authorizationpolicy':
            self.need('delete', CLI_RESOURCE[a[1]], ns); self.policy = None; return ''
        raise AssertionError('unmodelled kubectl ' + ' '.join(args))

    def get(self, resource, ns, name, a):
        absent = '' if '--ignore-not-found' in a else None
        if resource == 'namespaces':
            if name == az.NS and self.pools is None: return absent if absent is not None else (_ for _ in ()).throw(ValueError('absent'))
            return 'namespace/' + name if '-o' in a and a[a.index('-o') + 1] == 'name' else json.dumps({'metadata': {'labels': {'p8.campaign': 'p8test'}}})
        if resource == 'authorizationpolicies.security.istio.io':
            if self.policy is None: return ''
            return json.dumps({'metadata': self.policy}) if a[-1] == 'json' else 'authorizationpolicy/p8-shared-gate'
        if resource == 'configmaps':
            return json.dumps({'metadata': {'name': name, 'namespace': az.MESH_NS, 'uid': 'cm-uid'}, 'data': self.mesh})
        if resource == 'deployments.apps': return json.dumps({'spec': {'replicas': 1}})
        if resource == 'applications.argoproj.io': return json.dumps(observations()['argo'])
        if resource == 'nodes': return json.dumps({'items': [node('n1') | {'status': node('n1')['status'] | {'conditions': [{'type': 'Ready', 'status': 'True'}]}}]})
        if resource == 'services': return json.dumps(service(name[len('ext-authz-'):]))
        if resource == 'endpointslices.discovery.k8s.io':
            pool = a[a.index('-l') + 1].split('=ext-authz-')[1]
            return json.dumps({'items': slices(pool, [p['metadata']['uid'] for p in self.ns_pods() if p['metadata']['labels'].get('p10.pool') == pool])})
        if resource == 'pods':
            pods = self.all_pods() if ns != az.NS else self.ns_pods()
            pods = [p for p in pods if p['metadata']['namespace'] == ns]
            if '-l' in a:
                key, value = a[a.index('-l') + 1].split('=')
                pods = [p for p in pods if p['metadata']['labels'].get(key) == value]
            return json.dumps({'items': pods})
        raise AssertionError('unmodelled get ' + resource)

    def run(self, args, **kw):
        a = args[args.index('kubectl') + 1:]
        a = [x for x in a if not x.startswith('--request-timeout')]
        ns = a[a.index('-n') + 1] if '-n' in a else None
        if 'apply' in a or ('delete' in a and '-f' in a):
            value = json.loads(kw['input'])
            for item in value.get('items', [value]):
                resource = KIND_RESOURCE[item['kind']]
                item_ns = item['metadata'].get('namespace')
                key = (resource, item_ns, item['metadata']['name'])
                if 'apply' in a:
                    self.need('get', resource, item_ns); self.need('patch' if key in self.objects else 'create', resource, item_ns)
                    self.objects[key] = item
                    if item['kind'] == 'AuthorizationPolicy': self.policy = {'uid': 'policy-uid', 'labels': item['metadata']['labels']}
                else:
                    for verb in ('delete', 'get', 'list', 'watch'): self.need(verb, resource, item_ns)
                    self.objects.pop(key, None)
            pools = sorted(k[2] for k in self.objects if k[0] == 'deployments.apps' and k[2].startswith('ext-authz-'))
            self.pools = None if not any(k[0] == 'namespaces' for k in self.objects) else \
                ('shared' if pools == ['ext-authz-shared'] else 'isolated' if pools == ['ext-authz-bulk', 'ext-authz-critical'] else 'none')
            if self.pools == 'none': self.pools = ''
        elif 'rollout' in a and 'status' in a:
            for verb in ('get', 'list', 'watch'): self.need(verb, 'deployments.apps', ns)
        elif a[:2] == ['delete', 'namespace']:
            for verb in ('delete', 'get', 'list', 'watch'): self.need(verb, 'namespaces', None)
            self.objects = {}; self.pools = None
        else:
            raise AssertionError('unmodelled subprocess ' + ' '.join(args))
        return mock.Mock(returncode=0, stdout='')

    def popen(self, args, **kw):
        a = args[args.index('kubectl') + 1:]
        ns = a[a.index('-n') + 1]
        self.need('get', 'pods', ns); self.need('create', 'pods/portforward', ns)
        return mock.Mock(poll=lambda: None, wait=lambda timeout=None: 0)


def covered(need, granted):
    verb, resource, ns = need
    return need in granted or (verb, resource, None) in granted


class CampaignAccessTests(unittest.TestCase):
    def campaign_needs(self):
        cluster = RbacCluster()
        rt = object.__new__(az.p8.Runtime); rt.value = t8.identity(); rt.k = cluster.k
        directory = tempfile.mkdtemp()
        value = manifest()
        c = object.__new__(az.Campaign)
        c.value, c.identity, c.v, c.f, c.out, c.rt = value, value['identity'], value['plan'], value['fixture'], Path(directory), rt
        c.client = mock.Mock(token='tok', title='T')
        c.owned_namespace, c.policy, c.mesh, c.arm, c.stable = False, None, None, None, None
        db = Path(directory) / 'db.json'; db.write_text(json.dumps({'PGHOST': 'h', 'PGDATABASE': 'd', 'PGUSER': 'u', 'PGPASSWORD': 'p'})); db.chmod(0o600)
        def converge():   # the real converge's reads; its gateway_scope parsing is covered by the P8 tests
            c.j('-n', az.INGRESS_NS, 'get', 'authorizationpolicy', 'p8-shared-gate', '-o', 'json'); c.rt.pod(az.NS, 'app=haproxy')
            for i in c.ingress_pods():
                c.rt.admin(az.INGRESS_NS, i['metadata']['name'], 'config_dump?resource=dynamic_listeners')
                c.rt.admin(az.INGRESS_NS, i['metadata']['name'], 'clusters?format=json')
        c.converge = converge
        with mock.patch.object(az, 'DEADLINE', FUTURE), mock.patch.object(az.subprocess, 'run', cluster.run), \
             mock.patch.object(az.subprocess, 'Popen', cluster.popen), mock.patch.object(az, 'time', FakeTime()), \
             mock.patch.object(az.p8, 'request', lambda *a, **k: {'semantic_result': True, 'status': 200}), mock.patch.dict(os.environ, {'P10_DB_ENV': str(db)}):
            c.ledger = az.Ledger(Path(directory) / 'ledger.jsonl', value)
            c.start()
            c.setup('isolated')
            targets = c.identify('isolated')
            for t in targets: c.k('-n', az.NS, 'logs', t['name'], '-c', 'app')   # healthy app-log exclusion read
            c.guard_snapshot({t['uid'] for t in targets}); c.haproxy_snapshot(); c.log_counts(targets, '2026-11-06T00:00:00Z')
            for forward in (az.Forward(az.NS, targets[0]['name'], '19101:15000', Path(directory) / 'a.log'),
                            az.Forward('forgejo', 'forgejo-0', '13000:3000', Path(directory) / 'd.log')):
                forward.stop()
            restored = c.restore()
        self.assertIs(restored['restored'], True)
        return cluster.needs

    def test_every_campaign_command_is_covered_by_the_checked_access(self):
        needs = self.campaign_needs()
        granted = set(az.READ_ACCESS) | set(az.CAMPAIGN_ACCESS)
        self.assertEqual(sorted(n for n in needs if not covered(n, granted)), [])
        # Each listed campaign verb is actually exercised (no speculative grant), and dropping any one leaves a command uncovered.
        for entry in az.CAMPAIGN_ACCESS:
            self.assertTrue(any(covered(n, {entry}) for n in needs), entry)
            narrow = granted - {entry}
            self.assertTrue([n for n in needs if not covered(n, narrow)], entry)

    def test_any_missing_campaign_verb_blocks_the_approval_request(self):
        for entry in az.CAMPAIGN_ACCESS + az.READ_ACCESS:
            obs = observations()
            group = 'campaign' if entry in az.CAMPAIGN_ACCESS else 'read'
            obs['access'][group]['|'.join(map(str, entry))] = False
            result = az.preflight_verdict(manifest(), obs, PRICE, NOW)
            self.assertEqual(result['status'], 'blocked', entry)
            self.assertIn('campaign-rbac-decision' if group == 'campaign' else 'kubernetes-read-rbac', result['blockers'], entry)


class FakeTime:
    """Bounded waits elapse instantly: each sleep advances the monotonic clock."""
    def __init__(self): self.now = 0.0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class CampaignRollbackTests(unittest.TestCase):
    def campaign(self, cluster, directory):
        value = manifest()
        c = object.__new__(az.Campaign)
        c.value, c.identity, c.v, c.f = value, value['identity'], value['plan'], value['fixture']
        c.out = Path(directory); c.rt = cluster
        c.client = mock.Mock(token='tok', title='T')
        c.owned_namespace, c.policy, c.mesh, c.arm, c.stable = False, None, None, None, None
        c.ledger = az.Ledger(Path(directory) / 'ledger.jsonl', value)
        db = Path(directory) / 'db.json'; db.write_text(json.dumps({'PGHOST': 'h', 'PGDATABASE': 'd', 'PGUSER': 'u', 'PGPASSWORD': 'p'})); db.chmod(0o600)
        os.environ['P10_DB_ENV'] = str(db)
        return c

    def drive(self, cluster, converge_fault=False):
        directory = tempfile.mkdtemp()
        patches = [mock.patch.object(az, 'DEADLINE', FUTURE), mock.patch.object(az.subprocess, 'run', cluster.run), mock.patch.object(az, 'time', FakeTime()),
                   mock.patch.object(az.p8, 'request', cluster.request), mock.patch.dict(os.environ, {})]
        for p in patches: p.start()
        try:
            c = self.campaign(cluster, directory)
            def converge():
                if converge_fault: raise ValueError('ingress provider/HAProxy endpoint did not converge')
            c.converge = converge
            try:
                c.start(); started = True
            except ValueError:
                started = False
            first = c.restore(); second = c.restore()
            return c, started, first, second
        finally:
            for p in reversed(patches): p.stop()

    def assert_pristine(self, cluster, restoration, name=''):
        self.assertIs(restoration['restored'], True, name)
        self.assertEqual((cluster.namespace, cluster.policy, cluster.mesh), (None, None, cluster.original_mesh), name)
        self.assertEqual(restoration['owned_pending'], {'namespace': False, 'policy': False, 'mesh': False}, name)

    def test_clean_start_is_fully_restored_and_idempotent(self):
        cluster = FakeAzure()
        c, started, first, second = self.drive(cluster)
        self.assertTrue(started)
        self.assert_pristine(cluster, first); self.assert_pristine(cluster, second)
        self.assertEqual([r['step'] for r in c.ledger.rows()], ['setup'])
        self.assertEqual(cluster.calls, ['apply', 'patch-mesh', 'apply', 'delete-policy', 'patch-mesh', 'delete-namespace'])

    def test_failure_at_every_start_step_still_removes_what_may_exist(self):
        for name, cluster, converge in (('apply fails before any object', FakeAzure(apply=1), False),
                                        ('partial apply (namespace + Secret exist)', FakeAzure(apply_fails_at=2), False), ('rollout', FakeAzure(rollout=1), False),
                                        ('mesh patch', FakeAzure(mesh_patch=1), False), ('provider convergence', FakeAzure(), True)):
            c, started, first, _ = self.drive(cluster, converge)
            self.assertFalse(started, name)
            self.assert_pristine(cluster, first, name)

    def test_preexisting_objects_are_never_adopted(self):
        for setup in (lambda c: setattr(c, 'namespace', {'p8.campaign': 'p8test'}), lambda c: setattr(c, 'policy', {'uid': 'x', 'labels': {}}),
                      lambda c: setattr(c, 'provider_sticky', True)):
            cluster = FakeAzure(); setup(cluster)
            before = (copy.deepcopy(cluster.namespace), copy.deepcopy(cluster.policy))
            c, started, first, _ = self.drive(cluster)
            self.assertFalse(started)
            self.assertEqual(cluster.calls, [])                       # no apply, patch or delete
            self.assertEqual((cluster.namespace, cluster.policy), before)

    def test_replaced_or_stuck_objects_are_reported_not_claimed(self):
        cases = {'policy replaced': lambda c: c.policy.update(uid='someone-else'),
                 'mesh replaced': lambda c: c.mesh.update(uid='new-cm'),
                 'namespace delete fails': lambda c: c.faults.update(namespace_delete=99),
                 'namespace never goes': lambda c: c.faults.update(ghost=True),
                 'policy delete fails': lambda c: c.faults.update(policy_delete=99),
                 'https unhealthy': lambda c: setattr(c, 'healthy', False)}
        for name, change in cases.items():
            cluster = FakeAzure()
            directory = tempfile.mkdtemp()
            with mock.patch.object(az, 'DEADLINE', FUTURE), mock.patch.object(az.subprocess, 'run', cluster.run), mock.patch.object(az, 'time', FakeTime()), \
                 mock.patch.object(az.p8, 'request', cluster.request), mock.patch.dict(os.environ, {}):
                c = self.campaign(cluster, directory); c.converge = lambda: None
                c.start(); change(cluster)
                result = c.restore()
            self.assertIs(result['restored'], False, name)
            self.assertTrue(result['problems'] or not result.get('https_healthy'), name)


class MeasureSmokeTests(unittest.TestCase):
    """The live measure() path on stubs with the real driver, sampler and AMW projection (10s plan copy).

    The stubbed HAProxy/log sources disagree with the demand, so the run must end invalid: consumed in the
    ledger, raw and the accounting failure saved, every port-forward reaped. This is plumbing, not evidence.
    """
    def test_inconsistent_window_is_consumed_saved_and_invalid(self):
        directory = Path(tempfile.mkdtemp())
        value = manifest(); v = value['plan'] | {'duration_seconds': 10, 'drain_seconds': 5, 'scrape_seconds': 1, 'ingestion_seconds': 1}
        ts = [t | {'name': 'pod-' + t['uid']} for t in targets('isolated')]
        forwards = []
        class Forward:
            def __init__(self, *args): forwards.append(self); self.stopped = False
            def alive(self): return True
            def stop(self): self.stopped = True
        class Fetch:
            def __init__(self, ports, path): pass
            def ready(self, t): return True
            def __call__(self, t): return {k: 0 for k in m.STATS}
        class Client:
            token, title, counts = 'tok', 'T', {'critical': 0, 'bulk': 0}
            def critical(self, op, index, unauthenticated=False):
                return {'status': 404 if unauthenticated else 200, 'body': b'{}'}
            def issue_matches(self, body): return True
            def bulk(self, op, index): return {'semantic_result': True}
            def probes(self):
                def probe(kind):
                    def call(op, index):
                        self.counts[kind] += 1
                        return {'semantic_result': True, 'status': 200, 'error_class': 'none', 'overload': False}
                    return call
                return {k: probe(k) for k in m.CLASSES}
        info = {'Pid': 8, 'Start_time_sec': 1, 'Uptime_sec': 1, 'Nbthread': 1, 'Nbproc': 1, 'Maxconn': 256, 'DroppedLogs': 0, 'MaxconnReached': 0}
        snapshot = {'ring': [], 'info': info, 'stats': m.parse_haproxy_stats(t10.stats_text([], 'isolated'))}
        invariants = {k: 'c' * 64 for k in ('ingress_config_sha256', 'native_route_sha256', 'tls_auth_sha256', 'target_resources_sha256',
                      'proxy_retries_sha256', 'sentinel_sha256', 'confounder_policy_sha256')}
        invariants.update(stable_revision=value['identity']['stable_revision'], haproxy_image_id='sha256:x', haproxy_processes=1, haproxy_threads=1, haproxy_maxconn=256)
        pods = [{'name': t['name'], 'uid': t['uid']} for t in ts]
        fetch_amw = t10.amw(lambda: t10.prometheus(pods, {t['uid']: [0] for t in ts}, lambda uid, key, t: 0, namespace=az.NS))
        rt = mock.Mock()
        rt.pod.side_effect = lambda ns, selector: {'metadata': {'name': 'p', 'uid': 'stable'}, 'status': {'containerStatuses': [{'name': 'haproxy', 'imageID': 'sha256:x'}]}}
        c = object.__new__(az.Campaign)
        c.value, c.identity, c.v, c.f = value, value['identity'], v, value['fixture']
        c.out, c.rt, c.client, c.prom_token = directory, rt, Client(), 'token'
        c.transport = {'tls_verification': 'certificate-and-hostname'}
        c.stable = {'s': 1}
        with mock.patch.object(az, 'DEADLINE', FUTURE):
            c.ledger = az.Ledger(directory / 'ledger.jsonl', value)
            c.ledger.start('healthy', 'isolated')
        stubs = {'identify': lambda arm: ts, 'haproxy_snapshot': lambda: copy.deepcopy(snapshot), 'invariants': lambda *a: dict(invariants),
                 'guard_snapshot': lambda uids: {'pods': {}, 'nodes': [], 'postgres': {}}, 'stable_snapshot': lambda: {'s': 1}, 'argo_stable': lambda: True,
                 'log_counts': lambda targets, since: {'ingress': {'i0': []}, 'target': {t['uid']: [] for t in ts}, 'app': {t['uid']: [] for t in ts}}}
        for name, stub in stubs.items(): setattr(c, name, stub)
        sentinel = {'semantic_result': True, 'start_monotonic': 0, 'end_monotonic': 0, 'status': 200, 'error_class': 'none'}
        with mock.patch.object(az, 'DEADLINE', FUTURE), mock.patch.object(az, 'Forward', Forward), mock.patch.object(az.pair, 'AdminFetch', Fetch), \
             mock.patch.object(az.p8.p4, 'request', lambda *a, **k: dict(sentinel)), mock.patch.object(az.p8.p7, 'http_json', lambda url, token, timeout, form: fetch_amw('/api/v1/query', form)):
            with self.assertRaises(ValueError):
                c.measure('isolated', 'measured')
        run = directory / 'measured-isolated'
        raw = json.loads((run / 'raw.json').read_text())
        self.assertEqual(sum(e['record'] == 'operation' for e in raw['events']), 45)    # 10s: 5 critical + 40 bulk arrivals
        self.assertTrue(raw['samples'] and raw['managed_polls'] and raw['sentinels'])
        self.assertTrue((run / 'accounting-failure.json').exists())
        self.assertFalse((run / 'run.json').exists())
        self.assertEqual([r['step'] for r in c.ledger.rows()], ['healthy', 'measured'])
        self.assertEqual((len(forwards), all(f.stopped for f in forwards)), (3, True))


class HealthySmokeTests(unittest.TestCase):
    """The shared Local probe table driven through the Azure client connection (stubbed HTTPS responses)."""
    def campaign(self, wrong=None):
        directory = Path(tempfile.mkdtemp())
        value = manifest()
        c = object.__new__(az.Campaign)
        c.value, c.identity, c.v, c.f, c.out = value, value['identity'], value['plan'], value['fixture'], directory
        c.transport = {'tls_verification': 'certificate-and-hostname'}
        with mock.patch.object(az, 'DEADLINE', FUTURE):
            c.ledger = az.Ledger(directory / 'ledger.jsonl', value)
        plan = {(method, path, tuple(sorted(headers))): (name, expected) for name, method, path, headers, expected, _ in
                az.pair.local.probe_plan(F, {'Authorization': 'token tok'}, {'Authorization': 'Basic x'})}
        issue = json.dumps({'number': 1, 'title': 'T'}).encode()
        class Connection:
            def request(self, method, path, headers=None, body=None):
                name, status = plan[(method, path, tuple(sorted(headers)))]
                if name == wrong: status = 200 if status != 200 else 403
                payload = issue if name in {'critical', 'spoof-cannot-change-critical', 'canonical-dot-segment'} else b'# service=git-upload-pack'
                self.response = mock.Mock(status=status, read=lambda: payload)
            def getresponse(self): return self.response
            def close(self): pass
        c.client = mock.Mock(token='tok', title='T', git_auth='Basic x', connection=Connection, bulk=lambda op, index: {'semantic_result': True})
        c.identify = lambda arm: []
        return c

    def test_probe_table_through_the_managed_ingress_client(self):
        with mock.patch.object(az, 'DEADLINE', FUTURE):
            result = self.campaign().healthy('shared')
            self.assertEqual(len(result['probes']), 13)
            for wrong in ('canonical-dot-segment', 'negative-7', 'native-auth-deny', 'credential-body-exclusion'):
                with self.assertRaises(ValueError, msg=wrong): self.campaign(wrong).healthy('shared')


class SequenceTests(unittest.TestCase):
    """run_campaign over a stub campaign: order, fail-closed calibration and always-on rollback."""
    def run_with(self, invalid_calibration=False, calibrate=True, fail_measure=None):
        calls = []
        class Stub:
            def __init__(self, value, approval, ledger, output):
                self.out = Path(output); self.out.mkdir()
            def start(self): calls.append('start')
            def setup(self, arm): calls.append('setup-' + arm)
            def healthy(self, arm): calls.append('healthy-' + arm); return {'arm': arm}
            def measure(self, arm, phase):
                calls.append(phase + '-' + arm)
                if fail_measure == (phase, arm): raise ValueError('targets did not drain')
                (self.out / (phase + '-' + arm)).mkdir()
                run = t10.azure(arm)
                if invalid_calibration and phase == 'calibration': run['managed_samples'] = []
                return run
            def restore(self): calls.append('restore'); return {'restored': True}
        directory = tempfile.mkdtemp()
        with mock.patch.object(az, 'Campaign', Stub):
            code = az.run_campaign(manifest() | {'identity': t8.identity() | {'source_sha': SHA}}, {}, None, Path(directory) / 'out', calibrate)
        out = Path(directory) / 'out'
        return code, calls, (json.loads((out / 'result.json').read_text()) if (out / 'result.json').exists() else None)

    def test_positive_pair_after_healthy_and_calibration(self):
        code, calls, result = self.run_with()
        self.assertEqual(code, 0)
        self.assertEqual(result['status'], 'positive')
        self.assertEqual(calls[-1], 'restore')
        self.assertLess(calls.index('healthy-isolated'), calls.index('calibration-isolated'))
        self.assertLess(calls.index('calibration-shared'), calls.index('measured-shared'))

    def test_invalid_calibration_or_failed_run_stops_and_still_restores(self):
        for kwargs in ({'invalid_calibration': True}, {'fail_measure': ('measured', 'isolated'), 'calibrate': False}):
            code, calls, result = self.run_with(**kwargs)
            self.assertEqual((code, result, calls[-1]), (1, None, 'restore'))
        self.assertNotIn('measured-shared', self.run_with(invalid_calibration=True)[1])


if __name__ == '__main__':
    unittest.main()
