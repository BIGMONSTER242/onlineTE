"""Math-only diagnostic: LP-generated x0 is NOT an OnlineTE baseline."""
import unittest
import numpy as np
from experiments.active_set.prepare_cases import make_case, make_event, case_hash
from experiments.active_set.oracle import solve_lp,evaluate,rescale_old_flows,normalize_baseline
from experiments.active_set.selection import select_active

class MathChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d0=make_case();cls.initial=solve_lp(cls.d0);cls.x0=cls.initial['flows']
        cls.d1,cls.changed=make_event(cls.d0,'concentrated');cls.full=solve_lp(cls.d1)
    def test_full_equivalence_and_independent_evaluation(self):
        restricted=solve_lp(self.d1,self.d1['nodes'],self.x0)
        self.assertAlmostEqual(restricted['objective'],self.full['objective'],places=6)
        self.assertTrue(restricted['evaluation']['feasible'])
        self.assertLessEqual(restricted['objective_error'],1e-6)
        self.assertAlmostEqual(self.initial['objective'],.8,places=6)
    def test_changed_required(self):
        with self.assertRaises(ValueError):solve_lp(self.d1,[],self.x0)
    def test_frozen_and_feasibility(self):
        result=solve_lp(self.d1,self.changed,self.x0); self.assertTrue(result['optimal'])
        self.assertTrue(result['evaluation']['feasible']);j=0
        for (s,_),paths in zip(self.d1['ods'],self.d1['paths']):
            if s not in self.changed:np.testing.assert_allclose(result['flows'][j:j+len(paths)],self.x0[j:j+len(paths)],rtol=0,atol=1e-10)
            j+=len(paths)
    def test_new_demand_loads_and_nested_budget(self):
        old=rescale_old_flows(self.d0,self.d1,self.x0)
        self.assertTrue(evaluate(self.d1,old)['feasible'])
        self.assertGreater(max(np.abs(np.array(evaluate(self.d1,old)['loads'])-evaluate(self.d0,self.x0)['loads'])),1e-6)
        for method in ('impact_select','random_select'):
            for repeat in range(5):
                prev=set();last=float('inf')
                for ratio in (.1,.25,.5,1):
                    selected=select_active(self.d1,self.changed,ratio,method,repeat,old)
                    active=set(selected['active_sources'])
                    self.assertTrue(prev<=active);self.assertTrue(set(self.changed)<=active)
                    self.assertEqual(len(active),max(len(self.changed),int(np.ceil(ratio*6))))
                    result=solve_lp(self.d1,active,self.x0)
                    self.assertLessEqual(result['objective'],last+1e-6)
                    prev=active;last=result['objective']
    def test_determinism_and_dispersed(self):
        self.assertEqual(self.d0['hash'],case_hash(make_case()))
        a,changed=make_event(self.d0,'dispersed');b,_=make_event(self.d0,'dispersed')
        self.assertEqual(a,b);self.assertEqual(len(a['event']['changed_od_indices']),2)
        self.assertEqual(changed,sorted({a['ods'][k][0] for k in a['event']['changed_od_indices']}))
    def test_normalization_and_rejection(self):
        r=normalize_baseline(self.d0,self.x0,.8);self.assertEqual(r['status'],'ok')
        bad=list(self.x0);bad[0]=-1
        self.assertEqual(normalize_baseline(self.d0,bad,.8)['status'],'baseline_quality_failed')
    def test_limit_and_invalid_inputs(self):
        with self.assertRaises(ValueError):solve_lp(self.d0,time_limit=0)
        # Actual time-limit request: status and absence/presence of incumbent remain visible.
        r=solve_lp(self.d0,time_limit=1e-12)
        self.assertIn(r['status'],('limit','optimal'))
        self.assertIn('message',r);self.assertIn('incumbent_available',r)
        if r['status']=='limit':self.assertFalse(r['optimal'])

if __name__=='__main__':unittest.main()
