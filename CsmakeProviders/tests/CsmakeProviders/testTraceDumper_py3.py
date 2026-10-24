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
"""Unit tests for the Python 3 conversion of TraceDumper.py.

The file() -> open() change is checked with a real temp file (the unit's job
is writing text to it) and, for the failure path, a mocked open().

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import os
import shutil
import tempfile
import unittest
import unittest.mock
import warnings

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

TraceDumper = support.import_provider('TraceDumper')


class testTraceDumper_py3(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='csmake-trace-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, 'trace.html')

    def _dumper(self, auto=True):
        return TraceDumper.TraceDumper(self.path, 0.2, auto)

    def test_stacktraces_isHighlightedHtmlText(self):
        html = TraceDumper.stacktraces()

        self.assertIsInstance(html, str)
        self.assertIn('ThreadID', html)
        self.assertIn('test_stacktraces_isHighlightedHtmlText', html)

    def test_traceDumper_writesTheTraceToItsFileAsText(self):
        with unittest.mock.patch.object(
                TraceDumper, 'stacktraces', return_value='<pre>trace</pre>'):
            self._dumper().stacktraces()

        with open(self.path) as f:
            self.assertEqual(f.read(), '<pre>trace</pre>')

    def test_traceDumper_closesTheFileWhenWritingFails(self):
        opener = unittest.mock.mock_open()
        opener.return_value.write.side_effect = OSError('disk full')

        with unittest.mock.patch.object(TraceDumper, 'stacktraces',
                                        return_value='x'), \
                unittest.mock.patch('builtins.open', opener):
            with self.assertRaises(OSError):
                self._dumper().stacktraces()

        opener.assert_called_once_with(self.path, 'w+')
        opener.return_value.close.assert_called_once_with()

    def _runOnce(self, dumper, fileExists):
        dumper.stacktraces = unittest.mock.Mock()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)  # isSet()
            with unittest.mock.patch.object(
                    TraceDumper.time, 'sleep',
                    side_effect=lambda seconds: dumper.stop_requested.set()), \
                    unittest.mock.patch.object(
                        TraceDumper.os.path, 'isfile',
                        return_value=fileExists):
                dumper.run()
        return dumper.stacktraces

    def test_run_autoModeRewritesTheTraceEveryInterval(self):
        self.assertEqual(
            self._runOnce(self._dumper(auto=True), True).call_count, 1)

    def test_run_manualModeOnlyWritesWhenTheFileIsMissing(self):
        self.assertEqual(
            self._runOnce(self._dumper(auto=False), True).call_count, 0)
        self.assertEqual(
            self._runOnce(self._dumper(auto=False), False).call_count, 1)


if __name__ == '__main__':
    unittest.main()
