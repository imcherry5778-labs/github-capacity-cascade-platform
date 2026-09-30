#!/usr/bin/env python3
"""P3-W3 exact v15 pair proof; shared checkpoint/doctor contract is owned by W2."""
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('recovery', Path(__file__).with_name('validate-recovery.py'))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)
require, load = recovery.require, recovery.load
ROOT = Path(__file__).resolve().parents[1]
PINS = dict(line.split('=', 1) for line in (ROOT / 'versions.env').read_text().splitlines()
            if line and not line.startswith('#'))
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
HASH = re.compile(r'^[0-9a-f]{64}$')
SHA = re.compile(r'^[0-9a-f]{40}$')
PHASES = (
    'upstream_revalidated', 'regression_verified', 'fresh_a_prepared', 'source_ready', 'fixture_ready',
    'a_runtime_verified', 'source_doctor_calibrated', 'postgres_bootstrap_inventoried',
    'autosync_stopped', 'queue_flushed', 'forgejo_stopped', 'bundle_validated',
    'upgrade_writer_absent', 'b_started', 'b_runtime_verified', 'b_continuity',
    'b_marker_persisted', 'b_queue_flushed', 'b_stopped', 'source_cleaned',
    'target_prepared', 'database_restored', 'application_data_restored', 'secrets_restored',
    'restore_complete', 'forgejo_started', 'healthz', 'rollback_runtime_verified',
    'target_doctor_verified', 'retained_state', 'same_pat', 'same_session', 'marker_absence',
    'new_write', 'database_write', 'filesystem_write', 'post_rollback_write_verified',
    'credential_hygiene', 'maintenance_a_retained', 'target_cleaned', 'raw_cleaned',
)


def database_authority(value):
    require(isinstance(value, dict) and set(value) ==
            {'catalog', 'version', 'forgejo_version', 'forgejo_migration'}, 'DB authority inventory')
    catalog = []
    for table in ('forgejo_migration', 'forgejo_version', 'version'):
        columns = [('id', 'character varying'), ('created_unix', 'bigint')] if table == 'forgejo_migration' else [('id', 'bigint'), ('version', 'bigint')]
        catalog.extend(dict(table_name=table, column_name=c, data_type=t, ordinal_position=i)
                       for i, (c, t) in enumerate(columns, 1))
    require(value['catalog'] == catalog, 'DB authority columns changed')
    for key in ('version', 'forgejo_version'):
        rows = value[key]
        require(isinstance(rows, list) and len(rows) == 1 and rows[0].get('id') == 1 and
                type(rows[0].get('version')) is int and rows[0]['version'] > 0, 'DB version value')
    ids = value['forgejo_migration']
    require(isinstance(ids, list) and ids and all(isinstance(i, str) and re.fullmatch(r'v[0-9]+[a-z]_[a-z0-9_-]+', i) for i in ids)
            and ids == sorted(set(ids)), 'DB migration IDs')


def validate_runtime(value):
    stage = value.get('stage')
    require(stage in {'a', 'b', 'rollback'}, 'runtime stage')
    from_a = stage != 'b'
    tag = PINS['FORGEJO_UPGRADE_FROM_IMAGE_TAG'] if from_a else PINS['FORGEJO_IMAGE_TAG']
    prefix = 'FORGEJO_UPGRADE_FROM' if from_a else 'FORGEJO_UPGRADE_TO'
    digest = PINS[prefix + '_IMAGE_DIGEST']
    child = PINS[prefix + '_AMD64_DIGEST']
    require(DIGEST.fullmatch(digest) and DIGEST.fullmatch(child), 'unresolved official image')
    image = 'code.forgejo.org/forgejo/forgejo:' + tag + '@' + digest
    identities = {'code.forgejo.org/forgejo/forgejo@' + d for d in (digest, child)}
    require(value.get('tag') == tag and value.get('digest') == digest and
            value.get('version', '').startswith(tag.removesuffix('-rootless') + '+') and
            value.get('image_spec') == image and value.get('image_id') in identities,
            'exact application version/image identity')
    require(value.get('init_image_specs') == [image] * 3 and
            len(value.get('init_image_ids', [])) == 3 and all(i in identities for i in value['init_image_ids']),
            'first init/runtime image identity')
    require(SHA.fullmatch(value.get('source_sha', '')) and type(value.get('source_dirty')) is bool, 'source provenance')
    require(value.get('server_id'), 'server identity missing')
    for name in ('forgejo', 'postgres'):
        require(all(value.get('storage', {}).get(name, {}).get(k) for k in ('pvc_uid', 'pv_name', 'pv_uid')), 'storage identity missing')
    require(value.get('postgres_image_spec') == PINS['POSTGRES_IMAGE'] and value.get('postgres_image_id') and
            value.get('postgres_version', '').startswith('psql (PostgreSQL) 17.11'), 'PostgreSQL identity')
    require(value.get('chart_version') == PINS['FORGEJO_CHART_VERSION'] and
            value.get('chart_digest') == PINS['FORGEJO_CHART_DIGEST'] and
            value.get('argo_values_revision') == PINS['FORGEJO_VALUES_REVISION'] and
            value.get('argo_version') == PINS['ARGOCD_VERSION'], 'chart/Argo provenance drift')
    require(value.get('autosync') == {'enabled': False, 'prune': False, 'selfHeal': True}, 'maintenance ownership')
    sources = value.get('argo_sources', [])
    require(len(sources) == 2 and sources[0] == {
        'repoURL': PINS['FORGEJO_CHART'], 'path': '.', 'targetRevision': PINS['FORGEJO_CHART_VERSION'],
        'helm': {'releaseName': 'forgejo', 'valueFiles': ['$values/platform/forgejo/values-common.yaml', '$values/platform/forgejo/values-local.yaml'],
                 'parameters': [{'name': 'image.tag', 'value': tag}, {'name': 'image.digest', 'value': digest}]}}, 'maintenance chart/source override')
    require(sources[1] == {'repoURL': 'https://github.com/imcherry5778-labs/github-capacity-cascade-platform.git',
                          'targetRevision': PINS['FORGEJO_VALUES_REVISION'], 'ref': 'values'}, 'Git source override')
    require(HASH.fullmatch(value.get('pat_file_sha256', '')) and HASH.fullmatch(value.get('cookie_file_sha256', '')) and
            value.get('session_login_count') == 1, 'credential identity/re-login')
    database_authority(value.get('database_authority'))


def validate_result(result, clean=True):
    require(result.get('schema_version') == 1 and result.get('completed') is True, 'incomplete upgrade proof')
    stages = result['runtime']
    require(set(stages) == {'a', 'b', 'rollback'}, 'runtime inventory')
    a, b, rollback = (stages[name] for name in ('a', 'b', 'rollback'))
    require(a.get('version') != b.get('version'), 'equal A/B version')
    for name, value in stages.items():
        require(value.get('stage') == name, 'first-start/direct downgrade stage')
        validate_runtime(value)
    require(result.get('source_sha') == a['source_sha'] and all(v['source_sha'] == a['source_sha'] for v in stages.values()), 'source SHA differs')
    require(result.get('source_dirty') == a['source_dirty'] and all(v['source_dirty'] == a['source_dirty'] for v in stages.values()), 'source dirty differs')
    if clean:
        require(result['source_dirty'] is False, 'clean exact-head proof required')
    regression = result['regression']
    baseline = regression['baseline']
    summary = baseline['summary']
    require(summary.get('source_sha') == a['source_sha'] and summary.get('operation_samples') == 45 and
            summary.get('attempt_samples') == 45 and baseline.get('p1_p2_runtime') is True, 'baseline/runtime regression missing')
    require(len(baseline.get('run_provenance', [])) == 6 and all(h.get('source_sha') == a['source_sha'] and
            h.get('dirty') == a['source_dirty'] for h in baseline['run_provenance']), 'regression source differs')
    recovery.validate_result_data(regression['recovery'])
    require(regression['recovery'].get('source_sha') == a['source_sha'] and
            regression['recovery'].get('source_dirty') == a['source_dirty'], 'recovery regression source differs')
    require(regression['recovery'].get('runtime', {}).get('forgejo_version') == b['version'] and
            regression['recovery']['runtime'].get('forgejo_image_id') == b['image_id'], 'recovery runtime differs from B')
    records = result['phase_records']
    require(all(r.get('success') is True and 'phase' in r for r in records), 'failed/raw incomplete phase')
    names = [r['phase'] for r in records]
    require(names == list(PHASES), 'missing/duplicate/reordered lifecycle phase')
    checkpoint = result['checkpoint']
    require(checkpoint.get('backup_complete') is True and checkpoint.get('database_authority') == a['database_authority'], 'incomplete A checkpoint/DB authority')
    require(checkpoint.get('source_sha') == a['source_sha'] and checkpoint.get('source_dirty') == a['source_dirty'] and
            checkpoint.get('source_server_id') == a['server_id'] and checkpoint.get('source_storage') == a['storage'] and
            checkpoint.get('forgejo_version') == a['version'] and checkpoint.get('forgejo_image_id') == a['image_id'], 'checkpoint differs from A')
    require(set(checkpoint.get('components', {})) == set(recovery.COMPONENTS), 'checkpoint components')
    for name, component in checkpoint['components'].items():
        require(component.get('filename') == name and component.get('result') == 'success' and
                type(component.get('size')) is int and component['size'] > 0 and HASH.fullmatch(component.get('sha256', '')), 'incomplete checkpoint component')
    fixture = checkpoint.get('fixture', {})
    require(all(fixture.get(k) for k in ('user', 'repository', 'main_sha', 'feature_sha', 'pull_number', 'issue_number', 'pat_precheck', 'session_precheck')), 'fixture/precheck incomplete')
    require(a['server_id'] == b['server_id'] and a['storage'] == b['storage'], 'upgrade changed server/storage')
    require(a['server_id'] != rollback['server_id'], 'rollback server reused')
    for name in ('forgejo', 'postgres'):
        require(all(a['storage'][name][k] != rollback['storage'][name][k] for k in ('pvc_uid', 'pv_name', 'pv_uid')), 'rollback storage reused')
    for key in ('pat_file_sha256', 'cookie_file_sha256', 'postgres_image_id', 'postgres_version'):
        require(a[key] == b[key] == rollback[key], 'credential substitution/DB upgrade')
    require(rollback['database_authority'] == a['database_authority'], 'rollback DB metadata differs')
    require(result.get('schema_metadata_rewritten') is False, 'manual DB metadata rewrite')
    marker, absent, write = (result[k] for k in ('b_marker', 'marker_absence', 'post_write'))
    require(SHA.fullmatch(marker.get('commit', '')) and marker['commit'] not in (fixture['main_sha'], fixture['feature_sha']) and
            type(marker.get('issue_number')) is int and marker['issue_number'] > int(fixture['issue_number']) and
            marker.get('issue_title', '').startswith('b-only issue '), 'B-only marker not created')
    for proof in (marker, absent, write):
        require(all(proof.get(k) is True for k in ('api', 'database', 'filesystem')), 'marker/write persistence proof missing')
    require(absent.get('absent_commit') == marker['commit'] and absent.get('absent_issue') == marker['issue_number'] and
            absent.get('restored_main') == fixture['main_sha'] and absent.get('before_new_write') is True, 'marker absence missing/after new write')
    require(SHA.fullmatch(write.get('commit', '')) and write['commit'] not in (marker['commit'], fixture['main_sha']) and
            type(write.get('issue_number')) is int and write.get('issue_title', '').startswith('restored issue ') and
            write['issue_title'] != marker['issue_title'], 'post-rollback write missing')
    for name, doctor in result['doctor'].items():
        runtime = stages['b' if name == 'upgraded' else 'rollback' if name in {'target', 'post-write'} else 'a']
        require(doctor.get('forgejo_version') == runtime['version'] and doctor.get('forgejo_image_id') == runtime['image_id'], 'doctor runtime differs')
        require(doctor.get('selected') == [{'name': k, 'reason': v} for k, v in recovery.DOCTOR_CHECKS.items()] and
                doctor.get('checks') == {k: {'status': 'pass', 'command_exit': 0, 'diagnostics': 0} for k in recovery.DOCTOR_CHECKS}, 'doctor failure promoted')
        require(doctor.get('paths') == {'status': 'known_source_baseline_diagnostic', 'finding': 'missing_/data/log', 'scope': 'console_logging_only', 'command_exit': 1} and
                doctor.get('effective_config', {}).get('lfs_start_server') is False and
                doctor.get('not_applicable', {}).get('gc-lfs') == 'LFS_START_SERVER=false', 'doctor classification')
        baseline_doctor = result['doctor']['source']
        require(doctor.get('inventory') and doctor['inventory'] == baseline_doctor.get('inventory'), 'doctor inventory changed')
        effective = lambda d: {k: v for k, v in d['effective_config'].items() if not k.endswith('_setting')}
        require(effective(doctor) == effective(baseline_doctor), 'doctor effective config changed')
    require(set(result['doctor']) == {'source', 'upgraded', 'target', 'post-write'}, 'doctor inventory missing')
    require(len(result['upstream']) == 2 and all(v.get('reviewed') is True and HASH.fullmatch(v.get('sha256', '')) and
            v.get('url') == f'https://codeberg.org/forgejo/forgejo/raw/branch/forgejo/release-notes-published/{v.get("version")}.md' for v in result['upstream']) and
            [v.get('version') for v in result['upstream']] == ['15.0.8', '15.0.9'], 'official upstream evidence')
    expected = 'no schema-version change observed' if a['database_authority'] == b['database_authority'] else 'migration observed'
    require(result.get('database_observation') == expected, 'DB migration claim differs from observation')
    return result


def finalize(directory):
    directory = Path(directory)
    runtime = {stage: load(directory / f'runtime-{stage}.json') for stage in ('a', 'b', 'rollback')}
    result = {'schema_version': 1, 'completed': True, 'source_sha': runtime['a']['source_sha'],
              'source_dirty': runtime['a']['source_dirty'], 'runtime': runtime,
              'regression': {'baseline': load(directory / 'regression-baseline.json'),
                             'recovery': load(directory / 'regression-recovery.json')},
              'checkpoint': load(directory / 'checkpoint.json'),
              'b_marker': load(directory / 'b-marker.json'), 'marker_absence': load(directory / 'marker-absence.json'),
              'post_write': load(directory / 'post-write.json'), 'schema_metadata_rewritten': False,
              'doctor': {stage: load(directory / f'doctor-{stage}.json') for stage in ('source', 'upgraded', 'target', 'post-write')},
              'upstream': [json.loads(line) for line in (directory / 'upstream.jsonl').read_text().splitlines()],
              'phase_records': [json.loads(line) for line in (directory / 'phases.jsonl').read_text().splitlines()]}
    result['database_observation'] = 'no schema-version change observed' if runtime['a']['database_authority'] == runtime['b']['database_authority'] else 'migration observed'
    (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    validate_result(result, clean=False)
    print('valid W3 lifecycle; ' + ('exploratory dirty source' if result['source_dirty'] else 'clean exact-head source'))


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'regressions':
            directory, baseline_path, recovery_path, sha, dirty = sys.argv[2:]
            operations_spec = importlib.util.spec_from_file_location('operations', Path(__file__).with_name('validate-operation-results.py'))
            operations = importlib.util.module_from_spec(operations_spec)
            operations_spec.loader.exec_module(operations)
            baseline_path, directory = Path(baseline_path), Path(directory)
            summary = operations.summarize(baseline_path.parent)
            require(summary == load(baseline_path), 'baseline summary differs from raw results')
            headers = [json.loads(p.read_text().splitlines()[0]) for p in sorted(baseline_path.parent.glob('*/events.jsonl'))]
            require(all(h['source_sha'] == sha and h['dirty'] == json.loads(dirty) for h in headers), 'baseline source differs')
            rec = recovery.validate_result(recovery_path)
            require(rec.get('source_sha') == sha and rec.get('source_dirty') == json.loads(dirty), 'W2 source differs')
            evidence = {'summary': summary, 'p1_p2_runtime': True,
                        'run_provenance': [{k: h[k] for k in ('run_id', 'source_sha', 'dirty')} for h in headers]}
            (directory / 'regression-baseline.json').write_text(json.dumps(evidence, indent=2) + '\n')
            (directory / 'regression-recovery.json').write_text(json.dumps(rec, indent=2) + '\n')
            sys.exit(0)
        command, path = sys.argv[1:]
        if command == 'finalize':
            finalize(path)
        elif command == 'runtime':
            validate_runtime(load(path))
        elif command == 'result':
            validate_result(load(path))
        else:
            raise ValueError('usage: validate-upgrade.py runtime FILE | result FILE | finalize DIR')
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f'invalid upgrade evidence: {exc}', file=sys.stderr)
        sys.exit(1)
