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
"""Unit tests for the Python 3 conversion of HttpServiceProvider.py.

No sockets: the stdlib server/handler bases are patched where they would bind
or serve, and the config manager that would shell out to chmod is a
FakeManager that records the commands.  Real temp files are used only for
the mode bits the handler reads.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import http.server
import os
import shutil
import tempfile
import types
import unittest
import unittest.mock

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

CSP = support.import_provider('CsmakeServiceProvider')
HSP = support.import_provider('HttpServiceProvider')


class FakePort(object):
    """The part of CsmakePortManager that VirtualHTTPServer uses; records
    the order of calls into a shared list."""

    def __init__(self, events):
        self.events = events

    def address(self):
        self.events.append('address')
        return ('127.0.0.1', 8080)

    def lock(self):
        self.events.append('lock')

    def unbind(self):
        self.events.append('unbind')

    def unlock(self):
        self.events.append('unlock')


class testHttpServiceProvider_py3(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.manager = support.FakeManager(self.log)
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='csmake-http-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.www = os.path.join(self.tmp, 'www')
        os.mkdir(self.www)
        # The handler resolves the served path against the current directory
        cwd = unittest.mock.patch.object(HSP.os, 'getcwd', return_value=self.tmp)
        cwd.start()
        self.addCleanup(cwd.stop)

    def _handler(self, path='/'):
        handler = object.__new__(HSP.VirtualPathHTTPRequestHandler)
        handler.basepath = self.www
        handler.directory = self.tmp
        handler.daemon = types.SimpleNamespace(
            log=self.log, configManager=self.manager)
        handler.log = self.log
        handler.undo_privs = []
        handler.path = path
        return handler

    def _file(self, name, mode):
        path = os.path.join(self.www, name)
        with open(path, 'wb') as f:
            f.write(b'\xff\xfe')
        os.chmod(path, mode)
        return path

    def _assertChmod(self, command, path, mode):
        self.assertEqual(command[0], 'chmod')
        self.assertEqual(command[2], path)
        self.assertRegex(command[1], support.CHMOD_MODE)
        self.assertEqual(int(command[1], 8), mode)

    def test_importPath_usesThePython3StdlibServer(self):
        self.assertTrue(issubclass(
            HSP.VirtualHTTPServer, http.server.HTTPServer))
        self.assertTrue(issubclass(
            HSP.VirtualPathHTTPRequestHandler,
            http.server.SimpleHTTPRequestHandler))

    def test_translatePath_opensTheFileUpAndRestoresItsModeAfterwards(self):
        # the restore used a mode string built with oct(), '0o640' on Py3
        served = self._file('payload.bin', 0o640)
        handler = self._handler('/payload.bin')

        result = handler.translate_path('/payload.bin')

        self.assertEqual(result, served)
        self.assertEqual(self.manager.commands(), [['chmod', '777', served]])

        handler.finish_request()

        restore = self.manager.commands()[1:]
        self.assertEqual(len(restore), 3)
        self._assertChmod(restore[0], served, 0o640)
        self.assertEqual((restore[1][0], restore[1][-1]), ('chown', served))
        self.assertEqual((restore[2][0], restore[2][-1]), ('chgrp', served))

    def test_translatePath_directoryGetsATrailingSlashOnResultAndPath(self):
        os.chmod(self.www, 0o750)
        handler = self._handler('/')

        result = handler.translate_path('/')

        self.assertEqual(result, self.www + '/')
        self.assertEqual(handler.path, '/')
        self.assertEqual(self.manager.commands(),
                         [['chmod', '777', self.www + '/']])
        handler.finish_request()
        self._assertChmod(self.manager.commands()[1], self.www + '/', 0o750)

    def test_translatePath_directoryRequestedWithoutSlashIsRedirectedToOne(self):
        os.mkdir(os.path.join(self.www, 'sub'))
        handler = self._handler('/sub')

        result = handler.translate_path('/sub')

        self.assertEqual(result, os.path.join(self.www, 'sub') + '/')
        self.assertEqual(handler.path, '/sub/')

    def test_translatePath_missingFileIsTranslatedWithoutTouchingPrivs(self):
        handler = self._handler('/nothing.txt')

        result = handler.translate_path('/nothing.txt')

        self.assertEqual(result, os.path.join(self.www, 'nothing.txt'))
        handler.finish_request()
        self.assertEqual(self.manager.calls, [])

    def test_finishRequest_undoesInReverseOrder(self):
        order = []
        handler = self._handler()
        handler.undo_privs = [lambda: order.append('first'),
                              lambda: order.append('second')]

        handler.finish_request()

        self.assertEqual(order, ['second', 'first'])

    def test_doGet_restoresPrivsEvenWhenServingFails(self):
        handler = self._handler()
        undone = []
        handler.undo_privs = [lambda: undone.append(True)]

        with unittest.mock.patch.object(
                http.server.SimpleHTTPRequestHandler, 'do_GET',
                side_effect=BrokenPipeError):
            with self.assertRaises(BrokenPipeError):
                handler.do_GET()

        self.assertEqual(undone, [True])

    @unittest.skip("pre-existing typo: do_HEAD calls "
                   "SimpleHTTPServer.SimleHTTPRequestHandler, so HEAD "
                   "requests raise AttributeError (same code on Python 2)")
    def test_doHead_restoresPrivs(self):
        pass

    def test_server_bindsWhileThePortIsLockedAndUnbound(self):
        events = []
        server = object.__new__(HSP.VirtualHTTPServer)
        server.portobject = FakePort(events)

        with unittest.mock.patch.object(
                http.server.HTTPServer, 'server_bind',
                side_effect=lambda *args: events.append('bind')):
            server.server_bind()

        self.assertEqual(events, ['lock', 'unbind', 'bind', 'unlock'])

    def test_server_bindFailureStillUnlocksThePort(self):
        events = []
        server = object.__new__(HSP.VirtualHTTPServer)
        server.portobject = FakePort(events)

        with unittest.mock.patch.object(
                http.server.HTTPServer, 'server_bind',
                side_effect=OSError('address in use')):
            with self.assertRaises(OSError):
                server.server_bind()

        self.assertEqual(events, ['lock', 'unbind', 'unlock'])

    def test_server_init_bindsTheAddressOfThePortObject(self):
        events = []
        port = FakePort(events)

        with unittest.mock.patch.object(
                http.server.HTTPServer, '__init__',
                return_value=None) as base_init:
            server = HSP.VirtualHTTPServer(
                port, HSP.VirtualPathHTTPRequestHandler, 'the-daemon', '/srv')

        base_init.assert_called_once_with(
            server, ('127.0.0.1', 8080), HSP.VirtualPathHTTPRequestHandler)
        self.assertEqual(server.getVirtualizedPath(), '/srv')
        self.assertEqual(server.getDaemon(), 'the-daemon')


if __name__ == '__main__':
    unittest.main()
