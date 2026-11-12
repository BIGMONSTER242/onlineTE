"""Fixed synthetic inputs. Generation LP constructs D0 only, never x0."""
import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
import networkx as nx
import numpy as np
if __package__:
    from .oracle import solve_lp
else:
    from oracle import solve_lp

SEED_RULE = 'numpy SeedSequence([seed, stream, scenario_code, repeat]); streams: event=1, random=2; concentrated=0, dispersed=1'

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def case_hash(case):
    return canonical_hash({k:v for k,v in case.items() if k != 'hash'})

def rng_for(seed, stream, scenario, repeat=0):
    if scenario not in ('concentrated','dispersed'): raise ValueError('Unknown scenario')
    return np.random.default_rng(np.random.SeedSequence([int(seed),int(stream),0 if scenario=='concentrated' else 1,int(repeat)]))

def make_case(topology='synthetic6', seed=0, scale=True):
    if topology not in ('synthetic6','synthetic24'): raise ValueError('Unknown topology')
    n=6 if topology=='synthetic6' else 24
    undirected={tuple(sorted((i,(i+1)%n))) for i in range(n)}
    undirected.update({(0,3),(1,4),(2,5)} if n==6 else {tuple(sorted((i,(i+5)%n))) for i in range(n)})
    edges=sorted((a,b) for u,v in undirected for a,b in ((u,v),(v,u)))
    graph=nx.DiGraph(); graph.add_nodes_from(range(n)); graph.add_edges_from(edges,weight=1)
    ods=[[s,t] for s in range(n) for t in range(n) if s != t]
    paths=[list(itertools.islice(nx.shortest_simple_paths(graph,s,t,weight='weight'),4)) for s,t in ods]
    demands=np.random.default_rng(seed).uniform(.5,1.5,len(ods)).tolist()
    case=dict(topology=topology,seed=int(seed),nodes=list(range(n)),edges=[list(e) for e in edges],
              capacities=[10.]*len(edges),ods=ods,paths=paths,demands=demands,
              generation=dict(networkx=nx.__version__,numpy=np.__version__,seed_rule=SEED_RULE,
                              path_order='sorted node/edge insertion; NetworkX shortest_simple_paths; first 4',
                              scope='synthetic mechanism validation'))
    if scale:
        result=solve_lp(case)
        if not result['optimal']: raise RuntimeError('D0 construction LP not optimal: '+result['status'])
        factor=.8/result['objective']
        case['demands']=(np.asarray(demands)*factor).tolist()
        case['generation'].update(demand_scale=factor,unscaled_optimum=result['objective'],target_mlu=.8)
    case['hash']=case_hash(case)
    return case

def make_event(case, scenario):
    d1=copy.deepcopy(case)
    rng=rng_for(case['seed'],1,scenario)
    if scenario=='concentrated':
        sources=sorted(int(x) for x in rng.choice(case['nodes'],size=2,replace=False))
        indices=[k for k,(s,t) in enumerate(case['ods']) if s in sources]
    else:
        indices=sorted(int(x) for x in rng.choice(len(case['ods']),size=int(np.ceil(.05*len(case['ods']))),replace=False))
        sources=sorted({case['ods'][k][0] for k in indices})
    for k in indices: d1['demands'][k]*=2
    d1['event']=dict(scenario=scenario,changed_sources=sources,changed_od_indices=indices,d0_hash=case['hash'])
    d1['hash']=case_hash(d1)
    return d1,sources

def save_case(case,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(case,indent=2,allow_nan=False)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--topology',default='synthetic6');p.add_argument('--seed',type=int,default=0);p.add_argument('--output',required=True)
    a=p.parse_args();save_case(make_case(a.topology,a.seed),a.output)
