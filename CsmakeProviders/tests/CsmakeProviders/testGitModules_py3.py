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
"""Unit tests for CsmakeModules/GitFirstRelevantSha.py, GitLatestShaTag.py
and GitDependent.py.

GitProvider's fetch/remote/ref helpers and git.Repo are mocked, and the git
objects (commits, tags) are mocks with the attributes the modules read, so no
repository is involved.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import os
import types
import unittest
import unittest.mock

try:
    from . import csmake_alias
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import csmake_alias
    import providers_support as support

FIRST = csmake_alias.import_plugin('GitFirstRelevantSha')
LATEST = csmake_alias.import_plugin('GitLatestShaTag')
DEPENDENT = csmake_alias.import_plugin('GitDependent')
GitProvider = FIRST.GitProvider
git = FIRST.git

URL = 'https://git.example/project.git'


class ModuleTestCase(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.env = types.SimpleNamespace(
            env={'RESULTS': 'results'}, addTransPhase=unittest.mock.Mock(),
            doSubstitutions=lambda text: text.replace('%(RESULTS)s', 'results'))

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock

    def _plugin(self, clazz):
        module = object.__new__(clazz)
        module.log = self.log
        module.env = self.env
        return module

    def _gitProvider(self, module):
        self.fetch = self._patch(module.GitProvider, 'fetchRepository')
        self.remote = unittest.mock.Mock(name='remote')
        self.ensureRemote = self._patch(
            module.GitProvider, 'ensureCsmakeRemote',
            return_value=(self.remote, None))
        self.getSHA = self._patch(
            module.GitProvider, 'getSHAFromRef', return_value='startsha')
        self.Repo = self._patch(module.git, 'Repo')
        self.repo = self.Repo.return_value


class testGitFirstRelevantSha_py3(ModuleTestCase):

    def setUp(self):
        ModuleTestCase.setUp(self)
        self._gitProvider(FIRST)
        self.module = self._plugin(FIRST.GitFirstRelevantSha)
        root = unittest.mock.Mock(parents=[], hexsha='rootsha')
        middle = unittest.mock.Mock(parents=[root], hexsha='middlesha')
        side = unittest.mock.Mock(parents=[], hexsha='sidesha')
        self.tip = unittest.mock.Mock(parents=[middle, side], hexsha='tipsha')
        self.repo.commit.return_value = self.tip

    def _pull(self, **options):
        given = {'repo': URL, 'env': 'FIRST_SHA'}
        given.update(options)
        return self.module.pull(given)

    def test_pull_walksTheFirstParentsDownToTheRootCommit(self):
        result = self._pull()

        self.assertEqual(result, 'rootsha')
        self.repo.commit.assert_called_once_with('startsha')
        self.env.addTransPhase.assert_called_once_with('FIRST_SHA', 'rootsha')
        self.assertEqual(self.log.messages('passed'), [''])

    def test_pull_fetchesTheRepoUnderResultsFromTheDefaultBranch(self):
        self._pull()

        self.fetch.assert_called_once_with(
            self.log, 'project.git', os.path.join('./', 'results', 'project.git'),
            URL, 'master', 'branch', secure=False)
        self.getSHA.assert_called_once_with(
            self.log, self.repo, self.remote, 'master', 'branch')

    def test_pull_aGivenRefAndLocalDirectoryAreUsed(self):
        self._pull(**{'fetch-ref': 'tag:v1.2', 'local': '/clones/mine'})

        self.assertEqual(self.fetch.call_args[0][1:3], ('mine', '/clones/mine'))
        self.assertEqual(self.fetch.call_args[0][4:6], ('v1.2', 'tag'))
        self.Repo.assert_called_once_with('/clones/mine')

    def test_pull_aRelativeFileUrlBecomesAbsolute(self):
        self._pull(repo='file://./project.git')

        expected = 'file://' + os.path.abspath('.') + '/project.git'
        self.assertEqual(self.fetch.call_args[0][3], expected)
        self.ensureRemote.assert_called_once_with(self.repo, expected)

    def test_pull_aRefThatDoesNotResolveFailsWithoutSettingTheEnvironment(self):
        self.getSHA.return_value = None

        result = self._pull(**{'fetch-ref': 'branch:gone'})

        self.assertIsNone(result)
        self.assertEqual(self.log.messages('failed'), [''])
        self.assertEqual(len(self.log.messages('error')), 1)
        self.env.addTransPhase.assert_not_called()

    def test_pull_aFetchThatFailsIsNotSwallowed(self):
        self.fetch.side_effect = OSError('network is unreachable')

        with self.assertRaises(OSError):
            self._pull()

        self.env.addTransPhase.assert_not_called()

    def test_envAndSourcesPhasesPull(self):
        self.module.pull = unittest.mock.Mock(return_value='sha')

        self.assertEqual(FIRST.GitFirstRelevantSha.env(self.module, {'a': 1}), 'sha')
        self.assertEqual(FIRST.GitFirstRelevantSha.sources(self.module, {'b': 2}), 'sha')

        self.assertEqual(self.module.pull.call_args_list,
                         [unittest.mock.call({'a': 1}), unittest.mock.call({'b': 2})])

    def test_default_setsTheEnvironmentToUnknownUnlessAlreadySet(self):
        result = self.module.default({'env': 'FIRST_SHA'})

        self.assertEqual(result, '<unknown>')
        self.assertEqual(self.env.env['FIRST_SHA'], '<unknown>')
        self.env.env['FIRST_SHA'] = 'known'
        self.assertEqual(self.module.default({'env': 'FIRST_SHA'}), 'known')
        self.assertEqual(self.log.messages('passed'), ['', ''])


def lightweight(name, authored, sha):
    commit = unittest.mock.Mock(spec=git.Commit)
    commit.authored_date = authored
    commit.hexsha = sha
    tag = unittest.mock.MagicMock()
    tag.__str__.return_value = name
    tag.object = commit
    return tag


def annotated(name, tagged, authored, tag_sha, commit_sha):
    commit = unittest.mock.Mock(spec=git.Commit)
    commit.authored_date = authored
    commit.hexsha = commit_sha
    tag_object = unittest.mock.Mock()      # a TagObject: not a Commit
    tag_object.object = commit
    tag_object.tagged_date = tagged
    tag_object.hexsha = tag_sha
    tag = unittest.mock.MagicMock()
    tag.__str__.return_value = name
    tag.object = tag_object
    return tag


class testGitLatestShaTag_py3(ModuleTestCase):

    def setUp(self):
        ModuleTestCase.setUp(self)
        self._gitProvider(LATEST)
        self.module = self._plugin(LATEST.GitLatestShaTag)
        self.repo.commit.return_value = unittest.mock.Mock(authored_date=1000)

    def _pull(self, tags, **options):
        self.repo.tags = tags
        given = {'repo': URL, 'format': 'rel-*', 'env': 'LATEST_SHA'}
        given.update(options)
        return self.module.pull(given)

    def test_pull_picksTheCommitOfTheMostRecentMatchingTag(self):
        result = self._pull([
            lightweight('rel-1', 100, 'sha1'),
            lightweight('rel-3', 300, 'sha3'),
            lightweight('rel-2', 200, 'sha2')])

        self.assertEqual(result, 'sha3')
        self.env.addTransPhase.assert_called_once_with('LATEST_SHA', 'sha3')
        self.assertEqual(self.log.messages('passed'), [''])

    def test_pull_anAnnotatedTagIsDatedByWhenItWasTaggedAndGivesItsCommit(self):
        result = self._pull([
            lightweight('rel-1', 500, 'sha1'),
            annotated('rel-2', 800, 100, 'tagsha2', 'commitsha2')])

        self.assertEqual(result, 'commitsha2')
        self.assertIn('Tag found: rel-2 (tagsha2, commitsha2)',
                      self.log.messages('info'))

    def test_pull_onlyTagsMatchingTheFormatAreConsidered(self):
        result = self._pull([
            lightweight('rel-1', 100, 'sha1'),
            lightweight('nightly-9', 900, 'sha9')])

        self.assertEqual(result, 'sha1')

    def test_pull_tagsOnCommitsNewerThanTheCurrentOneAreIgnored(self):
        result = self._pull([
            lightweight('rel-1', 100, 'sha1'),
            lightweight('rel-2', 2000, 'sha2')])    # current is at 1000

        self.assertEqual(result, 'sha1')

    def test_pull_noMatchingTagFailsAndFallsBackToTheDefault(self):
        result = self._pull([lightweight('nightly-9', 900, 'sha9')])

        self.assertEqual(result, '<unknown>')
        self.assertEqual(self.log.messages('failed'), [''])
        self.assertEqual(self.log.messages('error'), ['No tags found'])
        self.assertEqual(self.env.env['LATEST_SHA'], '<unknown>')
        self.env.addTransPhase.assert_not_called()

    def test_pull_noMatchKeepsAnEnvironmentValueThatWasAlreadySet(self):
        self.env.env['LATEST_SHA'] = 'earlier'

        result = self._pull([])

        self.assertEqual(result, 'earlier')

    def test_pull_fetchesWithTheGivenRefAndLocalDirectory(self):
        self._pull([lightweight('rel-1', 100, 'sha1')],
                   **{'fetch-ref': 'branch:stable', 'local': '/clones/mine'})

        self.fetch.assert_called_once_with(
            self.log, 'mine', '/clones/mine', URL, 'stable', 'branch',
            secure=False)

    def test_pull_aFetchThatFailsIsNotSwallowed(self):
        self.fetch.side_effect = OSError('network is unreachable')

        with self.assertRaises(OSError):
            self._pull([])


class testGitDependent_py3(ModuleTestCase):

    def setUp(self):
        ModuleTestCase.setUp(self)
        self.fetch = self._patch(DEPENDENT.GitProvider, 'fetchRepository',
                                 return_value=('result', 'OK', {}))
        self.module = self._plugin(DEPENDENT.GitDependent)

    def _options(self, **more):
        options = {'URL': URL, 'name': 'project', 'ref': 'branch:topic',
                   'local': '%(RESULTS)s/deps'}
        options.update(more)
        return options

    def test_pull_fetchesTheNamedRepoIntoTheLocalDirectory(self):
        result = self.module.pull(self._options())

        self.assertEqual(result, ('result', 'OK', {}))
        self.fetch.assert_called_once_with(
            self.log, 'project', '%(RESULTS)s/deps/project', URL,
            'topic', 'branch', secure=False)

    def test_pull_secureAccessMustBeAskedForAsText(self):
        self.module.pull(self._options(secure='True'))
        self.module.pull(self._options(secure='False'))

        self.assertEqual(
            [c[1]['secure'] for c in self.fetch.call_args_list], [True, False])

    def test_pull_aRelativeFileUrlBecomesAbsolute(self):
        self.module.pull(self._options(URL='file://./project.git'))

        self.assertEqual(self.fetch.call_args[0][3],
                         'file://' + os.path.abspath('.') + '/project.git')

    def test_pull_theEnvOptionNamesTheLocalPath(self):
        self.module.pull(self._options(env='PROJECT_DIR'))

        self.assertEqual(self.env.env['PROJECT_DIR'], '%(RESULTS)s/deps/project')

    def test_pull_aRefThatCannotBeUnderstoodFailsWithoutFetching(self):
        result = self.module.pull(self._options(ref='a:b:c'))

        self.assertEqual(result[:2], (False, 'ERROR'))
        self.assertEqual(self.log.messages('failed'), [''])
        self.fetch.assert_not_called()

    def test_pull_aFetchThatFailsIsNotSwallowed(self):
        self.fetch.side_effect = OSError('network is unreachable')

        with self.assertRaises(OSError):
            self.module.pull(self._options())

    def test_sources_pulls(self):
        self.module.pull = unittest.mock.Mock(return_value='pulled')

        self.assertEqual(self.module.sources({'x': 1}), 'pulled')

    def test_clean_removesTheLocalRepo(self):
        rmtree = self._patch(DEPENDENT.shutil, 'rmtree')

        self.module.clean(self._options(env='PROJECT_DIR'))

        rmtree.assert_called_once_with('results/deps/project')
        self.assertEqual(self.env.env['PROJECT_DIR'], 'results/deps/project')
        self.assertEqual(self.log.messages('passed'), [''])

    def test_clean_aRepoThatCannotBeRemovedIsOnlyLogged(self):
        self._patch(DEPENDENT.shutil, 'rmtree', side_effect=OSError('gone'))

        self.module.clean(self._options())

        self.assertEqual(len(self.log.messages('info')), 1)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_default_onlyReportsTheLocalPath(self):
        self.module.default(self._options(env='PROJECT_DIR'))

        self.fetch.assert_not_called()
        self.assertEqual(self.env.env['PROJECT_DIR'], '%(RESULTS)s/deps/project')
        self.assertEqual(self.log.messages('passed'), [''])


if __name__ == '__main__':
    unittest.main()
