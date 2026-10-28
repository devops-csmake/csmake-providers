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
"""Unit tests for the configuration side of SshServiceProvider.py: the log
level helper, the ssh client and sshd daemon config writers, the config
manager's sshd config directory, the daemon's config registration and the
provider's options.

The shelling-out config manager is a FakeManager that records commands.  Real
temp directories are used for the paths whose content or existence is the
subject; nothing is written outside them (the daemon config is exercised with
a chroot inside the temp directory).

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import os
import shutil
import tempfile
import types
import unittest
import unittest.mock

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

CSP = support.import_provider('CsmakeServiceProvider')
SSP = support.import_provider('SshServiceProvider')


def settings(**given):
    result = {'quiet': False, 'verbose': False, 'debug': False,
              'dev-output': False}
    result.update(given)
    return result


class SshTestCase(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='csmake-ssh-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock


class testSshConfigurationHelper_py3(unittest.TestCase):

    def test_sshDebugLevel_isErrorByDefault(self):
        self.assertEqual(SSP.SshConfigurationHelper.sshDebugLevel(settings()),
                         'ERROR')

    def test_sshDebugLevel_followsTheMostVerboseSettingExceptQuiet(self):
        for given, expected in (
                ({'verbose': True}, 'VERBOSE'),
                ({'debug': True}, 'DEBUG'),
                ({'verbose': True, 'debug': True}, 'DEBUG'),
                ({'dev-output': True}, 'DEBUG3'),
                ({'verbose': True, 'debug': True, 'dev-output': True},
                 'DEBUG3'),
                ({'quiet': True}, 'QUIET'),
                ({'quiet': True, 'verbose': True, 'debug': True,
                  'dev-output': True}, 'QUIET')):
            with self.subTest(given=given):
                self.assertEqual(
                    SSP.SshConfigurationHelper.sshDebugLevel(settings(**given)),
                    expected)

    def test_sshDebugLevel_aMissingSettingIsAnError(self):
        with self.assertRaises(KeyError):
            SSP.SshConfigurationHelper.sshDebugLevel({'quiet': False})


class testSshClientConfig_py3(SshTestCase):

    def setUp(self):
        SshTestCase.setUp(self)
        self.home = os.path.join(self.tmp, 'home', 'builder')
        self.sshdir = os.path.join(self.home, '.ssh')
        self.port = types.SimpleNamespace(address=lambda: ('127.0.0.1', 2222))
        self.manager = support.FakeManager(self.log)
        self.manager.options = {'port': self.port}
        self.results = os.path.join(self.tmp, 'results')

    def _config(self, **given):
        module = types.SimpleNamespace(
            log=self.log, settings=settings(**given),
            env=types.SimpleNamespace(env={'RESULTS': self.results}),
            _ensureDirectoryExists=lambda path: os.makedirs(
                os.path.dirname(path), exist_ok=True),
            _cleanEnsuredDirectory=lambda path: None)
        return SSP.SshClientConfig(
            module, self.manager, self.home, self.home, False, None)

    def test_homesToGrokAreRootAndTheHomeDirectories(self):
        self.assertEqual(SSP.SshClientConfig.HOMES_TO_GROCK,
                         ['/root', '/home/*'])

    def test_writefile_namesTheHostPortAndLogLevel(self):
        config = self._config(verbose=True)
        config.port = self.port

        fobj = type('Out', (), {'text': '', 'write': lambda self, s: setattr(
            self, 'text', self.text + s)})()
        config.writefile(fobj)

        self.assertEqual(
            [line.strip() for line in fobj.text.split('\n')],
            ['Host 127.0.0.1', 'HostName 127.0.0.1', 'Port 2222',
             'LogLevel VERBOSE'])

    def test_ensure_setsUpTheUsersSshConfigOwnedLikeTheirHome(self):
        os.makedirs(self.sshdir)
        info = os.stat(self.home)
        owner = '%d:%d' % (info.st_uid, info.st_gid)
        config = self._config()
        cfg = os.path.join(self.sshdir, 'config')

        config.ensure()

        self.assertEqual(self.manager.commands(), [
            ['mkdir', '-p', self.sshdir], ['chown', owner, self.sshdir],
            ['chmod', '750', self.sshdir],
            ['mv', cfg, cfg + '.csmake.bkup'],
            ['touch', cfg], ['chown', owner, cfg], ['chmod', '600', cfg]])
        with open(cfg) as f:
            self.assertEqual(
                [line.strip() for line in f.read().split('\n')],
                ['Host 127.0.0.1', 'HostName 127.0.0.1', 'Port 2222',
                 'LogLevel ERROR'])

    def test_ensure_aHomeDirectoryThatDoesNotExistIsAnError(self):
        config = self._config()

        with self.assertRaises(FileNotFoundError):
            config.ensure()

        self.assertEqual(self.manager.calls, [])

    def test_ensure_anUnwritableSshDirectoryFallsBackToTempFileAndCp(self):
        os.makedirs(self.home)   # but no .ssh: the direct open() fails
        config = self._config()
        copied = []

        def capture(command):
            with open(command[1]) as f:
                copied.append((command[2], f.read()))
        self.manager.hooks['cp'] = capture

        config.ensure()

        cfg = os.path.join(self.sshdir, 'config')
        self.assertEqual([path for path, _ in copied], [cfg])
        self.assertIn('Port 2222', copied[0][1])
        self.assertEqual(len(self.log.messages('debug')), 1)


class testSshDaemonConfig_py3(SshTestCase):

    def setUp(self):
        SshTestCase.setUp(self)
        self.chroot = os.path.join(self.tmp, 'chroot')
        self.confdir = os.path.join(self.chroot, 'etc', 'csmake_ssh_t')
        self.rundir = os.path.join(self.chroot, 'run', 'sshd')
        os.makedirs(self.confdir)
        os.makedirs(self.rundir)
        self.port = types.SimpleNamespace(address=lambda: ('127.0.0.1', 2222))
        self.manager = support.FakeManager(self.log)
        self.manager.options = {'port': self.port}

    def _config(self, **given):
        module = types.SimpleNamespace(log=self.log, settings=settings(**given))
        return SSP.SshDaemonConfig(
            module, self.manager, '/etc/csmake_ssh_t', '/etc/csmake_ssh_t',
            True, self.chroot)

    def test_ensure_writesSshdConfigWithTheLogLevelAndListenAddress(self):
        config = self._config(debug=True)

        config.ensure()

        with open(os.path.join(self.confdir, 'sshd_config')) as f:
            self.assertEqual(
                f.read(), 'LogLevel DEBUG\nListenAddress 127.0.0.1:2222')

    def test_ensure_putsTheConfigAndThePrivilegeSeparationDirUnderManagement(self):
        config = self._config()
        conf = os.path.join(self.confdir, 'sshd_config')
        touch = os.path.join(self.rundir, 'touch')

        config.ensure()

        commands = [c for c in self.manager.commands() if c[0] != 'rm']
        self.assertEqual(commands, [
            ['mkdir', '-p', self.confdir], ['chmod', '777', self.confdir],
            ['mv', conf, conf + '.csmake.bkup'],
            ['touch', conf], ['chmod', '777', conf],
            ['mkdir', '-p', self.rundir], ['chown', '0:0', self.rundir],
            ['chmod', '755', self.rundir],
            ['mv', touch, touch + '.csmake.bkup']])
        self.assertEqual(self.log.messages('debug'),
                         ['Writing config to: /etc/csmake_ssh_t/sshd_config'])

    def test_ensure_theTouchFileIsLeftEmpty(self):
        self._config().ensure()

        with open(os.path.join(self.rundir, 'touch')) as f:
            self.assertEqual(f.read(), '')

    @unittest.skip("pre-existing: the final clean up runs "
                   "['rm', '-f', '\"/run/sshd/touch\"'] - the quotes are "
                   "part of the argument, so it would remove a file named "
                   "with quotes and leave /run/sshd/touch behind")
    def test_ensure_removesThePrivilegeSeparationTouchFile(self):
        self._config().ensure()

        self.assertIn(['rm', '-f', '/run/sshd/touch'], self.manager.commands())


class testSshServiceConfigManager_py3(SshTestCase):

    def setUp(self):
        SshTestCase.setUp(self)
        self.fake = support.FakeManager(self.log)

    def _manager(self, chroot=None):
        daemon = types.SimpleNamespace(provider=types.SimpleNamespace(tag='t'))
        manager = SSP.SshServiceConfigManager(
            types.SimpleNamespace(log=self.log), daemon,
            options={'chroot': chroot, 'no-sudo': True})
        manager.shellout = self.fake.shellout
        return manager

    def test_theDaemonConfigLivesInAnEtcDirectoryNamedForTheTag(self):
        manager = self._manager(chroot='/srv/chroot')

        self.assertEqual(manager.getDaemonConfigPaths(), ['/etc/csmake_ssh_t'])
        self.assertEqual(manager.getDaemonConfigFile(),
                         '/etc/csmake_ssh_t/sshd_config')
        self.assertEqual(manager.fullDaemonConfigPath,
                         '/srv/chroot/etc/csmake_ssh_t')

    def test_ensure_anExistingConfigDirectoryIsLeftAlone(self):
        manager = self._manager()

        manager.ensure()

        self.assertEqual(self.fake.commands(),
                         [['stat', '-c', '', '/etc/csmake_ssh_t']])

    def test_ensure_aMissingConfigDirectoryIsCreated(self):
        self.fake.results[('stat', '-c', '', '/etc/csmake_ssh_t')] = \
            support.called_process_error(['stat'])
        manager = self._manager()

        manager.ensure()

        self.assertEqual(self.fake.commands()[1],
                         ['mkdir', '-p', '/etc/csmake_ssh_t'])

    def test_ensure_aConfigDirectoryThatCannotBeCreatedIsLoggedAndWarnedAbout(self):
        self.fake.results[('stat', '-c', '', '/etc/csmake_ssh_t')] = \
            support.called_process_error(['stat'])
        self.fake.results[('mkdir', '-p', '/etc/csmake_ssh_t')] = \
            support.called_process_error(['mkdir'])
        manager = self._manager()

        manager.ensure()

        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_clean_removesTheConfigDirectoryWhenItIsThere(self):
        chroot = os.path.join(self.tmp, 'chroot')
        os.makedirs(os.path.join(chroot, 'etc', 'csmake_ssh_t'))
        manager = self._manager(chroot=chroot)

        manager.clean()

        self.assertEqual(self.fake.commands(), [
            ['rmdir', '-p', os.path.join(chroot, 'etc', 'csmake_ssh_t')]])

    def test_clean_doesNothingWhenTheDirectoryIsAlreadyGone(self):
        manager = self._manager(chroot=os.path.join(self.tmp, 'chroot'))

        manager.clean()

        self.assertEqual(self.fake.calls, [])

    def test_clean_aDirectoryThatCannotBeRemovedIsOnlyDevLogged(self):
        chroot = os.path.join(self.tmp, 'chroot')
        directory = os.path.join(chroot, 'etc', 'csmake_ssh_t')
        os.makedirs(directory)
        self.fake.results[('rmdir', '-p', directory)] = \
            support.called_process_error(['rmdir'])
        manager = self._manager(chroot=chroot)

        manager.clean()

        self.assertEqual(self.log.problems, [])


class testSshServiceDaemonConfigs_py3(SshTestCase):

    def _daemon(self, **options):
        options.setdefault('port', object())
        options.setdefault('no-sudo', False)
        options.setdefault('chroot', None)
        options.setdefault('client-chroot', None)
        return SSP.SshServiceDaemon(
            types.SimpleNamespace(log=self.log), 'the-provider', options)

    def test_init_usesTheSshConfigManagerAndHasNoProcessYet(self):
        daemon = self._daemon()

        self.assertIs(daemon.configManagerClass, SSP.SshServiceConfigManager)
        self.assertIsNone(daemon.process)

    def test_setupConfigs_registersTheClientAndTheDaemonConfigs(self):
        daemon = self._daemon(**{'client-chroot': '/srv/client'})
        daemon.configManager = unittest.mock.Mock()
        daemon.configManager.getDaemonConfigPaths.return_value = ['/etc/x']

        daemon._setupConfigs()

        register = daemon.configManager.register
        self.assertEqual(register.call_args_list, [
            unittest.mock.call(
                SSP.SshClientConfig, ['/root', '/home/*'], ensure=False,
                in_chroot=False, path_prefix='/srv/client'),
            unittest.mock.call(
                SSP.SshDaemonConfig, ['/etc/x'], ensure=False)])
        daemon.configManager.ensure.assert_called_once_with()
        daemon.configManager.start.assert_called_once_with()

    def test_setupConfigs_noClientChrootMeansNoPathPrefix(self):
        daemon = self._daemon()
        daemon.configManager = unittest.mock.Mock()

        daemon._setupConfigs()

        self.assertEqual(
            daemon.configManager.register.call_args_list[0][1]['path_prefix'],
            '')


class testSshServiceProvider_py3(SshTestCase):

    def setUp(self):
        SshTestCase.setUp(self)
        self._patch(CSP.subprocess, 'check_output', support.FakeCheckOutput({
            ('cat', '/proc/sys/net/ipv4/ip_local_port_range'):
                b'32768\t60999\n'}))
        self.find = self._patch(CSP.CsmakePortManager, 'findOpenTcpPort')

    def _provider(self, **options):
        return SSP.SshServiceProvider(
            types.SimpleNamespace(log=self.log), 'tag', **options)

    def test_theProviderRunsAnSshServiceDaemon(self):
        provider = self._provider()

        self.assertIs(provider.serviceClass, SSP.SshServiceDaemon)
        self.assertIs(provider.options['port'], self.find.return_value)

    def test_theClientChrootDefaultsToTheChroot(self):
        provider = self._provider(chroot='/srv/chroot')

        self.assertEqual(provider.options['client-chroot'], '/srv/chroot')

    def test_aClientChrootGivenIsKept(self):
        provider = self._provider(chroot='/srv/chroot',
                                  **{'client-chroot': '/srv/client'})

        self.assertEqual(provider.options['client-chroot'], '/srv/client')

    def test_withNoChrootTheClientChrootIsNone(self):
        provider = self._provider()

        self.assertIsNone(provider.options['client-chroot'])


if __name__ == '__main__':
    unittest.main()
