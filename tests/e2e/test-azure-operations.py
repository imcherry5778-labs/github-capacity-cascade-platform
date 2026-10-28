#!/usr/bin/env python3
"""Cost-free P7 transport, baseline isolation, query and original-protection regression."""
import copy
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ops = module('ops', 'validate-operation-results.py')
azure = module('azure_ops', 'azure-operations.py')
recovery = module('azure_recovery', 'azure-recovery.py')


def rejects(fn, *args):
    try:
        fn(*args)
    except (ValueError, KeyError):
        return
    raise AssertionError('invalid input accepted')


def rows(run, phase, azure=False):
    start = dict(record='run_start', schema_version=1, run_id=run, phase=phase,
                 started_at_utc='2026-10-28T09:00:00Z', scenario='healthy', source_sha='a' * 40, dirty=False,
                 environment={'kind': 'azure-aks' if azure else 'local-k3d'}, tool_versions={}, runtime_images={},
                 argo_values_revision='b' * 40, forgejo_chart_version='17.1.7', forgejo_chart_digest='sha256:x',
                 parameters=dict(concurrency=1, max_attempts=1, client_retry=False, api_timeout_seconds=60,
                                 git_timeout_seconds=65, git_kill_after_seconds=5),
                 measurement_boundary=ops.AZURE_BOUNDARY if azure else ops.LOCAL_BOUNDARY)
    if azure:
        start['transport'] = ops.transport('https://forgejo.example.com', 'azure-aks', '1.1.1.1')
    result = [start]
    for index, typ in enumerate(sorted(ops.OP_TYPES)):
        op = run + '-operation-' + str(index)
        result += [dict(record='operation_start', run_id=run, operation_id=op, operation_type=typ, timestamp_utc=start['started_at_utc']),
                   dict(record='attempt', run_id=run, operation_id=op, attempt_id=op + '-attempt-1', attempt_index=1,
                        timestamp_utc=start['started_at_utc'], duration_seconds=0.1, exit_code=0, http_status=200, error_class='none'),
                   dict(record='operation', run_id=run, operation_id=op, operation_type=typ, outcome='success',
                        attempt_count=1, duration_seconds=0.1, semantic_result=True)]
    result.append(dict(record='run_end', run_id=run, completion='success', validity='valid', ended_at_utc='2026-10-28T09:01:00Z'))
    return result


def write(path, value):
    path.write_text('\n'.join(json.dumps(r) for r in value) + '\n')


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    local = tmp / 'legacy.jsonl'
    write(local, rows('legacy', 'measured'))
    assert ops.validate(local)['transport'] is None  # old Local raw remains byte-for-byte usable
    for endpoint, kind, override in [('https://forgejo.example.com', 'local-k3d', None),
                                      ('http://127.0.0.1:13000', 'azure-aks', None),
                                      ('https://127.0.0.1', 'azure-aks', None),
                                      ('https://forgejo.example.com/path', 'azure-aks', None),
                                      ('https://user:password@forgejo.example.com', 'azure-aks', None),
                                      ('https://forgejo.example.com', 'azure-aks', '127.0.0.1'),
                                      ('https://forgejo.example.com', 'arbitrary', None)]:
        rejects(ops.transport, endpoint, kind, override)
    directory = tmp / 'baseline'
    directory.mkdir()
    for i in range(6):
        run = directory / f'run{i}'
        run.mkdir()
        write(run / 'events.jsonl', rows(f'run{i}', 'warmup' if i == 0 else 'measured', azure=True))
    summary = ops.summarize(directory)
    assert summary['operation_samples'] == summary['attempt_samples'] == 45
    assert summary['transport']['dns_client_override'] == '1.1.1.1'
    path = directory / 'run5/events.jsonl'
    original = rows('run5', 'measured', azure=True)
    for field, value in [('measurement_boundary', ops.LOCAL_BOUNDARY), ('measurement_boundary', 'anything'),
                         ('environment', {'kind': 'local-k3d'}), ('transport', None),
                         ('transport', dict(original[0]['transport'], tls_verification='disabled'))]:
        changed = copy.deepcopy(original)
        changed[0][field] = value
        write(path, changed)
        rejects(ops.validate, path)
    for field, value in [('transport', ops.transport('https://other.example.com', 'azure-aks', '1.1.1.1')),
                         ('transport', ops.transport('https://forgejo.example.com', 'azure-aks')),
                         ('environment', {'kind': 'azure-aks', 'cluster': 'other'}),
                         ('runtime_images', {'forgejo': 'changed'}), ('argo_values_revision', 'c' * 40)]:
        changed = copy.deepcopy(original)
        changed[0][field] = value
        write(path, changed)
        rejects(ops.summarize, directory)
    write(path, rows('local-mixed', 'measured'))
    rejects(ops.summarize, directory)

    summary.update(source_dirty=False, stable_deployed_revision='b' * 40)
    summary['environment']['cluster_resource_id'] = '/subscriptions/00000000/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks'
    identity = dict(cluster_resource_id=summary['environment']['cluster_resource_id'], namespace='aks-istio-ingress',
                    prometheus_cluster='aks-test', pod='aks-istio-ingressgateway-external-abc', container='istio-proxy', admin_cluster_name='selected-admin-cluster', envoy_cluster_name='outbound|3000||forgejo-http.forgejo.svc.cluster.local',
                    prometheus_endpoint='https://workspace.region.prometheus.monitor.azure.com', log_workspace_id='0' * 8 + '-0000-0000-0000-' + '0' * 12)
    plan = azure.query_plan(summary, identity)
    rejects(azure.query_plan, summary, dict(identity, password='secret'))
    pod_snapshot = {'metadata': {'namespace': identity['namespace'], 'uid': 'pod-uid'}, 'spec': {'nodeName': 'node', 'containers': [{'name': 'istio-proxy', 'image': 'proxy@sha256:actual'}]}, 'status': {'containerStatuses': [{'name': 'istio-proxy', 'ready': True, 'imageID': 'runtime-id', 'restartCount': 0}]}}
    with patch.object(azure, 'command', side_effect=[json.dumps(pod_snapshot), json.dumps({'version': 'actual-managed-proxy'}), json.dumps({'configs': [{'cluster': {'name': 'selected-admin-cluster', 'alt_stat_name': 'actual-stat-name', 'secret': 'do-not-export'}}]}), json.dumps({'stats': [{'name': 'cluster.actual-stat-name.upstream_rq_active_overflow', 'value': 0}, {'name': 'cluster.other.upstream_rq_total', 'value': 1}, {'histograms': {'supported_quantiles': [0, 0.5, 1], 'computed_quantiles': []}}]})]):
        proxy = azure.proxy_snapshot(identity)
        assert proxy['observations'] == {'cluster.actual-stat-name.upstream_rq_active_overflow': 0}
        assert 'upstream_rq_active' in proxy['missing_stats'] and 'do-not-export' not in json.dumps(proxy)
    assert plan['correlation']['request_level_join'] == 'not verified'
    assert plan['service_active_window_utc'] == summary['measured_window_utc']
    assert 'LogMessage' not in plan['kql'] and 'or vector(0)' not in str(plan['promql'])
    assert azure.prom_result({'status': 'success', 'data': {'resultType': 'matrix', 'result': []}})['status'] == 'no-data'
    observed = azure.prom_result({'status': 'success', 'data': {'resultType': 'matrix', 'result': [{'metric': {'namespace': 'forgejo'}, 'values': [[1, '0']]}]}})
    assert observed['status'] == 'observed' and observed['series'][0]['values'][0][1] == '0'
    rejects(azure.prom_result, {'status': 'success', 'data': {'resultType': 'matrix', 'result': [{'metric': {}, 'values': [[1, 'NaN']]}]}})
    rejects(azure.query_plan, summary, dict(identity, cluster_resource_id='/different/cluster'))
    rejects(azure.query_plan, summary, dict(identity, pod='x"} or up'))
    with patch.object(azure, 'command', return_value='secret-token'), patch.object(azure, 'http_json', side_effect=ValueError('secret-token')):
        rejects(azure.collect, plan, tmp / 'failed-query')
        assert json.loads((tmp / 'failed-query/forgejo_scrape.json').read_text()) == {'status': 'query-failed'}
        assert 'secret-token' not in ''.join(p.read_text() for p in (tmp / 'failed-query').iterdir())

    value = dict(campaign='p7test', stage='restore', source_sha='a' * 40, stable_deployed_revision='b' * 40,
                 stable=dict(namespace='forgejo', deployment='forgejo', pvc='forgejo-data', db_host='existing.postgres.database.azure.com',
                             db_name='forgejo', db_role='forgejo', pvc_uid='source-pvc', pv_uid='source-pv', pv_name='source-pv', disk_id='/source-disk'),
                 target=dict(namespace='p7-ops-p7test', pvc='p7-data', db_host='existing.postgres.database.azure.com',
                             db_name='p7_p7test_restore', db_role='p7_p7test_role', db_ipv4='10.0.1.4'))
    manifests = recovery.render(value)
    assert manifests['app.json']['spec']['containers'][0]['image'] == recovery.image('restore')
    assert not any(v['kind'] in {'Service', 'Ingress', 'Gateway', 'VirtualService'} for v in manifests.values())
    assert manifests['app.json']['spec']['containers'][0]['readinessProbe']['exec']['command'][-1].endswith('127.0.0.1:3000/api/healthz')
    for stage in ('a', 'rollback'):
        stage_value = copy.deepcopy(value)
        stage_value['stage'] = stage
        stage_value['target']['db_name'] = 'p7_p7test_' + stage
        stage_manifests = recovery.render(stage_value)
        assert recovery.admission(stage_value, {'items': [stage_manifests['app.json']]})['pods'] == 1
        if stage == 'a':
            assert recovery.admission(stage_value, {'items': [stage_manifests['app-b.json']]})['pods'] == 1
    pods = {'items': [manifests['app.json'], manifests['db-client.json']]}
    assert recovery.admission(value, pods)['cpu_millicores'] == 750
    for update in [{'overhead': {'cpu': '1m'}}, {'initContainers': [{'name': 'injected', 'restartPolicy': 'Always'}]}]:
        changed = copy.deepcopy(pods)
        changed['items'][0]['spec'].update(update)
        rejects(recovery.admission, value, changed)
    changed = copy.deepcopy(pods)
    changed['items'][0]['spec']['containers'][0]['env'].append({'name': 'GITEA__database__NAME', 'value': 'forgejo'})
    rejects(recovery.admission, value, changed)
    changed = copy.deepcopy(value)
    changed['target']['db_name'] = 'forgejo'
    rejects(recovery.render, changed)
    ini, password = tmp / 'app.ini', tmp / 'password'
    ini.write_text('APP_NAME = Forgejo\n[database]\nDB_TYPE = postgres\nHOST = existing.postgres.database.azure.com:5432\nNAME = forgejo\nUSER = forgejo\nPASSWD = original-secret\nSSL_MODE = verify-full\n[server]\nDISABLE_SSH = true\n[security]\nSECRET_KEY = unchanged-signing-state\n')
    ini.chmod(0o600)
    password.write_text('a' * 64)
    password.chmod(0o600)
    rejects(recovery.database_config, ini, value['target'])
    recovery.rebind(value, ini, password)
    recovery.database_config(ini, value['target'])
    private_ini = ini.read_text()
    ini.write_text(private_ini.replace('HTTP_ADDR = 127.0.0.1', 'HTTP_ADDR = 0.0.0.0'))
    rejects(recovery.database_config, ini, value['target'])
    ini.write_text(private_ini.replace('SSL_MODE = verify-full', 'SSL_MODE = disable'))
    rejects(recovery.database_config, ini, value['target'])
    rollback_input = copy.deepcopy(value)
    rollback_input['stage'] = 'rollback'
    rollback_input['target']['db_name'] = 'p7_p7test_rollback'
    ini.write_text(private_ini.replace('NAME = p7_p7test_restore', 'NAME = p7_p7test_a'))
    recovery.rebind(rollback_input, ini, password)
    recovery.database_config(ini, rollback_input['target'])
    ini.write_text(private_ini)
    assert 'original-secret' not in ini.read_text() and 'SECRET_KEY = unchanged-signing-state' in ini.read_text()
    snapshot = dict(namespace={'metadata': {'name': value['target']['namespace'], 'labels': {'p7.campaign': 'p7test'}}},
                    pvc={'metadata': {'name': 'p7-data', 'namespace': value['target']['namespace'], 'labels': {'p7.campaign': 'p7test'}, 'uid': 'target-pvc'},
                         'spec': {'volumeName': 'target-pv', 'resources': {'requests': {'storage': '10Gi'}}, 'storageClassName': 'managed-csi'}, 'status': {'phase': 'Bound'}},
                    pv={'metadata': {'name': 'target-pv', 'uid': 'target-pv'}, 'spec': {'csi': {'driver': 'disk.csi.azure.com', 'volumeHandle': '/target-disk'}, 'claimRef': {'uid': 'target-pvc'}}},
                    database={'current_database': value['target']['db_name'], 'current_user': value['target']['db_role'], 'owner': value['target']['db_role'], 'public_tables': 0, 'other_sessions': 0, 'server_address': '10.0.1.4', 'ssl': True}, pods=[])
    assert recovery.target_guard(value, snapshot, ini)['fresh_before_restore'] is True
    changed = copy.deepcopy(snapshot)
    changed['pv']['spec']['csi']['volumeHandle'] = '/SOURCE-DISK'
    rejects(recovery.target_guard, value, changed, ini)
    changed = copy.deepcopy(snapshot)
    changed['database']['public_tables'] = 1
    rejects(recovery.target_guard, value, changed, ini)
    changed = copy.deepcopy(snapshot)
    changed['pvc']['metadata']['labels'] = {}
    rejects(recovery.target_guard, value, changed, ini)

    checkpoint = tmp / 'checkpoint'
    checkpoint.mkdir(mode=0o700)
    for stage in ('restore', 'a'):
        checkpoint_input = copy.deepcopy(value)
        checkpoint_input['stage'] = stage
        checkpoint_input['target']['db_name'] = 'p7_p7test_' + stage
        (checkpoint / 'database.dump').write_bytes(b'fake-test-dump')
        with tarfile.open(checkpoint / 'application-data.tar', 'w') as tar:
            item = tarfile.TarInfo('gitea/conf/app.ini')
            item.size = 3
            tar.addfile(item, io.BytesIO(b'ini'))
        names = ['forgejo-admin', 'forgejo-db', 'forgejo-inline-config'] if stage == 'restore' else ['p7-credential']
        (checkpoint / 'secrets.json').write_text(json.dumps([{'metadata': {'name': n, 'namespace': 'forgejo' if stage == 'restore' else value['target']['namespace']}, 'data': {'key': 'test'}} for n in names]))
        components = {}
        for name in recovery.COMPONENTS:
            path = checkpoint / name
            path.chmod(0o600)
            components[name] = {'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        prefix = 'FORGEJO_UPGRADE_TO' if stage == 'restore' else 'FORGEJO_UPGRADE_FROM'
        manifest = dict(input=checkpoint_input, backup_complete=True, writer_absent=True, queue_flushed=True,
                        version='15.0.11+gitea-1.22.0' if stage == 'restore' else '15.0.9+gitea-1.22.0', image_spec=recovery.image(stage),
                        image_id='code.forgejo.org/forgejo/forgejo@' + recovery.PINS[prefix + '_IMAGE_DIGEST'], components=components)
        (checkpoint / 'manifest.json').write_text(json.dumps(manifest))
        assert recovery.bundle(checkpoint)['input']['stage'] == stage
        changed_manifest = copy.deepcopy(manifest)
        changed_manifest['writer_absent'] = False
        (checkpoint / 'manifest.json').write_text(json.dumps(changed_manifest))
        rejects(recovery.bundle, checkpoint)
        (checkpoint / 'manifest.json').write_text(json.dumps(manifest))
        (checkpoint / 'database.dump').write_bytes(b'corrupt')
        rejects(recovery.bundle, checkpoint)
        (checkpoint / 'database.dump').write_bytes(b'fake-test-dump')
        with tarfile.open(checkpoint / 'application-data.tar', 'w') as tar:
            tar.addfile(tarfile.TarInfo('../escape'))
        path = checkpoint / 'application-data.tar'
        manifest['components'][path.name] = {'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        (checkpoint / 'manifest.json').write_text(json.dumps(manifest))
        rejects(recovery.bundle, checkpoint)


print('PASS P7 Local compatibility/HTTPS transport, mixed baseline refusal, query no-data/zero, original DB/PVC and admission guards')

# Native-session adapter: same secure-cookie values, private A never authenticates to public B.
SESSION_CURL = r'''#!/usr/bin/env bash
set -euo pipefail
url="${!#}" out= jar= method=GET config= body=
while (($#)); do
  case "$1" in
    -c) shift; jar="$1" ;;
    -o) shift; out="$1" ;;
    -X) shift; method="$1" ;;
    -K) shift; config="$1" ;;
    --data-binary) shift; body="${1#@}" ;;
  esac
  shift
done
if [[ "$url" == */user/login ]]; then
  [[ "$url" == "$EXPECTED_LOGIN/user/login" ]] || exit 94
  if [[ "$method" == GET ]]; then
    if [[ "${TEST_CSRF_ABSENT:-0}" == 1 ]]; then
      printf '# Netscape HTTP Cookie File\n' >"$jar"
      printf '<input name="user_name" type="text">'
    else
      printf '# Netscape HTTP Cookie File\nforgejo.example.com\tFALSE\t/\tTRUE\t0\tsession\tcookie-secret\n' >"$jar"
      printf '<input value="csrf-value" type="hidden" name="_csrf">'
    fi
  else
    if [[ "${TEST_CSRF_ABSENT:-0}" == 1 ]]; then
      [[ ! -s "$config" ]]
      ! grep -q '_csrf=' "$body"
    else
      grep -q 'cookie-secret' "$config"
      grep -q '_csrf=csrf-value' "$body"
    fi
    printf '# Netscape HTTP Cookie File\nforgejo.example.com\tFALSE\t/\tTRUE\t0\tsession\tcookie-secret\n' >"$jar"
    printf 302
  fi
else
  [[ "$url" == http://127.0.0.1:13001/user/settings && -f "$config" ]]
  grep -q 'cookie-secret' "$config"
  printf 'dev-fixture' >"$out"
  printf '%s' "${TEST_SESSION_STATUS:-200}"
fi
'''
with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    bindir = temp / 'bin'
    bindir.mkdir()
    (bindir / 'curl').write_text(SESSION_CURL)
    (bindir / 'curl').chmod(0o755)
    for namespace, absent in (('forgejo', False), ('p7-ops-test', False), ('forgejo', True), ('p7-ops-test', True)):
        private = temp / (namespace + ('-no-csrf' if absent else ''))
        private.mkdir(mode=0o700)
        env = dict(os.environ, PATH=str(bindir) + ':' + os.environ['PATH'], P7_NAMESPACE=namespace,
                   P7_PRIVATE=str(private), P7_POD='fixture', FORGEJO_URL='https://forgejo.example.com',
                   DEV_USER='dev-fixture', DEV_PASSWORD='never-in-output', P7_PRIVATE_URL='http://127.0.0.1:13001',
                   EXPECTED_LOGIN='https://forgejo.example.com' if namespace == 'forgejo' else 'http://127.0.0.1:13001',
                   TEST_CSRF_ABSENT='1' if absent else '0')
        script = ['bash', str(ROOT / 'scripts/azure-recovery-check.sh')]
        proc = subprocess.run(script + ['session-login'], env=env, capture_output=True, text=True, timeout=10)
        assert proc.returncode == 0, proc.stderr
        before = (private / 'cookies').read_bytes()
        assert not (private / 'session-body').exists() and not (private / 'session-curl').exists()
        proc = subprocess.run(script + ['session-verify'], env=env, capture_output=True, text=True, timeout=10)
        assert proc.returncode == 0 and (private / 'cookies').read_bytes() == before
        assert 'cookie-secret' not in proc.stdout + proc.stderr
        bad = dict(env, TEST_SESSION_STATUS='302')
        proc = subprocess.run(script + ['session-verify'], env=bad, capture_output=True, text=True, timeout=10)
        assert proc.returncode != 0
        (private / 'cookies').write_text('tampered')
        proc = subprocess.run(script + ['session-verify'], env=env, capture_output=True, text=True, timeout=10)
        assert proc.returncode != 0
print('PASS same native-session cookie continuity, private-only A login, unauthenticated/tampered rejection')
