"""Summary fixtures are diagnostics, not reported experiment measurements."""
import csv
import hashlib
import json
import os
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from experiments.active_set.summarize import REQUIRED, load_validate, summarize, safe_file
from experiments.active_set.pack import pack

class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.plot_patch=patch('experiments.active_set.summarize._plot');self.plot_patch.start()
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/'run'; self.root.mkdir()
        (self.root/'case.json').write_text('{}')
        self.manifest={'config':{'topology':'synthetic6','seeds':[0],'scenarios':['concentrated']},
            'git':{'sha':'a'*40,'dirty':False},'config_sha256':'b'*64,
            'inputs':{'case.json':hashlib.sha256(b'{}').hexdigest()}}
        self.save_manifest()
        self.row={x:'' for x in REQUIRED}
        self.row.update(run_id='run',event='0-concentrated',seed=0,scenario='concentrated',method='baseline',
            status='baseline_quality_failed',exit_code=1)
        self.save_rows([self.row])
    def tearDown(self):
        self.tmp.cleanup();self.plot_patch.stop()
    def save_manifest(self):
        self.manifest['config_sha256']=hashlib.sha256(json.dumps(self.manifest['config'],sort_keys=True).encode()).hexdigest()
        (self.root/'manifest.json').write_text(json.dumps(self.manifest))
    def save_rows(self,rows):
        with (self.root/'results.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=sorted(REQUIRED));w.writeheader();w.writerows(rows)
    def test_failures_are_retained_and_packable(self):
        summarize(self.root)
        summary=json.loads((self.root/'summary.json').read_text())
        self.assertEqual(summary['event_counts']['concentrated']['baseline_quality_failed'],1)
        self.assertFalse(summary['c3_gate'])
        self.assertTrue(pack(self.root).is_file())
    def test_hash_mismatch(self):
        (self.root/'case.json').write_text('altered')
        with self.assertRaises(ValueError): load_validate(self.root)
    def test_missing_event_reports_then_fails(self):
        self.manifest['config']['seeds']=[0,1];self.save_manifest()
        with self.assertRaises(ValueError): summarize(self.root)
        self.assertEqual(len(json.loads((self.root/'summary.json').read_text())['missing_events']),1)
    def good_rows(self,seed,gap=.005):
        rows=[]
        plans=[('full_lp',-1,1),('changed_only',-1,2/24)]
        plans += [('impact_select',-1,b) for b in [.5,1]]
        plans += [('random_select',r,b) for r in range(5) for b in [.5,1]]
        for method,repeat,budget in plans:
            row=dict(self.row)
            row.update(seed=seed,event=f'{seed}-concentrated',method=method,repeat=repeat,
                actual_budget=budget,mandatory_count=2,d0_quality=.0001,f_star=.8,mlu=.8*(1+gap),
                gap=(gap+repeat*.001 if method=='random_select' else gap),
                demand_error=0,negative_flow=0,status='optimal',exit_code=0)
            rows.append(row)
        return rows
    def test_config_hash_mismatch(self):
        self.manifest['config_sha256']='0'*64
        (self.root/'manifest.json').write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError): load_validate(self.root)
    def test_random_aggregates_within_event_and_gate(self):
        self.manifest['config'].update(topology='synthetic24',seeds=[0,1,2,3,4],budgets=[.5,1],random_repeats=5)
        self.save_manifest()
        rows=[]
        for seed in range(5): rows += self.good_rows(seed,.005 if seed<3 else .02)
        self.save_rows(rows);summarize(self.root)
        data=json.loads((self.root/'summary.json').read_text())
        self.assertTrue(data['c3_gate'])
        self.assertEqual(data['event_counts']['concentrated']['impact_success_at_0.01'],3)
        self.assertEqual(len(data['random_event_summaries']),10)
        self.assertAlmostEqual(data['random_event_summaries'][0]['mean'],.007)
        self.assertEqual(data['random_event_summaries'][0]['n'],5)
        # Two successful seeds cannot pass the three-of-five gate.
        self.save_rows([r for r in rows if int(r['seed'])!=2]+[dict(self.row,seed=2,event='2-concentrated')])
        summarize(self.root)
        self.assertFalse(json.loads((self.root/'summary.json').read_text())['c3_gate'])
    def test_failed_random_repeat_not_silently_dropped(self):
        self.manifest['config'].update(topology='synthetic24',budgets=[.5,1],random_repeats=5)
        self.save_manifest();rows=self.good_rows(0)
        rows[-1].update(status='timeout',exit_code=1,gap='')
        self.save_rows(rows);summarize(self.root)
        data=json.loads((self.root/'summary.json').read_text())
        self.assertEqual(data['event_counts']['concentrated']['timeout'],1)
        self.assertEqual(data['random_event_summaries'][-1]['failed'],1)
        self.assertTrue(data['complete'])
    def test_missing_methods_fail(self):
        self.manifest['config'].update(topology='synthetic24',budgets=[.5,1],random_repeats=5)
        self.save_manifest();self.save_rows(self.good_rows(0)[:-1])
        with self.assertRaises(ValueError): summarize(self.root)
    def test_zero_outcome_categories_are_explicit(self):
        self.manifest['config'].update(topology='synthetic24',budgets=[.5,1],random_repeats=5)
        self.save_manifest();self.save_rows(self.good_rows(0));summarize(self.root)
        text=(self.root/'summary.md').read_text()
        for name in ['failures','timeouts','baseline_quality_failed','no_reoptimization_needed']:
            self.assertIn(f'- {name}: 0',text)
    def test_plot_cache_environment_scoped_and_not_packed(self):
        from experiments.active_set.summarize import _plot as mocked_plot
        # Exercise the actual wrapper while mocking rendering for a fast environment test.
        self.plot_patch.stop()
        try:
            from experiments.active_set.summarize import _plot
            before={key:os.environ.get(key) for key in ['MPLCONFIGDIR','XDG_CACHE_HOME']}
            def check(*args):
                for key in before:
                    path=Path(os.environ[key])
                    self.assertTrue(path.is_dir())
                    self.assertTrue(path.is_relative_to(self.root/'.cache'))
                (self.root/'.cache'/'private-cache.txt').write_text('not a deliverable')
            with patch('experiments.active_set.summarize._render_plots',side_effect=check):
                _plot(self.root,[],[],[])
            self.assertEqual(before,{key:os.environ.get(key) for key in before})
        finally:
            self.plot_patch.start()
        archive=pack(self.root)
        with tarfile.open(archive) as tf:
            self.assertFalse(any('.cache' in Path(name).parts for name in tf.getnames()))
    def test_symlink_and_traversal_rejected(self):
        (self.root/'link').symlink_to(self.root/'case.json')
        with self.assertRaises(ValueError): safe_file(self.root,'link')
        with self.assertRaises(ValueError): safe_file(self.root,'../outside')

if __name__=='__main__': unittest.main()
