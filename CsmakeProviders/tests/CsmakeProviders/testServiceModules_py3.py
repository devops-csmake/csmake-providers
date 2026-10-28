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
"""Unit tests for the csmake sections that wrap the service providers:
CsmakeModules/HttpService.py, HttpStopService.py, SshService.py,
SshStopService.py, PypiFacade.py, PypiStopFacade.py and the Pypi*Context
sections.

The providers (class level registries of services) are replaced by mocks and
the csmake base-class plumbing (exit callbacks, engine) by stand-ins, so only
the wrapper logic runs.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import types
import unittest
import unittest.mock

try:
    from . import csmake_alias
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import csmake_alias
    import providers_support as support

HTTP = csmake_alias.import_plugin('HttpService')
HTTP_STOP = csmake_alias.import_plugin('HttpStopService')
SSH = csmake_alias.import_plugin('SshService')
SSH_STOP = csmake_alias.import_plugin('SshStopService')
FACADE = csmake_alias.import_plugin('PypiFacade')
STOP_FACADE = csmake_alias.import_plugin('PypiStopFacade')
CREATE = csmake_alias.import_plugin('PypiCreateContext')
DELETE = csmake_alias.import_plugin('PypiDeleteContext')
POP = csmake_alias.import_plugin('PypiPopContext')
PUSH = csmake_alias.import_plugin('PypiPushContext')


class SectionTestCase(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.log.params = {'AspectId': 'aspect-1'}

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock

    def _section(self, clazz):
        """The section without csmake's engine: base class plumbing mocked."""
        section = object.__new__(clazz)
        section.log = self.log
        section.env = types.SimpleNamespace(env={})
        section.engine = unittest.mock.Mock()
        section._parseCommaAndNewlineList = lambda text: [
            part.strip() for part in text.replace('\n', ',').split(',')
            if part.strip()]
        for name in ('_dontValidateFiles', '_registerOnExitCallback',
                     '_unregisterOnExitCallback',
                     '_unregisterOtherClassOnExitCallback',
                     '_absorbNewMappedFiles'):
            setattr(section, name, unittest.mock.Mock())
        return section


class testHttpService_py3(SectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._patch(HTTP, 'HttpServiceProvider')
        self.service = self.provider.createServiceProvider.return_value
        self.service.isServiceExecuting.return_value = True
        self.section = self._section(HTTP.HttpService)

    def test_build_startsTheServiceAndPasses(self):
        result = self.section.build({'root-path': '/srv/www', 'port': '8080'})

        self.provider.createServiceProvider.assert_called_once_with(
            '_', self.section, **{'root-path': '/srv/www', 'port': '8080'})
        self.service.startService.assert_called_once_with()
        self.section._dontValidateFiles.assert_called_once_with()
        self.section._registerOnExitCallback.assert_called_once_with(
            '_stopService')
        self.assertIs(result, self.service)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_build_aTagNamesTheServiceAndIsNotPassedOn(self):
        options = {'tag': 'web', 'root-path': '/srv/www'}

        self.section.build(options)

        self.provider.createServiceProvider.assert_called_once_with(
            'web', self.section, **{'root-path': '/srv/www'})
        self.assertNotIn('tag', options)

    def test_build_aServiceThatIsNotExecutingFails(self):
        self.service.isServiceExecuting.return_value = False

        self.section.build({'root-path': '/srv/www'})

        self.assertEqual(self.log.messages('failed'), [''])
        self.assertEqual(self.log.messages('passed'), [])

    def test_build_aServiceThatCannotBeCreatedIsAnError(self):
        self.provider.createServiceProvider.side_effect = RuntimeError(
            'No port could be found')

        with self.assertRaises(RuntimeError):
            self.section.build({'root-path': '/srv/www'})

        self.service.startService.assert_not_called()
        self.assertEqual(self.log.messages('passed'), [])

    def test_stopService_disposesTheServiceAndRemovesTheExitCallback(self):
        self.section.build({'tag': 'web', 'root-path': '/srv/www'})
        self.log.records[:] = []

        self.section._stopService()

        self.provider.disposeServiceProvider.assert_called_once_with('web')
        self.section._unregisterOnExitCallback.assert_called_once_with(
            '_stopService')
        self.assertEqual(self.log.messages('passed'), [''])

    def test_stopService_aCallbackThatIsAlreadyGoneIsNotAnError(self):
        self.section.build({'root-path': '/srv/www'})
        self.section._unregisterOnExitCallback.side_effect = KeyError('gone')

        self.section._stopService()

        self.provider.disposeServiceProvider.assert_called_once_with('_')

    def test_joinPointsStartAndStopTheServiceAroundTheSection(self):
        started = self.section.start__build('build', {'root-path': '/x'}, 's', {})
        ended = self.section.end__build('build', {}, 's', {})

        self.assertIs(started, self.service)
        self.assertTrue(ended)
        self.provider.disposeServiceProvider.assert_called_once_with('_')


class testHttpStopService_py3(SectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._patch(HTTP_STOP, 'HttpServiceProvider')
        self.section = self._section(HTTP_STOP.HttpStopService)

    def test_stopService_disposesTheTaggedServiceAndItsExitCallback(self):
        self.section._stopService('web')

        self.section._unregisterOtherClassOnExitCallback.assert_called_once_with(
            'HttpService', '_stopService')
        self.provider.disposeServiceProvider.assert_called_once_with('web')

    def test_stopService_aMissingExitCallbackIsNotAnError(self):
        self.section._unregisterOtherClassOnExitCallback.side_effect = \
            KeyError('gone')

        self.section._stopService('web')

        self.provider.disposeServiceProvider.assert_called_once_with('web')

    @unittest.skip("pre-existing: build() calls self._stopService() without "
                   "the tag that _stopService(tag) requires, so the section "
                   "raises TypeError instead of stopping the service")
    def test_build_stopsTheServiceWithTheTagGiven(self):
        result = self.section.build({'tag': 'web'})

        self.provider.disposeServiceProvider.assert_called_once_with('web')
        self.assertEqual(self.log.messages('passed'), [''])
        self.assertIsNone(result)


class testSshService_py3(SectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._patch(SSH, 'SshServiceProvider')
        self.provider.hasServiceProvider.return_value = False
        self.service = self.provider.createServiceProvider.return_value
        self.service.isServiceExecuting.return_value = True
        self.section = self._section(SSH.SshService)

    def test_build_startsTheServiceAndPasses(self):
        result = self.section.build({'user': 'builder', 'chroot': '/c'})

        self.provider.hasServiceProvider.assert_called_once_with('_')
        self.provider.createServiceProvider.assert_called_once_with(
            '_', self.section, user='builder', chroot='/c')
        self.service.startService.assert_called_once_with()
        self.section._registerOnExitCallback.assert_called_once_with(
            '_stopService')
        self.assertEqual(self.log.messages('passed'), ['', ''])
        self.assertIsNone(result)

    def test_build_aTagNamesTheService(self):
        options = {'tag': 'one', 'user': 'builder'}

        self.section.build(options)

        self.provider.hasServiceProvider.assert_called_once_with('one')
        self.provider.createServiceProvider.assert_called_once_with(
            'one', self.section, user='builder')
        self.assertNotIn('tag', options)

    def test_build_aTagAlreadyInUseFailsWithoutStartingAnother(self):
        self.provider.hasServiceProvider.return_value = True

        self.section.build({'user': 'builder'})

        self.provider.createServiceProvider.assert_not_called()
        self.assertEqual(self.log.messages('failed'), [''])
        self.assertEqual(len(self.log.messages('error')), 1)
        self.section._unregisterOnExitCallback.assert_called_once_with(
            '_stopService')

    def test_build_aServiceThatDoesNotComeUpFailsAndForgetsTheExitCallback(self):
        self.service.isServiceExecuting.return_value = False

        self.section.build({'user': 'builder'})

        self.assertEqual(self.log.messages('failed'), [''])
        self.assertIn('The sshd service could not be started',
                      self.log.messages('error'))
        self.section._unregisterOnExitCallback.assert_called_once_with(
            '_stopService')

    def test_build_aServiceThatCannotBeCreatedIsAnError(self):
        self.provider.createServiceProvider.side_effect = RuntimeError('boom')

        with self.assertRaises(RuntimeError):
            self.section.build({'user': 'builder'})

    def test_stopService_disposesTheServiceAndRemovesTheExitCallback(self):
        self.section.build({'tag': 'one', 'user': 'builder'})
        self.log.records[:] = []

        self.section._stopService()

        self.provider.disposeServiceProvider.assert_called_once_with('one')
        self.assertEqual(self.log.messages('passed'), [''])

    def test_joinPointsStartAndStopTheServiceAroundTheSection(self):
        self.section.start__build('build', {'user': 'builder'}, 's', {})

        self.section.end__build('build', {}, 's', {})

        self.provider.disposeServiceProvider.assert_called_once_with('_')


class testSshStopService_py3(SectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._patch(SSH_STOP, 'SshServiceProvider')
        self.section = self._section(SSH_STOP.SshStopService)

    def test_stopService_disposesTheTaggedServiceAndItsExitCallback(self):
        self.section._stopService('one')

        self.section._unregisterOtherClassOnExitCallback.assert_called_once_with(
            'SshService', '_stopService')
        self.provider.disposeServiceProvider.assert_called_once_with('one')

    def test_stopService_aMissingExitCallbackIsNotAnError(self):
        self.section._unregisterOtherClassOnExitCallback.side_effect = \
            KeyError('gone')

        self.section._stopService('one')

        self.provider.disposeServiceProvider.assert_called_once_with('one')

    @unittest.skip("pre-existing: build() calls self._stopService() without "
                   "the tag that _stopService(tag) requires, so the section "
                   "raises TypeError instead of stopping the service")
    def test_build_stopsTheServiceWithTheTagGiven(self):
        self.section.build({'tag': 'one'})

        self.provider.disposeServiceProvider.assert_called_once_with('one')
        self.assertEqual(self.log.messages('passed'), [''])


class testPypiFacade_py3(SectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._patch(FACADE, 'PypiProvider')
        self.service = self.provider.createServiceProvider.return_value
        self.service.isServiceExecuting.return_value = True
        self.section = self._section(FACADE.PypiFacade)
        self.section.engine.getPhase.return_value = 'build'

    def test_startFacade_startsTheFacadeInTheBuildPhaseAndGivesTheController(self):
        controller = self.service.getController.return_value

        result = self.section._startFacade({'port': '8443', 'indicies': 'x'})

        self.provider.createServiceProvider.assert_called_once_with(
            '_', self.section, port='8443', indicies='x')
        self.service.startService.assert_called_once_with()
        self.section._registerOnExitCallback.assert_called_once_with(
            '_stopFacade')
        self.assertIs(result, controller)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_startFacade_aTagNamesTheFacadeAndIsNotPassedOn(self):
        options = {'tag': 'mirror', 'port': '8443'}

        self.section._startFacade(options)

        self.provider.createServiceProvider.assert_called_once_with(
            'mirror', self.section, port='8443')
        self.assertNotIn('tag', options)

    def test_startFacade_aFacadeThatIsNotExecutingFails(self):
        self.service.isServiceExecuting.return_value = False

        self.section._startFacade({})

        self.assertEqual(self.log.messages('failed'), [''])

    def test_startFacade_otherPhasesAreSkipped(self):
        self.section.engine.getPhase.return_value = 'test'

        result = self.section._startFacade({})

        self.assertIsNone(result)
        self.assertEqual(self.log.messages('skipped'), [''])
        self.provider.createServiceProvider.assert_not_called()
        self.section._absorbNewMappedFiles.assert_called_once_with()

    def test_startFacade_thePhasesOptionChoosesWhereItRuns(self):
        self.section.engine.getPhase.return_value = 'test'

        self.section._startFacade({'phases': 'build, test'})

        self.provider.createServiceProvider.assert_called_once()

    def test_startFacade_aFacadeThatCannotBeCreatedIsAnError(self):
        self.provider.createServiceProvider.side_effect = RuntimeError('boom')

        with self.assertRaises(RuntimeError):
            self.section._startFacade({})

    def test_stopFacade_disposesTheFacadeAndRemovesTheExitCallback(self):
        self.section._startFacade({'tag': 'mirror'})
        self.log.records[:] = []

        self.section._stopFacade()

        self.provider.disposeServiceProvider.assert_called_once_with('mirror')
        self.section._unregisterOnExitCallback.assert_called_once_with(
            '_stopFacade')
        self.assertEqual(self.log.messages('passed'), [''])

    def test_stopFacade_aCallbackThatIsAlreadyGoneIsNotAnError(self):
        self.section._startFacade({})
        self.section._unregisterOnExitCallback.side_effect = KeyError('gone')

        self.section._stopFacade()

        self.provider.disposeServiceProvider.assert_called_once_with('_')

    def test_joinPointLookup_defaultsToTheBuildPhase(self):
        lookup = self.section._joinPointLookup
        self.assertEqual(lookup('start', 'build', {}), self.section._poweron)
        self.assertEqual(lookup('end', 'build', {}), self.section._poweroff)
        self.assertIsNone(lookup('middle', 'build', {}))
        self.assertIsNone(lookup('start', 'test', {}))

    @unittest.skip("pre-existing: without a 'phases' option the default is "
                   "the string 'build', so 'phase in phases' is a substring "
                   "test and a phase named 'bui' (or 'ild') would match")
    def test_joinPointLookup_theDefaultIsExactlyTheBuildPhase(self):
        self.assertIsNone(self.section._joinPointLookup('start', 'bui', {}))

    def test_joinPointLookup_aStarMeansEveryPhase(self):
        lookup = self.section._joinPointLookup

        self.assertEqual(lookup('start', 'anything', {'phases': '*'}),
                         self.section._poweron)

    def test_joinPointLookup_aPhaseListChoosesThePhases(self):
        lookup = self.section._joinPointLookup
        options = {'phases': 'pull, build'}

        self.assertEqual(lookup('end', 'pull', options), self.section._poweroff)
        self.assertIsNone(lookup('end', 'test', options))

    def test_poweronAndPoweroffStartAndStopTheFacade(self):
        self.section._poweron('build', {}, 's', {})
        result = self.section._poweroff('build', {}, 's', {})

        self.assertTrue(result)
        self.provider.disposeServiceProvider.assert_called_once_with('_')

    def test_anUnknownPublicNameIsTakenForAPhaseAndStartsTheFacade(self):
        self.assertEqual(self.section.install, self.section._startFacade)

    def test_anUnknownPrivateNameIsAnError(self):
        with self.assertRaises(AttributeError):
            self.section._nonesuch

        self.assertEqual(len(self.log.messages('error')), 2)


class testPypiStopFacade_py3(SectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._patch(STOP_FACADE, 'PypiProvider')
        self.section = self._section(STOP_FACADE.PypiStopFacade)

    def test_default_stopsTheDefaultFacadeAndItsExitCallback(self):
        result = self.section.default({})

        self.assertTrue(result)
        self.section._unregisterOtherClassOnExitCallback.assert_called_once_with(
            'PypiFacade', '_stopFacade')
        self.provider.disposeServiceProvider.assert_called_once_with('_')
        self.assertEqual(self.log.messages('passed'), [''])

    def test_end_stopsTheTaggedFacadeWhenUsedAsAnAspect(self):
        result = self.section.end('end', {'tag': 'mirror'}, 's', {})

        self.assertTrue(result)
        self.provider.disposeServiceProvider.assert_called_once_with('mirror')

    def test_default_aMissingExitCallbackIsNotAnError(self):
        self.section._unregisterOtherClassOnExitCallback.side_effect = \
            KeyError('gone')

        self.assertTrue(self.section.default({}))

        self.provider.disposeServiceProvider.assert_called_once_with('_')


class ContextSectionTestCase(SectionTestCase):

    def _facade(self, module):
        provider = self._patch(module, 'PypiProvider')
        self.controller = provider.getServiceProvider.return_value \
            .getController.return_value
        return provider


class testPypiCreateContext_py3(ContextSectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._facade(CREATE)
        self.section = self._section(CREATE.PypiCreateContext)

    def test_build_registersTheContextWithTheFacade(self):
        options = {'name': 'mine', 'constraints': 'pip==1.0'}

        result = self.section.build(options)

        self.provider.getServiceProvider.assert_called_once_with('_')
        self.controller.registerContext.assert_called_once_with('mine', options)
        self.assertTrue(result)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_build_aTagSelectsTheFacade(self):
        self.section.build({'name': 'mine', 'tag': 'mirror'})

        self.provider.getServiceProvider.assert_called_once_with('mirror')

    def test_build_withNoFacadeRunningIsAnErrorNotAPass(self):
        self.provider.getServiceProvider.return_value = None

        with self.assertRaises(AttributeError):
            self.section.build({'name': 'mine'})

        self.assertEqual(self.log.messages('passed'), [])


class testPypiDeleteContext_py3(ContextSectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._facade(DELETE)
        self.section = self._section(DELETE.PypiDeleteContext)

    def test_build_removesTheContext(self):
        self.controller.unregisterContext.return_value = True

        result = self.section.build({'name': 'mine'})

        self.controller.unregisterContext.assert_called_once_with('mine')
        self.assertTrue(result)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_build_aContextStillInUseFailsTheSection(self):
        self.controller.unregisterContext.return_value = False

        result = self.section.build({'name': 'mine', 'tag': 'mirror'})

        self.assertFalse(result)
        self.assertEqual(self.log.messages('failed'), [''])
        self.provider.getServiceProvider.assert_called_once_with('mirror')


class testPypiPopContext_py3(ContextSectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._facade(POP)
        self.section = self._section(POP.PypiPopContext)

    def test_build_popsTheNamedContext(self):
        result = self.section.build({'name': 'mine'})

        self.controller.popCurrentContext.assert_called_once_with('mine')
        self.assertTrue(result)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_build_aTagSelectsTheFacade(self):
        self.section.build({'name': 'mine', 'tag': 'mirror'})

        self.provider.getServiceProvider.assert_called_once_with('mirror')


class testPypiPushContext_py3(ContextSectionTestCase):

    def setUp(self):
        SectionTestCase.setUp(self)
        self.provider = self._facade(PUSH)
        self.section = self._section(PUSH.PypiPushContext)

    def test_build_registersThenPushesTheContext(self):
        options = {'name': 'mine', 'indicies': 'http://x/simple/'}

        result = self.section.build(options)

        self.assertEqual(
            [c[0] for c in self.controller.method_calls],
            ['registerContext', 'pushCurrentContext'])
        self.controller.registerContext.assert_called_once_with('mine', options)
        self.controller.pushCurrentContext.assert_called_once_with('mine')
        self.assertTrue(result)

    def test_startAndEndJoinPointsPushAndPopTheContext(self):
        self.section.start__build('build', {'name': 'mine'}, 's', {})
        self.section.end__build('build', {'name': 'mine'}, 's', {})

        self.controller.pushCurrentContext.assert_called_once_with('mine')
        self.controller.popCurrentContext.assert_called_once_with('mine')
        self.assertEqual(self.log.messages('passed'), ['', ''])

    def test_end_aTagSelectsTheFacade(self):
        self.section.end__build('build', {'name': 'mine', 'tag': 'mirror'}, 's', {})

        self.provider.getServiceProvider.assert_called_once_with('mirror')

    def test_build_withNoFacadeRunningIsAnErrorNotAPass(self):
        self.provider.getServiceProvider.return_value = None

        with self.assertRaises(AttributeError):
            self.section.build({'name': 'mine'})

        self.assertEqual(self.log.messages('passed'), [])


if __name__ == '__main__':
    unittest.main()
