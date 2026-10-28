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
        with unittest.mock.patch.object(
                TraceDumper.time, 'sleep',
                side_effect=lambda seconds: dumper.stop_requested.set()), \
                unittest.mock.patch.object(
                    TraceDumper.os.path, 'isfile', return_value=fileExists):
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


    def test_run_checksTheStopFlagWithIsSet(self):
        # Event.isSet() is a deprecated alias of is_set()
        dumper = self._dumper()
        dumper.stacktraces = unittest.mock.Mock()
        flag = unittest.mock.Mock(spec=['is_set', 'set'])
        flag.is_set.side_effect = [False, True]
        dumper.stop_requested = flag

        with unittest.mock.patch.object(TraceDumper.time, 'sleep'):
            dumper.run()

        self.assertEqual(flag.is_set.call_count, 2)
        dumper.stacktraces.assert_called_once_with()

    def test_run_aTraceThatCannotBeWrittenEndsTheThreadWithTheError(self):
        dumper = self._dumper()
        dumper.stacktraces = unittest.mock.Mock(side_effect=OSError('disk full'))

        with unittest.mock.patch.object(TraceDumper.time, 'sleep'):
            with self.assertRaises(OSError):
                dumper.run()

    def test_stop_stopsTheThreadAndRemovesTheTraceFile(self):
        dumper = self._dumper()
        with open(self.path, 'w') as f:
            f.write('old trace')
        dumper.join = unittest.mock.Mock()

        dumper.stop()

        self.assertTrue(dumper.stop_requested.is_set())
        dumper.join.assert_called_once_with()
        self.assertFalse(os.path.exists(self.path))

    def test_stop_aTraceFileThatIsAlreadyGoneIsNotAnError(self):
        dumper = self._dumper()
        dumper.join = unittest.mock.Mock()

        dumper.stop()

        self.assertTrue(dumper.stop_requested.is_set())

    def test_init_anIntervalThatIsTooShortIsRefused(self):
        with self.assertRaises(AssertionError):
            TraceDumper.TraceDumper(self.path, 0.1, True)


class testTraceModuleFunctions_py3(unittest.TestCase):
    """trace_start() / trace_stop(): the module level on/off switch."""

    def setUp(self):
        self.addCleanup(setattr, TraceDumper, '_tracer', None)
        TraceDumper._tracer = None
        patch = unittest.mock.patch.object(TraceDumper, 'TraceDumper')
        self.dumper_class = patch.start()
        self.addCleanup(patch.stop)
        self.dumper = self.dumper_class.return_value

    def test_traceStart_startsADaemonThreadDumpingToTheFile(self):
        TraceDumper.trace_start('trace.html', 7, False)

        self.dumper_class.assert_called_once_with('trace.html', 7, False)
        self.assertIs(self.dumper.daemon, True)
        self.dumper.setDaemon.assert_not_called()   # deprecated spelling
        self.dumper.start.assert_called_once_with()

    def test_traceStart_defaultsToEveryFiveSecondsAndAlwaysUpdating(self):
        TraceDumper.trace_start('trace.html')

        self.dumper_class.assert_called_once_with('trace.html', 5, True)

    def test_traceStart_onlyOneTraceAtATime(self):
        self.dumper.fpath = '/work/trace.html'
        TraceDumper.trace_start('trace.html')

        with self.assertRaisesRegex(Exception, 'Already tracing to /work/trace.html'):
            TraceDumper.trace_start('other.html')

        self.assertEqual(self.dumper_class.call_count, 1)

    def test_traceStop_stopsTheTraceAndAllowsANewOne(self):
        TraceDumper.trace_start('trace.html')

        TraceDumper.trace_stop()

        self.dumper.stop.assert_called_once_with()
        self.assertIsNone(TraceDumper._tracer)
        TraceDumper.trace_start('again.html')
        self.assertEqual(self.dumper_class.call_count, 2)

    def test_traceStop_withNothingToStopIsAnError(self):
        with self.assertRaisesRegex(Exception, 'Not tracing'):
            TraceDumper.trace_stop()

    def test_traceStop_aSecondStopIsAnError(self):
        TraceDumper.trace_start('trace.html')
        TraceDumper.trace_stop()

        with self.assertRaisesRegex(Exception, 'Not tracing'):
            TraceDumper.trace_stop()


if __name__ == '__main__':
    unittest.main()
