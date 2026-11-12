"""Independent path-flow evaluator and offline HiGHS oracle (never online policy)."""
from time import perf_counter_ns, process_time_ns
import numpy as np
from scipy import sparse
from scipy.optimize import linprog

FEAS_TOL = 1e-6
LP_TOL = 1e-7

def matrices(case):
    edges = {tuple(e): i for i, e in enumerate(case['edges'])}
    er, ec, kr, kc = [], [], [], []
    j = 0
    for k, paths in enumerate(case['paths']):
        for path in paths:
            kr.append(k); kc.append(j)
            for edge in zip(path, path[1:]):
                er.append(edges[edge]); ec.append(j)
            j += 1
    return (sparse.csr_matrix((np.ones(len(er)), (er, ec)), shape=(len(edges), j)),
            sparse.csr_matrix((np.ones(len(kr)), (kr, kc)), shape=(len(case['ods']), j)))

def evaluate(case, flows, reference=None):
    edge, od = matrices(case)
    x = np.asarray(flows, dtype=float)
    if x.shape != (edge.shape[1],) or not np.all(np.isfinite(x)):
        raise ValueError('Invalid flow shape or nonfinite flow')
    d = np.asarray(case['demands'])
    load = np.asarray(edge @ x).ravel()
    mlu = float(np.max(load / np.asarray(case['capacities'])))
    demand_error = float(np.max(np.abs(od @ x - d) / np.maximum(1, d)))
    negative = float(max(0, -np.min(x)))
    result = dict(mlu=mlu, demand_error=demand_error, negative_flow=negative,
                  capacity_overload=max(0., mlu-1), feasible=demand_error <= FEAS_TOL and negative <= FEAS_TOL,
                  loads=load.tolist())
    if reference is not None:
        if not np.isfinite(reference) or reference <= 0: raise ValueError('Invalid reference objective')
        gap = (mlu-reference)/reference
        result.update(gap=float(gap), negative_gap_within_tolerance=bool(-FEAS_TOL <= gap < 0))
        if gap < -FEAS_TOL: raise ValueError('Recomputed MLU beats reference beyond tolerance')
    return result

def solve_lp(case, active_sources=None, x0=None, time_limit=60):
    if time_limit <= 0: raise ValueError('time_limit must be positive')
    edge, od = matrices(case)
    n = edge.shape[1]
    bounds = [(0., None)] * (n+1)
    if active_sources is not None:
        active = set(active_sources)
        if not active <= set(case['nodes']): raise ValueError('Unknown active source')
        if x0 is None or len(x0) != n: raise ValueError('Restricted LP requires matching x0')
        if not np.all(np.isfinite(x0)) or np.min(x0) < -FEAS_TOL: raise ValueError('Invalid x0')
        j = 0
        for (s, _), paths in zip(case['ods'], case['paths']):
            if s not in active:
                for p in range(len(paths)): bounds[j+p] = (float(x0[j+p]), float(x0[j+p]))
            j += len(paths)
        # Any changed source omitted from A produces a demand mismatch; reject before solver.
        frozen = [k for k,(s,_) in enumerate(case['ods']) if s not in active]
        old_d = od @ np.asarray(x0)
        if any(abs(old_d[k]-case['demands'][k])/max(1,case['demands'][k]) > FEAS_TOL for k in frozen):
            raise ValueError('Active set omits a changed source')
    aub = sparse.hstack([edge, -np.asarray(case['capacities'])[:,None]], format='csr')
    aeq = sparse.hstack([od, sparse.csr_matrix((od.shape[0],1))], format='csr')
    objective = np.zeros(n+1); objective[-1] = 1
    wall, cpu = perf_counter_ns(), process_time_ns()
    res = linprog(objective, A_ub=aub, b_ub=np.zeros(edge.shape[0]), A_eq=aeq,
                  b_eq=case['demands'], bounds=bounds, method='highs',
                  options={'time_limit':float(time_limit), 'primal_feasibility_tolerance':LP_TOL,
                           'dual_feasibility_tolerance':LP_TOL})
    out = dict(status={0:'optimal',1:'limit',2:'infeasible',3:'unbounded',4:'solver_error'}.get(res.status,'unknown'),
               status_code=int(res.status), optimal=bool(res.success), message=str(res.message),
               wall_ns=perf_counter_ns()-wall, cpu_ns=process_time_ns()-cpu,
               flows=None, objective=None, evaluation=None, bound=None,
               tolerances={'primal_feasibility_tolerance':LP_TOL,'dual_feasibility_tolerance':LP_TOL},
               incumbent_available=res.x is not None,
               bound_note='SciPy linprog HiGHS does not expose a time-limit bound or incumbent when absent.')
    if res.x is not None:
        out.update(flows=res.x[:-1].tolist(),objective=float(res.x[-1]))
        out['evaluation'] = evaluate(case,out['flows'])
        err = abs(out['evaluation']['mlu']-out['objective'])/max(1.,abs(out['objective']))
        out['objective_error'] = err
        if res.success and (err > FEAS_TOL or not out['evaluation']['feasible']):
            raise ValueError('Optimal LP failed independent feasibility/objective check')
    return out

def rescale_old_flows(d0, d1, x0):
    if d0['ods'] != d1['ods'] or d0['paths'] != d1['paths']: raise ValueError('Input/path mismatch')
    output=[]; j=0
    for old,new,paths in zip(d0['demands'],d1['demands'],d0['paths']):
        if old <= 0: raise ValueError('Positive D0 demand required')
        output.extend((np.asarray(x0[j:j+len(paths)]) * (new/old)).tolist()); j+=len(paths)
    return output

def normalize_baseline(case, flows, reference):
    raw=evaluate(case,flows)
    if not raw['feasible']: return dict(status='baseline_quality_failed',raw_evaluation=raw,flows=None)
    raw=evaluate(case,flows,reference)
    out=[]; j=0
    for demand,paths in zip(case['demands'],case['paths']):
        part=np.maximum(0., np.asarray(flows[j:j+len(paths)])); total=float(part.sum()); j+=len(paths)
        if total <= 0: return dict(status='baseline_quality_failed',raw_evaluation=raw,flows=None)
        out.extend((part/total*demand).tolist())
    evaluated=evaluate(case,out,reference)
    return dict(status='ok' if evaluated['feasible'] and evaluated['gap'] <= .001 else 'baseline_quality_failed',
                flows=out,raw_evaluation=raw,evaluation=evaluated,
                correction_l1=float(np.sum(np.abs(np.asarray(out)-flows))),
                correction_max=float(np.max(np.abs(np.asarray(out)-flows))))
