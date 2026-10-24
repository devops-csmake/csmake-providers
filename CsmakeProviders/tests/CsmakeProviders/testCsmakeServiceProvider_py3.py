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
"""Unit tests for the Python 3 conversion of CsmakeServiceProvider.py.

Everything that shells out goes through a FakeManager (it records the
commands instead of running them) or a patched subprocess.check_output; real
temp files are used only where the unit reads their mode bits.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import errno
import os
import shutil
import socket
import subprocess
import tempfile
import types
import unittest
import unittest.mock

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

CSP = support.import_provider('CsmakeServiceProvider')


class InPlaceConfig(CSP.CsmakeServiceConfig):
    def restore(self, filename, in_chroot):
        return True  # as SSLCertificateBundleConfig does


class ConfigTypeA(object):
    pass


class ConfigTypeB(object):
    pass


class testCsmakeServiceProvider_py3(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.manager = support.FakeManager(self.log)
        self.tmp = tempfile.mkdtemp(prefix='csmake-svc-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _file(self, name='target.txt', mode=0o640):
        path = os.path.join(self.tmp, name)
        with open(path, 'w') as f:
            f.write('x')
        os.chmod(path, mode)
        return path

    def _assertChmod(self, command, path, mode):
        self.assertEqual(command[0], 'chmod')
        self.assertEqual(command[2], path)
        self.assertRegex(command[1], support.CHMOD_MODE)
        self.assertEqual(int(command[1], 8), mode)

    # --- CsmakeServiceChangeFilePrivs ---------------------------------

    def test_changeFilePrivs_restoreUsesModeStringChmodAccepts(self):
        # oct(0o640) is '0640' on Python 2 but '0o640' on Python 3, which
        # chmod rejects.
        path = self._file(mode=0o640)
        info = os.stat(path)
        privs = CSP.CsmakeServiceChangeFilePrivs(
            path, self.manager, filemod='777')
        self.assertEqual(self.manager.commands(), [['chmod', '777', path]])

        privs()

        restore = self.manager.commands()[1:]
        self.assertEqual(len(restore), 3)
        self._assertChmod(restore[0], path, 0o640)
        self.assertEqual(restore[1], ['chown', str(info.st_uid), path])
        self.assertEqual(restore[2], ['chgrp', str(info.st_gid), path])

    def test_changeFilePrivs_restoreHappensOnlyOnce(self):
        path = self._file()
        privs = CSP.CsmakeServiceChangeFilePrivs(
            path, self.manager, filemod='777')
        privs()
        count = len(self.manager.calls)

        privs()

        self.assertEqual(len(self.manager.calls), count)

    def test_changeFilePrivs_changesOwnerAndGroupOnlyWhenAsked(self):
        path = self._file()

        privs = CSP.CsmakeServiceChangeFilePrivs(
            path, self.manager, fileuser='nobody', filegroup='nogroup',
            in_chroot=True)

        self.assertEqual(self.manager.calls, [
            (subprocess.check_call, ['chown', 'nobody', path], True),
            (subprocess.check_call, ['chgrp', 'nogroup', path], True)])
        privs.changed = False  # nothing to restore on garbage collection

    def test_changeFilePrivs_missingPathIsLeftAlone(self):
        path = os.path.join(self.tmp, 'absent')

        privs = CSP.CsmakeServiceChangeFilePrivs(
            path, self.manager, filemod='777')
        privs()

        self.assertEqual(self.manager.calls, [])

    def test_changeFilePrivs_unstatablePathIsDescribedByTheStatCommand(self):
        # check_output returns bytes; the parts must be text to be reused as
        # chmod/chown arguments.
        path = self._file()
        command = ('stat', '--printf', '%a %u %g', path)
        self.manager.results[command] = b'644 1000 1001\n'

        with unittest.mock.patch.object(
                CSP.os, 'stat', side_effect=OSError('denied')), \
                unittest.mock.patch.object(
                    CSP.os.path, 'exists', return_value=True):
            privs = CSP.CsmakeServiceChangeFilePrivs(path, self.manager)

        self.assertEqual(self.manager.calls, [
            (subprocess.check_output, list(command), True)])
        self.assertEqual(
            (privs.oldpermissions, privs.oldowner, privs.oldgroup),
            ('644', '1000', '1001'))
        for value in (privs.oldpermissions, privs.oldowner, privs.oldgroup):
            self.assertIsInstance(value, str)

    def test_changeFilePrivs_statCommandFailurePropagates(self):
        path = self._file()
        command = ('stat', '--printf', '%a %u %g', path)
        self.manager.results[command] = support.called_process_error(command)

        with unittest.mock.patch.object(
                CSP.os, 'stat', side_effect=OSError('denied')), \
                unittest.mock.patch.object(
                    CSP.os.path, 'exists', return_value=True):
            with self.assertRaises(subprocess.CalledProcessError):
                CSP.CsmakeServiceChangeFilePrivs(path, self.manager)

    # --- CsmakeServiceConfig._backupAndSetup / clean --------------------

    def _config(self, clazz=InPlaceConfig):
        return clazz(types.SimpleNamespace(log=self.log), self.manager,
                     'unused', 'unused', False, None)

    def test_backupAndSetup_inPlaceRestoreUsesModeStringsChmodAccepts(self):
        directory = os.path.join(self.tmp, 'etc')
        os.mkdir(directory)
        os.chmod(directory, 0o750)
        target = self._file('etc/bundle.crt', 0o640)
        backup = target + '.csmake.bkup'
        info = os.stat(target)
        owner = '%d:%d' % (info.st_uid, info.st_gid)
        dirinfo = os.stat(directory)
        dirowner = '%d:%d' % (dirinfo.st_uid, dirinfo.st_gid)
        config = self._config()

        config._backupAndSetup(
            target, moveOriginal=False, restoreInPlace=True, in_chroot=False)

        self.assertEqual(self.manager.commands(), [
            ['mkdir', '-p', directory],
            ['chmod', '777', directory],
            ['cp', target, backup],
            ['chmod', '777', target]])
        del self.manager.calls[:]

        config.clean()

        commands = self.manager.commands()
        self.assertEqual(len(commands), 5, commands)
        self.assertEqual(commands[0], ['rm', backup])
        self.assertEqual(commands[1], ['chown', owner, target])
        self._assertChmod(commands[2], target, 0o640)
        self.assertEqual(commands[3], ['chown', dirowner, directory])
        self._assertChmod(commands[4], directory, 0o750)

    def test_backupAndSetup_movedOriginalIsPutBackWithItsModes(self):
        directory = os.path.join(self.tmp, 'etc')
        os.mkdir(directory)
        os.chmod(directory, 0o750)
        target = self._file('etc/pip.conf', 0o600)
        backup = target + '.csmake.bkup'
        config = self._config(CSP.CsmakeServiceConfig)
        config._backupAndSetup(target, in_chroot=False)
        self.assertEqual(self.manager.commands()[:3], [
            ['mkdir', '-p', directory],
            ['chmod', '777', directory],
            ['mv', target, backup]])
        del self.manager.calls[:]

        config.clean()

        commands = self.manager.commands()
        self.assertEqual(commands[:2], [['rm', target], ['mv', backup, target]])
        chmods = [c for c in commands if c[0] == 'chmod']
        self.assertEqual(len(chmods), 2, commands)
        self._assertChmod(chmods[0], target, 0o600)
        self._assertChmod(chmods[1], directory, 0o750)

    def test_backupAndSetup_nothingExistedSoCreatedPathsAreRemoved(self):
        directory = os.path.join(self.tmp, 'new')
        target = os.path.join(directory, 'pip.conf')
        # nothing to back up: mv fails, which _backupAndSetup tolerates
        self.manager.results[('mv', target, target + '.csmake.bkup')] = \
            support.called_process_error(['mv'])
        config = self._config(CSP.CsmakeServiceConfig)
        config._backupAndSetup(target, in_chroot=False)
        del self.manager.calls[:]

        config.clean()

        self.assertEqual(self.manager.commands(), [
            ['rm', target], ['rmdir', '-p', directory]])
        self.assertEqual([], self.log.problems)

    def test_backupAndSetup_failedRestoreIsLoggedNotRaised(self):
        target = self._file()
        config = self._config(CSP.CsmakeServiceConfig)
        config._backupAndSetup(target, in_chroot=False)
        self.manager.results[('rm', target)] = support.called_process_error(
            ['rm', target])

        config.clean()  # must not raise

        self.assertEqual(len(self.log.problems), 1)
        self.assertIn(target, self.log.problems[0])

    def test_backupAndSetup_refusedOnceCleaningHasStarted(self):
        config = self._config(CSP.CsmakeServiceConfig)
        config.clean()

        with self.assertRaises(RuntimeError):
            config._backupAndSetup(self._file(), in_chroot=False)

        self.assertEqual(self.manager.calls, [])

    # --- CsmakeServiceConfigManager.clean ---------------------------------

    def test_configManager_cleanCleansEveryConfigEvenWhenOneFails(self):
        manager = CSP.CsmakeServiceConfigManager(
            types.SimpleNamespace(log=self.log), None,
            options={'chroot': None, 'no-sudo': True})
        good1 = unittest.mock.Mock()
        bad = unittest.mock.Mock()
        bad.clean.side_effect = RuntimeError('boom')
        bad.filepath.return_value = '/etc/bad.conf'
        good2 = unittest.mock.Mock()
        manager.typeToObjs = {ConfigTypeA: [good1, bad], ConfigTypeB: [good2]}
        manager.activeDirs = {'/etc': [good1]}

        manager.clean()

        for config in (good1, bad, good2):
            config.clean.assert_called_once_with()
        self.assertEqual(manager.typeToObjs, {})
        self.assertEqual(manager.activeDirs, {})
        self.assertEqual(len(self.log.problems), 1)
        self.assertIn('ConfigTypeA', self.log.problems[0])
        self.assertIn('/etc/bad.conf', self.log.problems[0])

    # --- CsmakePortManager / CsmakeServiceProvider ------------------------

    def _patchCheckOutput(self, outcome):
        command = ('cat', '/proc/sys/net/ipv4/ip_local_port_range')
        fake = support.FakeCheckOutput({command: outcome})
        patch = unittest.mock.patch.object(
            CSP.subprocess, 'check_output', fake)
        patch.start()
        self.addCleanup(patch.stop)
        return fake

    def test_getUserPortRange_returnsTextParts(self):
        # check_output gives bytes; callers int() the parts and compare the
        # strings with str
        fake = self._patchCheckOutput(b'32768\t60999\n')

        ports = CSP.CsmakePortManager.getUserPortRange(self.log)

        self.assertEqual(ports, ['32768', '60999'])
        for port in ports:
            self.assertIsInstance(port, str)
        self.assertEqual(fake.calls, [(
            ['cat', '/proc/sys/net/ipv4/ip_local_port_range'], {})])

    def test_getUserPortRange_commandFailurePropagates(self):
        self._patchCheckOutput(support.called_process_error(['cat'], 1))

        with self.assertRaises(subprocess.CalledProcessError):
            CSP.CsmakePortManager.getUserPortRange(self.log)

    def _provider(self):
        with unittest.mock.patch.object(
                CSP.CsmakeServiceProvider, '_processOptions'):
            return CSP.CsmakeServiceProvider(
                types.SimpleNamespace(log=self.log), 'tag')

    def test_serviceProvider_init_usesTheKernelsEphemeralPortRange(self):
        self._patchCheckOutput(b'32768\t60999\n')

        provider = self._provider()

        self.assertEqual((provider.lowerport, provider.upperport),
                         (32768, 60999))

    def test_serviceProvider_init_fallsBackToDefaultPortsOnBadRange(self):
        for outcome in (support.called_process_error(['cat']),
                        b'', b'garbage\n', b'\xff\xfe\n'):
            with self.subTest(outcome=outcome):
                self._patchCheckOutput(outcome)

                provider = self._provider()

                self.assertEqual((provider.lowerport, provider.upperport),
                                 (20000, 24000))

    def _bindingSocket(self, busy):
        sock = unittest.mock.Mock()
        sock.bind.side_effect = [
            socket.error(errno.EADDRINUSE, 'in use') for _ in range(busy)
        ] + [None] * 5
        return sock

    def _findPort(self, start, stop, sock):
        patches = [
            unittest.mock.patch.object(CSP.socket, 'socket',
                                       return_value=sock),
            unittest.mock.patch.object(CSP.CsmakePortManager, '_lock',
                                       return_value=None)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return CSP.CsmakePortManager.findOpenTcpPort(
            '127.0.0.1', start, stop, self.log)

    def test_findOpenTcpPort_acceptsRangeGivenAsText(self):
        sock = self._bindingSocket(busy=1)

        port = self._findPort('38000', '38010', sock)

        self.assertEqual(port.port, 38001)
        self.assertEqual(
            [c[0][0] for c in sock.bind.call_args_list],
            [('127.0.0.1', 38000), ('127.0.0.1', 38001)])
        port.sock = None  # keep __del__ from closing the shared mock

    def test_findOpenTcpPort_returnsNoneWhenEveryPortIsBusy(self):
        sock = self._bindingSocket(busy=3)

        port = self._findPort(38000, 38002, sock)

        self.assertIsNone(port)
        self.assertEqual(sock.bind.call_count, 3)

    def _providerWith(self, port):
        provider = object.__new__(CSP.CsmakeServiceProvider)
        provider.service = unittest.mock.Mock()
        provider.module = types.SimpleNamespace(log=self.log)
        provider.options = {'port': port}
        return provider

    def test_endService_cleansUpAPortObject(self):
        port = unittest.mock.Mock()
        provider = self._providerWith(port)

        provider.endService()

        port.cleanup.assert_called_once_with()
        self.assertIsNone(provider.service)

    def test_endService_leavesAPortGivenAsTextAlone(self):
        # a str has no cleanup(); it was the basestring check, now str
        provider = self._providerWith('2222')

        provider.endService()

        self.assertEqual([], self.log.messages('debug'))
        self.assertIsNone(provider.service)

    def test_endService_portCleanupFailureIsOnlyLogged(self):
        port = unittest.mock.Mock()
        port.cleanup.side_effect = RuntimeError('socket gone')
        provider = self._providerWith(port)

        provider.endService()

        self.assertEqual(len(self.log.messages('debug')), 1)
        self.assertIn('socket gone', self.log.messages('debug')[0])


if __name__ == '__main__':
    unittest.main()
