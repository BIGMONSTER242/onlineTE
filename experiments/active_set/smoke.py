"""Real mathematical checks plus real OnlineTE invocation; failures are fatal."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir');args=parser.parse_args()
    test=subprocess.run([sys.executable,'-m','unittest','discover','-s','experiments/active_set/tests','-v'])
    if test.returncode:
        print('Mathematical/operational checks failed; overall smoke FAILED.',flush=True)
        return test.returncode
    print('Independent checks passed. Running actual OnlineTE and C2 on synthetic6, seed 0.',flush=True)
    from .run import run
    config=Path(__file__).parent/'configs/smoke.yaml'
    status=run(config,args.run_dir)
    print('Overall smoke '+('PASSED' if status==0 else 'FAILED: see persisted baseline/LP evidence.'),flush=True)
    return status

if __name__=='__main__':raise SystemExit(main())
