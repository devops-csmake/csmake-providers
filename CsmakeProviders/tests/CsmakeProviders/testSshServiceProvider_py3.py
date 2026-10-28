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
"""Unit tests for the Python 3 conversion of SshServiceProvider.py.

No sshd, nc, ps or kill is run: the config manager's shellout is a
FakeManager (check_output answers are scripted BYTES, as the real call
returns) and the direct subprocess/time calls are patched.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import subprocess
import unittest
import unittest.mock

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

SSP = support.import_provider('SshServiceProvider')

SSHD_COMMAND = ['/usr/sbin/sshd', '-e', '-D', '-f', '/etc/csmake/sshd_config']
PS_COMMAND = ('ps', '-o', 'pid', '--ppid', '4242', '--noheaders')


class FakePort(object):
    def __init__(self):
        self.events = []

    def lock(self):
        self.events.append('lock')

    def unbind(self):
        self.events.append('unbind')

    def unlock(self):
        self.events.append('unlock')

    def address(self):
        return ('127.0.0.1', 2222)


class testSshServiceProvider_py3(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.manager = support.FakeManager(self.log, {
            ('which', 'sshd'): b'/usr/sbin/sshd\n'})
        self.manager.getDaemonConfigFile = lambda: '/etc/csmake/sshd_config'
        self.port = FakePort()
        self.process = unittest.mock.Mock(pid=4242)
        self.process.poll.return_value = None
        self.manager.results[tuple(SSHD_COMMAND)] = self.process
        self.daemon = object.__new__(SSP.SshServiceDaemon)
        self.daemon.log = self.log
        self.daemon.configManager = self.manager
        self.daemon.options = {'port': self.port}
        self.daemon.process = None

        self.sleep = self._patch(SSP.time, 'sleep')
        self.check_call = self._patch(SSP.subprocess, 'check_call')
        self.call = self._patch(SSP.subprocess, 'call', return_value=0)

    def _patch(self, target, name, **kwargs):
        patch = unittest.mock.patch.object(target, name, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock

    # --- _startListening --------------------------------------------------

    def test_startListening_buildsTheCommandFromDecodedWhichOutput(self):
        # `which` gives bytes; the path has to be decoded and stripped before
        # it is joined into the log line and handed to Popen.
        self.daemon._startListening()

        self.assertEqual(
            [(call.__name__, command) for call, command, _
             in self.manager.calls],
            [('check_output', ['which', 'sshd']),
             ('Popen', SSHD_COMMAND)])
        for part in self.manager.calls[1][1]:
            self.assertIsInstance(part, str)
        self.assertIs(self.daemon.process, self.process)
        self.assertIn('Calling Popen with: ' + ' '.join(SSHD_COMMAND),
                      self.log.messages('debug'))

    def test_startListening_probesThePortUntilTheServerListens(self):
        self.check_call.side_effect = [
            support.called_process_error(['nc']),
            support.called_process_error(['nc']),
            0]

        self.daemon._startListening()

        self.assertEqual(
            self.check_call.call_args_list,
            [unittest.mock.call(['nc', '-z', '127.0.0.1', '2222'])] * 3)
        self.assertEqual(self.sleep.call_args_list,
                         [unittest.mock.call(.1)] * 2)

    def test_startListening_locksAndUnbindsThePortThenUnlocksIt(self):
        self.daemon._startListening()

        self.assertEqual(self.port.events, ['lock', 'unbind', 'unlock'])

    def test_startListening_missingSshdIsAnErrorBeforeAnythingStarts(self):
        self.manager.results[('which', 'sshd')] = \
            support.called_process_error(['which', 'sshd'])

        with self.assertRaises(subprocess.CalledProcessError):
            self.daemon._startListening()

        self.assertEqual(self.port.events, [])
        self.assertEqual(len(self.manager.calls), 1)

    def test_startListening_aServerThatExitsAtOnceIsAnError(self):
        self.process.poll.return_value = 255

        with self.assertRaisesRegex(Exception, 'Process is not running'):
            self.daemon._startListening()

        self.check_call.assert_not_called()
        self.assertEqual(self.port.events, ['lock', 'unbind', 'unlock'])

    def test_startListening_aServerThatDiesWhileWaitingIsAnError(self):
        self.process.poll.side_effect = [None, None, 1, 1]
        self.check_call.side_effect = support.called_process_error(['nc'])

        with self.assertRaisesRegex(Exception, 'Process is not running'):
            self.daemon._startListening()

        self.assertEqual(self.port.events[-1], 'unlock')

    def test_startListening_aServerThatNeverListensTimesOut(self):
        self.check_call.side_effect = support.called_process_error(['nc'])

        with self.assertRaisesRegex(Exception, "didn't listen after 5 seconds"):
            self.daemon._startListening()

        self.assertEqual(self.check_call.call_count, 50)
        self.assertEqual(self.port.events[-1], 'unlock')

    # --- _cleanup -----------------------------------------------------------

    def _cleanupDaemon(self, psOutput):
        self.manager.results[PS_COMMAND] = psOutput
        self.daemon.process = unittest.mock.Mock(pid=4242)
        return self.daemon

    def test_cleanup_killsEachChildOfSshdListedByPs(self):
        self._cleanupDaemon(b'111\n222\n')

        self.daemon._cleanup()

        self.assertEqual(self.manager.commands(), [
            list(PS_COMMAND),
            ['kill', '-9', '111'],
            ['kill', '-9', '222']])
        for command in self.manager.commands():
            for part in command:
                self.assertIsInstance(part, str)
        self.assertEqual([], self.log.problems)

    def test_cleanup_noChildrenMeansNothingIsKilled(self):
        self._cleanupDaemon(b'')

        self.daemon._cleanup()

        self.assertEqual(self.manager.commands(), [list(PS_COMMAND)])
        self.call.assert_not_called()

    def test_cleanup_psFailureFallsBackToSudoKills(self):
        self._cleanupDaemon(support.called_process_error(list(PS_COMMAND)))

        self.daemon._cleanup()

        self.assertEqual(self.call.call_count, 2)
        script = self.call.call_args_list[0][0][0]
        self.assertIn('sudo ps -o pid --ppid 4242 --noheaders', script)
        self.assertTrue(self.call.call_args_list[0][1]['shell'])
        self.assertEqual(self.call.call_args_list[1][0][0],
                         ['sudo', 'kill', '4242'])
        self.assertEqual(len(self.log.problems), 1)
        self.assertIn('Could not stop sshd', self.log.problems[0])


if __name__ == '__main__':
    unittest.main()
