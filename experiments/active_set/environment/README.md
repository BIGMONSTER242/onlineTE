# Tested isolated CPU environment

Python 3.12 is required by the upstream PEP 695 syntax. The initial tested interpreter is 3.12.14 on Linux x86_64. `requirements.lock.txt` records the actual isolated environment, including transitive dependencies. Numba 0.61.2 supports NumPy 2.1.3 and Python 3.12. SciPy 1.15.3 supplies HiGHS; original OnlineTE uses OR-Tools 9.12.4544 PDLP with one thread. Gurobi imports are needed by upstream eager imports, but this adapter never invokes Gurobi or requires its license.

`setup.sh` creates/reuses `.venv`, installs locked versions and regenerates protocol code. No system pip upgrades. `PYTHON=/path/to/python3.12` selects an interpreter. Generated protocol modules and the environment are local, ignored artifacts.

`doctor.py` only inspects. Setup-installable missing modules/protocol code are warnings; an invalid Python version, missing source paths or unwritable output parent are hard errors. Read-only permission inspection is not a proof that a future write can succeed; actual output creation is checked by each command. Container detection and resolved paths are recorded to distinguish mount failures from missing packages.
