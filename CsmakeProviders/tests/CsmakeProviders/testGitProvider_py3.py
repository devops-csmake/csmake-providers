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
"""Unit tests for the Python 3 conversion of GitProvider.py.

GitPython is mocked (git.Repo and the GitProvider helpers that talk to
remotes), so no repository, git binary or network is involved.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import datetime
import unittest
import unittest.mock
import warnings

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

GPM = support.import_provider('GitProvider')   # the module
GitProvider = GPM.GitProvider

URL = 'file:///srv/source.git'
LOCAL = '/work/local/source'


class testGitProvider_py3(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.repo = unittest.mock.MagicMock(name='repo')
        self.repo.is_dirty.return_value = False
        self.repo.head.commit.name_rev = 'oldsha master'
        self.repo.head.commit.hexsha = 'newsha'
        self.config = self.repo.config_writer.return_value
        self.remote = unittest.mock.Mock(name='remote')

        self.Repo = self._patch(GPM.git, 'Repo', return_value=self.repo)
        self.ensureRemote = self._patch(
            GitProvider, 'ensureCsmakeRemote',
            return_value=(self.remote, None))
        self.getSHA = self._patch(
            GitProvider, 'getSHAFromRef', return_value='newsha')

    def _patch(self, target, name, **kwargs):
        patch = unittest.mock.patch.object(target, name, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock

    def _fetch(self, **kwargs):
        return GitProvider.fetchRepository(
            self.log, 'testing', LOCAL, URL, 'master', 'branch', **kwargs)

    def test_fetchRepository_returnsTheOldAndNewShaOnSuccess(self):
        result, status, extended = self._fetch()

        self.assertEqual((result, status), (('oldsha', 'newsha'), 'OK'))
        for key, value in {'URL': URL, 'oldSHA1': 'oldsha',
                           'oldRef': 'master', 'SHA1': 'newsha',
                           'Ref': 'master'}.items():
            self.assertEqual(extended[key], value, key)
        self.Repo.assert_called_once_with(LOCAL)
        self.getSHA.assert_called_once_with(
            self.log, self.repo, self.remote, 'master', 'branch')
        self.assertEqual(self.repo.head.reference, 'newsha')
        self.repo.head.reset.assert_called_once_with(
            index=True, working_tree=True)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_fetchRepository_releasesTheConfigLockBeforeDoingAnythingElse(self):
        # GitPython's config writer holds .git/config.lock until released;
        # Python 3 does not release it just because the writer was dropped,
        # and every later git config edit (adding the remote, ...) fails.
        events = []
        self.repo.is_dirty.side_effect = lambda *args: (
            events.append(('is_dirty', self.config.release.call_count)) or False)

        self._fetch()

        self.config.release.assert_called_once_with()
        self.assertEqual(events, [('is_dirty', 1)])
        self.assertEqual(self.config.set_value.call_args_list, [
            unittest.mock.call('http', 'sslVerify', 'true'),
            unittest.mock.call('http', 'postBuffer', '1048576000')])

    def test_fetchRepository_releasesTheConfigLockWhenSettingFails(self):
        self.config.set_value.side_effect = OSError('disk full')

        with self.assertRaises(OSError):
            self._fetch()

        self.config.release.assert_called_once_with()
        self.ensureRemote.assert_not_called()

    def test_fetchRepository_insecureFetchTurnsSslVerifyOff(self):
        self._fetch(secure=False)

        self.assertEqual(self.config.set_value.call_args_list[0],
                         unittest.mock.call('http', 'sslVerify', 'false'))
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_fetchRepository_aMissingLocalRepoIsInitialised(self):
        self.Repo.side_effect = GPM.git.exc.NoSuchPathError(LOCAL)
        self.Repo.init.return_value = self.repo

        result, status, _ = self._fetch()

        self.Repo.init.assert_called_once_with(LOCAL)
        self.assertEqual(status, 'OK')

    def test_fetchRepository_aDirtyRepoIsRefusedUntouched(self):
        self.repo.is_dirty.return_value = True

        result = self._fetch()

        self.assertEqual(result, (False, 'ERROR', 'Dirty Repository'))
        self.assertEqual(self.log.messages('failed'), [''])
        self.ensureRemote.assert_not_called()
        self.repo.head.reset.assert_not_called()

    def test_fetchRepository_aChangedRemoteUrlRecreatesTheRemote(self):
        self.ensureRemote.side_effect = [
            (self.remote, 'file:///srv/old.git'), (self.remote, None)]

        _, status, extended = self._fetch()

        self.repo.delete_remote.assert_called_once_with(self.remote)
        self.assertEqual(self.ensureRemote.call_count, 2)
        self.assertEqual(extended['oldURL'], 'file:///srv/old.git')

    def test_fetchRepository_anUnknownRefFails(self):
        self.getSHA.return_value = None

        result = self._fetch()

        self.assertEqual(
            result, (False, 'ERROR', 'Invalid Reference - Reference not found'))
        self.assertEqual(self.log.messages('failed'), [''])
        self.repo.head.reset.assert_not_called()

    def test_fetchRepository_aRepoWithNoCommitsYetHasAnEmptyOldSha(self):
        commit = unittest.mock.Mock(hexsha='newsha')
        type(self.repo.head).commit = unittest.mock.PropertyMock(
            side_effect=[ValueError('no commits'), ValueError('no commits'),
                         commit, commit])

        result, status, extended = self._fetch()

        self.assertEqual(result, ('', 'newsha'))
        self.assertEqual((extended['oldSHA1'], extended['oldRef']), ('', ''))

    def test_createLogRecord_authorIsTextAndTheDateIsUtc(self):
        # unicode() became str(); the author is a GitPython Actor
        class Actor(object):
            def __str__(self):
                return 'Zo\u00eb Tester'
        commit = unittest.mock.Mock(
            authored_date=86400, message='msg\n', summary='msg',
            author=Actor())
        commit.name_rev = 'abc123 master'

        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            record = GitProvider._createLogRecord(
                commit, {'refsdict': {'abc123': ['master', 'v1']}})

        self.assertEqual(record['author'], 'Zo\u00eb Tester')
        self.assertIs(type(record['author']), str)
        self.assertEqual(record['SHA1'], 'abc123')
        self.assertEqual(record['refs'], ['master', 'v1'])
        self.assertEqual(record['datetime'], datetime.datetime(1970, 1, 2))


if __name__ == '__main__':
    unittest.main()
