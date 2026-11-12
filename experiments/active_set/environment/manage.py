"""Stable environment command used by run.sh."""
import argparse
import json
import subprocess
import sys
from .doctor import ROOT, diagnose

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['doctor', 'setup'])
    args = parser.parse_args()
    if args.command == 'setup':
        raise SystemExit(subprocess.call(['bash', str(ROOT/'experiments/active_set/environment/setup.sh')], cwd=ROOT))
    result = diagnose()
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result['hard_errors'] else 0)
