"""Regression tests for the owner's Python 3.8 setup-failure report."""
import subprocess
import sys
import unittest
from experiments.active_set.environment.preflight import version_error


class PreflightTests(unittest.TestCase):
    def test_unsupported_version_reports_root_cause(self):
        error = version_error((3, 8, 10))
        self.assertIn('3.8.10', error)
        self.assertIn('has NOT started', error)
        self.assertIn('setup', error)
        self.assertIsNone(version_error((3, 12, 14)))

    def test_dependency_error_is_not_masked_by_fallback_import(self):
        for module in ['prepare_cases', 'selection']:
            code = '''import importlib.abc,sys
class BlockScipy(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname == 'scipy':
            raise ModuleNotFoundError("No module named 'scipy'",name='scipy')
sys.meta_path.insert(0,BlockScipy())
try:
    __import__('experiments.active_set.MODULE')
except ModuleNotFoundError as error:
    print(error.name)
'''.replace('MODULE', module)
            result = subprocess.run([sys.executable, '-c', code], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'scipy')


if __name__ == '__main__':
    unittest.main()
