# Execution log

## 2026-11-12: scope and source

- Scope: C1/C2 implementation, independent synthetic6 smoke, delivery for owner-run server screening. C3/C4 remain intentionally unimplemented.
- Actual upstream baseline is `a80b2df08adb69a5e99892134a5dd9445a48056a` on `sigcomm-ae`, matching the brief. No pre-existing user checkout was modified. The initially supplied account page did not identify a repository; owner subsequently authorized creating a new repository. Publication is tracked separately and never inferred from a local commit.
- Reviewed all required source entries and upstream test/evaluation/FAQ instructions; detailed audit and original/default regression evidence are in `environment/SOURCE_AUDIT.md`.
- Source compatibility and baseline/environment adapter are separated from C2 in Git history. Original optimization defaults are not changed. Initialization-only residual-threshold tightening and iteration cap are explicit in every adapter record.

## Implementation

- Fixed synthetic6/24 inputs, path table persistence, event RNG streams, independent flow evaluator and HiGHS full/restricted oracle.
- Source-based mandatory/impact/random selection, nested actual budgets and five random permutations. Equivalent actual budgets retain all nominal ratios in logs.
- Original path-split export, no LP substitution, raw quality rejection, bounded initialization and common corrected x0.
- Stable doctor/setup/smoke/screening/summarize/pack/admm-pilot commands. Setup is isolated; doctor is read-only.
- Incremental CSV/JSON, input/config/source hashes, checked resume with per-attempt logs and failure history, clean-tree formal screening requirement.
- Validated summary with failure/missing denominators, event-level random aggregation, predeclared C3 gate, plots and whitelist archive.

## Actual engineering verification

Only the three states requested in the brief are used here:

1. **实际执行通过**: full restricted LP equals full LP on synthetic6.
2. **实际执行通过**: omitting a changed source is rejected.
3. **实际执行通过**: nonactive source path flows stay unchanged.
4. **实际执行通过**: new-demand conservation and nonnegative flows.
5. **实际执行通过**: independently recomputed MLU equals LP objective.
6. **实际执行通过**: nested active-set expansion does not worsen objective within tolerance.
7. **实际执行通过**: old split ratios under D1 produce updated edge loads.
8. **实际执行通过**: random repeats retain mandatory sources and identical actual budgets.
9. **实际执行通过**: real HiGHS time-limit status; deliberately injected baseline failures persist; resume retries failures without deleting attempt evidence; bad hashes, incomplete results, symlinks and path traversal fail explicitly.
10. **实际执行通过**: real original OnlineTE default-stop regression, 126 outer iterations with local gRPC/3 workers. **执行失败**: default-stop solution does not meet the stricter D0 quality gate (gap 0.399848%).
11. **实际执行通过**: initialization adapter uses original updates, exports at 1000-iteration cap, independent normalized D0 gap 0.00740982%, demand error approximately 1.31e-16 and no negative flow. The status remains iteration_limit, not original-rule convergence.
12. **实际执行通过**: 20 unit tests, entire smoke (40 optimal C2 rows, both seed-0 synthetic6 scenarios), real summary and pack, compileall, shell syntax, pip check, protocol generation/import, doctor, git diff --check.
13. **未执行及原因**: full five-seed synthetic24 screening and server performance measurements are reserved for the owner's server.
14. **未执行及原因**: C3/C4 depend on reviewed server C2 evidence and are not part of this delivery. admm-pilot explicitly exits nonzero.

Pre-commit integration smoke: `results/active_set/20261112T080428Z-f10d8731` (ignored, dirty implementation tree; correctness only). Its package was produced successfully. Final clean-commit smoke and remote publication are reported in the handoff, not represented as pre-existing evidence here.

## Recovery and remaining boundary

- On interruption, inspect manifest status and run `screening --resume --run-dir ...` only against the same committed code/config/inputs. Failure attempts remain visible.
- User must create/authorize the intended remote destination before upload can be verified. Do not push upstream, force-push, merge, or run the formal server experiment on the owner's behalf.
- Return the generated result package for validation before considering sparse ADMM. No experimental speedup percentage is available or claimed.
