"""C1/C2 experiment driver. Never substitutes an LP solution for OnlineTE."""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ['run_id','event','seed','scenario','method','repeat','nominal_budget','actual_budget',
          'mandatory_count','active_set','d0_quality','f_star','mlu','gap','demand_error',
          'negative_flow','status','score_wall_ns','solve_wall_ns','total_wall_ns',
          'exit_code','log_path','solve_cpu_ns','no_reoptimization_needed','tolerance_negative_gap']


def json_default(value):
    if hasattr(value, 'tolist'): return value.tolist()
    if hasattr(value, 'item'): return value.item()
    if isinstance(value, Path): return str(value)
    raise TypeError(type(value).__name__)


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value, indent=2, default=json_default, allow_nan=False)+'\n')
    tmp.replace(path)


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def git(*args): return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()

def git_info():
    diff = subprocess.check_output(['git','diff','HEAD','--binary'],cwd=ROOT)
    untracked=git('ls-files','--others','--exclude-standard').splitlines()
    extras={p:digest(ROOT/p) for p in untracked if (ROOT/p).is_file()}
    return dict(sha=git('rev-parse','HEAD'),dirty=bool(git('status','--porcelain')),
                patch_sha256=hashlib.sha256(diff).hexdigest(),untracked_hashes=extras)


def manifest(config, command):
    info=git_info()
    versions={}
    for name in ['numpy','scipy','networkx','numba','grpcio','grpcio-tools','protobuf','ortools','gurobipy','matplotlib']:
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name]=None
    return dict(schema_version=1,git=info,git_sha=info['sha'],config=config,
                config_hash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),
                seeds=config['seeds'],scenarios=config['scenarios'],input_hashes={},
                expected_events=[dict(event=f'{seed}-{scenario}',seed=seed,scenario=scenario)
                                 for seed in config['seeds'] for scenario in config['scenarios']],
                command=command,python=sys.version,dependencies=versions,
                platform=platform.platform(),cpu=platform.processor(),cpu_count=os.cpu_count(),
                memory_bytes=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES'),
                resources=dict(max_workers=config['max_workers'],threads=config['threads'],
                               thread_environment={k:os.environ.get(k) for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS']}),
                time_units='nanoseconds',start_time_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                status='running',seed_derivation='See prepare_cases.py and selection.py; persisted input includes full paths and demands.',
                performance_eligible=not info['dirty'])


def append_row(directory,row):
    path=directory/'results.csv'; exists=path.exists()
    with path.open('a',newline='') as f:
        out=csv.DictWriter(f,FIELDS,extrasaction='ignore')
        if not exists: out.writeheader()
        out.writerow(row); f.flush(); os.fsync(f.fileno())


def read_rows(directory):
    p=directory/'results.csv'
    if not p.exists(): return []
    with p.open() as f: return list(csv.DictReader(f))


def result_key(row):
    return tuple(str(row.get(k,'')) for k in ['event','method','repeat','actual_budget'])


def load_config(path):
    # The shipped files are JSON, a strict YAML subset; allow user YAML overrides.
    text=Path(path).read_text()
    try: cfg=json.loads(text)
    except json.JSONDecodeError:
        import yaml
        cfg=yaml.safe_load(text)
    if cfg['threads'] != 1 or not 1 <= cfg['max_workers'] <= 4: raise ValueError('C1/C2 requires one numerical thread and at most four workers')
    if cfg['random_repeats'] != 5: raise ValueError('The first-round protocol requires five random repeats')
    if any(not 0 < r <= 1 for r in cfg['budgets']): raise ValueError('Invalid budget')
    return cfg


def run(config_path, run_dir=None, resume=False):
    from .prepare_cases import make_case, make_event
    from .oracle import solve_lp, evaluate, normalize_baseline, rescale_old_flows
    from .selection import select_active
    from .baseline import run_baseline
    if resume and not run_dir: raise ValueError('--resume requires --run-dir')
    cfg=load_config(config_path); current=manifest(cfg,sys.argv)
    if cfg['topology']=='synthetic24' and current['git']['dirty']:
        raise ValueError('Formal screening requires a clean committed checkout')
    directory=Path(run_dir).resolve() if run_dir else ROOT/'results'/'active_set'/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8])
    if directory.exists():
        if not resume: raise ValueError('Existing run directory requires --resume; it will not be overwritten')
        old=json.loads((directory/'manifest.json').read_text())
        matching=(old['git_sha']==current['git_sha'] and old['config_hash']==current['config_hash'] and old['git']==current['git'])
        matching &= all((directory/p).is_file() and digest(directory/p)==h for p,h in old['input_hashes'].items())
        if not matching:
            print('Resume mismatch: preserving old run; starting a new run ID.',flush=True)
            return run(config_path)
        current=old; current['status']='running'; current.setdefault('resume_commands',[]).append(sys.argv)
    directory.mkdir(parents=True,exist_ok=True)
    current['run_id']=directory.name
    # A process-level lock prevents simultaneous runs writing the same result tree.
    import fcntl
    lock=(directory/'.run.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    save(directory/'manifest.json',current)
    attempt=uuid.uuid4().hex[:12]
    logs=f'logs/{attempt}'
    existing=read_rows(directory)
    success={result_key(r) for r in existing if r['status']=='optimal' and r['exit_code']=='0'}
    # Failed attempts remain in attempts.csv; results.csv holds the current attempt only.
    if resume and existing:
        with (directory/'attempts.csv').open('a',newline='') as f:
            w=csv.DictWriter(f,FIELDS,extrasaction='ignore')
            if f.tell()==0: w.writeheader()
            w.writerows(existing)
        kept=[r for r in existing if result_key(r) in success]
        with (directory/'results.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,FIELDS);w.writeheader();w.writerows(kept)
    failures=0
    for seed in cfg['seeds']:
        base_path=directory/'inputs'/f'd0-{seed}.json'
        try:
            if base_path.exists(): d0=json.loads(base_path.read_text())
            else:
                d0=make_case(cfg['topology'],seed=seed);save(base_path,d0)
            current['input_hashes'][str(base_path.relative_to(directory))]=digest(base_path)
            save(directory/'manifest.json',current)
            ref=solve_lp(d0,time_limit=cfg['lp_timeout'])
            save(directory/logs/f'd0-oracle-{seed}.json',ref)
            if not ref['optimal']: raise RuntimeError('D0 scaling reference is not optimal')
            baseline_path=directory/'baseline'/str(seed)/'accepted.json'
            if baseline_path.exists(): accepted=json.loads(baseline_path.read_text())
            else:
                raw=run_baseline(d0,directory/'baseline'/str(seed)/attempt,timeout=cfg['baseline_timeout'],max_outer=cfg['max_outer'],mode='initialization',max_workers=cfg['max_workers'])
                save(directory/'baseline'/str(seed)/attempt/'adapter_result.json',raw)
                if raw.get('status') not in ('solved','iteration_limit') or raw.get('exit_code',1)!=0 or not raw.get('flows'): raise RuntimeError('Original baseline failed: '+str(raw.get('status')))
                accepted=normalize_baseline(d0,raw['flows'],ref['objective'])
                save(directory/'baseline'/str(seed)/attempt/'normalization.json',accepted)
                if accepted.get('status') != 'ok':
                    raise RuntimeError('baseline_quality_failed: '+str(accepted))
                save(baseline_path,accepted)
            x0=accepted['flows'];quality=evaluate(d0,x0,reference=ref['objective'])
            if quality['demand_error']>1e-6 or quality['negative_flow']>1e-6 or quality['gap']>0.001:
                raise RuntimeError('baseline_quality_failed')
            current['input_hashes'][str(baseline_path.relative_to(directory))]=digest(baseline_path)
            save(directory/'manifest.json',current)
        except Exception as exc:
            failures+=len(cfg['scenarios'])
            log=directory/logs/f'baseline-failure-{seed}.json'
            save(log,dict(error=str(exc),traceback=traceback.format_exc()))
            for scenario in cfg['scenarios']:
                append_row(directory,dict(run_id=directory.name,event=f'{seed}-{scenario}',seed=seed,scenario=scenario,
                                         method='baseline',status='baseline_quality_failed',exit_code=1,log_path=str(log.relative_to(directory))))
            continue
        for scenario in cfg['scenarios']:
            event=f'{seed}-{scenario}';event_start=time.perf_counter_ns()
            try:
                d1,changed=make_event(d0,scenario)
                event_path=directory/'inputs'/f'd1-{event}.json'
                if event_path.exists() and json.loads(event_path.read_text())!=json.loads(json.dumps(d1,default=json_default)):
                    raise ValueError('Event regeneration differs from persisted input')
                save(event_path,d1);current['input_hashes'][str(event_path.relative_to(directory))]=digest(event_path)
                save(directory/'manifest.json',current)
                oldflow=rescale_old_flows(d0,d1,x0)
                full=solve_lp(d1,time_limit=cfg['lp_timeout'])
                save(directory/logs/f'{event}-reference.json',full)
                if not full['optimal']:
                    append_row(directory,dict(run_id=directory.name,event=event,seed=seed,scenario=scenario,method='full_lp',
                        status=full['status'],exit_code=1,log_path=f'{logs}/{event}-reference.json'))
                    failures+=1;continue
                fstar=full['objective']; oldeval=evaluate(d1,oldflow,reference=fstar)
                noneed=oldeval['gap']<=.01 and oldeval['demand_error']<=1e-6 and oldeval['negative_flow']<=1e-6
                save(directory/logs/f'{event}-old-routing.json',dict(flows=oldflow,evaluation=oldeval,no_reoptimization_needed=noneed))
                plans=[('full_lp',-1,1.0),('changed_only',-1,len(changed)/len(d1['nodes']))]
                plans += [('impact_select',-1,b) for b in cfg['budgets']]
                plans += [('random_select',r,b) for r in range(cfg['random_repeats']) for b in cfg['budgets']]
                seen=set()
                for method,repeat,budget in plans:
                    score_start=time.perf_counter_ns()
                    sel=select_active(d1,changed,budget,method,repeat=repeat,xold=oldflow)
                    score_ns=time.perf_counter_ns()-score_start
                    active=sel['active_sources'];ratio=len(active)/len(d1['nodes'])
                    if method in ('impact_select','random_select'):
                        import math
                        sel['merged_nominal_budgets']=[b for b in cfg['budgets'] if max(len(changed),math.ceil(b*len(d1['nodes'])))==len(active)]
                    row=dict(run_id=directory.name,event=event,seed=seed,scenario=scenario,method=method,repeat=repeat,
                             nominal_budget=budget,actual_budget=ratio,mandatory_count=len(changed),active_set=json.dumps(active),
                             d0_quality=quality['gap'],f_star=fstar,no_reoptimization_needed=noneed)
                    key=result_key(row)
                    if key in seen: continue
                    seen.add(key)
                    if key in success: continue
                    start=time.perf_counter_ns();log_rel=f'{logs}/{event}-{method}-{repeat}-{len(active)}.json'
                    answer=full if method=='full_lp' else solve_lp(d1,active_sources=active,x0=x0,time_limit=cfg['lp_timeout'])
                    ev=evaluate(d1,answer['flows'],reference=fstar) if answer.get('flows') is not None else {}
                    valid=answer['optimal'] and ev.get('demand_error',1)<=1e-6 and ev.get('negative_flow',1)<=1e-6
                    if valid and abs(ev['mlu']-answer['objective'])>1e-6*max(1,abs(answer['objective'])): valid=False
                    if valid and ev['gap'] < -1e-6: valid=False
                    if valid and len(active)==len(d1['nodes']) and abs(answer['objective']-fstar)>1e-6*max(1,abs(fstar)):valid=False
                    row.update(mlu=ev.get('mlu'),gap=ev.get('gap'),demand_error=ev.get('demand_error'),negative_flow=ev.get('negative_flow'),
                               tolerance_negative_gap=bool(-1e-6<=ev.get('gap',0)<0),
                               status=answer['status'] if valid or not answer['optimal'] else 'validation_failed',
                               score_wall_ns=score_ns,solve_wall_ns=answer['wall_ns'],solve_cpu_ns=answer['cpu_ns'],
                               total_wall_ns=score_ns+time.perf_counter_ns()-start+(answer['wall_ns'] if method=='full_lp' else 0),exit_code=0 if valid else 1,log_path=log_rel)
                    save(directory/log_rel,dict(selection=sel,solution=answer,evaluation=ev,row=row))
                    append_row(directory,row)
                    if not valid: failures+=1
            except Exception as exc:
                failures+=1;log_rel=f'{logs}/{event}-failure.json'
                save(directory/log_rel,dict(error=str(exc),traceback=traceback.format_exc()))
                append_row(directory,dict(run_id=directory.name,event=event,seed=seed,scenario=scenario,method='event',
                    status='failed',exit_code=1,log_path=log_rel,total_wall_ns=time.perf_counter_ns()-event_start))
    current.update(status='failed' if failures else 'completed',failures=failures,
                   finish_time_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    save(directory/'manifest.json',current)
    print(f'RUN_DIR={directory}',flush=True)
    lock.close()
    return 1 if failures else 0


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',default=str(Path(__file__).parent/'configs/screening.yaml'))
    p.add_argument('--run-dir');p.add_argument('--resume',action='store_true');args=p.parse_args()
    try:return run(args.config,args.run_dir,args.resume)
    except Exception:
        traceback.print_exc();return 1

if __name__=='__main__':raise SystemExit(main())
