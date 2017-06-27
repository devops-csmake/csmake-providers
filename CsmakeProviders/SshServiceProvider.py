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

class SshConfigurationHelper:
    @staticmethod
    def sshDebugLevel(settings):
        loglevel = 'ERROR'
        if settings['quiet']:
            loglevel = 'QUIET'
        else:
            if settings['verbose']:
                loglevel = 'VERBOSE'
            if settings['debug']:
                loglevel = 'DEBUG'
            if settings['dev-output']:
                loglevel = 'DEBUG3'
        return loglevel

class SshClientConfig(CsmakeServiceConfig):
    HOMES_TO_GROCK = ['/root', '/home/*']

    def ensure(self):
        #Get the owner and group id of the current directory
        self.port = self.manager.options['port']
        pathstat = os.stat(self.path)
        pathowner = pathstat.st_uid
        pathgroup = pathstat.st_gid

        self._backupAndSetup(
            os.path.join(
                self.fullpath,
                ".ssh/config"),
            owner=str(pathowner),
            group=str(pathgroup),
            permissions="600",
            dirpermissions="750",
            in_chroot=False)

        CsmakeServiceConfig.ensure(self)

    def writefile(self, fobj):
        loglevel = SshConfigurationHelper.sshDebugLevel(self.module.settings)
        clientList = []
        #TODO: Perhaps should have a list of ports?
        #Old code: for interface in self.manager.options['interfaces']:
        address = self.port.address()
        clientList.append(
            """Host %s
                  HostName %s
                  Port %s
                  LogLevel %s""" % (
            address[0],
            address[0],
            address[1],
            loglevel))
        fobj.write('\n'.join(clientList))

class SshDaemonConfig(CsmakeServiceConfig):
    CONFIG_FILE_NAME = "sshd_config"

    def ensure(self):
        self.port = self.manager.options['port']
        pathToConfig = os.path.join(
            self.path,
            self.CONFIG_FILE_NAME )
        self.log.debug("Writing config to: %s", pathToConfig)
        self._backupAndSetup(pathToConfig)

        #Ensure the directory /var/run/sshd falls under the control
        # of the daemon config manager object.
        #sshd requires this for "Privilege separation"
        fullprivpath = "/run/sshd/touch"
        self._backupAndSetup(
            fullprivpath,
            setup=False,
            writefile=self.thunkwritefile,
            owner=0,
            group=0,
            dirpermissions="755" )

        CsmakeServiceConfig.ensure(self)
        self.manager.shellout(
            subprocess.call,
            ['rm', '-f', '"/run/sshd/touch"'] )

    def thunkwritefile(self, fobj):
        pass

    def writefile(self, fobj):
        loglevel = SshConfigurationHelper.sshDebugLevel(self.module.settings)
        daemonList = ["LogLevel %s" % loglevel]
        #TODO: Perhaps have a list of ports
        #Old code: for interface in self.manager.options['interfaces']:
        address = self.port.address()
        daemonList.append(
            "ListenAddress %s:%s" % address )
        fobj.write('\n'.join(daemonList))

class SshServiceConfigManager(CsmakeServiceConfigManager):

    def __init__(self, module, daemon, cwd=None, options={}):
        CsmakeServiceConfigManager.__init__(self, module, daemon, cwd, options)
        mybaseroot = '/'
        if self.chroot is not None:
            mybaseroot = self.chroot
        self.daemonConfigPath = "/etc/csmake_ssh_%s" % daemon.provider.tag
        self.fullDaemonConfigPath = os.path.join(
            mybaseroot,
            self.daemonConfigPath[1:])

    def getDaemonConfigPaths(self):
        return [self.daemonConfigPath]

    def getDaemonConfigFile(self):
        return os.path.join(
            self.daemonConfigPath,
            SshDaemonConfig.CONFIG_FILE_NAME )

    def ensure(self):
        try:
            try:
                self.shellout(
                    subprocess.check_output,
                    ['stat', '-c', '', self.fullDaemonConfigPath],
                    in_chroot=False,
                    quiet_check=True )
                result=0
            except:
                result=1
            if result == 0:
                self.log.devdebug("The sshd config directory already exists")
            else:
                self.log.devdebug("The sshd config directory does not exist, creating")
                self.shellout(
                    subprocess.check_call,
                    ['mkdir', '-p', self.fullDaemonConfigPath],
                    in_chroot=False)
        except:
            self.log.exception("Attempt to create sshd config directory '%s' failed", self.fullDaemonConfigPath )
            self.log.warning("The sshd will not have the appropriate configuration")

        CsmakeServiceConfigManager.ensure(self)

    def clean(self):
        CsmakeServiceConfigManager.clean(self)
        if os.path.exists(self.fullDaemonConfigPath):
            try:
                self.shellout(
                    subprocess.check_output,
                    ['rmdir', '-p', self.fullDaemonConfigPath],
                    in_chroot = False,
                    quiet_check=True )
            except Exception as e:
                self.log.devdebug(
                    "The sshd config could not be deleted '%s': %s: %s",
                    self.fullDaemonConfigPath,
                    e.__class__.__name__,
                    str(e) )

class SshServiceDaemon(CsmakeServiceDaemon):
    def __init__(self, module, provider, options):
        CsmakeServiceDaemon.__init__(self, module, provider, options)
        self.configManagerClass = SshServiceConfigManager
        self.process = None

    def _setupConfigs(self):
        #Handle the client side configuration
        prefix = ''
        if self.options['client-chroot'] is not None:
            prefix = self.options['client-chroot']
        self.configManager.register(
            SshClientConfig,
            SshClientConfig.HOMES_TO_GROCK,
            ensure=False,
            in_chroot=False,
            path_prefix = prefix )

        #Handle the server side configuration
        self.configManager.register(
            SshDaemonConfig,
            self.configManager.getDaemonConfigPaths(),
            ensure=False )

        CsmakeServiceDaemon._setupConfigs(self)

    def _startListening(self):
        fullsshd = self.configManager.shellout(
            subprocess.check_output,
            ['which', 'sshd'] )
        command = [
          fullsshd.strip(), '-e', '-D',
          '-f', self.configManager.getDaemonConfigFile()
        ]
        self.log.debug("Calling Popen with: %s", ' '.join(command))
        port = self.options['port']
        port.lock()
        port.unbind()
        try:
            self.process = self.configManager.shellout(
                subprocess.Popen,
                command )
            if self.process.poll() is not None:
                raise Exception("Process is not running")
            address = port.address()
            #Wait for 5 seconds to see the process come about
            for x in range(0,50):
                try:
                    subprocess.check_call(
                        ['nc', '-z', address[0], str(address[1])] )
                    #Process is listening - probably
                    if self.process.poll() is not None:
                        raise Exception("Process is not running")
                    break
                except:
                    #Process is not listening yet wait .1 sec and try again
                    time.sleep(.1)
                    if self.process.poll() is not None:
                        raise Exception("Process is not running")
            else:
                if self.process.poll() is not None:
                    raise Exception("Process never started")
                else:
                    raise Exception("Process didn't listen after 5 seconds")
        finally:
            port.unlock()

    def _cleanup(self):
        try:
            try:
                processes = self.configManager.shellout(
                    subprocess.check_output,
                    [ 'ps', '-o', 'pid', '--ppid', str(self.process.pid), '--noheaders' ] )
                processes = processes.split()
                for process in processes:
                    self.configManager.shellout(
                        subprocess.call,
                        [ 'kill', '-9', process ] )
            except:
                self.log.exception("Could not stop sshd using standard procedure, attempting to use sudo calls exclusively")
                subprocess.call("""set -eux
                    for x in `sudo ps -o pid --ppid %d --noheaders`
                    do
                        sudo kill -9 $x
                    done
                    """ % self.process.pid,
                    shell=True,
                    stdout=self.log.out(),
                    stderr=self.log.err() )
                subprocess.call(
                    ['sudo', 'kill', str(self.process.pid)],
                    stdout=self.log.out(),
                    stderr=self.log.err())
        except:
            self.log.exception("Couldn't terminate process cleanly")

class SshServiceProvider(CsmakeServiceProvider):

    serviceProviders = {}

    def __init__(self, module, tag, **options):
        CsmakeServiceProvider.__init__(self, module, tag, **options)
        self.serviceClass = SshServiceDaemon

    def _processOptions(self):
        CsmakeServiceProvider._processOptions(self)
        if 'client-chroot' not in self.options:
            self.options['client-chroot'] = self.options['chroot']
