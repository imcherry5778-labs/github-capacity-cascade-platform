#!/usr/bin/env python3
"""Owned P4-cluster P10 healthy classifier smoke; restore experiment config.

This is classification/native-auth proof only, not a two-pool load comparison.
No Azure entrypoint. No request/credential/body values are persisted.
"""
import base64
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('p10', ROOT / 'scripts/critical-bulk-isolation.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
gate = m.p8.p4.gate
k = gate.kube


def call(method, uri, headers=None, body=None):
    c = http.client.HTTPConnection('127.0.0.1', 18080, timeout=10)
    try:
        c.request(method, uri, headers=headers or {}, body=body)
        r = c.getresponse(); data = r.read()
        return r.status, r.getheader('x-gate-decision'), data
    finally: c.close()


HAPROXY_CLUSTER = 'outbound|8080||haproxy.shared-gate.svc.cluster.local'


def apply(config, checkpoint):
    value = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'haproxy', 'namespace': 'shared-gate'},
             'data': {'haproxy.cfg': config}}
    subprocess.run(['kubectl', '--request-timeout=30s', 'apply', '-f', '-'], input=json.dumps(value),
                   text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=45)
    k('-n', 'shared-gate', 'rollout', 'restart', 'deployment/haproxy')
    gate.command('kubectl', '-n', 'shared-gate', 'rollout', 'status', 'deployment/haproxy', '--timeout=90s')
    converge(checkpoint)


def converge(checkpoint):
    # rollout status does not prove the ingress Envoy dropped the replaced HAProxy
    # endpoint; a stale one is an ext_authz error (status_on_error 403, no decision).
    # Wait for the actual check cluster, never a gated probe retry.
    ingress = gate.pod('istio=p4-ingress')['metadata']['name']
    state = {}
    for _ in range(60):
        pods = json.loads(k('-n', 'shared-gate', 'get', 'pods', '-l', 'app=haproxy', '-o', 'json'))['items']
        ready = [p for p in pods if not p['metadata'].get('deletionTimestamp') and
                 any(c['type'] == 'Ready' and c['status'] == 'True' for c in p['status'].get('conditions', []))]
        clusters = json.loads(k('-n', 'shared-gate', 'exec', ingress, '-c', 'istio-proxy', '--',
                                'pilot-agent', 'request', 'GET', 'clusters?format=json'))
        hosts = [h for c in clusters.get('cluster_statuses', []) if c.get('name') == HAPROXY_CLUSTER
                 for h in c.get('host_statuses', [])]
        healthy = [h for h in hosts if h.get('health_status', {}).get('eds_health_status') == 'HEALTHY' and
                   not set(h['health_status']) - {'eds_health_status'}]
        new_pod = len(pods) == len(ready) == 1 and len(hosts) == len(healthy) == 1 and \
            healthy[0]['address']['socket_address'] == {'address': ready[0]['status']['podIP'], 'port_value': 8080}
        state = {'haproxy_pods': len(pods), 'ready_pods': len(ready), 'endpoints': len(hosts),
                 'healthy_endpoints': len(healthy), 'endpoint_is_new_pod': new_pod}
        if new_pod:
            checkpoint('haproxy-converged', **state)
            return
        time.sleep(1)
    checkpoint('haproxy-not-converged', **state)
    m.require(False, 'ingress HAProxy endpoint did not converge')


def last_proxy_record(checkpoint, name):
    # Allowlisted access-log fields only; upstream host addresses are not kept.
    rows = k('-n', 'shared-gate', 'logs', gate.pod('istio=p4-ingress')['metadata']['name'], '-c', 'istio-proxy', '--tail=50').splitlines()
    records = []
    for row in rows:
        try: value = json.loads(row)
        except ValueError: continue
        if isinstance(value, dict) and value.get('record') == 'proxy_request':
            records.append(value)
    if records:
        checkpoint(name + '-ingress-log', status=records[-1].get('status'), details=records[-1].get('details'),
                   upstream_cluster=records[-1].get('upstream_cluster'))


def effective_check(listeners):
    # istioctl emits camelCase; Azure admin config_dump uses snake_case.
    # Reuse the selected local parser rather than mixing those wire formats.
    gate.auth_filter(listeners)
    filters = [v['typedConfig'] for v in m.p8.walk(listeners)
               if v.get('name') == 'envoy.filters.http.ext_authz']
    m.require(filters and all(not f['httpService'].get('pathPrefix') for f in filters),
              'effective HTTP check path prefix drift')
    return filters


SPOOF = {'x-priority': 'critical', 'x-traffic-class': 'critical', 'x-p10-class': 'critical', 'x-operation-id': 'critical', 'x-attempt-id': 'critical'}


def probe_plan(f, auth, git_auth):
    """(name, method, path, headers, expected status, body): the same table for Local and the managed Azure ingress.

    Selected ingress canonicalization and native Forgejo must agree on the resulting exact fixture endpoint
    (dot-segment); every other noncanonical/extra-query/method/spoofed form must be denied by the exact classifier.
    """
    uri = m.routes(f)['critical'][0][1]
    plan = [('critical', 'GET', uri, auth, 200, None),
            ('canonical-dot-segment', 'GET', uri.replace('/issues/', '/./issues/'), auth, 200, None),
            ('native-auth-deny', 'GET', uri, {}, 404, None)]  # Private Forgejo repo: hide existence.
    for index, (method, path) in enumerate([('HEAD', uri), ('POST', uri), ('GET', uri + '?priority=critical'),
                                            ('GET', uri + '/'), ('GET', uri.replace('/issues/', '//issues/')),
                                            ('GET', uri.replace('/issues/', '/%2fissues/')), ('GET', '/api/v1/version')]):
        plan.append(('negative-' + str(index + 3), method, path, auth | SPOOF, 403, None))
    return plan + [('spoof-cannot-change-critical', 'GET', uri, auth | {'x-traffic-class': 'bulk', 'x-p10-class': 'bulk'}, 200, None),
                   ('credential-body-exclusion', 'GET', uri, auth | {'Cookie': 'p10-cookie-exclusion', 'x-gate-test-deny': 'true'}, 403, 'p10-body-exclusion'),
                   # Git v0 discovery is an exact allowed smart-HTTP read request. Native Forgejo validates Basic auth.
                   ('bulk-discovery', 'GET', m.routes(f)['bulk'][0][1], git_auth, 200, None)]


def probe_semantics(name, payload, f, title):
    """Native semantic content of the probes that must succeed; status alone is not success."""
    if name in {'critical', 'spoof-cannot-change-critical'}:
        value = json.loads(payload)
        return value['number'] == f['issue'] and value['title'] == title
    if name == 'canonical-dot-segment':
        return json.loads(payload)['number'] == f['issue']
    if name == 'bulk-discovery':
        return b'git-upload-pack' in payload
    return True


def run(directory):
    directory = Path(directory)
    def checkpoint(phase, **safe):
        with (directory / 'p10-checkpoints.jsonl').open('a') as stream:
            stream.write(json.dumps({'phase': phase, **safe}) + '\n')
    checkpoint('owner-preflight')
    gate.owned_image_node()  # Exact invocation-owned local cluster; never current context alone.
    f = {'owner': os.environ['DEV_USER'], 'repo': 'journey', 'issue': int(os.environ['ISSUE_NUMBER'])}
    m.fixture(f)
    auth = {'Authorization': 'token ' + os.environ['DEV_TOKEN']}
    checkpoint('source-preflight')
    original = json.loads(k('-n', 'shared-gate', 'get', 'configmap/haproxy', '-o', 'json'))
    config = m.haproxy(f, 'shared', 'shared-gate').replace('ext-authz-shared.shared-gate.svc.cluster.local', 'ext-authz-sim.shared-gate.svc.cluster.local')
    before_target = gate.pod('app=ext-authz-sim')['metadata']['uid']
    results = []
    def probe(name, method, path, headers, expected, body=None):
        status, decision, payload = call(method, path, headers, body)
        checkpoint(name, status=status, expected_status=expected, decision=decision if decision in {None, 'ALLOW', 'DENY'} else 'unexpected')
        if status != expected:
            last_proxy_record(checkpoint, name)
        m.require(status == expected, 'P10 healthy probe failed: ' + name)
        results.append({'probe': name, 'status': status, 'decision': decision})
        return payload
    try:
        checkpoint('apply-classifier')
        apply(config, checkpoint)
        checkpoint('classifier-ready')
        git_auth = {'Authorization': 'Basic ' + base64.b64encode((f['owner'] + ':' + os.environ['DEV_TOKEN']).encode()).decode()}
        for name, method, path, headers, expected, body in probe_plan(f, auth, git_auth):
            payload = probe(name, method, path, headers, expected, body)
            m.require(probe_semantics(name, payload, f, os.environ['ISSUE_TITLE']), 'native semantic mismatch: ' + name)
        git_env = os.environ.copy() | {'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                  'GIT_CONFIG_COUNT': '3', 'GIT_CONFIG_KEY_0': 'http.extraHeader', 'GIT_CONFIG_VALUE_0': 'Authorization: ' + git_auth['Authorization'],
                  'GIT_CONFIG_KEY_1': 'protocol.version', 'GIT_CONFIG_VALUE_1': '2',
                  'GIT_CONFIG_KEY_2': 'credential.helper', 'GIT_CONFIG_VALUE_2': ''}
        checkpoint('bulk-smart-http-v2-start')
        git = subprocess.run(['git', 'ls-remote', '--exit-code', 'http://127.0.0.1:18080/' + f['owner'] + '/journey.git', 'refs/heads/main'],
                             env=git_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        checkpoint('bulk-smart-http-v2-end', command_exit=git.returncode)
        m.require(git.returncode == 0 and git.stdout.split()[0] == os.environ['MAIN_SHA'], 'native smart HTTP semantic read')
        results.append({'probe': 'bulk-smart-http-v2', 'command_exit': 0, 'expected_main': True})
        checkpoint('app-log-exclusion')
        pod = gate.pod('app=ext-authz-sim')
        checks = [json.loads(row) for row in k('-n', 'shared-gate', 'logs', pod['metadata']['name'], '-c', 'app').splitlines()]
        gate.validate_checks(checks)
        checkpoint('effective-check-config')
        listeners = gate.proxy_config(gate.pod('istio=p4-ingress')['metadata']['name'], 'listeners')
        filters = effective_check(listeners)
        m.require(gate.pod('app=ext-authz-sim')['metadata']['uid'] == before_target, 'classifier smoke target replaced')
        result = {'classification': 'healthy-path-verified', 'source_sha': gate.command('git', 'rev-parse', 'HEAD').strip(),
                  'scope': 'single-target healthy classifier, not isolated load protection', 'probes': results,
                  'effective_ext_authz_sha256': m.digest(filters), 'target_uid': before_target,
                  'credential_body_exclusion': True, 'forgejo_native_auth': True,
                  'tls': 'not verified by local HTTP; required separately before Azure', 'fixture_values_retained': False}
    finally:
        checkpoint('restore-classifier')
        apply(original['data']['haproxy.cfg'], checkpoint)
    checkpoint('restored')
    m.save(Path(directory) / 'p10-healthy.json', result | {'experiment_haproxy_restored': True})


if __name__ == '__main__':
    try: run(sys.argv[1])
    except Exception:
        print('P10 local classifier failed; raw exception suppressed', file=sys.stderr)
        sys.exit(1)
