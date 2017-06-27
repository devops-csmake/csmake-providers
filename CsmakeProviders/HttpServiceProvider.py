# <copyright>
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
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
# <copyright>
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
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
import threading
import subprocess
import os.path
import time
from CsmakeServiceProvider import CsmakeServiceProvider, CsmakeServiceConfig
from CsmakeServiceProvider import CsmakeServiceDaemon
from CsmakeServiceProvider import CsmakeServiceConfigManager
from CsmakeServiceProvider import CsmakeServiceChangeFilePrivs
import BaseHTTPServer
import SimpleHTTPServer


class VirtualPathHTTPRequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        self.basepath = server.getVirtualizedPath()
        self.daemon = server.getDaemon()
        self.log = self.daemon.log
        self.undo_privs = []

        self.log.devdebug("Created vpath http request")
        SimpleHTTPServer.SimpleHTTPRequestHandler.__init__(
            self,
            request,
            client_address,
            server )

    def do_GET(self):
        try:
            SimpleHTTPServer.SimpleHTTPRequestHandler.do_GET(self)
        finally:
            self.finish_request()

    def do_HEAD(self):
        try:
            SimpleHTTPServer.SimleHTTPRequestHandler.do_HEAD(self)
        finally:
            self.finish_request()

    def finish_request(self):
        undoers = list(self.undo_privs)
        undoers.reverse()
        for undoer in undoers:
            undoer()

    def translate_path(self, virtpath):
        #translate_path by default will tack on cwd
        self.log.devdebug("Path requested: %s", virtpath)
        if virtpath.startswith('/'):
            virtpath = virtpath[1:]
        fullpath = os.path.join(self.basepath, virtpath)
        fullpath = os.path.relpath(fullpath, os.getcwd())
        self.log.devdebug("Path translated: %s", fullpath)
        result = SimpleHTTPServer.SimpleHTTPRequestHandler.translate_path(
            self,
            fullpath )
        if os.path.isdir(result):
            if result[-1] != '/':
                result += '/'
            if self.path[-1] != '/':
                self.path += '/'
        self.undo_privs.append(
            CsmakeServiceChangeFilePrivs(
                result,
                self.daemon.configManager,
                filemod='777' ) )
        self.log.devdebug("Path massaged: %s", result)
        self.log.devdebug("self path: %s", self.path)
        #TODO: Open privs on the path requested to 777
        return result

class VirtualHTTPServer(BaseHTTPServer.HTTPServer):
    def __init__(self, portobject, handler, daemon, virtualizedPath):
        self.portobject = portobject
        BaseHTTPServer.HTTPServer.__init__(self, portobject.address(), handler)
        self.basepath = virtualizedPath
        self.daemon = daemon

    def getVirtualizedPath(self):
        return self.basepath

    def getDaemon(self):
        return self.daemon

    def server_bind(self):
        self.portobject.lock()
        self.portobject.unbind()
        try:
            BaseHTTPServer.HTTPServer.server_bind(self)
        finally:
            self.portobject.unlock()

class HttpServiceDaemon(CsmakeServiceDaemon):
    def __init__(self, module, provider, options):
        CsmakeServiceDaemon.__init__(self, module, provider, options)
        self.server = VirtualHTTPServer(
            options['port'],
            VirtualPathHTTPRequestHandler,
            self,
            options['root-path'] )

    def _listeningLoop(self):
        self.server.serve_forever()

    def stop(self):
        CsmakeServiceDaemon.stop(self)
        self.server.shutdown()

class HttpServiceProvider(CsmakeServiceProvider):

    serviceProviders = {}

    def __init__(self, module, tag, **options):
        CsmakeServiceProvider.__init__(self, module, tag, **options)
        self.serviceClass = HttpServiceDaemon
