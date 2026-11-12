# Active-source experiment: C1/C2 only

This is **synthetic mechanism validation**, not a WAN performance claim. C2 asks
whether a restricted set of source ingress nodes can approach the full path-flow
LP optimum. LP timing is not distributed ADMM timing. C3 sparse updates and C4
priority scheduling are deliberately not implemented. No speedup is claimed.

## Baseline and units

The reference is USC-NSL/OnlineTE `sigcomm-ae`, commit
`a80b2df08adb69a5e99892134a5dd9445a48056a`. The actual local architecture is
single-coordinator nested ADMM with multiprocessing/local gRPC, not a validated
hierarchical WAN deployment. A worker is an equal commodity block; C2 source
selection is an LP variable restriction, **not** changing these worker blocks.
All OD commodities are ordered `(source, destination)`. Complete ordered edges,
capacities, paths, demands and mappings are persisted in `inputs/*.json`.

The console `Obj. Gap` is a residual/bound proxy, never our evaluation metric.
The independent evaluator rebuilds edge loads from actual path flows. Demand
error and negative-flow amplitude must each be at most 1e-6. The reported gap is
`(recomputed_MLU - full_LP_optimum) / full_LP_optimum`. Capacity pressure above
MLU 1 is not infeasibility. Negative numerical gaps are retained and flagged;
a gap below -1e-6 is an error. HiGHS primal/dual tolerances are 1e-7 and each LP
has a 60-second limit. A timeout is never accepted as an optimal reference.
The API preserves an incumbent when available and explicitly reports when
SciPy exposes neither an incumbent nor a bound.

D0 is scaled by an offline construction LP to optimum MLU 0.8. The common x0
must come from actual OnlineTE worker path splits. The adapter preserves raw
outputs, checks feasibility, clips only tiny negative values, normalizes the
nonnegative splits, rebuilds flows using D0 demands, records corrections and
requires gap <= 0.1%. It never replaces a failed baseline with an LP solution.
Diagnostic LP initial states occur only in explicitly labeled unit tests.
Original/default-stop regression and tightened initialization are distinct;
see `environment/README.md` and baseline records for exact deviations.

Wall and CPU timings are integer nanoseconds from perf_counter_ns and
process_time_ns. Baseline workers report CPU separately, summed in adapter
output. Existing upstream runtime_ns logs have a known divide-by-1000 behavior
and must not be interpreted as our new nanosecond timers. JIT/startup is not
silently removed from end-to-end baseline wall time.

## Reproduce

Use Python 3.12 on Ubuntu and a clean checkout of the delivered full Git SHA.
Do not replace an existing `~/OnlineTE` checkout. In the new experiment checkout:

```bash
bash experiments/active_set/run.sh doctor
bash experiments/active_set/run.sh setup
bash experiments/active_set/run.sh smoke
bash experiments/active_set/run.sh screening
```

Run the next command only after the previous command succeeds. `doctor` is
read-only: setup-repairable missing packages/generated protos are warnings;
wrong paths/mounts, unsupported Python or unwritable outputs are hard failures.
`setup` creates `.venv`, installs the tested exact lock and compiles protocols;
it does not upgrade system pip. Gurobi is an upstream import dependency, but
this baseline uses OR-Tools PDLP and C2 uses SciPy HiGHS, not a Gurobi license.
Smoke runs mathematical/operational tests then real OnlineTE on synthetic6
seed 0 and both C2 event scenarios. A failed/missing baseline makes the overall
smoke exit nonzero even when mathematical checks passed. Tests use mocks only
where labeled for failure/recovery and never publish those values as research.

The screening config is `configs/screening.yaml` (JSON-valid YAML). It fixes
synthetic24, seeds 0..4, two event scenarios, 4 paths per OD, capacities 10,
budgets 10/25/50/100% and five random permutations per event. Each budget uses a
prefix of one permutation. All changed sources are mandatory; actual budget
can exceed the nominal budget, particularly for dispersed changes. Equivalent
actual budgets are deduplicated, with all nominal values in selection logs.
Only independent synthetic6 smoke is run during engineering; the owner runs
formal screening on their server. Numerical libraries use one thread and
OnlineTE uses the greatest worker count <= configured maximum 4 dividing K.
Formal synthetic24 screening rejects a dirty checkout.

Every event branches from the same D0/x0. Old splits are rescaled by D1 demand
before recomputing loads and impact scores. D1 oracle results do not enter
selection, candidate expansion or stopping. Impact selects by the top 10% of
old-routing D1 utilized directed edges; ties use edge/source IDs. Nonactive
source path flows are fixed to x0, and all changed sources remain active.

The driver prints `RUN_DIR=...`. Then:

```bash
bash experiments/active_set/run.sh summarize --run-dir <RUN_DIR>
bash experiments/active_set/run.sh pack --run-dir <RUN_DIR>
```

Return the printed `.tar.gz` result package, not a directory containing your
licenses or credentials. Packing is whitelist-based with path and symlink
checks. Results, environments, caches and licenses are ignored by Git.

To resume the same interrupted run:

```bash
bash experiments/active_set/run.sh screening --resume --run-dir <RUN_DIR>
```

Successful rows are reused only when commit, dirty patch/untracked source
hashes, configuration and persisted input hashes match. A mismatch preserves
the old run and starts a new ID. Failed items are retried explicitly; previous
rows are saved in attempts.csv and each attempt has distinct logs. Interrupted
runs have status running and must not be mistaken for complete results.
A process lock prevents simultaneous writers to one run. Do not execute formal
measurements concurrently with another experiment.

`manifest.json` records SHA, dirty state/patch hash, command, Python/dependencies,
CPU/memory/resources, seed derivation, hashes, timing units and expected events.
`results.csv` contains per-case quality/status/budget/timing/log records;
`summary.md` and figures retain missing, failed, timed-out and no-reoptimization
cases. Random repeats are aggregated **within** events, not treated as extra
independent seeds. Missing/inconsistent input or failed summary/pack is nonzero.

## Next-stage gate

Only after receiving a complete server package do we check the predeclared C3
gate: at least three of the five concentrated-change seeds must be valid and
need reoptimization; for at least three, impact selection must reach gap <=1%
at actual budget <=50%, with all feasibility checks. Report 0.5% and 2% as well.
This is an engineering investment gate, not statistical or algorithmic novelty.
If arbitrary small sets work, this does not establish impact's superiority to
random. If the gate fails, preserve failures and propose a bounded next step;
do not silently tune away negative results.

C3 would first require one source per worker, full-update equivalence, truly
skipping PGD while returning cached contributions, latest sharing bias,
consistent momentum restart, all-worker aggregation weights, monotonically
increasing update IDs and full refresh every five inner updates. C4 requires
selection/frequency to change, not merely parallel-worker order, with identical
budget and maximum staleness five. All forced work must be counted. Only
skipping computation while retaining RPC cannot prove lower communication.

```bash
bash experiments/active_set/run.sh admm-pilot
# exits 2 with NOT IMPLEMENTED; never runs LP in its place
```
