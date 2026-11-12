#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3.12}"
command -v "$PYTHON" >/dev/null || { echo 'Python 3.12 is required; install/select it, then rerun setup.' >&2; exit 1; }
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 required"'
[[ -f protos/__init__.py ]] || { echo 'Wrong repository or missing mount: protos/__init__.py absent' >&2; exit 1; }
[[ -d .venv ]] || "$PYTHON" -m venv .venv
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3,12); assert sys.prefix != sys.base_prefix'
.venv/bin/python -m pip install -r experiments/active_set/environment/requirements.lock.txt
.venv/bin/python protos/__init__.py
.venv/bin/python -c 'import protos.array.array_pb2, protos.graph.graph_pb2, protos.core.core_pb2_grpc, protos.solver_params.solver_params_pb2; from te.algorithms.formulations.path_based.distributed.coordinator import OnlineTECoordinator'
.venv/bin/python experiments/active_set/environment/doctor.py
