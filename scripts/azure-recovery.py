#!/usr/bin/env python3
"""P7 private Azure target adapter; render/guards/rebind only, never deploy/delete."""
import configparser
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import tarfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recovery', ROOT / 'scripts/validate-recovery.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)
require = recovery.require
PINS = dict(line.split('=', 1) for line in (ROOT / 'versions.env').read_text().splitlines() if line and not line.startswith('#'))
COMPONENTS = ('database.dump', 'application-data.tar', 'secrets.json')


def load(path):
    return json.loads(Path(path).read_text())


def validate_input(value):
    require(set(value) == {'campaign', 'stage', 'source_sha', 'stable_deployed_revision', 'stable', 'target'}, 'Azure recovery input fields')
    campaign = value['campaign']
    require(re.fullmatch('[a-z][a-z0-9]{3,15}', campaign), 'campaign identifier')
    require(value['stage'] in {'restore', 'a', 'rollback'}, 'private target stage')
    require(all(re.fullmatch('[0-9a-f]{40}', value[k]) for k in ('source_sha', 'stable_deployed_revision')), 'exact source/revision')
    stable, target = value['stable'], value['target']
    require(set(stable) == {'namespace', 'deployment', 'pvc', 'db_host', 'db_name', 'db_role', 'pvc_uid', 'pv_uid', 'pv_name', 'disk_id'}, 'stable identity fields')
    require(stable['namespace'] == stable['deployment'] == 'forgejo' and stable['pvc'] == 'forgejo-data', 'stable identity')
    require(set(target) == {'namespace', 'pvc', 'db_host', 'db_name', 'db_role', 'db_ipv4'}, 'target fields')
    require(target['namespace'] == 'p7-ops-' + campaign and target['pvc'] == 'p7-data', 'target ownership namespace/PVC')
    require(target['db_name'] == f'p7_{campaign}_{value["stage"]}' and target['db_role'] == f'p7_{campaign}_role', 'target DB/role ownership')
    require(target['db_host'] == stable['db_host'] and re.fullmatch(r'[a-z0-9-]+\.postgres\.database\.azure\.com', target['db_host']), 'existing private PostgreSQL only')
    require(target['db_name'] != stable['db_name'] and target['db_role'] != stable['db_role'], 'original database/role forbidden')
    address = ipaddress.IPv4Address(target['db_ipv4'])
    require(any(address in ipaddress.IPv4Network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')), 'private DB IPv4 required')
    require(all(stable[k] for k in ('pvc_uid', 'pv_uid', 'pv_name', 'disk_id')), 'original storage identity required')
    return value


def image(stage):
    prefix = 'FORGEJO_UPGRADE_TO' if stage == 'restore' or stage == 'b' else 'FORGEJO_UPGRADE_FROM'
    tag = PINS['FORGEJO_IMAGE_TAG'] if prefix.endswith('TO') else PINS['FORGEJO_UPGRADE_FROM_IMAGE_TAG']
    return 'code.forgejo.org/forgejo/forgejo:' + tag + '@' + PINS[prefix + '_IMAGE_DIGEST']


def render(value):
    validate_input(value)
    ns = value['target']['namespace']
    labels = {'p7.campaign': value['campaign']}

    def resource(api, kind, name, **kwargs):
        return dict(apiVersion=api, kind=kind, metadata={'name': name, 'namespace': ns, 'labels': labels}, **kwargs)

    def pod(name, container):
        container.update(volumeMounts=[{'name': 'data', 'mountPath': '/data'}, {'name': 'credential', 'mountPath': '/credential', 'readOnly': True}])
        obj = resource('v1', 'Pod', name, spec={
            'restartPolicy': 'Never', 'automountServiceAccountToken': False,
            'securityContext': {'runAsUser': 1000, 'runAsGroup': 1000, 'fsGroup': 1000, 'runAsNonRoot': True},
            'containers': [container], 'volumes': [
                {'name': 'data', 'persistentVolumeClaim': {'claimName': 'p7-data'}},
                {'name': 'credential', 'secret': {'secretName': 'p7-credential', 'defaultMode': 0o440}}]})
        obj['metadata']['annotations'] = {'sidecar.istio.io/inject': 'false'}
        return obj

    helper = pod('p7-data-helper', {'name': 'helper', 'image': image('restore'),
                                  'command': ['sh', '-c', 'exec sleep infinity'],
                                  'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'}, 'limits': {'cpu': '100m', 'memory': '128Mi'}}})
    app = pod('p7-forgejo', {'name': 'forgejo', 'image': image(value['stage']), 'workingDir': '/data',
                           'command': ['forgejo', 'web', '--config', '/data/gitea/conf/app.ini'],
                           'env': [{'name': 'USER', 'value': 'git'}, {'name': 'HOME', 'value': '/data/git'}, {'name': 'GITEA_WORK_DIR', 'value': '/data'}],
                           'ports': [{'name': 'http', 'containerPort': 3000}],
                           'readinessProbe': {'exec': {'command': ['sh', '-c', 'wget -q -O /dev/null http://127.0.0.1:3000/api/healthz']}, 'periodSeconds': 5, 'timeoutSeconds': 3},
                           'resources': {'requests': {'cpu': '500m', 'memory': '1024Mi'}, 'limits': {'cpu': '500m', 'memory': '1024Mi'}}})
    # DB client has no application data volume and never receives administrator credentials.
    db = resource('v1', 'Pod', 'p7-db-client', spec={
        'restartPolicy': 'Never', 'automountServiceAccountToken': False,
        'securityContext': {'runAsUser': 1000, 'runAsGroup': 1000, 'fsGroup': 1000, 'runAsNonRoot': True},
        'containers': [{'name': 'postgres', 'image': PINS['POSTGRES_IMAGE'], 'command': ['sh', '-c', 'exec sleep infinity'],
                        'resources': {'requests': {'cpu': '250m', 'memory': '512Mi'}, 'limits': {'cpu': '250m', 'memory': '512Mi'}},
                        'env': [{'name': key, 'value': val} for key, val in {
                            'PGHOST': value['target']['db_host'], 'PGDATABASE': value['target']['db_name'],
                            'PGUSER': value['target']['db_role'], 'PGSSLMODE': 'verify-full', 'PGSSLROOTCERT': 'system'}.items()] +
                               [{'name': 'PGPASSWORD', 'valueFrom': {'secretKeyRef': {'name': 'p7-credential', 'key': 'password'}}}]}]})
    db['metadata']['annotations'] = {'sidecar.istio.io/inject': 'false'}
    checkpoint_helper = json.loads(json.dumps(helper))
    checkpoint_helper['metadata'].update(name='p7-checkpoint-helper', namespace='forgejo')
    checkpoint_helper['spec']['securityContext'].pop('fsGroup')
    checkpoint_helper['spec']['containers'][0]['volumeMounts'] = [{'name': 'data', 'mountPath': '/data', 'readOnly': True}]
    checkpoint_helper['spec']['volumes'] = [{'name': 'data', 'persistentVolumeClaim': {'claimName': value['stable']['pvc'], 'readOnly': True}}]
    checkpoint_db = json.loads(json.dumps(db))
    checkpoint_db['metadata'].update(name='p7-checkpoint-db', namespace='forgejo')
    for env in checkpoint_db['spec']['containers'][0]['env']:
        if env['name'] == 'PGDATABASE':
            env['value'] = value['stable']['db_name']
        elif env['name'] == 'PGUSER':
            env['value'] = value['stable']['db_role']
        elif env['name'] == 'PGPASSWORD':
            env['valueFrom']['secretKeyRef']['name'] = 'forgejo-db'
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns, 'labels': dict(labels, **{'istio-injection': 'disabled'})}}
    quota = resource('v1', 'ResourceQuota', 'p7-boundary', spec={'hard': {'pods': '2', 'requests.cpu': '750m', 'requests.memory': '1536Mi',
                                                                      'persistentvolumeclaims': '1', 'requests.storage': '10Gi', 'secrets': '1'}})
    pvc = resource('v1', 'PersistentVolumeClaim', 'p7-data', spec={'accessModes': ['ReadWriteOnce'], 'storageClassName': 'managed-csi',
                                                               'resources': {'requests': {'storage': '10Gi'}}})
    # Operator applies the separate app file only after restore/rebind/guard and helper removal.
    outputs = {'boundary.json': {'apiVersion': 'v1', 'kind': 'List', 'items': [namespace, quota]},
            'pvc.json': pvc, 'helper.json': helper, 'db-client.json': db, 'app.json': app,
            'checkpoint-helper.json': checkpoint_helper, 'checkpoint-db.json': checkpoint_db}
    if value['stage'] == 'a':
        upgraded = json.loads(json.dumps(app))
        upgraded['spec']['containers'][0]['image'] = image('b')
        outputs['app-b.json'] = upgraded
    return outputs


def admission(value, pods):
    """Inspect actual admitted Pods, including injected containers/init/overhead."""
    validate_input(value)
    expected = {}
    for obj in render(value).values():
        if obj['kind'] == 'Pod':
            expected.setdefault(obj['metadata']['name'], obj)
    require(len(pods['items']) <= 2, 'temporary Pod count')
    cpu, memory = 0, 0
    for pod in pods['items']:
        name = pod['metadata']['name']
        require(name in expected and pod['metadata']['namespace'] == expected[name]['metadata']['namespace'] and
                pod['metadata']['labels'].get('p7.campaign') == value['campaign'], 'admitted Pod ownership')
        spec = pod['spec']
        require(not spec.get('initContainers') and not spec.get('ephemeralContainers') and
                len(spec['containers']) == 1 and spec.get('automountServiceAccountToken') is False and
                not any(spec.get(k) for k in ('hostNetwork', 'hostPID', 'hostIPC')), 'unexpected injected/privileged container')
        container = spec['containers'][0]
        template = expected[name]['spec']['containers'][0]
        allowed_images = {template['image']}
        if name == 'p7-forgejo' and value['stage'] == 'a':
            allowed_images.add(image('b'))
        require(container['image'] in allowed_images and container['name'] == template['name'], 'admitted image/container drift')
        require(not container.get('envFrom') and all(container.get(k, []) == template.get(k, [])
                for k in ('command', 'args', 'env', 'volumeMounts')), 'admitted command/config override')
        security = container.get('securityContext', {})
        require(not security.get('privileged') and not security.get('allowPrivilegeEscalation') and
                not security.get('capabilities', {}).get('add') and
                spec['securityContext'].get('runAsUser') == 1000, 'admitted privilege drift')
        require(spec.get('volumes', []) == expected[name]['spec'].get('volumes', []), 'admitted volume drift')
        for resource in [container['resources']['requests'], spec.get('overhead', {})]:
            cpu_value = resource.get('cpu', '0')
            memory_value = resource.get('memory', '0')
            require(re.fullmatch(r'[0-9]+m?', cpu_value) and re.fullmatch(r'[0-9]+(?:Mi|Gi)?', memory_value), 'unsupported admitted quantity')
            cpu += int(cpu_value[:-1]) if cpu_value.endswith('m') else int(cpu_value) * 1000
            memory += int(memory_value[:-2]) * (1024**2 if memory_value.endswith('Mi') else 1024**3) if memory_value.endswith(('Mi', 'Gi')) else int(memory_value)
    require(cpu <= 750 and memory <= 1536 * 1024**2, 'admitted requests including overhead exceed approval design')
    return {'pods': len(pods['items']), 'cpu_millicores': cpu, 'memory_bytes': memory}


def config(path):
    parser = configparser.RawConfigParser(strict=True)
    parser.read_string('[DEFAULT]\n' + Path(path).read_text())
    require(parser.has_section('database'), 'restored database config missing')
    require(all(s == s.lower() for s in parser.sections() if s.lower() in {'server', 'database'}), 'ambiguous section case')
    return parser


def database_config(path, target):
    parser = config(path)
    expected = {'DB_TYPE': 'postgres', 'HOST': target['db_host'] + ':5432', 'NAME': target['db_name'],
                'USER': target['db_role'], 'SSL_MODE': 'verify-full'}
    require(all(parser.get('database', key, fallback=None) == val for key, val in expected.items()), 'restored config could address original/wrong database')
    require(parser.get('database', 'PASSWD', fallback='') and not parser.get('database', 'URL', fallback=''), 'ambiguous database password/URL')
    require(parser.get('server', 'HTTP_ADDR', fallback='') == '127.0.0.1' and
            parser.get('server', 'HTTP_PORT', fallback='3000') == '3000' and
            parser.get('server', 'PROTOCOL', fallback='http') == 'http' and
            parser.get('server', 'DISABLE_SSH', fallback='false').lower() == 'true', 'private app must bind only Pod loopback HTTP')
    return expected


def rebind(value, ini, password_file):
    validate_input(value)
    ini, password_file = Path(ini), Path(password_file)
    require(ini.is_file() and not ini.is_symlink() and ini.stat().st_mode & 0o077 == 0, 'private restored app.ini required')
    require(password_file.is_file() and not password_file.is_symlink() and password_file.stat().st_mode & 0o077 == 0, 'private password file required')
    password = password_file.read_text().strip()
    require(re.fullmatch('[a-zA-Z0-9]{32,128}', password), 'temporary password must be random alphanumeric 32-128 characters')
    parser = config(ini)
    # Input is the extracted target copy, never an original mounted source file.
    source_names = {value['stable']['db_name'], value['target']['db_name']}
    if value['stage'] == 'rollback':
        source_names.add('p7_' + value['campaign'] + '_a')
    require(parser.get('database', 'NAME') in source_names, 'unknown restored database ownership')
    require(parser.get('database', 'HOST') == value['stable']['db_host'] + ':5432' and
            parser.get('database', 'USER') in {value['stable']['db_role'], value['target']['db_role']}, 'unknown restored DB server/role')
    require(not parser.get('database', 'URL', fallback=''), 'database URL override forbidden')
    replacements = {'database': {'DB_TYPE': 'postgres', 'HOST': value['target']['db_host'] + ':5432', 'NAME': value['target']['db_name'],
                                'USER': value['target']['db_role'], 'PASSWD': password, 'SSL_MODE': 'verify-full'},
                    'server': {'HTTP_ADDR': '127.0.0.1'}}
    lines = (ini.read_text().rstrip('\n') + '\n').splitlines(keepends=True)
    result, section = [], ''
    observed = set()
    for line in lines:
        match = re.fullmatch(r'\s*\[([^]]+)\]\s*', line.strip())
        if match:
            result.extend(f'{k} = {v}\n' for k, v in replacements.get(section, {}).items())
            section = match[1].lower()
            observed.add(section)
        if section in replacements and '=' in line and not line.lstrip().startswith(('#', ';')):
            if line.split('=', 1)[0].strip().upper() in replacements[section]:
                continue
        result.append(line)
    result.extend(f'{k} = {v}\n' for k, v in replacements.get(section, {}).items())
    if 'server' not in observed:
        result.append('\n[server]\nHTTP_ADDR = 127.0.0.1\n')
    ini.write_text(''.join(result))
    database_config(ini, value['target'])


def target_guard(value, snapshot, ini):
    validate_input(value)
    target, stable = value['target'], value['stable']
    require(snapshot['namespace']['metadata']['name'] == target['namespace'] and
            snapshot['namespace']['metadata']['labels'].get('p7.campaign') == value['campaign'], 'target namespace ownership')
    pvc, pv = snapshot['pvc'], snapshot['pv']
    require(pvc['metadata']['name'] == target['pvc'] and pvc['metadata']['namespace'] == target['namespace'] and
            pvc['metadata']['labels'].get('p7.campaign') == value['campaign'] and
            pvc['metadata']['uid'] != stable['pvc_uid'] and pvc['spec']['volumeName'] == pv['metadata']['name'] and
            pvc['spec']['resources']['requests']['storage'] == '10Gi' and pvc['spec']['storageClassName'] == 'managed-csi' and
            pvc['status']['phase'] == 'Bound', 'fresh target PVC identity')
    require(pv['metadata']['uid'] != stable['pv_uid'] and pv['metadata']['name'] != stable['pv_name'] and
            pv['spec']['csi']['driver'] == 'disk.csi.azure.com' and
            pv['spec']['csi']['volumeHandle'].lower() != stable['disk_id'].lower() and
            pv['spec']['claimRef']['uid'] == pvc['metadata']['uid'], 'original disk/PV forbidden')
    require(snapshot['database'] == {'current_database': target['db_name'], 'current_user': target['db_role'],
                                     'owner': target['db_role'], 'public_tables': 0, 'other_sessions': 0,
                                     'server_address': target['db_ipv4'], 'ssl': True}, 'target DB must be fresh, exclusive, private TLS and role-owned before restore')
    require(snapshot['pods'] == [], 'target Pods must be absent at pre-restore guard')
    database_config(ini, target)
    return {'stage': value['stage'], 'target_namespace': target['namespace'], 'pvc_uid': pvc['metadata']['uid'],
            'pv_uid': pv['metadata']['uid'], 'db_name': target['db_name'], 'config_database': 'target-only', 'fresh_before_restore': True}


def bundle(directory):
    directory = Path(directory)
    require(directory.stat().st_mode & 0o777 == 0o700 and not directory.is_symlink(), 'checkpoint mode 0700')
    manifest = load(directory / 'manifest.json')
    validate_input(manifest['input'])
    require({p.name for p in directory.iterdir()} == set(COMPONENTS) | {'manifest.json'}, 'checkpoint file inventory')
    require(manifest['backup_complete'] is True and manifest['writer_absent'] is True and manifest['queue_flushed'] is True,
            'coordinated checkpoint incomplete')
    stable = manifest['input']['stage'] == 'restore'
    prefix = 'FORGEJO_UPGRADE_TO' if stable else 'FORGEJO_UPGRADE_FROM'
    version = '15.0.11+gitea-1.22.0' if stable else '15.0.9+gitea-1.22.0'
    identities = {'code.forgejo.org/forgejo/forgejo@' + PINS[prefix + suffix] for suffix in ('_IMAGE_DIGEST', '_AMD64_DIGEST')}
    require(manifest['version'] == version and manifest['image_spec'] == image('restore' if stable else 'a') and
            manifest['image_id'].removeprefix('docker-pullable://') in identities, 'checkpoint version/image')
    require(set(manifest['components']) == set(COMPONENTS), 'checkpoint components')
    total = (directory / 'manifest.json').stat().st_size
    for name in COMPONENTS:
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_mode & 0o777 == 0o600, 'checkpoint component mode/type')
        total += path.stat().st_size
        require(type(manifest['components'][name]['size']) is int and
                0 < path.stat().st_size == manifest['components'][name]['size'], 'checkpoint size')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        require(digest.hexdigest() == manifest['components'][name]['sha256'], 'checkpoint checksum')
    require(total <= 16 * 1024**3, 'checkpoint exceeds approved 16GiB boundary')
    with tarfile.open(directory / 'application-data.tar') as archive:
        for entry in archive:
            require(not entry.name.startswith('/') and '..' not in Path(entry.name).parts and
                    not entry.isdev() and not entry.isfifo(), 'unsafe checkpoint archive entry')
            if entry.issym() or entry.islnk():
                require(not entry.linkname.startswith('/') and '..' not in Path(entry.linkname).parts, 'unsafe archive link')
    secrets = load(directory / 'secrets.json')
    names = {'forgejo-admin', 'forgejo-db', 'forgejo-inline-config'} if stable else {'p7-credential'}
    namespace = 'forgejo' if stable else manifest['input']['target']['namespace']
    require(isinstance(secrets, list) and {s['metadata']['name'] for s in secrets} == names and len(secrets) == len(names) and
            all(s['metadata']['namespace'] == namespace and s.get('data') for s in secrets), 'Azure checkpoint secret inventory')
    return manifest


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'render' and len(sys.argv) == 4:
        directory = Path(sys.argv[3])
        manifests = render(load(sys.argv[2]))
        directory.mkdir(mode=0o700)
        for name, obj in manifests.items():
            with (directory / name).open('x') as stream:
                json.dump(obj, stream, indent=2)
                stream.write('\n')
    elif mode == 'rebind' and len(sys.argv) == 5:
        rebind(load(sys.argv[2]), sys.argv[3], sys.argv[4])
    elif mode == 'guard' and len(sys.argv) == 5:
        print(json.dumps(target_guard(load(sys.argv[2]), load(sys.argv[3]), sys.argv[4]), indent=2))
    elif mode == 'config' and len(sys.argv) == 4:
        value = validate_input(load(sys.argv[2]))
        database_config(sys.argv[3], value['target'])
        print('target-only database configuration')
    elif mode == 'admission' and len(sys.argv) == 4:
        print(json.dumps(admission(load(sys.argv[2]), load(sys.argv[3])), indent=2))
    elif mode == 'bundle' and len(sys.argv) == 3:
        bundle(sys.argv[2])
        print('coordinated Azure checkpoint components validated')
    else:
        raise ValueError('usage: azure-recovery.py render INPUT OUTPUT_DIR | rebind INPUT RESTORED_INI PASSWORD_FILE | guard INPUT SNAPSHOT RESTORED_INI | config INPUT RESTORED_INI | admission INPUT ADMITTED_PODS | bundle DIR')


if __name__ == '__main__':
    try:
        os.umask(0o077)
        main()
    except Exception:
        print('Azure recovery adapter refused input; original resources must remain untouched', file=sys.stderr)
        sys.exit(1)
