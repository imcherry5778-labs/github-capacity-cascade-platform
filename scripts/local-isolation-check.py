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


def apply(config):
    value = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'haproxy', 'namespace': 'shared-gate'},
             'data': {'haproxy.cfg': config}}
    subprocess.run(['kubectl', '--request-timeout=30s', 'apply', '-f', '-'], input=json.dumps(value),
                   text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=45)
    k('-n', 'shared-gate', 'rollout', 'restart', 'deployment/haproxy')
    gate.command('kubectl', '-n', 'shared-gate', 'rollout', 'status', 'deployment/haproxy', '--timeout=90s')


def effective_check(listeners):
    # istioctl emits camelCase; Azure admin config_dump uses snake_case.
    # Reuse the selected local parser rather than mixing those wire formats.
    gate.auth_filter(listeners)
    filters = [v['typedConfig'] for v in m.p8.walk(listeners)
               if v.get('name') == 'envoy.filters.http.ext_authz']
    m.require(filters and all(not f['httpService'].get('pathPrefix') for f in filters),
              'effective HTTP check path prefix drift')
    return filters


def run(directory):
    gate.owned_image_node()  # Exact invocation-owned local cluster; never current context alone.
    f = {'owner': os.environ['DEV_USER'], 'repo': 'journey', 'issue': int(os.environ['ISSUE_NUMBER'])}
    m.fixture(f)
    auth = {'Authorization': 'token ' + os.environ['DEV_TOKEN']}
    uri = m.routes(f)['critical'][0][1]
    original = json.loads(k('-n', 'shared-gate', 'get', 'configmap/haproxy', '-o', 'json'))
    config = m.haproxy(f, 'shared', 'shared-gate').replace('ext-authz-shared.shared-gate.svc.cluster.local', 'ext-authz-sim.shared-gate.svc.cluster.local')
    before_target = gate.pod('app=ext-authz-sim')['metadata']['uid']
    results = []
    def probe(name, method, path, headers, expected, body=None):
        status, decision, payload = call(method, path, headers, body)
        m.require(status == expected, 'P10 healthy probe failed: ' + name)
        results.append({'probe': name, 'status': status, 'decision': decision})
        return payload
    try:
        apply(config)
        payload = probe('critical', 'GET', uri, auth, 200)
        value = json.loads(payload)
        m.require(value['number'] == f['issue'] and value['title'] == os.environ['ISSUE_TITLE'], 'native issue semantic mismatch')
        # Selected ingress canonicalization and native Forgejo must agree on
        # the resulting exact fixture endpoint; no second URI decoder in HAProxy.
        normalized = probe('canonical-dot-segment', 'GET', uri.replace('/issues/', '/./issues/'), auth, 200)
        m.require(json.loads(normalized)['number'] == f['issue'], 'canonical/native route disagreement')
        probe('native-auth-deny', 'GET', uri, {}, 404)  # Private Forgejo repo: hide existence.
        for method, path in [('HEAD', uri), ('POST', uri), ('GET', uri + '?priority=critical'),
                             ('GET', uri + '/'), ('GET', uri.replace('/issues/', '//issues/')),
                             ('GET', uri.replace('/issues/', '/%2fissues/')), ('GET', '/api/v1/version')]:
            probe('negative-' + str(len(results)), method, path, auth | {'x-priority': 'critical', 'x-traffic-class': 'critical',
                  'x-p10-class': 'critical', 'x-operation-id': 'critical', 'x-attempt-id': 'critical'}, 403)
        probe('spoof-cannot-change-critical', 'GET', uri, auth | {'x-traffic-class': 'bulk', 'x-p10-class': 'bulk'}, 200)
        probe('credential-body-exclusion', 'GET', uri,
              auth | {'Cookie': 'p10-cookie-exclusion', 'x-gate-test-deny': 'true'}, 403, 'p10-body-exclusion')
        # Git v0 discovery is an exact allowed smart-HTTP read request. Native
        # Forgejo validates Basic auth; no writes or fake HTTP200 success.
        git_auth = {'Authorization': 'Basic ' + base64.b64encode((f['owner'] + ':' + os.environ['DEV_TOKEN']).encode()).decode()}
        data = probe('bulk-discovery', 'GET', m.routes(f)['bulk'][0][1], git_auth, 200)
        m.require(b'git-upload-pack' in data, 'native Git discovery mismatch')
        git_env = os.environ.copy() | {'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                  'GIT_CONFIG_COUNT': '3', 'GIT_CONFIG_KEY_0': 'http.extraHeader', 'GIT_CONFIG_VALUE_0': 'Authorization: ' + git_auth['Authorization'],
                  'GIT_CONFIG_KEY_1': 'protocol.version', 'GIT_CONFIG_VALUE_1': '2',
                  'GIT_CONFIG_KEY_2': 'credential.helper', 'GIT_CONFIG_VALUE_2': ''}
        git = subprocess.run(['git', 'ls-remote', '--exit-code', 'http://127.0.0.1:18080/' + f['owner'] + '/journey.git', 'refs/heads/main'],
                             env=git_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        m.require(git.returncode == 0 and git.stdout.split()[0] == os.environ['MAIN_SHA'], 'native smart HTTP semantic read')
        results.append({'probe': 'bulk-smart-http-v2', 'command_exit': 0, 'expected_main': True})
        pod = gate.pod('app=ext-authz-sim')
        checks = [json.loads(row) for row in k('-n', 'shared-gate', 'logs', pod['metadata']['name'], '-c', 'app').splitlines()]
        gate.validate_checks(checks)
        listeners = gate.proxy_config(gate.pod('istio=p4-ingress')['metadata']['name'], 'listeners')
        filters = effective_check(listeners)
        m.require(gate.pod('app=ext-authz-sim')['metadata']['uid'] == before_target, 'classifier smoke target replaced')
        result = {'classification': 'healthy-path-verified', 'source_sha': gate.command('git', 'rev-parse', 'HEAD').strip(),
                  'scope': 'single-target healthy classifier, not isolated load protection', 'probes': results,
                  'effective_ext_authz_sha256': m.digest(filters), 'target_uid': before_target,
                  'credential_body_exclusion': True, 'forgejo_native_auth': True,
                  'tls': 'not verified by local HTTP; required separately before Azure', 'fixture_values_retained': False}
    finally:
        apply(original['data']['haproxy.cfg'])
    m.save(Path(directory) / 'p10-healthy.json', result | {'experiment_haproxy_restored': True})


if __name__ == '__main__':
    try: run(sys.argv[1])
    except Exception:
        print('P10 local classifier failed; raw exception suppressed', file=sys.stderr)
        sys.exit(1)
