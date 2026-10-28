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
"""Unit tests for GitProvider's remote and history helpers (ensureCsmakeRemote,
_fetchRemote, pushTag, getSHAFromRef, generateSpanLogInfo, ...) with GitPython
mocked: remotes, refs and commits are small fakes with the attributes the
helpers read.  (testGitProvider_scenario.py exercises the same helpers against
real repositories under csmake's test harness.)

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import datetime
import types
import unittest
import unittest.mock
import warnings

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

GPM = support.import_provider('GitProvider')   # the module
GitProvider = GPM.GitProvider
git = GPM.git

URL = 'file:///srv/source.git'
FETCH_SPEC = '+refs/*:refs/remotes/Csmake/*'


class Refs(dict):
    """remote.refs: an IterableList raises IndexError for a missing name."""

    def __missing__(self, key):
        raise IndexError(key)


def ref(sha, name=None):
    return types.SimpleNamespace(
        commit=types.SimpleNamespace(hexsha=sha), name=name or sha)


class GitHelperTestCase(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock


class testGitProviderPaths_py3(unittest.TestCase):

    def test_determineRepoPath_joinsTheLocalDirectoryAndTheName(self):
        self.assertEqual(GitProvider.determineRepoPath('/clones', 'project'),
                         ('project', '/clones/project'))

    def test_splitRepoReference_understandsEachForm(self):
        for given, expected in ((None, ('master', 'branch')),
                                ('branch:topic', ('topic', 'branch')),
                                ('tag:v1.2', ('v1.2', 'tag')),
                                ('abc123', ('abc123', None)),
                                ('a:b:c', (None, None))):
            with self.subTest(given=given):
                self.assertEqual(GitProvider.splitRepoReference(given), expected)


class testGitProviderRemote_py3(GitHelperTestCase):

    def _repo(self, existing_url=None):
        repo = unittest.mock.Mock(name='repo')
        repo.remotes = types.SimpleNamespace()
        if existing_url is not None:
            repo.remotes.Csmake = unittest.mock.Mock(url=existing_url)
        self.created = unittest.mock.Mock(name='new remote')

        def create_remote(name, url):
            repo.remotes.Csmake = self.created
            return self.created
        repo.create_remote.side_effect = create_remote
        return repo

    def test_fetchRemote_fetchesEveryRefIntoTheCsmakeNamespaceAndPrunes(self):
        remote = unittest.mock.Mock()

        GitProvider._fetchRemote(remote, self.log)

        remote.fetch.assert_called_once_with(FETCH_SPEC, prune=True)

    def test_fetchRemote_retriesOnceAfterGitPythonsAssertionError(self):
        remote = unittest.mock.Mock()
        remote.fetch.side_effect = [AssertionError('issue 94'), None]

        GitProvider._fetchRemote(remote, self.log)

        self.assertEqual(remote.fetch.call_count, 2)

    def test_fetchRemote_aSecondAssertionErrorIsRaised(self):
        remote = unittest.mock.Mock()
        remote.fetch.side_effect = AssertionError('issue 94')

        with self.assertRaises(AssertionError):
            GitProvider._fetchRemote(remote, self.log)

        self.assertEqual(remote.fetch.call_count, 2)

    def test_fetchRemote_otherErrorsAreRaisedAtOnceAndNoLogIsNeeded(self):
        remote = unittest.mock.Mock()
        remote.fetch.side_effect = OSError('network is unreachable')

        with self.assertRaises(OSError):
            GitProvider._fetchRemote(remote, None)

        self.assertEqual(remote.fetch.call_count, 1)

    def test_ensureCsmakeRemote_anExistingRemoteForTheSameUrlIsReused(self):
        repo = self._repo(existing_url=URL)

        remote, oldurl = GitProvider.ensureCsmakeRemote(repo, URL, self.log)

        self.assertIs(remote, repo.remotes.Csmake)
        self.assertEqual(oldurl, URL)
        repo.create_remote.assert_not_called()
        repo.delete_remote.assert_not_called()

    def test_ensureCsmakeRemote_aMissingRemoteIsCreatedAndFetched(self):
        repo = self._repo()

        remote, oldurl = GitProvider.ensureCsmakeRemote(repo, URL, self.log)

        repo.create_remote.assert_called_once_with('Csmake', URL)
        self.created.fetch.assert_called_once_with(FETCH_SPEC, prune=True)
        self.assertIs(remote, self.created)
        self.assertEqual(oldurl, '')

    def test_ensureCsmakeRemote_aRemoteForAnotherUrlIsReplaced(self):
        repo = self._repo(existing_url='file:///srv/old.git')
        old = repo.remotes.Csmake

        remote, oldurl = GitProvider.ensureCsmakeRemote(repo, URL)

        repo.delete_remote.assert_called_once_with(old)
        repo.create_remote.assert_called_once_with('Csmake', URL)
        self.assertIs(remote, self.created)
        self.assertEqual(oldurl, 'file:///srv/old.git')

    def test_ensureCsmakeRemote_aFetchThatFailsIsRaised(self):
        repo = self._repo()
        self.created.fetch.side_effect = OSError('network is unreachable')

        with self.assertRaises(OSError):
            GitProvider.ensureCsmakeRemote(repo, URL, self.log)

    def test_ensureCsmakeRemote_aRemoteThatCannotBeCreatedIsRaised(self):
        repo = self._repo()
        repo.create_remote.side_effect = git.exc.GitCommandError(
            ['git', 'remote', 'add'], 128, stderr='could not lock config file')

        with self.assertRaises(git.exc.GitCommandError):
            GitProvider.ensureCsmakeRemote(repo, URL)

    def test_pushTag_createsTheTagWithTheMessageThenPushesIt(self):
        repo = unittest.mock.Mock()
        remote = unittest.mock.Mock()

        GitProvider.pushTag(repo, 'rel-1', remote, 'Release 1')

        repo.create_tag.assert_called_once_with('rel-1', message='Release 1')
        remote.push.assert_called_once_with(repo.create_tag.return_value)

    def test_pushTag_aLightweightTagHasNoMessage(self):
        repo = unittest.mock.Mock()

        GitProvider.pushTag(repo, 'rel-1', unittest.mock.Mock())

        repo.create_tag.assert_called_once_with('rel-1', message=None)

    def test_pushTag_aTagThatCannotBeCreatedIsNotPushed(self):
        repo = unittest.mock.Mock()
        repo.create_tag.side_effect = git.exc.GitCommandError(
            ['git', 'tag'], 128, stderr='tag already exists')
        remote = unittest.mock.Mock()

        with self.assertRaises(git.exc.GitCommandError):
            GitProvider.pushTag(repo, 'rel-1', remote)

        remote.push.assert_not_called()


class testGitProviderRefs_py3(GitHelperTestCase):

    def _remote(self, **refs):
        return types.SimpleNamespace(refs=Refs(refs))

    def _resolve(self, remote, name, reftype, repo=None):
        return GitProvider.getSHAFromRef(
            self.log, repo or unittest.mock.Mock(), remote, name, reftype)

    def test_aTagIsLookedUpUnderTags(self):
        remote = self._remote(**{'tags/v1': ref('tagsha')})

        self.assertEqual(self._resolve(remote, 'v1', 'tag'), 'tagsha')

    def test_aMissingTagIsLoggedAndGivesNone(self):
        self.assertIsNone(self._resolve(self._remote(), 'v1', 'tag'))
        self.assertEqual(len(self.log.messages('error')), 1)

    def test_aBranchIsLookedUpByName(self):
        remote = self._remote(topic=ref('branchsha'))

        self.assertEqual(self._resolve(remote, 'topic', 'branch'), 'branchsha')

    def test_aBranchThatIsOnlyAHeadIsFoundUnderHeads(self):
        remote = self._remote(**{'heads/topic': ref('headsha')})

        self.assertEqual(self._resolve(remote, 'topic', 'branch'), 'headsha')

    def test_aMissingBranchIsLoggedAndGivesNone(self):
        self.assertIsNone(self._resolve(self._remote(), 'topic', 'branch'))
        self.assertIn("Branch 'topic' did not resolve to a valid reference",
                      self.log.messages('error'))

    def test_anUntypedRefIsTriedAsAReferenceFirst(self):
        remote = self._remote(**{'changes/1': ref('changesha')})

        self.assertEqual(self._resolve(remote, 'changes/1', None), 'changesha')

    def test_anUntypedRefThatIsAShaOrTagComesFromTheLocalRepo(self):
        repo = unittest.mock.Mock()
        repo.commit.return_value = types.SimpleNamespace(hexsha='fullsha')

        self.assertEqual(
            self._resolve(self._remote(), 'abc123', None, repo), 'fullsha')

    def test_anUntypedRefThatOnlyExistsAsAHeadIsFoundThere(self):
        repo = unittest.mock.Mock()
        repo.commit.side_effect = git.exc.BadName('nope')
        remote = self._remote(**{'heads/topic': ref('headsha')})

        self.assertEqual(self._resolve(remote, 'topic', None, repo), 'headsha')

    def test_anUntypedRefThatCannotBeFoundAnywhereGivesNone(self):
        repo = unittest.mock.Mock()
        repo.commit.side_effect = ValueError('bad')

        self.assertIsNone(self._resolve(self._remote(), 'nothing', None, repo))
        self.assertEqual(len(self.log.messages('error')), 1)

    def test_populateRefLookups_groupsRefNamesByShaWithoutTheCsmakePrefix(self):
        repo = types.SimpleNamespace(refs=[
            ref('sha1', 'Csmake/master'), ref('sha1', 'Csmake/v1'),
            ref('sha2', 'topic')])
        lookups = {}

        GitProvider._populateRefLookups(repo, lookups)

        self.assertEqual(lookups, {'sha1': ['master', 'v1'], 'sha2': ['topic']})

    def test_populateRefLookups_aRefThatIsNotACommitIsSkipped(self):
        broken = types.SimpleNamespace(name='tags/tree')
        repo = types.SimpleNamespace(refs=[broken, ref('sha1', 'master')])
        lookups = {}

        GitProvider._populateRefLookups(repo, lookups)

        self.assertEqual(lookups, {'sha1': ['master']})


class Commit(object):
    """A commit with what generateSpanLogInfo and _createLogRecord read."""

    def __init__(self, sha, parent=None):
        self.hexsha = sha
        self.name_rev = '%s %s' % (sha, 'master')
        self.authored_date = 86400
        self.message = 'message %s\n' % sha
        self.summary = 'summary %s' % sha
        self.author = 'Author %s' % sha
        self.parent = parent

    def iter_parents(self):
        commit = self.parent
        while commit is not None:
            yield commit
            commit = commit.parent


class testGitProviderSpanLog_py3(GitHelperTestCase):

    def setUp(self):
        GitHelperTestCase.setUp(self)
        a = Commit('a')
        b = Commit('b', a)
        self.commits = {
            'a': a, 'b': b, 'c': Commit('c', b),
            'd': Commit('d', Commit('c2', b)),     # splits from c after b
            'orphan': Commit('orphan', Commit('orphan0'))}
        repo = unittest.mock.Mock()
        repo.commit.side_effect = lambda sha: self.commits[sha]
        repo.refs = [ref('c', 'Csmake/master'), ref('b', 'Csmake/v1')]
        self.Repo = self._patch(git, 'Repo', return_value=repo)

    def _span(self, old, new, findRefs=False):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)  # utcfromtimestamp
            return GitProvider.generateSpanLogInfo(
                self.log, '/clones/project', old, new, findRefs)

    def test_aNewShaDescendedFromTheOldGivesTheCommitsInBetween(self):
        result = self._span('a', 'c')

        self.assertEqual(result['type'], 'parent')
        self.assertEqual([h['SHA1'] for h in result['history']], ['c', 'b'])
        self.Repo.assert_called_once_with('/clones/project')

    def test_theRecordsCarryTheCommitDetailsAsText(self):
        record = self._span('a', 'b')['history'][0]

        self.assertEqual(record['SHA1'], 'b')
        self.assertEqual(record['ref'], 'master')
        self.assertEqual(record['message'], 'message b\n')
        self.assertEqual(record['summary'], 'summary b')
        self.assertEqual(record['author'], 'Author b')
        self.assertIs(type(record['author']), str)
        self.assertEqual(record['datetime'], datetime.datetime(1970, 1, 2))
        self.assertEqual(record['refs'], [])

    def test_findRefsAddsTheRefsPointingAtEachCommit(self):
        history = self._span('a', 'c', findRefs=True)['history']

        self.assertEqual([h['refs'] for h in history], [['master'], ['v1']])

    def test_historiesThatSplitAfterTheOldShaAreDiverged(self):
        result = self._span('c', 'd')

        self.assertEqual(result['type'], 'diverged')
        self.assertEqual(result['old']['SHA1'], 'c')
        self.assertEqual(result['new']['SHA1'], 'd')
        self.assertEqual(result['common']['SHA1'], 'b')
        self.assertEqual(result['history'], [])

    def test_unrelatedHistoriesAreDifferentTrees(self):
        result = self._span('a', 'orphan')

        self.assertEqual(result['type'], 'different_tree')
        self.assertEqual(result['old']['SHA1'], 'a')
        self.assertEqual(result['new']['SHA1'], 'orphan')
        self.assertIsNone(result['common'])
        self.assertEqual(result['history'], [])

    def test_anUnknownShaIsAnError(self):
        with self.assertRaises(KeyError):
            self._span('a', 'nonesuch')

    def test_aRepositoryThatCannotBeOpenedIsAnError(self):
        self.Repo.side_effect = git.exc.NoSuchPathError('/clones/project')

        with self.assertRaises(git.exc.NoSuchPathError):
            self._span('a', 'c')


if __name__ == '__main__':
    unittest.main()
