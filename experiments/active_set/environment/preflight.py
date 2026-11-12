"""Fail before importing numerical modules on an unsupported interpreter."""
import sys


def version_error(version):
    if tuple(version[:2]) == (3, 12):
        return None
    actual = '.'.join(str(x) for x in version[:3])
    return (f'Python 3.12 is required; current interpreter is {actual}. '
            'The experiment has NOT started. Install/select Python 3.12, then run '
            'PYTHON=/path/to/python3.12 bash experiments/active_set/run.sh setup. '
            'Do not upgrade system Python or continue to smoke/screening until setup succeeds.')


def main():
    error = version_error(sys.version_info)
    if error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
