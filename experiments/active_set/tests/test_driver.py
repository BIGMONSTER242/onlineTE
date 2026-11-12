"""Run-state tests use mocks only, not research measurements."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from experiments.active_set import run
from experiments.active_set.prepare_cases import make_case

class DriverTests(unittest.TestCase):
    def test_failure_is_persisted_and_resume_retries(self):
        config=Path(run.__file__).parent/'configs/smoke.yaml'
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'run'
            with patch('experiments.active_set.baseline.run_baseline',return_value={'flows':None,'status':'dependency_missing'}) as mock:
                self.assertEqual(run.run(config,directory),1)
                self.assertEqual(mock.call_count,1)
                rows=run.read_rows(directory)
                self.assertEqual(len(rows),2)
                self.assertTrue(all(r['status']=='baseline_quality_failed' for r in rows))
                self.assertEqual(run.run(config,directory,resume=True),1)
                self.assertEqual(mock.call_count,2)
                self.assertTrue((directory/'attempts.csv').exists())
                self.assertEqual(len(run.read_rows(directory)),2)
    def test_existing_run_not_overwritten(self):
        config=Path(run.__file__).parent/'configs/smoke.yaml'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):run.run(config,tmp)
    def test_config_rejects_unfair_threads(self):
        config=json.loads((Path(run.__file__).parent/'configs/smoke.yaml').read_text());config['threads']=2
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'config.yaml';p.write_text(json.dumps(config))
            with self.assertRaises(ValueError):run.load_config(p)

if __name__=='__main__': unittest.main()
