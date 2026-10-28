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
"""Unit tests for the service lifecycle: HttpServiceDaemon, the
CsmakeServiceDaemon base class it runs on (start, serve, stop, error paths)
and CsmakeServiceProvider.startService / endService / the provider registry.

The stdlib HTTP server and the config manager are mocked, so nothing binds a
socket and no thread is started (run() is called directly).

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import types
import unittest
import unittest.mock

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

CSP = support.import_provider('CsmakeServiceProvider')
HSP = support.import_provider('HttpServiceProvider')


class ServiceTestCase(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.module = types.SimpleNamespace(log=self.log)

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock


class testHttpServiceDaemon_py3(ServiceTestCase):

    def setUp(self):
        ServiceTestCase.setUp(self)
        self.server_class = self._patch(HSP, 'VirtualHTTPServer')
        self.server = self.server_class.return_value
        self.port = object()

    def _daemon(self, **options):
        options.setdefault('port', self.port)
        options.setdefault('root-path', '/srv/www')
        options.setdefault('no-sudo', False)
        options.setdefault('chroot', None)
        self.options = options
        return HSP.HttpServiceDaemon(self.module, 'the-provider', options)

    def test_init_servesTheRootPathOnThePortWithTheVirtualPathHandler(self):
        daemon = self._daemon()

        self.server_class.assert_called_once_with(
            self.port, HSP.VirtualPathHTTPRequestHandler, daemon, '/srv/www')
        self.assertIs(daemon.server, self.server)
        self.assertIs(daemon.port, self.port)

    def test_init_cannotChrootWithoutSudo(self):
        with self.assertRaisesRegex(ValueError, 'no-sudo'):
            self._daemon(**{'no-sudo': True, 'chroot': '/srv/chroot'})

        self.assertEqual(len(self.log.messages('error')), 1)
        self.server_class.assert_not_called()

    def test_init_aServerThatCannotBindIsAnError(self):
        self.server_class.side_effect = OSError(98, 'Address already in use')

        with self.assertRaises(OSError):
            self._daemon()

    def test_listeningLoop_servesRequestsUntilTheServerIsShutDown(self):
        daemon = self._daemon()

        daemon._listeningLoop()

        self.server.serve_forever.assert_called_once_with()

    def test_stop_marksTheDaemonStoppingBeforeShuttingTheServerDown(self):
        daemon = self._daemon()
        seen = []
        self.server.shutdown.side_effect = lambda: seen.append(
            daemon.stopListening)

        daemon.stop()

        self.assertEqual(seen, [True])
        self.assertFalse(daemon.isExecuting())

    def test_stop_aServerThatFailsToShutDownIsAnError(self):
        daemon = self._daemon()
        self.server.shutdown.side_effect = RuntimeError('not serving')

        with self.assertRaises(RuntimeError):
            daemon.stop()

        self.assertTrue(daemon.stopListening)


class testServiceDaemonLifecycle_py3(ServiceTestCase):
    """CsmakeServiceDaemon.run() and friends, driven through HttpServiceDaemon
    with the stdlib server and the config manager mocked."""

    def setUp(self):
        ServiceTestCase.setUp(self)
        self.server_class = self._patch(HSP, 'VirtualHTTPServer')
        self.server = self.server_class.return_value
        self.options = {'port': object(), 'root-path': '/srv/www',
                        'no-sudo': False, 'chroot': None}
        self.daemon = HSP.HttpServiceDaemon(
            self.module, 'the-provider', self.options)
        self.daemon.cwd = '/work'
        self.config_class = unittest.mock.Mock(name='configManagerClass')
        self.config = self.config_class.return_value
        self.daemon.configManagerClass = self.config_class
        self.events = []
        # serving ends when the server is shut down, i.e. stop was asked for
        self.server.serve_forever.side_effect = self._serve

    def _serve(self):
        self.events.append(('serve', self.daemon.ready))
        self.daemon.stopListening = True

    def test_run_setsUpConfigsStartsServingThenCleansUp(self):
        self.daemon.run()

        self.config_class.assert_called_once_with(
            self.module, self.daemon, '/work', self.options)
        self.assertEqual(
            [c[0] for c in self.config.method_calls],
            ['ensure', 'start', 'stop'])
        self.assertEqual(self.events, [('serve', True)])  # ready beforehand
        self.assertTrue(self.daemon.ready)
        self.assertFalse(self.daemon.isExecuting())
        self.assertIsNone(self.daemon.exception)

    def test_run_aServerThatDiesOnItsOwnIsStillCleanedUp(self):
        self.server.serve_forever.side_effect = OSError('socket closed')

        with self.assertRaises(OSError):
            self.daemon.run()

        self.assertEqual(self.log.messages('exception')[0].split('\n')[0],
                         'The service failed to start: socket closed')
        self.assertIsInstance(self.daemon.exception, OSError)
        self.config.stop.assert_called_once_with()
        self.assertTrue(self.daemon.ready)
        self.assertFalse(self.daemon.isExecuting())

    def test_run_configsThatFailToSetUpReleaseWhoeverIsWaiting(self):
        self.config.ensure.side_effect = RuntimeError('cannot configure')

        with self.assertRaises(RuntimeError):
            self.daemon.run()

        self.server.serve_forever.assert_not_called()
        self.assertTrue(self.daemon.ready)
        self.daemon.waitUntilReady()   # does not block
        self.config.stop.assert_called_once_with()

    def test_run_aConfigManagerThatCannotBeCreatedHasNothingToStop(self):
        self.config_class.side_effect = RuntimeError('bad options')

        with self.assertRaises(RuntimeError):
            self.daemon.run()

        self.assertTrue(self.daemon.ready)
        self.assertIsNone(self.daemon.configManager)

    def test_run_cleanupHookRunsAfterServing(self):
        self.daemon._cleanup = unittest.mock.Mock(
            side_effect=lambda: self.events.append(('cleanup', None)))

        self.daemon.run()

        self.assertEqual([e[0] for e in self.events], ['serve', 'cleanup'])

    def test_run_stopRequestedWhileServingIsNotWaitedOn(self):
        # stopListening already True when serving returns: must not wait for
        # an ending notification that nobody will send
        self.daemon.endingCondition = unittest.mock.Mock()

        self.daemon.run()

        self.daemon.endingCondition.wait.assert_not_called()

    def test_waitUntilReady_blocksUntilTheServiceIsReady(self):
        condition = unittest.mock.Mock()
        self.daemon.readyCondition = condition

        self.daemon.waitUntilReady()

        condition.wait.assert_called_once_with()
        self.assertEqual(
            [c[0] for c in condition.method_calls],
            ['acquire', 'wait', 'release'])

    def test_waitUntilReady_returnsAtOnceOnceReady(self):
        self.daemon.ready = True
        condition = unittest.mock.Mock()
        self.daemon.readyCondition = condition

        self.daemon.waitUntilReady()

        condition.wait.assert_not_called()

    def test_stop_wakesWhoeverWaitsForTheEnd(self):
        condition = unittest.mock.Mock()
        self.daemon.endingCondition = condition

        self.daemon.stop()

        self.assertEqual(
            [c[0] for c in condition.method_calls],
            ['acquire', 'notify_all', 'release'])
        self.assertTrue(self.daemon.stopListening)

    def test_stopAndJoin_stopsThenWaitsForTheThread(self):
        self.daemon.join = unittest.mock.Mock(
            side_effect=lambda: self.events.append(
                ('join', self.daemon.stopListening)))

        self.daemon.stopAndJoin()

        self.assertEqual(self.events, [('join', True)])


class LifecycleProvider(CSP.CsmakeServiceProvider):
    serviceProviders = {}


class testServiceProviderLifecycle_py3(ServiceTestCase):

    def setUp(self):
        ServiceTestCase.setUp(self)
        LifecycleProvider.serviceProviders = {}
        self.addCleanup(setattr, LifecycleProvider, 'serviceProviders', {})
        self._patch(CSP.subprocess, 'check_output', support.FakeCheckOutput({
            ('cat', '/proc/sys/net/ipv4/ip_local_port_range'):
                b'32768\t60999\n'}))
        self.process = self._patch(LifecycleProvider, '_processOptions')

    def _provider(self):
        provider = LifecycleProvider.createServiceProvider('tag', self.module)
        provider.serviceClass = unittest.mock.Mock(name='serviceClass')
        return provider

    def test_createServiceProvider_makesOneProviderPerTag(self):
        first = LifecycleProvider.createServiceProvider(
            'tag', self.module, interfaces='localhost')
        again = LifecycleProvider.createServiceProvider('tag', self.module)
        other = LifecycleProvider.createServiceProvider('other', self.module)

        self.assertIs(first, again)
        self.assertIsNot(first, other)
        self.assertEqual(first.options, {'interfaces': 'localhost'})
        self.assertTrue(LifecycleProvider.hasServiceProvider('tag'))
        self.assertIs(LifecycleProvider.getServiceProvider('other'), other)
        self.assertIsNone(LifecycleProvider.getServiceProvider('nope'))
        self.assertFalse(LifecycleProvider.hasServiceProvider('nope'))

    def test_startService_startsTheServiceAndWaitsUntilItIsReady(self):
        provider = self._provider()

        service = provider.startService()

        provider.serviceClass.assert_called_once_with(
            self.module, provider, provider.options)
        self.assertIs(service, provider.serviceClass.return_value)
        self.assertEqual(
            [c[0] for c in service.method_calls], ['start', 'waitUntilReady'])

    def test_startService_aServiceAlreadyRunningIsOnlyWaitedFor(self):
        provider = self._provider()
        first = provider.startService()

        again = provider.startService()

        self.assertIs(again, first)
        provider.serviceClass.assert_called_once()
        first.start.assert_called_once_with()
        self.assertEqual(first.waitUntilReady.call_count, 2)

    def test_isServiceExecuting_asksTheServiceOnceItIsReady(self):
        provider = self._provider()
        self.assertFalse(provider.isServiceExecuting())
        service = provider.startService()
        service.isExecuting.return_value = True

        self.assertTrue(provider.isServiceExecuting())

    def test_disposeServiceProvider_endsTheServiceAndForgetsTheTag(self):
        provider = self._provider()
        service = provider.startService()

        LifecycleProvider.disposeServiceProvider('tag')

        service.stopAndJoin.assert_called_once_with()
        self.assertIsNone(provider.service)
        self.assertFalse(LifecycleProvider.hasServiceProvider('tag'))

    def test_disposeServiceProvider_anUnknownTagIsIgnored(self):
        LifecycleProvider.disposeServiceProvider('nope')

        self.assertFalse(LifecycleProvider.hasServiceProvider('nope'))

    def test_endService_withoutAServiceDoesNothing(self):
        provider = self._provider()

        self.assertIsNone(provider.endService())


class testHttpServiceProvider_py3(ServiceTestCase):

    def test_theProviderRunsAnHttpServiceDaemon(self):
        self._patch(CSP.subprocess, 'check_output', support.FakeCheckOutput({
            ('cat', '/proc/sys/net/ipv4/ip_local_port_range'):
                b'32768\t60999\n'}))
        self._patch(HSP.HttpServiceProvider, '_processOptions')

        provider = HSP.HttpServiceProvider(self.module, 'tag', port='8080')

        self.assertIs(provider.serviceClass, HSP.HttpServiceDaemon)
        self.assertEqual(provider.options, {'port': '8080'})
        self.assertEqual((provider.lowerport, provider.upperport),
                         (32768, 60999))
        self.assertEqual(HSP.HttpServiceProvider.serviceProviders, {})


if __name__ == '__main__':
    unittest.main()
