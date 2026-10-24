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
"""Unit tests for the Python 3 conversion of CsmakeModules/GitTagRefs.py.

Only the two pure helpers that walk csversion sources are exercised (the
iteritems() -> items() conversions); the module is imported through the
test-only Csmake -> CsmakeCore alias in csmake_alias.py.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import importlib
import sys
import unittest

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
                'Csmake', 'CsmakeCore'):
            raise unittest.SkipTest(
                "GitTagRefs needs '%s', which is not available" % exc.name)
        raise


GitTagRefs = load_gitTagRefs().GitTagRefs

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


if __name__ == '__main__':
    unittest.main()
