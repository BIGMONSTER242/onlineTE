"""Deterministic pre-solve source selection; no D1 oracle information is used."""
import math
import numpy as np
try:
    from .oracle import matrices
    from .prepare_cases import rng_for
except ImportError:
    from oracle import matrices
    from prepare_cases import rng_for

def impact_scores(case,xold):
    edge,_=matrices(case); x=np.asarray(xold); capacities=np.asarray(case['capacities'])
    utilization=np.asarray(edge@x).ravel()/capacities
    h=sorted(range(len(capacities)),key=lambda e:(-utilization[e],e))[:math.ceil(.1*len(capacities))]
    scores={int(s):0. for s in case['nodes']};j=0
    for (s,t),paths in zip(case['ods'],case['paths']):
        scores[s]+=float(np.sum(np.asarray(edge[h,j:j+len(paths)]@x[j:j+len(paths)]).ravel()/capacities[h]));j+=len(paths)
    return dict(scores=scores,hot_edges=h,utilization=utilization.tolist(),ranking=sorted(scores,key=lambda s:(-scores[s],s)))

def select_active(case,changed_sources,budget_ratio,method,repeat=0,xold=None):
    changed=set(changed_sources); nodes=set(case['nodes'])
    if not changed <= nodes or not 0 < budget_ratio <= 1: raise ValueError('Invalid source/budget')
    b=max(len(changed),math.ceil(budget_ratio*len(nodes)))
    scores=None
    if method=='full_lp': b=len(nodes); extras=sorted(nodes-changed)
    elif method=='changed_only': b=len(changed);extras=[]
    elif method=='impact_select':
        if xold is None: raise ValueError('impact_select requires xold(D1)')
        scores=impact_scores(case,xold);extras=[s for s in scores['ranking'] if s not in changed]
    elif method=='random_select':
        scenario=case['event']['scenario']
        extras=[int(s) for s in rng_for(case['seed'],2,scenario,repeat).permutation(sorted(nodes-changed))]
    else: raise ValueError('Unknown method')
    active=sorted(changed|set(extras[:b-len(changed)]))
    return dict(active_sources=active,budget=b,nominal_ratio=float(budget_ratio),actual_ratio=b/len(nodes),
                mandatory_count=len(changed),repeat=int(repeat),scores=scores,
                reasons={s:('changed' if s in changed else method) for s in active})
