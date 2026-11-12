# Tested isolated CPU environment

Python 3.12 is required by the upstream PEP 695 syntax. The initial tested interpreter is 3.12.14 on Linux x86_64. `requirements.lock.txt` records the actual isolated environment, including transitive dependencies. Numba 0.61.2 supports NumPy 2.1.3 and Python 3.12. SciPy 1.15.3 supplies HiGHS; original OnlineTE uses OR-Tools 9.12.4544 PDLP with one thread. Gurobi imports are needed by upstream eager imports, but this adapter never invokes Gurobi or requires its license.

`setup.sh` creates/reuses `.venv`, installs locked versions and regenerates protocol code. No system pip upgrades. `PYTHON=/path/to/python3.12` selects an interpreter. Generated protocol modules and the environment are local, ignored artifacts.

`doctor.py` only inspects. Setup-installable missing modules/protocol code are warnings; an invalid Python version, missing source paths or unwritable output parent are hard errors. Read-only permission inspection is not a proof that a future write can succeed; actual output creation is checked by each command. Container detection and resolved paths are recorded to distinguish mount failures from missing packages.

## Recover from a server with Python 3.8

A failed setup reporting no Python 3.12 means dependencies were never installed.
Missing SciPy/generated protos and `Path.is_relative_to` errors from later commands
are consequences of running outside the supported environment, not algorithm results.
Do not upgrade or replace `/usr/bin/python3`. Install Python 3.12 side by side in
your own account. For example, using Astral's official uv installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
"$HOME/.local/bin/uv" python install 3.12
PYTHON="$("$HOME/.local/bin/uv" python find 3.12)" \
  bash experiments/active_set/run.sh setup
```

Run each command only after the preceding one succeeds. If uv or Python 3.12 is
already installed, reuse it instead of reinstalling. A Conda Python 3.12 interpreter
is also suitable via the explicit PYTHON path. Setup still creates this project's
`.venv`. After successful setup, run doctor, smoke, then screening, connected by
`&&`. Do not separately install SciPy into Python 3.8 or edit source to make the
unsupported interpreter appear compatible.
