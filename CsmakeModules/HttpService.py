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
from CsmakeProviders.HttpServiceProvider import HttpServiceProvider
from Csmake.CsmakeAspect import CsmakeAspect

class HttpService(CsmakeAspect):
    """Purpose: An module (or aspect) to serve build/built files via
                an http protocol
       Notes: * When used as a module - use HttpStopFacade to end the facade.
              To use as an aspect, begin the section declaration with the
              aspect moniker (&).
     Options: root-path - Path to the virtual root for the http service
              tag - (OPTIONAL) allows for multiple facades to be executing
                          at the same time.
                    If a tag is used and PypiStopFacade is also used,
                    the tag must be used with the PypiStopFacade section
                    as well.

              ::Network Controls::
              interfaces - (OPTIONAL) list of interfaces to listen on,
                           delimited by commas.  Currently only one
                           interface is supported in both the server and
                           the configuration of pip and easy_install in the
                           build.
                           Default is 'localhost'
              port - (OPTIONAL) The port for the Pypi proxy facade
                        to listen on pip requires ssl - although it trusts
                        localhost without this, you may choose a different
                        interface.  Implementation of SSL ensures that PyPI
                        access in a build will always be trusted.
                        Default is a free port in the range of
                        20000 - 24000 (see port-range)
              port-range - (OPTIONAL) A range for the ports for the
                        facade to listen on - a free port in the range
                        will be picked (NOTE: Does not attempt to avoid ports
                        occupied on CLOSE_WAIT and similar states).
        Phase: build - will start the proxy - if the proxy is
                       already started - the request will be ignored.
        JoinPoints: start__build - will launch the proxy
                    end__build - will stop and clean up the proxy"""

    REQUIRED_OPTIONS = ['root-path']

    def build(self, options):
        self.tag = '_'
        if 'tag' in options:
            self.tag = options['tag']
            del options['tag']
        self._dontValidateFiles()
        self._registerOnExitCallback("_stopService")
        self.service = HttpServiceProvider.createServiceProvider(
            self.tag,
            self,
            **options)
        self.service.startService()
        if self.service.isServiceExecuting():
            self.log.passed()
        else:
            self.log.failed()
        return self.service

    def _stopService(self):
        HttpServiceProvider.disposeServiceProvider(self.tag)
        self.log.passed()
        try:
            self._unregisterOnExitCallback("_stopService")
        except:
            pass

    def start__build(self, phase, options, step, stepoptions):
        return self.build(options)

    def end__build(self, phase, options, step, stepoptions):
        self._stopService()
        return True

