#!/usr/bin/env python3
"""P10 Azure source gates: read-only preflight, exact binding/approval/ledger and the owned paired campaign.

`preflight` uses only Kubernetes get / auth can-i / Envoy admin GET, `az aks show`, `az acr repository show`, one
AMW query pair and an anonymous HTTPS health read, behind a separate read-only acknowledgement. It never mutates
and never grants or requests a role. `campaign` mutates only after the explicit P10 approval manifest and env bind
this exact source, manifest, frozen plan and a fresh append-only ledger; every exit runs the owned rollback.

The offline contracts are exercised by tests/e2e/test-azure-isolation.py with mocked live data. That is not
runtime, admission, ingress, managed-telemetry or isolation evidence.
"""
from datetime import datetime, timedelta, timezone
import http.client
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


pair = module('p10_azure_pair', 'local-isolation-pair.py')
p9 = module('p10_azure_p9', 'azure-mitigation.py')
m = pair.m
p8 = m.p8
gate = p8.p4.gate
require, digest = m.require, m.digest
NS = p8.NS
INGRESS_NS, MESH_NS = 'aks-istio-ingress', 'aks-istio-system'
CANDIDATE = ROOT / 'experiments/fixtures/critical-bulk/candidate.json'
DEADLINE = p9.DEADLINE   # Environment retention; never extended by source.
HAPROXY_CLUSTER = 'outbound|8080||haproxy.' + NS + '.svc.cluster.local'
FORGEJO_CLUSTER = 'outbound|3000||forgejo-http.forgejo.svc.cluster.local'
ADMIN_PORTS, DIRECT = (19101, 19102), 13000
# One approval: healthy per arm, calibration pair at most once, measured pair once, at most four fault runs.
LIMITS = {'healthy': 2, 'calibration_pair': 1, 'measured_pair': 1, 'fault_runs': 4, 'pods': 4, 'cpu_m': 1500, 'memory_mi': 2048}
SETUP_SECONDS, HEALTHY_SECONDS, PREPARATION_SECONDS, CLEANUP_SECONDS = 300, 120, 1200, 1800
APPROVAL_FIELDS = {'approved', 'approval_url', 'source_sha', 'manifest_sha256', 'frozen_plan_sha256', 'limits'}
APPROVAL_URL = r'https://github\.com/imcherry5778-labs/github-capacity-cascade-platform/(?:issues|pull)/[1-9][0-9]*#(?:issuecomment|pullrequestreview)-[1-9][0-9]*'
DB_ENV_KEYS = {'PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD', 'PGSSLMODE'}
GUARD_SECONDS, SENTINEL_SECONDS = 2.0, 1.0
GUARD_POLICY = {'guards': sorted(m.GUARDS), 'sentinel_seconds': SENTINEL_SECONDS, 'guard_seconds': GUARD_SECONDS, 'environment': 'azure'}
# Reads the preflight needs, and the extra verbs the campaign's kubectl commands need (client-side `apply` = get +
# create/patch; `rollout restart` = patch; `rollout status` and `--wait` = get/list/watch; exec/logs/port-forward read the
# Pod first). A missing verb is an exact blocker; this source never grants, requests or escalates a role.
# tests/e2e/test-azure-isolation.py derives the verbs from the recorded commands and requires them to be covered here.
READ_ACCESS = (('list', 'nodes', None), ('list', 'pods', None), ('get', 'namespaces', None),
               ('get', 'configmaps', MESH_NS), ('get', 'authorizationpolicies.security.istio.io', INGRESS_NS),
               ('get', 'pods', INGRESS_NS), ('create', 'pods/exec', INGRESS_NS), ('get', 'customresourcedefinitions.apiextensions.k8s.io', None),
               ('get', 'applications.argoproj.io', 'argocd'), ('get', 'deployments.apps', 'forgejo'))
CAMPAIGN_ACCESS = (('create', 'namespaces', None), ('delete', 'namespaces', None), ('list', 'namespaces', None), ('watch', 'namespaces', None),
                   ('patch', 'configmaps', MESH_NS),
                   ('create', 'authorizationpolicies.security.istio.io', INGRESS_NS),
                   ('delete', 'authorizationpolicies.security.istio.io', INGRESS_NS),
                   ('get', 'pods/log', INGRESS_NS), ('get', 'pods', 'forgejo'), ('create', 'pods/portforward', 'forgejo'),
                   ('get', 'resourcequotas', NS), ('create', 'resourcequotas', NS),
                   ('get', 'secrets', NS), ('create', 'secrets', NS),
                   ('get', 'configmaps', NS), ('create', 'configmaps', NS), ('patch', 'configmaps', NS),
                   ('get', 'deployments.apps', NS), ('list', 'deployments.apps', NS), ('watch', 'deployments.apps', NS),
                   ('create', 'deployments.apps', NS), ('patch', 'deployments.apps', NS), ('delete', 'deployments.apps', NS),
                   ('get', 'services', NS), ('list', 'services', NS), ('watch', 'services', NS),
                   ('create', 'services', NS), ('delete', 'services', NS),
                   ('get', 'pods', NS), ('create', 'pods', NS),
                   ('get', 'sidecars.networking.istio.io', NS), ('create', 'sidecars.networking.istio.io', NS),
                   ('get', 'podmonitors.azmonitoring.coreos.com', NS), ('create', 'podmonitors.azmonitoring.coreos.com', NS),
                   ('create', 'pods/exec', NS), ('create', 'pods/portforward', NS), ('get', 'pods/log', NS),
                   ('list', 'endpointslices.discovery.k8s.io', NS))


# --- exact manifest / approval / ledger ----------------------------------------------------------------

def manifest(value):
    """Exact P10 Azure binding input: P8 identity, the unchanged source candidate plan, fixture and AMW identity."""
    require(type(value) is dict and set(value) == {'identity', 'plan', 'fixture', 'prometheus'}, 'P10 Azure manifest fields')
    p8.identity(value['identity']); m.fixture(value['fixture'])
    require(value['plan'] == m.plan(m.load(CANDIDATE)), 'plan differs from the source candidate')
    p = value['prometheus']
    require(type(p) is dict and set(p) == {'endpoint', 'cluster'} and
            re.fullmatch(r'https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.prometheus\.monitor\.azure\.com', p['endpoint']) and
            re.fullmatch(r'[a-zA-Z0-9_-]{1,63}', p['cluster']), 'AMW query identity')
    return value


def run_seconds(v):
    """Demand + drain + managed telemetry tail (scrape + ingestion) for one fault run."""
    return v['duration_seconds'] + v['drain_seconds'] + v['scrape_seconds'] + v['ingestion_seconds']


def total_seconds(v):
    return LIMITS['fault_runs'] * run_seconds(v) + PREPARATION_SECONDS + CLEANUP_SECONDS


def approval_gate(value, approval, ledger_exists, now=None):
    """Whole-campaign entry: exact approval, frozen thresholds, fresh ledger and the full time reserve."""
    manifest(value)
    now = now or datetime.now(timezone.utc)
    sha = value['identity']['source_sha']
    require(os.environ.get('P10_AZURE_APPROVED') == sha and type(approval) is dict and set(approval) == APPROVAL_FIELDS and
            approval['approved'] is True and approval['source_sha'] == sha and approval['manifest_sha256'] == digest(value) and
            type(approval['approval_url']) is str and re.fullmatch(APPROVAL_URL, approval['approval_url']), 'explicit exact P10 approval required')
    require(approval['limits'] == LIMITS, 'approval scope differs')
    # The candidate numbers are not conclusion thresholds until a cost-free calibration froze this exact plan.
    require(approval['frozen_plan_sha256'] == digest(value['plan']), 'numeric thresholds not frozen for this exact plan')
    # One approval is one campaign. A started campaign is never resumed or reused, whatever its outcome.
    require(not ledger_exists, 'campaign ledger already exists; a new campaign needs a new approval')
    require(now + timedelta(seconds=total_seconds(value['plan'])) < DEADLINE, 'insufficient retention time for the bounded campaign')


def step_gate(value, rows, step, arm, now=None):
    """Per-action count and time reserve. A started action is consumed whatever its outcome (append-only)."""
    require(step in {'setup', 'healthy', 'calibration', 'measured'} and arm in m.ARMS, 'unknown campaign step')
    now = now or datetime.now(timezone.utc)
    sha, manifest_sha = value['identity']['source_sha'], digest(value)
    require(all(r['source_sha'] == sha and r['manifest_sha256'] == manifest_sha for r in rows), 'ledger source/manifest drift')
    after = rows + [{'step': step, 'arm': arm}]
    count = lambda s, a=None: sum(r['step'] == s and (a is None or r['arm'] == a) for r in after)
    require(all(count('healthy', a) <= 1 for a in m.ARMS) and count('healthy') <= LIMITS['healthy'], 'healthy budget exceeded')
    require(all(count(s, a) <= LIMITS[s + '_pair'] for s in ('calibration', 'measured') for a in m.ARMS) and
            count('calibration') + count('measured') <= LIMITS['fault_runs'], 'fault-run budget exceeded')
    require(step in {'setup', 'healthy'} or count('healthy', arm) == 1, 'fault run before this arm passed healthy')
    seconds = {'setup': SETUP_SECONDS, 'healthy': HEALTHY_SECONDS}.get(step) or run_seconds(value['plan'])
    require(now + timedelta(seconds=seconds + CLEANUP_SECONDS) < DEADLINE, 'insufficient retention time for step plus owned rollback')


class Ledger:
    """Append-only campaign ledger, created exclusively before the first mutation."""
    def __init__(self, path, value):
        self.path, self.value = Path(path), value
        with open(self.path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)):
            pass

    def rows(self):
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]

    def start(self, step, arm, now=None):
        step_gate(self.value, self.rows(), step, arm, now)
        with self.path.open('a') as stream:
            stream.write(json.dumps({'step': step, 'arm': arm, 'source_sha': self.value['identity']['source_sha'],
                                     'manifest_sha256': digest(self.value), 'timestamp_utc': p8.utc()}) + '\n')


# --- actual target / admission / ingress contracts (pure) ----------------------------------------------

def azure_target(pod, v, service, slices, clusters, listeners, stats, bootstrap, hold):
    """Actual Pod UID -> sidecar container ID -> effective inbound capacity -> Service/EndpointSlice -> pool.

    Admin config_dump (snake_case) of the managed sidecar; the selected P9 inbound mapping and `cluster_name` stat
    tag. Inbound stats may not exist before the first request, so only their structural names are bound here.
    """
    mapping, _ = p8.target_mapping(clusters, stats, v['max_requests'], listeners, allow_uninitialized=True)
    metric = p9.metric_mapping(mapping, bootstrap)
    labels = pod['metadata'].get('labels', {})
    pool = labels.get('p10.pool')
    statuses = {c['name']: c for c in pod['status'].get('initContainerStatuses', []) + pod['status'].get('containerStatuses', [])}
    containers = {c['name']: c for c in gate.active_containers(pod)}
    require(pool in {'shared', 'critical', 'bulk'} and labels.get('app') == 'ext-authz-sim' and
            not pod['metadata'].get('deletionTimestamp'), 'target pool label')
    require({'app', 'istio-proxy'} <= set(statuses) & set(containers) and statuses['istio-proxy'].get('containerID') and
            statuses['app'].get('imageID') and statuses['istio-proxy'].get('ready') is True, 'target sidecar/app runtime identity absent')
    require(service['metadata']['name'] == 'ext-authz-' + pool and service['spec'].get('selector') == {'app': 'ext-authz-sim', 'p10.pool': pool} and
            all(s['metadata'].get('labels', {}).get('kubernetes.io/service-name') == service['metadata']['name'] for s in slices) and
            all(any(p.get('port') == 8080 for p in s.get('ports') or []) for s in slices), 'Service/EndpointSlice/pool mismatch')
    require(hold == v['hold_ms'], 'effective hold differs')
    endpoints = sorted({e['targetRef']['uid'] for s in slices for e in s.get('endpoints', [])
                        if e.get('conditions', {}).get('ready') and e.get('targetRef', {}).get('kind') == 'Pod'})
    uid = pod['metadata']['uid']
    return {'uid': uid, 'name': pod['metadata']['name'], 'pool': pool, 'sidecar_id': statuses['istio-proxy']['containerID'],
            'image_id': statuses['app']['imageID'], 'capacity': mapping['capacity'], 'hold_ms': hold,
            'mapping_sha256': digest({'mapping': {k: mapping[k] for k in ('cluster_name', 'alt_stat_name', 'capacity', 'endpoint_mapping')},
                                      'metric': metric}),
            'resources_sha256': digest({n: containers[n].get('resources') for n in ('app', 'istio-proxy')}),
            'service': service['metadata']['name'], 'service_uid': service['metadata']['uid'],
            'endpoint_pod_uid': uid if uid in endpoints else None, 'endpoints': endpoints,
            'prefixes': ['cluster.' + n + '.' for n in (mapping['cluster_name'], mapping['alt_stat_name']) if n]}


def pool_targets(arm, targets):
    """Exactly the arm's two actual targets; each Service selects exactly its pool's Pods."""
    expected = {'shared': 2} if arm == 'shared' else {'critical': 1, 'bulk': 1}
    require(len(targets) == 2 and len({t['uid'] for t in targets}) == 2 and len({t['sidecar_id'] for t in targets}) == 2 and
            {p: sum(t['pool'] == p for t in targets) for p in expected} == expected, 'actual pool topology')
    for t in targets:
        require(t['endpoint_pod_uid'] == t['uid'] and t['endpoints'] == sorted(x['uid'] for x in targets if x['pool'] == t['pool']),
                'Service endpoint set differs from pool Pods')
    require(len({(t['image_id'], t['resources_sha256'], t['capacity'], t['hold_ms'], t['mapping_sha256']) for t in targets}) == 1,
            'pool targets differ in image/resources/capacity/mapping')
    return targets


def pool_admission(identity, arm, pods):
    """Actual admitted Pods incl. injected/native sidecars, init containers and overhead (P8 conservative sum)."""
    admitted = p8.admission(identity, pods)
    labels = [p['metadata'].get('labels', {}) for p in pods]
    pools = sorted(l.get('p10.pool') for l in labels if l.get('app') == 'ext-authz-sim')
    expected = ['shared', 'shared'] if arm == 'shared' else ['bulk', 'critical']
    require(len(pods) == LIMITS['pods'] and pools == expected and sum(l.get('app') == 'haproxy' for l in labels) == 1 and
            sum(p['metadata']['name'] == 'p8-db-client' for p in pods) == 1, 'admitted P10 Pod composition differs')
    # p8.admission also bounds the conservative sum by the approved 1500m / 2048Mi.
    return admitted


def demand(identity, v, f):
    """Source estimate of the steady P10 Pods (sidecar from injection annotations). Init/native-sidecar/overhead is
    only known after actual admission; this estimate is never admission evidence."""
    pods = []
    for o in m.render(identity, v, f, 'isolated')['fixtures.json']['items']:
        if o['kind'] not in {'Deployment', 'Pod'}:
            continue
        template = o['spec']['template'] if o['kind'] == 'Deployment' else o
        annotations = template['metadata'].get('annotations', {})
        cpu = sum(p8.quantity(c['resources']['requests']['cpu']) for c in template['spec']['containers'])
        memory = sum(p8.quantity(c['resources']['requests']['memory']) for c in template['spec']['containers'])
        if annotations.get('sidecar.istio.io/inject') == 'true':
            cpu += p8.quantity(annotations['sidecar.istio.io/proxyCPU']); memory += p8.quantity(annotations['sidecar.istio.io/proxyMemory'])
        for i in range(o['spec'].get('replicas', 1) if o['kind'] == 'Deployment' else 1):
            pods.append({'name': o['metadata']['name'] + ('-' + str(i) if o['kind'] == 'Deployment' else ''), 'cpu': cpu, 'memory': memory})
    return pods


def headroom(nodes, pods, needed):
    """First-fit-decreasing of the estimated P10 requests onto current schedulable node free requests."""
    free = []
    for node in nodes:
        name = node['metadata']['name']
        used = {'cpu': 0.0, 'memory': 0.0}
        for pod in pods:
            if pod['spec'].get('nodeName') != name or pod['status'].get('phase') in {'Succeeded', 'Failed'}:
                continue
            containers = pod['spec']['containers'] + pod['spec'].get('initContainers', [])
            for key in used:
                used[key] += sum(p8.quantity(c.get('resources', {}).get('requests', {}).get(key, '0')) for c in containers)
                used[key] += p8.quantity(pod['spec'].get('overhead', {}).get(key, '0'))
        schedulable = not node['spec'].get('unschedulable') and not any(t['effect'] in {'NoSchedule', 'NoExecute'} for t in node['spec'].get('taints', [])) and \
            any(c['type'] == 'Ready' and c['status'] == 'True' for c in node['status']['conditions'])
        free.append({'name': name, 'schedulable': schedulable,
                     'cpu_free': p8.quantity(node['status']['allocatable']['cpu']) - used['cpu'],
                     'memory_free': p8.quantity(node['status']['allocatable']['memory']) - used['memory']})
    remaining = {n['name']: dict(n) for n in free if n['schedulable']}
    placed = True
    for pod in sorted(needed, key=lambda p: (-p['cpu'], -p['memory'])):
        node = next((n for n in remaining.values() if n['cpu_free'] >= pod['cpu'] and n['memory_free'] >= pod['memory']), None)
        if node is None:
            placed = False
            break
        node['cpu_free'] -= pod['cpu']; node['memory_free'] -= pod['memory']
    return {'fits': placed, 'nodes': free, 'demand': needed,
            'note': 'requests estimate only; init/native sidecar/Pod overhead and rolling transition need actual admission'}


def server_name_matches(names, hostname):
    return any(n == hostname or n.startswith('*.') and hostname.endswith(n[1:]) and hostname.count('.') == n.count('.') for n in names)


def ingress_contract(listeners, routes, hostname, provider=False):
    """Effective managed-ingress HTTPS chain for the Forgejo hostname.

    Istio BASE normalization (the default; mesh normalization is never changed) is `normalize_path` with no slash
    merge and escaped slashes kept, so `//` and `%2f` reach the exact HAProxy classifier unchanged and are denied.
    The Forgejo route has no rewrite or retries, so the classified and the native path are the same request.
    Before the campaign no ext_authz filter may exist on the chain; inside it P8 `gateway_scope` checks the provider.
    """
    chains = [c for c in m.p8.walk(listeners) if isinstance(c.get('filters'), list) and
              server_name_matches(c.get('filter_chain_match', {}).get('server_names', []), hostname)]
    require(chains, 'HTTPS filter chain for the Forgejo hostname absent')
    normalization = []
    for chain in chains:
        require(chain.get('transport_socket', {}).get('name') == 'envoy.transport_sockets.tls' and
                'DownstreamTlsContext' in chain['transport_socket'].get('typed_config', {}).get('@type', ''), 'Forgejo chain is not TLS')
        hcms = [f['typed_config'] for f in chain['filters'] if f.get('name') == 'envoy.filters.network.http_connection_manager']
        require(len(hcms) == 1, 'HTTP connection manager absent/ambiguous')
        hcm = hcms[0]
        state = {'normalize_path': hcm.get('normalize_path'), 'merge_slashes': hcm.get('merge_slashes', False),
                 'escaped_slashes': hcm.get('path_with_escaped_slashes_action', 'KEEP_UNCHANGED')}
        require(state['normalize_path'] is True and state['merge_slashes'] is False and
                state['escaped_slashes'] in {'KEEP_UNCHANGED', 'IMPLEMENTATION_SPECIFIC_DEFAULT'}, 'ingress path normalization differs from BASE')
        filters = [f for f in hcm.get('http_filters', []) if f.get('name') == 'envoy.filters.http.ext_authz']
        require(bool(filters) == provider, 'unexpected/absent ext_authz filter on the Forgejo chain')
        for f in filters:
            config = f['typed_config']
            require(HAPROXY_CLUSTER == config['http_service']['server_uri']['cluster'] and not config['http_service'].get('path_prefix') and
                    config.get('failure_mode_allow', False) is False and 'with_request_body' not in config, 'effective HTTP check path/body/fail-closed drift')
        normalization.append(state)
    selected = [r for r in m.p8.walk(routes) if isinstance(r.get('route'), dict) and r['route'].get('cluster') == FORGEJO_CLUSTER]
    require(selected and all(r['route'].get('retry_policy', {}).get('num_retries', 0) == 0 and
                             not {'prefix_rewrite', 'regex_rewrite', 'path_rewrite_policy', 'host_rewrite_literal'} & set(r['route'])
                             for r in selected), 'Forgejo route retries/rewrite')
    return {'hostname': hostname, 'chains': len(chains), 'normalization': normalization,
            'routes_sha256': digest(selected), 'contract': 'istio-BASE: normalize_path, no merge_slashes, escaped slashes kept'}


def mesh_contract(original, identity):
    """The revision shared ConfigMap the P8 provider overlay patches; normalization stays the default BASE."""
    p8.mesh_overlay(original, identity)   # owner/name/provider-absence guards
    mesh = json.loads(original['data']['mesh'])
    require(mesh.get('pathNormalization', {}).get('normalization', 'BASE') in {'BASE', 'DEFAULT'}, 'mesh path normalization is not the default BASE')
    return {'uid': original['metadata']['uid'], 'data_sha256': digest(original['data'])}


# --- managed (AMW) and runtime evidence projection (pure) ----------------------------------------------

def proxy_rows(text):
    """Selected Azure Telemetry access-log rows (status/detail/duration/cluster only; no URL/credential)."""
    rows = []
    for line in text.splitlines():
        if not line.startswith('{'):
            continue
        row = json.loads(line)
        if {'status', 'detail', 'duration_ms', 'cluster'} <= set(row):
            rows.append({'status': int(row['status']), 'details': row['detail'], 'cluster': row['cluster']})
    return rows


def non_http(row):
    # A shared gateway logs TLS connections that never select an HTTP filter chain (P8): retained, never a check.
    return row['status'] == 0 and row['details'] == 'filter_chain_not_found' and row['cluster'] in {None, '-'}


def stream_delta(before, after):
    """Per-Pod log stream window; a rotated/rewritten prefix is lost evidence, never a silent slice."""
    require(set(before) == set(after), 'log Pod inventory changed')
    for key in before:
        require(after[key][:len(before[key])] == before[key], 'log prefix changed/rotated')
    return {key: after[key][len(before[key]):] for key in before}


def azure_observation(targets, before, after, logs_before, logs_after, client_requests):
    ingress = [r for rows in stream_delta(logs_before['ingress'], logs_after['ingress']).values() for r in rows]
    targets_delta = stream_delta(logs_before['target'], logs_after['target'])
    app_delta = stream_delta(logs_before['app'], logs_after['app'])
    empty = {'ingress': [], 'target': {u: [] for u in targets_delta}, 'app': {u: [] for u in app_delta}}
    window = {'ingress': [{'status': r['status'], 'details': r['details']} for r in ingress if not non_http(r)],
              'target': {u: [{'status': r['status'], 'details': r['details']} for r in rows] for u, rows in targets_delta.items()},
              'app': app_delta}
    obs = pair.observation(targets, before, after, empty, window, client_requests)
    return obs, sum(non_http(r) for r in ingress)


def managed_rows(value, polls, pods, clock):
    """AMW raw samples projected onto the harness's actual Pod UID/pool inventory (labels are never identity)."""
    return m.project_managed(polls, pods, clock, namespace=NS, prometheus_cluster=value['prometheus']['cluster'],
                             scrape_seconds=value['plan']['scrape_seconds'])


def restoration_verdict(state):
    keys = ('policy_removed', 'mesh_restored', 'namespace_removed', 'ingress_provider_absent', 'stable_unchanged',
            'argo_stable', 'https_healthy')
    return {'restored': not state.get('problems') and all(state.get(k) is True for k in keys), **state}


def _dict(value, keys):
    return type(value) is dict and keys <= set(value)


def _list(value, nonempty=True):
    return type(value) is list and (bool(value) or not nonempty)


def _vector(value, kind):
    return _dict(value, {'status', 'data'}) and value['status'] == 'success' and _dict(value['data'], {'resultType', 'result'}) and \
        value['data']['resultType'] == kind and _list(value['data']['result'], nonempty=False)


# A section reaches the readiness evaluation only when it is a complete observation. Empty/partial structures are
# never "nothing wrong": the P10 pre-campaign AMW series may be empty and leftovers must be explicit False, nothing else.
SECTION_SHAPES = {
    'source': lambda o: _dict(o, {'head', 'clean'}),
    'access': lambda o: _dict(o, {'read', 'campaign'}) and type(o['read']) is dict and type(o['campaign']) is dict,
    'cluster': lambda o: _dict(o, {'id', 'agentPoolProfiles', 'serviceMeshProfile'}) and _list(o['agentPoolProfiles']),
    'capacity': lambda o: _dict(o, {'nodes', 'pods'}) and _list(o['nodes']) and _list(o['pods']),
    'mesh': lambda o: _dict(o, {'metadata', 'data'}) and _dict(o['data'], {'mesh'}),
    'ingress': lambda o: _list(o) and all(_dict(i, {'uid', 'listeners', 'routes'}) for i in o),
    'leftovers': lambda o: type(o) is dict and set(o) == {'namespace', 'policy'} and all(type(x) is bool for x in o.values()),
    'argo': lambda o: _dict(o, {'spec', 'status'}),
    'prometheus': lambda o: _dict(o, {'up', 'p10'}) and _vector(o['up'], 'vector') and _vector(o['p10'], 'matrix'),
}


def preflight_verdict(value, obs, price, now):
    """Fail-closed readiness of the *approval request*, never an approval.

    Missing, empty, partial or malformed observations are blockers; nothing reaches readiness by being skipped.
    """
    manifest(value)
    identity, v = value['identity'], value['plan']
    blockers, facts = [], {}
    def need(code, condition):
        if not condition:
            blockers.append(code)
        return condition
    def section(name, evaluate):
        observed = obs.get(name)
        if observed is None:
            return need('unobserved:' + name, False)
        if not SECTION_SHAPES[name](observed):
            return need('malformed:' + name, False)
        try:
            evaluate(observed)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            need('malformed:' + name, False)
    def access(a):
        missing = [list(k) for k in READ_ACCESS if a['read'].get('|'.join(map(str, k))) is not True]
        need('kubernetes-read-rbac', not missing)
        facts['read_access_missing'] = missing
        facts['campaign_access_missing'] = [list(k) for k in CAMPAIGN_ACCESS if a['campaign'].get('|'.join(map(str, k))) is not True]
        need('campaign-rbac-decision', not facts['campaign_access_missing'])
    def cluster(c):
        pools = c['agentPoolProfiles']
        need('cluster-identity', c.get('cluster_uid') == identity['cluster_uid'] and c['id'].lower() == identity['cluster_resource_id'].lower())
        need('mesh-revision', c['serviceMeshProfile']['istio']['revisions'] == [identity['revision']])
        need('fixed-nodes', sum(p['count'] for p in pools) == 2 and not any(p.get('enableAutoScaling') for p in pools))
        facts['cluster'] = {'kubernetes_version': c.get('currentKubernetesVersion'), 'nodes': sum(p['count'] for p in pools),
                            'vm_sizes': sorted({p['vmSize'] for p in pools}), 'revision': identity['revision']}
    def capacity(c):
        result = headroom(c['nodes'], c['pods'], demand(identity, v, value['fixture']))
        need('node-headroom', result['fits'])
        facts['headroom'] = result
    def mesh(original):
        try:
            facts['mesh'] = mesh_contract(original, identity)
        except ValueError:
            need('mesh-shared-configmap', False)
    def ingress(pods):
        try:
            facts['ingress'] = [ingress_contract(i['listeners'], i['routes'], identity['forgejo_hostname']) for i in pods]
        except ValueError:
            need('ingress-https-normalization-contract', False)
    def argo(app):
        need('stable-argo', app['spec']['sources'][1]['targetRevision'] == app['spec']['sources'][2]['targetRevision'] == identity['stable_revision'] and
             app['status']['sync']['status'] == 'Synced' and app['status']['health']['status'] == 'Healthy')
    def amw(p):
        need('amw-stable-scrape', any(r['metric'].get('job') == 'forgejo' and r['value'][1] == '1' for r in p['up']['data']['result']))
        need('amw-p10-series-present-before-campaign', p['p10']['data']['result'] == [])
    section('source', lambda s: need('source-not-exact-clean-head', s == {'head': identity['source_sha'], 'clean': True}))
    section('access', access)
    section('cluster', cluster)
    section('capacity', capacity)
    section('mesh', mesh)
    section('ingress', ingress)
    section('leftovers', lambda left: need('p10-leftover-objects', not any(left.values())))
    need('podmonitor-crd', obs.get('crd') is True)
    section('argo', argo)
    need('ext-authz-image-absent-or-unreadable', obs.get('image') is True)
    section('prometheus', amw)
    need('https-healthz-tls', obs.get('https') == {'status': 200, 'error_class': 'none', 'semantic_result': True})
    need('retention-reserve', now + timedelta(seconds=total_seconds(v)) < DEADLINE)
    require(type(price) is dict and set(price) == {'node_hour_usd', 'amw_per_10m_samples_usd', 'retrieved_utc'} and
            all(type(price[k]) in {int, float} and math.isfinite(price[k]) and price[k] > 0 for k in ('node_hour_usd', 'amw_per_10m_samples_usd')), 'price input')
    # Freshness is recorded for the approver, not capped here; a future or non-UTC retrieval time is not a price observation.
    retrieved = p8.p7.utc(price['retrieved_utc'])
    require(retrieved <= now, 'price retrieved in the future')
    hours = total_seconds(v) / 3600
    samples = 2 * (len(m.STATS) + 5) * math.ceil(total_seconds(v) / v['scrape_seconds'])   # 5 stats + 5 scrape series per target
    facts['cost'] = {'existing_shared_node_hold_usd': round(2 * hours * price['node_hour_usd'], 4),
                     'p10_amw_increment_usd': round(samples / 1e7 * price['amw_per_10m_samples_usd'], 6), 'hold_seconds': total_seconds(v),
                     'price': price, 'price_age_hours': round((now - retrieved).total_seconds() / 3600, 2), 'budget_and_headroom': 'UNKNOWN', 'note': 'retail list price; actual billed cost and remaining budget UNKNOWN'}
    return {'status': 'blocked' if blockers else 'ready-for-approval-request', 'blockers': blockers, 'facts': facts,
            'source_sha': identity['source_sha'], 'manifest_sha256': digest(value),
            'decisions_required': ['explicit P10 action/count/cost/time approval', 'campaign Kubernetes role (never self-granted)',
                                   'budget (UNKNOWN)', 'frozen numeric thresholds'],
            'evaluated_utc': now.isoformat()}


# --- live: read-only preflight -------------------------------------------------------------------------

def protected_kubeconfig():
    require(os.environ.get('KUBECONFIG') and Path(os.environ['KUBECONFIG']).is_file() and
            Path(os.environ['KUBECONFIG']).stat().st_mode & 0o077 == 0, 'dedicated protected kubeconfig required')


def readonly_args(args):
    """Only get / auth can-i / Envoy admin GET. Anything else is refused before a process starts."""
    rest = list(args[2:]) if args[:1] == ('-n',) else list(args)
    require(rest and (rest[0] == 'get' or rest[:2] == ['auth', 'can-i'] or
                      rest[0] == 'exec' and rest[2:7] == ['-c', 'istio-proxy', '--', 'pilot-agent', 'request'] and rest[7:8] == ['GET'] and len(rest) == 9),
            'read-only kubectl only')
    return args


class Preflight:
    def __init__(self, value):
        self.value = manifest(value)
        sha = value['identity']['source_sha']
        require(os.environ.get('P10_AZURE_READONLY') == sha, 'explicit read-only preflight acknowledgement required')
        protected_kubeconfig()
        p8.measurement_transport(value['identity'])

    def k(self, *args, check=True):
        readonly_args(args)
        return subprocess.run(['kubectl', '--request-timeout=15s', *args], check=check, capture_output=True, text=True, timeout=30)

    def j(self, *args):
        return json.loads(self.k(*args).stdout)

    def can(self, verb, resource, namespace):
        args = ('auth', 'can-i', verb, resource) + (('-n', namespace) if namespace else ())
        return self.k(*args, check=False).stdout.strip() == 'yes'

    def collect(self):
        identity = self.value['identity']
        obs, errors = {}, {}
        def observe(name, action):
            try:
                obs[name] = action()
            except Exception as exc:   # no raw text: it may carry tenant identifiers
                obs[name], errors[name] = None, type(exc).__name__
        observe('source', lambda: {'head': p8.p7.command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']),
                                   'clean': not p8.p7.command(['git', '-C', str(ROOT), 'status', '--porcelain'])})
        def cluster():
            value = json.loads(p8.p7.command(['az', 'aks', 'show', '--resource-group', identity['cluster_resource_id'].split('/')[4],
                                              '--name', identity['cluster_resource_id'].rsplit('/', 1)[1], '-o', 'json']))
            server = subprocess.run(['kubectl', 'config', 'view', '--minify', '-o', 'jsonpath={.clusters[0].cluster.server}'],
                                    check=True, capture_output=True, text=True, timeout=15).stdout
            require(urllib.parse.urlsplit(server).hostname in {value.get('fqdn'), value.get('privateFqdn')}, 'kubeconfig API server differs from AKS target')
            return {k: value.get(k) for k in ('id', 'currentKubernetesVersion', 'agentPoolProfiles', 'serviceMeshProfile')}
        observe('cluster', cluster)
        observe('access', lambda: {'read': {'|'.join(map(str, k)): self.can(*k) for k in READ_ACCESS},
                                   'campaign': {'|'.join(map(str, k)): self.can(*k) for k in CAMPAIGN_ACCESS}})
        if obs['access'] and all(obs['access']['read'].values()):
            if obs['cluster']:
                observe('cluster_uid', lambda: self.k('get', 'namespace', 'kube-system', '-o', 'jsonpath={.metadata.uid}').stdout)
                obs['cluster']['cluster_uid'] = obs.get('cluster_uid')
            observe('capacity', lambda: {'nodes': self.j('get', 'nodes', '-o', 'json')['items'],
                                         'pods': self.j('get', 'pods', '-A', '-o', 'json')['items']})
            observe('mesh', lambda: self.j('-n', MESH_NS, 'get', 'configmap', 'istio-shared-configmap-' + identity['revision'], '-o', 'json'))
            def ingress():
                selector = ','.join(k + '=' + v for k, v in identity['ingress_selector'].items())
                pods = self.j('-n', INGRESS_NS, 'get', 'pods', '-l', selector, '-o', 'json')['items']
                admin = lambda pod, path: json.loads(self.k('-n', INGRESS_NS, 'exec', pod, '-c', 'istio-proxy', '--',
                                                            'pilot-agent', 'request', 'GET', path).stdout)
                return [{'uid': p['metadata']['uid'], 'listeners': admin(p['metadata']['name'], 'config_dump?resource=dynamic_listeners'),
                         'routes': admin(p['metadata']['name'], 'config_dump?resource=dynamic_route_configs')} for p in pods]
            observe('ingress', ingress)
            observe('leftovers', lambda: {
                'namespace': bool(self.k('get', 'namespace', NS, '--ignore-not-found', '-o', 'name').stdout.strip()),
                'policy': bool(self.k('-n', INGRESS_NS, 'get', 'authorizationpolicy', 'p8-shared-gate', '--ignore-not-found', '-o', 'name').stdout.strip())})
            def crd():
                value = self.j('get', 'crd', 'podmonitors.azmonitoring.coreos.com', '-o', 'json')
                return any(c['type'] == 'Established' and c['status'] == 'True' for c in value['status']['conditions'])
            observe('crd', crd)
            observe('argo', lambda: self.j('-n', 'argocd', 'get', 'application', 'forgejo-azure', '-o', 'json'))
        def image():
            registry, reference = identity['ext_authz_image'].split('/', 1)
            p8.p7.command(['az', 'acr', 'repository', 'show', '--name', registry.split('.', 1)[0], '--image', reference, '-o', 'json'])
            return True
        observe('image', image)
        def prometheus():
            token = p8.p7.command(['az', 'account', 'get-access-token', '--resource', 'https://prometheus.monitor.azure.com',
                                   '--query', 'accessToken', '-o', 'tsv'])
            endpoint, cluster = self.value['prometheus']['endpoint'], self.value['prometheus']['cluster']
            query = lambda q: p8.p7.http_json(endpoint + '/api/v1/query', token, timeout=15, form={'query': q})
            return {'up': query('up{cluster=%s,namespace="forgejo"}' % json.dumps(cluster)),
                    'p10': query(m.managed_selector(NS, cluster))}
        observe('prometheus', prometheus)
        def https():
            result = p8.request('/api/healthz', {})
            return {k: result[k] for k in ('status', 'error_class', 'semantic_result')}
        observe('https', https)
        return obs, errors


# --- live: owned campaign ------------------------------------------------------------------------------

class PinnedHTTPS(http.client.HTTPSConnection):
    """Certificate + hostname verified HTTPS; an optional approved public IPv4 replaces only DNS (SNI unchanged)."""
    def __init__(self, host, address):
        super().__init__(host, 443, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address or self.host, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class AzureClient(pair.Client):
    """The Local demand (one Issue read; Git v2 info/refs + ls-refs), through the managed ingress over TLS."""
    def __init__(self, fixture, token, main_sha, title, host, address):
        super().__init__(fixture, token, main_sha, title)
        self.host, self.address = host, address

    def connection(self):
        return PinnedHTTPS(self.host, self.address)


class Forward:
    """Exact child `kubectl port-forward` handle; never restarted, always reaped."""
    def __init__(self, namespace, pod, ports, log):
        self.log = open(log, 'xb', opener=lambda p, flags: os.open(p, flags, 0o600))
        self.process = subprocess.Popen(['kubectl', '--request-timeout=15s', '-n', namespace, 'port-forward', '--address=127.0.0.1',
                                         'pod/' + pod, ports], stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, start_new_session=True)

    def alive(self):
        return self.process.poll() is None

    def stop(self):
        try:
            if self.process.poll() is None:
                self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
        finally:
            self.log.close()


class Campaign:
    def __init__(self, value, approval, ledger_path, output):
        self.value = manifest(value)
        approval_gate(value, approval, Path(ledger_path).exists())
        identity = value['identity']
        self.identity, self.v, self.f = identity, value['plan'], value['fixture']
        require(os.environ.get('DEV_USER') == self.f['owner'] and int(os.environ['ISSUE_NUMBER']) == self.f['issue'], 'fixture env differs from manifest')
        self.out = Path(output); self.out.mkdir(mode=0o700)
        self.rt = p8.Runtime(identity, approval_key='P10_AZURE_APPROVED')   # exact source/cluster/revision/fixed nodes/deadline
        transport = p8.measurement_transport(identity)
        self.transport = transport
        self.client = AzureClient(self.f, os.environ['DEV_TOKEN'], os.environ['MAIN_SHA'], os.environ['ISSUE_TITLE'],
                                  identity['forgejo_hostname'], transport['dns_client_override'])
        self.prom_token = p8.p7.command(['az', 'account', 'get-access-token', '--resource', 'https://prometheus.monitor.azure.com',
                                         '--query', 'accessToken', '-o', 'tsv'])
        # Ownership state: registered BEFORE the mutation it covers, released only after a read-back.
        self.owned_namespace = False
        self.policy = None          # {'uid': None until read back after apply}
        self.mesh = None            # original shared ConfigMap {uid, data}
        self.arm = None
        self.stable = None
        self.ledger = Ledger(ledger_path, value)    # exclusive: the first mutation needs a fresh ledger

    def checkpoint(self, phase, **safe):
        with (self.out / 'checkpoints.jsonl').open('a') as stream:
            stream.write(json.dumps({'phase': phase, 'monotonic': time.monotonic(), 'timestamp_utc': p8.utc(), **safe}) + '\n')

    def k(self, *args):
        return self.rt.k(*args)

    def j(self, *args):
        return json.loads(self.k(*args))

    def kubectl_input(self, args, value, timeout=120):
        subprocess.run(['kubectl', '--request-timeout=60s', *args, '-f', '-'], input=json.dumps(value), text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=timeout)

    # -- state readers --
    def stable_snapshot(self):
        pod = self.rt.pod('forgejo', 'app.kubernetes.io/name=forgejo')
        return {'pod_uid': pod['metadata']['uid'], 'deployment_spec_sha256': digest(self.j('-n', 'forgejo', 'get', 'deployment', 'forgejo', '-o', 'json')['spec'])}

    def argo_stable(self):
        app = self.j('-n', 'argocd', 'get', 'application', 'forgejo-azure', '-o', 'json')
        return (app['spec']['sources'][1]['targetRevision'] == app['spec']['sources'][2]['targetRevision'] == self.identity['stable_revision'] and
                app['status']['sync']['status'] == 'Synced' and app['status']['health']['status'] == 'Healthy')

    def ingress_pods(self):
        selector = ','.join(k + '=' + v for k, v in self.identity['ingress_selector'].items())
        pods = [p for p in self.rt.pods(INGRESS_NS, selector) if not p['metadata'].get('deletionTimestamp')]
        require(pods, 'ingress absent')
        return pods

    def provider_present(self):
        return any(v.get('name') == 'envoy.filters.http.ext_authz' and HAPROXY_CLUSTER in json.dumps(v) for p in self.ingress_pods()
                   for v in m.p8.walk(self.rt.admin(INGRESS_NS, p['metadata']['name'], 'config_dump?resource=dynamic_listeners')))

    # -- owned mutations --
    def start(self):
        """Refuse any pre-existing P10/P8 object, then namespace + experiment objects, provider overlay and CUSTOM policy."""
        require(datetime.now(timezone.utc) + timedelta(seconds=total_seconds(self.v)) < DEADLINE, 'insufficient retention time for the bounded campaign')
        require(not self.k('get', 'namespace', NS, '--ignore-not-found', '-o', 'name') and
                not self.k('-n', INGRESS_NS, 'get', 'authorizationpolicy', 'p8-shared-gate', '--ignore-not-found', '-o', 'name') and
                not self.provider_present(), 'pre-existing experiment namespace/policy/provider; never adopted')
        self.stable = self.stable_snapshot()
        require(self.argo_stable(), 'stable Argo drift before campaign')
        original = self.j('-n', MESH_NS, 'get', 'configmap', 'istio-shared-configmap-' + self.identity['revision'], '-o', 'json')
        mesh_contract(original, self.identity)
        for i in self.ingress_pods():
            ingress_contract(self.rt.admin(INGRESS_NS, i['metadata']['name'], 'config_dump?resource=dynamic_listeners'),
                             self.rt.admin(INGRESS_NS, i['metadata']['name'], 'config_dump?resource=dynamic_route_configs'),
                             self.identity['forgejo_hostname'])
        db = json.loads(Path(os.environ['P10_DB_ENV']).read_text())
        require(Path(os.environ['P10_DB_ENV']).stat().st_mode & 0o077 == 0 and set(db) <= DB_ENV_KEYS and
                {'PGHOST', 'PGDATABASE', 'PGUSER', 'PGPASSWORD'} <= set(db), 'protected DB read env')
        rendered = m.render(self.identity, self.v, self.f, 'shared')
        items = rendered['fixtures.json']['items']
        namespace = [o for o in items if o['kind'] == 'Namespace']
        rest = [o for o in items if o['kind'] != 'Namespace']
        secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'p8-db-read', 'namespace': NS, 'labels': {'p8.campaign': self.identity['campaign']}},
                  'type': 'Opaque', 'stringData': db}
        self.ledger.start('setup', 'shared')
        self.owned_namespace = True                 # before the first apply: a partial apply is still owned
        self.kubectl_input(['apply'], {'apiVersion': 'v1', 'kind': 'List', 'items': namespace + [secret] + rest})
        self.rollouts(['haproxy', 'ext-authz-shared'])
        self.mesh = {'uid': original['metadata']['uid'], 'data': original['data']}
        self.k('-n', MESH_NS, 'patch', 'configmap', original['metadata']['name'], '--type=merge', '-p',
               json.dumps(p8.mesh_overlay(original, self.identity)))
        self.policy = {'uid': None}
        self.kubectl_input(['apply'], rendered['policy.json'])
        self.policy['uid'] = self.j('-n', INGRESS_NS, 'get', 'authorizationpolicy', 'p8-shared-gate', '-o', 'json')['metadata']['uid']
        self.converge()
        self.arm = 'shared'
        self.checkpoint('started')

    def rollouts(self, names):
        for name in names:
            subprocess.run(['kubectl', '-n', NS, 'rollout', 'status', 'deployment/' + name, '--timeout=240s'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=270)

    def converge(self, timeout=180):
        """Every ingress replica has the exact CUSTOM scope and one healthy HAProxy endpoint that is the current Pod."""
        deadline = time.monotonic() + timeout
        policy = self.j('-n', INGRESS_NS, 'get', 'authorizationpolicy', 'p8-shared-gate', '-o', 'json')
        require(policy['metadata']['uid'] == self.policy['uid'], 'CUSTOM policy UID drift')
        while True:
            try:
                hp = self.rt.pod(NS, 'app=haproxy')
                for i in self.ingress_pods():
                    name = i['metadata']['name']
                    p8.gateway_scope(self.identity, policy, self.rt.admin(INGRESS_NS, name, 'config_dump?resource=dynamic_listeners'))
                    clusters = self.rt.admin(INGRESS_NS, name, 'clusters?format=json')
                    hosts = [h for c in clusters.get('cluster_statuses', []) if c.get('name') == HAPROXY_CLUSTER for h in c.get('host_statuses', [])]
                    require(len(hosts) == 1 and hosts[0]['health_status'] == {'eds_health_status': 'HEALTHY'} and
                            hosts[0]['address']['socket_address'] == {'address': hp['status']['podIP'], 'port_value': 8080}, 'ingress HAProxy endpoint')
                return
            except (ValueError, KeyError, subprocess.SubprocessError):
                require(time.monotonic() < deadline, 'ingress provider/HAProxy endpoint did not converge')
                time.sleep(2)

    def setup(self, arm):
        """Drained transition: remove the previous pools, admit the new ones, then swap the HAProxy backend selection."""
        if arm == self.arm:
            return
        self.ledger.start('setup', arm)
        rendered = m.render(self.identity, self.v, self.f, arm)['fixtures.json']['items']
        old = [o for o in m.render(self.identity, self.v, self.f, self.arm)['fixtures.json']['items']
               if o['kind'] in {'Deployment', 'Service'} and o['metadata']['name'].startswith('ext-authz-')]
        self.arm = None          # nothing measured until the new mapping is read back
        self.kubectl_input(['delete', '--ignore-not-found', '--wait=true', '--timeout=150s'], {'apiVersion': 'v1', 'kind': 'List', 'items': old}, 180)
        deadline = time.monotonic() + 180
        while self.rt.pods(NS, 'app=ext-authz-sim'):
            require(time.monotonic() < deadline, 'previous pool Pods did not terminate')
            time.sleep(2)
        pools = [o for o in rendered if o['kind'] in {'Deployment', 'Service'} and o['metadata']['name'].startswith('ext-authz-')]
        config = next(o for o in rendered if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'haproxy')
        self.kubectl_input(['apply'], {'apiVersion': 'v1', 'kind': 'List', 'items': pools + [config]})
        self.rollouts([o['metadata']['name'] for o in pools if o['kind'] == 'Deployment'])
        self.k('-n', NS, 'rollout', 'restart', 'deployment/haproxy')
        self.rollouts(['haproxy'])
        self.converge()
        self.arm = arm
        self.checkpoint('arm-admitted', arm=arm)

    def identify(self, arm):
        pool_admission(self.identity, arm, self.j('-n', NS, 'get', 'pods', '-o', 'json')['items'])
        pods = [p for p in self.rt.pods(NS, 'app=ext-authz-sim') if not p['metadata'].get('deletionTimestamp')]
        require(len(pods) == 2, 'pool Pod count')
        targets = []
        for pod in sorted(pods, key=lambda p: p['metadata']['uid']):
            name, pool = pod['metadata']['name'], pod['metadata']['labels']['p10.pool']
            deadline = time.monotonic() + 120
            while True:   # effective inbound capacity and hold must reach this sidecar before anything is measured
                try:
                    admin = lambda path: self.rt.admin(NS, name, path)
                    target = azure_target(pod, self.v, self.j('-n', NS, 'get', 'service', 'ext-authz-' + pool, '-o', 'json'),
                                          self.j('-n', NS, 'get', 'endpointslices', '-l', 'kubernetes.io/service-name=ext-authz-' + pool, '-o', 'json')['items'],
                                          admin('config_dump?resource=dynamic_active_clusters'), admin('config_dump?resource=dynamic_listeners'),
                                          admin('stats?format=json&filter=upstream_rq_'), admin('config_dump?mask=bootstrap.stats_config'),
                                          int(self.k('-n', NS, 'exec', name, '-c', 'app', '--', 'cat', '/config/hold-ms')))
                    break
                except (ValueError, KeyError, subprocess.SubprocessError):
                    require(time.monotonic() < deadline, 'effective inbound capacity/hold/endpoint did not converge')
                    time.sleep(2)
            targets.append(target)
        return pool_targets(arm, targets)

    def healthy(self, arm):
        """Classifier/native-auth/TLS through the actual managed ingress for this arm: the Local probe table over HTTPS."""
        self.ledger.start('healthy', arm)
        local = pair.local
        git_auth = {'Authorization': self.client.git_auth}
        results = []
        for name, method, path, headers, expected, body in local.probe_plan(self.f, {'Authorization': 'token ' + self.client.token}, git_auth):
            c = self.client.connection()
            try:
                c.request(method, path, headers=headers, body=body); r = c.getresponse(); payload = r.read()
            finally:
                c.close()
            results.append({'probe': name, 'status': r.status, 'expected': expected})
            require(r.status == expected and local.probe_semantics(name, payload, self.f, self.client.title), 'P10 healthy probe failed: ' + name)
        require(self.client.bulk('healthy-bulk', 1)['semantic_result'], 'native smart HTTP v2 read')
        for t in self.identify(arm):
            rows = [json.loads(line) for line in self.k('-n', NS, 'logs', t['name'], '-c', 'app').splitlines()]
            if rows: gate.validate_checks(rows)
        self.checkpoint('healthy', arm=arm, probes=len(results))
        return {'arm': arm, 'probes': results, 'tls': self.transport['tls_verification'], 'native_auth': True}

    def guard_snapshot(self, target_uids):
        pods = self.j('get', 'pods', '-A', '-o', 'json')['items']
        selected = {}
        def one(ns, label, value, key):
            mine = [p for p in pods if p['metadata']['namespace'] == ns and p['metadata'].get('labels', {}).get(label) == value]
            require(len(mine) == 1, 'confounder pod inventory ambiguous')
            selected[key] = p8.p4.pod_guard(mine[0])
        one('forgejo', 'app.kubernetes.io/name', 'forgejo', 'forgejo'); one(NS, 'app', 'haproxy', 'haproxy')
        selected['postgres'] = p8.p4.pod_guard(next(p for p in pods if p['metadata']['namespace'] == NS and p['metadata']['name'] == 'p8-db-client'))
        selector = self.identity['ingress_selector']
        for p in pods:
            if p['metadata']['namespace'] == INGRESS_NS and all(p['metadata'].get('labels', {}).get(k) == v for k, v in selector.items()):
                selected['ingress-' + p['metadata']['uid']] = p8.p4.pod_guard(p)
            if p['metadata']['uid'] in target_uids:
                selected['target-' + p['metadata']['uid']] = p8.p4.pod_guard(p)
        nodes = [{'name': n['metadata']['name'], 'conditions': {c['type']: c['status'] for c in n['status']['conditions']
                  if c['type'] in {'Ready', 'MemoryPressure', 'DiskPressure', 'PIDPressure'}}} for n in self.j('get', 'nodes', '-o', 'json')['items']]
        sql = self.k('-n', NS, 'exec', 'p8-db-client', '-c', 'db', '--', 'psql', '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', p8.SQL)
        db = json.loads(next(line for line in sql.splitlines() if line.startswith('{')))
        return {'pods': selected, 'nodes': nodes, 'postgres': {'query_ok': db['query_ok'], 'connections': db['connections'],
                'max_connections': db['max_connections'], 'reserved': db['reserved'], 'superuser_reserved': 0}}

    def haproxy_snapshot(self):
        name = self.rt.pod(NS, 'app=haproxy')['metadata']['name']
        run = lambda *command: self.k('-n', NS, 'exec', name, '-c', 'haproxy', '--', *command)
        return {'ring': m.parse_ring(run('sh', '-c', 'echo "show events p10" | nc -w 2 127.0.0.1 8405')),
                'info': m.parse_haproxy_info(run('sh', '-c', 'echo "show info" | nc -w 2 127.0.0.1 8405')),
                'stats': m.parse_haproxy_stats(run('wget', '-qO-', 'http://127.0.0.1:8404/stats;csv'))}

    def log_counts(self, targets, since):
        app, target = {}, {}
        for t in targets:
            rows = [json.loads(line) for line in self.k('-n', NS, 'logs', t['name'], '-c', 'app').splitlines()]
            if rows: gate.validate_checks(rows)
            app[t['uid']] = rows
            target[t['uid']] = proxy_rows(self.k('-n', NS, 'logs', t['name'], '-c', 'istio-proxy'))
        # The shared gateway's history is not read: every read of one run starts at the same fixed instant, so the
        # earlier read is still an exact prefix of the later one (rotation/rewrite stays detectable).
        ingress = {p['metadata']['uid']: proxy_rows(self.k('-n', INGRESS_NS, 'logs', p['metadata']['name'], '-c', 'istio-proxy', '--since-time=' + since))
                   for p in self.ingress_pods()}
        return {'ingress': ingress, 'target': target, 'app': app}

    def invariants(self, targets, info, haproxy_image):
        scopes = []
        for i in sorted(self.ingress_pods(), key=lambda p: p['metadata']['uid']):
            name = i['metadata']['name']
            listeners = self.rt.admin(INGRESS_NS, name, 'config_dump?resource=dynamic_listeners')
            routes = self.rt.admin(INGRESS_NS, name, 'config_dump?resource=dynamic_route_configs')
            scopes.append({'uid': i['metadata']['uid'], 'contract': ingress_contract(listeners, routes, self.identity['forgejo_hostname'], provider=True),
                           'scope': p8.gateway_scope(self.identity, self.j('-n', INGRESS_NS, 'get', 'authorizationpolicy', 'p8-shared-gate', '-o', 'json'), listeners)})
        return {'stable_revision': self.identity['stable_revision'], 'ingress_config_sha256': digest(scopes),
                'native_route_sha256': digest(sorted(s['contract']['routes_sha256'] for s in scopes)),
                'tls_auth_sha256': digest({'transport': self.transport, 'native_auth': 'forgejo-pat', 'ext_authz': 'CUSTOM'}),
                'target_resources_sha256': targets[0]['resources_sha256'], 'haproxy_image_id': haproxy_image,
                'haproxy_processes': info['Nbproc'], 'haproxy_threads': info['Nbthread'], 'haproxy_maxconn': info['Maxconn'],
                'proxy_retries_sha256': digest({'haproxy': 'retries 0', 'route_num_retries': 0}),
                'sentinel_sha256': digest({'direct_port': DIRECT, 'seconds': SENTINEL_SECONDS, 'plan': self.v['duration_seconds']}),
                'confounder_policy_sha256': digest(GUARD_POLICY)}

    def measure(self, arm, phase):
        """One fault run: the W1 driver and validator, W2 sampler/guards, AMW raw-sample collection on one clock."""
        self.ledger.start(phase, arm)   # consumed from here, whatever happens
        v, errors = self.v, []
        directory = self.out / (phase + '-' + arm); directory.mkdir(mode=0o700)
        targets = self.identify(arm)
        stop, live = threading.Event(), {t['uid']: {'ready': True, 'restarts': 0} for t in targets}
        events, sentinels, snapshots, polls, forwards, threads = [], [], [], [], [], []
        ports = dict(zip([t['uid'] for t in targets], ADMIN_PORTS))
        uids = {t['uid'] for t in targets}
        poll_failures = []
        def guarded(action):
            def body():
                try: action()
                except Exception as exc: errors.append(type(exc).__name__)
            return body
        auth = {'Authorization': 'token ' + self.client.token}
        issue = m.routes(self.f)['critical'][0][1]
        expected = (self.f['issue'], self.client.title)
        sampler = None
        since = datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
        try:
            for t in targets:
                forwards.append(Forward(NS, t['name'], '%d:15000' % ports[t['uid']], directory / ('admin-%d.log' % ports[t['uid']])))
            forgejo = self.rt.pod('forgejo', 'app.kubernetes.io/name=forgejo')['metadata']['name']
            forwards.append(Forward('forgejo', forgejo, '%d:3000' % DIRECT, directory / 'direct.log'))
            fetch = pair.AdminFetch(ports, pair.stat_path(targets[0]['prefixes']))
            sampler = pair.Sampler(targets, v['sample_seconds'], fetch, lambda: live)
            deadline = time.monotonic() + 30
            while True:
                try:
                    if all(fetch.ready(t) for t in targets): break
                except (OSError, http.client.HTTPException, ValueError):
                    pass
                require(time.monotonic() < deadline and all(f.alive() for f in forwards), 'target admin unavailable')
                time.sleep(.2)
            # Not measured: routing/native auth through the arm, then every target's inbound stats exist.
            warm = pair.Run.warm_up(self, targets, fetch)
            self.checkpoint('warm-up', arm=arm, step=phase, **warm)
            hp = self.rt.pod(NS, 'app=haproxy')
            haproxy_image = next(c['imageID'] for c in hp['status']['containerStatuses'] if c['name'] == 'haproxy')
            early = self.haproxy_snapshot()
            invariants = self.invariants(targets, early['info'], haproxy_image)
            binding = m.binding(self.identity, v, self.f, invariants)
            clock_start = m.clock_pair()
            poll_origin = time.monotonic()
            selector = m.managed_selector(NS, self.value['prometheus']['cluster'])
            amw = lambda path, params: p8.p7.http_json(self.value['prometheus']['endpoint'] + path, self.prom_token, timeout=5, form=params)
            def poll():
                lookback = min(600, int(time.monotonic() - poll_origin) + 2 * v['scrape_seconds'])
                try: polls.append(m.poll_managed(amw, selector, lookback))
                except Exception as exc: poll_failures.append(type(exc).__name__)   # a gap, never a value
            def monitor_managed():
                while not stop.is_set():
                    poll(); stop.wait(v['scrape_seconds'] / 3)
            def monitor_guards():
                while not stop.is_set():
                    begin = time.monotonic(); snapshot = self.guard_snapshot(uids)
                    snapshots.append({'begin': begin, 'end': time.monotonic(), 'snapshot': snapshot})
                    for key, pod in snapshot['pods'].items():
                        if key.startswith('target-'):
                            live[key[len('target-'):]] = {'ready': pod['ready'], 'restarts': sum(c['restarts'] for c in pod['containers'])}
                    stop.wait(GUARD_SECONDS)
            def monitor_sentinel():
                while not stop.is_set():
                    sentinels.append({'read': p8.p4.request(DIRECT, issue, auth, expected), 'health': p8.p4.request(DIRECT, '/api/healthz', {})})
                    stop.wait(SENTINEL_SECONDS)
            threads = [threading.Thread(target=guarded(f), daemon=True) for f in
                       (lambda: sampler.run(stop), monitor_guards, monitor_sentinel, monitor_managed)]
            for thread in threads: thread.start()
            deadline = time.monotonic() + 60
            while not (len(sampler.rows) >= 4 and snapshots and sentinels and polls):
                require(time.monotonic() < deadline and not errors, 'monitors did not start before the window')
                time.sleep(.1)
            before = self.haproxy_snapshot()
            logs_before = self.log_counts(targets, since)
            requests_before = dict(self.client.counts)
            before_at = time.monotonic()
            self.checkpoint('window-start', arm=arm, step=phase)
            origin = m.drive(v, self.client.probes(), events.append)
            self.checkpoint('window-end', arm=arm, step=phase)
            completed = max(e['completed'] for e in events if e['record'] == 'operation')
            coverage_end = max(completed, origin + v['duration_seconds'])
            deadline = time.monotonic() + v['drain_seconds']
            while sampler.rows[-1]['at'] < completed + 2 * v['sample_seconds'] or any(
                    t['stats']['upstream_rq_active'] for r in sampler.rows[-2:] for t in r['targets']):
                require(time.monotonic() < deadline, 'targets did not drain')
                time.sleep(.1)
            after = self.haproxy_snapshot()
            demand_counts = {k: self.client.counts[k] - requests_before[k] for k in m.CLASSES}
            want = pair.expected_log_counts(after['ring'][len(before['ring']):])
            deadline = time.monotonic() + 30
            while True:   # asynchronous access-log flush: bounded wait, counted against HAProxy
                logs_after = self.log_counts(targets, since)
                obs, non_http_rows = azure_observation(targets, before, after, logs_before, logs_after, demand_counts)
                got = {'ingress': len(obs['ingress_rows']), 'target': sum(map(len, obs['target_rows'].values())),
                       'app': sum(map(len, obs['app_checks'].values()))}
                if got == want or time.monotonic() > deadline: break
                time.sleep(1)
            after_at = time.monotonic()
            # Managed tail: scrape + ingestion at most; stop early once a drained-boundary sample is visible.
            pods = [{'name': t['name'], 'uid': t['uid'], 'pool': t['pool']} for t in targets]
            tail = time.monotonic() + v['scrape_seconds'] + v['ingestion_seconds']
            while time.monotonic() < tail:
                try:
                    rows = managed_rows(self.value, list(polls), pods, {'start': clock_start, 'end': m.clock_pair()})
                    if rows and rows[-1]['sample_at'] > coverage_end + m.MANAGED_CLOCK_TOLERANCE + 1: break
                except ValueError:
                    break
                time.sleep(v['scrape_seconds'] / 3)
            sentinels.append({'read': p8.p4.request(DIRECT, issue, auth, expected), 'health': p8.p4.request(DIRECT, '/api/healthz', {})})
            begin = time.monotonic(); final = self.guard_snapshot(uids)
            snapshots.append({'begin': begin, 'end': time.monotonic(), 'snapshot': final})
        finally:
            stop.set()
            for thread in threads: thread.join(timeout=30)
            for forward in forwards: forward.stop()
            # Append-only raw, saved whatever stopped the run; a failed run stays invalid and consumed.
            m.save(directory / 'raw.json', {'events': events, 'samples': sampler.rows if sampler else [], 'managed_polls': polls,
                                            'managed_poll_failures': poll_failures, 'sentinels': sentinels, 'guard_snapshots': snapshots,
                                            'monitor_errors': errors})
        clock_end = m.clock_pair()
        require(not errors, 'monitor thread failed: ' + ','.join(sorted(set(errors))))
        require(self.stable_snapshot() == self.stable and self.argo_stable(), 'stable Forgejo/Argo changed during the run')
        after_invariants = self.invariants(targets, after['info'], haproxy_image)
        clock = {'start': clock_start, 'end': clock_end}
        try:
            evidence = m.window_accounting(arm, obs)
        except ValueError:
            m.save(directory / 'accounting-failure.json', {'expected_log_counts': want, 'log_deltas': got, 'client_requests': demand_counts, 'observation': obs})
            raise
        try:
            managed = managed_rows(self.value, polls, pods, clock)
        except ValueError as exc:   # structurally invalid managed series: kept raw above, never zero
            managed = []
            self.checkpoint('managed-invalid', arm=arm, step=phase, reason=str(exc)[:200])
        clean = evidence['queue_end'] == evidence['haproxy_retries'] == evidence['dropped_logs'] == evidence['classifier_escapes'] == 0 and \
            evidence['counter_lifetime_unchanged'] and all(c['queue'] == c['other'] == 0 for c in evidence['classes'].values())
        tls = self.transport['tls_verification'] == 'certificate-and-hostname' and all(e['record'] != 'operation' or all(
            a['error_class'] not in {'transport', 'timeout'} for a in e['attempts']) for e in events)
        facts = {'haproxy': {k: evidence[k] for k in ('queue_end', 'haproxy_retries', 'dropped_logs', 'classifier_escapes', 'counter_lifetime_unchanged')},
                 'native_auth': warm['anonymous_issue'] == 404, 'tls': tls, 'ingress': {'rows': len(obs['ingress_rows']), 'non_http_retained': non_http_rows},
                 'span': (before_at, after_at)}
        run = {'plan': v, 'arm': arm, 'source_sha': self.identity['source_sha'], 'binding': binding, 'binding_sha256': digest(binding),
               'runtime_before': invariants, 'runtime_after': after_invariants, 'events': events, 'samples': sampler.rows,
               'environment': 'azure', 'healthy_classification': True, 'tls': tls, 'native_auth': facts['native_auth'],
               'guards': pair.guards_from(snapshots, (origin, coverage_end), sentinels, clean, facts), 'accounting': evidence,
               'managed_samples': managed, 'managed_clock': clock,
               'observation': {'sampler_failures': sampler.failures, 'managed_poll_failures': poll_failures, 'managed_polls': len(polls),
                               'ring_window': obs['ring_after'][len(obs['ring_before']):], 'log_deltas': got, 'warm_up': warm,
                               'targets': [{k: x for k, x in t.items() if k != 'prefixes'} for t in targets]}}
        m.save(directory / 'run.json', run)
        self.checkpoint('raw-saved', arm=arm, step=phase)
        return run

    # -- owned rollback --
    def restore(self):
        """Exact-UID CUSTOM removal -> guarded shared ConfigMap data restore -> owned namespace removal -> read-back."""
        problems, state = [], {}
        def step(name, action):
            try: action()
            except Exception as exc: problems.append(name + ':' + type(exc).__name__)
        def policy():
            if self.policy is not None:
                live = self.k('-n', INGRESS_NS, 'get', 'authorizationpolicy', 'p8-shared-gate', '--ignore-not-found', '-o', 'json')
                if live:
                    meta = json.loads(live)['metadata']
                    require(meta['uid'] == self.policy['uid'] or self.policy['uid'] is None and
                            meta.get('labels', {}).get('p8.campaign') == self.identity['campaign'], 'CUSTOM policy is not the owned object')
                    self.k('-n', INGRESS_NS, 'delete', 'authorizationpolicy', 'p8-shared-gate', '--wait=true', '--timeout=60s')
                require(not self.k('-n', INGRESS_NS, 'get', 'authorizationpolicy', 'p8-shared-gate', '--ignore-not-found', '-o', 'name'), 'policy remains')
                self.policy = None
            state['policy_removed'] = True
        def mesh():
            if self.mesh is not None:
                live = self.j('-n', MESH_NS, 'get', 'configmap', 'istio-shared-configmap-' + self.identity['revision'], '-o', 'json')
                require(live['metadata']['uid'] == self.mesh['uid'], 'shared ConfigMap replaced; not restored blindly')
                if live['data'] != self.mesh['data']:
                    self.k('-n', MESH_NS, 'patch', 'configmap', live['metadata']['name'], '--type=merge', '-p', json.dumps({'data': self.mesh['data']}))
                require(self.j('-n', MESH_NS, 'get', 'configmap', live['metadata']['name'], '-o', 'json')['data'] == self.mesh['data'], 'shared ConfigMap data not restored')
                self.mesh = None
            state['mesh_restored'] = True
        def namespace():
            if self.owned_namespace:
                if self.k('get', 'namespace', NS, '--ignore-not-found', '-o', 'name'):
                    labels = self.j('get', 'namespace', NS, '-o', 'json')['metadata'].get('labels', {})
                    require(labels.get('p8.campaign') == self.identity['campaign'], 'namespace is not the owned object')
                    subprocess.run(['kubectl', '--request-timeout=60s', 'delete', 'namespace', NS, '--wait=true', '--timeout=300s'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=330)
                require(not self.k('get', 'namespace', NS, '--ignore-not-found', '-o', 'name'), 'owned namespace remains')
                self.owned_namespace = False
            state['namespace_removed'] = True
        step('policy', policy)
        step('mesh', mesh)
        step('namespace', namespace)
        def verify():
            deadline = time.monotonic() + 120
            while self.provider_present():
                require(time.monotonic() < deadline, 'ingress still has the experiment ext_authz filter')
                time.sleep(2)
            state['ingress_provider_absent'] = True
            state['stable_unchanged'] = self.stable is None or self.stable_snapshot() == self.stable
            state['argo_stable'] = self.argo_stable()
            health = p8.request('/api/healthz', {})
            read = p8.request(m.routes(self.f)['critical'][0][1], {'Authorization': 'token ' + self.client.token}, (self.f['issue'], self.client.title))
            state['https_healthy'] = health['semantic_result'] is True and read['semantic_result'] is True
        step('verify', verify)
        state['owned_pending'] = {'namespace': self.owned_namespace, 'policy': self.policy is not None, 'mesh': self.mesh is not None}
        return restoration_verdict({'problems': problems, **state})


def sequence(calibrate):
    """Healthy both arms, optional calibration pair, measured pair; no automatic repetition."""
    steps = [('healthy', 'shared'), ('healthy', 'isolated')]
    if calibrate:
        steps += [('calibration', 'isolated'), ('calibration', 'shared')]
    return steps + [('measured', 'shared' if calibrate else 'isolated'), ('measured', 'isolated' if calibrate else 'shared')]


def run_campaign(value, approval, ledger_path, output, calibrate=False):
    campaign = Campaign(value, approval, ledger_path, output)
    runs, outcomes, failure = {}, {}, None
    try:
        campaign.start()
        for step, arm in sequence(calibrate):
            campaign.setup(arm)
            if step == 'healthy':
                m.save(campaign.out / ('healthy-' + arm + '.json'), campaign.healthy(arm))
                continue
            runs[(step, arm)] = campaign.measure(arm, step)
            try:
                outcomes[(step, arm)] = pair.summarize(m.validate(runs[(step, arm)]))
            except ValueError as exc:
                outcomes[(step, arm)] = {'status': 'invalid', 'arm': arm, 'reason': str(exc)}
            m.save(campaign.out / (step + '-' + arm) / 'summary.json', outcomes[(step, arm)])
            # Fail closed: a calibration that is not valid never leads to the measured pair.
            require(step != 'calibration' or outcomes[(step, arm)]['status'] == 'valid', 'calibration not valid; campaign stops')
    except Exception as exc:
        failure = {'class': type(exc).__name__, 'message': str(exc) if isinstance(exc, ValueError) and len(str(exc)) < 200 else None}
        m.save(campaign.out / 'failure.json', failure)
    finally:
        restoration = campaign.restore()
        m.save(campaign.out / 'restoration.json', restoration)
    if failure or not restoration['restored'] or not all(('measured', a) in runs for a in m.ARMS):
        return 1
    try:
        result = m.compare(runs[('measured', 'shared')], runs[('measured', 'isolated')])
    except ValueError as exc:
        result = {'status': 'invalid', 'reason': str(exc)}
    result = {**result, 'source_sha': value['identity']['source_sha'], 'manifest_sha256': digest(value), 'completed': True,
              'arms': [outcomes[('measured', a)] for a in m.ARMS],
              'limitations': ['one Azure pair; not a statistical generalization', 'exact fixture operations only; actor/role protection not established']}
    m.save(campaign.out / 'result.json', result)
    return 0 if result['status'] in {'positive', 'valid-negative'} else 1


def main(args):
    if len(args) == 4 and args[0] == 'preflight':
        value = m.load(args[1])
        obs, errors = Preflight(value).collect()
        verdict = preflight_verdict(value, obs, m.load(args[2]), datetime.now(timezone.utc))
        m.save(args[3], {**verdict, 'collection_errors': errors})
        print(json.dumps({'status': verdict['status'], 'blockers': verdict['blockers'], 'collection_errors': errors}))
        return 0 if verdict['status'] == 'ready-for-approval-request' else 1
    if len(args) in {5, 6} and args[0] == 'campaign' and args[5:] in ([], ['--calibration']):
        return run_campaign(m.load(args[1]), m.load(args[2]), args[3], args[4], calibrate=args[5:] == ['--calibration'])
    raise ValueError('usage: preflight MANIFEST PRICE OUTPUT | campaign MANIFEST APPROVAL LEDGER OUTPUT [--calibration]')


if __name__ == '__main__':
    try:
        os.umask(0o077)
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) and len(str(exc)) < 200 and '\n' not in str(exc) else 'raw exception suppressed'
        print('P10 Azure failed: ' + type(exc).__name__ + ': ' + reason, file=sys.stderr)
        sys.exit(1)
