#!/usr/bin/env python3
"""Actual pinned HAProxy requests: raw URI, method, spoofing and safe check copy.

Disposable Docker-only protocol check; no cloud, native Forgejo or TLS claim.
"""
import importlib.util
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True  # Lifecycle source provenance requires a clean tree.
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('p10', ROOT / 'scripts/critical-bulk-isolation.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
F = {'owner': 'fixture', 'repo': 'journey', 'issue': 1}


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.PIPE, timeout=60).strip()


def run(output):
    name = 'p10-check-' + uuid.uuid4().hex[:10]
    containers = []
    docker('network', 'create', name)
    try:
        with tempfile.TemporaryDirectory() as directory:
            config = m.haproxy(F, 'isolated', 'local')
            for kind in m.CLASSES:
                config = config.replace('ext-authz-' + kind + '.local.svc.cluster.local', name + '-app')
            path = Path(directory) / 'haproxy.cfg'; path.write_text(config)
            app = name + '-app'; hp = name + '-hp'
            containers.append(app)
            docker('run', '-d', '--name', app, '--network', name, '-v', str(ROOT / 'cmd/ext-authz-sim/main.py') + ':/app.py:ro',
                   m.p8.PINS['EXT_AUTHZ_BASE_IMAGE'], 'python', '/app.py')
            docker('exec', app, 'python', '-c',
                   "import socket,time\nfor i in range(100):\n try:\n  socket.create_connection(('127.0.0.1',8080),1).close();break\n except OSError:time.sleep(.1)\nelse:raise SystemExit(1)")
            # Both backend names point at one app ONLY for classifier protocol
            # validation. This harness cannot demonstrate physical isolation.
            containers.append(hp)
            docker('run', '-d', '--name', hp, '--network', name, '-p', '127.0.0.1::8080',
                   '-v', str(path) + ':/config/haproxy.cfg:ro', m.p8.PINS['HAPROXY_IMAGE'], 'haproxy', '-W', '-db', '-f', '/config/haproxy.cfg')
            port = int(docker('port', hp, '8080/tcp').rsplit(':', 1)[1])
            def request(method, uri, headers=None, body=None):
                c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                try:
                    c.request(method, uri, headers=headers or {}, body=body)
                    r = c.getresponse(); r.read()
                    return r.status, r.getheader('x-gate-decision')
                finally: c.close()
            for _ in range(50):
                try:
                    if request('GET', '/')[0] == 403: break
                except (OSError, http.client.HTTPException): pass
                time.sleep(.1)
            else: raise ValueError('HAProxy readiness')
            headers = {'Authorization': 'p4-check-without-credentials'}
            records = []
            for kind, pairs in m.routes(F).items():
                for method, uri in pairs:
                    status, decision = request(method, uri, headers | {'x-p10-class': 'opposite', 'x-traffic-class': 'opposite'})
                    m.require((status, decision) == (200, 'ALLOW'), 'actual allowlisted dispatch failed: ' + kind + ' ' + method + ' ' + str(status) + ' ' + str(decision))
                    records.append({'case': kind, 'status': status, 'decision': decision})
            uri = m.routes(F)['critical'][0][1]
            negatives = [('POST', uri), ('HEAD', uri), ('get', uri), ('GET', uri + '/'), ('GET', uri + '?'),
                         ('GET', uri + '?priority=critical'), ('GET', uri.replace('/issues/', '/./issues/')),
                         ('GET', uri.replace('/issues/', '/%2e/issues/')), ('GET', uri.replace('/issues/', '//issues/')),
                         ('GET', uri.replace('/issues/', '/%2fissues/')), ('GET', 'http://example.test' + uri),
                         ('GET', uri + '#fragment'), ('GET', '/api/v1/version')]
            for i, (method, path_value) in enumerate(negatives):
                status, decision = request(method, path_value, headers | {'x-priority': 'critical', 'x-p10-class': 'critical',
                      'x-traffic-class': 'critical', 'x-operation-id': 'critical', 'x-attempt-id': 'critical', 'x-forwarded-for': '127.0.0.1'})
                m.require(status in {400, 403} and decision is None, 'actual classifier escape')
                records.append({'case': 'negative-' + str(i), 'status': status, 'decision': decision})
            for unsafe in ({'Authorization': 'p10-private-pat-sentinel'}, headers | {'Cookie': 'p10-cookie-sentinel'}):
                m.require(request('GET', uri, unsafe) == (403, 'DENY'), 'unsafe direct check reached ALLOW')
            m.require(request('GET', uri, headers, 'p10-body-sentinel') == (403, 'DENY'), 'body accepted')
            checks = [json.loads(line) for line in docker('logs', app).splitlines()]
            m.require(len(checks) == 6 and sum(r['decision'] == 'ALLOW' for r in checks) == 3, 'backend dispatch count drift')
            serialized = json.dumps(checks)
            m.require(all(v not in serialized for v in ('p10-private-pat-sentinel', 'p10-cookie-sentinel', 'p10-body-sentinel')), 'credential/body retained')
            # The harness's HAProxy observations, read from the real pinned process the same way the owned harness reads them.
            def in_haproxy(*command): return docker('exec', hp, *command)
            ring = m.parse_ring(in_haproxy('sh', '-c', 'echo "show events p10" | nc -w 2 127.0.0.1 8405'))
            info = m.parse_haproxy_info(in_haproxy('sh', '-c', 'echo "show info" | nc -w 2 127.0.0.1 8405'))
            stats = m.parse_haproxy_stats(in_haproxy('wget', '-qO-', 'http://127.0.0.1:8404/stats;csv'))
            by_class = {k: sum(r['class'] == k for r in ring) for k in ('critical', 'bulk', 'deny', '-')}
            malformed = [r for r in ring if r['class'] == '-']
            m.require(by_class == {'critical': 4, 'bulk': 2, 'deny': 13, '-': 1} and len(ring) == 20 and
                      all(r['server'] == 'pool' and r['backend'] == r['class'] for r in ring if r['class'] in m.CLASSES) and
                      all(r['server'] == '<NOSRV>' and r['status'] == 403 for r in ring if r['class'] == 'deny') and
                      len(malformed) == 1 and malformed[0]['status'] == 400 and malformed[0]['termination'] == 'PR', 'real ring class/backend/server rows')
            # A request rejected before classification is not a connection without a request: it must stay accountable.
            m.require(not any(m.no_request(r) for r in ring), 'malformed request mistaken for a no-request connection')
            # The same counter identities the harness's window accounting relies on, against the real process.
            m.require(stats['frontend']['check']['req_tot'] == len(ring) and
                      stats['frontend']['check']['hrsp_4xx'] == sum(400 <= r['status'] < 500 for r in ring) and
                      stats['backend']['critical']['req_tot'] == 4 and stats['backend']['bulk']['req_tot'] == 2 and
                      stats['backend']['critical']['hrsp_2xx'] == 1 and stats['backend']['critical']['hrsp_4xx'] == 3 and
                      stats['backend']['bulk']['hrsp_2xx'] == 2, 'real HAProxy counters follow the ring')
            m.require((info['Nbthread'], info['Nbproc'], info['Maxconn'], info['DroppedLogs'], info['MaxconnReached']) == (1, 1, 256, 0, 0) and
                      {r['pid'] for r in ring} == {info['Pid']}, 'real HAProxy process invariants')
            m.save(output, {'scope': 'pinned HAProxy classifier protocol only', 'haproxy_image': m.p8.PINS['HAPROXY_IMAGE'],
                            'source_sha': m.p8.subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                            'cases': records, 'app_checks': checks, 'ring_classes': by_class, 'native_auth_tls': 'not verified', 'physical_isolation': 'not verified'})
    finally:
        for container in reversed(containers):
            subprocess.run(['docker', 'rm', '-f', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        subprocess.run(['docker', 'network', 'rm', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


if __name__ == '__main__':
    try: run(sys.argv[1])
    except Exception:
        print('P10 HAProxy protocol check failed; raw exception suppressed', file=sys.stderr)
        sys.exit(1)
