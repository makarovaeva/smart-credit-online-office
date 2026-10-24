"""CLI orchestration tests: pure command construction, no costly training."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scoring_pipeline_entrypoint', ROOT / 'main.py')
scoring_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scoring_main)


class ScoringMainTests(unittest.TestCase):
    def test_dry_run_generate_invokes_both_stages_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'new_run'
            code = scoring_main.run([
                '--generate', '--count', '400', '--simulate-outcomes',
                '--out-dir', str(dest), '--dry-run',
            ])
            self.assertEqual(code, 0)
            self.assertFalse(dest.exists())

    def test_commands_reference_pre_decision_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = scoring_main.parse_args([
                '--generate', '--simulate-outcomes', '--out-dir', str(Path(tmp) / 'sample')
            ])
            cmds, profiles, applications, scored = scoring_main.build_commands(args)
            self.assertEqual(len(cmds), 2)
            self.assertEqual(profiles.name, 'profiles_compliance.json')
            self.assertEqual(applications.name, 'applications_generated.json')
            self.assertTrue(str(scored).endswith('scoring'))
            self.assertIn('--simulate-outcomes', cmds[1])

    def test_external_inputs_mode_never_regenerates(self):
        with tempfile.TemporaryDirectory() as tmp:
            profiles = Path(tmp) / 'profiles.json'
            apps = Path(tmp) / 'apps.json'
            profiles.write_text('[]')
            apps.write_text('[]')
            args = scoring_main.parse_args([
                '--profiles', str(profiles), '--applications', str(apps),
                '--simulate-outcomes', '--out-dir', str(Path(tmp) / 'result'),
            ])
            cmds, *_ = scoring_main.build_commands(args)
            self.assertEqual(len(cmds), 1)
            self.assertIn('calibrate_scoring.py', cmds[0][1])

    def test_prevent_nonempty_output_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'old'
            dest.mkdir()
            (dest / 'keep.txt').write_text('important')
            with self.assertRaises(SystemExit):
                scoring_main.run([
                    '--generate', '--simulate-outcomes', '--out-dir', str(dest),
                ])
            self.assertEqual((dest / 'keep.txt').read_text(), 'important')

    def test_generated_data_cannot_be_paired_with_real_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'labels.csv';f.write_text('application_id,default_12m\n')
            with self.assertRaises(SystemExit):
                scoring_main.parse_args(['--generate','--labels',str(f),'--out-dir',str(Path(tmp)/'run')])


if __name__ == '__main__':
    unittest.main()
