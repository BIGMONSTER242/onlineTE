"""Read-only environment diagnostics. Missing setup-installable items are warnings."""
import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[3]


def diagnose():
    hard, warnings, checks = [], [], {}
    checks['repository_root'] = str(ROOT)
    for path in ['protos/__init__.py', 'requirements.txt',
                 'te/algorithms/formulations/path_based/distributed/worker.py']:
        checks[path] = (ROOT/path).is_file()
        if not checks[path]: hard.append(f'Missing repository path: {ROOT/path}; check checkout/container mount, not pip.')
    checks['python'] = platform.python_version()
    if sys.version_info[:2] != (3, 12):
        hard.append('Tested environment requires Python 3.12 (upstream uses PEP 695 syntax); select python3.12 for setup.')
    checks['venv'] = sys.prefix != sys.base_prefix
    if not checks['venv']: warnings.append('Not in project virtual environment; setup creates .venv without changing system pip.')
    checks['versions'] = {}
    for package, module in [('numpy','numpy'), ('numba','numba'), ('scipy','scipy'),
            ('networkx','networkx'), ('grpcio','grpc'), ('grpcio-tools','grpc_tools'),
            ('ortools','ortools.pdlp.python.pdlp'), ('protobuf','google.protobuf'),
            ('jsonargparse','jsonargparse'), ('gurobipy','gurobipy'), ('PyYAML','yaml')]:
        try:
            importlib.import_module(module)
            checks['versions'][package] = importlib.metadata.version(package)
        except Exception as error:
            warnings.append(f'{package}: {type(error).__name__}: {error}; run setup')
    for module in ['protos.array.array_pb2', 'protos.graph.graph_pb2',
                   'protos.core.core_pb2_grpc', 'protos.solver_params.solver_params_pb2']:
        try: importlib.import_module(module); checks[module] = True
        except Exception as error:
            checks[module] = False
            warnings.append(f'Generated protocol module {module}: {error}; setup regenerates it')
    output = ROOT/'results'/'active_set'
    ancestor = output
    while not ancestor.exists(): ancestor = ancestor.parent
    checks['output_parent'] = str(ancestor)
    checks['output_writable'] = os.access(ancestor, os.W_OK | os.X_OK)
    if not checks['output_writable']: hard.append(f'Output is not writable under {ancestor}; check mount/ownership')
    checks['container_detected'] = Path('/.dockerenv').exists()
    checks['cwd'] = os.getcwd()
    # PDLP does not need a license. Presence of gurobipy is not license validation.
    checks['baseline_solver'] = 'OR-Tools PDLP, Threads=1, no Gurobi license required'
    checks['lp_solver'] = 'SciPy HiGHS'
    return dict(checks=checks, warnings=warnings, hard_errors=hard)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    result = diagnose()
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result['hard_errors'] else 0)
