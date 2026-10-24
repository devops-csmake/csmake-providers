# <copyright>
# (c) Copyright 2026 Autumn Patterson
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# </copyright>
"""Guard: every Python file in the repository must still compile.

Python 2 syntax (print statements, "raise a, b, c", backticks) and mixed
tab/space indentation (TabError) are compile-time errors on Python 3, so this
catches them creeping back in even in files no test imports.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import os
import unittest

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support


class testCompiles_py3(unittest.TestCase):

    def test_everyPythonFileCompiles(self):
        failures = []
        checked = 0
        for dirpath, dirnames, filenames in os.walk(support.REPO):
            dirnames[:] = [d for d in dirnames
                           if d != '__pycache__' and not d.startswith('.')]
            for name in sorted(filenames):
                if not name.endswith('.py'):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, 'rb') as f:
                    source = f.read()
                checked += 1
                try:
                    compile(source, path, 'exec', dont_inherit=True)
                except (SyntaxError, ValueError) as exc:
                    failures.append('%s: %s' % (
                        os.path.relpath(path, support.REPO), exc))
        self.assertGreater(checked, 10, "found suspiciously few Python files")
        self.assertEqual([], failures)


if __name__ == '__main__':
    unittest.main()
