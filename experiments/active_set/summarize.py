"""Validate and summarize active-set experiments without hiding unsuccessful events."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path

REQUIRED = {'run_id','event','seed','scenario','method','repeat','nominal_budget','actual_budget',
 'mandatory_count','active_set','d0_quality','f_star','mlu','gap','demand_error','negative_flow',
 'status','score_wall_ns','solve_wall_ns','total_wall_ns','exit_code','log_path'}


def safe_file(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError(f'Unsafe relative path: {relative}')
    p = root / relative
    if any(q.is_symlink() for q in [p, *p.parents] if q != root.parent):
        raise ValueError(f'Symlink is not permitted: {relative}')
    if not p.resolve().is_relative_to(root.resolve()) or not p.is_file():
        raise ValueError(f'Missing or unsafe file: {relative}')
    return p


def number(row, key):
    try:
        n = float(row[key])
        return n if math.isfinite(n) else None
    except (KeyError, ValueError, TypeError):
        return None


def valid(row):
    return (row['status'] in {'optimal','success','passed'} and str(row['exit_code']) == '0'
            and all(number(row, k) is not None for k in ['gap','f_star','mlu','demand_error','negative_flow'])
            and number(row,'d0_quality') is not None and number(row,'d0_quality') <= .001
            and number(row,'f_star') > 0 and 0 <= number(row,'demand_error') <= 1e-6
            and 0 <= number(row,'negative_flow') <= 1e-6 and number(row,'gap') >= -1e-6)


def load_validate(run_dir):
    supplied = Path(run_dir).absolute()
    if any(p.is_symlink() for p in [supplied,*supplied.parents]):
        raise ValueError('Run directory must not be a symlink or traverse one')
    root = supplied.resolve()
    manifest = json.loads(safe_file(root, 'manifest.json').read_text())
    config = manifest.get('config', {})
    manifest.setdefault('git', {'sha': manifest.get('git_sha', ''), 'dirty': manifest.get('dirty', 'unknown')})
    manifest.setdefault('inputs', manifest.get('input_hashes', {}))
    manifest.setdefault('config_sha256', manifest.get('config_hash'))
    sha = manifest['git']['sha']
    if len(sha) != 40 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('manifest git.sha must be a complete hexadecimal SHA')
    if not manifest.get('config_sha256') or not manifest.get('inputs'):
        raise ValueError('manifest lacks config_sha256 or input hashes')
    actual_config_hash = hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    if actual_config_hash != manifest['config_sha256']:
        raise ValueError('Config hash mismatch')
    for rel, digest in manifest['inputs'].items():
        if hashlib.sha256(safe_file(root, rel).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Input hash mismatch: {rel}')
    with safe_file(root, 'results.csv').open(newline='') as f:
        reader = csv.DictReader(f)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'Missing CSV columns: {sorted(missing)}')
        rows = list(reader)
    if not rows:
        raise ValueError('results.csv has no records')
    for r in rows:
        if r.get('log_path'):
            safe_file(root, r['log_path'])
        for key in ['score_wall_ns','solve_wall_ns','total_wall_ns']:
            n = number(r,key)
            if n is not None and n < 0:
                raise ValueError(f'Negative {key}')
    return root, manifest, config, rows


def summarize(run_dir):
    root, manifest, config, rows = load_validate(run_dir)
    seeds = manifest.get('seeds', config.get('seeds', [0,1,2,3,4]))
    scenarios = manifest.get('scenarios', config.get('scenarios', ['concentrated','dispersed']))
    groups = defaultdict(list)
    for r in rows:
        groups[(int(r['seed']), r['scenario'])].append(r)
    expected = [(int(s), sc) for sc in scenarios for s in seeds]
    if manifest.get('expected_events'):
        expected = [(int(e['seed']),e['scenario']) for e in manifest['expected_events']]
    missing = [key for key in expected if key not in groups]
    statuses = Counter(r['status'] for r in rows)
    event_counts = {}
    gate_events = []
    lines = ['# Active-set C2 screening summary', '',
      f"Commit: {manifest['git']['sha']}",
      f"Dirty tree: {manifest['git'].get('dirty', 'unknown')}",
      f"Preset seeds: {seeds}; preset events: {len(expected)}.",
      f"Missing events (counted as unsuccessful): {len(missing)} {missing}",
      'All timings are nanoseconds. LP times are not distributed ADMM performance.', '',
      '## Recorded statuses', *[f'- {k}: {v}' for k,v in sorted(statuses.items())], '']
    random_summaries = []
    for sc in scenarios:
        counts = Counter(events_with_failures=0, timeout=0, baseline_quality_failed=0,
                         no_reoptimization_needed=0, missing=0, valid_events=0)
        for seed in seeds:
            event = groups.get((int(seed),sc), [])
            if not event:
                counts['missing'] += 1
                continue
            if any(r['status'] not in {'optimal','success','passed','no_reoptimization_needed'} for r in event):
                counts['events_with_failures'] += 1
            if any(r['status'] == 'baseline_quality_failed' for r in event):
                counts['baseline_quality_failed'] += 1
            if any('timeout' in r['status'].lower() or r['status'].lower() == 'time_limit' for r in event):
                counts['timeout'] += 1
            no_reopt = any(r['status'] == 'no_reoptimization_needed' or
                           r.get('no_reoptimization_needed','').lower() == 'true' for r in event)
            if no_reopt:
                counts['no_reoptimization_needed'] += 1
            good = [r for r in event if valid(r)]
            full = [r for r in good if r['method'] == 'full_lp']
            if full and not any(r['status'] == 'baseline_quality_failed' for r in event):
                counts['valid_events'] += 1
            for threshold in [.005,.01,.02]:
                if not no_reopt and full and any(r['method'] == 'impact_select' and
                    number(r,'gap') <= threshold and number(r,'actual_budget') is not None and
                    number(r,'actual_budget') <= .5 for r in good):
                    counts[f'impact_success_at_{threshold}'] += 1
                    if threshold == .01:
                        gate_events.append((seed,sc))
            if full and not any(r['method'] == 'event' and r['exit_code'] != '0' for r in event):
                n = int(str(config.get('topology','synthetic24')).replace('synthetic',''))
                mandatory = int(full[0]['mandatory_count'])
                expected_budgets = {max(mandatory,math.ceil(float(b)*n))/n for b in config.get('budgets',[])}
                expected_keys = {('full_lp', '-1', 1.0), ('changed_only','-1',mandatory/n)}
                expected_keys.update(('impact_select','-1',b) for b in expected_budgets)
                expected_keys.update(('random_select',str(r),b) for b in expected_budgets
                    for r in range(int(config.get('random_repeats',5))))
                present = {(r['method'],str(r['repeat']),number(r,'actual_budget')) for r in event}
                if expected_keys - present:
                    counts['events_with_missing_methods'] += 1
            by_budget = defaultdict(list)
            for r in event:
                if r['method'] == 'random_select':
                    by_budget[number(r,'actual_budget')].append(r)
            for budget, rr in by_budget.items():
                gaps = [number(r,'gap') for r in rr if valid(r)]
                random_summaries.append(dict(seed=seed,scenario=sc,actual_budget=budget,
                    n=len(gaps),failed=len(rr)-len(gaps),
                    mean=sum(gaps)/len(gaps) if gaps else None,
                    minimum=min(gaps) if gaps else None,maximum=max(gaps) if gaps else None))
                repeats = {str(r['repeat']) for r in rr}
                if len(repeats) != int(config.get('random_repeats',5)) or len(rr) != len(repeats):
                    counts['incomplete_random_budget_groups'] += 1
        event_counts[sc] = dict(counts)
        lines += [f'## {sc}', f'Preset denominator: {len(seeds)} events.',
          *[f"- { {'events_with_failures': 'failures', 'timeout': 'timeouts'}.get(k,k)}: {v}"
            for k,v in sorted(counts.items())], '']
    main = seeds == [0,1,2,3,4] and config.get('topology') in ('synthetic24',24)
    concentrated = [x for x in gate_events if x[1] in ('concentrated','concentrated_change')]
    incomplete = manifest.get('status') == 'running' or bool(missing) or any(
        v.get('incomplete_random_budget_groups',0) or v.get('events_with_missing_methods',0)
        for v in event_counts.values())
    gate = main and len(concentrated) >= 3 and not incomplete
    lines += ['## C3 engineering gate',
      f'Eligible main configuration: {main}. Gate passed: {gate}.',
      'At least 3 of the 5 preset concentrated-change events must be valid, need reoptimization, '
      'and reach gap <= 1% with impact_select using <= 50% actual entries.',
      'This is an engineering decision, not statistical significance or evidence of ADMM speedup.',
      'Random repetitions are aggregated within an event, never counted as independent seeds.', '']
    incomplete = manifest.get('status') == 'running' or bool(missing) or any(v.get('incomplete_random_budget_groups',0) or v.get('events_with_missing_methods',0) for v in event_counts.values())
    data = dict(status_counts=dict(statuses),event_counts=event_counts,missing_events=missing,
                random_event_summaries=random_summaries,c3_gate=gate,complete=not incomplete)
    (root/'summary.json').write_text(json.dumps(data,indent=2)+'\n')
    _plot(root, rows, random_summaries, scenarios, event_counts)
    output = root/'summary.md'
    output.write_text('\n'.join(lines)+'\n')
    if incomplete:
        raise ValueError('Incomplete experiment: summary written with missing/incomplete items; see summary.md')
    return output


def _plot(root, rows, random_summaries, scenarios, event_counts=None):
    # Limit cache environment changes to rendering; never rely on a writable home.
    cache = Path(root)/'.cache'
    destinations = {'MPLCONFIGDIR': cache/'matplotlib', 'XDG_CACHE_HOME': cache/'xdg'}
    for directory in destinations.values():
        if any(p.is_symlink() for p in [directory, *directory.parents]):
            raise ValueError('Plot cache must not traverse a symlink')
        directory.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in destinations}
    try:
        os.environ.update({key: str(path) for key,path in destinations.items()})
        _render_plots(root, rows, random_summaries, scenarios, event_counts)
    finally:
        for key,value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _render_plots(root, rows, random_summaries, scenarios, event_counts=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for scenario in scenarios:
        fig, ax = plt.subplots(figsize=(8,5))
        for method in ['impact_select','changed_only']:
            rr = [r for r in rows if r['scenario']==scenario and r['method']==method and valid(r)]
            ax.scatter([number(r,'actual_budget') for r in rr], [100*number(r,'gap') for r in rr],label=method,alpha=.7)
            for r in rr:
                ax.annotate(str(r['seed']),(number(r,'actual_budget'),100*number(r,'gap')),fontsize=6)
        for r in random_summaries:
            if r['scenario'] == scenario and r['mean'] is not None:
                ax.errorbar(r['actual_budget'],100*r['mean'],
                  yerr=[[100*(r['mean']-r['minimum'])],[100*(r['maximum']-r['mean'])]],
                  fmt='x',color='gray',alpha=.7)
                ax.annotate(str(r['seed']),(r['actual_budget'],100*r['mean']),fontsize=6)
        ax.plot([],[], 'x',color='gray',label='random: event mean and range')
        ax.axhline(1,color='black',linestyle='--',label='1% target')
        counts = (event_counts or {}).get(scenario,{})
        annotation = (f"failures: {counts.get('events_with_failures',0)}; "
                      f"timeouts: {counts.get('timeout',0)}; missing: {counts.get('missing',0)}\n"
                      f"baseline_quality_failed: {counts.get('baseline_quality_failed',0)}; "
                      f"no_reoptimization_needed: {counts.get('no_reoptimization_needed',0)}")
        ax.set(xlabel='Actual active-source fraction',ylabel='Gap (%)',title=scenario+'\n'+annotation)
        ax.legend(); fig.tight_layout()
        safe_name = ''.join(c for c in scenario if c.isalnum() or c in '_-')
        fig.savefig(root/f'gap_{safe_name}.png',dpi=150); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',required=True)
    args=parser.parse_args()
    try:
        print(summarize(args.run_dir))
    except (ValueError, KeyError, OSError, ImportError) as exc:
        parser.exit(1,f'Summary failed: {exc}\n')

if __name__ == '__main__':
    main()
