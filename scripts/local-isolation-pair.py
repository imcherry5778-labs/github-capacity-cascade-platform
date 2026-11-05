#!/usr/bin/env python3
"""P10 Local paired load: shared 2-replica pool vs isolated Critical/Bulk pools, one owned P4 cluster.

Real ingress CUSTOM ext_authz -> pinned HAProxy classifier -> real Service/Pod pools with selected-Istio
inbound capacity -> real Forgejo native auth. Cost-free; no Azure entrypoint, credential or mutation.

Local HTTP loopback port-forward on one single-node runner is NOT Azure/TLS evidence, and a Local result is
not a protection claim beyond these exact fixture operations. A valid negative is a valid result: only the
measured pair decides, and thresholds are never relaxed after the fact.
"""
import base64
import concurrent.futures
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
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


m = module('p10_pair', 'critical-bulk-isolation.py')
local = module('p10_pair_local', 'local-isolation-check.py')
sat = m.p8.p4
gate = sat.gate
require, digest = m.require, m.digest
NS = 'shared-gate'
GATED, DIRECT = 18080, 13000
ADMIN_PORTS = (19101, 19102)
SENTINEL_SECONDS, GUARD_SECONDS = 1.0, 2.0
GUARD_POLICY = {'guards': sorted(m.GUARDS), 'sentinel_seconds': SENTINEL_SECONDS, 'guard_seconds': GUARD_SECONDS}
LIMITATIONS = ['Local HTTP loopback port-forward on one single-node runner; not Azure, TLS or managed-telemetry evidence',
               'No CPU saturation metric (metrics-server disabled): node pressure conditions only',
               'Exact fixture operations only; actor/role protection is not established',
               'One pair; thresholds are the unchanged candidate and are not frozen by this run']


def kj(*args):
    return json.loads(gate.kube(*args))


# --- demand --------------------------------------------------------------------------------------------

def ls_refs_body(branch='main'):
    """Git protocol v2 ls-refs request; verified against `git upload-pack --stateless-rpc`."""
    def pkt(text): return ('%04x' % (len(text) + 4)).encode() + text.encode()
    return pkt('command=ls-refs\n') + b'0001' + pkt('ref-prefix refs/heads/%s\n' % branch) + b'0000'


class Client:
    """Critical = one Issue read. Bulk = the two HTTP requests of a Git v2 read (info/refs, then ls-refs).

    A new connection per request through the ingress port-forward; no retry. Every issued HTTP request is
    counted per class (the ingress-side demand that must equal what HAProxy classified).
    """
    def __init__(self, fixture, token, main_sha, title, port=GATED):
        self.f, self.token, self.main_sha, self.title, self.port = fixture, token, main_sha, title, port
        routes = m.routes(fixture)
        self.critical_uri, (self.refs_uri, self.pack_uri) = routes['critical'][0][1], [uri for _, uri in routes['bulk']]
        self.git_auth = 'Basic ' + base64.b64encode((fixture['owner'] + ':' + token).encode()).decode()
        self.counts = {kind: 0 for kind in m.CLASSES}
        self.lock = threading.Lock()

    def fetch(self, kind, method, uri, headers, body=None):
        with self.lock: self.counts[kind] += 1
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            c.request(method, uri, body=body, headers=headers); r = c.getresponse()
            return {'status': r.status, 'body': r.read(), 'error': None}
        except TimeoutError:
            return {'status': None, 'body': b'', 'error': 'timeout'}
        except (OSError, http.client.HTTPException):
            return {'status': None, 'body': b'', 'error': 'transport'}
        finally:
            c.close()

    @staticmethod
    def result(response, semantic):
        if response['error']:
            return {'semantic_result': False, 'status': None, 'error_class': response['error'], 'overload': False}
        ok = response['status'] == 200 and semantic(response['body'])
        return {'semantic_result': ok, 'status': response['status'], 'overload': response['status'] == 403,
                'error_class': 'none' if ok else ('http_status' if response['status'] != 200 else 'semantic_error')}

    def issue_matches(self, body):
        try:
            value = json.loads(body)
            return value.get('number') == self.f['issue'] and value.get('title') == self.title and \
                value.get('state') == 'open' and value.get('pull_request') is None
        except (ValueError, AttributeError):
            return False

    def critical(self, op, index, unauthenticated=False):
        headers = {'x-operation-id': op, 'x-attempt-id': f'{op}-attempt-{index}'}
        if not unauthenticated: headers['Authorization'] = 'token ' + self.token
        return self.fetch('critical', 'GET', self.critical_uri, headers)

    def bulk(self, op, index):
        headers = {'Authorization': self.git_auth, 'Git-Protocol': 'version=2', 'x-operation-id': op}
        first = self.fetch('bulk', 'GET', self.refs_uri, headers | {'x-attempt-id': f'{op}-attempt-{index}-http-1'})
        if first['error'] or first['status'] != 200 or not (b'version 2' in first['body'] and b'ls-refs' in first['body']):
            return self.result(first, lambda body: False)
        second = self.fetch('bulk', 'POST', self.pack_uri, headers | {'Content-Type': 'application/x-git-upload-pack-request',
                            'x-attempt-id': f'{op}-attempt-{index}-http-2'}, ls_refs_body())
        return self.result(second, lambda body: (self.main_sha + ' refs/heads/main').encode() in body)

    def probes(self):
        return {'critical': lambda op, index: self.result(self.critical(op, index), self.issue_matches),
                'bulk': self.bulk}


# --- native sampling -----------------------------------------------------------------------------------

def stat_path(prefixes):
    clusters = [p[len('cluster.'):-1] for p in prefixes]
    names = '|'.join(sorted(k[len('upstream_rq_'):] for k in m.STATS))
    regex = '^cluster\\.(?:%s)\\.upstream_rq_(?:%s)$' % ('|'.join(re.escape(c) for c in clusters), names)
    return '/stats?filter=' + urllib.parse.quote(regex, safe='')


def parse_stats(text, prefixes):
    stats = {}
    for line in text.splitlines():
        if ': ' not in line: continue
        key, value = line.rsplit(': ', 1)
        for prefix in prefixes:
            if key.startswith(prefix) and key[len(prefix):] in m.STATS:
                require(value.isdigit() and key[len(prefix):] not in stats, 'non-integer or duplicate target stat')
                stats[key[len(prefix):]] = int(value)
    require(set(stats) == m.STATS, 'required target stats absent/ambiguous')
    return stats


class Sampler:
    """Fixed-cadence native Envoy stat rows for both targets from one process on one monotonic clock.

    `sample_at` is the midpoint of the concurrent reads; a failed read leaves a gap (never a zero or a retry),
    and a missed tick is skipped rather than caught up with a burst of snapshots.
    """
    PLUMBING = {'name', 'endpoints', 'prefixes'}

    def __init__(self, targets, interval, fetch, status, clock=time.monotonic):
        self.targets, self.interval, self.fetch, self.status, self.clock = targets, interval, fetch, status, clock
        self.rows, self.failures = [], 0

    def tick(self, pool):
        begin = self.clock()
        reads = [pool.submit(self.fetch, t) for t in self.targets]
        try:
            stats = [r.result() for r in reads]
        except Exception:
            self.failures += 1
            return
        end = self.clock()
        live = self.status()
        self.rows.append({'at': end, 'sample_at': (begin + end) / 2, 'targets': [
            {**{k: x for k, x in t.items() if k not in self.PLUMBING}, 'ready': live[t['uid']]['ready'],
             'restarts': live[t['uid']]['restarts'], 'stats': s} for t, s in zip(self.targets, stats)]})

    def run(self, stop):
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.targets)) as pool:
            due = self.clock()
            while not stop.is_set():
                self.tick(pool)
                due += self.interval
                now = self.clock()
                if due < now: due = now
                stop.wait(due - now)


class AdminFetch:
    """Persistent Envoy admin connection per target (via a kubectl port-forward to loopback)."""
    def __init__(self, ports, path):
        self.ports, self.path, self.connections = ports, path, {}

    def ready(self, target):
        """Admin reachable. Inbound cluster stats do not exist before the first request, so that is not readiness."""
        c = http.client.HTTPConnection('127.0.0.1', self.ports[target['uid']], timeout=2)
        try:
            c.request('GET', '/server_info'); r = c.getresponse()
            return r.status == 200 and json.loads(r.read()).get('state') == 'LIVE'
        finally:
            c.close()

    def __call__(self, target):
        uid = target['uid']
        try:
            if uid not in self.connections:
                self.connections[uid] = http.client.HTTPConnection('127.0.0.1', self.ports[uid], timeout=2)
            c = self.connections[uid]
            c.request('GET', self.path); r = c.getresponse(); text = r.read().decode()
            require(r.status == 200, 'target admin read failed')
            return parse_stats(text, target['prefixes'])
        except (OSError, http.client.HTTPException, ValueError):
            c = self.connections.pop(uid, None)
            if c: c.close()
            raise


# --- confounder guards ---------------------------------------------------------------------------------

DB_QUERY = """SELECT json_build_object('query_ok',1=1,'connections',(SELECT count(*) FROM pg_stat_activity),
  'max_connections',current_setting('max_connections')::int,
  'superuser_reserved',current_setting('superuser_reserved_connections')::int,
  'reserved',current_setting('reserved_connections')::int);"""


def guard_snapshot(target_uids):
    pods = kj('get', 'pods', '-A', '-o', 'json')['items']
    selected = {}
    for ns, label, value, key in (('forgejo', 'app.kubernetes.io/name', 'forgejo', 'forgejo'), ('postgres', 'app.kubernetes.io/name', 'postgres', 'postgres'),
                                  (NS, 'app', 'haproxy', 'haproxy'), (NS, 'istio', 'p4-ingress', 'ingress')):
        mine = [p for p in pods if p['metadata']['namespace'] == ns and p['metadata'].get('labels', {}).get(label) == value]
        require(len(mine) == 1, 'confounder pod inventory ambiguous')
        selected[key] = sat.pod_guard(mine[0])
    for p in pods:
        if p['metadata']['uid'] in target_uids:
            selected['target-' + p['metadata']['uid']] = sat.pod_guard(p)
    require(len(selected) == 4 + len(target_uids), 'target Pod absent from confounder inventory')
    nodes = [{'name': n['metadata']['name'], 'conditions': {c['type']: c['status'] for c in n['status']['conditions']
              if c['type'] in {'Ready', 'MemoryPressure', 'DiskPressure', 'PIDPressure'}}} for n in kj('get', 'nodes', '-o', 'json')['items']]
    db = json.loads(gate.kube('-n', 'postgres', 'exec', 'postgres-0', '-c', 'postgres', '--', 'psql', '-U', 'postgres', '-d', 'forgejo', '-tA', '-c', DB_QUERY))
    return {'pods': selected, 'nodes': nodes, 'postgres': db}


def guards_from(snapshots, window, sentinels, accounting_ok, facts):
    """The nine guards from same-window observations. A failed guard is recorded, never hidden.

    `window` = (start, coverage_end) on the harness monotonic clock; each guard states its observed span.
    """
    first = snapshots[0]['snapshot']
    span = (snapshots[0]['begin'], snapshots[-1]['end'])
    def stable(keys):
        return all(set(s['snapshot']['pods']) == set(first['pods']) and all(
            s['snapshot']['pods'][k]['ready'] and s['snapshot']['pods'][k]['phase'] == 'Running' and not s['snapshot']['pods'][k]['reason'] and
            s['snapshot']['pods'][k]['uid'] == first['pods'][k]['uid'] and s['snapshot']['pods'][k]['containers'] == first['pods'][k]['containers'] and
            all(c['ready'] and c['last_termination'] not in {'OOMKilled', 'Error'} for c in s['snapshot']['pods'][k]['containers'])
            for k in keys) for s in snapshots)
    targets = [k for k in first['pods'] if k.startswith('target-')]
    pod_names = lambda key: [c['name'] for c in first['pods'][key]['containers']]
    nodes_ok = all(s['snapshot']['nodes'] and all(n['conditions'] == {'Ready': 'True', 'MemoryPressure': 'False', 'DiskPressure': 'False', 'PIDPressure': 'False'}
                                                for n in s['snapshot']['nodes']) for s in snapshots)
    db_ok = all(s['snapshot']['postgres']['query_ok'] and s['snapshot']['postgres']['connections'] <
                s['snapshot']['postgres']['max_connections'] - s['snapshot']['postgres']['reserved'] - s['snapshot']['postgres']['superuser_reserved']
                for s in snapshots)
    sentinel_ok = bool(sentinels) and all(e['read']['semantic_result'] and e['health']['semantic_result'] for e in sentinels) and \
        min(e['read']['start_monotonic'] for e in sentinels) <= window[0] and max(e['read']['end_monotonic'] for e in sentinels) >= window[1]
    sentinel_span = (min(e['read']['start_monotonic'] for e in sentinels), max(e['health']['end_monotonic'] for e in sentinels)) if sentinels else (0, 0)
    def dense(times, limit):
        times = sorted(times)
        return len(times) >= 2 and all(b - a <= limit for a, b in zip(times, times[1:]))
    # A monitor that died mid-window leaves a hole, which is a failed guard, not a pass.
    held = dense([s['begin'] for s in snapshots] + [snapshots[-1]['end']], 4 * GUARD_SECONDS)
    sentinel_held = bool(sentinels) and dense([e['read']['start_monotonic'] for e in sentinels] + [sentinels[-1]['read']['end_monotonic']], 5 * SENTINEL_SECONDS)
    entries = {
        'forgejo': (held and stable(['forgejo']), {'pod': first['pods']['forgejo']['uid']}, span),
        # Local Forgejo has no mesh sidecar; absence is the observation, a present one must also be stable.
        'forgejo_sidecar': (held and ('istio-proxy' not in pod_names('forgejo') or stable(['forgejo'])), {'sidecar': 'istio-proxy' in pod_names('forgejo')}, span),
        'postgres': (held and stable(['postgres']) and db_ok, {'pod': first['pods']['postgres']['uid'], 'connections_ok': db_ok}, span),
        'node': (held and nodes_ok, {'nodes': [n['name'] for n in first['nodes']]}, span),
        'scheduling': (held and stable(targets + ['haproxy', 'ingress']) and len(targets) == 2, {'targets': sorted(targets)}, span),
        'sentinel': (sentinel_ok and sentinel_held, {'reads': len(sentinels)}, sentinel_span),
        'haproxy': (accounting_ok and held and stable(['haproxy']), facts['haproxy'], facts['span']),
        'tls_native_auth': (facts['native_auth'] is True, {'tls': m.LOCAL_TLS, 'native_auth': facts['native_auth']}, facts['span']),
        'ingress': (accounting_ok and held and stable(['ingress']), facts['ingress'], facts['span'])}
    require(set(entries) == m.GUARDS, 'guard inventory')
    return {name: {'observed': True, 'competing_bottleneck': not ok, 'start': s, 'end': e, 'evidence_sha256': digest(evidence)}
            for name, (ok, evidence, (s, e)) in entries.items()}


# --- cluster state -------------------------------------------------------------------------------------

def apply_list(items):
    value = {'apiVersion': 'v1', 'kind': 'List', 'items': items}
    subprocess.run(['kubectl', '--request-timeout=60s', 'apply', '-f', '-'], input=json.dumps(value), text=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=90)


def delete_list(items):
    value = {'apiVersion': 'v1', 'kind': 'List', 'items': items}
    subprocess.run(['kubectl', '--request-timeout=60s', 'delete', '-f', '-', '--ignore-not-found', '--wait=true', '--timeout=150s'],
                   input=json.dumps(value), text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=180)


def rollout(name, seconds):
    """`gate.command` kills at 60s; a pool Pod with a sidecar on a loaded runner may legitimately take longer."""
    subprocess.run(['kubectl', '-n', NS, 'rollout', 'status', name, f'--timeout={seconds}s'], stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, check=True, timeout=seconds + 30)


def stable_snapshot():
    items = kj('-n', 'forgejo', 'get', 'deployment/forgejo', 'service/forgejo-http', '-o', 'json')['items']
    return sorted(({'kind': i['kind'], 'uid': i['metadata']['uid'], 'spec': i['spec']} for i in items), key=lambda x: x['kind'])


def present(items):
    """Which of the exact inventory objects exist, by kind/namespace/name (never by label)."""
    found = []
    for item in items:
        group = item['apiVersion'].split('/')[0] if '/' in item['apiVersion'] else ''
        name = gate.kube('-n', item['metadata']['namespace'], 'get', item['kind'].lower() + ('.' + group if group else ''),
                         item['metadata']['name'], '--ignore-not-found', '-o', 'name').strip()
        if name: found.append(name)
    return found


def left_over(inventory):
    """Anything a P10 run would create or overwrite that is already there: never adopted, never silently cleaned.

    Labeled P10 objects and Pods from an earlier run, and also any object -- labeled or not -- that already holds
    one of the exact names this run is about to apply (and later delete).
    """
    found = [i['metadata']['name'] for kind in ('deployments', 'services', 'sidecars.networking.istio.io')
             for i in kj('-n', NS, 'get', kind, '-l', 'p10.pair=owned', '-o', 'json')['items']]
    found += [p['metadata']['name'] for p in kj('-n', NS, 'get', 'pods', '-l', 'app=ext-authz-pool', '-o', 'json')['items']]
    return found + [name for items in inventory for name in present(items)]


def baseline():
    deployment = kj('-n', NS, 'get', 'deployment/ext-authz-sim', '-o', 'json')
    pod = deployment['spec']['template']
    return {'haproxy_config': kj('-n', NS, 'get', 'configmap/haproxy', '-o', 'json')['data']['haproxy.cfg'],
            'hold_ms': kj('-n', NS, 'get', 'configmap/ext-authz-hold', '-o', 'json')['data']['hold-ms'],
            'replicas': deployment['spec']['replicas'], 'stable': stable_snapshot(),
            'template': {'metadata': {'annotations': {k: v for k, v in pod['metadata'].get('annotations', {}).items()
                                                      if k in {'sidecar.istio.io/inject', 'proxy.istio.io/config'}}}, 'spec': pod['spec']}}


def pool_pods(expected):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        pods = [p for p in kj('-n', NS, 'get', 'pods', '-l', 'app=ext-authz-pool', '-o', 'json')['items'] if not p['metadata'].get('deletionTimestamp')]
        ready = [p for p in pods if any(c['type'] == 'Ready' and c['status'] == 'True' for c in p['status'].get('conditions', []))]
        if len(pods) == len(ready) == expected:
            return ready
        time.sleep(2)
    require(False, 'Pod pools did not become Ready')


def target_identity(pod, v, service, slices, clusters, hold):
    statuses = {c['name']: c for c in pod['status'].get('initContainerStatuses', []) + pod['status']['containerStatuses']}
    containers = {c['name']: c for c in gate.active_containers(pod)}
    require({'app', 'istio-proxy'} <= set(statuses) and {'app', 'istio-proxy'} <= set(containers), 'target sidecar absent')
    cluster = gate.target_cluster(clusters, v['max_requests'])
    uid, pool = pod['metadata']['uid'], pod['metadata']['labels']['p10.pool']
    endpoints = {e['targetRef']['uid'] for s in slices for e in s.get('endpoints', []) if e.get('conditions', {}).get('ready') and e.get('targetRef', {}).get('kind') == 'Pod'}
    require(service['metadata']['name'] == 'ext-authz-' + pool, 'Service/pool mismatch')
    return {'uid': uid, 'pool': pool, 'sidecar_id': statuses['istio-proxy']['containerID'], 'image_id': statuses['app']['imageID'],
            'capacity': v['max_requests'], 'hold_ms': hold,
            'mapping_sha256': digest({'cluster': cluster['name'], 'alt': cluster['altStatName'], 'circuit_breakers': cluster['circuitBreakers'], 'port': 8080}),
            'resources_sha256': digest({n: containers[n].get('resources') for n in ('app', 'istio-proxy')}),
            'service': service['metadata']['name'], 'service_uid': service['metadata']['uid'],
            'endpoint_pod_uid': uid if uid in endpoints else None, 'endpoints': sorted(endpoints),
            'prefixes': ['cluster.' + n + '.' for n in (cluster['name'], cluster['altStatName']) if n]}


def identify(arm, v):
    expected = {'shared': 2} if arm == 'shared' else {'critical': 1, 'bulk': 1}
    pods = pool_pods(2)
    require({p: sum(x['metadata']['labels']['p10.pool'] == p for x in pods) for p in expected} == expected, 'actual pool topology')
    targets = []
    for pod in sorted(pods, key=lambda p: p['metadata']['uid']):
        name, pool = pod['metadata']['name'], pod['metadata']['labels']['p10.pool']
        deadline = time.monotonic() + 120
        while True:   # the effective inbound capacity must reach this sidecar before anything is measured
            try:
                clusters = gate.proxy_config(name, 'clusters')
                gate.target_cluster(clusters, v['max_requests'])
                hold = int(gate.kube('-n', NS, 'exec', name, '-c', 'app', '--', 'cat', '/config/hold-ms'))
                if hold == v['hold_ms']: break
            except (ValueError, subprocess.SubprocessError):
                pass
            require(time.monotonic() < deadline, 'effective inbound capacity/hold did not converge')
            time.sleep(1)
        service = kj('-n', NS, 'get', 'service', 'ext-authz-' + pool, '-o', 'json')
        slices = kj('-n', NS, 'get', 'endpointslices', '-l', 'kubernetes.io/service-name=ext-authz-' + pool, '-o', 'json')['items']
        target = target_identity(pod, v, service, slices, clusters, hold)
        pool_uids = sorted(p['metadata']['uid'] for p in pods if p['metadata']['labels']['p10.pool'] == pool)
        require(target['endpoints'] == pool_uids and target['endpoint_pod_uid'] == target['uid'], 'Service endpoint set differs from pool Pods')
        target['name'] = name
        targets.append(target)
    return targets


def runtime_invariants(v, targets, stable, info, haproxy_image):
    ingress = gate.pod('istio=p4-ingress')['metadata']['name']
    filters = local.effective_check(gate.proxy_config(ingress, 'listeners'))
    routes = [r for c in gate.proxy_config(ingress, 'routes') for h in c.get('virtualHosts', []) for r in h.get('routes', [])
              if r.get('route', {}).get('cluster') == 'outbound|3000||forgejo-http.forgejo.svc.cluster.local']
    require(routes and all(r['route'].get('retryPolicy', {}).get('numRetries', 0) == 0 for r in routes), 'Forgejo ingress route absent or retries enabled')
    require(len({t['resources_sha256'] for t in targets}) == 1 and len({t['mapping_sha256'] for t in targets}) == 1, 'targets differ')
    return {'stable_revision': digest(stable), 'ingress_config_sha256': digest(filters),
            'native_route_sha256': digest({'cluster': routes[0]['route']['cluster'], 'num_retries': 0}),
            'tls_auth_sha256': digest({'tls': m.LOCAL_TLS, 'native_auth': 'forgejo-pat', 'ext_authz': 'CUSTOM'}),
            'target_resources_sha256': targets[0]['resources_sha256'], 'haproxy_image_id': haproxy_image,
            'haproxy_processes': info['Nbproc'], 'haproxy_threads': info['Nbthread'], 'haproxy_maxconn': info['Maxconn'],
            'proxy_retries_sha256': digest({'haproxy': 'retries 0', 'route_num_retries': 0}),
            'sentinel_sha256': digest({'direct_port': DIRECT, 'seconds': SENTINEL_SECONDS, 'plan': v['duration_seconds']}),
            'confounder_policy_sha256': digest(GUARD_POLICY)}


# --- HAProxy / logs ------------------------------------------------------------------------------------

def haproxy_pod():
    pod = gate.pod('app=haproxy')
    return pod['metadata']['name'], next(c['imageID'] for c in pod['status']['containerStatuses'] if c['name'] == 'haproxy')


def haproxy_snapshot():
    name, _ = haproxy_pod()
    def run(*command): return gate.kube('-n', NS, 'exec', name, '-c', 'haproxy', '--', *command)
    return {'ring': m.parse_ring(run('sh', '-c', 'echo "show events p10" | nc -w 2 127.0.0.1 8405')),
            'info': m.parse_haproxy_info(run('sh', '-c', 'echo "show info" | nc -w 2 127.0.0.1 8405')),
            'stats': m.parse_haproxy_stats(run('wget', '-qO-', 'http://127.0.0.1:8404/stats;csv'))}


def proxy_rows(pod):
    rows = []
    for line in gate.kube('-n', NS, 'logs', pod, '-c', 'istio-proxy').splitlines():
        if not line.startswith('{'): continue
        row = json.loads(line)
        if row.get('record') == 'proxy_request':
            require(set(row) == {'record', 'status', 'details', 'upstream_cluster', 'upstream_host'}, 'unsafe proxy log')
            rows.append({'status': int(row['status']), 'details': row['details']})
    return rows


def log_counts(targets, ingress):
    app = {}
    for t in targets:
        rows = [json.loads(line) for line in gate.kube('-n', NS, 'logs', t['name'], '-c', 'app').splitlines()]
        if rows: gate.validate_checks(rows)
        app[t['uid']] = rows
    return {'ingress': proxy_rows(ingress), 'target': {t['uid']: proxy_rows(t['name']) for t in targets}, 'app': app}


def observation(targets, before, after, logs_before, logs_after, client_requests):
    return {'ring_before': before['ring'], 'ring_after': after['ring'], 'stats_before': before['stats'], 'stats_after': after['stats'],
            'info_before': before['info'], 'info_after': after['info'], 'client_requests': client_requests,
            'targets': [{'uid': t['uid'], 'pool': t['pool']} for t in targets],
            'ingress_rows': logs_after['ingress'][len(logs_before['ingress']):],
            'target_rows': {t['uid']: logs_after['target'][t['uid']][len(logs_before['target'][t['uid']]):] for t in targets},
            'app_checks': {t['uid']: logs_after['app'][t['uid']][len(logs_before['app'][t['uid']]):] for t in targets}}


def expected_log_counts(ring_rows):
    checks = [r for r in ring_rows if not m.no_request(r)]   # a connection without a request never reached ingress/target
    answered = [r for r in checks if r['termination'] == '--' and r['status'] in {200, 503}]
    return {'ingress': len(checks), 'target': len(answered), 'app': sum(r['status'] == 200 for r in answered)}


def log_deltas(targets, before, after):
    return {'ingress': len(after['ingress']) - len(before['ingress']),
            'target': sum(len(after['target'][t['uid']]) - len(before['target'][t['uid']]) for t in targets),
            'app': sum(len(after['app'][t['uid']]) - len(before['app'][t['uid']]) for t in targets)}


def wait_gone(selector, timeout):
    """Pod garbage collection is asynchronous: an object delete returning is not Pods gone."""
    deadline = time.monotonic() + timeout
    while kj('-n', NS, 'get', 'pods', '-l', selector, '-o', 'json')['items']:
        require(time.monotonic() < deadline, 'Pods did not terminate: ' + selector)
        time.sleep(1)


def stop_forward(process, log):
    process.terminate()
    try: process.wait(timeout=10)
    except subprocess.TimeoutExpired: process.kill()
    log.close()
    Path(log.name).unlink(missing_ok=True)


# --- one arm ---------------------------------------------------------------------------------------------

class Run:
    def __init__(self, out, source, fixture, v, base, identity, health):
        self.out, self.source, self.f, self.v, self.base, self.identity, self.health = out, source, fixture, v, base, identity, health
        self.client = Client(fixture, os.environ['DEV_TOKEN'], os.environ['MAIN_SHA'], os.environ['ISSUE_TITLE'])
        self.auth = {'Authorization': 'token ' + os.environ['DEV_TOKEN']}
        self.expected = (fixture['issue'], os.environ['ISSUE_TITLE'])
        self.issue_uri = m.routes(fixture)['critical'][0][1]
        # Exact rendered inventories this run created or may have partly created. Registered before the first apply
        # and released only after their absence is read back, so no failure point can orphan a pool object.
        self.owned = []

    def checkpoint(self, phase, **safe):
        with (self.out / 'checkpoints.jsonl').open('a') as stream:
            stream.write(json.dumps({'phase': phase, 'monotonic': time.monotonic(), **safe}) + '\n')
        print('[p10-pair] ' + phase, flush=True)

    def sentinel(self):
        return {'read': sat.request(DIRECT, self.issue_uri, self.auth, self.expected), 'health': sat.request(DIRECT, '/api/healthz', {})}

    def setup(self, arm):
        """Admit the arm's pools (after the previous topology is gone), then its HAProxy backend selection."""
        rendered = m.local_render(self.identity, self.v, self.f, arm, self.base['template'])
        self.owned.append(rendered['pools.json']['items'])   # before any mutation: a partial apply is still owned
        gate.kube('-n', NS, 'patch', 'configmap', 'ext-authz-hold', '--type=merge', '-p', json.dumps({'data': {'hold-ms': str(self.v['hold_ms'])}}))
        apply_list(rendered['pools.json']['items'])
        for item in rendered['pools.json']['items']:
            if item['kind'] == 'Deployment':
                rollout('deployment/' + item['metadata']['name'], 240)
        self.checkpoint('pools-admitted', arm=arm)
        # HAProxy resolves the backend Services at start, so it is restarted only after they exist.
        local.apply(rendered['haproxy.cfg'], self.checkpoint)
        targets = identify(arm, self.v)
        self.checkpoint('mapping', arm=arm, pools=sorted({t['pool'] for t in targets}), pods=len(targets))
        return targets

    def warm_up(self, targets, fetch):
        """Not measured: prove routing and native auth through the arm, then materialize every target's stats.

        A new sidecar exposes its inbound stats only after its first request and the Service picks a Pod at random,
        so the pass repeats (bounded) until every Pod has them. Strict stat parsing starts only after that.
        """
        deadline = time.monotonic() + 90
        passes = 0
        while True:
            passes += 1
            issue, anonymous = self.client.critical('warmup-critical', passes), self.client.critical('warmup-critical-anonymous', passes, True)
            routed = issue['status'] == 200 and self.client.issue_matches(issue['body']) and anonymous['status'] == 404 and \
                self.client.bulk('warmup-bulk', passes)['semantic_result']
            if routed:
                try:
                    for t in targets: fetch(t)
                    return {'authenticated_issue': 200, 'anonymous_issue': 404, 'git_read': 200, 'passes': passes}
                except (OSError, http.client.HTTPException, ValueError):
                    pass
            require(time.monotonic() < deadline, 'warm-up through the arm did not succeed')
            time.sleep(1)

    def measure(self, arm, targets):
        v, errors = self.v, []
        directory = self.out / arm
        directory.mkdir()
        stop = threading.Event()
        ports = dict(zip([t['uid'] for t in targets], ADMIN_PORTS))
        live = {t['uid']: {'ready': True, 'restarts': 0} for t in targets}
        events, sentinels, snapshots, forwards, threads = [], [], [], [], []
        target_uids = {t['uid'] for t in targets}
        def guarded(action):
            def body():
                try: action()
                except Exception as exc: errors.append(type(exc).__name__)
            return body
        try:
            for t in targets:
                log = open(ROOT / '.tmp' / f'p10-admin-{ports[t["uid"]]}.log', 'w')
                forwards.append((subprocess.Popen(['kubectl', '-n', NS, 'port-forward', '--address', '127.0.0.1', 'pod/' + t['name'],
                                                   f'{ports[t["uid"]]}:15000'], stdout=log, stderr=log), log))
            fetch = AdminFetch(ports, stat_path(targets[0]['prefixes']))
            sampler = Sampler(targets, v['sample_seconds'], fetch, lambda: live)
            deadline = time.monotonic() + 30
            while True:
                try:
                    if all(fetch.ready(t) for t in targets): break
                except (OSError, http.client.HTTPException, ValueError):
                    pass
                require(time.monotonic() < deadline and all(p.poll() is None for p, _ in forwards), 'target admin unavailable')
                time.sleep(.2)
            warm = self.warm_up(targets, fetch)
            self.checkpoint('warm-up', arm=arm, **warm)
            ingress = gate.pod('istio=p4-ingress')['metadata']['name']
            _, haproxy_image = haproxy_pod()
            stable = stable_snapshot()
            early = haproxy_snapshot()
            invariants = runtime_invariants(v, targets, stable, early['info'], haproxy_image)
            binding = m.binding(self.identity, v, self.f, invariants, 'local', self.base['template'])
            def monitor_guards():
                while not stop.is_set():
                    begin = time.monotonic(); snapshot = guard_snapshot(target_uids)
                    snapshots.append({'begin': begin, 'end': time.monotonic(), 'snapshot': snapshot})
                    for key, pod in snapshot['pods'].items():
                        if key.startswith('target-'):
                            live[key[len('target-'):]] = {'ready': pod['ready'], 'restarts': sum(c['restarts'] for c in pod['containers'])}
                    stop.wait(GUARD_SECONDS)
            def monitor_sentinel():
                while not stop.is_set():
                    sentinels.append(self.sentinel())
                    stop.wait(SENTINEL_SECONDS)
            threads = [threading.Thread(target=guarded(f), daemon=True) for f in (lambda: sampler.run(stop), monitor_guards, monitor_sentinel)]
            for thread in threads: thread.start()
            deadline = time.monotonic() + 60
            while not (len(sampler.rows) >= 4 and snapshots and sentinels):
                require(time.monotonic() < deadline and not errors, 'monitors did not start before the window')
                time.sleep(.1)
            # Idle boundary: no demand between these snapshots and the first arrival.
            before = haproxy_snapshot()
            logs_before = log_counts(targets, ingress)
            requests_before = dict(self.client.counts)
            before_at = time.monotonic()
            self.checkpoint('window-start', arm=arm)
            origin = m.drive(v, self.client.probes(), events.append)
            self.checkpoint('window-end', arm=arm)
            completed = max(e['completed'] for e in events if e['record'] == 'operation')
            coverage_end = max(completed, origin + v['duration_seconds'])
            deadline = time.monotonic() + v['drain_seconds']
            while sampler.rows[-1]['at'] < completed + 2 * v['sample_seconds'] or any(
                    t['stats']['upstream_rq_active'] for r in sampler.rows[-2:] for t in r['targets']):
                require(time.monotonic() < deadline, 'targets did not drain')
                time.sleep(.1)
            after = haproxy_snapshot()
            demand = {k: self.client.counts[k] - requests_before[k] for k in m.CLASSES}
            expected = expected_log_counts(after['ring'][len(before['ring']):])
            deadline = time.monotonic() + 30   # asynchronous access-log flush: bounded wait, counted against HAProxy
            while True:
                logs_after = log_counts(targets, ingress)
                got = log_deltas(targets, logs_before, logs_after)
                if got == expected or time.monotonic() > deadline: break
                time.sleep(1)
            after_at = time.monotonic()
            sentinels.append(self.sentinel())
            begin = time.monotonic(); final = guard_snapshot(target_uids)
            snapshots.append({'begin': begin, 'end': time.monotonic(), 'snapshot': final})
        finally:
            stop.set()
            for thread in threads: thread.join(timeout=30)
            for process, log in forwards: stop_forward(process, log)
        require(not errors, 'monitor thread failed: ' + ','.join(sorted(set(errors))))
        after_invariants = runtime_invariants(v, targets, stable_snapshot(), after['info'], haproxy_image)
        obs = observation(targets, before, after, logs_before, logs_after, demand)
        try:
            evidence = m.window_accounting(arm, obs)
        except ValueError:
            m.save(directory / 'accounting-failure.json', {'expected_log_counts': expected, 'log_deltas': got, 'client_requests': demand,
                                                          'observation': obs})
            raise
        native_auth = self.health['forgejo_native_auth'] is True and warm['anonymous_issue'] == 404
        clean = evidence['queue_end'] == evidence['haproxy_retries'] == evidence['dropped_logs'] == evidence['classifier_escapes'] == 0 and \
            evidence['counter_lifetime_unchanged'] and all(c['queue'] == c['other'] == 0 for c in evidence['classes'].values())
        facts = {'haproxy': {k: evidence[k] for k in ('queue_end', 'haproxy_retries', 'dropped_logs', 'classifier_escapes', 'no_request_connections',
                                                      'counter_lifetime_unchanged')},
                 'native_auth': native_auth, 'ingress': {'rows': len(obs['ingress_rows'])}, 'span': (before_at, after_at)}
        guards = guards_from(snapshots, (origin, coverage_end), sentinels, clean, facts)
        run = {'plan': v, 'arm': arm, 'source_sha': self.source['sha'], 'binding': binding, 'binding_sha256': digest(binding),
               'runtime_before': invariants, 'runtime_after': after_invariants, 'events': events, 'samples': sampler.rows,
               'environment': 'local', 'healthy_classification': self.health['classification'] == 'healthy-path-verified',
               'tls': m.LOCAL_TLS, 'native_auth': native_auth, 'guards': guards, 'accounting': evidence,
               'observation': {'sampler_failures': sampler.failures, 'sentinels': sentinels, 'guard_snapshots': snapshots,
                               'ring_window': obs['ring_after'][len(obs['ring_before']):], 'log_deltas': got, 'warm_up': warm,
                               'targets': [{k: x for k, x in t.items() if k != 'prefixes'} for t in targets]}}
        m.save(directory / 'run.json', run)
        self.checkpoint('raw-saved', arm=arm, operations=sum(e['record'] == 'operation' for e in events), samples=len(sampler.rows))
        return run

    def remove_owned(self):
        """Delete the exact owned inventory (absent objects are fine) and release ownership only once it reads back absent."""
        errors = []
        for items in self.owned:
            try: delete_list(items)
            except Exception as exc: errors.append(type(exc).__name__)
        require(not errors, 'owned pool objects not deleted: ' + ','.join(sorted(set(errors))))
        wait_gone('app=ext-authz-pool', 180)
        remaining = [name for items in self.owned for name in present(items)]
        require(not remaining, 'owned pool objects remain: ' + ','.join(remaining))
        self.owned.clear()

    def restore(self):
        """Remove the owned pools, restore HAProxy/hold/original target, and prove the original state is back."""
        problems, state, base = [], {}, self.base
        def step(name, action):
            try: action()
            except Exception as exc: problems.append(name + ':' + type(exc).__name__)
        step('pools', self.remove_owned)
        step('haproxy', lambda: local.apply(base['haproxy_config'], self.checkpoint))
        step('hold', lambda: gate.kube('-n', NS, 'patch', 'configmap', 'ext-authz-hold', '--type=merge', '-p', json.dumps({'data': {'hold-ms': base['hold_ms']}})))
        step('target', lambda: (gate.kube('-n', NS, 'scale', 'deployment/ext-authz-sim', f'--replicas={base["replicas"]}'),
                                rollout('deployment/ext-authz-sim', 180)))
        def verify():
            state['p10_resources'] = [i['metadata']['name'] for kind in ('deployments', 'services', 'sidecars.networking.istio.io') for i in
                                       kj('-n', NS, 'get', kind, '-l', 'p10.pair=owned', '-o', 'json')['items']]
            state['pool_pods'] = len(kj('-n', NS, 'get', 'pods', '-l', 'app=ext-authz-pool', '-o', 'json')['items'])
            state['owned_pending'] = sum(len(items) for items in self.owned)
            state['haproxy_restored'] = kj('-n', NS, 'get', 'configmap/haproxy', '-o', 'json')['data']['haproxy.cfg'] == base['haproxy_config']
            state['hold_restored'] = kj('-n', NS, 'get', 'configmap/ext-authz-hold', '-o', 'json')['data']['hold-ms'] == base['hold_ms']
            deployment = kj('-n', NS, 'get', 'deployment/ext-authz-sim', '-o', 'json')
            state['target_replicas_restored'] = deployment['spec']['replicas'] == base['replicas'] == deployment['status'].get('readyReplicas', 0)
            state['stable_forgejo_unchanged'] = stable_snapshot() == base['stable']
        step('verify', verify)
        restored = not problems and not state.get('p10_resources') and state.get('pool_pods') == 0 and state.get('owned_pending') == 0 and all(
            state.get(k) is True for k in ('haproxy_restored', 'hold_restored', 'target_replicas_restored', 'stable_forgejo_unchanged'))
        return {'restored': restored, 'problems': problems, **state}


def summarize(validated):
    keys = ('logical_operations', 'attempts', 'success', 'good', 'good_fraction', 'max_seconds')
    return {'status': validated['status'], 'arm': validated['arm'], 'saturation_fraction': validated['saturation_fraction'],
            'critical': {k: validated['clients']['critical'][k] for k in keys}, 'bulk': {k: validated['clients']['bulk'][k] for k in keys},
            'accounting': validated['accounting']}


def run_pair(out_root):
    out_root = Path(out_root)
    directory = out_root / 'p10-pair'
    directory.mkdir()
    gate.owned_image_node()   # exact invocation-owned local cluster, never the current context alone
    source = json.loads((out_root / 'source.json').read_text())
    health = json.loads((out_root / 'p10-healthy.json').read_text())
    require(health['source_sha'] == source['sha'] and health.get('experiment_haproxy_restored') is True and
            health['classification'] == 'healthy-path-verified' and health['forgejo_native_auth'] is True, 'healthy classifier/native-auth gate')
    v = m.plan(m.load(ROOT / 'experiments/fixtures/critical-bulk/candidate.json'))
    fixture = m.fixture({'owner': os.environ['DEV_USER'], 'repo': 'journey', 'issue': int(os.environ['ISSUE_NUMBER'])})
    base = baseline()
    identity = {'source_sha': source['sha'], 'cluster_uid': Path(os.environ['LOCAL_CLUSTER_OWNERSHIP_MARKER']).read_text().strip(),
                'stable_revision': digest(base['stable']), 'ext_authz_image_id': json.loads((out_root / 'app-image.json').read_text())['config_digest']}
    m.local_identity(identity)
    inventory = [m.local_render(identity, v, fixture, arm, base['template'])['pools.json']['items'] for arm in m.ARMS]
    require('ext-authz-sim.' + NS in base['haproxy_config'] and base['replicas'] >= 1 and not left_over(inventory), 'fixture is not in the expected pre-P10 state')
    run = Run(directory, source, fixture, v, base, identity, health)
    m.save(directory / 'baseline.json', {'hold_ms': base['hold_ms'], 'replicas': base['replicas'], 'haproxy_config_sha256': digest(base['haproxy_config']),
                                          'stable_sha256': digest(base['stable']), 'template': base['template'], 'plan': v, 'source': source})
    run.checkpoint('baseline')
    runs, failure = {}, None
    try:
        gate.kube('-n', NS, 'scale', 'deployment/ext-authz-sim', '--replicas=0')
        wait_gone('app=ext-authz-sim', 180)
        for arm in m.ARMS:
            if run.owned:   # nothing from the transition is measured: remove the previous pools, then admit the new ones
                run.remove_owned()
            targets = run.setup(arm)
            runs[arm] = run.measure(arm, targets)
            try:
                summary = summarize(m.validate(runs[arm]))
            except ValueError as exc:
                summary = {'status': 'invalid', 'arm': arm, 'reason': str(exc)}
            m.save(directory / arm / 'summary.json', summary)
            run.checkpoint('arm-validated', arm=arm, status=summary['status'])
    except Exception as exc:
        failure = {'phase': 'run', 'class': type(exc).__name__, 'message': str(exc) if isinstance(exc, ValueError) and len(str(exc)) < 200 else None}
        m.save(directory / 'failure.json', failure)
        run.checkpoint('failed', error=failure['class'], message=failure['message'])
    finally:
        # Also for BaseException (interrupt, cancellation): the owned inventory is removed whatever stopped the run.
        restoration = run.restore()
        m.save(directory / 'restoration.json', restoration)
        run.checkpoint('restored', restored=restoration['restored'])
    if failure or not restoration['restored']:
        return 1
    return finish(directory, runs, source)


def finish(directory, runs, source):
    result = m.compare(runs['shared'], runs['isolated'])
    result = {**result, 'source_sha': source['sha'], 'source_dirty': source['dirty'], 'completed': True, 'limitations': LIMITATIONS,
              'arms': [summarize(r) for r in result['arms']]}
    m.save(directory / 'result.json', result)
    print('[p10-pair] result ' + json.dumps({k: result[k] for k in ('status', 'bulk_saturation', 'shared_critical_degradation',
                                                                     'isolated_critical_protection') if k in result}), flush=True)
    return 0 if result['status'] in {'positive', 'valid-negative'} else 1


def verify(out_root):
    """Re-validate the saved raw pair independently of the run that produced it."""
    directory = Path(out_root) / 'p10-pair'
    runs = {a: m.load(directory / a / 'run.json') for a in m.ARMS}
    source = m.load(Path(out_root) / 'source.json')
    saved, again = m.load(directory / 'result.json'), m.compare(runs['shared'], runs['isolated'])
    restoration = m.load(directory / 'restoration.json')
    require(restoration['restored'] is True and saved['completed'] is True and saved['source_sha'] == source['sha'] and
            all(r['source_sha'] == source['sha'] for r in runs.values()) and saved['status'] == again['status'] and
            saved['status'] in {'positive', 'valid-negative'}, 'saved pair differs from re-validation or was not restored')
    print(json.dumps({'status': again['status'], 'source_sha': source['sha'], 'source_dirty': source['dirty'], 'restored': True}))


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'run': sys.exit(run_pair(sys.argv[2]))
        elif sys.argv[1] == 'result': verify(sys.argv[2])
        else: raise ValueError('unknown mode')
    except Exception as exc:
        tb = exc.__traceback__
        while tb and tb.tb_next: tb = tb.tb_next
        where = f'{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}' if tb else 'unknown'
        reason = str(exc) if isinstance(exc, ValueError) and len(str(exc)) < 200 and '\n' not in str(exc) else 'raw exception suppressed'
        print(f'P10 local pair failed: {type(exc).__name__} at {where}: {reason}', file=sys.stderr)
        sys.exit(1)
