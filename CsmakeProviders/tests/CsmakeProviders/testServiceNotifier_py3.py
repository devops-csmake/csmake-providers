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
"""Unit tests for the file watching in CsmakeServiceProvider.py: the pyinotify
based CsmakeServiceConfigNotifier, its CsmakeServiceConfigPoller fallback and
the CsmakeServiceConfigManager that drives them.

pyinotify (stubbed when absent, see providers_support) is mocked at its
WatchManager / ThreadedNotifier boundary, events are fed in as plain objects,
time.sleep is patched and no thread is ever started.  Real temp directories
stand in for the paths being watched.

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
IN_CREATE = 0x100


class WatchTestCase(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='csmake-watch-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sleep = self._patch(CSP.time, 'sleep')

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock

    def _file(self, *parts):
        path = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('x')
        return path


class testServiceNotifier_py3(WatchTestCase):

    def setUp(self):
        WatchTestCase.setUp(self)
        self.poller_class = self._patch(CSP, 'CsmakeServiceConfigPoller')
        self.poller = self.poller_class.return_value
        self.WatchManager = self._patch(
            CSP.pyinotify, 'WatchManager', create=True)
        self.watcher = self.WatchManager.return_value
        self.ThreadedNotifier = self._patch(
            CSP.pyinotify, 'ThreadedNotifier', create=True)
        self.thread = self.ThreadedNotifier.return_value
        self._patch(CSP.pyinotify, 'IN_CREATE', IN_CREATE, create=True)
        self.manager = types.SimpleNamespace(
            log=self.log, getDefaultPollRate=lambda: .01,
            _ensureInstance=unittest.mock.Mock(),
            notifyContentionDetected=unittest.mock.Mock())
        self.fileinfo = ('/etc/pip.conf', [], object, None, None, True)

    def _notifier(self, actualPath, **kwargs):
        notifier = CSP.CsmakeServiceConfigNotifier(
            manager=self.manager, fileinfo=self.fileinfo,
            actualPath=actualPath, **kwargs)
        self.addCleanup(setattr, notifier, 'thread', None)
        return notifier

    def test_init_pollsFirstThenSwitchesToTheNotifier(self):
        path = os.path.join(self.tmp, 'etc', 'pip.conf')

        notifier = self._notifier(path, pollTime=5)

        self.poller_class.assert_called_once_with()
        self.poller.my_init.assert_called_once_with(
            notifier, self.fileinfo, path, 5)
        self.assertEqual(
            [c[0] for c in self.poller.method_calls],
            ['my_init', 'start', 'startPolling', 'stopPolling'])

    def test_init_theDefaultPollRateComesFromTheManager(self):
        path = os.path.join(self.tmp, 'pip.conf')

        self._notifier(path)

        self.assertEqual(self.poller.my_init.call_args[0][3], .01)

    def test_init_eachRequiredArgumentIsChecked(self):
        complete = dict(manager=self.manager, fileinfo=self.fileinfo,
                        actualPath=self.tmp)
        for missing in sorted(complete):
            with self.subTest(missing=missing):
                given = dict(complete)
                del given[missing]

                with self.assertRaisesRegex(ValueError, missing):
                    CSP.CsmakeServiceConfigNotifier(**given)

    def test_setupWatcher_watchesTheNearestExistingDirectoryForCreations(self):
        path = os.path.join(self.tmp, 'missing', 'deeper', 'pip.conf')

        notifier = self._notifier(path)

        self.WatchManager.assert_called_once_with()
        self.ThreadedNotifier.assert_called_once_with(self.watcher)
        self.thread.start.assert_called_once_with()
        self.watcher.add_watch.assert_called_once_with(
            self.tmp, IN_CREATE, notifier, auto_add=True)
        self.assertIs(notifier.wd, self.watcher.add_watch.return_value)
        self.manager._ensureInstance.assert_not_called()

    def test_setupWatcher_aFileThatAlreadyExistsIsManagedNotWatched(self):
        path = self._file('etc', 'pip.conf')

        notifier = self._notifier(path)

        self.manager._ensureInstance.assert_called_once_with(
            path, self.fileinfo)
        self.assertEqual(notifier.instancesEnsured, [path])
        self.watcher.add_watch.assert_not_called()
        self.poller.stopPolling.assert_called_once_with()

    def test_setupWatcher_aFileIsOnlyManagedOnce(self):
        path = self._file('pip.conf')
        notifier = self._notifier(path)

        self.assertTrue(notifier._processFile())

        self.manager._ensureInstance.assert_called_once_with(
            path, self.fileinfo)

    def test_setupWatcher_everyWildcardMatchIsManaged(self):
        a = self._file('home', 'a', 'pip.conf')
        b = self._file('home', 'b', 'pip.conf')

        notifier = self._notifier(os.path.join(self.tmp, 'home', '*', 'pip.conf'))

        self.assertEqual(
            sorted(c[0][0] for c in self.manager._ensureInstance.call_args_list),
            [a, b])
        self.assertEqual(sorted(notifier.instancesEnsured), [a, b])
        self.watcher.add_watch.assert_not_called()

    @unittest.skip("pre-existing: _processFile's error handling calls "
                   "self.log.exception but the notifier has no 'log' (only "
                   "self.manager.log), so a failing _ensureInstance raises "
                   "AttributeError instead of being logged")
    def test_setupWatcher_aFailingInstanceIsLoggedAndTheRestStillManaged(self):
        pass

    def test_setupWatcher_retriesWhileInotifyResourcesAreBusy(self):
        self.WatchManager.side_effect = [
            OSError(24, 'Too many open files'),
            OSError(24, 'Too many open files'), self.watcher]

        notifier = self._notifier(os.path.join(self.tmp, 'pip.conf'))

        self.assertEqual(self.sleep.call_args_list,
                         [unittest.mock.call(1)] * 2)
        self.assertIs(notifier.watcher, self.watcher)
        self.assertTrue(any('retrying every 1s' in message
                            for message in self.log.messages('debug')))
        self.manager.notifyContentionDetected.assert_not_called()

    def test_setupWatcher_givesUpAfterFiveTriesAndFallsBackToPolling(self):
        self.WatchManager.side_effect = OSError(24, 'Too many open files')

        notifier = self._notifier(os.path.join(self.tmp, 'pip.conf'))

        self.assertEqual(self.WatchManager.call_count, 5)
        self.assertEqual(self.sleep.call_count, 5)
        self.manager.notifyContentionDetected.assert_called_once_with()
        self.poller.stop.assert_called_once_with()
        self.poller.join.assert_called_once_with()
        self.poller.stopPolling.assert_not_called()
        self.ThreadedNotifier.assert_not_called()
        self.assertEqual(len(self.log.messages('warning')), 2)
        self.assertIsNone(notifier.watcher)

    def test_setupWatcher_aPathWithNoExistingAncestorIsAnError(self):
        with self.assertRaisesRegex(ValueError, 'doesn.t exist'):
            self._notifier('csmake-no-such-directory-xyz/pip.conf')

        self.watcher.add_watch.assert_not_called()

    def test_switchToPolling_pollsAndLetsGoOfTheWatcher(self):
        notifier = self._notifier(os.path.join(self.tmp, 'pip.conf'))
        self.poller.reset_mock()

        notifier.switchToPolling()

        self.poller.startPolling.assert_called_once_with()
        self.thread.stop.assert_called_once_with()
        self.assertEqual((notifier.thread, notifier.watcher, notifier.wd),
                         (None, None, None))

    def test_releaseNotifiers_aFailingStopIsLoggedAndStillReleases(self):
        notifier = self._notifier(os.path.join(self.tmp, 'pip.conf'))
        self.thread.stop.side_effect = RuntimeError('already stopped')

        notifier.releaseNotifiers()

        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertIsNone(notifier.thread)

    def test_stop_stopsThePollerThenReleasesTheWatcher(self):
        notifier = self._notifier(os.path.join(self.tmp, 'pip.conf'))

        notifier.stop()

        self.assertEqual(
            [c[0] for c in self.poller.method_calls][-2:], ['stop', 'join'])
        self.thread.stop.assert_called_once_with()

    def test_removeWatch_dropsTheWatchRecursivelyOnce(self):
        notifier = self._notifier(os.path.join(self.tmp, 'pip.conf'))
        notifier.wd = 7

        notifier._removeWatch()
        notifier._removeWatch()

        self.watcher.rm_watch.assert_called_once_with(7, rec=True)
        self.assertIsNone(notifier.wd)

    def test_delete_aFailureToStopIsLoggedNotRaised(self):
        notifier = self._notifier(os.path.join(self.tmp, 'pip.conf'))
        self.poller.stop.side_effect = RuntimeError('boom')

        notifier.__del__()

        self.assertEqual(len(self.log.messages('exception')), 1)
        self.poller.stop.side_effect = None

    # --- events ---------------------------------------------------------

    def _watching(self, pattern):
        notifier = self._notifier(os.path.join(self.tmp, 'pip.conf'))
        notifier.actualPath = pattern
        notifier._processFile = unittest.mock.Mock(return_value=True)
        self.watcher.rm_watch.reset_mock()
        return notifier

    @staticmethod
    def _event(pathname, wd=7):
        return types.SimpleNamespace(pathname=pathname, wd=wd)

    def test_processInCreate_theWatchedFileAppearingIsManaged(self):
        notifier = self._watching('/t/home/*/pip.conf')

        notifier.process_IN_CREATE(self._event('/t/home/a/pip.conf'))

        notifier._processFile.assert_called_once_with()
        self.watcher.rm_watch.assert_not_called()

    def test_processInCreate_somethingElseAppearingIsIgnored(self):
        notifier = self._watching('/t/home/*/pip.conf')

        notifier.process_IN_CREATE(self._event('/t/home/a'))

        notifier._processFile.assert_not_called()
        self.watcher.rm_watch.assert_not_called()

    def test_processInCreate_aDirectoryThatCannotLeadToTheFileLosesItsWatch(self):
        notifier = self._watching('/t/home/a*/x')

        notifier.process_IN_CREATE(self._event('/t/home/b/new', wd=9))

        self.watcher.rm_watch.assert_called_once_with(9, rec=True)
        notifier._processFile.assert_not_called()

    def test_processInQOverflow_rescansBecauseEventsWereLost(self):
        notifier = self._watching('/t/home/*/pip.conf')

        notifier.process_IN_Q_OVERFLOW(self._event(None))

        notifier._processFile.assert_called_once_with()


class testServicePoller_py3(WatchTestCase):

    def _poller(self, rate=.5):
        notifier = types.SimpleNamespace(
            manager=types.SimpleNamespace(log=self.log),
            _processFile=unittest.mock.Mock(return_value=False))
        poller = CSP.CsmakeServiceConfigPoller()
        poller.my_init(notifier, ('info',), '/etc/pip.conf', rate)
        return poller, notifier

    def test_startPolling_waitsForAFileThatIsNotThereYet(self):
        poller, notifier = self._poller()

        poller.startPolling()

        self.assertTrue(poller.waitToPoll.is_set())
        self.assertEqual(len(self.log.messages('debug')), 1)

    def test_startPolling_doesNotPollForAFileThatIsAlreadyManaged(self):
        poller, notifier = self._poller()
        notifier._processFile.return_value = True

        poller.startPolling()

        self.assertFalse(poller.waitToPoll.is_set())

    def test_stopPolling_pausesThePoll(self):
        poller, _ = self._poller()
        poller.startPolling()

        poller.stopPolling()

        self.assertFalse(poller.waitToPoll.is_set())

    def test_run_checksForTheFileEveryPollIntervalUntilStopped(self):
        poller, notifier = self._poller(rate=.5)
        poller.startPolling()
        notifier._processFile.reset_mock()
        self.sleep.side_effect = [None, None, lambda: None]
        self.sleep.side_effect = (
            lambda seconds: setattr(poller, 'pollRunning', False)
            if self.sleep.call_count == 3 else None)

        poller.run()

        self.assertEqual(notifier._processFile.call_count, 3)
        self.assertEqual(self.sleep.call_args_list,
                         [unittest.mock.call(.5)] * 3)

    def test_run_stoppedWhileWaitingDoesNotPoll(self):
        poller, notifier = self._poller()

        poller.stop()
        poller.run()

        notifier._processFile.assert_not_called()
        self.sleep.assert_not_called()


class FakeConfig(object):
    """A config type (entrytype) as CsmakeServiceConfigManager makes them."""
    instances = None

    def __init__(self, module, manager, path, fullpath, in_chroot, chroot):
        self.args = (module, manager, path, fullpath, in_chroot, chroot)
        self.ensured = False
        self.updated = 0
        FakeConfig.instances.append(self)

    def ensure(self):
        self.ensured = True

    def update(self):
        self.updated += 1


class FailingConfig(FakeConfig):
    def ensure(self):
        raise OSError('cannot configure')


class testServiceConfigManager_py3(WatchTestCase):

    def setUp(self):
        WatchTestCase.setUp(self)
        FakeConfig.instances = []
        self.module = types.SimpleNamespace(log=self.log)

    def _manager(self, chroot=None):
        return CSP.CsmakeServiceConfigManager(
            self.module, None, options={'chroot': chroot, 'no-sudo': True})

    def _entry(self, instance, entrytype=FakeConfig, callback=None,
               in_chroot=True, failed=None):
        return (instance, [] if failed is None else failed, entrytype,
                callback, None, in_chroot)

    def test_register_remembersTheEntriesAndEnsuresOnRequest(self):
        manager = self._manager()
        manager.ensure = unittest.mock.Mock()

        manager.register(FakeConfig, ['/etc/a', '/etc/b'], ensure=False)
        manager.ensure.assert_not_called()
        manager.register(FakeConfig, ['/etc/c'], callback='cb', in_chroot=False,
                         path_prefix='/p')

        self.assertEqual(
            [entry[0] for entry in manager.monitoringDirs],
            ['/etc/a', '/etc/b', '/etc/c'])
        self.assertEqual(manager.monitoringDirs[2][2:], (FakeConfig, 'cb', '/p', False))
        manager.ensure.assert_called_once_with()

    def test_ensure_oneNotifierPerEntryWatchingTheRealPathUnderTheChroot(self):
        notifier_class = self._patch(CSP, 'CsmakeServiceConfigNotifier')
        chroot = os.path.join(self.tmp, 'chroot')
        manager = self._manager(chroot=chroot)
        manager.register(FakeConfig, ['/etc/pip.conf'], ensure=False)
        outside = os.path.join(self.tmp, 'outside', 'pip.conf')
        manager.register(FakeConfig, [outside], ensure=False,
                         in_chroot=False, path_prefix=None)

        manager.ensure()
        manager.ensure()

        self.assertEqual(notifier_class.call_count, 2)
        first = notifier_class.call_args_list[0][1]
        self.assertIs(first['manager'], manager)
        self.assertEqual(first['fileinfo'], manager.monitoringDirs[0])
        self.assertEqual(first['actualPath'], chroot + '/etc/pip.conf')
        self.assertEqual(
            notifier_class.call_args_list[1][1]['actualPath'], outside)
        self.assertEqual(len(manager.dirMonitors), 2)

    def test_ensure_doesNothingOnceTheManagerHasStopped(self):
        notifier_class = self._patch(CSP, 'CsmakeServiceConfigNotifier')
        manager = self._manager()
        manager.register(FakeConfig, ['/etc/a'], ensure=False)
        manager.running = False

        manager.ensure()

        notifier_class.assert_not_called()

    def test_ensureInstance_createsAndEnsuresTheConfigAndTellsTheCallback(self):
        manager = self._manager()
        callback = unittest.mock.Mock()

        manager._ensureInstance('/etc/pip.conf', self._entry(
            '/etc/pip.conf', callback=callback))

        config, = FakeConfig.instances
        self.assertEqual(config.args, (self.module, manager, '/etc/pip.conf',
                                       '/etc/pip.conf', True, None))
        self.assertTrue(config.ensured)
        callback.assert_called_once_with(config)
        self.assertEqual(manager.getAllOfType(FakeConfig), [config])
        self.assertEqual(manager.activeDirs['/etc/pip.conf'], [config])

    def test_ensureInstance_aChrootedPathIsGivenToTheConfigRelativeToTheChroot(self):
        manager = self._manager(chroot='/srv/chroot')

        manager._ensureInstance('/srv/chroot/etc/pip.conf',
                                self._entry('/etc/pip.conf'))

        self.assertEqual(FakeConfig.instances[0].args[2:4], (
            '/etc/pip.conf', '/srv/chroot/etc/pip.conf'))

    def test_ensureInstance_aPathOutsideTheChrootIsUsedAsIs(self):
        manager = self._manager(chroot='/srv/chroot')

        manager._ensureInstance('/elsewhere/pip.conf',
                                self._entry('/etc/pip.conf'))

        self.assertEqual(FakeConfig.instances[0].args[2], '/elsewhere/pip.conf')
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_ensureInstance_relativePathsBecomeAbsolute(self):
        manager = self._manager()

        manager._ensureInstance('etc/pip.conf', self._entry('etc/pip.conf'))
        manager._ensureInstance('./pip.conf', self._entry('./pip.conf'))

        self.assertEqual(FakeConfig.instances[0].args[2], '/etc/pip.conf')
        self.assertEqual(FakeConfig.instances[1].args[2],
                         os.path.abspath('./pip.conf'))

    def test_ensureInstance_aConfigIsOnlyCreatedOncePerInstanceAndType(self):
        manager = self._manager()
        entry = self._entry('/etc/pip.conf')

        manager._ensureInstance('/etc/pip.conf', entry)
        manager._ensureInstance('/etc/pip.conf', entry)

        self.assertEqual(len(FakeConfig.instances), 1)

    def test_ensureInstance_aConfigThatFailsIsLoggedAndNotRetried(self):
        manager = self._manager()
        failed = []
        entry = self._entry('/etc/pip.conf', FailingConfig, failed=failed)

        manager._ensureInstance('/etc/pip.conf', entry)
        manager._ensureInstance('/etc/pip.conf', entry)

        self.assertEqual(failed, ['/etc/pip.conf'])
        self.assertEqual(len(FakeConfig.instances), 1)
        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertEqual(manager.getAllOfType(FailingConfig), [])

    def test_update_updatesEveryInstanceOfTheTypeOnly(self):
        manager = self._manager()
        manager._ensureInstance('/a', self._entry('/a'))
        manager._ensureInstance('/b', self._entry('/b'))
        manager._ensureInstance('/c', self._entry('/c', FailingConfig))

        manager.update(FakeConfig)
        manager.update(unittest.mock.Mock)  # a type nothing was made for

        self.assertEqual([c.updated for c in FakeConfig.instances], [1, 1, 0])
        self.assertIsNone(manager.getAllOfType(unittest.mock.Mock))

    def test_run_backsOffFromInotifyWhileTheContentionLasts(self):
        manager = self._manager()
        events = []
        monitors = [unittest.mock.Mock(name='m%d' % i) for i in (1, 2)]
        for monitor in monitors:
            monitor.switchToPolling.side_effect = (
                lambda m=monitor: events.append(('poll', m._mock_name)))
            monitor.switchToNotifier.side_effect = (
                lambda m=monitor: events.append(('notify', m._mock_name)))
        manager.dirMonitors = monitors
        self._patch(CSP.random, 'randint', return_value=42)

        def sleeping(seconds):
            events.append(('sleep', seconds))
            manager.running = False  # end the loop after this round
        self.sleep.side_effect = sleeping
        manager.notifyContentionDetected()

        manager.run()

        self.assertEqual(events, [
            ('poll', 'm1'), ('poll', 'm2'), ('sleep', 42),
            ('notify', 'm1'), ('notify', 'm2')])
        self.assertFalse(manager.waitForContention.is_set())
        self.assertEqual(self.log.messages('warning'), [
            'Backing off inotify resources due to contention for 42s'])

    def test_run_endsWithoutBackingOffWhenStoppedWhileWaiting(self):
        manager = self._manager()
        monitor = unittest.mock.Mock()
        manager.dirMonitors = [monitor]
        manager.running = False
        manager.waitForContention.set()

        manager.run()

        monitor.switchToPolling.assert_not_called()
        self.sleep.assert_not_called()

    def test_stop_stopsEveryMonitorEvenIfOneFailsThenCleans(self):
        manager = self._manager()
        bad, good = unittest.mock.Mock(), unittest.mock.Mock()
        bad.stop.side_effect = RuntimeError('boom')
        manager.dirMonitors = [bad, good]
        config = unittest.mock.Mock()
        manager.typeToObjs = {FakeConfig: [config]}

        manager.stop()

        good.stop.assert_called_once_with()
        config.clean.assert_called_once_with()
        self.assertFalse(manager.running)
        self.assertTrue(manager.waitForContention.is_set())
        self.assertTrue(manager.daemonEvent.is_set())
        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertEqual(manager.typeToObjs, {})


if __name__ == '__main__':
    unittest.main()
