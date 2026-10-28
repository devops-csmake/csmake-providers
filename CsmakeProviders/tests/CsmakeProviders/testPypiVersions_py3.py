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
"""Unit tests for how PypiProvider.py represents versions that are not PEP 440
conformant.

packaging 22 removed LegacyVersion.  PypiProvider asks for one through a small
helper that uses packaging's LegacyVersion if it still has it and otherwise a
local stand-in with the same ordering.  Both paths are exercised by swapping
the module's 'packaging.version' for a fake with and without LegacyVersion.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import types
import unittest
import unittest.mock
import warnings

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

PypiProvider = support.import_provider('PypiProvider')
packaging_version = PypiProvider.version      # the real packaging.version

INDEX = 'http://index.example/simple/'
PACKAGE_PAGE = INDEX + 'mypkg/'

# (filename, heuristic, package, build, version text): the non PEP 440 names
# of the owner's canonical list in testPypiProvider_basic.py
NON_PEP440_NAMES = [
    ('mypackage-is-v(42.4.1Thisisdog)-3iohagi.tar.gz',
     '6a', 'mypackage-is', '3iohagi', '42.4.1Thisisdog'),
    ('mypackage-is-v(42.4.1-Thisisdog)-3iohagi.tar.gz',
     '6a', 'mypackage-is', '3iohagi', '42.4.1-Thisisdog'),
    ('mypackage-is-v(42.4.1Thisisdog)3iohagi.tar.gz',
     '6b', 'mypackage-is', None, 'v(42.4.1Thisisdog)3iohagi'),
    ('mypackage-is-v(42.4.1Thisisdog)3i-33o-3hagi.tar.gz',
     '6b', 'mypackage-is', '3hagi', 'v(42.4.1Thisisdog)3i-33o'),
    ('mypackage-is-42.4.1Thisisdog3i-33o-hagi.tar.gz',
     '6d', 'mypackage-is-42.4.1Thisisdog3i-33o', None, 'hagi'),
    ('mypackage-is-42.4.1Thisisdog3i-33o-3hagi.tar.gz',
     '6c', 'mypackage-is-42.4.1Thisisdog3i', '3hagi', '33o'),
    ('functools32-3.2.3_1.tar.gz',
     '6d', 'functools32', None, '3.2.3_1'),
    ('pylibmc-1.1.1jarn1.tar.gz',
     '6d', 'pylibmc', None, '1.1.1jarn1')]

# What packaging 21's LegacyVersion sorts this list into (recorded from it)
CORPUS = ['1.0', '1.1', '1.10', '1.2', '1.0rc1', '1.0pre1', '1.0-final',
          '1.0-1', '1.0.0', 'hagi', 'Hagi', 'v(42.4.1Thisisdog)3iohagi',
          '3.2.3_1', '1.1.1jarn1', '', 'abc', 'abd', '1.0dev', '1.0a', '1.0b',
          '1.0c', 'weird-ver', '2.0.0-beta', '01.1']
LEGACY_ORDER = [
    'abc', 'abd', '', 'hagi', 'Hagi', 'v(42.4.1Thisisdog)3iohagi', 'weird-ver',
    '1.0dev', '1.0a', '1.0b', '1.0c', '1.0rc1', '1.0pre1', '1.0', '1.0.0',
    '1.0-final', '1.0-1', '1.1', '01.1', '1.1.1jarn1', '1.2', '1.10',
    '2.0.0-beta', '3.2.3_1']


class FakeLegacyVersion(object):
    """What packaging's LegacyVersion class is to PypiProvider: built from a
    string, printable."""

    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


def packaging_with_legacy():
    return types.SimpleNamespace(
        Version=packaging_version.Version,
        InvalidVersion=packaging_version.InvalidVersion,
        LegacyVersion=FakeLegacyVersion)


def packaging_without_legacy():
    return types.SimpleNamespace(
        Version=packaging_version.Version,
        InvalidVersion=packaging_version.InvalidVersion)


class testPypiVersions_py3(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()

    def _packaging(self, module):
        patch = unittest.mock.patch.object(PypiProvider, 'version', module)
        patch.start()
        self.addCleanup(patch.stop)

    def _context(self):
        controller = types.SimpleNamespace(
            log=self.log, getContext=lambda name: None)
        return PypiProvider.PypiContext({'name': 'simple'}, controller)

    # --- the helper ---------------------------------------------------------

    def test_nonPep440Version_usesLegacyVersionWhilePackagingHasIt(self):
        self._packaging(packaging_with_legacy())

        found = PypiProvider._nonPep440Version('weird')

        self.assertIsInstance(found, FakeLegacyVersion)
        self.assertEqual(found.text, 'weird')

    def test_nonPep440Version_fallsBackOncePackagingDroppedIt(self):
        self._packaging(packaging_without_legacy())

        found = PypiProvider._nonPep440Version('weird')

        self.assertIsInstance(found, PypiProvider._NonPep440Version)
        self.assertEqual(str(found), 'weird')

    def test_nonPep440Version_neverCrashesOnAnOddString(self):
        self._packaging(packaging_without_legacy())
        for text in ('', ' ', '!!!', '1..2', 'v(', '--', '\u00fcn\u00ef',
                     '1.0\n', 'x' * 5000, '\x00'):
            with self.subTest(text=text[:20]):
                found = PypiProvider._nonPep440Version(text)

                self.assertEqual(str(found), text)
                hash(found)
                self.assertEqual(found, PypiProvider._nonPep440Version(text))

    # --- the stand-in -------------------------------------------------------

    def _loose(self, text):
        return PypiProvider._NonPep440Version(text)

    def test_standIn_printsAsTheStringItWasGiven(self):
        loose = self._loose('v(42.4.1)Thisisdog')

        self.assertEqual(str(loose), 'v(42.4.1)Thisisdog')
        self.assertEqual(repr(loose), "<NonPep440Version('v(42.4.1)Thisisdog')>")

    def test_standIn_orderingMatchesTheLegacyVersionItReplaces(self):
        ordered = sorted(self._loose(text) for text in CORPUS)

        self.assertEqual([str(v) for v in ordered], LEGACY_ORDER)

    def test_standIn_agreesWithTheRealLegacyVersionWhenInstalled(self):
        legacy = getattr(packaging_version, 'LegacyVersion', None)
        if legacy is None:
            self.skipTest("this packaging has no LegacyVersion to compare to")
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            real = [legacy(text) for text in CORPUS]
        loose = [self._loose(text) for text in CORPUS]

        for index, left in enumerate(loose):
            for other, right in enumerate(loose):
                self.assertEqual(left < right, real[index] < real[other])
                self.assertEqual(left == right, real[index] == real[other])
        self.assertEqual([str(v) for v in sorted(real)], LEGACY_ORDER)

    def test_standIn_equalityIgnoresCaseAndTrailingZeros(self):
        self.assertEqual(self._loose('Hagi'), self._loose('hagi'))
        self.assertEqual(hash(self._loose('Hagi')), hash(self._loose('hagi')))
        self.assertEqual(self._loose('1.0'), self._loose('1.0.0'))
        self.assertNotEqual(self._loose('1.0'), self._loose('1.1'))
        self.assertEqual(len({self._loose('Hagi'), self._loose('hagi')}), 1)

    def test_standIn_sortsBeforeEveryPep440Version(self):
        loose = self._loose('zzz')
        pep440 = packaging_version.Version('0.0.1')

        self.assertTrue(loose < pep440)
        self.assertTrue(loose <= pep440)
        self.assertTrue(pep440 > loose)
        self.assertFalse(pep440 < loose)
        self.assertFalse(loose >= pep440)
        self.assertNotEqual(loose, pep440)
        self.assertNotEqual(pep440, loose)
        self.assertEqual(sorted([pep440, loose]), [loose, pep440])

    def test_standIn_cannotBeComparedWithPlainStrings(self):
        with self.assertRaises(TypeError):
            self._loose('1.0') < '1.0'
        self.assertNotEqual(self._loose('1.0'), '1.0')

    def test_standIn_looksLikeAPackagingVersionToCallersThatAsk(self):
        loose = self._loose('1.0-weird')

        self.assertEqual(loose.public, '1.0-weird')
        self.assertEqual(loose.base_version, '1.0-weird')
        self.assertEqual(loose.epoch, -1)
        self.assertFalse(loose.is_prerelease)
        self.assertFalse(loose.is_postrelease)
        self.assertFalse(loose.is_devrelease)

    # --- the version heuristics, with and without LegacyVersion -----------

    def test_splitPypiName_nonPep440NamesGetALegacyVersionWhenPackagingHasOne(self):
        self._packaging(packaging_with_legacy())
        context = self._context()
        for filename, heuristic, package, build, text in NON_PEP440_NAMES:
            with self.subTest(filename=filename):
                result = context._splitPypiName(filename, {}, None)

                self.assertEqual(
                    (result['heuristic'], result['package'], result['build']),
                    (heuristic, package, build))
                self.assertIsInstance(result['version'], FakeLegacyVersion)
                self.assertEqual(result['version'].text, text)

    def test_splitPypiName_nonPep440NamesStillParseWithoutLegacyVersion(self):
        self._packaging(packaging_without_legacy())
        context = self._context()
        for filename, heuristic, package, build, text in NON_PEP440_NAMES:
            with self.subTest(filename=filename):
                result = context._splitPypiName(filename, {}, None)

                self.assertEqual(
                    (result['heuristic'], result['package'], result['build']),
                    (heuristic, package, build))
                self.assertIsInstance(
                    result['version'], PypiProvider._NonPep440Version)
                self.assertEqual(str(result['version']), text)

    def test_splitPypiName_aGivenPackageNameStillReachesTheFallback(self):
        self._packaging(packaging_without_legacy())

        result = self._context()._splitPypiName(
            'pylibmc-1.1.1jarn1.tar.gz', {}, 'pylibmc')

        self.assertEqual(str(result['version']), '1.1.1jarn1')

    def test_splitPypiName_pep440NamesAreUnaffectedByEitherPath(self):
        for module in (packaging_with_legacy(), packaging_without_legacy()):
            self._packaging(module)
            result = self._context()._splitPypiName(
                'mypkg-1.0.tar.gz', {}, 'mypkg')

            self.assertEqual(result['version'], packaging_version.Version('1.0'))

    def test_splitPypiName_aNameWithNoVersionAtAllIsStillRejected(self):
        self._packaging(packaging_without_legacy())

        with self.assertRaises(ValueError):
            self._context()._splitPypiName('mypkg.tar.gz', {}, None)


class testPypiControllerPins_py3(unittest.TestCase):
    """The initial constraints a constraining index produces must be
    requirement text packaging accepts, whatever the version looks like."""

    def setUp(self):
        self.log = support.FakeLog()

    def _urlopen(self, routes):
        urlopen = support.FakeUrlopen(routes)
        patch = unittest.mock.patch.object(
            PypiProvider.urllib.request, 'urlopen', urlopen)
        patch.start()
        self.addCleanup(patch.stop)

    def _controller(self, **options):
        options.update(chroot=None, interfaces=['127.0.0.1'], port=None)
        configManager = types.SimpleNamespace(register=lambda *a, **k: None)
        return PypiProvider.PypiController(configManager, self.log, options)

    def test_pinSpecifier_pep440VersionsAreComparedAsVersions(self):
        pin = PypiProvider._pinSpecifier(packaging_version.Version('1.0'))

        self.assertEqual(pin, '==1.0')

    def test_pinSpecifier_otherVersionsAreComparedAsText(self):
        pin = PypiProvider._pinSpecifier(
            PypiProvider._NonPep440Version('weird-ver'))

        self.assertEqual(pin, '===weird-ver')

    def test_aConstrainingIndexWithANonPep440VersionStillStarts(self):
        self._urlopen({
            INDEX: b'<a href="mypkg/">mypkg</a>',
            PACKAGE_PAGE: b'<a href="mypkg-1.0.tar.gz">mypkg-1.0.tar.gz</a>'
                          b'<a href="mypkg-weird.tar.gz">mypkg-weird.tar.gz</a>'})

        controller = self._controller(**{'constraining-indicies': INDEX})

        self.assertEqual(controller.getInitialConstraints(),
                         ['mypkg==1.0|===weird'])
        self.assertEqual([], self.log.problems)

    def test_theConstrainedContextStillOffersBothVersions(self):
        self._urlopen({
            INDEX: b'<a href="mypkg/">mypkg</a>',
            PACKAGE_PAGE: b'<a href="mypkg-1.0.tar.gz">mypkg-1.0.tar.gz</a>'
                          b'<a href="mypkg-weird.tar.gz">mypkg-weird.tar.gz</a>'})
        controller = self._controller(**{'constraining-indicies': INDEX})
        handler = support.FakeHandler()

        controller.getContext('simple').listVersions('mypkg', handler)

        page = handler.wfile.getvalue()
        self.assertIn(b'<a href="mypkg-1.0.tar.gz">', page)
        self.assertIn(b'<a href="mypkg-weird.tar.gz">', page)


if __name__ == '__main__':
    unittest.main()
