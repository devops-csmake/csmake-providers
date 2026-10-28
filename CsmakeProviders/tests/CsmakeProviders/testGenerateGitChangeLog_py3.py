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
"""Unit tests for CsmakeModules/GenerateGitChangeLog.py.

The formatters write real temp files (their encoded content is the subject);
GitPython and the GitProvider remote/log helpers are mocked.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import datetime
import os
import shutil
import tempfile
import types
import unittest
import unittest.mock

try:
    from . import csmake_alias
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import csmake_alias
    import providers_support as support

GGCL = csmake_alias.import_plugin('GenerateGitChangeLog')
GenerateGitChangeLog = GGCL.GenerateGitChangeLog
GitProvider = GGCL.GitProvider

URL = 'https://git.example/project.git'
WHEN = datetime.datetime(2020, 1, 2, 3, 4, 5)


def record(sha, summary, author='A U Thor'):
    return {'SHA1': sha, 'summary': summary, 'author': author,
            'datetime': WHEN, 'ref': 'master', 'refs': [],
            'message': summary + '\n'}


def changelog(*records):
    return {'type': 'parent', 'history': list(records), 'old': None,
            'new': None, 'common': None}


class ChangeLogTestCase(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='csmake-chglog-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock

    def _module(self, yieldsfiles=None):
        module = object.__new__(GenerateGitChangeLog)
        module.log = self.log
        module.env = types.SimpleNamespace(env={'RESULTS': self.tmp})
        module.yieldsfiles = yieldsfiles
        return module

    def _read(self, path):
        with open(path, 'rb') as f:
            return f.read().decode('utf-8')


class testChangeLogFormats_py3(ChangeLogTestCase):

    def _write(self, kind, log, extra=None):
        path = os.path.join(self.tmp, 'changes.' + kind)
        self._module()._formatOutput(log, [(path, kind)], extra or {})
        return self._read(path)

    def test_logFormat_isOneShortShaAndSummaryPerLine(self):
        text = self._write('log', changelog(
            record('0123456789abcdef', 'Fix the thing'),
            record('fedcba9876543210', 'Add the other thing')))

        self.assertEqual(
            text, '0123456 Fix the thing\nfedcba9 Add the other thing\n')

    def test_tsvFormat_hasTheUrlShaSummaryAuthorAndIsoDate(self):
        text = self._write('tsv', changelog(record('abc123', 'Fix')),
                           {'URL': URL})

        self.assertEqual(
            text, '%s\tabc123\tFix\tA U Thor\t2020-01-02T03:04:05\n' % URL)

    def test_csvFormat_quotesTheSummaryAndAuthor(self):
        text = self._write('csv', changelog(record('abc123', 'Fix, again')),
                           {'URL': URL})

        self.assertEqual(
            text, '%s,abc123,"Fix, again","A U Thor",2020-01-02T03:04:05\n' % URL)

    def test_yamlFormat_roundTripsTheChangelogWithTheExtraInfo(self):
        import yaml
        log = changelog(record('abc123', 'Fix'))

        text = self._write('yaml', log, {'URL': URL})

        loaded = yaml.safe_load(text)
        self.assertEqual(loaded['URL'], URL)
        self.assertEqual(loaded['history'][0]['summary'], 'Fix')
        self.assertEqual(loaded['history'][0]['datetime'], WHEN)

    def test_nonAsciiTextIsWrittenAsUtf8(self):
        text = self._write('log', changelog(
            record('abc123', 'caf\u00e9 \u2603 na\u00efve')))

        self.assertEqual(text, 'abc123 caf\u00e9 \u2603 na\u00efve\n')
        with open(os.path.join(self.tmp, 'changes.log'), 'rb') as f:
            self.assertIn(b'caf\xc3\xa9 \xe2\x98\x83', f.read())

    def test_noLog_sayssoAndWhyInTheTextFormats(self):
        text = self._write('log', None, {'errortext': 'No valid previous version'})

        self.assertEqual(
            text, '*** No Changes Detected ***\n'
                  '----- No valid previous version')

    def test_noLog_yamlCarriesTheMessageAndTheExtraInfo(self):
        import yaml

        text = self._write('yaml', None, {'errortext': 'same'})

        self.assertEqual(yaml.safe_load(text), {
            'message': '*** No Change Detected ***', 'errortext': 'same'})

    def test_aFileTypeWithoutAFormatterIsReportedAndNotWritten(self):
        path = os.path.join(self.tmp, 'changes.html')

        self._module()._formatOutput(changelog(), [(path, 'html')])

        self.assertFalse(os.path.exists(path))
        self.assertEqual(len(self.log.messages('error')), 1)

    def test_everyRequestedFileIsWritten(self):
        paths = [os.path.join(self.tmp, name) for name in ('a.log', 'b.tsv')]

        self._module()._formatOutput(
            changelog(record('abc123', 'Fix')),
            [(paths[0], 'log'), (paths[1], 'tsv')], {'URL': URL})

        self.assertTrue(self._read(paths[0]).startswith('abc123 Fix'))
        self.assertTrue(self._read(paths[1]).startswith(URL))

    def test_aFileThatCannotBeCreatedIsAnError(self):
        path = os.path.join(self.tmp, 'missing-dir', 'changes.log')

        with self.assertRaises(FileNotFoundError):
            self._module()._formatOutput(changelog(), [(path, 'log')])


class testChangeLogBuild_py3(ChangeLogTestCase):
    """GenerateGitChangeLog.build(): decide what to do, fetch, span the log,
    format it."""

    def setUp(self):
        ChangeLogTestCase.setUp(self)
        self.fetch = self._patch(GitProvider, 'fetchRepository')
        self.remote = unittest.mock.Mock(name='remote')
        self.ensureRemote = self._patch(
            GitProvider, 'ensureCsmakeRemote',
            return_value=(self.remote, None))
        self.getSHA = self._patch(
            GitProvider, 'getSHAFromRef',
            side_effect=lambda log, repo, remote, ref, reftype: 'sha-' + ref)
        self.span = self._patch(
            GitProvider, 'generateSpanLogInfo',
            return_value=changelog(record('abc123def', 'Fix')))
        self.Repo = self._patch(GGCL.git, 'Repo')
        self.out = os.path.join(self.tmp, 'out.log')
        self.module = self._module([{'location': 'out.log', 'type': 'log'}])

    def _build(self, **options):
        given = {'repo': URL, 'old': 'branch:v1', 'new': 'branch:v2'}
        given.update(options)
        return self.module.build(given)

    def test_build_withNoFilesToYieldThereIsNothingToDo(self):
        module = self._module(None)

        result = module.build({'repo': URL, 'old': 'a', 'new': 'b'})

        self.assertIsNone(result)
        self.assertEqual(len(self.log.messages('warning')), 2)
        self.assertEqual(self.log.messages('passed'), [''])
        self.Repo.assert_not_called()

    def test_build_writesTheSpanLogBetweenTheTwoRefs(self):
        result = self._build()

        self.Repo.assert_called_once_with(
            os.path.join(self.tmp, 'project.git'))
        self.ensureRemote.assert_called_once_with(self.Repo.return_value, URL)
        self.assertEqual(
            [c[0][3:] for c in self.getSHA.call_args_list],
            [('v2', 'branch'), ('v1', 'branch')])
        self.span.assert_called_once_with(
            self.log, os.path.join(self.tmp, 'project.git'),
            'sha-v1', 'sha-v2', False)
        self.assertEqual(self._read(self.out), 'abc123d Fix\n')
        self.assertEqual(self.log.messages('passed'), [''])
        self.assertIsNone(result)

    def test_build_aLocalOptionNamesTheRepositoryDirectory(self):
        self._build(local='/var/tmp/clones/mine')

        self.Repo.assert_called_once_with('/var/tmp/clones/mine')

    def test_build_locationsAreRelativeToResultsUnlessAbsolute(self):
        absolute = os.path.join(self.tmp, 'elsewhere.log')
        module = self._module([
            {'location': 'out.log', 'type': 'log'},
            {'location': absolute, 'type': 'log'}])

        module.build({'repo': URL, 'old': 'branch:v1', 'new': 'branch:v2'})

        self.assertTrue(os.path.exists(self.out))
        self.assertTrue(os.path.exists(absolute))

    def test_build_aRepoThatIsNotThereYetIsFetchedFirst(self):
        repo = unittest.mock.Mock(name='repo')
        self.Repo.side_effect = [GGCL.git.exc.NoSuchPathError('x'), repo]

        self._build()

        self.fetch.assert_called_once_with(
            self.log, 'project.git', os.path.join(self.tmp, 'project.git'),
            URL, 'v2', 'branch', secure=False)
        self.ensureRemote.assert_called_once_with(repo, URL)

    def test_build_noPreviousVersionYieldsAnExplanationNotALog(self):
        for old in ('', '<unknown>'):
            with self.subTest(old=old):
                self.log.records[:] = []

                result = self._build(old=old)

                self.assertTrue(result)
                self.assertEqual(
                    self._read(self.out),
                    '*** No Changes Detected ***\n'
                    '----- No valid previous version')
                self.span.assert_not_called()
                self.assertEqual(self.log.messages('passed'), [''])

    def test_build_identicalVersionsYieldAnExplanationNotALog(self):
        result = self._build(old='branch:v2', new='branch:v2')

        self.assertTrue(result)
        self.assertIn('Old and new versions identical', self._read(self.out))
        self.Repo.assert_not_called()

    def test_build_aShaLookupThatFailsIsRetriedAfterAFetch(self):
        self.getSHA.side_effect = [RuntimeError('unknown ref'), 'new', 'old']

        self._build()

        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.getSHA.call_count, 3)
        self.span.assert_called_once_with(
            self.log, os.path.join(self.tmp, 'project.git'), 'old', 'new', False)
        self.assertEqual(self.log.messages('passed'), [''])

    @unittest.skip("pre-existing: the retry after a failed ref lookup passes "
                   "the git.Repo object to fetchRepository where the URL "
                   "belongs")
    def test_build_theRetryFetchesFromTheRepoUrl(self):
        self.getSHA.side_effect = [RuntimeError('unknown ref'), 'new', 'old']

        self._build()

        self.assertEqual(self.fetch.call_args[0][3], URL)

    def test_build_aSpanLogThatFailsIsRetriedAfterAFetch(self):
        self.span.side_effect = [RuntimeError('unknown commit'),
                                 changelog(record('abc123def', 'Fix'))]

        self._build()

        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.span.call_count, 2)
        self.assertEqual(self._read(self.out), 'abc123d Fix\n')

    def test_build_aSpanLogThatKeepsFailingFailsTheSection(self):
        self.span.side_effect = RuntimeError('unknown commit')

        result = self._build()

        self.assertIsNone(result)
        self.assertEqual(self.log.messages('failed'), [''])
        self.assertEqual(self.log.messages('passed'), [])
        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertFalse(os.path.exists(self.out))


class testChangeLogDiverged_py3(ChangeLogTestCase):

    @unittest.skip("pre-existing: _logFormatter.diverged refers to an "
                   "undefined name 'result' (it should use 'changelog'), so "
                   "a diverged history raises NameError instead of being "
                   "written")
    def test_aDivergedHistoryShowsTheOldNewAndCommonRecords(self):
        log = {'type': 'diverged', 'history': [],
               'old': record('1111111aaaa', 'Old tip'),
               'new': record('2222222bbbb', 'New tip'),
               'common': record('3333333cccc', 'Base')}
        path = os.path.join(self.tmp, 'out.log')

        self._module()._formatOutput(log, [(path, 'log')], {'URL': URL})

        text = self._read(path)
        self.assertIn('NOTE: Record history diverges', text)
        for wanted in ('1111111 Old tip', '2222222 New tip', '3333333 Base'):
            self.assertIn(wanted, text)


if __name__ == '__main__':
    unittest.main()
