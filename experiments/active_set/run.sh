#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then PY="${PYTHON:-python3}"; fi
command="${1:-help}"
if [[ $# -gt 0 ]]; then shift; fi
case "$command" in
  doctor|setup) exec "$PY" -m experiments.active_set.environment.manage "$command" "$@" ;;
  smoke) exec "$PY" -m experiments.active_set.smoke "$@" ;;
  screening) exec "$PY" -m experiments.active_set.run "$@" ;;
  summarize) exec "$PY" -m experiments.active_set.summarize "$@" ;;
  pack) exec "$PY" -m experiments.active_set.pack "$@" ;;
  admm-pilot) echo 'C3 尚未实现 / NOT IMPLEMENTED. C2 server evidence and the predeclared gate are required.' >&2; exit 2 ;;
  *) echo 'Usage: run.sh {doctor|setup|smoke|screening|summarize|pack|admm-pilot} [options]' >&2; exit 2 ;;
esac
