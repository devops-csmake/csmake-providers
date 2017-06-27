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
from Csmake.CsmakeAspect import CsmakeAspect
from CsmakeProviders.SshServiceProvider import SshServiceProvider

class SshService(CsmakeAspect):
    """Purpose: Provide a local sshd/ssh configuration that simulates
              a network interaction across ssh.
              Useful for running an ansible configuration for example.
     Options:
         user - Specifies the user that will use ssh to connect to
                the sshd service.
                NOTE: This user's .ssh/config file will be temporarily
                      modified to support use of the port the sshd
                      is listening on for this service.
         interfaces - (OPTIONAL) List of interfaces to listen on,
                        delimited with commas or newlines.
                      Default: localhost
         tag - (OPTIONAL) allows for several sshd services to be
                          operational at the same time in the same build
                          given unique values for 'tag'
                      Default: <nothing>
         chroot - (OPTIONAL) Will operate the sshd in a chrooted environment
                          determined by the path provided
                    Default: /
                  Note: This will temporarily change the specified
                      user's .ssh/config file in the specified environment
                      (unless client-chroot is specified)
         client-chroot - (OPTIONAL) Will configure the user's .ssh/config
                      in the given chrooted environment to access the
                      service on the given port
                    Default: The value of chroot
         port - (OPTIONAL) Will stand up the sshd on the given port
                 Default: a currently open port in 'port-range'
         port-range - (OPTIONAL) Will stand up the sshd in a given range
                   Ignored if a specific port is called out by 'port'
                   Format:  <lower> - <upper> (Inclusive)
                   Default: 2222-3333
     Phases/JoinPoints:  
         build - will stand the service up in the build phase
                 When used as a regular section, StopSshService must be used
         start__build - will stand up the service at the start of the
                        decorated regular section
         end__build - will tear down the service at the end of the section
    """

    def _startService(self, options):
        if SshServiceProvider.hasServiceProvider(self.tag):
            self.log.error("sshd with service tag '%s' already executing", self.tag)
            self.log.failed()
            self._unregisterOnExitCallback("_stopService")
            return None

        self.provider = SshServiceProvider.createServiceProvider(
            self.tag,
            self,
            **options)
        self.provider.startService()
        if self.provider is not None and self.provider.isServiceExecuting():
            self.log.passed()
        else:
            self.log.error("The sshd service could not be started")
            self.log.failed()
            self._unregisterOnExitCallback("_stopService")
        return None

    def _stopService(self):
        SshServiceProvider.disposeServiceProvider(self.tag)
        self._unregisterOnExitCallback("_stopService")
        self.log.passed()

    def build(self, options):
        self.tag = '_'
        if 'tag' in options:
            self.tag = options['tag']
            del options['tag']
        self._dontValidateFiles()
        self._registerOnExitCallback("_stopService")
        self.log.passed()
        return self._startService(options)

    def start__build(self, phase, options, step, stepoptions):
        return self.build(options)

    def end__build(self, phase, options, step, stepoptions):
        self._stopService()
