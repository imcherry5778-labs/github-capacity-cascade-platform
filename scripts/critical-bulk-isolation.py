#!/usr/bin/env python3
"""P10 offline renderer, bounded operation driver and evidence validator.

No Azure credentials, apply, IAM, provisioning or paid execution entrypoint.
Transport/observation callbacks are supplied by the owned local harness. Unknown
or incomplete evidence never becomes a positive or valid negative result.
"""
import concurrent.futures
import copy
import hashlib
import importlib.util
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
    # The existing single provider/mesh overlay and original native/TLS route are
    # reused without adding an extension provider or stable resource.
    return result


def binding(identity, v, f, invariants):
    p8.identity(identity); plan(v); fixture(f)
    keys = {'stable_revision', 'ingress_config_sha256', 'native_route_sha256', 'tls_auth_sha256',
            'target_resources_sha256', 'haproxy_image_id', 'haproxy_processes', 'haproxy_threads',
            'haproxy_maxconn', 'proxy_retries_sha256', 'sentinel_sha256', 'confounder_policy_sha256'}
    require(set(invariants) == keys and invariants['stable_revision'] == identity['stable_revision'] and
            invariants['haproxy_processes'] == invariants['haproxy_threads'] == 1 and invariants['haproxy_maxconn'] == 256 and
            all(re.fullmatch('[0-9a-f]{64}', invariants[k]) for k in keys if k.endswith('_sha256')), 'runtime invariant binding')
    return {'source_sha': identity['source_sha'], 'identity': identity, 'fixture': f,
            'plan_sha256': digest(v), 'schedule_sha256': digest(schedule(v)),
            'render_sha256': {a: digest(render(identity, v, f, a)) for a in ARMS}, 'invariants': invariants}


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
    if not samples or samples[0]['at'] > start or samples[-1]['at'] < end or samples[0]['sample_at'] > start or samples[-1]['sample_at'] < end:
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
            require(set(values) == set(COUNTERS) | {'upstream_rq_active', 'upstream_rq_pending_active'} and
                    all(type(x) is int and x >= 0 for x in values.values()), 'missing/invalid native stat')
            old = previous.get(t['uid'], values)
            require(all(values[k] >= old[k] for k in COUNTERS), 'counter reset')
            require(values['upstream_rq_pending_overflow'] == 0 and values['upstream_rq_pending_active'] == 0, 'competing pending capacity')
            previous[t['uid']] = values
    within = [s for s in samples if start <= s['sample_at'] <= end]
    saturated = {}
    for pool in expected:
        saturated[pool] = sum(any(t['pool'] == pool and t['stats']['upstream_rq_active'] >= v['max_requests'] for t in s['targets']) for s in within) / len(within) if within else None
    return saturated


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


def validate(run):
    v = plan(run['plan']); arm = run['arm']; require(arm in ARMS, 'unknown arm')
    require(re.fullmatch('[0-9a-f]{40}', run['source_sha']) and run['binding_sha256'] == digest(run['binding']) and
            run['binding']['plan_sha256'] == digest(v) and run['binding']['schedule_sha256'] == digest(schedule(v)) and
            run['binding']['source_sha'] == run['source_sha'] and
            run['binding'] == binding(run['binding']['identity'], v, run['binding']['fixture'], run['binding']['invariants']), 'source/demand binding drift')
    require(run['runtime_before'] == run['runtime_after'] == run['binding']['invariants'], 'runtime configuration drift')
    require(run['healthy_classification'] is True and run['native_auth'] is True and run['tls'] is True, 'healthy/native-auth/TLS gate')
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
    if run['environment'] == 'azure':
        require(run['managed_samples'], 'required managed signals absent')
        observed = observed and coverage(v, run['managed_samples'], start, coverage_end, managed=True)
    else:
        require(run['environment'] == 'local', 'unknown environment')
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
