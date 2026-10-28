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
"""Unit tests for CsmakeModules/GitTagRefs.py.

The two pure helpers that walk csversion sources (the iteritems() -> items()
conversions) are exercised directly; tag() is exercised with GitProvider and
git.Repo mocked, a real PyYAML parsing real (temp file) manifests, and csmake
core's file manager replaced by a stub.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import importlib
import os
import shutil
import sys
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


def load_gitTagRefs():
    csmake_alias.install()  # SkipTest if csmake core cannot be found
    if support.REPO not in sys.path:
        sys.path.insert(0, support.REPO)
    try:
        return importlib.import_module('CsmakeModules.GitTagRefs')
    except ImportError as exc:
        if (exc.name or '').split('.')[0] in support.OPTIONAL_LIBS + (
                'CsmakeCore',):
            raise unittest.SkipTest(
                "GitTagRefs needs '%s', which is not available" % exc.name)
        raise


GTR = load_gitTagRefs()   # the module
GitTagRefs = GTR.GitTagRefs

URL_A = 'https://git.example/a.git'
URL_B = 'https://git.example/b.git'


def git_source(url, ref):
    return ('git', {'URL': url, 'REF': ref})


class testGitTagRefs_py3(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.tagger = object.__new__(GitTagRefs)
        self.tagger.log = self.log
        self.tagger.tag = 'rel-1'
        self.tagger.multiref = False

    def test_processCsversionSources_groupsGitRefsBySourceAndUrl(self):
        sources = {
            'srcA': {'build1': git_source(URL_A, 'sha1'),
                     'build2': git_source(URL_A, 'sha1'),
                     'docs': ('tar', {'URL': 'https://x/docs.tgz'})},
            'srcB': {'build1': git_source(URL_B, 'sha3')}}
        gitrefs = {}

        self.tagger._processCsversionSources(sources, gitrefs)

        self.assertEqual(gitrefs, {
            'srcA': {URL_A: [[{'URL': URL_A, 'REF': 'sha1'}, 'build1'],
                             [{'URL': URL_A, 'REF': 'sha1'}, 'build2']]},
            'srcB': {URL_B: [[{'URL': URL_B, 'REF': 'sha3'}, 'build1']]}})

    def test_processCsversionSources_nonGitSourcesAreIgnored(self):
        gitrefs = {}

        self.tagger._processCsversionSources(
            {'srcA': {'build1': ('tar', {'URL': 'x'})}}, gitrefs)

        self.assertEqual(gitrefs, {})

    def _gitrefs(self, ref2='sha1'):
        return {'srcA': {URL_A: [[{'URL': URL_A, 'REF': 'sha1'}, 'build1'],
                                 [{'URL': URL_A, 'REF': ref2}, 'build2']]},
                'srcB': {URL_B: [[{'URL': URL_B, 'REF': 'sha3'}, 'build1']]}}

    def test_createGitTagList_oneTagPerRepoWhenBuildsAgree(self):
        taglist = self.tagger._createGitTagList(self._gitrefs())

        self.assertEqual(taglist, [(URL_A, 'rel-1', 'sha1'),
                                   (URL_B, 'rel-1', 'sha3')])

    def test_createGitTagList_multirefAlsoTagsEveryBuild(self):
        self.tagger.multiref = True

        taglist = self.tagger._createGitTagList(self._gitrefs(ref2='sha2'))

        self.assertEqual(taglist, [
            (URL_A, 'rel-1_build1', 'sha1'),
            (URL_A, 'rel-1_build2', 'sha2'),
            (URL_A, 'rel-1', 'sha1'),
            (URL_B, 'rel-1_build1', 'sha3'),
            (URL_B, 'rel-1', 'sha3')])

    def test_createGitTagList_disagreeingRefsAreAnErrorWithoutMultiref(self):
        with self.assertRaisesRegex(ValueError, 'Inconsistent References'):
            self.tagger._createGitTagList(self._gitrefs(ref2='sha2'))

        self.assertEqual(len(self.log.problems), 5)
        self.assertIn(URL_A, self.log.problems[1])
        self.assertIn('build2', self.log.problems[2])


MANIFEST = """\
sources:
  srcA:
    build1: [git, {{URL: "{url_a}", REF: "{ref_a}"}}]
    build2: [git, {{URL: "{url_a}", REF: "{ref_a}"}}]
  srcB:
    build1: [git, {{URL: "{url_b}", REF: "branch:master"}}]
"""


class testGitTagRefs_tag_py3(unittest.TestCase):
    """GitTagRefs.tag(): manifests in, fetch + tag + push out."""

    def setUp(self):
        self.log = support.FakeLog()
        self.tmp = tempfile.mkdtemp(prefix='csmake-tagrefs-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

        self.fetch = self._patch(GTR.GitProvider, 'fetchRepository')
        self.remote = unittest.mock.Mock(name='remote')
        self.ensureRemote = self._patch(
            GTR.GitProvider, 'ensureCsmakeRemote',
            return_value=(self.remote, None))
        self.pushTag = self._patch(GTR.GitProvider, 'pushTag')
        self.Repo = self._patch(GTR.git, 'Repo')

    def _patch(self, target, name, **kwargs):
        patch = unittest.mock.patch.object(target, name, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock

    def _manifest(self, text, name='manifest.yml'):
        path = os.path.join(self.tmp, name)
        with open(path, 'w') as f:
            f.write(text)
        return path

    def _standardManifest(self, ref_a='branch:master', **urls):
        return self._manifest(MANIFEST.format(
            url_a=urls.get('url_a', URL_A), ref_a=ref_a,
            url_b=urls.get('url_b', URL_B)))

    def _tag(self, *paths, **options):
        tagger = object.__new__(GitTagRefs)
        tagger.log = self.log
        tagger.env = types.SimpleNamespace(env={'RESULTS': '/results'})
        fileManager = unittest.mock.Mock()
        fileManager.resolveFileMappings.return_value = [
            types.SimpleNamespace(index={'location': path}) for path in paths]
        tagger._getFileManager = lambda: fileManager
        tagger._parseCommaAndNewlineList = lambda text: [
            part.strip() for part in text.replace('\n', ',').split(',')
            if part.strip()]
        options = dict(options, files='\n'.join(paths))
        options.setdefault('tag', 'rel-1')
        result = tagger.tag(options)
        self.fileManager = fileManager
        return result

    def test_tag_fetchesTagsAndPushesEachRepoOnce(self):
        manifest = self._standardManifest()

        self._tag(manifest)

        self.fileManager.resolveFileMappings.assert_called_once_with(
            [manifest], True)
        self.assertEqual(self.fetch.call_args_list, [
            unittest.mock.call(self.log, URL_A, '/results/a.git', URL_A,
                               'master', 'branch', secure=False),
            unittest.mock.call(self.log, URL_B, '/results/b.git', URL_B,
                               'master', 'branch', secure=False)])
        self.assertEqual(self.pushTag.call_args_list, [
            unittest.mock.call(self.Repo.return_value, 'rel-1',
                               self.remote, None)] * 2)
        self.Repo.assert_any_call('/results/a.git')
        self.assertEqual(self.log.messages('passed'), [''])
        self.assertEqual([], self.log.problems)

    def test_tag_optionsChooseTheMessageSecurityAndLocalDirectory(self):
        manifest = self._standardManifest()

        self._tag(manifest, message='Release 1', secure='True',
                  local='/var/tmp/repos')

        self.assertEqual(self.fetch.call_args_list[0], unittest.mock.call(
            self.log, URL_A, '/var/tmp/repos/a.git', URL_A,
            'master', 'branch', secure=True))
        self.assertEqual(self.pushTag.call_args_list[0][0][3], 'Release 1')

    def test_tag_aManifestThatIsAListOfSourcesIsAccepted(self):
        manifest = self._manifest(
            '- srcA:\n'
            '    build1: [git, {URL: "%s", REF: "branch:master"}]\n' % URL_A)

        self._tag(manifest)

        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_tag_refsThatDisagreeFailWithoutFetchingAnything(self):
        manifest = self._manifest(
            'sources:\n'
            '  srcA:\n'
            '    build1: [git, {URL: "%s", REF: "branch:one"}]\n'
            '    build2: [git, {URL: "%s", REF: "branch:two"}]\n'
            % (URL_A, URL_A))

        result = self._tag(manifest)

        self.assertIsNone(result)
        self.assertEqual(self.log.messages('failed'), [''])
        self.fetch.assert_not_called()
        self.pushTag.assert_not_called()

    def test_tag_urlsThatAreNotUsableAreSkippedWithAWarning(self):
        manifest = self._standardManifest(
            url_a='https://git.example/(draft).git', url_b='  ')

        self._tag(manifest)

        self.fetch.assert_not_called()
        self.assertEqual(len(self.log.messages('warning')), 2)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_tag_aRelativeFileUrlIsMadeAbsolute(self):
        manifest = self._standardManifest(url_b='file://./b.git')

        self._tag(manifest)

        expected = 'file://' + os.path.abspath('.') + '/b.git'
        self.assertEqual(self.fetch.call_args_list[1][0][1], expected)
        self.assertEqual(self.fetch.call_args_list[1][0][3], expected)

    def test_tag_anExistingTagIsNotAnError(self):
        manifest = self._standardManifest()
        self.pushTag.side_effect = GTR.git.exc.GitCommandError(
            ['git', 'push'], 128, stderr='tag already exists')

        self._tag(manifest)

        self.assertEqual(self.pushTag.call_count, 2)
        self.assertEqual(len(self.log.messages('info')), 2)
        self.assertEqual(self.log.messages('passed'), [''])

    def test_tag_anyOtherPushFailureIsRaised(self):
        manifest = self._standardManifest()
        self.pushTag.side_effect = GTR.git.exc.GitCommandError(
            ['git', 'push'], 1, stderr='remote hung up')

        with self.assertRaises(GTR.git.exc.GitCommandError):
            self._tag(manifest)

        self.assertEqual(self.pushTag.call_count, 1)
        self.assertEqual(self.log.messages('passed'), [])

    def test_tag_aFailedFetchStopsBeforeAnythingIsTagged(self):
        manifest = self._standardManifest()
        self.fetch.side_effect = OSError('network is unreachable')

        with self.assertRaises(OSError):
            self._tag(manifest)

        self.pushTag.assert_not_called()

    def test_tag_aMalformedManifestIsAnError(self):
        manifest = self._manifest('sources: [unterminated\n')

        with self.assertRaises(GTR.yaml.YAMLError):
            self._tag(manifest)

        self.fetch.assert_not_called()

    def test_tag_aManifestCannotInstantiatePythonObjects(self):
        # a manifest is data; loading it must not execute anything
        manifest = self._manifest(
            'sources: !!python/object/apply:os.getcwd []\n')

        with self.assertRaises(GTR.yaml.YAMLError):
            self._tag(manifest)

        self.fetch.assert_not_called()

    def test_tag_aMissingManifestFileIsAnError(self):
        with self.assertRaises(FileNotFoundError):
            self._tag(os.path.join(self.tmp, 'absent.yml'))


if __name__ == '__main__':
    unittest.main()
