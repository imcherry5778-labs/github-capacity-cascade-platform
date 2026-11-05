#!/usr/bin/env python3
"""P10 offline renderer, bounded operation driver and evidence validator.

No Azure credentials, apply, IAM, provisioning or paid execution entrypoint.
Transport/observation callbacks are supplied by the owned local harness. Unknown
or incomplete evidence never becomes a positive or valid negative result.
"""
import bisect
import concurrent.futures
import copy
import csv
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import sys
import threading
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('p10_p8', ROOT / 'scripts/azure-cascade.py')
p8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p8)
require, digest, load, save = p8.require, p8.digest, p8.load, p8.save
ARMS = ('shared', 'isolated')
CLASSES = ('critical', 'bulk')
GUARDS = {'haproxy', 'forgejo', 'forgejo_sidecar', 'postgres', 'node', 'scheduling', 'sentinel', 'tls_native_auth', 'ingress'}
COUNTERS = ('upstream_rq_total', 'upstream_rq_active_overflow', 'upstream_rq_pending_overflow')
STATS = set(COUNTERS) | {'upstream_rq_active', 'upstream_rq_pending_active'}
# Local drive/sampling happens inside one harness process and one monotonic clock. A managed
# (Prometheus) sample is stamped by another host's wall clock; its alignment allowance is a
# data-validity bound, not a conclusion threshold.
MANAGED_CLOCK_TOLERANCE = 2.0
MANAGED_CLOCK_DRIFT = 0.5
LOCAL_TLS = 'local-http-not-applicable'


def fixture(v):
    require(set(v) == {'owner', 'repo', 'issue'}, 'fixture fields')
    require(all(isinstance(v[k], str) and re.fullmatch('[a-z][a-z0-9-]{0,39}', v[k]) for k in ('owner', 'repo')), 'bounded canonical fixture names')
    require(type(v['issue']) is int and 1 <= v['issue'] <= 1000000, 'exact fixture issue')
    return v


def routes(f):
    fixture(f)
    base = '/' + f['owner'] + '/' + f['repo']
    return {'critical': [('GET', '/api/v1/repos' + base + '/issues/' + str(f['issue']))],
            'bulk': [('GET', base + '.git/info/refs?service=git-upload-pack'), ('POST', base + '.git/git-upload-pack')]}


def classify(method, uri, f):
    # Exact raw HAProxy request-target, including query. No decoding, case folding,
    # path-prefix match, trusted identity, correlation or client priority input.
    for kind, pairs in routes(f).items():
        if (method, uri) in pairs:
            return kind
    return 'deny'


def plan(v):
    expected = {'duration_seconds', 'critical_interval_seconds', 'bulk_interval_seconds', 'critical_workers', 'bulk_workers',
                'max_attempts', 'max_requests', 'hold_ms', 'sample_seconds', 'scrape_seconds', 'ingestion_seconds',
                'drain_seconds', 'max_driver_lag_seconds', 'critical_deadline_seconds', 'protection_fraction',
                'degradation_fraction', 'saturation_fraction'}
    require(set(v) == expected, 'P10 plan fields')
    require(all(type(x) in {int, float} and math.isfinite(x) for x in v.values()), 'finite numeric plan')
    require(type(v['duration_seconds']) is int and 10 <= v['duration_seconds'] <= 300, 'bounded duration')
    require(0.05 <= v['sample_seconds'] <= 1 and 1 <= v['scrape_seconds'] <= 30 and 0 <= v['ingestion_seconds'] <= 60, 'observation cadence')
    require(0.1 <= v['bulk_interval_seconds'] <= 2 and 1 <= v['critical_interval_seconds'] <= 5, 'bounded arrivals')
    require(all(type(v[k]) is int and 1 <= v[k] <= n for k, n in [('critical_workers', 4), ('bulk_workers', 24), ('max_attempts', 2), ('max_requests', 4), ('hold_ms', 2000)]), 'bounded concurrency/retry/fault')
    require(5 <= v['drain_seconds'] <= 30 and .05 <= v['max_driver_lag_seconds'] <= .5 and
            .1 <= v['critical_deadline_seconds'] <= 3, 'timing bounds')
    require(.9 <= v['protection_fraction'] <= 1 and .05 <= v['degradation_fraction'] <= .5 and
            .25 <= v['saturation_fraction'] <= 1, 'frozen conclusion thresholds')
    return v


def schedule(v):
    plan(v)
    return sorted([{'id': f'{kind}-{i}', 'kind': kind, 'at': round(i * v[kind + '_interval_seconds'], 9)}
                   for kind in CLASSES for i in range(math.ceil(v['duration_seconds'] / v[kind + '_interval_seconds']))],
                  key=lambda x: (x['at'], x['kind']))


def haproxy(f, arm, namespace=p8.NS):
    require(arm in ARMS, 'unknown arm')
    pairs = routes(f)
    lines = ['global', '  nbthread 1', '  maxconn 256', '  log ring@p10 format raw local0',
             '  stats socket ipv4@127.0.0.1:8405 level operator',
             'ring p10', '  format raw', '  size 16777216', '  maxlen 768',
             'defaults', '  mode http', '  log global', '  retries 0', '  timeout connect 250ms',
             '  timeout client 4s', '  timeout server 3s', '  timeout queue 250ms',
             '  log-format "{\\"status\\":%ST,\\"termination\\":\\"%ts\\",\\"class\\":\\"%[var(txn.p10_class)]\\",\\"backend\\":\\"%b\\",\\"server\\":\\"%s\\",\\"request_counter\\":%rt,\\"pid\\":%pid,\\"accept_time\\":\\"%Ts.%ms\\",\\"queue_ms\\":%Tw,\\"connect_ms\\":%Tc,\\"response_ms\\":%Tr,\\"total_ms\\":%Ta}"',
             'frontend check', '  bind :8080', '  option httpclose',
             '  http-request set-var(txn.p10_class) str(deny)',
             '  http-request del-header x-priority', '  http-request del-header x-traffic-class',
             '  http-request del-header x-p10-class', '  http-request set-header x-shared-gate-hop haproxy']
    for kind, matches in pairs.items():
        for i, (method, uri) in enumerate(matches):
            name = kind + str(i)
            lines += [f'  acl {name}_method method {method}', f'  acl {name}_uri url -m str {uri}',
                      f'  http-request set-var(txn.p10_class) str({kind}) if {name}_method {name}_uri']
    lines += ['  http-request deny deny_status 403 if { var(txn.p10_class) -m str deny }']
    for kind in CLASSES:
        pool = 'shared' if arm == 'shared' else kind
        lines += [f'  use_backend {pool} if {{ var(txn.p10_class) -m str {kind} }}']
    for pool in (('shared',) if arm == 'shared' else CLASSES):
        # One shared two-endpoint Service vs two one-endpoint Services. HAProxy
        # process, frontend, timeouts, limits and retries are identical.
        lines += [f'backend {pool}', f'  server pool ext-authz-{pool}.{namespace}.svc.cluster.local:8080']
    lines += ['listen local_stats', '  bind 127.0.0.1:8404', '  no log', '  stats enable', '  stats uri /stats']
    return '\n'.join(lines) + '\n'


def render(identity, v, f, arm):
    p8.identity(identity); plan(v); fixture(f)
    result = p8.render(identity)
    items = result['fixtures.json']['items']
    items[:] = [o for o in items if o['kind'] not in {'HorizontalPodAutoscaler', 'Sidecar'} and
                not (o['kind'] in {'Deployment', 'Service'} and o['metadata']['name'] == 'ext-authz-sim')]
    original = next(o for o in p8.render(identity)['fixtures.json']['items'] if o['kind'] == 'Deployment' and o['metadata']['name'] == 'ext-authz-sim')
    for pool in (('shared',) if arm == 'shared' else CLASSES):
        name = 'ext-authz-' + pool
        deployment = copy.deepcopy(original)
        deployment['metadata']['name'] = name
        deployment['spec']['replicas'] = 2 if pool == 'shared' else 1
        labels = {'app': 'ext-authz-sim', 'p10.pool': pool}
        deployment['spec']['selector']['matchLabels'] = labels
        deployment['spec']['template']['metadata']['labels'].update(labels)
        items.append(deployment)
        metadata = copy.deepcopy(deployment['metadata'])
        items += [dict(apiVersion='v1', kind='Service', metadata=metadata, spec={'selector': labels,
                         'ports': [{'name': 'http-check', 'port': 8080, 'targetPort': 8080}]})]
    items += [dict(apiVersion='networking.istio.io/v1', kind='Sidecar',
                   metadata={'name': 'p10-capacity', 'namespace': p8.NS, 'labels': {'p8.campaign': identity['campaign']}},
                   spec={'workloadSelector': {'labels': {'app': 'ext-authz-sim'}},
                         'inboundConnectionPool': {'http': {'http2MaxRequests': v['max_requests']}}})]
    next(o for o in items if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'ext-authz-hold')['data']['hold-ms'] = str(v['hold_ms'])
    next(o for o in items if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'haproxy')['data']['haproxy.cfg'] = haproxy(f, arm)
    hp = next(o for o in items if o['kind'] == 'Deployment' and o['metadata']['name'] == 'haproxy')
    hp['spec']['template']['spec']['containers'][0]['readinessProbe'] = {
        'exec': {'command': ['wget', '-q', '-O', '/dev/null', 'http://127.0.0.1:8404/stats']}}
    # Existing managed scraper; no collector/controller or extra Service.
    items.append(dict(apiVersion='azmonitoring.coreos.com/v1', kind='PodMonitor',
        metadata={'name': 'p10-envoy', 'namespace': p8.NS, 'labels': {'p8.campaign': identity['campaign']}},
        spec={'selector': {'matchLabels': {'app': 'ext-authz-sim'}}, 'podMetricsEndpoints': [{
            'port': 'http-envoy-prom', 'path': '/stats/prometheus', 'interval': str(v['scrape_seconds']) + 's',
            'relabelings': [{'targetLabel': 'job', 'replacement': 'p10-envoy'}],
            'metricRelabelings': [{'sourceLabels': ['__name__'],
                'regex': 'envoy_cluster_upstream_rq_(active_overflow|active|total|pending_active|pending_overflow)', 'action': 'keep'}]}]}))
    # The existing single provider/mesh overlay and original native/TLS route are
    # reused without adding an extension provider or stable resource.
    return result


def local_identity(value):
    # The invocation-owned disposable cluster: its k3d server container ID is the ownership marker.
    require(type(value) is dict and set(value) == {'source_sha', 'cluster_uid', 'stable_revision', 'ext_authz_image_id'} and
            re.fullmatch('[0-9a-f]{40}', value['source_sha']) and re.fullmatch('[0-9a-f]{64}', value['cluster_uid']) and
            re.fullmatch('[0-9a-f]{64}', value['stable_revision']) and
            re.fullmatch('sha256:[0-9a-f]{64}', value['ext_authz_image_id']), 'local identity')
    return value


def local_render(identity, v, f, arm, template, namespace='shared-gate'):
    """Deterministic Local pool manifests derived from the live P4 target pod template.

    Same pod template/image/resources/hold in both arms; only the Deployment/Service split and
    the HAProxy backend selection differ. No HPA/KEDA/controller/node/PVC and no stable resource.
    """
    local_identity(identity); plan(v); fixture(f); require(arm in ARMS and type(template) is dict, 'local render input')
    items = []
    for pool in (('shared',) if arm == 'shared' else CLASSES):
        labels = {'app': 'ext-authz-pool', 'p10.pool': pool}
        pod = copy.deepcopy(template)
        pod['metadata'] = {'labels': dict(labels), 'annotations': dict(template.get('metadata', {}).get('annotations', {}))}
        pod['spec']['terminationGracePeriodSeconds'] = 2   # a pool only ever terminates after its demand drained
        meta = {'name': 'ext-authz-' + pool, 'namespace': namespace, 'labels': {'p10.pair': 'owned', **labels}}
        items += [dict(apiVersion='apps/v1', kind='Deployment', metadata=copy.deepcopy(meta),
                       spec={'replicas': 2 if pool == 'shared' else 1, 'selector': {'matchLabels': dict(labels)}, 'template': pod}),
                  dict(apiVersion='v1', kind='Service', metadata=copy.deepcopy(meta),
                       spec={'selector': dict(labels), 'ports': [{'name': 'http-check', 'port': 8080, 'targetPort': 8080}]})]
    items.append(dict(apiVersion='networking.istio.io/v1', kind='Sidecar',
                      metadata={'name': 'p10-capacity', 'namespace': namespace, 'labels': {'p10.pair': 'owned'}},
                      spec={'workloadSelector': {'labels': {'app': 'ext-authz-pool'}},
                            'inboundConnectionPool': {'http': {'http2MaxRequests': v['max_requests']}}}))
    return {'pools.json': {'apiVersion': 'v1', 'kind': 'List', 'items': items}, 'haproxy.cfg': haproxy(f, arm, namespace)}


def binding(identity, v, f, invariants, environment='azure', template=None):
    plan(v); fixture(f)
    if environment == 'azure':
        p8.identity(identity)
        def renderer(arm): return render(identity, v, f, arm)
    else:
        require(environment == 'local', 'unknown environment')
        local_identity(identity)
        def renderer(arm): return local_render(identity, v, f, arm, template)
    keys = {'stable_revision', 'ingress_config_sha256', 'native_route_sha256', 'tls_auth_sha256',
            'target_resources_sha256', 'haproxy_image_id', 'haproxy_processes', 'haproxy_threads',
            'haproxy_maxconn', 'proxy_retries_sha256', 'sentinel_sha256', 'confounder_policy_sha256'}
    require(set(invariants) == keys and invariants['stable_revision'] == identity['stable_revision'] and
            invariants['haproxy_processes'] == invariants['haproxy_threads'] == 1 and invariants['haproxy_maxconn'] == 256 and
            all(re.fullmatch('[0-9a-f]{64}', invariants[k]) for k in keys if k.endswith('_sha256')), 'runtime invariant binding')
    result = {'source_sha': identity['source_sha'], 'identity': identity, 'fixture': f,
              'plan_sha256': digest(v), 'schedule_sha256': digest(schedule(v)),
              'render_sha256': {a: digest(renderer(a)) for a in ARMS}, 'invariants': invariants}
    if environment == 'local':
        result['template'] = template
    return result


def drive(v, probes, emit, *, clock=time.monotonic, wait=time.sleep, stopped=lambda: False):
    """Independent deterministic arrivals; distinct client operations/attempts.

    A Git command may produce several checks. Never infer its check count. A
    failed/aborted arrival is retained. Finite workers/backlog and no hidden retry.
    """
    arrivals = schedule(v)
    origin = clock()
    emit({'record': 'schedule', 'origin': origin, 'items': arrivals, 'sha256': digest(arrivals)})
    lock = threading.Lock()
    def record(row):
        with lock:
            emit(row)
    def operation(item, submitted):
        attempts = []
        issued = clock()
        if not stopped() and issued < origin + v['duration_seconds']:
            for index in range(1, v['max_attempts'] + 1):
                started = clock()
                try:
                    result = probes[item['kind']](item['id'], index)
                except Exception:
                    result = {'semantic_result': False, 'status': None, 'error_class': 'driver-error'}
                safe = {k: result[k] for k in ('semantic_result', 'status', 'error_class', 'overload') if k in result}
                attempts.append({'index': index, 'started': started, 'ended': clock(), **safe})
                if result['semantic_result'] or not result.get('overload', False) or stopped():
                    break
        record({'record': 'operation', **item, 'scheduled': origin + item['at'], 'submitted': submitted,
                'issued': issued if attempts else None, 'completed': clock(), 'attempts': attempts})
    with concurrent.futures.ThreadPoolExecutor(max_workers=v['critical_workers']) as critical, \
         concurrent.futures.ThreadPoolExecutor(max_workers=v['bulk_workers']) as bulk:
        futures = []
        for item in arrivals:
            due = origin + item['at']
            if due > clock(): wait(due - clock())
            if stopped() or sum(not f.done() for f in futures) >= 2 * (v['critical_workers'] + v['bulk_workers']):
                record({'record': 'operation', **item, 'scheduled': due, 'submitted': None, 'issued': None,
                        'completed': clock(), 'attempts': []})
            else:
                futures.append((critical if item['kind'] == 'critical' else bulk).submit(operation, item, clock()))
        end = origin + v['duration_seconds']
        if end > clock(): wait(end - clock())
        for future in futures: future.result()
    emit({'record': 'end', 'at': clock(), 'expected_end': end})
    return origin


def client_report(v, events):
    schedules = [r for r in events if r['record'] == 'schedule']
    require(len(schedules) == 1, 'missing/duplicate schedule')
    source = schedules[0]; expected = schedule(v)
    require(source['items'] == expected and source['sha256'] == digest(expected), 'arrival drift')
    operations = [r for r in events if r['record'] == 'operation']
    require(len(operations) == len(expected) and len({r['id'] for r in operations}) == len(expected), 'missing/duplicate operations')
    by_id = {r['id']: r for r in operations}
    result = {}
    for item in expected:
        r = by_id[item['id']]
        require(all(r[k] == item[k] for k in ('kind', 'at')) and r['scheduled'] == source['origin'] + item['at'], 'operation drift')
        require(r['issued'] is not None and r['submitted'] is not None and 1 <= len(r['attempts']) <= v['max_attempts'], 'incomplete/early stopped demand')
        require(r['scheduled'] <= r['submitted'] <= r['issued'] <= r['scheduled'] + v['max_driver_lag_seconds'] and
                r['issued'] < source['origin'] + v['duration_seconds'], 'arrival lag/worker backlog')
        previous = r['issued']
        for index, a in enumerate(r['attempts'], 1):
            require(a['index'] == index and previous <= a['started'] <= a['ended'] <= r['completed'] and
                    type(a['semantic_result']) is bool, 'attempt clock/semantic integrity')
            require(a['error_class'] not in {'transport', 'timeout', 'driver-error'} and a['status'] is not None, 'transport/driver failure')
            if index > 1:
                prior = r['attempts'][index - 2]
                require(prior['semantic_result'] is False and prior.get('overload') is True, 'unbounded/native-auth retry')
            require((a['semantic_result'] and a['status'] == 200 and a['error_class'] == 'none') or
                    (not a['semantic_result'] and a['status'] in {403, 429, 503} and a['error_class'] == 'http_status'),
                    'native auth/semantic response confounder')
            previous = a['ended']
    ends = [r for r in events if r['record'] == 'end']
    end = source['origin'] + v['duration_seconds']
    require(len(ends) == 1 and ends[0]['expected_end'] == end and
            end <= ends[0]['at'] <= end + v['drain_seconds'] and
            max(r['completed'] for r in operations) <= ends[0]['at'], 'early stop/incomplete drain')
    for kind in CLASSES:
        selected = [r for r in operations if r['kind'] == kind]
        latencies = [r['completed'] - r['scheduled'] for r in selected]
        successful = [r for r in selected if r['attempts'][-1]['semantic_result']]
        good = sum(r['attempts'][-1]['semantic_result'] and r['completed'] - r['scheduled'] <= v['critical_deadline_seconds'] for r in selected)
        result[kind] = {'logical_operations': len(selected), 'attempts': sum(len(r['attempts']) for r in selected),
                        'success': len(successful), 'good': good, 'good_fraction': good / len(selected),
                        'latency_seconds': latencies, 'max_seconds': max(latencies)}
    return result, source['origin'], end


def coverage(v, samples, start, end, *, managed=False):
    """Native high-resolution signals establish pool saturation, not minute bins.

    Missing coverage/freshness returns observation-insufficient; structural UID,
    counter reset and accounting failures remain invalid in validate().
    """
    cadence = v['scrape_seconds'] if managed else v['sample_seconds']
    max_age = v['scrape_seconds'] + v['ingestion_seconds'] if managed else 2 * v['sample_seconds']
    # The sampled instants must bracket the window. A native sample was also *received* inside it; a managed
    # sample only becomes visible after ingestion, so its delay is bounded by max_age below, not by the window.
    if not samples or samples[0]['sample_at'] > start or samples[-1]['sample_at'] < end:
        return False
    if not managed and (samples[0]['at'] > start or samples[-1]['at'] < end):
        return False
    return all(0 <= s['at'] - s['sample_at'] <= max_age for s in samples) and all(
        0 < b['sample_at'] - a['sample_at'] <= 2 * cadence for a, b in zip(samples, samples[1:]))


def pool_guard(v, arm, samples, start, end):
    require(samples, 'missing pool observations')
    baseline = samples[0]['targets']
    expected = {'shared': 2} if arm == 'shared' else {'critical': 1, 'bulk': 1}
    require(len(baseline) == 2 and {p: sum(t['pool'] == p for t in baseline) for p in expected} == expected and
            len({t['uid'] for t in baseline}) == 2, 'actual target topology/UID mapping')
    require(len({t['sidecar_id'] for t in baseline}) == 2 and
            len({t['service_uid'] for t in baseline}) == len(expected) and
            all(t['endpoint_pod_uid'] == t['uid'] and t['service'] == 'ext-authz-' + t['pool'] for t in baseline),
            'actual Service endpoint/sidecar mapping')
    identity_keys = ('uid', 'pool', 'sidecar_id', 'image_id', 'capacity', 'hold_ms', 'mapping_sha256',
                     'resources_sha256', 'service', 'service_uid', 'endpoint_pod_uid')
    require(all(t['stats']['upstream_rq_active'] == 0 for t in samples[0]['targets'] + samples[-1]['targets']), 'native boundary inflight')
    initial = {t['uid']: {k: t[k] for k in identity_keys} for t in baseline}
    previous = {}
    for s in samples:
        current = {t['uid']: {k: t[k] for k in identity_keys} for t in s['targets']}
        require(len(s['targets']) == 2 and current == initial, 'pool/UID/sidecar lifetime drift')
        for t in s['targets']:
            require(t['capacity'] == v['max_requests'] and t['hold_ms'] == v['hold_ms'] and
                    t['ready'] is True and t['restarts'] == 0, 'fault/image/resource/lifecycle drift')
            require(t['sidecar_id'] and t['image_id'] and all(re.fullmatch('[0-9a-f]{64}', t[k]) for k in ('mapping_sha256', 'resources_sha256')), 'missing effective inbound binding')
            values = t['stats']
            require(set(values) == STATS and all(type(x) is int and x >= 0 for x in values.values()), 'missing/invalid native stat')
            old = previous.get(t['uid'], values)
            require(all(values[k] >= old[k] for k in COUNTERS), 'counter reset')
            require(values['upstream_rq_pending_overflow'] == 0 and values['upstream_rq_pending_active'] == 0, 'competing pending capacity')
            previous[t['uid']] = values
    def at_cap(s, pool):
        return any(t['pool'] == pool and t['stats']['upstream_rq_active'] >= v['max_requests'] for t in s['targets'])
    # Fraction of elapsed demand-window time, never of sample rows: a row carries no
    # weight of its own, so a burst of extra snapshots only adds near-zero-length
    # intervals. A state change is placed at the midpoint of its sampling interval.
    return {pool: sum(max(0, min(b['sample_at'], end) - max(a['sample_at'], start)) * (at_cap(a, pool) + at_cap(b, pool)) / 2
                      for a, b in zip(samples, samples[1:])) / (end - start) for pool in expected}


def clock_pair(wall=time.time, monotonic=time.monotonic):
    """Bracketed wall/monotonic reference; call at the start and again after the last managed poll."""
    before = wall(); mono = monotonic(); after = wall()
    return {'wall': (before + after) / 2, 'monotonic': mono, 'uncertainty': (after - before) / 2}


def clock_bound(clock):
    """Validate the wall<->monotonic mapping and return the allowance for managed timestamps.

    Only the harness's own wall/monotonic pairs are checked here. Skew between the collector host and the
    harness host is not measured by any clock; it is bounded by managed_guard()'s native counter bracket.
    """
    require(type(clock) is dict and set(clock) == {'start', 'end'}, 'managed clock fields')
    a, b = clock['start'], clock['end']
    for pair in (a, b):
        require(type(pair) is dict and set(pair) == {'wall', 'monotonic', 'uncertainty'} and
                all(type(x) in {int, float} and math.isfinite(x) for x in pair.values()) and 0 <= pair['uncertainty'] <= .25, 'managed clock pair')
    require(b['monotonic'] > a['monotonic'] and
            abs((b['wall'] - a['wall']) - (b['monotonic'] - a['monotonic'])) <= MANAGED_CLOCK_DRIFT, 'wall/monotonic clock step')
    return MANAGED_CLOCK_TOLERANCE + a['uncertainty'] + b['uncertainty']


def to_monotonic(clock, timestamp):
    clock_bound(clock)
    require(type(timestamp) in {int, float} and math.isfinite(timestamp), 'managed timestamp')
    return clock['start']['monotonic'] + (timestamp - clock['start']['wall'])


MANAGED_METRICS = {'envoy_cluster_upstream_rq_' + k[len('upstream_rq_'):]: k for k in STATS}
# Selected managed bootstrap tag (P9 Azure evidence: `stats_tags` emits `cluster_name`, never the Envoy default
# `envoy_cluster_name`). `cluster` is the AMW cluster label that scopes the shared workspace to the target cluster.
MANAGED_CLUSTER_LABEL = 'cluster_name'


def managed_selector(namespace, prometheus_cluster, job='p10-envoy', cluster='inbound|8080||'):
    names = '|'.join(sorted(k[len('envoy_cluster_upstream_rq_'):] for k in MANAGED_METRICS))
    return '{__name__=~"envoy_cluster_upstream_rq_(%s)",cluster=%s,namespace=%s,job=%s,%s=%s}' % (
        names, json.dumps(prometheus_cluster), json.dumps(namespace), json.dumps(job), MANAGED_CLUSTER_LABEL, json.dumps(cluster))


def poll_managed(fetch, selector, lookback_seconds, clock=time.monotonic):
    """One Prometheus-API query for RAW samples (a range vector keeps the actual scrape timestamps).

    `fetch(path, params)` returns the parsed JSON. The caller owns authentication; none exists here.
    `at` is when the response reached the harness, i.e. the latest moment each returned sample was visible.
    """
    data = fetch('/api/v1/query', {'query': '%s[%ds]' % (selector, lookback_seconds)})
    return {'at': clock(), 'data': data}


def project_managed(polls, pods, clock, *, namespace, prometheus_cluster, scrape_seconds, cluster='inbound|8080||', job='p10-envoy'):
    """Prometheus raw samples -> rows for managed_guard()/coverage(); Pod label -> actual Pod UID/pool.

    Series carry the Pod *name* only, so identity comes from the harness's Kubernetes inventory, never
    from the series. A scrape is one timestamp per Pod holding all five stats; absent, empty, partial,
    unmapped or rewritten series are invalid and never zero. A round some Pod lacks is skipped, leaving a
    coverage gap (observation-insufficient), not a value. Each sample's visibility time is the first poll
    that returned it, so ingestion delay is measured.
    """
    inventory = {p['name']: p for p in pods}
    require(pods and len(inventory) == len(pods) and all(set(p) == {'name', 'uid', 'pool'} for p in pods) and
            len({p['uid'] for p in pods}) == len(pods), 'managed Pod inventory')
    values, seen = {}, {}
    for poll in polls:
        data = poll['data']
        require(type(data) is dict and data.get('status') == 'success' and type(data.get('data')) is dict and
                data['data'].get('resultType') == 'matrix' and type(data['data'].get('result')) is list, 'managed query response')
        for series in data['data']['result']:
            labels = series['metric']
            metric = MANAGED_METRICS.get(labels.get('__name__'))
            require(metric and labels.get('namespace') == namespace and labels.get('job') == job and
                    labels.get('cluster') == prometheus_cluster and labels.get(MANAGED_CLUSTER_LABEL) == cluster and
                    'envoy_cluster_name' not in labels, 'unexpected managed series')
            pod = inventory.get(labels.get('pod'))
            require(pod, 'managed series from unmapped Pod')
            for timestamp, raw in series['values']:
                require(type(timestamp) in {int, float} and math.isfinite(timestamp) and type(raw) is str and re.fullmatch(r'\d+', raw), 'managed sample value')
                key = (pod['uid'], round(timestamp, 3))
                require(values.setdefault(key, {}).setdefault(metric, int(raw)) == int(raw), 'managed sample rewritten')
                seen[key + (metric,)] = min(seen.get(key + (metric,), poll['at']), poll['at'])
    scrapes = {p['uid']: [] for p in pods}
    for (uid, timestamp), stats in values.items():
        require(set(stats) == STATS, 'partial managed scrape')
        scrapes[uid].append(timestamp)
    require(all(scrapes.values()), 'required managed series absent')
    rows, used = [], set()
    for first, uid0 in sorted((t, u) for u, ts in scrapes.items() for t in ts):
        if (uid0, first) in used:
            continue
        group = {uid0: first}
        for uid, stamps in scrapes.items():
            near = [t for t in stamps if uid != uid0 and (uid, t) not in used and abs(t - first) <= scrape_seconds / 2]
            if near:
                group[uid] = min(near, key=lambda t: abs(t - first))
        used.update(group.items() if len(group) == len(scrapes) else [(uid0, first)])
        if len(group) == len(scrapes):
            targets = [{'uid': p['uid'], 'pool': p['pool'], 'sample_at': to_monotonic(clock, group[p['uid']]),
                        'stats': dict(values[(p['uid'], group[p['uid']])])} for p in pods]
            rows.append({'at': max(seen[(p['uid'], group[p['uid']], stat)] for p in pods for stat in STATS),
                         'sample_at': max(t['sample_at'] for t in targets), 'targets': targets})
    return sorted(rows, key=lambda r: r['sample_at'])


def managed_guard(native, managed, coverage_end, v, clock):
    """Harness-projected managed (PodMonitor) rows; timestamps alone are never a signal.

    Every row must carry both actual native-baseline Pod UID/pool series with all five stats. Absent, empty
    or partial series are invalid, never zero; only a structurally valid series with a freshness/coverage gap
    is observation-insufficient (coverage()). Counters are bracketed at the sample's own time by the native
    samples (+/- the clock allowance), bounded by, and after the drained boundary equal to, the final native
    counters.
    """
    require(managed, 'required managed signals absent')
    tolerance = clock_bound(clock)
    identity = {t['uid']: t['pool'] for t in native[0]['targets']}
    final = {t['uid']: t['stats'] for t in native[-1]['targets']}
    times = [s['sample_at'] for s in native]
    require(times == sorted(times), 'native samples out of order')
    at = {uid: [next(t for t in s['targets'] if t['uid'] == uid)['stats'] for s in native] for uid in identity}
    previous = {}
    for row in managed:
        require(type(row) is dict and set(row) == {'at', 'sample_at', 'targets'} and
                all(type(row[k]) in {int, float} and math.isfinite(row[k]) for k in ('at', 'sample_at')), 'managed sample fields')
        targets = row['targets']
        require(type(targets) is list and len(targets) == len(identity) and
                all(type(t) is dict and set(t) == {'uid', 'pool', 'sample_at', 'stats'} and
                    type(t['sample_at']) in {int, float} and math.isfinite(t['sample_at']) for t in targets) and
                {t['uid']: t['pool'] for t in targets} == identity, 'managed Pod UID/pool series missing or drifted')
        require(row['sample_at'] == max(t['sample_at'] for t in targets), 'managed row time differs from its series')
        for t in targets:
            values = t['stats']
            require(type(values) is dict and set(values) == STATS and all(type(x) is int and x >= 0 for x in values.values()), 'missing/invalid managed stat')
            require(values['upstream_rq_pending_overflow'] == values['upstream_rq_pending_active'] == 0 and
                    values['upstream_rq_active'] <= v['max_requests'], 'competing pending capacity')
            old = previous.get(t['uid'], values)
            require(all(values[k] >= old[k] for k in COUNTERS), 'managed counter reset')
            require(all(values[k] <= final[t['uid']][k] for k in COUNTERS), 'managed counter beyond drained native counter')
            low = bisect.bisect_right(times, t['sample_at'] - tolerance) - 1
            high = bisect.bisect_left(times, t['sample_at'] + tolerance)
            require(all((low < 0 or at[t['uid']][low][k] <= values[k]) and
                        values[k] <= at[t['uid']][min(high, len(times) - 1)][k] for k in COUNTERS), 'managed value outside native bracket at its own time')
            require(t['sample_at'] < coverage_end + tolerance or all(values[k] == final[t['uid']][k] for k in COUNTERS), 'managed/native drained counter mismatch')
            previous[t['uid']] = values


def accounting(arm, evidence, clients):
    """All exact-check units are supplied, never derived from Git command count.

    Native frontend, backend, target admission/overflow, app and ingress counts
    must agree at drained boundaries. Rejected requests need no app record/ID.
    """
    require(evidence['classifier_escapes'] == 0 and evidence['dropped_logs'] == 0 and
            evidence['counter_lifetime_unchanged'] is True, 'classifier escape/log/counter lifetime')
    counts = evidence['classes']
    require(set(counts) == set(CLASSES), 'class counters missing')
    for kind, c in counts.items():
        fields = {'checks', 'admitted', 'rejected', 'queue', 'other', 'app', 'ingress', 'backend', 'target_total', 'pool'}
        require(set(c) == fields and all(type(c[k]) is int and c[k] >= 0 for k in fields - {'pool'}), 'check evidence fields')
        require(c['pool'] == ('shared' if arm == 'shared' else kind), 'pre/post class pool routing')
        require(c['checks'] == c['admitted'] + c['rejected'] + c['queue'] + c['other'] == c['ingress'] == c['backend'] == c['target_total'] and
                c['admitted'] == c['app'] and c['queue'] == c['other'] == 0, 'exact-check conservation/competing HAProxy queue')
        require(c['checks'] >= clients[kind]['attempts'], 'attempt/check denominator gap')
        if kind == 'critical': require(c['checks'] == clients[kind]['attempts'], 'single-HTTP critical check mismatch')
    require(evidence['frontend'] == sum(c['checks'] for c in counts.values()) and evidence['queue_start'] == evidence['queue_end'] ==
            evidence['inflight_start'] == evidence['inflight_end'] == evidence['haproxy_retries'] == 0, 'drain/frontend/retry conservation')
    return counts


RING = {'status': int, 'termination': str, 'class': str, 'backend': str, 'server': str, 'request_counter': int, 'pid': int,
        'accept_time': str, 'queue_ms': int, 'connect_ms': int, 'response_ms': int, 'total_ms': int}
HAPROXY_COUNTERS = ('req_tot', 'hrsp_2xx', 'hrsp_4xx', 'hrsp_5xx', 'econ', 'eresp', 'wretr', 'wredis', 'cli_abrt', 'srv_abrt')
HAPROXY_GAUGES = ('qcur', 'qmax', 'scur', 'smax')


def parse_ring(text):
    """Server-side class/backend/server rows of the experiment ring; any malformed row is lost evidence."""
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    for r in rows:
        require(type(r) is dict and set(r) == set(RING) and all(type(r[k]) is t for k, t in RING.items()) and
                r['class'] in CLASSES + ('deny', '-') and re.fullmatch(r'\d+\.\d{3}', r['accept_time']) and
                all(r[k] >= -1 for k in ('queue_ms', 'connect_ms', 'response_ms', 'total_ms')), 'HAProxy ring row fields')
    require(len({r['request_counter'] for r in rows}) == len(rows), 'duplicate HAProxy request counter')
    return rows


def no_request(r):
    """A connection closed before any request (the kubelet TCP readiness probe): HAProxy logs 400/CR without a class.

    It is not a check and has no request to classify. Only this exact shape is set aside; any other row that is
    not a classified check stays in the accounting as an escape/other.
    """
    return (r['class'] == '-' and r['status'] == 400 and r['termination'] == 'CR' and r['backend'] == 'check' and
            r['server'] == '<NOSRV>' and r['queue_ms'] == r['connect_ms'] == r['response_ms'] == -1)


def parse_haproxy_stats(text):
    out = {'frontend': {}, 'backend': {}}
    for row in csv.DictReader(io.StringIO(text.removeprefix('# '))):
        side = {'FRONTEND': 'frontend', 'BACKEND': 'backend'}.get(row['svname'])
        if side:
            out[side][row['pxname']] = {k: int(row[k]) if row.get(k, '').isdigit() else None for k in HAPROXY_COUNTERS + HAPROXY_GAUGES}
    return out


def parse_haproxy_info(text):
    info = dict(line.split(': ', 1) for line in text.splitlines() if ': ' in line)
    keys = ('Pid', 'Start_time_sec', 'Uptime_sec', 'Nbthread', 'Nbproc', 'Maxconn', 'DroppedLogs', 'MaxconnReached')
    require(all(k in info and info[k].isdigit() for k in keys), 'HAProxy info fields')
    return {k: int(info[k]) for k in keys}


def window_accounting(arm, obs):
    """Exact-check accounting for one drained window from independent observation sources.

    Class is attributed only by the HAProxy server-side ring (exact method+URL). Each other source is
    compared at the level it can actually attribute: native HAProxy counters per backend, client-issued
    requests per class (exact routing), app checks by operation ID (admitted only), ingress/target
    access logs and target admission per pool. Rejected requests need no app record.
    """
    require(arm in ARMS, 'unknown arm')
    pools = ('shared',) if arm == 'shared' else CLASSES
    pool_of = lambda kind: 'shared' if arm == 'shared' else kind
    before, after = obs['ring_before'], obs['ring_after']
    require(after[:len(before)] == before, 'HAProxy ring rewritten or lost')
    window = after[len(before):]
    rows = [r for r in window if not no_request(r)]
    ib, ia, sb, sa = obs['info_before'], obs['info_after'], obs['stats_before'], obs['stats_after']
    def count(side, name, key, snapshot):
        value = snapshot[side][name][key]
        require(value is not None, 'HAProxy counter absent')
        return value
    def moved(side, name, key): return count(side, name, key, sa) - count(side, name, key, sb)
    lifetime = (ib['Pid'] == ia['Pid'] and ib['Start_time_sec'] == ia['Start_time_sec'] and ia['Uptime_sec'] >= ib['Uptime_sec'] and
                ib['Nbthread'] == ia['Nbthread'] == ib['Nbproc'] == ia['Nbproc'] == 1 and ib['Maxconn'] == ia['Maxconn'] == 256 and
                ib['MaxconnReached'] == ia['MaxconnReached'] == 0 and {r['pid'] for r in after} <= {ia['Pid']})
    classes, answered = {}, {}
    for kind in CLASSES:
        selected = [r for r in rows if r['class'] == kind]
        queue = [r for r in selected if r['queue_ms'] > 0]
        # The target answered 200 (admitted) or 503 (inbound active overflow) whether or not HAProxy queued it.
        answered[kind] = [r['status'] for r in selected if r['termination'] == '--' and r['status'] in {200, 503}]
        served = [r for r in selected if r['queue_ms'] <= 0 and r['termination'] == '--']
        admitted = sum(r['status'] == 200 for r in served); rejected = sum(r['status'] == 503 for r in served)
        classes[kind] = {'checks': len(selected), 'admitted': admitted, 'rejected': rejected, 'queue': len(queue),
                         'other': len(selected) - len(queue) - admitted - rejected,
                         'app': sum((c['operation_id'] or '').startswith(kind + '-') for cs in obs['app_checks'].values() for c in cs),
                         'ingress': obs['client_requests'][kind],
                         'backend': sum(r['backend'] == pool_of(kind) and r['server'] == 'pool' for r in selected),
                         'target_total': len(answered[kind]), 'pool': pool_of(kind)}
    escapes = sum(r['class'] not in CLASSES or r['backend'] != pool_of(r['class']) or r['server'] != 'pool' for r in rows)
    # Native per-backend counters equal the server-side rows (no unlogged or phantom checks).
    for pool in pools:
        mine = [r for r in rows if r['backend'] == pool]
        require(moved('backend', pool, 'req_tot') == len(mine) and moved('backend', pool, 'hrsp_2xx') == sum(r['status'] == 200 for r in mine) and
                moved('backend', pool, 'hrsp_5xx') == sum(r['status'] >= 500 for r in mine) and
                all(moved('backend', pool, k) == 0 for k in ('econ', 'eresp', 'wretr', 'wredis', 'cli_abrt', 'srv_abrt')) and
                count('backend', pool, 'qmax', sa) == 0, 'HAProxy backend counters vs ring')
    # The frontend counts every logged request including the no-request 400s; only the backends are check-only.
    require(moved('frontend', 'check', 'req_tot') == len(window) and
            moved('frontend', 'check', 'hrsp_4xx') == sum(400 <= r['status'] < 500 for r in window), 'HAProxy frontend vs ring')
    # Pool-level target admission: access log rows are not class-attributable, so compare per pool.
    for pool in pools:
        logs = [r for t in obs['targets'] if t['pool'] == pool for r in obs['target_rows'][t['uid']]]
        mine = [a for kind, a in answered.items() if pool_of(kind) == pool]
        require(len(logs) == sum(map(len, mine)) and sum(r['status'] == 200 for r in logs) == sum(s == 200 for a in mine for s in a) and
                sum(r['status'] == 503 and 'overflow' in r['details'] for r in logs) == sum(s == 503 for a in mine for s in a), 'target access log vs class accounting')
    # Ingress: one access-log row per client request; every non-200 is the ext_authz rejection.
    ingress = obs['ingress_rows']
    require(len(ingress) == sum(obs['client_requests'].values()) == len(rows) and
            sum(r['status'] != 200 for r in ingress) == sum(s == 503 for a in answered.values() for s in a) and
            all(r['details'] == 'ext_authz_error' for r in ingress if r['status'] != 200), 'ingress access log vs class accounting')
    require(sum(c['app'] for c in classes.values()) == sum(len(cs) for cs in obs['app_checks'].values()) and
            all(c['decision'] == 'ALLOW' for cs in obs['app_checks'].values() for c in cs), 'app checks outside experiment classes')
    queued = lambda s: sum(count('backend', p, 'qcur', s) for p in pools)
    inflight = lambda s: sum(count('backend', p, 'scur', s) for p in pools) + count('frontend', 'check', 'scur', s)
    return {'classes': classes, 'classifier_escapes': escapes, 'no_request_connections': len(window) - len(rows), 'dropped_logs': ia['DroppedLogs'] - ib['DroppedLogs'],
            'counter_lifetime_unchanged': lifetime, 'frontend': moved('frontend', 'check', 'req_tot') - (len(window) - len(rows)),
            'queue_start': queued(sb), 'queue_end': queued(sa), 'inflight_start': inflight(sb), 'inflight_end': inflight(sa),
            'haproxy_retries': sum(moved('backend', p, k) for p in pools for k in ('wretr', 'wredis'))}


def validate(run):
    v = plan(run['plan']); arm = run['arm']; environment = run['environment']
    require(arm in ARMS and environment in {'azure', 'local'}, 'unknown arm/environment')
    require(re.fullmatch('[0-9a-f]{40}', run['source_sha']) and run['binding_sha256'] == digest(run['binding']) and
            run['binding']['plan_sha256'] == digest(v) and run['binding']['schedule_sha256'] == digest(schedule(v)) and
            run['binding']['source_sha'] == run['source_sha'] and
            run['binding'] == binding(run['binding']['identity'], v, run['binding']['fixture'], run['binding']['invariants'],
                                      environment, run['binding'].get('template')), 'source/demand binding drift')
    require(run['runtime_before'] == run['runtime_after'] == run['binding']['invariants'], 'runtime configuration drift')
    # Local HTTP is never TLS evidence: it must say so, and only Azure may assert TLS.
    require(run['healthy_classification'] is True and run['native_auth'] is True and
            (run['tls'] is True if environment == 'azure' else run['tls'] == LOCAL_TLS), 'healthy/native-auth/TLS gate')
    clients, start, end = client_report(v, run['events'])
    coverage_end = max(end, max(e['completed'] for e in run['events'] if e['record'] == 'operation'))
    saturated = pool_guard(v, arm, run['samples'], start, end)
    counts = accounting(arm, run['accounting'], clients)
    # Bind class accounting to actual per-UID native counter differences.
    first = {t['uid']: t for t in run['samples'][0]['targets']}
    last = {t['uid']: t for t in run['samples'][-1]['targets']}
    for pool in saturated:
        relevant = [c for c in counts.values() if c['pool'] == pool]
        for stat, key in [('upstream_rq_total', 'admitted'), ('upstream_rq_active_overflow', 'rejected')]:
            require(sum(last[u]['stats'][stat] - t['stats'][stat] for u, t in first.items() if t['pool'] == pool) ==
                    sum(c[key] for c in relevant), 'native counter vs class accounting mismatch')
    guards = run['guards']
    require(set(guards) == GUARDS and all(g['observed'] is True and g['competing_bottleneck'] is False and
            g['start'] <= start and g['end'] >= coverage_end and re.fullmatch('[0-9a-f]{64}', g['evidence_sha256']) for g in guards.values()), 'same-window confounder guard missing/failed')
    observed = coverage(v, run['samples'], start, coverage_end)
    if environment == 'azure':
        managed_guard(run['samples'], run['managed_samples'], coverage_end, v, run['managed_clock'])
        observed = observed and coverage(v, run['managed_samples'], start, coverage_end, managed=True)
    return {'status': 'valid' if observed else 'observation-insufficient', 'arm': arm, 'clients': clients,
            'accounting': counts, 'saturation_fraction': saturated, 'source_sha': run['source_sha'],
            'binding_sha256': run['binding_sha256']}


def compare(shared, isolated):
    a, b = validate(shared), validate(isolated)
    require(shared['binding'] == isolated['binding'] and shared['environment'] == isolated['environment'], 'comparison source/revision/demand/fault/confounder binding drift')
    signature = lambda run: {(t['image_id'], t['resources_sha256'], t['capacity'], t['hold_ms'], t['mapping_sha256'])
                             for t in run['samples'][0]['targets']}
    require(signature(shared) == signature(isolated) and len(signature(shared)) == 1, 'cross-arm actual image/resource/capacity drift')
    if any(r['status'] == 'observation-insufficient' for r in (a, b)):
        return {'status': 'observation-insufficient', 'arms': [a, b]}
    v = shared['plan']
    saturation = (a['saturation_fraction']['shared'] >= v['saturation_fraction'] and
                  b['saturation_fraction']['bulk'] >= v['saturation_fraction'] and
                  a['accounting']['bulk']['rejected'] > 0 and b['accounting']['bulk']['rejected'] > 0)
    degraded = a['clients']['critical']['good_fraction'] <= 1 - v['degradation_fraction'] and a['accounting']['critical']['rejected'] > 0
    protected = b['clients']['critical']['good_fraction'] >= v['protection_fraction']
    return {'status': 'positive' if saturation and degraded and protected else 'valid-negative',
            'bulk_saturation': saturation, 'shared_critical_degradation': degraded, 'isolated_critical_protection': protected,
            'scope': 'exact fixture operations only; actor/role protection not established', 'arms': [a, b]}


def main(args):
    command = args[0]
    if command == 'render':
        result = render(load(args[1]), load(args[2]), load(args[3]), args[4]); out = Path(args[5]); out.mkdir()
        for name, value in result.items(): save(out / name, value)
    elif command == 'validate': save(args[2], validate(load(args[1])))
    elif command == 'compare': save(args[3], compare(load(args[1]), load(args[2])))
    else: raise ValueError('unknown offline command')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Exception:
        # Inputs may include sensitive identities or paths. No raw exceptions.
        print('P10 offline validation failed; inspect protected inputs', file=sys.stderr)
        sys.exit(1)
