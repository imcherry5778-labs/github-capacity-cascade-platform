#!/usr/bin/env python3
"""P8 bounded Azure adapter. Rendering never deploys; runtime commands need P8 approval."""
import concurrent.futures
import base64
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import math
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import threading
import time
import urllib.parse
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]

def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

p4 = module('p4', 'shared-gate-saturation.py')
p7 = module('p7', 'azure-operations.py')
require, save, load, digest = p4.require, p4.save, p4.read, p4.digest
PINS = dict(line.split('=', 1) for line in (ROOT / 'versions.env').read_text().splitlines() if line and not line.startswith('#'))
NS = 'p8-shared-gate'
SQL = """BEGIN READ ONLY; SET LOCAL statement_timeout='3s';
SELECT json_build_object('query_ok',true,'connections',(SELECT count(*) FROM pg_stat_activity),
 'max_connections',current_setting('max_connections')::int,
 'reserved',current_setting('superuser_reserved_connections')::int+current_setting('reserved_connections')::int,
 'database_bytes',pg_database_size(current_database())); COMMIT;"""


def utc():
    return datetime.now(timezone.utc).isoformat()


def plan(value):
    require(set(value) == {'max_requests', 'hold_ms', 'logical_operations', 'concurrency', 'waves', 'wave_interval_seconds'}, 'scenario fields')
    p4.scenario({k: value[k] for k in ('max_requests', 'hold_ms', 'logical_operations', 'concurrency')})
    require(type(value['waves']) is int and 1 <= value['waves'] <= 120, 'wave count bounds')
    require(type(value['wave_interval_seconds']) in {int, float} and 1 <= value['wave_interval_seconds'] <= 30, 'wave pacing bounds')
    require(90 <= (value['waves'] - 1) * value['wave_interval_seconds'] <= 600, 'window must cover multiple metric/controller cycles')
    return value


def identity(value):
    require(set(value) == {'campaign', 'source_sha', 'cluster_resource_id', 'cluster_uid', 'revision',
                           'stable_revision', 'ext_authz_image', 'ingress_selector', 'pg_resource_id', 'forgejo_hostname'}, 'identity fields')
    hostname = value['forgejo_hostname']
    require(isinstance(hostname, str) and len(hostname) <= 253 and '.' in hostname and
            all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in hostname.split('.')), 'exact normalized Forgejo hostname required')
    p7.operations.transport('https://' + hostname, 'azure-aks')
    require(re.fullmatch('[a-z][a-z0-9]{3,15}', value['campaign']), 'campaign identifier')
    require(all(re.fullmatch('[0-9a-f]{40}', value[k]) for k in ('source_sha', 'stable_revision')), 'exact source revisions')
    require(re.fullmatch('[0-9a-f-]{36}', value['cluster_uid']), 'cluster UID')
    require(re.fullmatch('asm-[0-9]+-[0-9]+', value['revision']), 'managed revision')
    require(re.fullmatch(r'[a-z0-9]+\.azurecr\.io/ext-authz-sim@sha256:[0-9a-f]{64}', value['ext_authz_image']), 'ACR digest required')
    require(value['ingress_selector'] and all(re.fullmatch('[a-zA-Z0-9./_-]+', k) and
            re.fullmatch('[a-zA-Z0-9._-]+', v) for k, v in value['ingress_selector'].items()), 'exact ingress selector')
    for key, suffix in (('cluster_resource_id', 'Microsoft.ContainerService/managedClusters/'),
                        ('pg_resource_id', 'Microsoft.DBforPostgreSQL/flexibleServers/')):
        require(re.fullmatch(r'/subscriptions/[0-9a-f-]{36}/resource[Gg]roups/[a-zA-Z0-9_-]+/providers/' + suffix + r'[a-zA-Z0-9_-]+', value[key]), 'resource identity')
    return value


def measurement_transport(value):
    identity(value)
    transport = p7.operations.transport(os.environ['FORGEJO_URL'], 'azure-aks', os.environ.get('JOURNEY_DNS_OVERRIDE'))
    require(urllib.parse.urlsplit(transport['endpoint']).hostname == value['forgejo_hostname'], 'measurement hostname differs from approved Forgejo hostname')
    return transport


def render(value):
    identity(value)
    labels = {'p8.campaign': value['campaign']}
    def obj(api, kind, name, ns=NS, **kw):
        return dict(apiVersion=api, kind=kind, metadata=dict(name=name, namespace=ns, labels=labels), **kw)
    # Reuse the exact P4 HAProxy policy; replace only the experiment namespace.
    source = (ROOT / 'experiments/fixtures/shared-gate/resources.yaml').read_text()
    hp = textwrap.dedent(source.split('  haproxy.cfg: |\n', 1)[1].split('\n---', 1)[0]).replace('shared-gate.svc', NS + '.svc').rstrip() + '\n'
    hp = hp.replace('frontend check\n', 'frontend check\n  option httpclose\n')
    resources = [dict(apiVersion='v1', kind='Namespace', metadata={'name': NS, 'labels': labels | {'istio.io/rev': value['revision']}}),
                 obj('v1', 'ResourceQuota', 'p8-boundary', spec={'hard': {'pods': '4', 'requests.cpu': '1500m',
                     'requests.memory': '2048Mi', 'limits.cpu': '1500m', 'limits.memory': '2048Mi', 'persistentvolumeclaims': '0'}}),
                 obj('v1', 'ConfigMap', 'haproxy', data={'haproxy.cfg': hp}),
                 obj('v1', 'ConfigMap', 'ext-authz-hold', data={'hold-ms': '0'})]
    for name, container, inject in (
        ('haproxy', dict(name='haproxy', image=PINS['HAPROXY_IMAGE'], args=['-W', '-db', '-f', '/config/haproxy.cfg']), False),
        ('ext-authz-sim', dict(name='app', image=value['ext_authz_image'], env=[{'name': 'CHECK_HOLD_FILE', 'value': '/config/hold-ms'}]), True)):
        container.update(imagePullPolicy='IfNotPresent', ports=[{'containerPort': 8080}],
            readinessProbe={'tcpSocket': {'port': 8080}}, resources={'requests': {'cpu': '50m', 'memory': '64Mi'},
                'limits': {'cpu': '100m' if inject else '250m', 'memory': '128Mi' if inject else '256Mi'}},
            volumeMounts=[{'name': 'config', 'mountPath': '/config', 'readOnly': True}])
        if inject:
            container['securityContext'] = {'readOnlyRootFilesystem': True, 'allowPrivilegeEscalation': False, 'runAsUser': 10001}
        annotations = {'sidecar.istio.io/inject': str(inject).lower()}
        if inject:
            annotations.update({'sidecar.istio.io/proxyCPU': '100m', 'sidecar.istio.io/proxyMemory': '128Mi',
                                'sidecar.istio.io/proxyCPULimit': '225m', 'sidecar.istio.io/proxyMemoryLimit': '256Mi'})
        resources += [obj('apps/v1', 'Deployment', name, spec={'replicas': 1, 'strategy': {'type': 'Recreate'},
            'selector': {'matchLabels': {'app': name}}, 'template': {'metadata': {'labels': labels | {'app': name}, 'annotations': annotations},
                'spec': {'automountServiceAccountToken': False, 'containers': [container],
                         'volumes': [{'name': 'config', 'configMap': {'name': 'ext-authz-hold' if inject else 'haproxy'}}]}}}),
            obj('v1', 'Service', name, spec={'selector': {'app': name}, 'ports': [{'name': 'http-check', 'port': 8080, 'targetPort': 8080}]})]
    resources += [obj('networking.istio.io/v1', 'Sidecar', 'ext-authz-sim', spec={
        'workloadSelector': {'labels': {'app': 'ext-authz-sim'}}, 'inboundConnectionPool': {'http': {'http2MaxRequests': 1024}}}),
        obj('autoscaling/v2', 'HorizontalPodAutoscaler', 'hpa-app-cpu', spec={
            'scaleTargetRef': {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'name': 'ext-authz-sim'}, 'minReplicas': 1, 'maxReplicas': 2,
            'metrics': [{'type': 'ContainerResource', 'containerResource': {'container': 'app', 'name': 'cpu',
                'target': {'type': 'Utilization', 'averageUtilization': 60}}}]}),
        obj('v1', 'Pod', 'p8-db-client', spec={'automountServiceAccountToken': False, 'restartPolicy': 'Never',
            'containers': [{'name': 'db', 'image': PINS['POSTGRES_IMAGE'], 'command': ['sleep', 'infinity'],
                'envFrom': [{'secretRef': {'name': 'p8-db-read'}}],
                'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'}, 'limits': {'cpu': '100m', 'memory': '128Mi'}}}]})]
    resources[-1]['metadata']['annotations'] = {'sidecar.istio.io/inject': 'false'}
    policy = obj('security.istio.io/v1', 'AuthorizationPolicy', 'p8-shared-gate', ns='aks-istio-ingress',
                 spec={'selector': {'matchLabels': value['ingress_selector']}, 'action': 'CUSTOM',
                       'provider': {'name': 'p8-shared-gate'}, 'rules': [{'to': [{'operation': {
                           'hosts': [value['forgejo_hostname'], value['forgejo_hostname'] + ':443']}}]}]})
    return {'fixtures.json': {'apiVersion': 'v1', 'kind': 'List', 'items': resources}, 'policy.json': policy}


def mesh_overlay(original, value):
    identity(value)
    require(original['metadata']['name'] == 'istio-shared-configmap-' + value['revision'] and
            original['metadata']['namespace'] == 'aks-istio-system' and not original['metadata'].get('ownerReferences') and
            not original['metadata'].get('labels', {}).get('argocd.argoproj.io/instance'), 'operator-owned revision shared ConfigMap only')
    result = copy.deepcopy(original)
    mesh = json.loads(result['data']['mesh'])  # P6 renderer writes JSON; unknown encoding fails closed.
    providers = mesh.setdefault('extensionProviders', [])
    require(not any(p['name'] == 'p8-shared-gate' for p in providers), 'provider already exists')
    providers.append({'name': 'p8-shared-gate', 'envoyExtAuthzHttp': {
        'service': 'haproxy.' + NS + '.svc.cluster.local', 'port': 8080, 'timeout': '5s', 'failOpen': False,
        'includeRequestHeadersInCheck': ['x-operation-id', 'x-attempt-id', 'x-gate-test-deny'],
        'includeAdditionalHeadersInCheck': {'authorization': 'p4-check-without-credentials'},
        'headersToDownstreamOnDeny': ['x-gate-decision']}})
    matcher = mesh.setdefault('defaultConfig', {}).setdefault('proxyStatsMatcher', {})
    matcher['inclusionSuffixes'] = sorted(set(matcher.get('inclusionSuffixes', [])) | set(p4.SUFFIXES))
    result['data']['mesh'] = json.dumps(mesh)
    # Only data is patched; UID/resourceVersion remain protected operator restoration guards.
    return {'data': result['data']}


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def gateway_scope(value, policy, listeners):
    """Check the live policy and the RBAC metadata gate that enables CUSTOM calls.

    Selected Istio 1.30 emits exact, case-insensitive :authority matchers and a
    provider-specific RBAC shadow policy. Unknown/broader shapes fail closed.
    """
    expected = render(value)['policy.json']
    require(policy['metadata']['name'] == expected['metadata']['name'] and
            policy['metadata']['namespace'] == expected['metadata']['namespace'] and
            policy['spec'] == expected['spec'], 'actual CUSTOM selector/provider/hostname policy drift')
    hosts = set(expected['spec']['rules'][0]['to'][0]['operation']['hosts'])
    def permission_hosts(permission):
        if set(permission) == {'header'}:
            header = permission['header']
            require(set(header) == {'name', 'string_match'} and header['name'] == ':authority' and
                    set(header['string_match']) == {'exact', 'ignore_case'} and header['string_match']['ignore_case'] is True,
                    'effective CUSTOM host matcher is not exact authority')
            return {header['string_match']['exact']}
        for key in ('and_rules', 'or_rules'):
            if set(permission) == {key}:
                rules = permission[key].get('rules', [])
                require(rules, 'empty effective CUSTOM host matcher')
                groups = [permission_hosts(rule) for rule in rules]
                return set.intersection(*groups) if key == 'and_rules' else set.union(*groups)
        raise ValueError('unrestricted/unknown effective CUSTOM permission')
    prefix = 'istio-ext-authz-p8-shared-gate'
    policy_id = prefix + '-ns[aks-istio-ingress]-policy[p8-shared-gate]-rule[0]'
    matches = 0
    for hcm in walk(listeners):
        filters = hcm.get('http_filters', [])
        for index, filt in enumerate(filters):
            if filt.get('name') != 'envoy.filters.http.ext_authz':
                continue
            enabled = filt['typed_config'].get('filter_enabled_metadata')
            require(enabled == {'filter': 'envoy.filters.http.rbac',
                'path': [{'key': 'istio_ext_authz_shadow_effective_policy_id'}],
                'value': {'string_match': {'prefix': prefix}}}, 'effective CUSTOM provider metadata gate differs')
            policies = []
            for prior in filters[:index]:
                config = prior.get('typed_config', {})
                if prior.get('name') == 'envoy.filters.http.rbac' and config.get('shadow_rules_stat_prefix') == 'istio_ext_authz_':
                    require(config['shadow_rules'].get('action') == 'DENY', 'effective CUSTOM shadow rule action differs')
                    policies.extend((key, rule) for key, rule in config['shadow_rules'].get('policies', {}).items() if key.startswith(prefix))
            require(len(policies) == 1 and policies[0][0] == policy_id, 'effective CUSTOM policy absent/extra rules')
            permissions = policies[0][1].get('permissions', [])
            require(permissions and all(permission_hosts(p) == hosts for p in permissions), 'effective CUSTOM hostname scope differs')
            matches += 1
    require(matches > 0, 'effective CUSTOM filter chain absent')
    return {'hostname': value['forgejo_hostname'], 'hosts': sorted(hosts), 'policy_uid': policy['metadata']['uid'],
            'policy_spec_sha256': digest(policy['spec']), 'effective_policy_id': policy_id, 'filter_chains': matches}


def target_mapping(dump, stat_payload, capacity, listeners=None, *, allowed_capacities=None):
    clusters = [v['cluster'] for v in walk(dump) if isinstance(v.get('cluster'), dict) and
                v['cluster'].get('name', '').startswith('inbound|')]
    bindings = {v['route']['cluster'] for chain in walk(listeners) if chain.get('filter_chain_match', {}).get('destination_port') == 8080
                for v in walk(chain) if isinstance(v.get('route'), dict) and v['route'].get('cluster')}
    selected = [c for c in clusters if any(v.get('port_value') == 8080 for v in walk(c.get('load_assignment', {}))) or
                c.get('type') == 'ORIGINAL_DST' and c['name'] in bindings]
    require(len(selected) == 1, 'actual inbound app endpoint cluster absent/ambiguous')
    c = selected[0]
    thresholds = c.get('circuit_breakers', {}).get('thresholds', [])
    if allowed_capacities is not None:
        actual = [t.get('max_requests') for t in thresholds if t.get('priority', 'DEFAULT') == 'DEFAULT']
        require(len(actual) == 1 and actual[0] in allowed_capacities, 'actual active-request capacity outside release boundary')
        capacity = actual[0]
    require(any(t.get('priority', 'DEFAULT') == 'DEFAULT' and t.get('max_requests') == capacity for t in thresholds), 'actual active-request capacity differs')
    prefixes = {'cluster.' + n + '.' for n in (c['name'], c.get('alt_stat_name')) if n}
    names = {s['name']: s['value'] for s in stat_payload['stats'] if any(s.get('name', '').startswith(p) and
             s['name'][len(p):] in p4.SUFFIXES for p in prefixes)}
    require(len(names) == len(p4.SUFFIXES) and set(p4.by_suffix(names)) == set(p4.SUFFIXES), 'required actual target stats absent/ambiguous')
    return {'cluster_name': c['name'], 'alt_stat_name': c.get('alt_stat_name'), 'capacity': capacity,
            'stat_names': sorted(names), 'endpoint_mapping': 'listener-port-8080-to-ORIGINAL_DST' if c.get('type') == 'ORIGINAL_DST' else 'load_assignment'}, names


def quantity(value):
    match = re.fullmatch(r'([0-9]+(?:[.][0-9]+)?)(n|u|m|Ki|Mi|Gi|Ti|k|M|G)?', value)
    require(match is not None, 'unsupported resource quantity')
    scales = {None: 1, 'n': 1e-9, 'u': 1e-6, 'm': .001, 'Ki': 1024, 'Mi': 1024**2, 'Gi': 1024**3, 'Ti': 1024**4, 'k': 1000, 'M': 1000**2, 'G': 1000**3}
    return float(match[1]) * scales[match[2]]


def metric_window(value):
    match = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?', value)
    require(match and any(match.groups()), 'resource metric window missing/invalid')
    seconds = sum(float(v or 0) * scale for v, scale in zip(match.groups(), (3600, 60, 1)))
    require(0 < seconds <= 120, 'resource metric window outside bounded observation contract')
    return seconds


def path_delta(before, after):
    require(after['checks'][:len(before['checks'])] == before['checks'], 'app log prefix changed/rotated')
    result = {'checks': after['checks'][len(before['checks']):], 'proxies': {}, 'proxy_streams': {}}
    for label, streams in before['proxies'].items():
        require(set(streams) == set(after['proxies'][label]), 'proxy log Pod inventory changed')
        result['proxies'][label], result['proxy_streams'][label] = [], {}
        for uid, records in streams.items():
            current = after['proxies'][label][uid]
            require(current[:len(records)] == records, 'proxy log prefix changed/rotated')
            result['proxies'][label].extend(current[len(records):])
            result['proxy_streams'][label][uid] = {'before': len(records), 'after': len(current)}
    return result


def admission(value, pods):
    """Conservative sum includes every init/native sidecar plus Pod overhead."""
    require(1 <= len(pods) <= 4, 'admitted Pod cap')
    total = {kind: {key: 0 for key in ('cpu', 'memory')} for kind in ('requests', 'limits')}
    names = []
    for pod in pods:
        require(pod['metadata']['namespace'] == NS and pod['metadata'].get('labels', {}).get('p8.campaign') == value['campaign'], 'unexpected Pod owner')
        spec = pod['spec']
        require(not spec.get('ephemeralContainers') and not spec.get('hostNetwork') and not any('persistentVolumeClaim' in v for v in spec.get('volumes', [])), 'unexpected admission/PVC')
        containers = spec['containers'] + spec.get('initContainers', [])
        for container in containers:
            for kind in total:
                for key in total[kind]:
                    require(key in container.get('resources', {}).get(kind, {}), 'injected/container resources must be bounded')
                    total[kind][key] += quantity(container['resources'][kind][key])
        for kind in total:
            for key in total[kind]:
                total[kind][key] += quantity(spec.get('overhead', {}).get(key, '0'))
        if any(c['name'] == 'app' for c in spec['containers']):
            app = next(c for c in spec['containers'] if c['name'] == 'app')
            require(app['resources']['requests']['cpu'] == '50m', 'app CPU request changed')
        names.append({'name': pod['metadata']['name'], 'uid': pod['metadata']['uid'],
                      'containers': [{'name': c['name'], 'native_sidecar': c.get('restartPolicy') == 'Always', 'resources': c['resources']} for c in containers]})
    require(all(total[k]['cpu'] <= 1.5 + 1e-9 and total[k]['memory'] <= 2048 * 1024**2 for k in total), 'admitted aggregate exceeds approval design')
    return {'pods': names, 'conservative_sum': total, 'note': 'all sequential init resources summed too; upper bound on scheduler effective resources'}


class Runtime:
    def __init__(self, value, approval_key='P8_AZURE_APPROVED'):
        self.value = identity(value)
        self.since = utc()
        require(os.environ.get(approval_key) == value['source_sha'], 'explicit campaign execution acknowledgement required')
        require(datetime.now(timezone.utc) < datetime(2026, 10, 30, 1, 30, tzinfo=timezone.utc), 'environment retention deadline reached')
        require(os.environ.get('KUBECONFIG') and Path(os.environ['KUBECONFIG']).is_file(), 'dedicated protected kubeconfig required')
        require(Path(os.environ['KUBECONFIG']).stat().st_mode & 0o077 == 0, 'kubeconfig must be protected')
        require(p7.command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']) == value['source_sha'] and
                not p7.command(['git', '-C', str(ROOT), 'status', '--porcelain']), 'clean exact source required')
        cluster = json.loads(p7.command(['az', 'aks', 'show', '--resource-group', value['cluster_resource_id'].split('/')[4],
                                         '--name', value['cluster_resource_id'].rsplit('/', 1)[1], '-o', 'json']))
        server = self.k('config', 'view', '--minify', '-o', 'jsonpath={.clusters[0].cluster.server}')
        require(urllib.parse.urlsplit(server).hostname in {cluster.get('fqdn'), cluster.get('privateFqdn')} and
                urllib.parse.urlsplit(server).scheme == 'https', 'kubeconfig API server differs from actual AKS target')
        require(self.k('get', 'namespace', 'kube-system', '-o', 'jsonpath={.metadata.uid}') == value['cluster_uid'], 'cluster identity mismatch')
        require(cluster['serviceMeshProfile']['istio']['revisions'] == [value['revision']], 'mesh revision drift')
        require(all(not p.get('enableAutoScaling') for p in cluster['agentPoolProfiles']), 'fixed existing nodes required')

    def k(self, *args):
        return p7.command(['kubectl', '--request-timeout=15s', *args])

    def j(self, *args):
        return json.loads(self.k(*args))

    def pods(self, ns, selector):
        return self.j('-n', ns, 'get', 'pods', '-l', selector, '-o', 'json')['items']

    def pod(self, ns, selector):
        pods = self.pods(ns, selector)
        require(len(pods) == 1 and not pods[0]['metadata'].get('deletionTimestamp'), 'single stable selected Pod required')
        return pods[0]

    def admin(self, ns, pod, path):
        return self.j('-n', ns, 'exec', pod, '-c', 'istio-proxy', '--', 'pilot-agent', 'request', 'GET', path)

    def targets(self):
        return self.pods(NS, 'app=ext-authz-sim')

    def configuration(self, config, *, target_range=(1, 1), haproxy_config=None, hpa_name='hpa-app-cpu',
                      target_pods=None, releasing=False):
        measurement_transport(self.value)
        policy = self.j('-n', 'aks-istio-ingress', 'get', 'authorizationpolicy', 'p8-shared-gate', '-o', 'json')
        result = {'targets': [], 'scenario': config, 'ingress': [], 'forgejo_hostname': self.value['forgejo_hostname']}
        for pod in self.targets() if target_pods is None else target_pods:
            name = pod['metadata']['name']
            require(next(c['image'] for c in pod['spec']['containers'] if c['name'] == 'app') == self.value['ext_authz_image'], 'target source image drift')
            mapping, _ = target_mapping(self.admin(NS, name, 'config_dump?resource=dynamic_active_clusters'),
                self.admin(NS, name, 'stats?format=json&filter=upstream_rq_'), config['max_requests'],
                self.admin(NS, name, 'config_dump?resource=dynamic_listeners'),
                allowed_capacities=(2, 1024) if releasing else None)
            hold = int(self.k('-n', NS, 'exec', name, '-c', 'app', '--', 'cat', '/config/hold-ms'))
            require(hold in (0, 1000) if releasing else hold == config['hold_ms'], 'hold convergence')
            if releasing:
                result.setdefault('fault_state', {})[pod['metadata']['uid']] = {'hold_ms': hold, 'max_requests': mapping['capacity']}
            statuses = pod['status'].get('containerStatuses', []) + pod['status'].get('initContainerStatuses', [])
            result['targets'].append({'uid': pod['metadata']['uid'], 'name': name, 'mapping': mapping,
                'images': {s['name']: s['imageID'] for s in statuses},
                'proxy_version': self.admin(NS, name, 'server_info')['version'],
                'runtime_guard': self.admin(NS, name, 'runtime?format=json').get('entries', {}).get(p4.GUARD),
                'stats_matcher': [v['stats_matcher'] for v in walk(self.admin(NS, name, 'config_dump?mask=bootstrap.stats_config')) if 'stats_matcher' in v]})
        require(target_range[0] <= len(result['targets']) <= target_range[1], 'target replica range differs')
        hp = self.pod(NS, 'app=haproxy')
        require(next(c['image'] for c in hp['spec']['containers'] if c['name'] == 'haproxy') == PINS['HAPROXY_IMAGE'], 'HAProxy source image drift')
        hp_config = self.k('-n', NS, 'exec', hp['metadata']['name'], '-c', 'haproxy', '--', 'cat', '/config/haproxy.cfg')
        require(hp_config == haproxy_config.rstrip('\n') if haproxy_config is not None else
                'retries 0' in hp_config and 'maxconn' not in hp_config and 'rate-limit' not in hp_config, 'HAProxy policy drift')
        result['haproxy'] = {'uid': hp['metadata']['uid'], 'config_sha256': hashlib.sha256(hp_config.encode()).hexdigest()}
        selector = ','.join(k + '=' + v for k, v in self.value['ingress_selector'].items())
        for ingress in self.pods('aks-istio-ingress', selector):
            name = ingress['metadata']['name']
            listeners = self.admin('aks-istio-ingress', name, 'config_dump?resource=dynamic_listeners')
            scope = gateway_scope(self.value, policy, listeners)
            filters = [v['typed_config'] for v in walk(listeners) if v.get('name') == 'envoy.filters.http.ext_authz']
            require(filters and all('haproxy.' + NS + '.svc.cluster.local' in f['http_service']['server_uri']['cluster'] and
                    f.get('failure_mode_allow', False) is False for f in filters), 'actual ingress check path/fail-closed mapping')
            require(all(any(h.get('key', '').lower() == 'authorization' and h.get('value') == 'p4-check-without-credentials'
                            for h in f['http_service']['authorization_request']['headers_to_add']) for f in filters), 'check credential replacement absent')
            routes = self.admin('aks-istio-ingress', name, 'config_dump?resource=dynamic_route_configs')
            selected = [v for v in walk(routes) if isinstance(v.get('route'), dict) and 'forgejo-http.forgejo.svc' in v['route'].get('cluster', '')]
            require(selected and all(v['route'].get('retry_policy', {}).get('num_retries', 0) == 0 for v in selected), 'actual Forgejo route retries')
            result['ingress'].append({'name': name, 'uid': ingress['metadata']['uid'], 'hostname_scope': scope,
                                      'provider_sha256': digest(filters), 'routes_sha256': digest(selected)})
        require(result['ingress'], 'ingress absent')
        stable = self.pod('forgejo', 'app.kubernetes.io/name=forgejo')
        result['stable'] = {'uid': stable['metadata']['uid'], 'images': {s['name']: s['imageID'] for s in
            stable['status'].get('containerStatuses', []) + stable['status'].get('initContainerStatuses', [])},
            'deployment_spec_sha256': digest(self.j('-n', 'forgejo', 'get', 'deployment', 'forgejo', '-o', 'json')['spec'])}
        result['targets'].sort(key=lambda t: t['uid'])
        result['ingress'].sort(key=lambda t: t['uid'])
        result['hpa_spec'] = self.j('-n', NS, 'get', 'hpa', hpa_name, '-o', 'json')['spec']
        return result

    def stats(self, actual):
        result = {}
        for t in actual['targets']:
            payload = self.admin(NS, t['name'], 'stats?format=json&filter=upstream_rq_')
            result[t['uid']] = {s['name']: s['value'] for s in payload['stats'] if s.get('name') in t['mapping']['stat_names']}
            require(sorted(result[t['uid']]) == t['mapping']['stat_names'], 'target stats disappeared')
        return result

    def haproxy(self):
        import csv
        import io
        text = self.k('-n', NS, 'exec', self.pod(NS, 'app=haproxy')['metadata']['name'], '-c', 'haproxy', '--',
                      'wget', '-qO-', 'http://127.0.0.1:8404/stats;csv')
        rows = [r for r in csv.DictReader(io.StringIO(text.removeprefix('# '))) if r['pxname'] == 'ext_authz' and r['svname'] == 'app']
        require(len(rows) == 1, 'HAProxy selected server absent')
        return {'status': rows[0]['status']} | {k: int(rows[0][k]) for k in p4.HAPROXY_FIELDS}

    def logs(self, actual):
        checks, proxies = [], {'target': {}, 'ingress': {}}
        for t in actual['targets']:
            records = [json.loads(line) for line in self.k('-n', NS, 'logs', t['name'], '-c', 'app').splitlines()]
            if records:
                p4.gate.validate_checks(records)
            checks += records
        for label, ns, pods in (('target', NS, actual['targets']), ('ingress', 'aks-istio-ingress', actual['ingress'])):
            for pod in pods:
                proxies[label][pod['uid']] = []
                for line in self.k('-n', ns, 'logs', pod['name'], '-c', 'istio-proxy').splitlines():
                    if not line.startswith('{'):
                        continue
                    row = json.loads(line)
                    if not {'status', 'detail', 'duration_ms', 'cluster'} <= set(row):
                        continue
                    proxies[label][pod['uid']].append({k: row[k] for k in ('status', 'detail', 'duration_ms', 'cluster')})
        return {'checks': checks, 'proxies': proxies}

    def guard(self, hpa_name='hpa-app-cpu', event_timestamps=False):
        owned = self.j('-n', NS, 'get', 'pods', '-o', 'json')['items']
        admitted = admission(self.value, owned)
        pods = [self.pod('forgejo', 'app.kubernetes.io/name=forgejo')] + owned
        nodes = self.j('get', 'nodes', '-o', 'json')['items']
        all_pods = self.j('get', 'pods', '-A', '-o', 'json')['items']
        headroom = []
        for node in nodes:
            used = {'cpu': 0, 'memory': 0}
            for pod in all_pods:
                if pod['spec'].get('nodeName') != node['metadata']['name'] or pod['status'].get('phase') in {'Succeeded', 'Failed'}:
                    continue
                for container in pod['spec']['containers'] + pod['spec'].get('initContainers', []):
                    for key in used:
                        used[key] += quantity(container.get('resources', {}).get('requests', {}).get(key, '0'))
                for key in used:
                    used[key] += quantity(pod['spec'].get('overhead', {}).get(key, '0'))
            headroom.append({'name': node['metadata']['name'], 'schedulable': not node['spec'].get('unschedulable') and
                not any(t['effect'] in {'NoSchedule', 'NoExecute'} for t in node['spec'].get('taints', [])),
                'cpu_free': quantity(node['status']['allocatable']['cpu']) - used['cpu'],
                'memory_free': quantity(node['status']['allocatable']['memory']) - used['memory']})
        metric = self.j('get', '--raw', '/apis/metrics.k8s.io/v1beta1/pods')
        node_metric = self.j('get', '--raw', '/apis/metrics.k8s.io/v1beta1/nodes')
        start = time.monotonic()
        sql = self.k('-n', NS, 'exec', 'p8-db-client', '-c', 'db', '--', 'psql', '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', SQL)
        db = json.loads(next(line for line in sql.splitlines() if line.startswith('{')))
        db['command_latency_seconds'] = time.monotonic() - start
        app = self.j('-n', 'argocd', 'get', 'application', 'forgejo-azure', '-o', 'json')
        require(app['spec']['sources'][1]['targetRevision'] == app['spec']['sources'][2]['targetRevision'] == self.value['stable_revision'] and
                app['spec']['syncPolicy']['automated'] == {'prune': False, 'selfHeal': True} and
                app['status']['sync']['status'] == 'Synced' and app['status']['health']['status'] == 'Healthy', 'stable Argo drift')
        return {'timestamp_utc': utc(), 'pods': sorted([p4.pod_guard(p) for p in pods], key=lambda p: p['uid']),
            'admission': admitted,
            'runtime_images': {p['metadata']['uid']: {s['name']: s['imageID'] for s in
                p['status'].get('containerStatuses', []) + p['status'].get('initContainerStatuses', [])} for p in pods},
            'node_headroom': headroom,
            'nodes': [{'name': n['metadata']['name'], 'conditions': {c['type']: c['status'] for c in n['status']['conditions'] if c['type'] in {'Ready', 'MemoryPressure', 'DiskPressure', 'PIDPressure'}}} for n in nodes],
            'pod_metrics': [{k: p[k] for k in ('metadata', 'timestamp', 'window', 'containers')} for p in metric['items'] if p['metadata']['namespace'] in {NS, 'forgejo'}],
            'node_metrics': node_metric['items'], 'postgres': db,
            'hpa': self.j('-n', NS, 'get', 'hpa', hpa_name, '-o', 'json')['status'],
            'events': [({'reason': e.get('reason'), 'type': e.get('type')} |
                        ({'timestamp_utc': e.get('lastTimestamp') or e.get('eventTime') or e['metadata']['creationTimestamp']} if event_timestamps else {})) for e in self.j('get', 'events', '-A', '-o', 'json')['items']
                       if e.get('type') == 'Warning' and e.get('metadata', {}).get('namespace') in {NS, 'forgejo'} and
                       (e.get('lastTimestamp') or e.get('eventTime') or e['metadata']['creationTimestamp']) >= self.since]}


def request(path, headers, expected=None, direct=False):
    endpoint = p7.operations.transport(os.environ['FORGEJO_URL'], 'azure-aks', os.environ.get('JOURNEY_DNS_OVERRIDE'))
    host = urllib.parse.urlsplit(endpoint['endpoint']).hostname
    require(all(re.fullmatch('[a-zA-Z-]+', k) and not any(c in v for c in '\r\n') for k, v in headers.items()), 'unsafe HTTP header')
    url = ('http://127.0.0.1:13000' if direct else endpoint['endpoint']) + path
    args = ['curl', '-q', '--noproxy', '*', '--proto', '=http' if direct else '=https',
            '--silent', '--show-error', '--max-time', '10', '--config', '-', '--write-out', '\n%{http_code}', url]
    if not direct and os.environ.get('JOURNEY_DNS_OVERRIDE'):
        args += ['--resolve', host + ':443:' + os.environ['JOURNEY_DNS_OVERRIDE']]
    # Headers travel through stdin; no credential-bearing argv/output artifact.
    curl_config = ''.join('header = ' + json.dumps(k + ': ' + v) + '\n' for k, v in headers.items())
    start = time.monotonic()
    status, semantic, error = None, False, 'transport'
    try:
        response = subprocess.run(args, input=curl_config.encode(), capture_output=True, timeout=12)
        end = time.monotonic()  # P7 single curl-command boundary; semantic parsing is outside timing.
        if response.returncode == 0:
            body, code = response.stdout.rsplit(b'\n', 1)
            status = int(code)
            if status == 200:
                if expected is None:
                    semantic = True
                else:
                    try:
                        value = json.loads(body)
                        semantic = value.get('number') == expected[0] and value.get('title') == expected[1] and value.get('state') == 'open' and value.get('pull_request') is None
                    except (ValueError, AttributeError):
                        pass
            error = 'none' if semantic else ('http_status' if status != 200 else 'semantic_error')
        elif response.returncode == 28:
            error = 'timeout'
    except subprocess.TimeoutExpired:
        end, error = time.monotonic(), 'timeout'
    return {'status': status, 'semantic_result': semantic, 'error_class': error,
            'start_monotonic': start, 'end_monotonic': end, 'duration_seconds': end - start}


def git_read(op, attempt):
    endpoint = p7.operations.transport(os.environ['FORGEJO_URL'], 'azure-aks', os.environ.get('JOURNEY_DNS_OVERRIDE'))
    host = urllib.parse.urlsplit(endpoint['endpoint']).hostname
    values = [('http.sslVerify', 'true'), ('http.proxy', ''), ('http.followRedirects', 'false'),
              ('http.extraHeader', 'Authorization: Basic ' + base64.b64encode((os.environ['DEV_USER'] + ':' + os.environ['DEV_TOKEN']).encode()).decode()), ('http.extraHeader', 'x-operation-id: ' + op),
              ('http.extraHeader', 'x-attempt-id: ' + attempt)]
    if os.environ.get('JOURNEY_DNS_OVERRIDE'):
        values.append(('http.curloptResolve', host + ':443:' + os.environ['JOURNEY_DNS_OVERRIDE']))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'FORGEJO_ADMIN_', 'DEV_TOKEN'))}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0', GIT_CONFIG_COUNT=str(len(values)))
    for i, (k, v) in enumerate(values):
        env['GIT_CONFIG_KEY_' + str(i)] = k
        env['GIT_CONFIG_VALUE_' + str(i)] = v
    start, success, error = time.monotonic(), False, 'transport'
    try:
        result = subprocess.run(['git', 'ls-remote', '--exit-code', endpoint['endpoint'] + '/' + os.environ['DEV_USER'] + '/journey.git', 'refs/heads/main'],
                                env=env, capture_output=True, text=True, timeout=10)
        success = result.returncode == 0 and result.stdout.split() == [os.environ['EXPECTED_MAIN_SHA'], 'refs/heads/main']
        error = 'none' if success else 'git_command'
    except subprocess.TimeoutExpired:
        error = 'timeout'
    return {'semantic_result': success, 'error_class': error, 'duration_seconds': time.monotonic() - start}


def measure(value, config, output, phase, max_attempts, frozen=None):
    plan(config)
    require(phase in {'calibration', 'no-retry', 'retry'} and max_attempts == (2 if phase == 'retry' else 1), 'paired retry policy')
    output = Path(output)
    output.mkdir(mode=0o700)
    try:
        measurement_transport(value)
        runtime = Runtime(value)
        actual = runtime.configuration(config)
        fingerprint = {'source_sha': value['source_sha'], 'identity': value, 'configuration': actual,
                       'slo_sha256': hashlib.sha256((ROOT / 'docs/evidence/p7-operations-20261028/initial-slo.json').read_bytes()).hexdigest()}
        if phase != 'calibration':
            require(frozen == fingerprint, 'frozen source/identity/scenario/runtime differs')
    except BaseException:
        save(output / 'invocation-failure.json', {'record': 'configuration-or-execution-gate-failed', 'phase': phase, 'timestamp_utc': utc()})
        raise
    save(output / 'configuration.json', fingerprint)
    path = f'/api/v1/repos/{os.environ["DEV_USER"]}/journey/issues/{int(os.environ["ISSUE_NUMBER"])}'
    expected = (int(os.environ['ISSUE_NUMBER']), os.environ['ISSUE_TITLE'])
    auth = {'Authorization': 'token ' + os.environ['DEV_TOKEN']}
    run = str(uuid.uuid4())
    lock = threading.Lock()
    def emit(row):
        with lock, (output / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(row, separators=(',', ':')) + '\n')
    emit({'record': 'run_start', 'run_id': run, 'timestamp_utc': utc(), 'phase': phase, 'max_attempts': max_attempts,
          'fingerprint': digest(fingerprint), 'transport': p7.operations.transport(os.environ['FORGEJO_URL'], 'azure-aks', os.environ.get('JOURNEY_DNS_OVERRIDE')),
          'direct_transport': 'authenticated HTTP through dedicated loopback Pod port-forward; public traffic uses verified HTTPS'})
    stop = threading.Event()
    def sample():
        while not stop.is_set():
            emit({'record': 'target', 'monotonic': time.monotonic(), 'stats': runtime.stats(actual)})
            stop.wait(.2)
    def guard():
        while not stop.is_set():
            emit({'record': 'guard', 'snapshot': runtime.guard()})
            stop.wait(5)
    def sentinel():
        while not stop.is_set():
            emit({'record': 'sentinel', 'result': request(path, auth, expected, direct=True)})
            stop.wait(.2)
    def operation(wave, i):
        op = f'{run}-w{wave}-op{i}'
        begin = time.monotonic()
        for count in range(1, max_attempts + 1):
            attempt = f'{op}-attempt-{count}'
            result = request(path, auth | {'x-operation-id': op, 'x-attempt-id': attempt}, expected)
            emit({'record': 'attempt', 'operation_id': op, 'attempt_id': attempt, 'attempt_index': count, **result})
            if result['semantic_result']:
                break
        emit({'record': 'operation', 'operation_id': op, 'attempt_count': count, 'success': result['semantic_result'], 'duration_seconds': time.monotonic() - begin})
    try:
        before_logs = runtime.logs(actual)
        save(output / 'before.json', {'stats': runtime.stats(actual), 'haproxy': runtime.haproxy(), 'guard': runtime.guard(), 'timestamp_utc': utc()})
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as monitors, concurrent.futures.ThreadPoolExecutor(max_workers=config['concurrency']) as clients:
            futures = [monitors.submit(f) for f in (sample, guard, sentinel)]
            try:
                for wave in range(config['waves']):
                    started = time.monotonic()
                    work = [clients.submit(operation, wave, i) for i in range(config['logical_operations'])]
                    git_op = f'{run}-git-{wave}'
                    emit({'record': 'git_read', 'operation_id': git_op, 'attempt_id': git_op + '-attempt-1',
                          **git_read(git_op, git_op + '-attempt-1')})
                    for future in work:
                        future.result()
                    elapsed = time.monotonic() - started
                    require(elapsed <= config['wave_interval_seconds'], 'demand pacing overrun; retain invalid run')
                    if wave + 1 < config['waves']:
                        stop.wait(config['wave_interval_seconds'] - elapsed)
                    for future in futures:
                        if future.done():
                            future.result()
                            raise ValueError('monitor exited early')
            finally:
                stop.set()
            for future in futures:
                future.result()
        time.sleep(2)  # bounded access-log flush, no additional workload
        require(runtime.configuration(config) == actual, 'runtime/replicas changed during measured run')
        save(output / 'after.json', {'stats': runtime.stats(actual), 'haproxy': runtime.haproxy(), 'guard': runtime.guard(), 'timestamp_utc': utc()})
        after_logs = runtime.logs(actual)
        save(output / 'path.json', path_delta(before_logs, after_logs))
        emit({'record': 'run_end', 'run_id': run, 'timestamp_utc': utc(), 'completed': True})
    except BaseException:
        emit({'record': 'run_failure', 'run_id': run, 'timestamp_utc': utc(), 'completed': False})
        raise


def guard_validation(snapshots, hpa_spec):
    require(hpa_spec['minReplicas'] == 1 and hpa_spec['maxReplicas'] == 2 and hpa_spec['metrics'] == [{
        'type': 'ContainerResource', 'containerResource': {'container': 'app', 'name': 'cpu',
        'target': {'type': 'Utilization', 'averageUtilization': 60}}}], 'app ContainerResource HPA contract')
    require(len(snapshots) >= 3, 'during-run guards absent')
    first = snapshots[0]
    times = []
    metric_ages = []
    for snap in snapshots:
        require(snap['pods'] == first['pods'] and all(p['ready'] and p['phase'] == 'Running' and not p['reason'] and
                all(c['ready'] and c['last_termination'] not in {'OOMKilled', 'Error'} for c in p['containers']) for p in snap['pods']), 'workload readiness/restart/replacement')
        require(snap['nodes'] and all(n['conditions'] == {'Ready': 'True', 'MemoryPressure': 'False', 'DiskPressure': 'False', 'PIDPressure': 'False'} for n in snap['nodes']), 'node pressure')
        require(snap['node_metrics'] and snap['pod_metrics'], 'resource observations absent')
        require(any(n['schedulable'] and n['cpu_free'] >= .15 and n['memory_free'] >= 192 * 1024**2 for n in snap['node_headroom']), 'no scheduling headroom for second replica')
        db = snap['postgres']
        require(db['query_ok'] and db['connections'] < db['max_connections'] - db['reserved'], 'DB connection exhaustion')
        hpa = snap['hpa']
        conditions = {c['type']: c for c in hpa.get('conditions', [])}
        require(all(conditions.get(k, {}).get('status') == 'True' for k in ('AbleToScale', 'ScalingActive')) and
                (conditions.get('ScalingLimited', {}).get('status') == 'False' or conditions.get('ScalingLimited', {}).get('reason') == 'TooFewReplicas'), 'metric/controller failure or replica cap')
        require(hpa['currentReplicas'] == hpa['desiredReplicas'] == 1 and hpa.get('currentMetrics'), 'HPA scale or metric changed')
        metric = [m['containerResource'] for m in hpa['currentMetrics'] if m.get('type') == 'ContainerResource' and
                  m['containerResource'].get('container') == 'app' and m['containerResource'].get('name') == 'cpu']
        require(len(metric) == 1 and type(metric[0]['current'].get('averageUtilization')) is int and
                0 <= metric[0]['current']['averageUtilization'] < 60, 'app CPU metric absent or above target; mismatch not established')
        for pod in snap['pods']:
            observation = [m for m in snap['pod_metrics'] if m['metadata']['name'] == pod['name']]
            require(len(observation) == 1 and {c['name'] for c in pod['containers']} <= {c['name'] for c in observation[0]['containers']}, 'workload/container resource metric absent')
            stamp = p7.utc(observation[0]['timestamp'])
            age = (p7.utc(snap['timestamp_utc']) - stamp).total_seconds()
            require(0 <= age <= 2 * metric_window(observation[0]['window']), 'stale resource metrics')
            metric_ages.append(age)
            require(all(quantity(c['usage']['cpu']) >= 0 and quantity(c['usage']['memory']) >= 0 for c in observation[0]['containers']), 'invalid resource metric value')
        require(not any(e['reason'] in {'FailedScheduling', 'FailedGetResourceMetric', 'FailedComputeMetricsReplicas'} for e in snap['events']), 'scheduling/metric error')
        targets = [p for p in snap['pod_metrics'] if p['metadata']['namespace'] == NS and p['metadata']['name'].startswith('ext-authz-sim-')]
        require(len(targets) == 1 and any(c['name'] == 'app' and c['usage'].get('cpu') for c in targets[0]['containers']), 'app metric absent')
        times.append(p7.utc(targets[0]['timestamp']))
    require(len(set(times)) >= 3 and (max(times) - min(times)).total_seconds() >= 60, 'actual metric update window too short')
    return {'metric_update_span_seconds': (max(times) - min(times)).total_seconds(),
            'resource_metric_age_max_seconds': max(metric_ages), 'freshness_rule': 'at most two reported CPU measurement windows; timestamps must also update across at least 60s',
            'app_cpu_scaling': 'no scale observed with healthy metric/controller and replica headroom'}


def validate_run(directory):
    directory = Path(directory)
    events = p4.rows(directory / 'events.jsonl')
    require(events[0]['record'] == 'run_start' and events[-1]['record'] == 'run_end' and events[-1]['completed'] and
            not any(e['record'] == 'run_failure' for e in events), 'incomplete/failed run')
    require(events[0]['run_id'] == events[-1]['run_id'] and sum(e['record'] == 'run_start' for e in events) ==
            sum(e['record'] == 'run_end' for e in events) == 1, 'run lifecycle correlation')
    require(events[0]['phase'] in {'calibration', 'no-retry', 'retry'} and events[0]['max_attempts'] ==
            (2 if events[0]['phase'] == 'retry' else 1), 'bounded paired retry policy')
    transport = events[0]['transport']
    require(transport == p7.operations.transport(transport['endpoint'], 'azure-aks', transport.get('dns_client_override')), 'verified HTTPS transport evidence')
    fingerprint = load(directory / 'configuration.json')
    identity(fingerprint['identity'])
    require(urllib.parse.urlsplit(transport['endpoint']).hostname == fingerprint['identity']['forgejo_hostname'] and
            fingerprint['configuration']['forgejo_hostname'] == fingerprint['identity']['forgejo_hostname'], 'recorded/frozen hostname differs')
    actual = fingerprint['configuration']
    config = plan(actual['scenario'])
    require(events[0]['fingerprint'] == digest(fingerprint), 'configuration fingerprint')
    start, end = p7.utc(events[0]['timestamp_utc']), p7.utc(events[-1]['timestamp_utc'])
    require((end - start).total_seconds() >= 90, 'HPA observation window')
    before, after, path = [load(directory / f) for f in ('before.json', 'after.json', 'path.json')]
    guards = [before['guard']] + [e['snapshot'] for e in events if e['record'] == 'guard'] + [after['guard']]
    hpa = guard_validation(guards, actual['hpa_spec'])
    attempts, ops = [[e for e in events if e['record'] == typ] for typ in ('attempt', 'operation')]
    require(len(ops) == config['waves'] * config['logical_operations'] and len({o['operation_id'] for o in ops}) == len(ops), 'logical demand/count differs')
    require(len({a['attempt_id'] for a in attempts}) == len(attempts), 'duplicate attempts')
    require(all(type(a['semantic_result']) is bool and a['error_class'] in {'none', 'http_status', 'semantic_error', 'timeout', 'transport'} and
                (a['status'] is None or type(a['status']) is int and 100 <= a['status'] <= 599) for a in attempts), 'attempt result schema')
    require(all(a['attempt_id'] == f"{a['operation_id']}-attempt-{a['attempt_index']}" and
                a['end_monotonic'] >= a['start_monotonic'] and math.isfinite(a['duration_seconds']) and
                abs(a['duration_seconds'] - (a['end_monotonic'] - a['start_monotonic'])) < .00001 for a in attempts), 'attempt ID/timing invalid')
    for op in ops:
        selected = [a for a in attempts if a['operation_id'] == op['operation_id']]
        require(1 <= len(selected) == op['attempt_count'] <= events[0]['max_attempts'] and
                [a['attempt_index'] for a in selected] == list(range(1, len(selected) + 1)) and
                all(not a['semantic_result'] for a in selected[:-1]) and selected[-1]['semantic_result'] == op['success'] and
                (len(selected) == events[0]['max_attempts'] or selected[-1]['semantic_result']), 'attempt correlation/policy')
    require({a['operation_id'] for a in attempts} == {o['operation_id'] for o in ops}, 'orphan attempt')
    failures = [a for a in attempts if not a['semantic_result']]
    require(failures and all(a['error_class'] == 'http_status' for a in failures), 'impact absent or transport/semantic confounder')
    sentinels = [e['result'] for e in events if e['record'] == 'sentinel']
    require(sentinels and all(s['semantic_result'] for s in sentinels) and any(s['start_monotonic'] <= a['end_monotonic'] and
            a['start_monotonic'] <= s['end_monotonic'] for s in sentinels for a in failures), 'direct authenticated sentinel failed/nonoverlapping')
    deltas, peak = [], 0
    for target in actual['targets']:
        uid = target['uid']
        b, a = before['stats'][uid], after['stats'][uid]
        require(sorted(a) == sorted(b) == target['mapping']['stat_names'], 'stat inventory drift')
        delta = p4.by_suffix({k: a[k] - v for k, v in b.items()})
        require(all(delta[k] >= 0 for k in p4.SUFFIXES) and p4.by_suffix(b)['upstream_rq_active'] == p4.by_suffix(a)['upstream_rq_active'] == 0, 'outstanding work/counter reset')
        require(delta['upstream_rq_active_overflow'] > 0 and delta['upstream_rq_pending_overflow'] == 0, 'active-request mechanism missing/competing pending overflow')
        peak = max(peak, max((p4.by_suffix(e['stats'][uid])['upstream_rq_active'] for e in events if e['record'] == 'target'), default=0))
        deltas.append(delta)
    require(peak > 0, 'active pressure not sampled')
    hp0, hp1 = before['haproxy'], after['haproxy']
    require(hp1['status'] in {'UP', 'no check'} and hp1['qcur'] == hp1['qmax'] == 0 and all(hp1[k] == hp0[k] for k in ('econ', 'eresp', 'wretr', 'wredis', 'cli_abrt', 'srv_abrt')), 'HAProxy competing queue/error/retry')
    dispatched = p4.backend_requests(hp1) - p4.backend_requests(hp0)
    rejected = [r for r in path['proxies']['target'] if int(r['status']) == 503 and 'overflow' in r['detail']]
    admitted = sum(d['upstream_rq_total'] for d in deltas)
    overflow = sum(d['upstream_rq_active_overflow'] for d in deltas)
    # A shared gateway also logs TLS connections that never select an HTTP/SNI
    # filter chain. Retain these records, but do not count them as scoped checks.
    non_http_ingress = [r for r in path['proxies']['ingress'] if int(r['status']) == 0 and
                       r['detail'] == 'filter_chain_not_found' and r['cluster'] in {None, '-'}]
    ingress_http = [r for r in path['proxies']['ingress'] if r not in non_http_ingress]
    require(dispatched == len(path['proxies']['target']) == len(ingress_http) == admitted + overflow and
            len(rejected) == overflow and admitted == len(path['checks']), 'dispatch/admission/rejection mapping mismatch')
    require(all(int(r['status']) == 200 or r['detail'] == 'ext_authz_error' for r in ingress_http), 'unmapped ingress rejection')
    if path['checks']:
        p4.gate.validate_checks(path['checks'])
    git = [e for e in events if e['record'] == 'git_read']
    require(len(git) == config['waves'], 'Git read observation absent')
    require(dispatched >= len(attempts), 'HTTP Issue attempt/check accounting')
    known = {a['attempt_id']: a['operation_id'] for a in attempts + git}
    require(all(c['decision'] == 'ALLOW' and known.get(c['attempt_id']) == c['operation_id'] for c in path['checks']), 'unattributed admitted check')
    slo = load(ROOT / 'docs/evidence/p7-operations-20261028/initial-slo.json')
    return {'validity': 'pending-cloud-confounder-review', 'hypothesis': 'pending', 'fingerprint': digest(fingerprint),
        'window_utc': {'start': before['timestamp_utc'], 'end': after['timestamp_utc']}, 'logical_operations': len(ops), 'attempts': len(attempts),
        'issue_failures': sum(not o['success'] for o in ops), 'issue_attempt_slo_latency_violations': sum(a['duration_seconds'] > slo['command_latency']['per_operation']['issue_read']['threshold_max_seconds'] for a in attempts),
        'issue_latency_boundary': 'same single curl command timing as P7; logical operation total includes bounded retry and is recorded separately',
        'https_git_reads': len(git), 'https_git_failures': sum(not g['semantic_result'] for g in git),
        'git_boundary': 'ls-remote main semantic read; not equivalent to P7 clone/fetch latency SLI',
        'dispatched_checks': dispatched, 'admitted_checks': admitted, 'active_rejections': overflow, 'active_peak': peak,
        'non_http_ingress_records_retained': len(non_http_ingress),
        'git_dispatched_checks_inferred_from_total_minus_single_request_issue_attempts': dispatched - len(attempts), 'hpa': hpa,
        'source_sha': fingerprint['source_sha'], 'configuration': 'configuration.json',
        'limitations': ['Git attempts may dispatch multiple checks; no 1:1 inference', 'server linkage: window/workload; app admitted check IDs only',
                        'PostgreSQL CPU/storage, Forgejo/sidecar CPU/throttling/latency and node scheduling/headroom require same-window review before valid/hypothesis claims']}


REVIEW_SIGNALS = {'forgejo_app_cpu_latency', 'forgejo_sidecar_cpu_pressure', 'postgres_cpu', 'postgres_connections',
                  'postgres_latency', 'postgres_storage_io', 'node_cpu_memory_scheduling', 'haproxy_queue_error_retry', 'direct_authenticated_sentinel'}


def reviewed_run(directory):
    directory = Path(directory)
    result = validate_run(directory)
    review = load(directory / 'confounder-review.json')
    require(review['source_sha'] == result['source_sha'] and review['fingerprint'] == result['fingerprint'] and
            review['window_utc'] == result['window_utc'] and review['competing_bottleneck'] is False and
            review['missing_required_signals'] == [] and set(review['signals']) == REVIEW_SIGNALS, 'confounder review incomplete')
    for signal, evidence in review['signals'].items():
        path = Path(evidence['file'])
        require(not path.is_absolute() and '..' not in path.parts and path.suffix in {'.json', '.jsonl'}, 'review evidence relative path')
        require(evidence['interpretation'] and evidence['status'] == 'observed' and evidence['samples'] > 0 and
                p7.utc(evidence['start_utc']) <= p7.utc(result['window_utc']['start']) and
                p7.utc(evidence['end_utc']) >= p7.utc(result['window_utc']['end']), 'required signal missing/window mismatch: ' + signal)
        require(hashlib.sha256((directory / path).read_bytes()).hexdigest() == evidence['sha256'], 'review evidence changed')
    result['validity'] = 'valid'
    result['hypothesis'] = 'active-request saturation and developer impact supported; retry comparison pending'
    result['confounder_review_sha256'] = hashlib.sha256((directory / 'confounder-review.json').read_bytes()).hexdigest()
    return result


def paired(first, second, frozen):
    one, two = reviewed_run(first), reviewed_run(second)
    e1, e2 = [p4.rows(Path(p) / 'events.jsonl')[0] for p in (first, second)]
    require(e1['phase'] == 'no-retry' and e2['phase'] == 'retry' and e1['max_attempts'] == 1 and e2['max_attempts'] == 2, 'paired order/policy')
    require(load(Path(first) / 'configuration.json') == load(Path(second) / 'configuration.json') == frozen and
            e1['transport'] == e2['transport'], 'paired config/source/replica/demand/transport changed')
    require(one['logical_operations'] == two['logical_operations'], 'paired logical demand differs')
    return {'source_sha': frozen['source_sha'], 'validity': 'valid', 'no_retry': one, 'retry': two,
            'retry_attempt_amplification': two['attempts'] / one['attempts'],
            'check_dispatch_ratio': two['dispatched_checks'] / one['dispatched_checks'],
            'hypothesis_retry': 'supported' if two['attempts'] > one['attempts'] else 'not supported',
            'cleanup': 'pending; paired evidence alone does not establish restoration'}


def cloud_plan(directory, query_identity):
    directory = Path(directory)
    fingerprint = load(directory / 'configuration.json')
    before, after = [load(directory / name) for name in ('before.json', 'after.json')]
    require(set(query_identity) == {'cluster_resource_id', 'prometheus_cluster', 'prometheus_endpoint', 'log_workspace_id'}, 'cloud query identity')
    require(query_identity['cluster_resource_id'] == fingerprint['identity']['cluster_resource_id'], 'cloud target differs')
    require(re.fullmatch('[a-zA-Z0-9_-]+', query_identity['prometheus_cluster']) and
            re.fullmatch('[0-9a-f-]{36}', query_identity['log_workspace_id']), 'cloud label/workspace identity')
    cluster = 'cluster=' + json.dumps(query_identity['prometheus_cluster'])
    selector = 'job="forgejo",namespace="forgejo",' + cluster
    # Actual metric availability is evidence; no absent series -> zero coercion.
    expressions = {'forgejo_scrape': 'up{' + selector + '}',
                   'forgejo_cpu': 'rate(process_cpu_seconds_total{' + selector + '}[1m])',
                   'forgejo_memory': 'process_resident_memory_bytes{' + selector + '}'}
    start, end = before['timestamp_utc'], after['timestamp_utc']
    logs = f'''ContainerLogV2
| where TimeGenerated between (datetime({start}) .. datetime({end}))
| where _ResourceId =~ '{query_identity['cluster_resource_id']}'
| where PodNamespace in ('forgejo', '{NS}', 'aks-istio-ingress')
| summarize entries=count(), first_seen=min(TimeGenerated), last_seen=max(TimeGenerated) by PodNamespace, PodName, ContainerName, LogSource'''
    return {'schema_version': 1, 'source_sha': fingerprint['source_sha'], 'fingerprint': digest(fingerprint),
            'identity': query_identity, 'service_active_window_utc': {'start': start, 'end': end},
            'promql': expressions, 'kql': logs, 'step_seconds': 15}


def postgres_metrics(directory, output):
    """Existing ARM metrics only. Non-overlapping/empty samples remain missing."""
    directory = Path(directory)
    value = load(directory / 'configuration.json')['identity']
    window = [load(directory / name)['timestamp_utc'] for name in ('before.json', 'after.json')]
    names = ['cpu_percent', 'active_connections', 'storage_percent', 'storage_used', 'storage_free', 'iops', 'read_iops', 'write_iops',
             'disk_iops_consumed_percentage', 'disk_queue_depth']
    payload = json.loads(p7.command(['az', 'monitor', 'metrics', 'list', '--resource', value['pg_resource_id'],
        '--metric', *names, '--start-time', window[0], '--end-time', window[1], '--interval', 'PT1M',
        '--aggregation', 'Average', 'Maximum', '-o', 'json']))
    metrics = []
    for item in payload['value']:
        points = [point for series in item.get('timeseries', []) for point in series.get('data', [])]
        observed = [p for p in points if any(k in p and p[k] is not None for k in ('average', 'maximum'))]
        metrics.append({'name': item['name']['value'], 'unit': item['unit'], 'status': 'observed' if observed else 'no-data', 'points': points})
    save(output, {'source_sha': value['source_sha'], 'resource_id': value['pg_resource_id'], 'window_utc': {'start': window[0], 'end': window[1]},
                  'metrics': metrics, 'interpretation': 'ARM minute bins; assess overlap/aggregation with SQL command latency and direct sentinel, not request-level DB tracing'})


def main():
    args = sys.argv[1:]
    if len(args) == 3 and args[0] == 'render':
        output = Path(args[2]); output.mkdir(mode=0o700)
        for name, obj in render(load(args[1])).items():
            save(output / name, obj)
    elif len(args) == 4 and args[0] == 'mesh':
        save(args[3], mesh_overlay(load(args[2]), load(args[1])))
    elif len(args) in {5, 6} and args[0] == 'measure':
        phase = args[3]
        frozen = load(args[5]) if len(args) == 6 else None
        measure(load(args[1]), load(args[2]), args[4], phase, 2 if phase == 'retry' else 1, frozen)
    elif len(args) == 3 and args[0] == 'validate':
        save(args[2], validate_run(args[1]))
    elif len(args) == 3 and args[0] == 'review':
        save(args[2], reviewed_run(args[1]))
    elif len(args) == 5 and args[0] == 'pair':
        save(args[4], paired(args[1], args[2], load(args[3])))
    elif len(args) == 4 and args[0] == 'queries':
        save(args[3], cloud_plan(args[1], load(args[2])))
    elif len(args) == 3 and args[0] == 'postgres-metrics':
        postgres_metrics(args[1], args[2])
    elif len(args) == 3 and args[0] == 'freeze':
        require(p4.rows(Path(args[1]) / 'events.jsonl')[0]['phase'] == 'calibration', 'freeze requires calibration phase')
        result = reviewed_run(args[1])
        require(result['issue_failures'] > 0 and result['active_rejections'] > 0, 'calibration failed')
        save(args[2], load(Path(args[1]) / 'configuration.json'))
    else:
        raise ValueError('usage: render IDENTITY DIR | mesh IDENTITY ORIGINAL_CM OUTPUT | measure IDENTITY SCENARIO calibration|no-retry|retry DIR [FROZEN] | validate|review RUN OUTPUT | freeze CALIBRATION OUTPUT | pair NO_RETRY RETRY FROZEN OUTPUT')


if __name__ == '__main__':
    try:
        os.umask(0o077)
        main()
    except Exception:
        print('Azure cascade failed; preserve negative evidence and inspect protected operator inputs', file=sys.stderr)
        sys.exit(1)
