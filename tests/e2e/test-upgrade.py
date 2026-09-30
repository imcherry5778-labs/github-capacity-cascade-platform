#!/usr/bin/env python3
"""Reject invalid W3 proof, especially success with the wrong state/credential boundary."""
import copy
import importlib.util
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('upgrade', ROOT / 'scripts/validate-upgrade.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
rec_spec = importlib.util.spec_from_file_location('recovery_tests', ROOT / 'tests/e2e/test-recovery.py')
rec_tests = importlib.util.module_from_spec(rec_spec)
rec_spec.loader.exec_module(rec_tests)


def storage(seed):
    return {name: {k: seed + name + k for k in ('pvc_uid', 'pv_name', 'pv_uid')} for name in ('forgejo', 'postgres')}


def runtime(stage):
    a = stage != 'b'
    tag = u.PINS['FORGEJO_UPGRADE_FROM_IMAGE_TAG'] if a else u.PINS['FORGEJO_IMAGE_TAG']
    digest = u.PINS['FORGEJO_UPGRADE_FROM_IMAGE_DIGEST' if a else 'FORGEJO_UPGRADE_TO_IMAGE_DIGEST']
    image = 'code.forgejo.org/forgejo/forgejo:' + tag + '@' + digest
    catalog = []
    for table in ('forgejo_migration', 'forgejo_version', 'version'):
        cols = [('id', 'character varying'), ('created_unix', 'bigint')] if table == 'forgejo_migration' else [('id', 'bigint'), ('version', 'bigint')]
        catalog += [dict(table_name=table, column_name=c, data_type=t, ordinal_position=i) for i, (c, t) in enumerate(cols, 1)]
    return dict(stage=stage, source_sha='a' * 40, source_dirty=False, version=tag[:-9] + '+gitea-1.22.0', tag=tag,
                digest=digest, image_spec=image, image_id='code.forgejo.org/forgejo/forgejo@' + digest,
                init_image_specs=[image] * 3, init_image_ids=['code.forgejo.org/forgejo/forgejo@' + digest] * 3,
                server_id='target' if stage == 'rollback' else 'source', storage=storage('t' if stage == 'rollback' else 's'),
                database_authority={'catalog': catalog, 'version': [{'id': 1, 'version': 305}],
                                    'forgejo_version': [{'id': 1, 'version': 44}], 'forgejo_migration': ['v14a_example']},
                postgres_image_spec=u.PINS['POSTGRES_IMAGE'], postgres_image_id='postgres@sha256:p', postgres_version='psql (PostgreSQL) 17.11',
                chart_version=u.PINS['FORGEJO_CHART_VERSION'], chart_digest=u.PINS['FORGEJO_CHART_DIGEST'],
                argo_values_revision=u.PINS['FORGEJO_VALUES_REVISION'], argo_version=u.PINS['ARGOCD_VERSION'],
                argo_sources=[{'repoURL': u.PINS['FORGEJO_CHART'], 'path': '.', 'targetRevision': u.PINS['FORGEJO_CHART_VERSION'],
                               'helm': {'releaseName': 'forgejo', 'valueFiles': ['$values/platform/forgejo/values-common.yaml', '$values/platform/forgejo/values-local.yaml'],
                                        'parameters': [{'name': 'image.tag', 'value': tag}, {'name': 'image.digest', 'value': digest}]}},
                              {'repoURL': 'https://github.com/imcherry5778-labs/github-capacity-cascade-platform.git', 'targetRevision': u.PINS['FORGEJO_VALUES_REVISION'], 'ref': 'values'}],
                autosync={'enabled': False, 'prune': False, 'selfHeal': True}, pat_file_sha256='d' * 64, cookie_file_sha256='e' * 64, session_login_count=1)


def proof():
    stages = {stage: runtime(stage) for stage in ('a', 'b', 'rollback')}
    a = stages['a']
    rec = rec_tests.RecoveryValidationTest().result()
    rec.update(source_sha=a['source_sha'], source_dirty=False,
               runtime={'forgejo_version': stages['b']['version'], 'forgejo_image_id': stages['b']['image_id']})
    regression = {'baseline': {'summary': {'source_sha': a['source_sha'], 'operation_samples': 45, 'attempt_samples': 45},
                               'p1_p2_runtime': True,
                               'run_provenance': [{'run_id': str(i), 'source_sha': a['source_sha'], 'dirty': False} for i in range(6)]},
                  'recovery': rec}
    return dict(schema_version=1, completed=True, source_sha=a['source_sha'], source_dirty=False,
                runtime=stages, regression=regression, phase_records=[{'phase': p, 'success': True} for p in u.PHASES],
                checkpoint={'source_sha': a['source_sha'], 'source_dirty': False, 'source_server_id': a['server_id'], 'source_storage': a['storage'],
                            'forgejo_version': a['version'], 'forgejo_image_id': a['image_id'], 'database_authority': a['database_authority'], 'backup_complete': True,
                            'components': {n: {'filename': n, 'result': 'success', 'size': 10, 'sha256': 'f' * 64} for n in u.recovery.COMPONENTS},
                            'fixture': {'user': 'dev', 'repository': 'journey', 'main_sha': '1' * 40, 'feature_sha': '2' * 40,
                                        'pull_number': '1', 'issue_number': '2', 'pat_precheck': True, 'session_precheck': True}},
                schema_metadata_rewritten=False, database_observation='no schema-version change observed',
                b_marker={'commit': '3' * 40, 'issue_number': 3, 'issue_title': 'b-only issue run', 'api': True, 'database': True, 'filesystem': True},
                marker_absence={'restored_main': '1' * 40, 'absent_commit': '3' * 40, 'absent_issue': 3, 'api': True, 'database': True, 'filesystem': True, 'before_new_write': True},
                post_write={'commit': '4' * 40, 'issue_number': 3, 'issue_title': 'restored issue run', 'api': True, 'database': True, 'filesystem': True},
                doctor={name: {'forgejo_version': stages[stage]['version'], 'forgejo_image_id': stages[stage]['image_id'],
                              'inventory': [{'name': k} for k in u.recovery.DOCTOR_CHECKS],
                              'selected': [{'name': k, 'reason': v} for k, v in u.recovery.DOCTOR_CHECKS.items()],
                              'checks': {k: {'status': 'pass', 'command_exit': 0, 'diagnostics': 0} for k in u.recovery.DOCTOR_CHECKS},
                              'paths': {'status': 'known_source_baseline_diagnostic', 'finding': 'missing_/data/log', 'scope': 'console_logging_only', 'command_exit': 1},
                              'effective_config': {'lfs_start_server': False}, 'not_applicable': {'gc-lfs': 'LFS_START_SERVER=false'}}
                        for name, stage in [('source', 'a'), ('upgraded', 'b'), ('target', 'rollback'), ('post-write', 'rollback')]},
                upstream=[{'version': v, 'reviewed': True, 'sha256': 'a' * 64,
                           'url': f'https://codeberg.org/forgejo/forgejo/raw/branch/forgejo/release-notes-published/{v}.md'} for v in ('15.0.8', '15.0.9')])


class UpgradeProofTest(unittest.TestCase):
    def reject(self, value):
        with self.assertRaises(ValueError):
            u.validate_result(value)

    def test_complete_proof_and_reused_issue_number_with_distinct_title(self):
        u.validate_result(proof())

    def test_equal_versions_unresolved_image_and_b_first(self):
        for field, value in [('version', '15.0.9+gitea-1.22.0'), ('image_id', ''), ('init_image_ids', [runtime('b')['image_id']] * 3)]:
            with self.subTest(field=field):
                p = proof()
                p['runtime']['a'][field] = value
                self.reject(p)

    def test_queue_writer_restore_and_absence_order(self):
        for first, second in [('queue_flushed', 'b_started'), ('forgejo_stopped', 'b_started'),
                              ('source_cleaned', 'forgejo_started'), ('restore_complete', 'forgejo_started'), ('marker_absence', 'new_write')]:
            with self.subTest(first=first):
                p = proof()
                names = [r['phase'] for r in p['phase_records']]
                i, j = names.index(first), names.index(second)
                p['phase_records'][i], p['phase_records'][j] = p['phase_records'][j], p['phase_records'][i]
                self.reject(p)

    def test_missing_phase_never_infers_success(self):
        for phase in u.PHASES:
            with self.subTest(phase=phase):
                p = proof()
                p['phase_records'] = [r for r in p['phase_records'] if r['phase'] != phase]
                self.reject(p)

    def test_incomplete_checkpoint(self):
        p = proof()
        p['checkpoint']['backup_complete'] = False
        self.reject(p)
        p = proof()
        p['checkpoint']['components']['database.dump']['sha256'] = ''
        self.reject(p)

    def test_direct_downgrade_storage_reuse_or_identity_missing(self):
        for field in ('server_id', 'storage'):
            p = proof()
            p['runtime']['rollback'][field] = copy.deepcopy(p['runtime']['b'][field])
            self.reject(p)
        p = proof()
        p['runtime']['rollback']['storage']['forgejo']['pv_uid'] = ''
        self.reject(p)

    def test_b_marker_missing_or_absence_not_proven(self):
        for key, field, value in [('b_marker', 'commit', '1' * 40), ('b_marker', 'issue_title', ''),
                                  ('marker_absence', 'api', False), ('marker_absence', 'before_new_write', False),
                                  ('marker_absence', 'absent_commit', '4' * 40), ('post_write', 'filesystem', False)]:
            p = proof()
            p[key][field] = value
            self.reject(p)

    def test_pat_cookie_substitution_and_relogin(self):
        for field, value in [('pat_file_sha256', 'f' * 64), ('cookie_file_sha256', 'f' * 64), ('session_login_count', 2)]:
            p = proof()
            p['runtime']['b'][field] = value
            self.reject(p)

    def test_db_authority_and_manual_metadata_rewrite(self):
        p = proof()
        p['schema_metadata_rewritten'] = True
        self.reject(p)
        p = proof()
        p['runtime']['rollback']['database_authority']['version'][0]['version'] = 306
        self.reject(p)
        p = proof()
        del p['runtime']['a']['database_authority']['forgejo_migration']
        self.reject(p)
        p = proof()
        p['database_observation'] = 'migration observed'
        self.reject(p)

    def test_doctor_failure_or_paths_promoted(self):
        for field, value in [('checks', {}), ('paths', {'status': 'pass'}), ('selected', []), ('inventory', [])]:
            p = proof()
            p['doctor']['upgraded'][field] = value
            self.reject(p)

    def test_dirty_source_is_exploratory(self):
        p = proof()
        p['source_dirty'] = p['checkpoint']['source_dirty'] = True
        for r in p['runtime'].values(): r['source_dirty'] = True
        for h in p['regression']['baseline']['run_provenance']: h['dirty'] = True
        p['regression']['recovery']['source_dirty'] = True
        self.reject(p)
        u.validate_result(p, clean=False)

    def test_maintenance_policy_and_stable_pins(self):
        p = proof()
        p['runtime']['rollback']['autosync']['enabled'] = True
        self.reject(p)
        self.assertEqual(u.PINS['FORGEJO_IMAGE_TAG'], '15.0.9-rootless')

    def test_ci_artifact_allowlist_and_no_metadata_sql_rewrite(self):
        workflow = (ROOT / '.github/workflows/local-platform.yml').read_text()
        block = workflow.split('name: local-upgrade-results', 1)[1].split('retention-days:', 1)[0]
        paths = [line.strip() for line in block.splitlines() if line.strip().startswith('results/')]
        expected = ['checkpoint.json', 'doctor-source.json', 'doctor-upgraded.json', 'doctor-target.json', 'doctor-post-write.json',
                    'phases.jsonl', 'upstream.jsonl', 'runtime-a.json', 'runtime-b.json', 'runtime-rollback.json',
                    'b-marker.json', 'marker-absence.json', 'post-write.json', 'target-identity.json', 'result.json',
                    'regression-baseline.json', 'regression-recovery.json']
        self.assertEqual(paths, ['results/local/upgrade-*/' + name for name in expected])
        source = (ROOT / 'scripts/local-recover.sh').read_text()
        self.assertNotRegex(source, r'(?i)(?:UPDATE|DELETE FROM)\s+(?:forgejo_)?(?:version|migration)')
        self.assertIn('timeout -k 5s 150s', source)
        self.assertEqual(source.count('"$URL/user/login"'), 2)  # One GET/POST, only in session_login.


if __name__ == '__main__':
    unittest.main()
