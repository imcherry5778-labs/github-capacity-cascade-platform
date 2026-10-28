#!/usr/bin/env python3
"""P7 HTTPS baseline and existing Azure Monitor query path. No provision/IAM/deploy."""
import datetime as dt
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('operation_results', ROOT / 'scripts/validate-operation-results.py')
operations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operations)
require = operations.require


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    # A failed/negative collection is immutable too; retry into another output directory.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=60).stdout.strip()


def utc(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.utcoffset() == dt.timedelta(0), 'UTC required')
    return parsed


def ready(context):
    uid = command(['kubectl', '--request-timeout=15s', 'get', 'namespace', 'kube-system', '-o', 'jsonpath={.metadata.uid}'])
    require(uid == context['environment']['cluster_uid'], 'Kubernetes context/cluster identity drift')
    app = json.loads(command(['kubectl', '--request-timeout=15s', '-n', 'argocd', 'get',
                              'application', 'forgejo-azure', '-o', 'json']))
    require(app['spec']['syncPolicy']['automated'] == {'prune': False, 'selfHeal': True}
            and app['status']['sync']['status'] == 'Synced' and app['status']['health']['status'] == 'Healthy'
            and app['status']['operationState']['phase'] == 'Succeeded' and not app.get('operation'), 'stable Argo readiness/policy')
    revision = context['argo_values_revision']
    require(app['spec']['sources'][1]['targetRevision'] == revision
            and app['spec']['sources'][2]['targetRevision'] == revision
            and app['status']['sync']['revisions'] == [context['forgejo_chart_digest'], revision, revision], 'stable deployed revision drift')
    pods = json.loads(command(['kubectl', '--request-timeout=15s', '-n', 'forgejo', 'get', 'pods',
                               '-l', 'app.kubernetes.io/name=forgejo', '-o', 'json']))['items']
    require(len(pods) == 1 and not pods[0]['metadata'].get('deletionTimestamp') and
            any(c['type'] == 'Ready' and c['status'] == 'True' for c in pods[0]['status']['conditions']), 'stable Pod readiness')
    image = next(c['imageID'] for c in pods[0]['status']['containerStatuses'] if c['name'] == 'forgejo')
    require(image == context['runtime_images']['forgejo'], 'stable runtime image drift')
    endpoint = os.environ['FORGEJO_URL']
    override = os.environ.get('JOURNEY_DNS_OVERRIDE')
    parsed = operations.transport(endpoint, 'azure-aks', override)
    curl = ['curl', '-q', '--noproxy', '*', '--proto', '=https', '--fail', '--silent', '--show-error', '--max-time', '15']
    if override:
        curl += ['--resolve', urllib.parse.urlsplit(parsed['endpoint']).hostname + ':443:' + override]
    command(curl + [endpoint + '/api/healthz'])


def baseline(context_path, output, private):
    context = load(context_path)
    require(context['environment']['kind'] == 'azure-aks', 'Azure context required')
    require(re.fullmatch('[0-9a-f-]{36}', context['environment']['cluster_uid']), 'cluster identity required')
    require(context['source_sha'] == command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']) and
            context['dirty'] is False and not command(['git', '-C', str(ROOT), 'status', '--porcelain']), 'clean exact execution source required')
    endpoint = os.environ['FORGEJO_URL']
    operations.transport(endpoint, 'azure-aks', os.environ.get('JOURNEY_DNS_OVERRIDE'))
    output, private = Path(output), Path(private)
    require(private.is_dir() and private.stat().st_mode & 0o777 == 0o700, 'private fixture directory mode 0700 required')
    require(not any((private / f'journey-{i}').exists() for i in range(6)), 'existing fixture work must be preserved')
    output.mkdir(mode=0o700)  # exclusive; failed runs are never overwritten
    for index in range(6):
        ready(context)
        env = dict(os.environ, JOURNEY_ENVIRONMENT='azure-aks', RESULT_CONTEXT_FILE=str(Path(context_path).resolve()),
                   RESULTS_ROOT=str(output.resolve()), RESULT_PHASE='warmup' if index == 0 else 'measured',
                   JOURNEY_DIR=str(private.resolve() / f'journey-{index}'), JOURNEY_GATE_CORRELATION='1',
                   JOURNEY_GIT_TIMEOUT_SECONDS='65', JOURNEY_GIT_KILL_AFTER_SECONDS='5')
        # No campaign timeout. Each network command retains the P3 command bounds.
        subprocess.run(['bash', str(ROOT / 'tests/e2e/forgejo-developer-journey.sh'), 'create'], env=env, check=True)
    ready(context)
    save(output / 'baseline-summary.json', operations.summarize(output))


def query_plan(summary, identity):
    fields = {'cluster_resource_id', 'prometheus_cluster', 'namespace', 'pod', 'container',
              'envoy_cluster_name', 'admin_cluster_name', 'prometheus_endpoint', 'log_workspace_id'}
    require(set(identity) in (fields, fields | {'envoy_cluster_label'}), 'query identity fields')
    cluster_label = identity.get('envoy_cluster_label', 'envoy_cluster_name')
    require(cluster_label in {'cluster_name', 'envoy_cluster_name'}, 'unsupported Envoy cluster label')
    require(summary['environment']['kind'] == 'azure-aks' and summary['measurement_boundary'] == operations.AZURE_BOUNDARY
            and summary['operation_samples'] == summary['attempt_samples'] == 45 and summary['source_dirty'] is False,
            'healthy clean Azure baseline required')
    require(summary['plan'] == {'warmup': 1, 'measured': 5, 'concurrency': 1, 'max_attempts': 1,
                               'api_timeout_seconds': 60, 'git_timeout_seconds': 65, 'git_kill_after_seconds': 5}, 'baseline plan drift')
    window = summary['measured_window_utc']
    require(utc(window['start']) <= utc(window['end']), 'measurement window order')
    require(identity['cluster_resource_id'] == summary['environment']['cluster_resource_id'], 'query cluster differs from measured cluster')
    for field in ('cluster_resource_id', 'prometheus_cluster', 'namespace', 'pod', 'container', 'envoy_cluster_name'):
        require(isinstance(identity[field], str) and re.fullmatch(r'[a-zA-Z0-9_./:|+-]+', identity[field]), 'unsafe query identity')
    require(identity['namespace'] in {'forgejo', 'aks-istio-ingress'} and identity['container'] == 'istio-proxy', 'selected stable proxy identity required')
    require(re.fullmatch(r'https://[a-z0-9.-]+\.prometheus\.monitor\.azure\.com', identity['prometheus_endpoint']), 'Managed Prometheus endpoint')
    require(re.fullmatch(r'[0-9a-f-]{36}', identity['log_workspace_id']), 'Log Analytics workspace ID')
    labels = dict(cluster=identity['prometheus_cluster'], **{k: identity[k] for k in ('namespace', 'pod')})
    proxy = ','.join(k + '=' + json.dumps(v) for k, v in labels.items())
    cluster = proxy + ',' + cluster_label + '=' + json.dumps(identity['envoy_cluster_name'])
    expressions = {'forgejo_scrape': 'up{job="forgejo",namespace="forgejo",cluster=' + json.dumps(identity['prometheus_cluster']) + '}',
                   'proxy_scrape': 'up{job="azure-stable-envoy",' + proxy + '}'}
    for stat in ('upstream_rq_active', 'upstream_rq_active_overflow', 'upstream_rq_pending_active', 'upstream_rq_pending_overflow', 'upstream_rq_total'):
        expressions[stat] = 'envoy_cluster_' + stat + '{job="azure-stable-envoy",' + cluster + '}'
    # No raw LogMessage, URL, headers, user or correlation values leave Log Analytics.
    logs = f'''ContainerLogV2
| where TimeGenerated between (datetime({window['start']}) .. datetime({window['end']}))
| where _ResourceId =~ '{identity['cluster_resource_id']}'
| where PodNamespace == 'forgejo' or (PodNamespace == '{identity['namespace']}' and PodName == '{identity['pod']}')
| summarize entries=count(), first_seen=min(TimeGenerated), last_seen=max(TimeGenerated) by PodNamespace, PodName, ContainerName, LogSource'''
    return {'schema_version': 1, 'source_sha': summary['source_sha'], 'stable_deployed_revision': summary['stable_deployed_revision'],
            'measured_run_ids': summary['measured_run_ids'], 'service_active_window_utc': window, 'identity': identity,
            'correlation': {'client': 'run_id -> operation_id -> attempt_id', 'server': 'time-window-and-workload',
                            'request_level_join': 'not verified', 'distributed_tracing': 'not verified'},
            'promql': expressions, 'kql': logs, 'step_seconds': 30,
            'interpretation': 'absent series/rows are no-data; observed overflow=0 is visibility only; no saturation/rejection proof'}


def prom_result(payload):
    require(payload.get('status') == 'success' and payload['data']['resultType'] == 'matrix', 'Prometheus query failed')
    series = payload['data']['result']
    allowed = {'__name__', 'cluster', 'namespace', 'pod', 'job', 'instance', 'envoy_cluster_name', 'cluster_name'}
    result = []
    for item in series:
        values = item['values']
        require(all(len(v) == 2 and math.isfinite(float(v[0])) and math.isfinite(float(v[1])) for v in values), 'non-finite metric observation')
        result.append({'metric': {k: v for k, v in item['metric'].items() if k in allowed}, 'values': values})
    return {'status': 'observed' if any(s['values'] for s in result) else 'no-data', 'series': result}


def http_json(url, token):
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
    # TLS verification uses the OS trust store. No redirects to another credential origin.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None
    with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
        return json.load(response)


def collect(plan, output):
    identity = plan['identity']
    # The saved plan records exact queries/window; validate the credential destination again.
    require(re.fullmatch(r'https://[a-z0-9.-]+\.prometheus\.monitor\.azure\.com', identity['prometheus_endpoint']), 'Managed Prometheus endpoint')
    output = Path(output)
    output.mkdir(mode=0o700)
    save(output / 'query-plan.json', plan)
    token = command(['az', 'account', 'get-access-token', '--resource', 'https://prometheus.monitor.azure.com', '--query', 'accessToken', '-o', 'tsv'])
    for name, expression in plan['promql'].items():
        require(re.fullmatch('[a-z_]+', name), 'query filename')
        query = urllib.parse.urlencode(dict(query=expression, start=plan['service_active_window_utc']['start'],
                                           end=plan['service_active_window_utc']['end'], step=plan['step_seconds']))
        try:
            result = prom_result(http_json(identity['prometheus_endpoint'] + '/api/v1/query_range?' + query, token))
            require(all(s['metric'].get('cluster') == identity['prometheus_cluster'] for s in result['series']), 'returned series cluster mismatch')
        except Exception:
            save(output / (name + '.json'), {'status': 'query-failed'})
            raise ValueError('Prometheus collection failed; retained previous results') from None
        save(output / (name + '.json'), result)
    del token
    try:
        rows = json.loads(command(['az', 'monitor', 'log-analytics', 'query', '-w', identity['log_workspace_id'],
                                   '--analytics-query', plan['kql'], '--timespan',
                                   plan['service_active_window_utc']['start'] + '/' + plan['service_active_window_utc']['end'], '-o', 'json']))
        require(isinstance(rows, list) and all(set(r) <= {'PodNamespace', 'PodName', 'ContainerName', 'LogSource', 'entries', 'first_seen', 'last_seen', 'TableName'} for r in rows), 'unexpected Log Analytics fields')
        save(output / 'logs.json', {'status': 'observed' if rows else 'no-data', 'rows': rows})
    except Exception:
        save(output / 'logs-failure.json', {'status': 'query-failed'})
        raise ValueError('Log Analytics collection failed') from None


def proxy_snapshot(identity):
    """Read actual admin cluster/stat identity; never retain the raw config dump."""
    ns, pod = identity['namespace'], identity['pod']
    require(ns in {'forgejo', 'aks-istio-ingress'} and re.fullmatch('[a-z0-9-]+', pod), 'stable proxy selector')
    base = ['kubectl', '--request-timeout=15s', '-n', ns]
    obj = json.loads(command(base + ['get', 'pod', pod, '-o', 'json']))
    require(obj['metadata']['namespace'] == ns and not obj['metadata'].get('deletionTimestamp'), 'live proxy Pod required')
    native = [c for c in obj['spec'].get('initContainers', []) if c.get('restartPolicy') == 'Always']
    proxy = next(c for c in obj['spec']['containers'] + native if c['name'] == 'istio-proxy')
    statuses = obj['status'].get('containerStatuses', []) + obj['status'].get('initContainerStatuses', [])
    status = next(c for c in statuses if c['name'] == 'istio-proxy')
    require(status['ready'] is True, 'proxy readiness')
    def admin(path):
        return json.loads(command(base + ['exec', pod, '-c', 'istio-proxy', '--', 'pilot-agent', 'request', 'GET', path]))
    server = admin('server_info')
    dump = admin('config_dump?resource=dynamic_active_clusters')
    clusters = []
    for config in dump.get('configs', []):
        # Envoy resource filtering unwraps DynamicCluster into individual Any entries.
        if 'cluster' in config:
            clusters.append(config['cluster'])
        else:
            clusters.extend(entry['cluster'] for entry in config.get('dynamic_active_clusters', []))
    selected = [c for c in clusters if c['name'] == identity['admin_cluster_name']]
    require(len(selected) == 1, 'exact admin cluster not found')
    cluster = selected[0]
    alt = cluster.get('alt_stat_name')
    prefixes = sorted({'cluster.' + name + '.' for name in (cluster['name'], alt) if name})
    stats = admin('stats?format=json&filter=upstream_rq_')
    suffixes = {'upstream_rq_active', 'upstream_rq_active_overflow', 'upstream_rq_pending_active', 'upstream_rq_pending_overflow', 'upstream_rq_total'}
    observations = {s['name']: s['value'] for s in stats.get('stats', [])
                    if any(s.get('name', '').startswith(prefix) and s['name'][len(prefix):] in suffixes for prefix in prefixes)}
    return {'observed_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'namespace': ns, 'pod': pod,
            'pod_uid': obj['metadata']['uid'], 'node': obj['spec']['nodeName'], 'container': 'istio-proxy',
            'image_spec': proxy['image'], 'image_id': status['imageID'], 'restarts': status['restartCount'],
            'container_lifecycle': 'native-init-sidecar' if proxy in native else 'regular',
            'proxy_version': server['version'], 'cluster_name': cluster['name'], 'alt_stat_name': alt,
            'native_stat_prefixes': prefixes, 'observations': observations,
            'missing_stats': sorted(s for s in suffixes if not any(prefix + s in observations for prefix in prefixes)),
            'prometheus_cluster_label_to_verify': identity['envoy_cluster_name'],
            'prometheus_cluster_label_name': identity.get('envoy_cluster_label', 'envoy_cluster_name'),
            'mechanism': 'visibility only; saturation/rejection not verified'}


def main():
    if len(sys.argv) == 5 and sys.argv[1] == 'baseline':
        baseline(*sys.argv[2:])
    elif len(sys.argv) == 5 and sys.argv[1] == 'queries':
        save(sys.argv[4], query_plan(load(sys.argv[2]), load(sys.argv[3])))
    elif len(sys.argv) == 4 and sys.argv[1] == 'collect':
        collect(load(sys.argv[2]), sys.argv[3])
    elif len(sys.argv) == 4 and sys.argv[1] == 'proxy-snapshot':
        save(sys.argv[3], proxy_snapshot(load(sys.argv[2])))
    else:
        raise ValueError('usage: azure-operations.py baseline CONTEXT RESULTS PRIVATE_DIR | queries SUMMARY IDENTITY OUTPUT | collect PLAN OUTPUT_DIR | proxy-snapshot IDENTITY OUTPUT')


if __name__ == '__main__':
    try:
        os.umask(0o077)
        main()
    except Exception:
        # subprocess stderr/URL/token/config must never be reflected in reviewable artifacts.
        print('Azure operations failed; inspect protected operator inputs and retained result status', file=sys.stderr)
        sys.exit(1)
