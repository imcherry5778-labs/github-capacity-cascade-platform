#!/usr/bin/env python3
"""P9 four-arm source/render, open-loop load and continuing-demand recovery evidence.

No apply/publish/IAM entrypoint. measure/release/transition require a separate P9
exact-source approval manifest; offline commands never construct Runtime.
"""
import concurrent.futures
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import uuid

sys.dont_write_bytecode = True
import importlib.util
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('p8_adapter', ROOT / 'scripts/azure-cascade.py')
p8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p8)
require, save, load, digest = p8.require, p8.save, p8.load, p8.digest
NS = p8.NS  # Reuse removed P8 fixture names, owned by the NEW campaign label.
ARMS = ('C0', 'C1', 'C2', 'C3')
HPA = 'p9-proxy'
SLO = ROOT / 'docs/evidence/p7-operations-20261028/initial-slo.json'
DEADLINE = datetime(2026, 10, 30, 1, 30, tzinfo=timezone.utc)


# Selected managed runtime contract, not an auto-discovery/fallback policy.
TARGET_METRIC = {'cluster_label': 'cluster_name', 'cluster': 'inbound|8080||',
                 'alt_stat_name': 'inbound|8080||;', 'port': 8080,
                 'tag_regex': r'^cluster(\.(.+);)', 'job': 'p9-envoy',
                 'overflow': 'envoy_cluster_upstream_rq_active_overflow',
                 'active': 'envoy_cluster_upstream_rq_active',
                 'admin_request': 'stats?format=json', 'exposition_request': 'stats/prometheus'}


def metric_contract():
    return copy.deepcopy(TARGET_METRIC)


def signal_queries(v):
    c = metric_contract()
    base = 'cluster=' + json.dumps(v['prometheus_cluster']) + ',namespace=' + json.dumps(NS)
    selector = base + ',job=' + json.dumps(c['job']) + ',' + c['cluster_label'] + '=' + json.dumps(c['cluster'])
    raw = c['overflow'] + '{' + selector + '}'
    return {'raw': raw, 'rate': 'rate(' + raw + '[1m])', 'active': c['active'] + '{' + selector + '}',
            'timestamp': 'timestamp(' + raw + ')', 'samples': 'count_over_time(' + raw + '[1m])'}


def selected_mapping(mapping):
    c = metric_contract()
    require(mapping['cluster_name'] == c['cluster'] and mapping['alt_stat_name'] == c['alt_stat_name'] and
            mapping['endpoint_mapping'] == f'listener-port-{c["port"]}-to-ORIGINAL_DST' and
            mapping['stat_names'] == sorted('cluster.' + c['alt_stat_name'] + '.' + key for key in p8.p4.SUFFIXES), 'selected inbound metric mapping drift')
    return c


def metric_mapping(mapping, bootstrap):
    c = selected_mapping(mapping)
    configs = [v for v in p8.walk(bootstrap) if 'stats_tags' in v]
    require(len(configs) == 1 and configs[0].get('use_all_default_tags') is False, 'bootstrap stat tag contract')
    tags = [t for t in configs[0]['stats_tags'] if t['tag_name'] in {c['cluster_label'], 'envoy_cluster_name'}]
    require(tags == [{'tag_name': c['cluster_label'], 'regex': c['tag_regex']}], 'bootstrap cluster label drift')
    return {'cluster_label': c['cluster_label'], 'tag_regex': c['tag_regex']}


def native_samples(text):
    """Only the two selected metric families; unrelated/bootstrap clusters never count."""
    c = metric_contract()
    found = {}
    types = {row.split()[2]: row.split()[3] for row in text.splitlines() if row.startswith('# TYPE ')}
    for name, kind in ((c['overflow'], 'counter'), (c['active'], 'gauge')):
        require(name not in types or types[name] == kind, 'native metric type drift')
    for line in text.splitlines():
        if not line.startswith((c['overflow'] + '{', c['active'] + '{')):
            continue
        match = re.fullmatch(r'([^{}]+)\{(.*)\} ([^ ]+)', line)
        require(match is not None, 'invalid selected native metric')
        name, labels, value = match.groups()
        pairs = re.findall(r'([a-zA-Z_][a-zA-Z_0-9]*)=("(?:[^"\\]|\\.)*")(?:,|$)', labels)
        require(','.join(k + '=' + v for k, v in pairs) == labels and len({k for k, _ in pairs}) == len(pairs), 'ambiguous native labels')
        labels = {k: json.loads(v) for k, v in pairs}
        if c['cluster'] not in labels.values():
            continue
        require(labels.get(c['cluster_label']) == c['cluster'] and 'envoy_cluster_name' not in labels and name not in found, 'native inbound label drift/duplicate')
        value = float(value)
        require(bounded(value, 0, 1000000000000), 'invalid native metric value')
        require(types.get(name) == ('counter' if name == c['overflow'] else 'gauge'), 'native metric type absent')
        found[name] = value
    return found


def admin_observation(target, observation):
    c = selected_mapping(target['mapping'])
    require(target['metric_binding'] == {'cluster_label': c['cluster_label'], 'tag_regex': c['tag_regex']}, 'saved metric binding drift')
    expected = set(target['mapping']['stat_names'])
    values = observation['values']
    require(set(values) <= expected and set(observation['missing']) == expected - set(values) and
            all(bounded(v, 0, 1000000000000) for v in values.values()), 'invalid/mismapped admin stats')
    full = set(values) == expected
    require(observation['status'] == ('observed' if full else 'uninitialized'), 'admin stat state differs')
    native = observation['native']
    require(set(native) <= {c['overflow'], c['active']} and all(bounded(v, 0, 1000000000000) for v in native.values()), 'unknown/invalid native metric')
    if full:
        require(set(native) == {c['overflow'], c['active']} and
                native[c['overflow']] >= values['cluster.' + c['alt_stat_name'] + '.upstream_rq_active_overflow'], 'missing/mismapped native target sample')
    return full


def bounded(value, low, high):
    return type(value) in {int, float} and math.isfinite(value) and low <= value <= high


def plan(v):
    require(set(v) == {'mitigation_seconds', 'recovery_seconds', 'backoff_ms', 'seed', 'queue_limit',
                      'queue_timeout_ms', 'threshold', 'scrape_seconds', 'ingestion_seconds',
                      'controller_seconds', 'freshness_seconds', 'prometheus', 'prometheus_cluster',
                      'identity_client_id', 'keda_version'}, 'P9 plan fields')
    require(all(type(v[k]) is int and 1 <= v[k] <= 60 for k in ('scrape_seconds', 'ingestion_seconds', 'controller_seconds')), 'actual cadence required')
    require(type(v['mitigation_seconds']) is int and v['mitigation_seconds'] % 10 == 0 and
            max(120, 3 * (v['scrape_seconds'] + v['ingestion_seconds'] + v['controller_seconds'])) <= v['mitigation_seconds'] <= 300, 'common cadence observation interval')
    require(type(v['recovery_seconds']) is int and v['recovery_seconds'] % 10 == 0 and 120 <= v['recovery_seconds'] <= 240 and
            v['mitigation_seconds'] + v['recovery_seconds'] <= 540, 'bounded recovery deadline; 60s drain within 600s')
    require(type(v['seed']) is int and 0 <= v['seed'] < 2**32 and len(v['backoff_ms']) == 2 and
            all(bounded(x, 100, 1000) for x in v['backoff_ms']) and v['backoff_ms'][0] <= v['backoff_ms'][1], 'bounded deterministic backoff+jitter')
    require(type(v['queue_limit']) is int and 1 <= v['queue_limit'] <= 24 and bounded(v['queue_timeout_ms'], 100, 500), 'bounded admission queue')
    require(bounded(v['threshold'], .25, 1) and type(v['freshness_seconds']) is int and
            v['scrape_seconds'] + v['ingestion_seconds'] <= v['freshness_seconds'] <= 120, 'rate threshold/freshness')
    require(re.fullmatch(r'https://[a-z0-9.-]+\.prometheus\.monitor\.azure\.com', v['prometheus']) and
            re.fullmatch(r'[a-zA-Z0-9_-]+', v['prometheus_cluster']), 'exact Managed Prometheus target')
    require(re.fullmatch(r'[0-9a-f-]{36}', v['identity_client_id']) and re.fullmatch(r'2\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?', v['keda_version']), 'actual KEDA version/identity required')
    require(load(SLO)['command_latency']['per_operation']['issue_read']['threshold_max_seconds'] == .2, 'P7 SLO changed')
    return v


def schedule(v):
    plan(v)
    duration = v['mitigation_seconds'] + v['recovery_seconds']
    return [{'id': f'w{wave}-{kind}-{index}', 'kind': kind, 'at': wave * 5, 'wave': wave}
            for wave in range(duration // 5) for kind, count in (('issue', 24), ('git', 1)) for index in range(count)]


def retry_delay(v, arm, item):
    if arm != 'C1':
        return 0
    # Per logical ID: scheduling/thread order cannot change jitter.
    seed = int(hashlib.sha256(f"{v['seed']}:{item['id']}".encode()).hexdigest(), 16)
    return random.Random(seed).uniform(*v['backoff_ms']) / 1000


def scale_query(v):
    """Counter -> per-Pod rate -> sum, guarded against partial/stale inventory.

    Exact name/labels and these inventory series MUST be checked in calibration.
    There is deliberately no empty -> 0 fallback.
    """
    base = 'cluster=' + json.dumps(v['prometheus_cluster']) + ',namespace=' + json.dumps(NS)
    raw = signal_queries(v)['raw']
    fresh = f'(time() - timestamp({raw}) <= {v["freshness_seconds"]})'
    rates = f'(rate({raw}[1m]) and {fresh})'
    inventory = 'count(kube_pod_info{' + base + ',pod=~"ext-authz-sim-.+"})'
    count = f'count({rates})'
    up = 'up{' + base + ',job=' + json.dumps(metric_contract()['job']) + '}'
    return (f'sum({rates}) and on() ({count} == {inventory}) '
            f'and on() (min({up}) == 1) '
            f'and on() (count({up}) == {inventory}) '
            f'and on() (max(time() - timestamp({up})) <= {v["freshness_seconds"]}) '
            f'and on() (max(time() - timestamp(kube_pod_info{{{base},pod=~"ext-authz-sim-.+"}})) <= {v["freshness_seconds"]})')


def render(identity, v, arm):
    p8.identity(identity); plan(v)
    require(arm in ARMS, 'unknown arm')
    result = p8.render(identity)
    items = result['fixtures.json']['items']
    hp = next(o for o in items if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'haproxy')
    config = hp['data']['haproxy.cfg'].replace('timeout connect 5s', 'timeout connect 250ms').replace('timeout server 10s', 'timeout server 2s').replace('timeout client 10s', 'timeout client 4s')
    # Same logging policy for all arms; no URL, credentials or bodies.
    config = 'global\n  log stdout format raw local0\n' + config
    config = config.replace('  mode http\n', '  mode http\n  log global\n  log-format "{\\"status\\":%ST,\\"termination\\":\\"%ts\\",\\"queue_ms\\":%Tw,\\"connect_ms\\":%Tc,\\"response_ms\\":%Tr,\\"total_ms\\":%Ta}"\n')
    if arm == 'C2':
        config = config.replace('  timeout connect 250ms', '  timeout queue ' + str(v['queue_timeout_ms']) + 'ms\n  timeout connect 250ms')
        config = config.replace('  default_backend ext_authz', '  http-request deny deny_status 429 if { queue(ext_authz) ge ' + str(v['queue_limit']) + ' }\n  default_backend ext_authz')
        config = config.replace('svc.cluster.local:8080\n', 'svc.cluster.local:8080 maxconn 2 maxqueue ' + str(v['queue_limit']) + '\n')
    config = config.replace('listen local_stats\n', 'listen local_stats\n  no log\n')
    hp['data']['haproxy.cfg'] = config
    if arm == 'C3':
        items[:] = [o for o in items if o['kind'] != 'HorizontalPodAutoscaler']
        items += [dict(apiVersion='keda.sh/v1alpha1', kind='TriggerAuthentication',
            metadata={'name': 'p9-prometheus', 'namespace': NS, 'labels': {'p8.campaign': identity['campaign']}},
            spec={'podIdentity': {'provider': 'azure-workload', 'identityId': v['identity_client_id']}}),
            dict(apiVersion='keda.sh/v1alpha1', kind='ScaledObject',
            metadata={'name': HPA, 'namespace': NS, 'labels': {'p8.campaign': identity['campaign']}},
            spec={'scaleTargetRef': {'name': 'ext-authz-sim'}, 'minReplicaCount': 1, 'maxReplicaCount': 2,
                'pollingInterval': 15, 'advanced': {'horizontalPodAutoscalerConfig': {'name': HPA,
                'behavior': {'scaleDown': {'stabilizationWindowSeconds': 300}}}},
                'triggers': [{'type': 'prometheus', 'metricType': 'AverageValue',
                    'metadata': {'serverAddress': v['prometheus'], 'query': scale_query(v), 'threshold': str(v['threshold']),
                                 'ignoreNullValues': 'false', 'unsafeSsl': 'false'},
                    'authenticationRef': {'name': 'p9-prometheus'}}]})]
    # Existing managed scraper, experiment-owned PodMonitor. No new collector/controller.
    items.append(dict(apiVersion='azmonitoring.coreos.com/v1', kind='PodMonitor',
        metadata={'name': 'p9-envoy', 'namespace': NS, 'labels': {'p8.campaign': identity['campaign']}},
        spec={'selector': {'matchLabels': {'app': 'ext-authz-sim'}}, 'podMetricsEndpoints': [{
            'port': 'http-envoy-prom', 'path': '/stats/prometheus', 'interval': str(v['scrape_seconds']) + 's',
            'relabelings': [{'targetLabel': 'job', 'replacement': 'p9-envoy'}],
            'metricRelabelings': [{'sourceLabels': ['__name__'], 'regex': 'envoy_cluster_upstream_rq_(active_overflow|active|total|pending_overflow)', 'action': 'keep'}]}]}))
    return result


def controller_guard(arm, hpas, scaled):
    relevant = [o for o in hpas if o['spec']['scaleTargetRef']['name'] == 'ext-authz-sim']
    so = [o for o in scaled if o['spec']['scaleTargetRef']['name'] == 'ext-authz-sim']
    require(len(relevant) == 1, 'exactly one HPA must own target')
    hp = relevant[0]
    if arm == 'C3':
        require(len(so) == 1 and so[0]['metadata']['name'] == HPA and
                hp['metadata']['name'] == HPA and any(r['kind'] == 'ScaledObject' and
                r['uid'] == so[0]['metadata']['uid'] and r.get('controller') is True for r in hp['metadata'].get('ownerReferences', [])), 'KEDA HPA ownership differs')
    else:
        require(not so and hp['metadata']['name'] == 'hpa-app-cpu' and not hp['metadata'].get('ownerReferences'), 'CPU HPA ownership differs')
    require(hp['spec']['minReplicas'] == 1 and hp['spec']['maxReplicas'] == 2, 'scaling bounds')
    return hp


def approval_gate(identity, v, approval, ledger, now=None):
    p8.identity(identity); plan(v)
    now = now or datetime.now(timezone.utc)
    require(os.environ.get('P9_AZURE_APPROVED') == identity['source_sha'] and
            approval['source_sha'] == identity['source_sha'] and approval['identity'] == identity and
            approval['plan_sha256'] == digest(v) and approval['approved'] is True and approval['approval_url'], 'explicit exact P9 approval required')
    require(approval['limits'] == {'calibration': 2, 'measured_per_arm': 1, 'pod': 4, 'cpu_m': 1500, 'memory_mi': 2048}, 'approval scope differs')
    require(now + timedelta(seconds=v['mitigation_seconds'] + v['recovery_seconds'] + 60 + 1800) < DEADLINE, 'insufficient retention time for run/drain/rollback')
    require(all(r['source_sha'] == identity['source_sha'] and (r['phase'] == 'calibration' or r['plan_sha256'] == digest(v)) for r in ledger), 'ledger source/plan drift')
    require(sum(r['phase'] == 'calibration' for r in ledger) <= 2 and all(sum(r['phase'] == 'measured' and r['arm'] == a for r in ledger) <= 1 for a in ARMS), 'campaign run budget exceeded')


def execution_gate(identity, v, approval, ledger, now=None):
    approval_gate(identity, v, approval, ledger, now)
    require(v['identity_client_id'] != '00000000-0000-0000-0000-000000000000', 'replace candidate identity with actual approved client ID')
    require(approval['normal_test_passed'] is True and approval['healthy_gate_passed'] is True and
            approval['runtime_preflight_passed'] is True, 'normal/healthy/live preflight required')


def preparation_gate(identity, v, approval, ledger, now=None):
    approval_gate(identity, v, approval, ledger, now)
    require(approval['normal_test_passed'] is True, 'normal/native-auth/TLS evidence required before healthy initialization')


def telemetry(rows, pods, now, freshness):
    require(rows and set(r['pod_uid'] for r in rows) == set(pods) and len(rows) == len(pods), 'missing/extra/duplicate target telemetry')
    for r in rows:
        require(r['status'] == 'observed' and r['pod'] == pods[r['pod_uid']] and
                bounded(r['rate'], 0, 1000000) and bounded(r['active'], 0, 1000000) and
                0 <= now - r['timestamp'] <= freshness and r['samples'] >= 2, 'empty/stale/error/uninitialized rate')
    return sum(r['rate'] for r in rows)


class TargetLifecycle:
    """Shared live/saved boundary: admission -> Ready -> initialized series."""
    def __init__(self, arm, initial_uids, v):
        self.arm, self.initial, self.v = arm, set(initial_uids), v
        self.first_seen, self.ready_since, self.observed, self.admin_seen = {}, {}, set(), set()

    def inventory(self, pods, at):
        names = {p['uid']: p['name'] for p in pods}
        require(len(names) == len(pods) and len(set(names.values())) == len(pods) and
                1 <= len(pods) <= (2 if self.arm == 'C3' else 1), 'target inventory duplicates/bounds')
        require(self.initial <= set(names) and set(self.first_seen) <= set(names), 'target lifetime disappeared')
        for p in pods:
            uid = p['uid']
            self.first_seen.setdefault(uid, at)
            new = self.arm == 'C3' and uid not in self.initial and uid not in self.observed
            require(not p['reason'] and all(c['restarts'] == 0 and c['last_termination'] not in {'OOMKilled', 'Error'} for c in p['containers']), 'target lifecycle failure')
            ready = p['ready'] and all(c['ready'] for c in p['containers']) and p['phase'] == 'Running'
            if not ready:
                require(new and p['phase'] in {'Pending', 'Running'} and at - self.first_seen[uid] <= 90 and
                        uid not in self.ready_since, 'target startup/readiness failure')
            else:
                require(not new or uid in self.ready_since or at - self.first_seen[uid] <= 90, 'target Ready startup timeout')
                self.ready_since.setdefault(uid, at)
        return names

    def admin(self, targets, observations, stats, at):
        require(set(observations) == {t['uid'] for t in targets} and
                set(observations) <= set(self.first_seen), 'unknown admin UID/inventory')
        complete = set()
        for target in targets:
            uid = target['uid']
            if admin_observation(target, observations[uid]):
                require(uid in stats and stats[uid] == observations[uid]['values'], 'admin snapshot differs')
                complete.add(uid)
            else:
                require(self.arm == 'C3' and uid not in (self.initial | self.admin_seen) and uid in self.ready_since and
                        at - self.ready_since[uid] <= self.v['ingestion_seconds'] + 3 * self.v['scrape_seconds'], 'unapproved missing admin stats/startup timeout')
                require(uid not in stats, 'uninitialized stats fabricated')
        require(set(stats) == complete, 'unknown/missing stat UID')
        self.admin_seen |= complete

    def signal(self, signal, pods, at, epoch):
        names = self.inventory(pods, at)
        rows = signal['pods']
        require(all(r['metric_contract'] == metric_contract() for r in rows), 'saved series metric contract drift')
        observed = {r['pod_uid']: r['pod'] for r in rows}
        require(set(observed) <= self.admin_seen, 'series without initialized admin stats')
        missing = set(names) - set(observed)
        if missing:
            require(signal['status'] == 'warming-new-pod' and self.arm == 'C3' and
                    set(signal['missing_uids']) == missing and signal['query'] == [] and
                    missing <= set(names) - self.initial - self.observed, 'unapproved missing telemetry')
            for uid in missing:
                since = self.ready_since.get(uid)
                require(since is None or at - since <= self.v['ingestion_seconds'] + 3 * self.v['scrape_seconds'], 'new-Pod series startup timeout')
        else:
            require(signal['status'] == 'observed' and len(signal['query']) == 1 and
                    bounded(float(signal['query'][0]['value'][1]), 0, 1000000), 'empty/invalid guarded scale query')
        ready_names = {uid: name for uid, name in names.items() if uid in self.ready_since and uid not in missing}
        # Always validate existing series, including while another UID warms up.
        value = telemetry(rows, ready_names, epoch, self.v['freshness_seconds'])
        self.observed.update(observed)
        return None if missing else value


def accounting(arm, v):
    # Window boundary residuals belong to the denominator, even on invalid runs.
    for k in ('checks', 'target_admitted', 'target_rejected', 'admission_shed', 'queue_timeout',
              'queue_start', 'queue_end', 'inflight_start', 'inflight_end', 'path_errors'):
        require(type(v[k]) is int and v[k] >= 0, 'check accounting fields')
    require(v['checks'] + v['queue_start'] + v['inflight_start'] == v['target_admitted'] + v['target_rejected'] +
            v['admission_shed'] + v['queue_timeout'] + v['path_errors'] + v['queue_end'] + v['inflight_end'], 'check conservation failed')
    require(arm == 'C2' or v['admission_shed'] == v['queue_timeout'] == v['queue_start'] == v['queue_end'] == 0, 'competing HAProxy admission/queue')
    return v


def frozen(identity, v, calibration):
    plan(v); p8.identity(identity)
    require(1 <= len(calibration) <= 2 and all(c['source_sha'] == identity['source_sha'] and c['plan_sha256'] == digest(v) and
            c['reviewed'] is True and c['missing_required_signals'] == [] and c['cadence_observed'] is True and
            c['all_pod_series_observed'] is True and c['counter_semantics'] == 'per-pod-active-overflow-counter-rate-per-second' and
            c['controller_ownership_verified'] is True and c['metric_contract'] == metric_contract() for c in calibration), 'reviewed bounded calibration required')
    transport = calibration[-1]['transport']
    require(transport == p8.p7.operations.transport(transport['endpoint'], 'azure-aks', transport.get('dns_client_override')) and
            urllib.parse.urlsplit(transport['endpoint']).hostname == identity['forgejo_hostname'] and
            all(c['transport'] == transport and c['fixture_sha256'] == calibration[-1]['fixture_sha256'] for c in calibration) and
            re.fullmatch('[0-9a-f]{64}', calibration[-1]['fixture_sha256']), 'calibration transport/fixture freeze')
    return {'source_sha': identity['source_sha'], 'identity': identity, 'plan': v, 'metric_contract': metric_contract(), 'transport': transport,
            'fixture_sha256': calibration[-1]['fixture_sha256'], 'schedule_sha256': digest(schedule(v)),
            'slo_sha256': hashlib.sha256(SLO.read_bytes()).hexdigest(),
            'render_sha256': {a: digest(render(identity, v, a)) for a in ARMS},
            'calibration_sha256': [digest(c) for c in calibration]}


def retryable(result):
    # Native 403 is never retryable without scoped experiment-overload evidence.
    return result['semantic_result'] is False and result.get('overload') is True and result['status'] in {403, 429, 503}


def drive(v, arm, issue, git, emit, release, *, clock=time.monotonic, wait=time.sleep, monitor_error=lambda: False):
    """Independent arrivals, separate Issue12/Git1 workers, finite backlog.

    Never wait for a wave to finish before scheduling the next wave. Every planned
    arrival has a terminal row, including missed/cancelled/failed-to-issue demand.
    """
    arrivals = schedule(v)
    origin = clock()
    released = False
    futures = []
    cancelled = threading.Event()
    emit({'record': 'schedule', 'origin': origin, 'origin_utc': p8.utc(), 'items': arrivals, 'sha256': digest(arrivals)})
    def operation(item):
        scheduled = origin + item['at']
        issued = clock()
        if cancelled.is_set() or issued >= origin + v['mitigation_seconds'] + v['recovery_seconds']:
            emit({'record': 'operation', **item, 'scheduled': scheduled, 'issued': None, 'completed': clock(), 'outcome': 'cancelled', 'attempts': [], 'backoff_seconds': 0})
            return
        attempts, delayed = [], 0
        for index in range(1, 3 if item['kind'] == 'issue' else 2):
            if index > 1 and cancelled.is_set():
                break
            started = clock()
            try:
                result = (issue if item['kind'] == 'issue' else git)(item['id'], index)
            except Exception:
                result = {'semantic_result': False, 'status': None, 'error_class': 'driver-error', 'duration_seconds': clock() - started}
            attempts.append({'index': index, 'started': started, 'ended': clock(), **result})
            if index == 2 or item['kind'] == 'git' or not retryable(result):
                break
            delay = retry_delay(v, arm, item)
            wait(delay); delayed += delay
        emit({'record': 'operation', **item, 'scheduled': scheduled, 'issued': issued, 'completed': clock(),
              'outcome': 'completed', 'attempts': attempts, 'backoff_seconds': delayed})
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as issues, concurrent.futures.ThreadPoolExecutor(max_workers=1) as reads:
        for item in arrivals:
            due = origin + item['at']
            if monitor_error():
                cancelled.set()
            if not cancelled.is_set() and due > clock():
                wait(due - clock())
            if not released and (item['at'] >= v['mitigation_seconds'] or cancelled.is_set()):
                # Release runs independently: kubelet ConfigMap convergence must
                # never pause arrivals. Collector records actual per-Pod convergence.
                release(origin + v['mitigation_seconds'])
                released = True
            if monitor_error():
                cancelled.set()
            pending = sum(not f.done() for f in futures)
            if cancelled.is_set() or pending >= 49:
                cancelled.set()
                emit({'record': 'operation', **item, 'scheduled': due, 'issued': None, 'completed': clock(), 'outcome': 'not-issued', 'attempts': [], 'backoff_seconds': 0})
            else:
                futures.append((issues if item['kind'] == 'issue' else reads).submit(operation, item))
        end = origin + v['mitigation_seconds'] + v['recovery_seconds']
        if not cancelled.is_set() and end > clock():
            wait(end - clock())
        cancelled.set()
        for f in futures:
            f.result()
    emit({'record': 'observation_end', 'at': end, 'drained': clock()})
    return origin


def demand_report(v, events):
    sched = [e for e in events if e['record'] == 'schedule']
    require(len(sched) == 1 and sched[0]['items'] == schedule(v) and sched[0]['sha256'] == digest(schedule(v)), 'paused/reduced/changed demand schedule')
    origin = sched[0]['origin']
    rows = [e for e in events if e['record'] == 'operation']
    wanted = {x['id']: x for x in schedule(v)}
    require(len(rows) == len(wanted) and {r['id'] for r in rows} == set(wanted), 'whole campaign denominator missing')
    for r in rows:
        require(all(r[k] == wanted[r['id']][k] for k in ('kind', 'at', 'wave')) and r['scheduled'] == origin + r['at'], 'arrival drift')
        require(r['outcome'] in {'completed', 'cancelled', 'not-issued'}, 'operation outcome')
        if r['issued'] is None:
            require(not r['attempts'] and r['outcome'] != 'completed', 'unissued accounting')
            continue
        require(r['scheduled'] <= r['issued'] <= r['completed'] and
                1 <= len(r['attempts']) <= (2 if r['kind'] == 'issue' else 1), 'operation/attempt timing')
        prev = r['issued']
        for index, a in enumerate(r['attempts'], 1):
            require(type(a['semantic_result']) is bool and a['error_class'] in {'none', 'http_status', 'semantic_error', 'timeout', 'transport', 'git_command', 'driver-error'}, 'attempt semantic/error schema')
            require(a['index'] == index and prev <= a['started'] <= a['ended'] <= r['completed'] and
                    bounded(a['duration_seconds'], 0, 12) and a['duration_seconds'] <= a['ended'] - a['started'] + .01, 'P7 command timing missing/invalid')
            if index > 1:
                require(retryable(r['attempts'][index - 2]), 'native denial/unscoped retry')
            prev = a['ended']
        require(bounded(r['backoff_seconds'], 0, 1) and
                r['completed'] - r['scheduled'] + .0001 >= sum(a['duration_seconds'] for a in r['attempts']) + r['backoff_seconds'], 'retry/queue end-to-end latency missing')
    missed = sum(r['issued'] is None for r in rows)
    return {'scheduled': len(rows), 'issued': len(rows) - missed, 'unissued': missed,
            'failed': sum(r['issued'] is not None and not r['attempts'][-1]['semantic_result'] for r in rows),
            'attempts': sum(len(r['attempts']) for r in rows),
            'driver_lag_max_seconds': max((r['issued'] - r['scheduled'] for r in rows if r['issued'] is not None), default=None),
            'command_seconds': [a['duration_seconds'] for r in rows for a in r['attempts']],
            'end_to_end_seconds': [r['completed'] - r['scheduled'] for r in rows if r['issued'] is not None]}, rows, origin


def recovery(v, events, observation_good):
    report, rows, origin = demand_report(v, events)
    release = [e for e in events if e['record'] == 'release']
    convergence = [e for e in events if e['record'] == 'convergence']
    require(len(release) == 1 and release[0]['at'] >= origin + v['mitigation_seconds'], 'fault release command missing/early')
    deadline = origin + v['mitigation_seconds'] + v['recovery_seconds']
    stable = min((e['at'] for e in convergence if e['healthy'] is True and e['at'] >= release[0]['at']), default=None)
    windows, streak, first = [], 0, None
    for offset in range(v['mitigation_seconds'], v['mitigation_seconds'] + v['recovery_seconds'], 10):
        start, end = origin + offset, origin + offset + 10
        group = [r for r in rows if start <= r['scheduled'] < end]
        good = stable is not None and start >= stable and observation_good(start, end)
        good = good and len(group) == 50 and sum(r['kind'] == 'issue' for r in group) == 48
        for r in group:
            good = good and r['outcome'] == 'completed' and r['issued'] is not None
            if not good:
                break
            good = (r['issued'] - r['scheduled'] <= .2 and r['completed'] <= end and
                    len(r['attempts']) == 1 and r['attempts'][0]['semantic_result'] is True)
            if r['kind'] == 'issue':
                good = good and r['attempts'][0]['duration_seconds'] <= .2
        windows.append({'start': start, 'end': end, 'scheduled': len(group), 'good': bool(good)})
        if good:
            streak += 1
            if streak == 1:
                first = start
            if streak == 3:
                return {'status': 'recovered', 'release_command': release[0]['at'], 'converged': stable,
                        'first_good_window': first, 'confirmation': end, 'recovery_seconds': end - release[0]['at'],
                        'windows': windows, 'campaign': report}
        else:
            streak, first = 0, None
    return {'status': 'not recovered within observation window', 'release_command': release[0]['at'], 'converged': stable,
            'first_good_window': first, 'confirmation': None, 'deadline': deadline, 'windows': windows, 'campaign': report}


def config_guard(before, after, arm, healthy=False, releasing=False):
    """Only explicitly approved C3 target lifetime/replica and release fault delta."""
    one, two = copy.deepcopy(before), copy.deepcopy(after)
    if releasing:
        fault = two.pop('fault_state')
        require(set(fault) == {t['uid'] for t in two['targets']}, 'release target inventory differs')
        for t in two['targets']:
            state = fault[t['uid']]
            require(set(state) == {'hold_ms', 'max_requests'} and state['hold_ms'] in (0, 1000) and
                    state['max_requests'] in (2, 1024) and t['mapping']['capacity'] == state['max_requests'], 'release fault boundary')
            t['mapping']['capacity'] = 2
        require(healthy == all(f == {'hold_ms': 0, 'max_requests': 1024} for f in fault.values()), 'release convergence differs')
    elif healthy:
        require(two['scenario']['max_requests'] == 1024 and two['scenario']['hold_ms'] == 0, 'healthy gate release boundary')
        two['scenario'].update(max_requests=2, hold_ms=1000)
        for t in two['targets']:
            require(t['mapping']['capacity'] == 1024, 'actual healthy capacity')
            t['mapping']['capacity'] = 2
    if arm == 'C3':
        require(1 <= len(after['targets']) <= 2, 'C3 replicas outside delta')
        def normalize(target):
            return {k: v for k, v in target.items() if k not in {'uid', 'name'}}
        reference = normalize(one['targets'][0])
        require(all(normalize(t) == reference for t in one['targets'] + two['targets']), 'C3 image/build/mapping/runtime drift')
        one['targets'], two['targets'] = [reference], [reference]
    require(one == two, 'unapproved configuration/UID/replica/hostname drift')


class SnapshotBudgetExceeded(ValueError):
    """Typed budget failure; never infer a cause from arbitrary error text."""


class InitializationGuardError(ValueError):
    """Only fixed codes from initialization_safety may be published."""


def initialization_error(error):
    # Never publish str(error), argv, stderr, response bodies or user class names.
    if type(error) is InitializationGuardError:
        code = error.args[0] if error.args else None
        if not isinstance(code, str) or code not in {'admission_cap_exceeded', 'pod_not_ready_or_restarted', 'node_pressure',
                        'insufficient_headroom', 'database_unhealthy', 'warning_event'}:
            code = 'unknown_failure'
        return {'exception_class': 'InitializationGuardError', 'error_code': code}
    classes = ((SnapshotBudgetExceeded, 'snapshot_command_budget_exceeded'),
               (p8.subprocess.TimeoutExpired, 'command_timeout'),
               (p8.subprocess.CalledProcessError, 'command_failed'),
               (json.JSONDecodeError, 'invalid_json'), (ValueError, 'validation_failed'),
               (KeyError, 'missing_field'), (TypeError, 'invalid_type'),
               (FileNotFoundError, 'file_not_found'), (PermissionError, 'permission_denied'),
               (OSError, 'io_failure'), (RuntimeError, 'runtime_failure'),
               (KeyboardInterrupt, 'interrupted'), (SystemExit, 'system_exit'))
    for cls, code in classes:
        if type(error) is cls:
            return {'exception_class': cls.__name__, 'error_code': code}
    return {'exception_class': 'BaseException', 'error_code': 'unknown_failure'}


class Runtime(p8.Runtime):
    def __init__(self, identity, v, arm, approval, ledger, *, preparation=False):
        require(not preparation or arm == 'C0', 'healthy preparation uses CPU owner only')
        (preparation_gate if preparation else execution_gate)(identity, v, approval, ledger)
        super().__init__(identity, approval_key='P9_AZURE_APPROVED')
        self.v, self.arm = v, arm
        self.collection_deadline = threading.local()
        self.initial_uids = set()
        self.preparation = preparation
        self.hpa_name = HPA if arm == 'C3' else 'hpa-app-cpu'
        self.hp_config = next(o['data']['haproxy.cfg'] for o in render(identity, v, arm)['fixtures.json']['items']
                              if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'haproxy')
        # No caller/default kubeconfig, admin certificate or cluster run-command.
        self.prom_token = p8.p7.command(['az', 'account', 'get-access-token', '--resource', 'https://prometheus.monitor.azure.com', '--query', 'accessToken', '-o', 'tsv'])
        actual = self.j('-n', 'kube-system', 'get', 'deployment', 'keda-operator', '-o', 'json')
        image = next(c['image'] for c in actual['spec']['template']['spec']['containers'] if 'keda' in c['image'])
        require(image.rsplit(':', 1)[-1].lstrip('v') == v['keda_version'], 'actual KEDA version differs; follow matching official docs')
        require(actual['status'].get('availableReplicas', 0) >= 1, 'managed KEDA unavailable')
        for crd in ('scaledobjects.keda.sh', 'triggerauthentications.keda.sh', 'podmonitors.azmonitoring.coreos.com'):
            obj = self.j('get', 'crd', crd, '-o', 'json')
            require(any(c['type'] == 'Established' and c['status'] == 'True' for c in obj['status']['conditions']), 'required CRD unavailable')

    def k(self, *args):
        deadline = getattr(getattr(self, 'collection_deadline', None), 'at', None)
        remaining = 15 if deadline is None else min(15, deadline - time.monotonic())
        if remaining <= 0:
            raise SnapshotBudgetExceeded('snapshot command budget exceeded')
        return p8.subprocess.run(['kubectl', '--request-timeout=10s', *args], check=True, capture_output=True, text=True, timeout=remaining).stdout.strip()

    def configuration(self, config, *, inventory=None, releasing=False, initializing=False):
        require(not initializing or getattr(self, 'preparation', False) and config['hold_ms'] == 0 and config['max_requests'] == 1024, 'healthy initialization boundary')
        inventory = self.targets() if inventory is None else inventory
        # Source image is an invariant even before a new Pod can be exec'd.
        require(all(next(c['image'] for c in p['spec']['containers'] if c['name'] == 'app') == self.value['ext_authz_image']
                    for p in inventory), 'target source image drift')
        ready = [p for p in inventory if p8.p4.pod_guard(p)['ready']]
        require(self.arm == 'C3' or len(ready) == len(inventory), 'baseline readiness failure')
        hpas = self.j('-n', NS, 'get', 'hpa', '-o', 'json')['items']
        scaled = [o for o in self.j('-n', NS, 'get', 'scaledobjects', '-o', 'json')['items'] if o['spec']['scaleTargetRef']['name'] == 'ext-authz-sim']
        controller_guard(self.arm, hpas, scaled)
        deferred = set()
        if initializing:
            deferred = {p['metadata']['uid'] for p in ready} - getattr(self, 'initializing_stat_seen', set())
        elif self.arm == 'C3' and hasattr(self, 'lifecycle'):
            deferred = set(self.lifecycle.first_seen) - self.initial_uids - self.lifecycle.admin_seen
        result = super().configuration(config, target_range=(1, 2) if self.arm == 'C3' else (1, 1),
                                       haproxy_config=self.hp_config, hpa_name=self.hpa_name,
                                       target_pods=ready, releasing=releasing, stat_uids=deferred, stats_path=metric_contract()['admin_request'])
        self.admin_observations = result.pop('stat_observations')
        result['metric_contract'] = metric_contract()
        for target in result['targets']:
            bootstrap = self.admin(NS, target['name'], 'config_dump?mask=bootstrap.stats_config')
            target['metric_binding'] = metric_mapping(target['mapping'], bootstrap)
            observation = self.admin_observations[target['uid']]
            observation['native'] = native_samples(self.k('-n', NS, 'exec', target['name'], '-c', 'istio-proxy', '--',
                                                        'pilot-agent', 'request', 'GET', metric_contract()['exposition_request']))
            if admin_observation(target, observation) and initializing:
                self.initializing_stat_seen = getattr(self, 'initializing_stat_seen', set()) | {target['uid']}
        expected = render(self.value, self.v, self.arm)['fixtures.json']['items']
        if self.arm == 'C3':
            so = next(o for o in expected if o['kind'] == 'ScaledObject')
            require(scaled[0]['spec'] == so['spec'], 'ScaledObject policy drift')
            result['scaledobject_spec'] = scaled[0]['spec']
        else:
            require(result['hpa_spec'] == next(o['spec'] for o in expected if o['kind'] == 'HorizontalPodAutoscaler'), 'CPU HPA drift')
        return result

    def stats(self, actual):
        require(set(self.admin_observations) == {t['uid'] for t in actual['targets']}, 'admin target inventory drift')
        return {uid: o['values'] for uid, o in self.admin_observations.items() if o['status'] == 'observed'}

    def guard(self):
        return super().guard(hpa_name=self.hpa_name, event_timestamps=True,
                             cpu_preparation=getattr(self, 'preparation', False))

    def haproxy(self):
        import csv
        import io
        text = self.k('-n', NS, 'exec', self.pod(NS, 'app=haproxy')['metadata']['name'], '-c', 'haproxy', '--',
                      'wget', '-qO-', 'http://127.0.0.1:8404/stats;csv')
        rows = [r for r in csv.DictReader(io.StringIO(text.removeprefix('# '))) if r['pxname'] == 'ext_authz']
        def selected(name):
            matches = [r for r in rows if r['svname'] == name]
            require(len(matches) == 1, 'HAProxy server/backend row missing')
            return {'status': matches[0]['status']} | {k: int(matches[0][k]) for k in p8.p4.HAPROXY_FIELDS}
        return selected('app') | {'backend': selected('BACKEND')}

    def prom(self, query):
        emit = getattr(self, 'emit', lambda _: None)
        metadata = {'source_sha': self.value['source_sha'], 'query_sha256': digest(query), 'at': time.monotonic()}
        deadline = getattr(self.collection_deadline, 'at', None)
        timeout = 5 if deadline is None else min(5, deadline - time.monotonic())
        require(timeout > 0, 'snapshot query budget exceeded')
        emit({'record': 'prometheus_query_intent', **metadata})
        try:
            data = p8.p7.http_json(self.v['prometheus'] + '/api/v1/query?' + urllib.parse.urlencode({'query': query}), self.prom_token, timeout=timeout)
        except urllib.error.HTTPError as error:
            # Query response only, never credential requests. Preserve negative
            # bodies in protected evidence, redact a server-echoed bearer token.
            body = error.read(1024 * 1024).decode('utf-8', errors='replace').replace(self.prom_token, '[REDACTED]')
            emit({'record': 'prometheus_query_error', **metadata, 'http_status': error.code, 'body': body})
            raise
        emit({'record': 'prometheus_query_response', **metadata, 'http_status': 200, 'payload': data})
        require(data.get('status') == 'success' and data['data']['resultType'] == 'vector', 'Prometheus query error')
        return data['data']['result']

    def signal(self, pods, *, at=None, initializing=False):
        require(not initializing or getattr(self, 'preparation', False), 'initialization signal boundary')
        queries = signal_queries(self.v)
        rate, active, stamp, count = [self.prom(queries[key]) for key in ('rate', 'active', 'timestamp', 'samples')]
        rows = []
        names = {p['metadata']['name']: p['metadata']['uid'] for p in pods}
        for values in (rate, active, stamp, count):
            require(all(r['metric'].get('pod') in names and all(r['metric'].get(k) == val for k, val in
                    {'cluster': self.v['prometheus_cluster'], 'namespace': NS, 'job': metric_contract()['job'],
                     metric_contract()['cluster_label']: metric_contract()['cluster']}.items()) for r in values), 'unknown target series/metric label drift')
        for pod in pods:
            name, uid = pod['metadata']['name'], pod['metadata']['uid']
            selected = [[r for r in values if r['metric'].get('pod') == name] for values in (rate, active, stamp, count)]
            require(all(len(x) <= 1 for x in selected), 'duplicate per-Pod series')
            if not p8.p4.pod_guard(pod)['ready'] or self.admin_observations.get(uid, {}).get('status') != 'observed' or any(not x for x in selected):
                continue
            r, a, s, c = [float(x[0]['value'][1]) for x in selected]
            # One sample cannot initialize rate. Other invalid/stale values fail
            # telemetry validation even if a second Pod is still Pending.
            if c < 2:
                require(bounded(c, 0, 1), 'invalid sample count')
                continue
            rows.append({'pod': name, 'pod_uid': uid, 'status': 'observed', 'rate': r, 'active': a, 'timestamp': s, 'samples': c, 'metric_contract': metric_contract()})
        missing = [uid for uid in names.values() if uid not in {r['pod_uid'] for r in rows}]
        signal = {'status': ('uninitialized' if initializing else 'warming-new-pod') if missing else 'observed', 'missing_uids': missing,
                  'pods': rows, 'query': [], 'query_sha256': digest(scale_query(self.v))}
        if not missing:
            signal['query'] = self.prom(scale_query(self.v))
        if initializing:
            if rows:
                telemetry(rows, {r['pod_uid']: r['pod'] for r in rows}, time.time(), self.v['freshness_seconds'])
            if not missing and not signal['query']:
                signal['status'] = 'uninitialized'
            elif not missing:
                require(len(signal['query']) == 1 and bounded(float(signal['query'][0]['value'][1]), 0, 1000000), 'invalid guarded initialization query')
        else:
            self.lifecycle.signal(signal, [p8.p4.pod_guard(p) for p in pods], time.monotonic() if at is None else at, time.time())
        return signal

    def release(self, emit):
        emit({'record': 'release', 'at': time.monotonic(), 'timestamp_utc': p8.utc(), 'hold_ms': 0, 'max_requests': 1024})
        # Only experiment fault knobs, same mandatory check/native auth path.
        self.k('-n', NS, 'patch', 'configmap', 'ext-authz-hold', '--type=merge', '-p', json.dumps({'data': {'hold-ms': '0'}}))
        self.k('-n', NS, 'patch', 'sidecar', 'ext-authz-sim', '--type=merge', '-p', json.dumps({'spec': {'inboundConnectionPool': {'http': {'http2MaxRequests': 1024}}}}))


def collect_snapshot(runtime, config, before, emit, release_started):
    """Live config + per-Pod stats/logs every cycle, not just first/last UID."""
    runtime.emit = emit
    at = time.monotonic()
    runtime.collection_deadline.at = at + 30
    inventory = runtime.pods(NS, 'app=ext-authz-sim')
    emit({'record': 'replica_timeline', 'at': at, 'pods': [p8.p4.pod_guard(p) for p in inventory],
          'hpa': runtime.j('-n', NS, 'get', 'hpa', runtime.hpa_name, '-o', 'json')})
    if not hasattr(runtime, 'lifecycle'):
        runtime.lifecycle = TargetLifecycle(runtime.arm, runtime.initial_uids, runtime.v)
    runtime.lifecycle.inventory([p8.p4.pod_guard(p) for p in inventory], at)
    releasing = release_started.is_set()
    actual = runtime.configuration(config, inventory=inventory, releasing=releasing)
    healthy = releasing and all(f == {'hold_ms': 0, 'max_requests': 1024} for f in actual['fault_state'].values())
    config_guard(before, actual, runtime.arm, healthy, releasing)
    guard = runtime.guard()
    stats = runtime.stats(actual)
    runtime.lifecycle.admin(actual['targets'], runtime.admin_observations, stats, at)
    logs = runtime.logs(actual)
    # HAProxy's stdout log-format contains only timing/status/termination fields.
    hp = runtime.pod(NS, 'app=haproxy')
    hp_logs = [json.loads(line) for line in runtime.k('-n', NS, 'logs', hp['metadata']['name'], '-c', 'haproxy').splitlines() if line.startswith('{')]
    signal = runtime.signal(inventory, at=at)
    all_converged = healthy and signal['status'] == 'observed' and {p['metadata']['uid'] for p in inventory} == {t['uid'] for t in actual['targets']}
    if releasing and not healthy:
        emit({'record': 'snapshot_gap', 'at': at, 'reason': 'release-not-converged', 'fault_state': actual['fault_state']})
    snap = {'record': 'snapshot', 'at': at, 'end': time.monotonic(), 'epoch': time.time(), 'timestamp_utc': p8.utc(),
            'configuration': actual, 'guard': guard, 'stats': stats, 'logs': logs, 'haproxy': runtime.haproxy(),
            'haproxy_logs': hp_logs, 'signal': signal, 'fault_healthy': healthy, 'healthy': all_converged,
            'release_started': releasing, 'admin_stats': runtime.admin_observations, 'target_inventory': [p8.p4.pod_guard(p) for p in inventory]}
    emit(snap)
    if all_converged:
        emit({'record': 'convergence', 'at': snap['end'], 'healthy': True, 'targets': [t['uid'] for t in actual['targets']]})


class CPUStartup:
    """P9 C0 preparation only: retained startup warnings need positive recovery."""
    seconds = 90
    quiet_seconds = 15
    reasons = {'FailedGetContainerResourceMetric', 'FailedComputeMetricsReplicas'}

    def __init__(self, actual):
        require(len(actual['targets']) == 1, 'CPU startup requires one target')
        self.target = actual['targets'][0]['uid']
        self.target_name = actual['targets'][0]['name']
        self.spec = copy.deepcopy(actual['hpa_spec'])
        self.hpa_uid = self.ready_at = None
        self.history, self.candidate, self.completed = {}, None, False

    def observe(self, guard, emit, at):
        epoch = p8.p7.utc(guard['timestamp_utc']).timestamp()
        hpa = guard['cpu_hpa']; meta = hpa['metadata']
        require(meta['name'] == 'hpa-app-cpu' and meta['namespace'] == NS and isinstance(meta.get('uid'), str) and
                re.fullmatch(r'[A-Za-z0-9-]{1,64}', meta['uid']) and
                not meta.get('ownerReferences') and not meta.get('deletionTimestamp') and hpa['spec'] == self.spec, 'CPU preparation owner/spec drift')
        lifecycle = guard.get('cpu_preparation_pods')
        require(isinstance(lifecycle, list), 'CPU preparation lifecycle absent')
        pods = [p for p in lifecycle if p.get('uid') == self.target]
        require(len(lifecycle) == 1 and len(pods) == 1, 'CPU preparation target UID drift')
        pod = pods[0]
        require({'namespace', 'name', 'uid', 'creationTimestamp', 'deletionTimestamp', 'ready_conditions'} <= set(pod) and
                pod['namespace'] == NS and pod['name'] == self.target_name and isinstance(pod['creationTimestamp'], str) and
                isinstance(pod['ready_conditions'], list), 'CPU preparation lifecycle fields absent/drifted')
        require(pod['deletionTimestamp'] is None, 'CPU preparation terminating/unknown target')
        ready = [c for c in pod['ready_conditions'] if c.get('status') == 'True']
        require(len(ready) == 1, 'CPU preparation target not Ready')
        require(isinstance(ready[0].get('lastTransitionTime'), str), 'CPU preparation Ready transition absent')
        ready_at = p8.p7.utc(ready[0]['lastTransitionTime']).timestamp()
        require(p8.p7.utc(pod['creationTimestamp']).timestamp() <= ready_at, 'CPU preparation creation/Ready time invalid')
        if self.hpa_uid is None:
            self.hpa_uid, self.ready_at = meta['uid'], ready_at
        require((self.hpa_uid, self.ready_at) == (meta['uid'], ready_at), 'CPU preparation UID/Ready transition drift')
        created = p8.p7.utc(meta['creationTimestamp']).timestamp()
        require(created <= epoch and ready_at <= epoch, 'CPU preparation future lifecycle timestamp')
        events = {}
        for e in guard['events']:
            # Owner includes the exact UID; reason alone never grants an exception.
            owner = {'kind': 'HorizontalPodAutoscaler', 'name': 'hpa-app-cpu', 'namespace': NS, 'uid': self.hpa_uid}
            safe = {'uid': e.get('uid') if isinstance(e.get('uid'), str) and re.fullmatch(r'[A-Za-z0-9-]{1,64}', e['uid']) else None,
                    'reason': e.get('reason') if e.get('reason') in self.reasons | {'Unhealthy', 'FailedScheduling', 'BackOff', 'FailedMount', 'FailedRescale'} else 'OtherWarning',
                    'type': 'Warning', 'count': e.get('count') if type(e.get('count')) is int else None,
                    'owner': owner if e.get('owner') == owner else {'matches_cpu_hpa': False},
                    **{k: p8.p7.utc(e[k]).isoformat() for k in ('first_timestamp_utc', 'timestamp_utc') if k in e}}
            emit({'record': 'cpu_preparation_warning', 'at': at, 'event': safe})
            if not (e['type'] == 'Warning' and e['reason'] in self.reasons and
                    e.get('owner') == owner):
                raise InitializationGuardError('warning_event')
            first, last = [p8.p7.utc(e[k]).timestamp() for k in ('first_timestamp_utc', 'timestamp_utc')]
            require(isinstance(e.get('uid'), str) and re.fullmatch(r'[A-Za-z0-9-]{1,64}', e['uid']) and
                    e['uid'] not in events and type(e.get('count')) is int and e['count'] > 0 and
                    created <= first <= last <= epoch, 'CPU preparation warning identity/time invalid')
            signature = (e['timestamp_utc'], e['count'])
            if e['uid'] in self.history:
                previous = self.history[e['uid']]
                require(p8.p7.utc(signature[0]) >= p8.p7.utc(previous[0]) and signature[1] >= previous[1], 'CPU warning history regressed')
            if self.completed:
                require(self.history.get(e['uid']) == signature, 'CPU preparation warning recurred')
            else:
                require(0 <= epoch - p8.p7.utc(pod['creationTimestamp']).timestamp() <= self.seconds and
                        0 <= epoch - p8.p7.utc(meta['creationTimestamp']).timestamp() <= self.seconds,
                        'CPU warning outside startup lifetime')
            events[e['uid']] = signature
        require(set(self.history) <= set(events), 'CPU preparation warning history lost')
        if events != self.history:
            self.candidate = None
        self.history = events
        samples = [p for p in guard['pod_metrics'] if p['metadata']['namespace'] == NS and p['metadata']['name'] == pod['name']]
        require(len(samples) <= 1, 'ambiguous CPU preparation sample')
        metric, status, stamp, sample_evidence, current_evidence = False, False, None, None, None
        if samples:
            sample = samples[0]
            apps = [c for c in sample['containers'] if c['name'] == 'app']
            require(len(apps) <= 1, 'ambiguous app CPU sample')
            if apps:
                cpu = apps[0]['usage'].get('cpu')
                require(isinstance(cpu, str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?(?:n|u|m)?', cpu) and
                        math.isfinite(p8.quantity(cpu)) and p8.quantity(cpu) > 0, 'zero/unknown app CPU sample')
                # Resource Metrics serializes Go durations: both 38.03s and
                # 1m5.166s are observed. Keep the same <=90s semantic bound.
                duration = re.fullmatch(r'(?:([0-9]+)m)?([0-9]+(?:\.[0-9]+)?)s', sample['window'])
                seconds = float(duration[1] or 0) * 60 + float(duration[2]) if duration else None
                require(seconds is not None and 0 < seconds <= self.seconds, 'invalid CPU sample window')
                stamp = p8.p7.utc(sample['timestamp']).timestamp()
                metric = 0 <= epoch - stamp <= 30 and ready_at <= stamp - seconds
                sample_evidence = {'timestamp_epoch': stamp, 'window_seconds': seconds, 'app_cpu': cpu}
        active = [c for c in hpa['status'].get('conditions', []) if c['type'] == 'ScalingActive']
        able = [c for c in hpa['status'].get('conditions', []) if c['type'] == 'AbleToScale']
        require(len(able) <= 1 and all(c['status'] == 'True' for c in able), 'CPU HPA unable to scale')
        require(len(active) <= 1, 'ambiguous CPU HPA condition')
        current = hpa['status'].get('currentMetrics', [])
        empty_startup = (current == [{'type': ''}] and len(active) == 1 and active[0]['status'] == 'False' and
                         active[0].get('reason') in self.reasons)
        if current and not empty_startup:
            require(len(current) == 1 and current[0]['type'] == 'ContainerResource' and
                    current[0]['containerResource']['name'] == 'cpu' and current[0]['containerResource']['container'] == 'app', 'CPU HPA metric drift')
            value = current[0]['containerResource']['current']
            status = (type(value.get('averageUtilization')) is int and value['averageUtilization'] > 0 and
                      isinstance(value.get('averageValue'), str) and
                      re.fullmatch(r'[0-9]+(?:\.[0-9]+)?(?:n|u|m)?', value['averageValue']) is not None and
                      math.isfinite(p8.quantity(value['averageValue'])) and p8.quantity(value['averageValue']) > 0)
            current_evidence = {'container': 'app', 'name': 'cpu',
                                'averageUtilization': value.get('averageUtilization') if type(value.get('averageUtilization')) is int else None,
                                'averageValue': value.get('averageValue') if isinstance(value.get('averageValue'), str) and
                                re.fullmatch(r'[0-9]+(?:\.[0-9]+)?(?:n|u|m)?', value['averageValue']) else None}
        last = max((p8.p7.utc(e['timestamp_utc']).timestamp() for e in guard['events']), default=0)
        transition = p8.p7.utc(active[0]['lastTransitionTime']).timestamp() if active else None
        recovered = (len(active) == 1 and active[0]['status'] == 'True' and
                     last <= transition <= epoch)
        if active and active[0]['status'] != 'True':
            require(active[0].get('reason') in self.reasons, 'CPU HPA non-startup failure')
        generation = hpa['status'].get('observedGeneration')
        require(generation is None or type(generation) is int and generation == meta.get('generation'), 'CPU HPA observed generation drift')
        positive = bool(able) and metric and status and recovered and epoch - last >= self.quiet_seconds
        if self.completed:
            require(positive, 'CPU preparation regressed after recovery')
        elif positive:
            # Retained warnings require two advancing valid samples and a quiet
            # HPA interval. An already healthy no-warning baseline needs no wait.
            if not events or self.candidate and at - self.candidate[0] >= self.quiet_seconds and stamp > self.candidate[1]:
                self.completed = True
            elif self.candidate is None:
                self.candidate = (at, stamp)
        else:
            self.candidate = None
        emit({'record': 'cpu_preparation_poll', 'at': at, 'target_uid': self.target, 'hpa_uid': self.hpa_uid,
              'ready_since_epoch': ready_at, 'sample_epoch': stamp, 'valid_ready_window': bool(metric),
              'sample': sample_evidence, 'hpa_current_cpu': current_evidence, 'hpa_spec': self.spec,
              'scaling_active': bool(active and active[0]['status'] == 'True'), 'hpa_transition_epoch': transition,
              'hpa_metric_recovered': bool(status and recovered), 'status': 'ready' if self.completed else 'pending',
              'warning_history': copy.deepcopy(self.history), 'measured_denominator': False})
        return self.completed


def initialization_safety(guard, *, cpu_startup=None, emit=None, at=None):
    def check(condition, code):
        if not condition:
            raise InitializationGuardError(code)
    admitted = guard['admission']
    check(len(admitted['pods']) <= 4 and all(v['cpu'] <= 1.5 + 1e-9 and v['memory'] <= 2048 * 1024**2
            for v in admitted['conservative_sum'].values()), 'admission_cap_exceeded')
    check(guard['pods'] and all(p['ready'] and p['phase'] == 'Running' and not p['reason'] and
            all(c['ready'] and c['restarts'] == 0 and c['last_termination'] not in {'OOMKilled', 'Error'} for c in p['containers'])
            for p in guard['pods']), 'pod_not_ready_or_restarted')
    check(guard['nodes'] and all(n['conditions'] == {'Ready': 'True', 'MemoryPressure': 'False', 'DiskPressure': 'False', 'PIDPressure': 'False'} for n in guard['nodes']), 'node_pressure')
    check(any(n['schedulable'] and n['cpu_free'] >= .15 and n['memory_free'] >= 192 * 1024**2 for n in guard['node_headroom']), 'insufficient_headroom')
    check(guard['postgres']['query_ok'] and guard['postgres']['connections'] < guard['postgres']['max_connections'] - guard['postgres']['reserved'], 'database_unhealthy')
    if cpu_startup is None:
        check(not guard['events'], 'warning_event')
        return True
    return cpu_startup.observe(guard, emit, at)


def healthy_initialize(runtime, v, journey, emit, *, clock=time.monotonic, wait=time.sleep):
    """One existing healthy journey, then bounded read-only polling. No flags set.

    Caller holds the append-only initialization ledger lock. Preparation authority
    never grants the measure path or KEDA mutation/authentication success.
    """
    started = stage_started = clock()
    stage = 'preparation_boundary'
    try:
        require(getattr(runtime, 'preparation', False) and runtime.arm == 'C0', 'preparation runtime required')
        runtime.emit = emit
        runtime.collection_deadline.at = clock() + 30
        config = {'max_requests': 1024, 'hold_ms': 0, 'logical_operations': 24, 'concurrency': 12,
                  'waves': (v['mitigation_seconds'] + v['recovery_seconds']) // 5, 'wave_interval_seconds': 5}
        stage, stage_started = 'configuration', clock()
        before = runtime.configuration(config, initializing=True)
        require(len(before['targets']) == 1, 'healthy initialization starts with one Ready target')
        initial = {t['uid'] for t in before['targets']}
        cpu_startup = CPUStartup(before)
        settle_deadline = started + CPUStartup.seconds
        stage, stage_started = 'readiness_resource_guard', clock()
        while True:
            complete = initialization_safety(runtime.guard(), cpu_startup=cpu_startup, emit=emit, at=clock())
            require(clock() <= settle_deadline, 'CPU preparation settling timeout')
            if complete:
                break
            wait(min(15, settle_deadline - clock()))
            require(clock() < settle_deadline, 'CPU preparation settling timeout')
            runtime.collection_deadline.at = min(clock() + 30, settle_deadline)
            actual = runtime.configuration(config, initializing=True)
            require(actual == before, 'CPU settling configuration drift')
        stage, stage_started = 'baseline_stats', clock()
        stats_before = copy.deepcopy(runtime.stats(before))
        stage, stage_started = 'baseline_logs', clock()
        logs_before = runtime.logs(before)
        emit({'record': 'healthy_journey_intent', 'source_sha': runtime.value['source_sha'], 'at': clock(),
              'target_uids': sorted(initial), 'stats_before': stats_before, 'measured_denominator': False, 'invocations': 1})
        stage, stage_started = 'healthy_journey', clock()
        journey_started = stage_started
        try:
            journey_path = journey(90)  # Existing journey only; never retry for telemetry.
        finally:
            # Keep actual request/check evidence on journey failure as well. The
            # protected client audit separately retains every API intent/response.
            stage, stage_started = 'journey_accounting', clock()
            deadline = clock() + v['ingestion_seconds'] + 3 * v['scrape_seconds']
            runtime.collection_deadline.at = min(clock() + 30, deadline)
            delta = p8.path_delta(logs_before, runtime.logs(before))
            emit({'record': 'healthy_journey_accounting', 'at': clock(), 'measured_denominator': False,
                  'ingress_http_records': sum(not (int(r['status']) == 0 and r['detail'] == 'filter_chain_not_found' and r['cluster'] in {None, '-'}) for r in delta['proxies']['ingress']),
                  'authorization_checks': len(delta['checks']), 'log_delta': delta})
            stage, stage_started = 'healthy_journey', journey_started
        stage, stage_started = 'journey_validation', clock()
        client = p8.p7.operations.validate(journey_path)
        journey_rows = p8.p4.rows(journey_path)
        require(client['validity'] == 'valid' and client['completion'] == 'success' and client['phase'] == 'warmup' and
                client['source_sha'] == runtime.value['source_sha'] and journey_rows[0]['dirty'] is False and
                client['transport'] == p8.measurement_transport(runtime.value), 'healthy journey provenance/completion differs')
        attempts = {r['attempt_id']: r['operation_id'] for r in journey_rows if r['record'] == 'attempt'}
        require(len(attempts) == 9 and sum(r['record'] == 'auxiliary_event' and r['kind'] == 'fixture' and
                r['name'] == 'shared_gate_auxiliary_scope' and r['outcome'] == 'success' for r in journey_rows) == 1,
                'healthy journey attempt/auxiliary scope absent')
        auxiliary = journey_rows[0]['run_id'] + '-auxiliary'
        known = attempts | {auxiliary + '-attempt-1': auxiliary}
        window_start = p8.p7.utc(journey_rows[0]['started_at_utc'])
        # Existing journey timestamps have second precision; include that final second.
        window_end = p8.p7.utc(journey_rows[-1]['ended_at_utc']) + timedelta(seconds=1)
        while True:
            stage, stage_started = 'telemetry_configuration', clock()
            require(clock() < deadline, 'healthy initialization polling timeout; do not repeat journey')
            runtime.collection_deadline.at = min(clock() + 30, deadline)
            actual = runtime.configuration(config, initializing=True)
            require({t['uid'] for t in actual['targets']} == initial and actual == before, 'initialization config/UID drift')
            stage, stage_started = 'telemetry_resource_guard', clock()
            initialization_safety(runtime.guard(), cpu_startup=cpu_startup, emit=emit, at=clock())
            stage, stage_started = 'telemetry_signal', clock()
            pods = runtime.targets()
            require({p['metadata']['uid'] for p in pods} == initial, 'initialization live UID drift')
            signal = runtime.signal(pods, initializing=True)
            emit({'record': 'healthy_telemetry_poll', 'at': clock(), 'configuration': actual,
                  'admin_stats': runtime.admin_observations, 'signal': signal, 'deadline': deadline})
            if signal['status'] == 'observed':
                require(clock() <= deadline, 'healthy initialization polling timeout')
                stage, stage_started = 'positive_path', clock()
                logs_after = runtime.logs(actual)
                delta = p8.path_delta(logs_before, logs_after)
                ingress = delta['proxies']['ingress']
                http = [r for r in ingress if not (int(r['status']) == 0 and r['detail'] == 'filter_chain_not_found' and r['cluster'] in {None, '-'})]
                checks, target = delta['checks'], delta['proxies']['target']
                require(checks and len(checks) == len(target) == len(http), 'healthy shared path missing/zero/mismatched')
                p8.p4.gate.validate_checks(checks)
                require(all(c['decision'] == 'ALLOW' and c['controlled_deny'] is False and
                            c['credential_values_absent'] is True and c['body_absent'] is True and c['haproxy_hop'] is True and
                            c['attempt_id'] in known and known[c['attempt_id']] == c['operation_id'] and
                            window_start <= p8.p7.utc(c['timestamp_utc']) < window_end for c in checks),
                        'healthy shared check denied/unattributed/outside journey window')
                require(set(attempts) <= {c['attempt_id'] for c in checks}, 'healthy developer attempt bypassed shared path')
                mapping = actual['targets'][0]['mapping']
                require(all(int(r['status']) == 200 and r['detail'] == 'via_upstream' and
                            r['cluster'] in {mapping['cluster_name'], mapping['alt_stat_name']} for r in target),
                        'healthy target path denied/mismapped')
                # Existing journey asserts private anonymous 401/404; those are native
                # auth outcomes after an ALLOW check, never ext_authz denial/failure.
                require(all(int(r['status']) in {200, 201, 401, 404} and r['detail'] == 'via_upstream' and
                            re.fullmatch(r'outbound\|3000\|\|forgejo-http\.forgejo\.svc(?:\.cluster\.local)?;?', r['cluster'] or '') for r in http),
                        'healthy ingress path denied/mismapped')
                uid = actual['targets'][0]['uid']
                total = p8.p4.by_suffix(runtime.stats(actual)[uid])['upstream_rq_total']
                if uid in stats_before:
                    total -= p8.p4.by_suffix(stats_before[uid])['upstream_rq_total']
                    require(total == len(target), 'healthy target counter/log delta mismatch')
                else:
                    require(total == len(logs_after['proxies']['target'][uid]), 'healthy target lifetime counter/log mismatch')
                require(clock() <= deadline, 'healthy initialization polling timeout')
                result = {'record': 'healthy_initialization_complete', 'source_sha': runtime.value['source_sha'],
                          'at': clock(), 'metric_contract': metric_contract(), 'journey_invocations': 1,
                          'ingress_http_records': len(http), 'authorization_checks': len(delta['checks']),
                          'request_accounting': 'actual same-window server log deltas, not 1:1 operation/HTTP inference',
                          'log_delta': delta, 'journey_sha256': hashlib.sha256(Path(journey_path).read_bytes()).hexdigest(),
                          'correlated_attempt_checks': {aid: sum(c['attempt_id'] == aid for c in checks) for aid in attempts},
                          'auxiliary_checks': sum(c['operation_id'] == auxiliary for c in checks),
                          'target_requests': total, 'counter_accounting': 'observed-start-delta' if uid in stats_before else 'whole-UID-counter-and-log',
                          'proxy_linkage': 'same-window count/cluster/status; proxy format has no per-request correlation IDs',
                          'ready_for_keda_authentication': True, 'runtime_preflight_passed': False}
                emit(result)
                return result
            stage, stage_started = 'telemetry_configuration', clock()
            require(clock() < deadline, 'healthy initialization polling timeout; do not repeat journey')
            wait(min(v['scrape_seconds'], deadline - clock()))
    except BaseException as error:
        at = clock()
        emit({'record': 'healthy_initialization_failure', 'source_sha': runtime.value['source_sha'],
              'at': at, 'stage': stage, 'elapsed_seconds': at - started,
              'stage_elapsed_seconds': at - stage_started, **initialization_error(error),
              'runtime_preflight_passed': False, 'ready_for_keda_authentication': False,
              'measured_denominator': False})
        raise


def initialize(identity, v, approval, context, private, output, ledger):
    """Approved preparation entrypoint. Never provisions IAM/images or mutates KEDA."""
    import fcntl
    output, private, ledger = Path(output), Path(private), Path(ledger)
    require(private.is_dir() and private.stat().st_mode & 0o777 == 0o700 and
            not (private / 'healthy-journey').exists(), 'new protected healthy fixture directory required')
    output.mkdir(mode=0o700)
    with ledger.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stream.seek(0)
        prior = [json.loads(line) for line in stream if line.strip()]
        require(not any(e.get('record') == 'healthy_journey_intent' and e['source_sha'] == identity['source_sha'] for e in prior), 'healthy journey already consumed; new approval required')
        runtime = Runtime(identity, v, 'C0', approval, [], preparation=True)
        def emit(row):
            line = json.dumps(row) + '\n'
            with (output / 'events.jsonl').open('a') as events: events.write(line)
            stream.seek(0, 2); stream.write(line); stream.flush(); os.fsync(stream.fileno())
        def journey(timeout):
            env = dict(os.environ, JOURNEY_ENVIRONMENT='azure-aks', RESULT_CONTEXT_FILE=str(Path(context).resolve()),
                       RESULTS_ROOT=str((output / 'journey').resolve()), RESULT_PHASE='warmup',
                       JOURNEY_DIR=str((private / 'healthy-journey').resolve()), JOURNEY_GATE_CORRELATION='1', JOURNEY_GATE_AUX_CORRELATION='1', RECOVERY_FIXTURE='1')
            # Existing script retains TLS/native auth/private-repo checks and PAT ID.
            p8.subprocess.run(['timeout', '--signal=TERM', '--kill-after=5s', str(timeout) + 's',
                               'bash', str(ROOT / 'tests/e2e/forgejo-developer-journey.sh'), 'create'],
                              env=env, check=True, timeout=timeout + 10)
            paths = list((output / 'journey').glob('*/events.jsonl'))
            require(len(paths) == 1, 'healthy journey raw inventory differs')
            return paths[0]
        try:
            healthy_initialize(runtime, v, journey, emit)
        except BaseException as error:
            # Publication is the fixed-field event above. Full exception chains may
            # include sensitive command output/paths and stay in private mode0600.
            import traceback
            try:
                with open(private / 'initialization-failure.txt', 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as trace:
                    traceback.print_exception(type(error), error, error.__traceback__, file=trace)
            except OSError:
                emit({'record': 'healthy_initialization_private_diagnostic_failure',
                      'source_sha': identity['source_sha'], 'error_code': 'private_diagnostic_write_failed'})
            raise
        finally:
            runtime.prom_token = None


def _measure(identity, v, arm, phase, output, approval_path, frozen_path, ledger_path):
    plan(v); require(arm in ARMS and phase in {'calibration', 'measured'}, 'arm/phase')
    output = Path(output); output.mkdir(mode=0o700)
    ledger_path = Path(ledger_path)
    # A single append-only ledger per approval; flock prevents concurrent/budget bypass.
    import fcntl
    with ledger_path.open('a+') as ledger_file:
        fcntl.flock(ledger_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger_file.seek(0)
        ledger = [json.loads(line) for line in ledger_file if line.strip()]
        entry = {'source_sha': identity['source_sha'], 'plan_sha256': digest(v), 'arm': arm, 'phase': phase, 'timestamp_utc': p8.utc()}
        approval = load(approval_path)
        # Count before any workload. Failed runs consume budget too.
        execution_gate(identity, v, approval, ledger + [entry])
        ledger_file.seek(0, 2); ledger_file.write(json.dumps(entry) + '\n'); ledger_file.flush(); os.fsync(ledger_file.fileno())
        manifest = {'source_sha': identity['source_sha'], 'identity': identity, 'plan': v, 'metric_contract': metric_contract(),
                    'transport': p8.measurement_transport(identity),
                    'fixture_sha256': digest({k: os.environ[k] for k in ('DEV_USER', 'ISSUE_NUMBER', 'ISSUE_TITLE', 'EXPECTED_MAIN_SHA')}),
                    'schedule_sha256': digest(schedule(v)), 'slo_sha256': hashlib.sha256(SLO.read_bytes()).hexdigest(),
                    'render_sha256': {a: digest(render(identity, v, a)) for a in ARMS}}
        if phase == 'measured':
            frozen_manifest = load(frozen_path)
            require(all(frozen_manifest[k] == val for k, val in manifest.items()) and frozen_manifest['calibration_sha256'], 'measured comparison not frozen')
        runtime = Runtime(identity, v, arm, approval, ledger + [entry])
        config = {'max_requests': 2, 'hold_ms': 1000, 'logical_operations': 24, 'concurrency': 12,
                  'waves': (v['mitigation_seconds'] + v['recovery_seconds']) // 5, 'wave_interval_seconds': 5}
        baseline = runtime.configuration(config)
        runtime.initial_uids = {t['uid'] for t in baseline['targets']}
        require(len(runtime.initial_uids) == 1, 'every arm starts at one target replica')
        save(output / 'configuration.json', manifest | {'arm': arm, 'phase': phase, 'baseline': baseline})
        lock, stop, release_started, failed = threading.Lock(), threading.Event(), threading.Event(), threading.Event()
        def emit(row):
            with lock, (output / 'events.jsonl').open('a') as stream:
                stream.write(json.dumps(row, separators=(',', ':')) + '\n')
        run_started = time.monotonic()
        start_utc = p8.utc()
        save(output / 'before.json', {'timestamp_utc': start_utc})
        emit({'record': 'run_start', 'source_sha': identity['source_sha'], 'timestamp_utc': start_utc, 'arm': arm, 'phase': phase,
              'transport': p8.measurement_transport(identity), 'fingerprint': digest(manifest)})
        path = f'/api/v1/repos/{os.environ["DEV_USER"]}/journey/issues/{int(os.environ["ISSUE_NUMBER"])}'
        expected = (int(os.environ['ISSUE_NUMBER']), os.environ['ISSUE_TITLE'])
        prefix = str(uuid.uuid4())
        def issue(op, index):
            result = p8.request(path, {'Authorization': 'token ' + os.environ['DEV_TOKEN'],
                'x-operation-id': prefix + '-' + op, 'x-attempt-id': prefix + '-' + op + '-attempt-' + str(index)}, expected)
            # p8.request has no native-vs-overload header. Require a concurrent
            # healthy direct sentinel and record the scoped experiment context.
            result['overload'] = result['status'] in {403, 429, 503} and sentinel_ok.is_set()
            return result
        def git(op, index):
            return p8.git_read(prefix + '-' + op, prefix + '-' + op + '-attempt-1')
        sentinel_ok = threading.Event()
        def sentinel():
            while not stop.is_set():
                result = p8.request(path, {'Authorization': 'token ' + os.environ['DEV_TOKEN']}, expected, direct=True)
                emit({'record': 'sentinel', 'at': time.monotonic(), 'result': result})
                if result['semantic_result']:
                    sentinel_ok.set()
                else:
                    sentinel_ok.clear(); failed.set()
                stop.wait(1)
        def monitor():
            while not stop.is_set():
                try:
                    collect_snapshot(runtime, config, baseline, emit, release_started)
                except Exception:
                    emit({'record': 'monitor_failure', 'at': time.monotonic()}); failed.set(); return
                stop.wait(1)
        def release(_due):
            release_started.set()
            release_future.append(workers.submit(runtime.release, emit))
        release_future = []
        try:
            collect_snapshot(runtime, config, baseline, emit, release_started)
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as workers:
                monitors = [workers.submit(sentinel), workers.submit(monitor)]
                try:
                    # Require healthy direct/native path before any experiment arrivals.
                    require(sentinel_ok.wait(15) and not failed.is_set(), 'direct native-auth sentinel preflight')
                    drive(v, arm, issue, git, emit, release,
                          monitor_error=lambda: failed.is_set() or time.monotonic() - run_started >= 570)
                finally:
                    stop.set()
                for future in monitors + release_future:
                    future.result()
            collect_snapshot(runtime, config, baseline, emit, release_started)
            require(not failed.is_set() and time.monotonic() - run_started <= 600, 'monitor/guard/deadline failure; preserve invalid run')
            end_utc = p8.utc()
            save(output / 'after.json', {'timestamp_utc': end_utc})
            emit({'record': 'run_end', 'timestamp_utc': end_utc, 'completed': True})
        except BaseException:
            emit({'record': 'run_failure', 'timestamp_utc': p8.utc(), 'completed': False})
            raise
        finally:
            runtime.prom_token = None


def measure(identity, v, arm, phase, output, approval_path, frozen_path, ledger_path):
    try:
        return _measure(identity, v, arm, phase, output, approval_path, frozen_path, ledger_path)
    except BaseException:
        directory = Path(output)
        if directory.is_dir() and not (directory / 'invocation-failure.json').exists():
            save(directory / 'invocation-failure.json', {'record': 'invocation-failure', 'source_sha': identity.get('source_sha'),
                 'arm': arm, 'phase': phase, 'timestamp_utc': p8.utc()})
        raise


def transition(identity, v, target, output, approval):
    """Plan only: reviewer/operator performs each mutation after observing its gate.

    No atomic apply can safely remove a CPU HPA and create a KEDA owner together.
    The generated plan names exact objects, waits, and fail-closed ownership tests.
    """
    p8.identity(identity); plan(v); require(target in {'C0', 'C3'}, 'transition target')
    require(approval['identity'] == identity and approval['source_sha'] == identity['source_sha'], 'transition identity approval')
    steps = ([{'delete': 'HorizontalPodAutoscaler/hpa-app-cpu', 'wait_absent': True},
              {'assert': 'zero HPA/ScaledObject target owners'},
              {'apply': ['TriggerAuthentication/p9-prometheus', 'ScaledObject/p9-proxy']},
              {'assert': 'one HPA p9-proxy owned by exact ScaledObject UID; no CPU HPA'}] if target == 'C3' else
             [{'delete': 'ScaledObject/p9-proxy', 'wait_absent': True},
              {'wait_absent': 'HorizontalPodAutoscaler/p9-proxy (foreground dependent deletion)'},
              {'assert': 'zero HPA/ScaledObject target owners'},
              {'apply': ['HorizontalPodAutoscaler/hpa-app-cpu']}, {'assert': 'one unowned CPU HPA; no ScaledObject'}])
    save(output, {'identity': identity, 'namespace': NS, 'target': target, 'steps': steps,
                  'manual_scale_success': False, 'rollback': 'remove CUSTOM policy first on uncertainty; preserve original controller manifests; no overlapping owners'})


def common_guards(snapshots, baseline, arm):
    require(len(snapshots) >= 3, 'missing observation snapshots')
    fixed = {p['uid']: p for p in snapshots[0]['guard']['pods'] if not p['name'].startswith('ext-authz-sim-')}
    first_targets = {t['uid'] for t in baseline['targets']}
    seen = set()
    pending_since = {}
    warm_epochs = [s['epoch'] for s in snapshots if s['signal'].get('status') == 'warming-new-pod']
    previous = None
    for s in snapshots:
        config_guard(baseline, s['configuration'], arm, s.get('fault_healthy', s['healthy']), s.get('release_started', False))
        guard = s['guard']
        admitted = guard['admission']
        require(len(admitted['pods']) <= 4 and all(total['cpu'] <= 1.5 + 1e-9 and total['memory'] <= 2048 * 1024**2 for total in admitted['conservative_sum'].values()), 'actual admitted cap exceeded')
        if previous:
            for uid, images in previous['guard']['runtime_images'].items():
                current = guard['runtime_images'].get(uid)
                require(current is not None, 'Pod lifetime disappeared without final evidence')
                if uid in fixed or uid in first_targets:
                    require(current == images, 'runtime image/lifetime drift')
                else:
                    require(arm == 'C3' and all(current.get(name) == image for name, image in images.items()), 'new Pod runtime image drift')
        require({p['uid']: p for p in guard['pods'] if p['uid'] in fixed} == fixed and
                {p['uid'] for p in guard['pods'] if not p['name'].startswith('ext-authz-sim-')} == set(fixed), 'stable/helper Pod drift')
        require(guard['nodes'] and all(n['conditions'] == {'Ready': 'True', 'MemoryPressure': 'False', 'DiskPressure': 'False', 'PIDPressure': 'False'} for n in guard['nodes']), 'node pressure')
        require(guard['postgres']['query_ok'] and guard['postgres']['connections'] < guard['postgres']['max_connections'] - guard['postgres']['reserved'], 'DB health')
        warming = arm == 'C3' and s['signal'].get('status') == 'warming-new-pod'
        # A guarded empty query during a new Pod's first two samples is explicit
        # no-data. It cannot prove controller health or recovery. Existing-Pod
        # errors and scheduling failure are never covered by this exception.
        require(not any(e['reason'] in {'FailedScheduling', 'FailedGetResourceMetric'} for e in guard['events']), 'scheduling/resource metric error')
        for e in guard['events']:
            if e['reason'] in {'FailedComputeMetricsReplicas', 'FailedGetExternalMetric'}:
                require(arm == 'C3' and e.get('timestamp_utc') and any(abs(p8.p7.utc(e['timestamp_utc']).timestamp() - epoch) <= 35 for epoch in warm_epochs), 'metric failure outside bounded new-Pod warmup')
        require(any(n['schedulable'] and n['cpu_free'] >= .15 and n['memory_free'] >= 192 * 1024**2 for n in guard['node_headroom']), 'node headroom')
        require(guard['node_metrics'] and guard['pod_metrics'], 'missing node/Pod metrics')
        for p in guard['pods']:
            new_target = arm == 'C3' and p['uid'] not in fixed and p['uid'] not in first_targets
            pending_since.setdefault(p['uid'], s['at'])
            require((p['phase'] == 'Running' or new_target and p['phase'] == 'Pending' and s['at'] - pending_since[p['uid']] <= 90) and not p['reason'] and
                    all(c['last_termination'] not in {'OOMKilled', 'Error'} and c['restarts'] == 0 for c in p['containers']), 'Pod lifecycle failure')
            require(p['ready'] or new_target and s['at'] - pending_since[p['uid']] <= 90, 'unbounded new-Pod readiness gap')
            if p['uid'] in fixed or p['uid'] in first_targets:
                require(p['ready'] and all(c['ready'] for c in p['containers']), 'baseline readiness failure')
            obs = [m for m in guard['pod_metrics'] if m['metadata']['name'] == p['name']]
            # A newly admitted C3 Pod can await its first resource metric. It
            # cannot contribute to recovery until full observations are present.
            if not obs and warming and arm == 'C3' and p['uid'] not in first_targets:
                continue
            require(len(obs) == 1 and {c['name'] for c in p['containers']} <= {c['name'] for c in obs[0]['containers']}, 'missing container metric')
            age = (p8.p7.utc(guard['timestamp_utc']) - p8.p7.utc(obs[0]['timestamp'])).total_seconds()
            require(0 <= age <= 2 * p8.metric_window(obs[0]['window']), 'stale resource metric')
        hpa = guard['hpa']
        cond = {c['type']: c for c in hpa.get('conditions', [])}
        require(cond.get('AbleToScale', {}).get('status') == 'True' and 1 <= hpa['desiredReplicas'] <= 2, 'controller scale/status failure')
        if not warming:
            require(cond.get('ScalingActive', {}).get('status') == 'True' and hpa.get('currentMetrics'), 'controller metric/status failure')
        else:
            require(cond.get('ScalingActive', {}).get('status') == 'True' or
                    cond.get('ScalingActive', {}).get('reason') == 'FailedGetExternalMetric', 'unexpected controller failure in new-Pod warmup')
        if arm != 'C3':
            require(hpa['currentReplicas'] == hpa['desiredReplicas'] == 1, 'unexpected CPU HPA replica delta')
        uids = {t['uid'] for t in s['configuration']['targets']}
        require(arm == 'C3' or uids == first_targets, 'non-scaling UID delta')
        require(seen <= uids, 'departed target lacks final counter/log observation')
        seen |= uids
        if previous:
            require(s['at'] > previous['at'], 'snapshot order')
        previous = s
    return seen


def path_accounting(arm, snapshots):
    first, last = snapshots[0], snapshots[-1]
    target_uids = {uid for s in snapshots for uid in s['stats']}
    inventory_uids = {p['uid'] for s in snapshots for p in s.get('target_inventory', [])}
    require(set(last['stats']) == target_uids and inventory_uids <= target_uids, 'target lifetime lacks final counters')
    totals = {'target_admitted': 0, 'target_rejected': 0}
    checks, rejected, target_records = [], 0, 0
    for uid in target_uids:
        life = [s for s in snapshots if uid in s['stats']]
        initial = p8.p4.by_suffix(first['stats'][uid]) if uid in first['stats'] else None
        previous = initial
        for s in life:
            current = p8.p4.by_suffix(s['stats'][uid])
            require(set(current) == set(p8.p4.SUFFIXES) and (previous is None or all(current[k] >= previous[k] for k in p8.p4.SUFFIXES if k not in {'upstream_rq_active', 'upstream_rq_pending_active'})), 'counter reset/missing series')
            require(current['upstream_rq_pending_active'] == 0 and current['upstream_rq_pending_overflow'] == (initial['upstream_rq_pending_overflow'] if initial is not None else 0), 'competing pending overflow')
            previous = current
        require(previous['upstream_rq_active'] == 0 and (initial is None or initial['upstream_rq_active'] == 0), 'target boundary inflight')
        totals['target_admitted'] += previous['upstream_rq_total'] - initial['upstream_rq_total'] if initial is not None else previous['upstream_rq_total']
        totals['target_rejected'] += previous['upstream_rq_active_overflow'] - initial['upstream_rq_active_overflow'] if initial is not None else previous['upstream_rq_active_overflow']
        def target_log(s):
            return s['logs']['proxies']['target'].get(uid, [])
        before = target_log(first)
        after = target_log(life[-1])
        require(after[:len(before)] == before, 'target log rotated')
        delta = after[len(before):]
        target_records += len(delta)
        rejected += sum(int(r['status']) == 503 and 'overflow' in r['detail'] for r in delta)
    # App logs are aggregated by Pod at collection; use check_id, never list order
    # across replicas. Every new check must retain valid operation/attempt linkage.
    old = {c['check_id'] for c in first['logs']['checks']}
    for c in last['logs']['checks']:
        if c['check_id'] not in old:
            checks.append(c)
    if checks:
        p8.p4.gate.validate_checks(checks)
    require(all(c['decision'] == 'ALLOW' and not c['controlled_deny'] for c in checks), 'native/controlled denial mixed with overload')
    require(len(checks) == totals['target_admitted'] and rejected == totals['target_rejected'] and
            target_records == sum(totals.values()), 'target dispatch/admission/rejection evidence differs')
    ingress = []
    for uid, records in last['logs']['proxies']['ingress'].items():
        before = first['logs']['proxies']['ingress'][uid]
        require(records[:len(before)] == before, 'ingress log rotated')
        ingress += records[len(before):]
    ingress = [r for r in ingress if not (int(r['status']) == 0 and r['detail'] == 'filter_chain_not_found' and r['cluster'] in {None, '-'})]
    require(all(int(r['status']) == 200 or r['detail'] in {'ext_authz_error', 'ext_authz_denied'} for r in ingress), 'native authorization/transport denial confounder')
    hp0, hp1 = first['haproxy_logs'], last['haproxy_logs']
    require(hp1[:len(hp0)] == hp0, 'HAProxy log rotated')
    hp = hp1[len(hp0):]
    shed = sum(r['status'] == 429 and r['termination'].startswith('PR') for r in hp)
    queued = sum(r['status'] == 503 and r['termination'].startswith('sQ') for r in hp)
    errors = sum(r['termination'][:2] not in {'--', 'PR', 'sQ'} for r in hp)
    require(all(bounded(r['queue_ms'], -1, 10000) for r in hp), 'HAProxy queue timing missing')
    require(arm == 'C2' or all(r['queue_ms'] == 0 for r in hp), 'competing HAProxy queue')
    require(len(hp) == len(ingress) and errors == 0, 'check/ingress/HAProxy path error')
    result = accounting(arm, {'checks': len(hp), **totals, 'admission_shed': shed, 'queue_timeout': queued,
        'queue_start': first['haproxy']['qcur'] + first['haproxy']['backend']['qcur'],
        'queue_end': last['haproxy']['qcur'] + last['haproxy']['backend']['qcur'],
        'inflight_start': first['haproxy']['scur'], 'inflight_end': last['haproxy']['scur'], 'path_errors': errors})
    require(p8.p4.backend_requests(last['haproxy']) - p8.p4.backend_requests(first['haproxy']) == target_records and
            p8.p4.backend_requests(last['haproxy']['backend']) - p8.p4.backend_requests(first['haproxy']['backend']) == target_records + queued,
            'HAProxy server/backend dispatch mapping differs')
    if arm != 'C2':
        require(last['haproxy']['backend']['qmax'] == 0 and last['haproxy']['qmax'] == 0, 'competing sampled backend queue')
    result['queue_ms'] = [r['queue_ms'] for r in hp]
    result['admitted_checks'] = checks
    return result


def validate(directory):
    directory = Path(directory)
    manifest = load(directory / 'configuration.json')
    v, arm, identity = manifest['plan'], manifest['arm'], manifest['identity']
    plan(v); p8.identity(identity); require(arm in ARMS, 'arm')
    require(manifest['metric_contract'] == metric_contract() and manifest['baseline']['metric_contract'] == metric_contract(), 'saved metric contract drift')
    require(manifest['source_sha'] == identity['source_sha'] and manifest['schedule_sha256'] == digest(schedule(v)) and
            manifest['slo_sha256'] == hashlib.sha256(SLO.read_bytes()).hexdigest() and
            manifest['render_sha256'] == {a: digest(render(identity, v, a)) for a in ARMS}, 'manifest drift')
    events = p8.p4.rows(directory / 'events.jsonl')
    require(events[0]['record'] == 'run_start' and events[-1]['record'] == 'run_end' and events[-1]['completed'] and
            not any(e['record'] in {'run_failure', 'monitor_failure'} for e in events), 'failed/incomplete run')
    require(events[0]['transport'] == manifest['transport'] and events[0]['transport'] == p8.p7.operations.transport(events[0]['transport']['endpoint'], 'azure-aks',
            events[0]['transport'].get('dns_client_override')) and urllib.parse.urlsplit(events[0]['transport']['endpoint']).hostname == identity['forgejo_hostname'], 'transport/hostname drift')
    snapshots = [e for e in events if e['record'] == 'snapshot']
    uids = common_guards(snapshots, manifest['baseline'], arm)
    report, rows, origin = demand_report(v, events)
    require(report['unissued'] == 0 and report['driver_lag_max_seconds'] <= 2, 'driver demand reduction/lag invalidates comparison')
    for r in rows:
        expected_delay = retry_delay(v, arm, r) if len(r['attempts']) == 2 else 0
        require(abs(r['backoff_seconds'] - expected_delay) < 1e-8, 'arm retry delta differs')
    signals = []
    lifecycle = TargetLifecycle(arm, {t['uid'] for t in manifest['baseline']['targets']}, v)
    for s in snapshots:
        inventory = s.get('target_inventory', [p for p in s['guard']['pods'] if p['name'].startswith('ext-authz-sim-')])
        # Guard collection can observe Pending -> Ready later in this cycle.
        # Lifecycle/config/signal use the same inventory taken at snapshot start.
        require({p['uid']: p['name'] for p in inventory} ==
                {p['uid']: p['name'] for p in s['guard']['pods'] if p['name'].startswith('ext-authz-sim-')}, 'snapshot target inventory differs')
        require({t['uid']: t['name'] for t in s['configuration']['targets']} ==
                {p['uid']: p['name'] for p in inventory if p['ready']}, 'Ready configuration inventory differs')
        lifecycle.inventory(inventory, s['at'])
        lifecycle.admin(s['configuration']['targets'], s['admin_stats'], s['stats'], s['at'])
        require(s['configuration']['metric_contract'] == metric_contract(), 'snapshot metric contract drift')
        signals.append(lifecycle.signal(s['signal'], inventory, s['at'], s['epoch']))
        require(s['signal']['query_sha256'] == digest(scale_query(v)), 'scale query drift')
    require(signals[-1] is not None and all(b['end'] - a['end'] <= 35 for a, b in zip(snapshots, snapshots[1:])), 'final/missing observation gap')
    require(snapshots[0]['end'] <= origin and snapshots[-1]['at'] >= origin + v['mitigation_seconds'] + v['recovery_seconds'] and
            snapshots[-1]['end'] <= origin + v['mitigation_seconds'] + v['recovery_seconds'] + 60, 'full observation/drain deadline coverage')
    path = path_accounting(arm, snapshots)
    require(path['checks'] >= report['attempts'], 'attempt/check denominator incomplete')
    known = {c['attempt_id']: c['operation_id'] for c in path.pop('admitted_checks')}
    # Each admitted HTTP check has a known client attempt. Rejected checks cannot
    # be joined request-by-request; conservation above is required separately.
    for attempt, op in known.items():
        require(any(attempt.endswith('-' + r['id'] + '-attempt-' + str(a['index'])) and
                    op.endswith('-' + r['id']) for r in rows for a in r['attempts']), 'unattributed admitted check')
    sentinels = [e for e in events if e['record'] == 'sentinel']
    require(sentinels and all(s['result']['semantic_result'] for s in sentinels) and
            sentinels[0]['at'] <= origin and sentinels[-1]['at'] >= origin + v['mitigation_seconds'] + v['recovery_seconds'] - 1, 'same-window direct sentinel coverage')
    def observed(start, end):
        points = [s for s in snapshots if s['at'] <= end and s['end'] >= start - 10]
        return (points and points[0]['end'] <= start + 5 and points[-1]['end'] >= end - 5 and
                all(s['healthy'] and s['signal'].get('status') == 'observed' for s in points) and
                all(b['end'] - a['end'] <= 15 for a, b in zip(points, points[1:])) and
                not any(start <= e['at'] < end for e in events if e['record'] == 'snapshot_gap') and
                all(p['ready'] for s in points for p in s['guard']['pods']))
    rec = recovery(v, events, observed)
    timeline = [e for e in events if e['record'] == 'replica_timeline']
    # A Ready new Pod alone is not proof: require signal, controller desired=2,
    # then Ready=2 and actual admitted traffic on both Pod lifetimes.
    scale = {'status': 'not observed', 'signal_to_desired_ready_traffic': []}
    if arm == 'C3':
        signal_at = next((s['end'] for s, value in zip(snapshots, signals) if value is not None and value > v['threshold']), None)
        desired = next((t['at'] for t in timeline if signal_at is not None and t['at'] >= signal_at and t['hpa']['status'].get('desiredReplicas') == 2), None)
        ready = next((t['at'] for t in timeline if desired is not None and t['at'] >= desired and sum(p['ready'] for p in t['pods']) == 2), None)
        traffic = next((s['end'] for s, value in zip(snapshots, signals) if value is not None and ready is not None and
                        s['at'] >= ready and len(s['stats']) == 2 and all(p8.p4.by_suffix(stats)['upstream_rq_total'] > 0 for stats in s['stats'].values())), None)
        if traffic is not None:
            scale = {'status': 'observed; audit scale ownership before autoscaling claim', 'signal_to_desired_ready_traffic': [signal_at, desired, ready, traffic]}
    return {'source_sha': identity['source_sha'], 'fingerprint': digest(manifest), 'arm': arm,
            'validity': 'pending-cloud-confounder-review', 'hypothesis': 'pending',
            'window_utc': {'start': events[0]['timestamp_utc'], 'end': events[-1]['timestamp_utc']},
            'campaign': report, 'accounting': path, 'recovery': rec, 'scaling': scale,
            'target_uids': sorted(uids), 'cleanup': 'pending'}


def reviewed(directory):
    directory = Path(directory)
    result = validate(directory)
    review = load(directory / 'confounder-review.json')
    signals = p8.REVIEW_SIGNALS | {'proxy_series_freshness', 'scaling_ownership_audit'}
    require(review['source_sha'] == result['source_sha'] and review['fingerprint'] == result['fingerprint'] and
            review['window_utc'] == result['window_utc'] and review['competing_bottleneck'] is False and
            review['missing_required_signals'] == [] and set(review['signals']) == signals, 'same-window confounder review incomplete')
    for name, e in review['signals'].items():
        path = Path(e['file'])
        require(not path.is_absolute() and '..' not in path.parts and path.suffix in {'.json', '.jsonl'}, 'relative evidence path')
        require(e['status'] == 'observed' and e['samples'] > 0 and e['interpretation'] and
                p8.p7.utc(e['start_utc']) <= p8.p7.utc(result['window_utc']['start']) and
                p8.p7.utc(e['end_utc']) >= p8.p7.utc(result['window_utc']['end']) and
                hashlib.sha256((directory / path).read_bytes()).hexdigest() == e['sha256'], 'missing/window/checksum review: ' + name)
    if result['arm'] == 'C2':
        require(review['haproxy_queue_role'] == 'measured-admission-policy', 'C2 queue misclassified as guard')
    else:
        require(review['haproxy_queue_role'] == 'competing-bottleneck-guard', 'HAProxy guard omitted')
    require(review['manual_replica_changes'] == 0, 'manual scaling is not autoscaling evidence')
    result['validity'] = 'valid'
    result['hypothesis'] = 'reviewed single contemporaneous comparison; no statistical generalization'
    return result


def compare(directories, freeze):
    require(len(directories) == 4, 'four arms required')
    results, configs = [reviewed(d) for d in directories], [load(Path(d) / 'configuration.json') for d in directories]
    require([r['arm'] for r in results] == list(ARMS), 'arm order/identity')
    reference = configs[0]['baseline']
    for config in configs:
        require(config['phase'] == 'measured' and all(config[k] == freeze[k] for k in ('source_sha', 'identity', 'plan', 'metric_contract', 'transport', 'fixture_sha256', 'schedule_sha256', 'slo_sha256', 'render_sha256')), 'comparison freeze/source/schedule drift')
        current = copy.deepcopy(config['baseline'])
        expected = copy.deepcopy(reference)
        # A HAProxy config rollout is the admission arm's allowed policy delta.
        # Return-to-C0 config for C3 can also replace that HAProxy Pod.
        if config['arm'] in {'C2', 'C3'}:
            current['haproxy']['uid'] = expected['haproxy']['uid']
            hp = next(o['data']['haproxy.cfg'] for o in render(freeze['identity'], freeze['plan'], config['arm'])['fixtures.json']['items'] if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'haproxy')
            require(current['haproxy']['config_sha256'] == hashlib.sha256(hp.strip().encode()).hexdigest(), 'cross-arm HAProxy policy drift')
            current['haproxy']['config_sha256'] = expected['haproxy']['config_sha256']
        if config['arm'] == 'C3':
            current.pop('scaledobject_spec')
            current['hpa_spec'] = expected['hpa_spec']
        config_guard(expected, current, config['arm'])
    return {'source_sha': freeze['source_sha'], 'validity': 'valid', 'arms': results,
            'corrective_actions': {'backoff': 'link observed C1 result after review', 'admission': 'link observed C2 result after review',
                                   'proxy_scaling': 'link C3 ownership/timeline/result after review'},
            'cleanup': 'pending; comparison does not establish restoration'}


def main(args):
    if len(args) == 8 and args[0] == 'initialize':
        initialize(load(args[1]), load(args[2]), load(args[3]), args[4], args[5], args[6], args[7])
    elif len(args) == 5 and args[0] == 'render':
        identity, v, arm = load(args[1]), load(args[2]), args[3]
        output = Path(args[4]); output.mkdir(mode=0o700)
        for name, obj in render(identity, v, arm).items():
            save(output / name, obj)
    elif len(args) == 6 and args[0] == 'transition':
        transition(load(args[1]), load(args[2]), args[3], args[4], load(args[5]))
    elif len(args) == 5 and args[0] == 'freeze':
        frozen_value = frozen(load(args[1]), load(args[2]), [load(p) for p in args[3].split(',')])
        save(args[4], frozen_value)
    elif len(args) == 9 and args[0] == 'measure':
        measure(load(args[1]), load(args[2]), args[3], args[4], args[5], args[6], args[7], args[8])
    elif len(args) == 4 and args[0] == 'queries':
        save(args[3], p8.cloud_plan(args[1], load(args[2])))
    elif len(args) == 3 and args[0] == 'postgres-metrics':
        p8.postgres_metrics(args[1], args[2])
    elif len(args) == 3 and args[0] in {'validate', 'review'}:
        save(args[2], (validate if args[0] == 'validate' else reviewed)(args[1]))
    elif len(args) == 7 and args[0] == 'compare':
        save(args[6], compare(args[1:5], load(args[5])))
    else:
        raise ValueError('usage: initialize IDENTITY PLAN APPROVAL CONTEXT PRIVATE OUTPUT INIT_LEDGER | render IDENTITY PLAN ARM DIR | transition IDENTITY PLAN C0|C3 OUTPUT APPROVAL | freeze IDENTITY PLAN CALIBRATION[,CALIBRATION] OUTPUT | measure IDENTITY PLAN ARM calibration|measured DIR APPROVAL FROZEN|- LEDGER | validate|review RUN OUTPUT | compare C0 C1 C2 C3 FROZEN OUTPUT')


if __name__ == '__main__':
    try:
        os.umask(0o077)
        main(sys.argv[1:])
    except Exception:
        print('P9 failed; retain append-only negative evidence and inspect protected operator inputs', file=sys.stderr)
        sys.exit(1)
