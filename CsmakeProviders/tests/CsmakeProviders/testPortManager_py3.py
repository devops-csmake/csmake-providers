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
"""Unit tests for the port handling in CsmakeServiceProvider.py: the NAT port
manager (iptables redirect), createPort, the cross-process port lock, and how
CsmakeServiceProvider._processOptions picks or creates the service's port.

No socket is bound, no iptables rule is added and nothing under /var/lock is
touched: socket.socket, subprocess, fcntl, open() and the directory checks
are patched.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import errno
import fcntl
import socket
import subprocess
import types
import unittest
import unittest.mock

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

CSP = support.import_provider('CsmakeServiceProvider')
PortManager = CSP.CsmakePortManager

LOCK_DIR = '/var/lock/csmake'
LOCK_FILE = '/var/lock/csmake/_CsmakePortManager.lock'


class PortTestCase(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock


class testNatPortManager_py3(PortTestCase):

    def setUp(self):
        PortTestCase.setUp(self)
        self.handler = unittest.mock.Mock(name='sockethandler')
        self.sock = unittest.mock.Mock(name='bound socket')
        self.bindport = unittest.mock.Mock(
            name='bindport', port=32768, sock=self.sock)
        self.bindport.address.return_value = ('10.0.0.5', 32768)
        self.range = self._patch(PortManager, 'getUserPortRange',
                                 return_value=['32768', '60999'])
        self.find = self._patch(PortManager, 'findOpenTcpPort',
                                return_value=self.bindport)
        # The command list is edited in place after check_call() returns
        # (--append becomes --delete), so record a copy of each call.
        self.added = []
        self.check_call = self._patch(
            CSP.subprocess, 'check_call',
            side_effect=lambda argv, **kwargs: self.added.append(
                (list(argv), kwargs)))
        self.call = self._patch(CSP.subprocess, 'call')

    def _nat(self, port=80):
        nat = CSP.CsmakeNATPortManager(
            '10.0.0.5', port, self.log, self.handler)
        # A NAT manager removes its iptables rule (sudo!) when it is garbage
        # collected; make sure that can never happen after the patches end.
        self.addCleanup(setattr, nat, 'natted', False)
        return nat

    def _rule(self, action='--append', to=32768, port=80):
        return ['sudo', 'iptables', '--table', 'nat', action, 'OUTPUT',
                '--source', '10.0.0.5', '--protocol', 'tcp',
                '--dport', str(port), '--jump', 'REDIRECT',
                '--to-port', str(to)]

    def test_init_redirectsTheRequestedPortToAnEphemeralOne(self):
        nat = self._nat()

        self.find.assert_called_once_with(
            '10.0.0.5', '32768', '60999', self.log, self.handler)
        self.assertEqual(self.added, [
            (self._rule(), {'stdout': None, 'stderr': None})])
        self.assertTrue(nat.natted)
        self.assertEqual(nat.iptablesCommand, self._rule('--delete'))
        self.assertEqual(nat.address(), ('10.0.0.5', 32768))
        self.assertIs(nat.sock, self.sock)
        self.assertEqual((nat.interface, nat.port), ('10.0.0.5', 80))

    def test_init_aKernelRangeThatCannotBeReadFallsBackToTheDefaults(self):
        self.range.side_effect = support.called_process_error(['cat'])

        self._nat()

        self.find.assert_called_once_with(
            '10.0.0.5', '20000', '21000', self.log, self.handler)
        self.assertEqual(len(self.log.messages('exception')), 1)

    def test_init_noFreePortIsAnErrorAndNoRuleIsAdded(self):
        self.find.return_value = None
        # (pre-existing: the half built manager's __del__ then trips over
        # bindport being None; keep that noise out of the test output)
        self._patch(CSP.CsmakeNATPortManager, '__del__', lambda self: None)

        with self.assertRaises(Exception):
            self._nat()

        self.check_call.assert_not_called()

    def test_init_aFailingIptablesIsAnErrorAndNothingIsToBeUndone(self):
        self.check_call.side_effect = support.called_process_error(['iptables'])

        with self.assertRaises(subprocess.CalledProcessError):
            self._nat()

        self.call.assert_not_called()

    def test_cleanup_deletesTheRuleOnceAndReleasesThePorts(self):
        nat = self._nat()

        nat.cleanup()
        nat.cleanup()

        self.call.assert_called_once_with(
            self._rule('--delete'), stdout=None, stderr=None)
        self.assertFalse(nat.natted)
        self.assertEqual(self.bindport.cleanup.call_count, 2)
        self.sock.close.assert_called_once_with()
        self.assertIsNone(nat.sock)

    def test_cleanup_withoutARuleDoesNotCallIptables(self):
        nat = self._nat()
        nat.natted = False

        nat.cleanup()

        self.call.assert_not_called()
        self.bindport.cleanup.assert_called_once_with()


class testCreatePort_py3(PortTestCase):

    def setUp(self):
        PortTestCase.setUp(self)
        self.socket_class = self._patch(CSP.socket, 'socket')
        self.sock = self.socket_class.return_value
        self.handler = unittest.mock.Mock(side_effect=lambda sock: sock)

    def test_createPort_bindsTheRequestedAddress(self):
        port = PortManager.createPort('127.0.0.1', 8080, self.log, self.handler)

        self.sock.bind.assert_called_once_with(('127.0.0.1', 8080))
        self.handler.assert_called_once_with(self.sock)
        self.assertEqual(port.address(), ('127.0.0.1', 8080))
        self.assertEqual(self.log.messages('debug'), ['Bound 127.0.0.1:8080'])

    def test_createPort_aPrivilegedPortIsRedirectedWithNat(self):
        self.sock.bind.side_effect = socket.error(errno.EACCES, 'denied')
        nat_class = self._patch(CSP, 'CsmakeNATPortManager')

        port = PortManager.createPort('127.0.0.1', 80, self.log, self.handler)

        nat_class.assert_called_once_with('127.0.0.1', 80, self.log, self.handler)
        self.assertIs(port, nat_class.return_value)

    def test_createPort_aPortThatIsInUseIsAnError(self):
        self.sock.bind.side_effect = socket.error(errno.EADDRINUSE, 'in use')
        nat_class = self._patch(CSP, 'CsmakeNATPortManager')

        with self.assertRaises(socket.error):
            PortManager.createPort('127.0.0.1', 8080, self.log, self.handler)

        nat_class.assert_not_called()


class testPortLock_py3(PortTestCase):

    def setUp(self):
        PortTestCase.setUp(self)
        self.exists = self._patch(CSP.os.path, 'exists', return_value=False)
        self.makedirs = self._patch(CSP.os, 'makedirs')
        self.flock = self._patch(CSP.fcntl, 'flock')
        self.opener = unittest.mock.mock_open()
        patch = unittest.mock.patch('builtins.open', self.opener)
        patch.start()
        self.addCleanup(patch.stop)

    def test_lock_createsTheLockDirectoryAndTakesAnExclusiveLock(self):
        lockfile = PortManager._lock(self.log)

        self.makedirs.assert_called_once_with(LOCK_DIR)
        self.opener.assert_called_once_with(LOCK_FILE, 'a')
        self.flock.assert_called_once_with(lockfile, fcntl.LOCK_EX)
        self.assertIs(lockfile, self.opener.return_value)

    def test_lock_anExistingLockDirectoryIsNotRecreated(self):
        self.exists.return_value = True

        PortManager._lock(self.log)

        self.makedirs.assert_not_called()

    def test_lock_anUncreatableLockDirectoryIsLoggedAndYieldsNoLock(self):
        self.makedirs.side_effect = PermissionError(errno.EACCES, 'denied')

        lockfile = PortManager._lock(self.log)

        self.assertIsNone(lockfile)
        self.opener.assert_not_called()
        self.assertEqual(len(self.log.messages('exception')), 1)

    def test_lock_aLockThatCannotBeTakenClosesTheFileAndIsLogged(self):
        self.flock.side_effect = OSError(errno.EINTR, 'interrupted')

        PortManager._lock(self.log)

        self.opener.return_value.close.assert_called_once_with()
        self.assertEqual(len(self.log.messages('exception')), 1)

    def test_unlock_releasesTheLockThenClosesTheFile(self):
        lockfile = unittest.mock.Mock()

        PortManager._unlock(lockfile, self.log)

        self.flock.assert_called_once_with(lockfile, fcntl.LOCK_UN)
        lockfile.close.assert_called_once_with()
        self.assertEqual(self.log.problems, [])

    def test_unlock_aFailureToReleaseStillClosesTheFile(self):
        lockfile = unittest.mock.Mock()
        self.flock.side_effect = OSError('bad descriptor')

        PortManager._unlock(lockfile, self.log)

        lockfile.close.assert_called_once_with()
        self.assertEqual(len(self.log.messages('exception')), 1)

    def test_unlock_aFailureToCloseIsLogged(self):
        lockfile = unittest.mock.Mock()
        lockfile.close.side_effect = OSError('io error')

        PortManager._unlock(lockfile, self.log)

        self.assertEqual(len(self.log.messages('exception')), 1)

    def _port(self):
        return PortManager('127.0.0.1', 8080, unittest.mock.Mock(), self.log, None)

    def test_instanceLock_isTakenOnceAndReleasedOnce(self):
        lock = self._patch(PortManager, '_lock', return_value='the-lockfile')
        unlock = self._patch(PortManager, '_unlock')
        port = self._port()

        port.lock()
        port.lock()
        port.unlock()
        port.unlock()

        lock.assert_called_once_with(self.log)
        unlock.assert_called_once_with('the-lockfile', self.log)
        self.assertIsNone(port.lockfile)

    def test_unbind_closesTheSocketOnce(self):
        port = self._port()
        sock = port.sock

        port.unbind()
        port.unbind()

        sock.close.assert_called_once_with()
        self.assertIsNone(port.sock)
        self.assertEqual(self.log.messages('debug'), ['freed 127.0.0.1:8080'])

    def test_cleanup_aFailingUnbindAndAFailingUnlockAreEachLogged(self):
        port = self._port()
        port.sock.close.side_effect = OSError('bad descriptor')
        port.lockfile = 'held'
        self._patch(PortManager, '_unlock', side_effect=RuntimeError('stuck'))

        port.cleanup()

        self.assertEqual(
            [m.split('\n')[0] for m in self.log.messages('exception')],
            ['Unbind failed', 'Unlock failed'])

    def test_addresses_areTheInterfaceAndPort(self):
        port = self._port()

        self.assertEqual(port.address(), ('127.0.0.1', 8080))
        self.assertEqual(port.realaddress(), ('127.0.0.1', 8080))


class testProviderPortOptions_py3(PortTestCase):
    """CsmakeServiceProvider._processOptions: choosing the service's port."""

    def setUp(self):
        PortTestCase.setUp(self)
        self.find = self._patch(PortManager, 'findOpenTcpPort')
        self.create = self._patch(PortManager, 'createPort')

    def _provider(self, **options):
        provider = object.__new__(CSP.CsmakeServiceProvider)
        provider.log = self.log
        provider.module = types.SimpleNamespace(
            log=self.log, env=types.SimpleNamespace(env={}))
        provider.lowerport, provider.upperport = 20000, 24000
        provider.options = options
        return provider

    def test_noPortGivenMeansTheFirstFreePortOfTheDefaultRange(self):
        provider = self._provider()

        provider._processOptions()

        self.find.assert_called_once_with(
            'localhost', 20000, 24000, self.log, provider._customizeSocket)
        self.assertIs(provider.options['port'], self.find.return_value)
        self.assertEqual(provider.options['interfaces'], ['localhost'])
        self.assertIsNone(provider.options['chroot'])
        self.assertIs(provider.options['no-sudo'], False)

    def test_interfacesAreSplitOnCommasAndNewlinesAndTheFirstIsUsed(self):
        provider = self._provider(interfaces='10.0.0.5, 10.0.0.6\n10.0.0.7')

        provider._processOptions()

        self.assertEqual(provider.options['interfaces'],
                         ['10.0.0.5', '10.0.0.6', '10.0.0.7'])
        self.assertEqual(self.find.call_args[0][0], '10.0.0.5')

    def test_aPortRangeOfOnePortIsSearchedAsGiven(self):
        # (only a single-port range: how the upper bound is computed for a
        # wider range is not asserted)
        provider = self._provider(**{'port-range': ' 30000 - 30000'})

        provider._processOptions()

        self.assertEqual(self.find.call_args[0][1:3], (30000, 30000))

    def test_aMalformedPortRangeIsAnError(self):
        provider = self._provider(**{'port-range': '30000'})

        with self.assertRaisesRegex(ValueError, 'port-range'):
            provider._processOptions()

        self.assertEqual(len(self.log.messages('error')), 2)
        self.find.assert_not_called()

    def test_everyPortBeingBusyIsAnError(self):
        self.find.return_value = None
        provider = self._provider()

        with self.assertRaisesRegex(RuntimeError, 'No port could be found'):
            provider._processOptions()

        self.assertEqual(len(self.log.messages('error')), 1)
        self.assertNotIn('port', provider.options)

    def test_anExplicitPortIsCreatedNotSearchedFor(self):
        provider = self._provider(port='8080', interfaces='10.0.0.5')

        provider._processOptions()

        self.create.assert_called_once_with(
            '10.0.0.5', 8080, self.log, provider._customizeSocket)
        self.find.assert_not_called()
        self.assertIs(provider.options['port'], self.create.return_value)

    def test_anExplicitPortThatCannotBeCreatedIsAnError(self):
        self.create.side_effect = socket.error(errno.EADDRINUSE, 'in use')
        provider = self._provider(port='8080')

        with self.assertRaises(socket.error):
            provider._processOptions()

    def test_theChosenAddressIsPublishedToTheNamedEnvironmentVariables(self):
        self.find.return_value.address.return_value = ('10.0.0.5', 31000)
        provider = self._provider(**{'interface-env': 'FACADE_HOST',
                                     'port-env': 'FACADE_PORT'})

        provider._processOptions()

        self.assertEqual(provider.module.env.env,
                         {'FACADE_HOST': '10.0.0.5', 'FACADE_PORT': 31000})


if __name__ == '__main__':
    unittest.main()
