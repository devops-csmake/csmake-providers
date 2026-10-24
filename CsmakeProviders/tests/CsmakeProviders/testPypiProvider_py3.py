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
"""Unit tests for the Python 3 conversion of PypiProvider.py (any OS).

(testPypiProvider_basic.py needs csmake's test harness, a chroot and a
Linux-only 'pyinotify'; these need none of that.)

Every boundary is faked: urllib.request.urlopen answers from a table of
BYTES responses, the HTTP handler is a FakeHandler with a binary wfile,
subprocess.check_output is a FakeCheckOutput.  Real temp files are used only
where the unit's job is file I/O (the cache is read 'rb' and written 'wb').

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import errno
import hashlib
import io
import os
import shutil
import ssl
import tempfile
import traceback
import types
import unittest
import unittest.mock
import urllib.error

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

PypiProvider = support.import_provider('PypiProvider')
version = PypiProvider.version  # the 'packaging' version module

INDEX = 'http://index.example/simple/'
PACKAGE_PAGE = INDEX + 'mypkg/'
FILE1 = 'http://files.example/packages/mypkg-1.0.tar.gz'
FILE2 = 'http://index.example/packages/mypkg-2.0.tar.gz'

# Every byte value, so none of it is valid UTF-8 or survives newline
# translation by accident, and longer than the 10240 byte copy chunk.
PAYLOAD = bytes(bytearray(range(256))) * 100 + b'\r\n\x1a\xff\xfe'

INDEX_PAGE = (b'<html><body>\n'
              b'<a href="mypkg/">mypkg</a><br/>\n'
              b'<a href="caf%C3%A9/">caf\xc3\xa9</a><br/>\n'
              b'</body></html>\n')
PACKAGE_PAGE_BODY = (
    b'<html><body>\n'
    b'<a href="http://files.example/packages/mypkg-1.0.tar.gz'
    b'#md5=0123456789abcdef">mypkg-1.0.tar.gz</a><br/>\n'
    b'<a href="../../packages/mypkg-2.0.tar.gz">mypkg-2.0.tar.gz</a><br/>\n'
    b'</body></html>\n')

HEADER = (b'<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">'
          b'<html>\n<title>csmake PyPI Proxy</title>\n<body>\n'
          b'<h2>csmake PyPI Proxy: %s</h2>\n')
FOOTER = b'</body>\n</html>\n'


def standard_page(title, *entries):
    return HEADER % title + b''.join(entries) + FOOTER


class FakeController(object):
    """The part of PypiController that PypiContext uses."""

    def __init__(self, log, cache=None):
        self.log = log
        self.image = {}
        self.services = {}
        self.cache = cache
        self.contexts = {}

    def getPypiImage(self):
        return (self.image, self.services)

    def lockPackageList(self):
        pass

    def unlockPackageList(self):
        pass

    def getCachePath(self):
        return self.cache

    def getContext(self, name):
        return self.contexts.get(name)


class testPypiProvider_py3(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.tmp = tempfile.mkdtemp(prefix='csmake-pypi-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _urlopen(self, routes):
        urlopen = support.FakeUrlopen(routes)
        self._patch(PypiProvider.urllib.request, 'urlopen', urlopen)
        return urlopen

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock

    def _context(self, indicies=INDEX, cache=None, **info):
        controller = FakeController(self.log, cache)
        info = dict(info, name='simple')
        if indicies is not None:
            info['indicies'] = indicies
        context = PypiProvider.PypiContext(info, controller)
        controller.contexts['simple'] = context
        return context, controller

    def _pull(self, url, paths=None, onfail=None):
        thread = PypiProvider.PullLinksThread(url, paths, self.log, onfail)
        thread.run()  # what start() would run in the thread
        return thread

    def _indexRoutes(self, **more):
        routes = {INDEX: INDEX_PAGE, PACKAGE_PAGE: PACKAGE_PAGE_BODY,
                  FILE1: (PAYLOAD, {'Content-Type': 'application/x-gzip',
                                    'Content-Length': str(len(PAYLOAD))})}
        routes.update(more)
        return routes

    # --- PullLinksThread ----------------------------------------------------

    def test_pullLinks_decodesTheBytesPageAndUnquotesHrefs(self):
        # urlopen().read() is bytes; the page must be decoded before it is
        # split into links, and %-escapes in hrefs are unquoted as UTF-8.
        urlopen = self._urlopen({INDEX: INDEX_PAGE})

        thread = self._pull(INDEX)

        self.assertEqual(
            thread.getLinks(),
            (INDEX, [('mypkg/', 'mypkg'), ('café/', 'café')]))
        self.assertEqual(urlopen.calls, [INDEX])

    def test_pullLinks_invalidUtf8InThePageDoesNotAbortTheParse(self):
        self._urlopen({INDEX: b'<a href="a/">a\xff</a><a href="b/">b</a>'})

        thread = self._pull(INDEX)

        self.assertEqual(thread.getLinks()[1],
                         [('a/', 'a�'), ('b/', 'b')])

    def test_pullLinks_malformedAnchorsAreSkippedAndLogged(self):
        self._urlopen({INDEX: b'<a name="top">x</a><a href=bare>y</a>'
                              b'<a href="good/">good</a>'})

        thread = self._pull(INDEX)

        self.assertEqual(thread.getLinks()[1], [('good/', 'good')])
        self.assertEqual(len(self.log.messages('info')), 2)

    def test_pullLinks_aPageWithoutAnchorsHasNoLinks(self):
        self._urlopen({INDEX: b'<html><body>nothing here</body></html>'})

        self.assertEqual(self._pull(INDEX).getLinks(), (INDEX, []))

    def test_pullLinks_httpErrorIsReraisedWithTheOriginalTraceback(self):
        # Python 2's three argument raise became with_traceback()
        self._urlopen({})

        thread = self._pull(INDEX)

        try:
            thread.getLinks()
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 404)
            frames = [f.name for f in traceback.extract_tb(error.__traceback__)]
            self.assertIn('_doPaths', frames)
        else:
            self.fail("getLinks() should have raised the HTTPError")

    def test_pullLinks_networkErrorIsReraised(self):
        self._urlopen({INDEX: urllib.error.URLError('connection refused')})

        thread = self._pull(INDEX)

        with self.assertRaises(urllib.error.URLError):
            thread.getLinks()

    def test_pullLinks_triesTheNextPathWhenOneFails(self):
        urlopen = self._urlopen({PACKAGE_PAGE: PACKAGE_PAGE_BODY})

        thread = self._pull(INDEX, ('missing', 'mypkg'))

        self.assertEqual(urlopen.calls, [INDEX + 'missing/', PACKAGE_PAGE])
        url, links = thread.getLinks()
        self.assertEqual(url, PACKAGE_PAGE)
        self.assertEqual(thread.getPath(), 'mypkg')
        self.assertEqual(len(links), 2)

    def test_pullLinks_failureCallbackCanSupplyAFallbackLocation(self):
        urlopen = self._urlopen({PACKAGE_PAGE: PACKAGE_PAGE_BODY})
        seen = []

        def onfail(thread):
            seen.append(thread)
            return (INDEX, ('mypkg',))
        thread = self._pull(INDEX, ('nope',), onfail)

        self.assertEqual(seen, [thread])
        self.assertEqual(urlopen.calls, [INDEX + 'nope/', PACKAGE_PAGE])
        self.assertEqual(thread.getLinks()[0], PACKAGE_PAGE)

    def test_pullLinks_pathsThatAreNotATupleAreRejected(self):
        self._urlopen({})

        thread = self._pull(INDEX, 'mypkg')

        with self.assertRaises(TypeError):
            thread.getLinks()

    # --- the HTML pages ---------------------------------------------------

    def test_sendStandardHTMLPage_writesUtf8BytesAndCountsBytes(self):
        # Built as text, encoded exactly once for the binary socket, with
        # Content-Length counting bytes rather than characters.
        context, _ = self._context(indicies=None)
        handler = support.FakeHandler()
        page = context._startStandardHTMLPage('Pkg café')
        page.write('<p>café</p>\n')

        context._sendStandardHTMLPage(page, handler)

        expected = standard_page(b'Pkg caf\xc3\xa9', b'<p>caf\xc3\xa9</p>\n')
        self.assertNotEqual(len(expected), len(expected.decode('utf-8')))
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.header('Content-type'), 'text/html')
        self.assertEqual(handler.header('Content-Length'), str(len(expected)))
        self.assertTrue(handler.ended)
        self.assertEqual(handler.wfile.getvalue(), expected)
        self.assertTrue(page.closed)

    def test_nullHTTPHandler_collectsTheResponseBytes(self):
        context, _ = self._context(indicies=None)
        handler = PypiProvider.PypiContext.NullHTTPHandler()

        context._sendStandardHTMLPage(
            context._startStandardHTMLPage('x'), handler)

        self.assertIsInstance(handler.wfile, io.BytesIO)
        self.assertEqual(handler.wfile.getvalue(), standard_page(b'x'))

    def test_listPackages_rendersTheIndexAsExactBytes(self):
        urlopen = self._urlopen({INDEX: INDEX_PAGE})
        context, controller = self._context()
        handler = support.FakeHandler()

        result = context.listPackages(handler)

        expected = standard_page(
            b'Available packages in context: simple',
            b'<p><a href="mypkg/">mypkg</a></p>\n',
            b'<p><a href="caf\xc3\xa9/">caf\xc3\xa9</a></p>\n')
        self.assertTrue(result)
        self.assertEqual(handler.wfile.getvalue(), expected)
        self.assertEqual(handler.header('Content-Length'), str(len(expected)))
        self.assertEqual(list(controller.image), ['mypkg', 'café'])
        self.assertEqual(urlopen.calls, [INDEX])
        self.assertEqual([], self.log.problems)

    def test_listPackages_anUnreachableIndexIsLoggedAndSkipped(self):
        self._urlopen({INDEX: urllib.error.URLError('no route to host')})
        context, controller = self._context()
        handler = support.FakeHandler()

        context.listPackages(handler)

        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.wfile.getvalue(), standard_page(
            b'Available packages in context: simple'))
        self.assertFalse(controller.services[INDEX][0])
        self.assertEqual(len(self.log.problems), 1)
        self.assertIn(INDEX, self.log.problems[0])

    def test_listPackages_rendersASnapshotOfTheImage(self):
        # Other request threads add packages to the image while a page is
        # being written; iterating the live keys() view raises RuntimeError.
        # Simulate that deterministically: a package appears mid-render.
        context, controller = self._context(indicies=None)
        controller.image['alpha'] = ({}, {})
        controller.image['beta'] = ({}, {})

        class MidRenderMutation(io.StringIO):
            mutated = False

            def write(self, text):
                if text.startswith('<p>') and not self.mutated:
                    self.mutated = True
                    controller.image['gamma'] = ({}, {})
                return io.StringIO.write(self, text)

        startPage = context._startStandardHTMLPage

        def mutatingStartPage(pagename):
            page = MidRenderMutation(startPage(pagename).getvalue())
            page.seek(0, 2)
            return page
        context._startStandardHTMLPage = mutatingStartPage
        handler = PypiProvider.PypiContext.NullHTTPHandler()

        context.listPackages(handler)

        self.assertIn('gamma', controller.image)
        self.assertEqual(handler.wfile.getvalue(), standard_page(
            b'Available packages in context: simple',
            b'<p><a href="alpha/">alpha</a></p>\n',
            b'<p><a href="beta/">beta</a></p>\n'))

    def test_listVersions_rendersTheFilesWithFragmentsAsExactBytes(self):
        urlopen = self._urlopen(self._indexRoutes())
        context, controller = self._context()
        handler = support.FakeHandler()

        result = context.listVersions('mypkg', handler)

        expected = standard_page(
            b'Files available for "mypkg" in context: simple',
            b'<p><a href="mypkg-1.0.tar.gz#md5=0123456789abcdef">'
            b'mypkg-1.0.tar.gz</a></p>\n',
            b'<p><a href="mypkg-2.0.tar.gz">mypkg-2.0.tar.gz</a></p>\n')
        self.assertTrue(result)
        self.assertEqual(handler.wfile.getvalue(), expected)
        self.assertEqual(handler.header('Content-Length'), str(len(expected)))
        files = controller.image['mypkg'][0]
        self.assertEqual(files['mypkg-1.0.tar.gz'][1], [FILE1])
        self.assertEqual(files['mypkg-2.0.tar.gz'][1], [FILE2])
        self.assertEqual(urlopen.calls, [PACKAGE_PAGE])
        self.assertEqual([], self.log.problems)

    def test_listVersions_constraintsLimitTheVersionsOffered(self):
        self._urlopen(self._indexRoutes())
        context, _ = self._context(constraints='mypkg<2')
        handler = support.FakeHandler()

        context.listVersions('mypkg', handler)

        self.assertEqual(handler.wfile.getvalue(), standard_page(
            b'Files available for "mypkg" in context: simple',
            b'<p><a href="mypkg-1.0.tar.gz#md5=0123456789abcdef">'
            b'mypkg-1.0.tar.gz</a></p>\n'))

    def test_listVersions_linksThatCannotBeVersionedAreSkipped(self):
        self._urlopen({PACKAGE_PAGE:
                       b'<a href="README.txt">README.txt</a>'
                       b'<a href="mypkg-1.0.tar.gz">mypkg-1.0.tar.gz</a>'})
        context, _ = self._context()
        handler = support.FakeHandler()

        context.listVersions('mypkg', handler)

        self.assertEqual(handler.wfile.getvalue(), standard_page(
            b'Files available for "mypkg" in context: simple',
            b'<p><a href="mypkg-1.0.tar.gz">mypkg-1.0.tar.gz</a></p>\n'))

    def test_listVersions_anUnknownPackageIsA404(self):
        self._urlopen({INDEX: INDEX_PAGE})
        context, _ = self._context()
        handler = support.FakeHandler()

        result = context.listVersions('nosuch', handler)

        self.assertFalse(result)
        self.assertEqual(handler.errors, [(404, 'nosuch: Not Found')])
        self.assertIsNone(handler.status)
        self.assertEqual([], self.log.problems)

    def test_listVersions_aServerErrorIsLoggedAndNoFilesAreOffered(self):
        # (the package is known from the index listing, so it is still a
        # page - just an empty one - rather than a 404)
        self._urlopen({PACKAGE_PAGE: urllib.error.HTTPError(
            PACKAGE_PAGE, 500, 'Server Error', None, None),
            INDEX: INDEX_PAGE})
        context, _ = self._context()
        handler = support.FakeHandler()

        result = context.listVersions('mypkg', handler)

        self.assertTrue(result)
        self.assertEqual(handler.wfile.getvalue(), standard_page(
            b'Files available for "mypkg" in context: simple'))
        self.assertEqual(len(self.log.problems), 1)
        self.assertIn('Pulling index', self.log.problems[0])

    # --- getPackage (cache read 'rb', cache write 'wb') -----------------

    def _cachedFile(self, content=PAYLOAD):
        path = os.path.join(self.tmp, 'mypkg-1.0.tar.gz')
        with open(path, 'wb') as f:
            f.write(content)
        return path

    def test_getPackage_servesACachedFileByteForByte(self):
        context, controller = self._context(indicies=None)
        cached = self._cachedFile()
        controller.image['mypkg'] = (
            {'mypkg-1.0.tar.gz': [cached, [], {}]}, {})
        handler = support.FakeHandler()

        result = context.getPackage('mypkg', 'mypkg-1.0.tar.gz', handler)

        self.assertTrue(result)
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.header('Content-type'),
                         'application/octet-stream')
        self.assertEqual(handler.header('Content-length'), str(len(PAYLOAD)))
        self.assertEqual(hashlib.sha256(handler.wfile.getvalue()).hexdigest(),
                         hashlib.sha256(PAYLOAD).hexdigest())
        self.assertEqual([], self.log.problems)

    def test_getPackage_streamsUpstreamToTheClientAndTheCache(self):
        urlopen = self._urlopen(self._indexRoutes())
        cache = os.path.join(self.tmp, 'cache')
        context, controller = self._context(cache=cache)
        handler = support.FakeHandler()

        result = context.getPackage('mypkg', 'mypkg-1.0.tar.gz', handler)

        cachefile = os.path.join(cache, 'mypkg', 'mypkg-1.0.tar.gz')
        self.assertEqual(result, cachefile)
        self.assertEqual(urlopen.calls, [PACKAGE_PAGE, FILE1])
        # headers come from the upstream response (an HTTPMessage)
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.header('Content-type'), 'application/x-gzip')
        self.assertEqual(handler.header('Content-length'), str(len(PAYLOAD)))
        wanted = hashlib.sha256(PAYLOAD).hexdigest()
        self.assertEqual(
            hashlib.sha256(handler.wfile.getvalue()).hexdigest(), wanted)
        with open(cachefile, 'rb') as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), wanted)
        self.assertEqual(
            controller.image['mypkg'][0]['mypkg-1.0.tar.gz'][0], cachefile)
        self.assertEqual([], self.log.problems)

    def test_getPackage_theFileJustCachedIsServedFromTheCacheNextTime(self):
        urlopen = self._urlopen(self._indexRoutes())
        context, _ = self._context(cache=os.path.join(self.tmp, 'cache'))
        context.getPackage('mypkg', 'mypkg-1.0.tar.gz', support.FakeHandler())
        handler = support.FakeHandler()

        context.getPackage('mypkg', 'mypkg-1.0.tar.gz', handler)

        self.assertEqual(handler.wfile.getvalue(), PAYLOAD)
        self.assertEqual(urlopen.calls.count(FILE1), 1)
        self.assertEqual([], self.log.problems)

    def test_getPackage_noUpstreamContentLengthMeansNoneIsSent(self):
        self._urlopen(self._indexRoutes(**{
            FILE1: (PAYLOAD, {'Content-Type': 'application/x-gzip'})}))
        context, _ = self._context(cache=os.path.join(self.tmp, 'cache'))
        handler = support.FakeHandler()

        context.getPackage('mypkg', 'mypkg-1.0.tar.gz', handler)

        self.assertIsNone(handler.header('Content-length'))
        self.assertEqual(handler.wfile.getvalue(), PAYLOAD)

    def test_getPackage_anUnreadableCacheEntryFallsBackToTheIndex(self):
        self._urlopen(self._indexRoutes())
        context, controller = self._context(
            cache=os.path.join(self.tmp, 'cache'))
        entry = ['/no/such/cached/mypkg-1.0.tar.gz', [FILE1], {}]
        controller.image['mypkg'] = ({'mypkg-1.0.tar.gz': entry}, {})
        handler = support.FakeHandler()

        context.getPackage('mypkg', 'mypkg-1.0.tar.gz', handler)

        self.assertEqual(handler.wfile.getvalue(), PAYLOAD)
        self.assertEqual(len(self.log.problems), 1)
        self.assertIn('Attempt to read cache failed', self.log.problems[0])

    def test_getPackage_triesTheNextMirrorWhenOneFails(self):
        mirrorA = 'http://a.example/mypkg-1.0.tar.gz'
        mirrorB = 'http://b.example/mypkg-1.0.tar.gz'
        urlopen = self._urlopen({
            mirrorA: urllib.error.URLError('connection refused'),
            mirrorB: (PAYLOAD, {'Content-Type': 'application/x-gzip'})})
        self._patch(PypiProvider.random, 'shuffle')  # keep the order
        cache = os.path.join(self.tmp, 'cache')
        context, controller = self._context(indicies=None, cache=cache)
        controller.image['mypkg'] = ({'mypkg-1.0.tar.gz': [
            False, [mirrorA, mirrorB], {}]}, {})
        handler = support.FakeHandler()

        result = context.getPackage('mypkg', 'mypkg-1.0.tar.gz', handler)

        self.assertEqual(urlopen.calls, [mirrorA, mirrorB])
        self.assertEqual(handler.wfile.getvalue(), PAYLOAD)
        with open(result, 'rb') as f:
            self.assertEqual(f.read(), PAYLOAD)
        self.assertEqual(len(self.log.problems), 1)
        self.assertIn(mirrorA, self.log.problems[0])

    def test_getPackage_noMirrorWorkingLeavesNoPartialCacheFile(self):
        mirrorA = 'http://a.example/mypkg-1.0.tar.gz'
        mirrorB = 'http://b.example/mypkg-1.0.tar.gz'
        self._urlopen({mirrorA: urllib.error.URLError('refused'),
                       mirrorB: urllib.error.URLError('refused')})
        self._patch(PypiProvider.random, 'shuffle')
        cache = os.path.join(self.tmp, 'cache')
        context, controller = self._context(indicies=None, cache=cache)
        controller.image['mypkg'] = ({'mypkg-1.0.tar.gz': [
            False, [mirrorA, mirrorB], {}]}, {})
        handler = support.FakeHandler()

        with self.assertRaisesRegex(ValueError, 'could produce'):
            context.getPackage('mypkg', 'mypkg-1.0.tar.gz', handler)

        self.assertEqual(os.listdir(os.path.join(cache, 'mypkg')), [])
        self.assertIsNone(handler.status)
        self.assertFalse(controller.image['mypkg'][0]['mypkg-1.0.tar.gz'][0])

    def test_getPackage_aClientThatHangsUpMidTransferLeavesNoCacheFile(self):
        class HungUpWfile(io.BytesIO):
            def write(self, data):
                raise BrokenPipeError(errno.EPIPE, 'Broken pipe')
        self._urlopen(self._indexRoutes())
        cache = os.path.join(self.tmp, 'cache')
        context, controller = self._context(cache=cache)
        handler = support.FakeHandler()
        handler.wfile = HungUpWfile()

        result = context.getPackage('mypkg', 'mypkg-1.0.tar.gz', handler)

        self.assertIsNone(result)
        self.assertEqual(os.listdir(os.path.join(cache, 'mypkg')), [])
        self.assertEqual(len(self.log.messages('warning')), 1)
        self.assertFalse(controller.image['mypkg'][0]['mypkg-1.0.tar.gz'][0])

    def test_getPackage_anUnknownPackageIsAnError(self):
        self._urlopen({INDEX: INDEX_PAGE})
        context, _ = self._context()

        with self.assertRaisesRegex(ValueError, 'nosuch is not available'):
            context.getPackage(
                'nosuch', 'nosuch-1.0.tar.gz', support.FakeHandler())

    def test_getPackage_anUnknownFilenameIsAnError(self):
        self._urlopen(self._indexRoutes())
        context, _ = self._context()

        with self.assertRaisesRegex(ValueError, 'mypkg-9.9.tar.gz is not'):
            context.getPackage(
                'mypkg', 'mypkg-9.9.tar.gz', support.FakeHandler())

    # --- _splitPypiName (the region whose tab/space indent was fixed) -----

    def _split(self, filename, packageName=None):
        context, _ = self._context(indicies=None)
        return context._splitPypiName(filename, {}, packageName)

    def test_splitPypiName_aDashedPackageNameGivenIsStrippedOff(self):
        result = self._split('my-pkg-1.2.3.tar.gz', 'my_pkg')

        self.assertEqual(result['package'], 'my-pkg')
        self.assertEqual(result['version'], version.Version('1.2.3'))
        self.assertEqual(result['ext'], '.tar.gz')
        self.assertFalse(result['isWheel'])

    def test_splitPypiName_wheelsYieldTheirCompatibilityTags(self):
        result = self._split('pip-6.1.1-py2.py3-none-any.whl')

        self.assertEqual(result['package'], 'pip')
        self.assertEqual(result['version'], version.Version('6.1.1'))
        self.assertTrue(result['isWheel'])
        self.assertEqual(
            (result['python'], result['abi'], result['platform']),
            ('py2.py3', 'none', 'any'))

    def test_splitPypiName_aHashFragmentIsSplitFromTheFilename(self):
        result = self._split('mypkg-1.0.tar.gz#md5=abc', 'mypkg')

        self.assertEqual(result['filename'], 'mypkg-1.0.tar.gz')
        self.assertEqual(result['fragment'], '#md5=abc')

    def test_splitPypiName_rejectsWhatIsNotAnArchiveWithAVersion(self):
        for filename in ('mypkg-1.0.exe', 'mypkg.tar.gz', 'README'):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    self._split(filename)

    def test_splitPypiName_aDifferentPackageNameIsRejected(self):
        with self.assertRaisesRegex(ValueError, 'did not match package'):
            self._split('other-pkg-1.0.tar.gz', 'mypkg')

    # --- PypiController (cache scan, constraining index) ------------------

    def _controller(self, **options):
        options.update(chroot=None, interfaces=['127.0.0.1'], port=None)
        configManager = types.SimpleNamespace(register=lambda *a, **k: None)
        return PypiProvider.PypiController(configManager, self.log, options)

    def _cacheEntry(self, package, filename):
        directory = os.path.join(self.tmp, 'cache', package)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, filename)
        with open(path, 'wb') as f:
            f.write(PAYLOAD)
        return path

    def test_controller_loadsFilesCachedByAnEarlierRun(self):
        cached = self._cacheEntry('mypkg', 'mypkg-1.0.tar.gz')

        controller = self._controller(cache=os.path.join(self.tmp, 'cache'))

        files, versions = controller.getPypiImage()[0]['mypkg']
        self.assertEqual(files['mypkg-1.0.tar.gz'][0], cached)
        self.assertEqual(list(versions), [version.Version('1.0')])

    def test_controller_unplaceableCacheFilesAreLoggedAndSkipped(self):
        self._cacheEntry('mypkg', 'mypkg-1.0.tar.gz')
        self._cacheEntry('mypkg', 'README')

        controller = self._controller(cache=os.path.join(self.tmp, 'cache'))

        files = controller.getPypiImage()[0]['mypkg'][0]
        self.assertEqual(list(files), ['mypkg-1.0.tar.gz'])
        self.assertEqual(len(self.log.problems), 1)
        self.assertIn('README', self.log.problems[0])

    def test_controller_createsAMissingCacheDirectory(self):
        cache = os.path.join(self.tmp, 'new', 'cache')

        controller = self._controller(cache=cache)

        self.assertTrue(os.path.isdir(cache))
        self.assertEqual(controller.getCachePath(), cache)

    def test_controller_aConstrainingIndexPinsTheContextToItsVersions(self):
        self._urlopen({INDEX: b'<a href="mypkg/">mypkg</a>',
                       PACKAGE_PAGE: PACKAGE_PAGE_BODY})

        controller = self._controller(**{'constraining-indicies': INDEX})

        self.assertEqual(controller.getInitialConstraints(),
                         ['mypkg==1.0|==2.0'])
        self.assertEqual([], self.log.problems)

    # --- the proxy thread's request dispatch ------------------------------

    def _proxy(self, path='/simple/'):
        proxy = object.__new__(PypiProvider.PypiProxyThread)
        proxy.service = types.SimpleNamespace(log=self.log)
        proxy.controller = unittest.mock.Mock()
        proxy.path = path
        proxy.send_error = unittest.mock.Mock()
        return proxy

    def test_proxyDoGet_handsTheRequestToTheController(self):
        proxy = self._proxy('/simple/mypkg/')

        proxy.do_GET()

        proxy.controller.doRequestedPath.assert_called_once_with(
            '/simple/mypkg/', proxy)
        proxy.send_error.assert_not_called()

    def test_proxyDoGet_anUnknownPackageIsA404(self):
        proxy = self._proxy()
        proxy.controller.doRequestedPath.side_effect = ValueError('nope')

        proxy.do_GET()

        proxy.send_error.assert_called_once_with(404, 'File not found')

    def test_proxyDoGet_anyOtherFailureIsA500WithTheReason(self):
        proxy = self._proxy()
        proxy.controller.doRequestedPath.side_effect = RuntimeError('boom')

        proxy.do_GET()

        proxy.send_error.assert_called_once_with(
            500, 'Internal Server Error on Pypi Proxy Facade: boom')
        self.assertEqual(len(self.log.problems), 1)

    def test_proxyDoGet_theShutdownProbeIsAnswered503(self):
        proxy = self._proxy('/xyzzy/xzyyzl33t/...shuttingdownthefacade...')

        proxy.do_GET()

        proxy.send_error.assert_called_once_with(503, 'Service shutting down')
        proxy.controller.doRequestedPath.assert_not_called()

    def test_proxy_writeMethodsAreRefusedWith405(self):
        for method in ('do_POST', 'do_PUT', 'do_DELETE'):
            with self.subTest(method=method):
                proxy = self._proxy()

                getattr(proxy, method)()

                self.assertEqual(proxy.send_error.call_args[0][0], 405)

    # --- the TLS facade: openssl ciphers, shutdown wake-up -----------------

    def _openssl(self, outcome):
        fake = support.FakeCheckOutput({('openssl', 'ciphers'): outcome})
        self._patch(PypiProvider.subprocess, 'check_output', fake)
        return fake

    def _construct(self, build):
        self._patch(PypiProvider.CsmakeServiceDaemon, '__init__',
                    lambda *args, **kwargs: None)
        self._patch(PypiProvider.CsmakeServiceProvider, '__init__',
                    lambda *args, **kwargs: None)
        return build()

    def test_opensslCiphers_areTextWhereSslWantsText(self):
        # ssl.wrap_socket(ciphers=...) takes str; check_output gives bytes.
        fake = self._openssl(b'ECDHE-RSA-AES256-GCM-SHA384:AES128-SHA\n')

        provider = self._construct(
            lambda: PypiProvider.PypiProvider(object(), 'tag'))
        service = self._construct(lambda: PypiProvider.PypiService(
            object(),
            types.SimpleNamespace(getCertificateManager=lambda: None),
            {'interfaces': ['localhost']}))

        for ciphers in (provider.ciphers, service.ciphers):
            self.assertEqual(ciphers, 'ECDHE-RSA-AES256-GCM-SHA384:AES128-SHA')
            self.assertIsInstance(ciphers, str)
        self.assertEqual(fake.calls, [(['openssl', 'ciphers'], {})] * 2)

    def test_opensslCiphers_aFailingOpensslStopsTheProvider(self):
        self._openssl(support.called_process_error(['openssl', 'ciphers']))

        with self.assertRaises(PypiProvider.subprocess.CalledProcessError):
            self._construct(lambda: PypiProvider.PypiProvider(object(), 'tag'))

    @unittest.skipIf(not hasattr(ssl, 'wrap_socket'),
                     "pre-existing: ssl.wrap_socket was removed in Python "
                     "3.12 so PypiProvider._customizeSocket cannot work "
                     "there until it is ported to ssl.SSLContext")
    def test_customizeSocket_wrapsWithTheTextCipherList(self):
        provider = object.__new__(PypiProvider.PypiProvider)
        provider.ciphers = 'AES128-SHA'
        provider.certificateManager = types.SimpleNamespace(
            getCertPath=lambda: '/c.crt', getCertKeyPath=lambda: '/c.key')
        wrap = self._patch(ssl, 'wrap_socket', return_value='wrapped')

        result = provider._customizeSocket('sock')

        self.assertEqual(result, 'wrapped')
        self.assertEqual(wrap.call_args[1]['ciphers'], 'AES128-SHA')
        self.assertEqual(wrap.call_args[1]['certfile'], '/c.crt')

    def _service(self, accepting):
        service = object.__new__(PypiProvider.PypiService)
        service.controller = unittest.mock.Mock()
        service.port = types.SimpleNamespace(
            address=lambda: ('127.0.0.1', 8443))
        service.accepting = accepting
        self._patch(PypiProvider.CsmakeServiceDaemon, 'stop')
        return service

    def test_serviceStop_wakesABlockedAcceptWithAHttpsRequest(self):
        urlopen = self._patch(
            PypiProvider.urllib.request, 'urlopen',
            side_effect=urllib.error.URLError('closing'))
        service = self._service(accepting=True)

        service.stop()

        service.controller.shutdown.assert_called_once_with()
        urlopen.assert_called_once_with(
            'https://127.0.0.1:8443/xyzzy/xzyyzl33t/...shuttingdownthefacade...',
            timeout=1)

    def test_serviceStop_doesNotProbeAServiceThatIsNotAccepting(self):
        urlopen = self._patch(PypiProvider.urllib.request, 'urlopen')
        service = self._service(accepting=False)

        service.stop()

        urlopen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
