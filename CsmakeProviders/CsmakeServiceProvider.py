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
import os
import stat
import glob
import fnmatch
import time
import fcntl
import socket
import random
import logging
import pyinotify

#Shut up pyinotify...
try:
    logger = logging.getLogger('pyinotify')
    logger.setLevel(1000)
except:
    pass

###############################################################
# General stuff to consider for standing up services in a build
#
#TODO: Add management of the /etc/hosts file in the client chroot
#TODO: Add ability to specify interfaces as hosts and assign
#      loopback addresses.
#TODO: Add a way to bring up/down a lo:x interface
#         ifconfig lo:## 127.0.0.10 255.255.255.0 up

class CsmakeServiceChangeFilePrivs:
    def __init__(self, path, manager,
                 filemod=None, fileuser=None, filegroup=None,
                 in_chroot=False):
        self.changed = False
        self.oldowner = None
        self.oldgroup = None
        self.oldpermissions = None
        self.manager = manager
        self.path = path
        self.in_chroot = in_chroot

        if not os.path.exists(self.path):
            return
        try:
            oldstat = os.stat(self.path)
            self.oldowner = str(oldstat.st_uid)
            self.oldgroup = str(oldstat.st_gid)
            self.oldpermissions = oct(stat.S_IMODE(oldstat.st_mode))
        except Exception as e:
            statout = self.manager.shellout(
                subprocess.check_output,
                ['stat', '--printf', '%a %u %g', self.path] )
            statparts = statout.split()
            self.oldpermissions=statparts[0]
            self.oldowner=statparts[1]
            self.oldgroup=statparts[2]
        if filemod is not None:
            self.manager.shellout(
                subprocess.check_call,
                ['chmod', filemod, self.path],
                in_chroot=in_chroot )
            self.changed = True
        if fileuser is not None:
            self.manager.shellout(
                subprocess.check_call,
                ['chown', fileuser, self.path],
                in_chroot=in_chroot )
            self.changed = True
        if filegroup is not None:
            self.manager.shellout(
                subprocess.check_call,
                ['chgrp', filegroup, self.path],
                in_chroot=in_chroot )
            self.changed = True

    def __call__(self):
        """Calling the change instance will restore the old settings"""
        if self.changed:
            self.manager.shellout(
                subprocess.check_call,
                ['chmod', self.oldpermissions, self.path],
                in_chroot=self.in_chroot )
            self.manager.shellout(
                subprocess.check_call,
                ['chown', self.oldowner, self.path],
                in_chroot=self.in_chroot )
            self.manager.shellout(
                subprocess.check_call,
                ['chgrp', self.oldgroup, self.path],
                in_chroot=self.in_chroot )
            self.changed = False

    def __del__(self):
        if self.changed:
            try:
                self()
            except:
                self.manager.log.exception("Restoration failed for: %s", self.path)

class CsmakeServiceConfig:
    def __init__(self, module, manager, path, fullpath, in_chroot, chroot):
        self.in_chroot = in_chroot
        self.chroot = chroot
        self.module = module
        self.manager = manager
        self.fullpath = fullpath
        self.log = module.log
        self.path = path
        self.backupsuffix = ".csmake.bkup"
        self.executing = True
        self.files = []
        self.cleaningUp = False
        self.backupLock = threading.Lock()
        self.uid = os.geteuid()
        self.gid = os.getegid()

    def ensure(self):
        self.update()
        pass

    def restore(self, filename, in_chroot):
        return False

    def writefile(self, fobj):
        pass

    def update(self):
        for filename, _, _, _, _, _, _, _, _, _, in_chroot, writefile in self.files:
            writeCall = writefile
            if writeCall is None:
                writeCall = self.writefile
            filepath = filename
            if in_chroot and self.chroot is not None:
                filepath = self.chroot + filename

            try:
                with open(filepath, 'w') as fobj:
                    writeCall(fobj)
            except Exception as e:
                self.log.debug("Couldn't write '%s' directly.  Using indirect method: %s: %s", filepath, e.__class__.__name__, str(e))
                _, filename = os.path.split(filepath)
                temppath = os.path.join(
                    self.module.env.env['RESULTS'],
                    ".daemoncfgs",
                    filename )
                self.module._ensureDirectoryExists(temppath)
                with open(temppath, 'w') as fobj:
                    writeCall(fobj)
                #cp will preserve the target's attributes
                self.manager.shellout(
                    subprocess.check_call,
                    ['cp', temppath, filepath],
                    in_chroot=False)
                os.remove(temppath)
                self.module._cleanEnsuredDirectory(temppath)

    def clean(self):
        self.backupLock.acquire()
        self.cleaningUp = True
        self.backupLock.release()
        self._restoreMovedFiles()

    def filepath(self):
        return self.path

    #TODO: Consider creating a way to track any changes that happen to the
    #      configuration.  In the cases where the file is copied instead
    #      of moved, ensure that the file can be restored in place, instead
    #      of moving the backup back in.
    #TODO: Move the backup and restore logic to use a ChangeFilePriv
    #      object - or better a subclass that also tracks the original
    #      content.
    def _backupAndSetup(
        self,
        path,
        owner=None,
        group=None,
        permissions="777",
        dirpermissions="777",
        setup=True,
        moveOriginal=True,
        restoreInPlace=False,
        in_chroot=True,
        writefile=None):
        """Maintains a backup of the original if one exists and sets up
           and empty file with the desired permissions.  This will
           also create and maintain any directories (with given permissions)
           if the path to the file does not exist.
           During cleanup all files backed up with this method will be
           restored to their original state.
           path - path to the file to backup and setup
           owner - the owner to set any paths created and the file specified
           group - the group to set any paths created and the file specified
           permissions - a string of the chmod octal for the file specified
           dirpermissions - a string of the chmod octal for the path to the file
           setup - When False, this will skip any setup for the new file
           moveOriginal - When False, the original file will not be moved
           restoreInPlace - Allows the "restore" method to be called
                            to handle the restoration of the original file
                            and will only reset the permissions if the
                            restore method returns true during cleanup
           in_chroot - When True, the path is assumed to be inside the chroot
                       (if one is provided - otherwise this does nothing)
                       When False, the path is assumed to be rooted in
                       the filesystem of the build system.
                       You should only specify False when you need to specify
                       non-chroot paths in a chrooted environment - this should
                       be rare.
           writefile - The writefile method to use for the given backup
                       if nothing is specified, self.writefile will be used.
                       The method must take a file object.
        """

        #Refuse to touch anything if we're cleaning up
        self.backupLock.acquire()
        if self.cleaningUp:
            self.backupLock.release()
            raise RuntimeError("Clean up has started, continuing to backup files will leave the system in an undefined state")
        manager = self.manager
        owngrp = None
        if owner is not None:
            owngrp = owner
            if group is not None:
                owngrp = "%s:%s" % (owngrp, group)

        dirpath, filename = os.path.split(path)
        backup = os.path.join(
            dirpath,
            filename + self.backupsuffix )
        chrootdirpath = dirpath
        chrootpath = path
        chrootbackup = backup
        if in_chroot and self.chroot is not None:
            chrootdirpath = self.chroot + dirpath
            chrootpath = self.chroot + path
            chrootbackup = self.chroot + backup

        oldowner = None
        oldgroup = None
        oldpermissions = None
        olddirowner = None
        olddirgroup = None
        olddirpermissions = None
        direxisted = False
        actualWritefile = writefile
        if writefile is None:
            actualWritefile = self.writefile
        try:
            olddirstat = os.stat(chrootdirpath)
            direxisted = True
            olddirowner = olddirstat.st_uid
            olddirgroup = olddirstat.st_gid
            olddirpermissions = oct(stat.S_IMODE(olddirstat.st_mode))
            oldstat = os.stat(chrootpath)
            oldowner = oldstat.st_uid
            oldgroup = oldstat.st_gid
            oldpermissions = oct(stat.S_IMODE(oldstat.st_mode))
        except Exception as e:
            self.log.devdebug("Getting old stat info for '%s' failed with: %s", path, str(e))
            self.log.devdebug("   Assuming path or file does not exist")
        manager.shellout(
            subprocess.call,
            ['mkdir', '-p', chrootdirpath],
            False)
        movedto = None
        try:
            if owngrp is not None:
                manager.shellout(
                    subprocess.check_call,
                    ['chown', owngrp, chrootdirpath],
                    False)
            elif group is not None:
                manager.shellout(
                    subprocess.check_call,
                    ['chgrp', group, chrootdirpath],
                    False)
            if dirpermissions is not None:
                manager.shellout(
                    subprocess.check_call,
                    ['chmod', dirpermissions, chrootdirpath],
                    False)
            try:
                command = ['mv']
                if not moveOriginal:
                    command=['cp']
                manager.shellout(
                    subprocess.check_output,
                    command + [chrootpath,chrootbackup],
                    False,
                    quiet_check=True )
                movedto = backup
                self.log.devdebug("Backed up '%s' to '%s'", chrootpath, chrootbackup)
            except Exception as e:
                self.log.devdebug("Attempting to move '%s' caused: %s (this is probably ok)", path, str(e))
            if setup:
                if moveOriginal:
                    manager.shellout(
                        subprocess.check_call,
                        ['touch', chrootpath],
                        False)
                if owngrp is not None:
                    manager.shellout(
                        subprocess.check_call,
                        ['chown', owngrp, chrootpath],
                        False)
                elif group is not None:
                    manager.shellout(
                        subprocess.check_call,
                        ['chgrp', group, chrootpath],
                        False)
                if permissions is not None:
                    manager.shellout(
                        subprocess.check_call,
                        ['chmod', permissions, chrootpath],
                        False)
        finally:
            #Ensure we try to reset the original condition even if everything
            #  blew up.
            self.files.append((
                path,
                movedto,
                oldowner,
                oldgroup,
                oldpermissions,
                direxisted,
                olddirowner,
                olddirgroup,
                olddirpermissions,
                restoreInPlace,
                in_chroot,
                writefile))
            #self.log.devdebug("File record added: %s", str(self.files[-1]))
            self.backupLock.release()
        return None

    def _restoreMovedFiles(self):
        for oldpath, backup, owner, group, permissions, direxisted, dirowner, dirgroup, dirpermissions, restoreInPlace, in_chroot, _ in self.files:
            olddir, _ = os.path.split(oldpath)
            chrootpath = oldpath
            chrootdir = olddir
            chrootbackup = backup
            manager = self.manager
            if in_chroot and self.chroot is not None:
                chrootpath = self.chroot + oldpath
                chrootdir = self.chroot + olddir
                if backup is not None:
                    chrootbackup = self.chroot + backup
            if backup is None:
                self.log.devdebug("No backup exists for: %s", oldpath)
            else:
                self.log.devdebug("Backup '%s' exists for: %s", backup, oldpath)
            if restoreInPlace and self.restore(oldpath, in_chroot):
                if chrootbackup is not None:
                    manager.shellout(
                        subprocess.call,
                        ['rm', chrootbackup],
                        False )
                if owner is not None:
                    oldowner = owner
                    if group is not None:
                        oldowner = "%s:%s" % (oldowner, group)
                    manager.shellout(
                        subprocess.call,
                        ['chown', oldowner, chrootpath],
                        False )
                elif group is not None:
                    manager.shellout(
                        subprocess.call,
                        ['chgrp', group, chrootpath],
                        False )
                if permissions is not None:
                    manager.shellout(
                        subprocess.call,
                        ['chmod', permissions, chrootpath],
                        False )
                if dirowner is not None:
                    oldowner = dirowner
                    if dirgroup is not None:
                        oldowner = "%s:%s" % (oldowner, dirgroup)

                    manager.shellout(
                        subprocess.call,
                        ['chown', oldowner, chrootdir],
                        False )
                elif dirgroup is not None:
                    manager.shellout(
                        subprocess.call,
                        ['chgrp', dirgroup, chrootdir],
                        False )
                if dirpermissions is not None:
                    manager.shellout(
                        subprocess.call,
                        ['chmod', dirpermissions, chrootdir],
                        False )
                continue
            olddir, _ = os.path.split(oldpath)
            manager.shellout(
                subprocess.call,
                ['rm', chrootpath],
                False )
            if backup is not None:
                try:
                    manager.shellout(
                        subprocess.check_call,
                        ['mv', chrootbackup, chrootpath],
                        False )
                    if owner is not None:
                        oldowner = owner
                        if group is not None:
                            oldowner = "%s:%s" % (oldowner, group)
                        manager.shellout(
                            subprocess.call,
                            ['chown', oldowner, chrootpath],
                            False )
                    elif group is not None:
                        manager.shellout(
                            subprocess.call,
                            ['chgrp', group, chrootpath],
                            False )
                    if permissions is not None:
                        manager.shellout(
                            subprocess.call,
                            ['chmod', permissions, chrootpath],
                            False )
                except Exception as e:
                    self.log.warning("The path '%s' couldn't be restored to '%s': %s", backup, oldpath, str(e))
            if direxisted:
                if dirowner is not None:
                    oldowner = dirowner
                    if dirgroup is not None:
                        oldowner = "%s:%s" % (oldowner, dirgroup)

                    manager.shellout(
                        subprocess.call,
                        ['chown', oldowner, chrootdir],
                        False )
                elif dirgroup is not None:
                    manager.shellout(
                        subprocess.call,
                        ['chgrp', dirgroup, chrootdir],
                        False )
                if dirpermissions is not None:
                    manager.shellout(
                        subprocess.call,
                        ['chmod', dirpermissions, chrootdir],
                        False )
            else:
                try:
                    manager.shellout(
                        subprocess.check_output,
                        ['rmdir', '-p', chrootdir],
                        False,
                        quiet_check=True )
                except Exception as e:
                    self.log.devdebug(
                        "rmdir did not complete - probably ok: %s: %s",
                        e.__class__.__name__,
                        str(e) )
        self.files = []

class CsmakeServiceConfigNotifierTimeout(Exception):
    pass

class CsmakeServiceConfigPoller(threading.Thread):
    def my_init(self, notifier, fileinfo, actualPath, pollRate):
        self.notifier = notifier
        self.fileinfo = fileinfo
        self.actualPath = actualPath
        self.pollRate = pollRate
        self.pollRunning = True
        self.waitToPoll = threading.Event()

    def run(self):
        while self.pollRunning:
            self.waitToPoll.wait()
            if self.pollRunning:
                self.notifier._processFile()
                time.sleep(self.pollRate)

    def startPolling(self):
        self.notifier.manager.log.debug("Polling signaled: %s", self.actualPath)
        if self.notifier._processFile():
            return
        self.waitToPoll.set()

    def stopPolling(self):
        self.waitToPoll.clear()

    def stop(self):
        self.pollRunning = False
        self.waitToPoll.set()

class CsmakeServiceConfigNotifier(pyinotify.ProcessEvent):
    def my_init(self, **kwargs):
        if 'manager' not in kwargs:
            raise ValueError("__init__ requires 'manager' argument")
        if 'fileinfo' not in kwargs:
            raise ValueError("__init__ requires 'fileinfo' argument")
        if 'actualPath' not in kwargs:
            raise ValueError("__init__ requires 'actualPath' argument")

        self.manager = kwargs['manager']
        self.fileinfo = kwargs['fileinfo']
        self.actualPath = kwargs['actualPath']
        if 'pollTime' in kwargs:
            self.pollTime = kwargs['pollTime']
        else:
            self.pollTime = self.manager.getDefaultPollRate()

        self.poller = CsmakeServiceConfigPoller()
        self.poller.my_init(
            self,
            self.fileinfo,
            self.actualPath,
            self.pollTime )
        self.instancesEnsured = []
        self.watcher = None
        self.thread = None
        self.wd = None
        self.poller.start()
        self.poller.startPolling()
        self.switchToNotifier()

    def switchToPolling(self):
        self.manager.log.debug("Switching to polling: %s", self.actualPath)
        self.poller.startPolling()
        self.releaseNotifiers()

    def switchToNotifier(self):
        self.manager.log.debug("Switching to notifier: %s", self.actualPath)
        try:
            self.setupWatcher()
            self.poller.stopPolling()
        except CsmakeServiceConfigNotifierTimeout:
            self.manager.log.warning("inotify contention detected: %s", self.actualPath)
            self.manager.notifyContentionDetected()
            self.stop()

    def setupWatcher(self):
        attempts = 0
        maxAttempts = 5
        noticeEvery=4
        sleepBetweenAttempts = 1
        while self.watcher is None and attempts < maxAttempts:
            attempts += 1
            try:
                self.watcher = pyinotify.WatchManager()
            except OSError as ose:
                if (attempts % noticeEvery) == 0:
                    self.manager.log.devdebug("'%s' still encountered attempting to setup pyinotify, try again period %ds", str(ose), sleepBetweenAttempts)
                elif attempts == 1:
                    self.manager.log.debug("'%s' encountered attempting to setup pyinotify, retrying every %ds for %ds until resources come free", str(ose), sleepBetweenAttempts, sleepBetweenAttempts * maxAttempts)
                time.sleep(sleepBetweenAttempts)
        if self.watcher is None:
            self.manager.log.warning("Could not establish watcher after %ds - Switching to polling", sleepBetweenAttempts*maxAttempts)
            raise CsmakeServiceConfigNotifierTimeout("Could not establish watcher after %ds")
        self.thread = pyinotify.ThreadedNotifier(self.watcher)
        self.thread.start()
        self.wd = None
        if self._processFile():
            return
        #Find the most specific extant path to watch
        directory, _ = os.path.split(self.actualPath)
        while not os.path.exists(directory):
            directory, _ = os.path.split(directory)
            if len(directory) == 0:
                raise ValueError(
                    "directory for '%s' doesn't exist" % self.actualPath)
        self.manager.log.devdebug("Adding watcher on: %s, for: %s", directory, self.actualPath)
        self.wd = self.watcher.add_watch(
            directory,
            pyinotify.IN_CREATE,
            self,
            auto_add=True)
        self.manager.log.debug("Notifiers active: %s", self.actualPath)

    def __del__(self):
        if hasattr(self, 'thread'):
            try:
                self.stop()
            except:
                self.manager.log.exception("Attempting to stop watcher failed")

    def stop(self):
        self.poller.stop()
        self.poller.join()
        self.releaseNotifiers()

    def releaseNotifiers(self):
        if self.thread is not None:
            try:
                self.thread.stop()
            except:
                self.manager.log.exception("Attempting to stop watcher failed")
        self.thread = None
        self.watcher = None
        self.wd = None

    def _removeWatch(self):
        if self.wd is not None:
            wd = self.wd
            self.wd = None
            self.watcher.rm_watch(wd, rec=True)

    def _processFile(self):
        if os.path.exists(self.actualPath):
            #The path already exists...don't watch it
            if self.actualPath in self.instancesEnsured:
                return True
            self.manager._ensureInstance(self.actualPath, self.fileinfo)
            self.instancesEnsured.append(self.actualPath)
            self._removeWatch()
            return True

        #Ensure any matches that already exist
        dirs = glob.glob(self.actualPath)
        for instance in dirs:
            if instance in self.instancesEnsured:
                continue
            self.manager._ensureInstance(
                instance,
                self.fileinfo )
            self.instancesEnsured.append(instance)
        return False

    def process_IN_CREATE(self, event):
        parent, _ = os.path.split(event.pathname)
        parentrel = os.path.relpath(self.actualPath, parent)
        targetrel = os.path.relpath(parent, self.actualPath)
        parentparts = [ x for x in parentrel.split('/') if x != '..' ]
        targetparts = [ x for x in targetrel.split('/') if x != '..' ]
        for part in parentparts:
            if len(targetparts) == 0:
                break
            targetpart = targetparts.pop(0)
            if not fnmatch.fnmatch(targetpart, part):
                self.manager.log.devdebug("Removing path watch: %s  For: %s", parent, self.actualPath)
                self.watcher.rm_watch(event.wd, rec=True)
                break
        if fnmatch.fnmatch(event.pathname, self.actualPath):
            self.manager.log.debug("Match for '%s': '%s'", self.actualPath, event.pathname)
            self._processFile()
        else:
            self.manager.log.devdebug("xxx No match '%s': '%s'", self.actualPath, event.pathname)

    def process_IN_Q_OVERFLOW(self, event):
        self.manager.log.devdebug("File processing overloaded")
        self._processFile()

class CsmakeServiceConfigManager(threading.Thread):
    def __init__(self, module, daemon, cwd=None, options={}):
        threading.Thread.__init__(self)
        self.lock = threading.RLock()
        self.daemonEvent = threading.Event()
        self.options = options
        self.chroot = options['chroot']
        self.noSudo = options['no-sudo']
        self.module = module
        self.daemon = daemon
        self.log = module.log
        self.defaultPollRate = .01

        #Tracking pyinotify monitors
        self.dirMonitors = []

        #Format is: [[<glob-path>, [<failed paths>], <type>, <callback>], ...]
        self.monitoringDirs = []
        self.monitoredDirs = []
        self.polledMonitoringDirs = []

        #Format is: {<path> : [<config objs>]}
        self.activeDirs = {}

        #Format is: {<type> : [<config objs>]}
        self.typeToObjs = {}

        self.running = True
        self.cwd = cwd
        self.waitForContention = threading.Event()

    def getDefaultPollRate(self):
        return self.defaultPollRate

    def notifyContentionDetected(self):
        self.waitForContention.set()

    def getDaemon(self):
        return self.daemon

    def shellout(self, subprocess_call, command, in_chroot=True, sudo=True, quiet_check=False, with_user_env=False):
        keywords = {}
        callCommand = command
        if subprocess_call is not subprocess.check_output:
            keywords['stdout'] = self.log.out()
            keywords['stderr'] = self.log.err()
        elif quiet_check:
            keywords['stderr'] = subprocess.STDOUT
        if self.cwd is not None:
            keywords['cwd'] = self.cwd
        sudo_cmd = ['sudo']
        if with_user_env:
            sudo_cmd.append('-E')
        if in_chroot and self.chroot is not None:
            if not sudo or self.noSudo :
                self.log.error("Can't chroot without sudo")
            callCommand = sudo_cmd + ['chroot', self.chroot] + command
        elif sudo and not self.noSudo:
            callCommand = sudo_cmd + command
        self.log.devdebug("shellout: %s(%s, %s)", str(subprocess_call), callCommand, str(keywords))
        return subprocess_call(
            callCommand,
            **keywords )

    def stop(self):
        self.lock.acquire()
        self.running = False
        self.waitForContention.set()
        self.lock.release()
        try:
            for monitor in self.dirMonitors:
                try:
                    monitor.stop()
                except:
                    self.log.exception("Attempting to stop a monitor")
        except:
            self.log.exception("Error processing monitor list")
        self.daemonEvent.set()
        if self.is_alive():
            self.join()
        self.clean()

    def clean(self):
        for key, value in self.typeToObjs.iteritems():
            for config in value:
                try:
                    config.clean()
                except:
                    self.log.exception("Cleaning '%s', path '%s' Failed", key.__name__, config.filepath())
        self.typeToObjs = {}
        self.activeDirs = {}

    #TODO: It would be really nice to set up pyinotify events
    #      instead of a poll loop as we should be able to
    #      catch and pounce on changes much more quickly
    def register(
        self,
        entrytype,
        paths,
        callback=None,
        ensure=True,
        in_chroot=True,
        path_prefix=None):
        self.lock.acquire()
        for path in paths:
            self.monitoringDirs.append(
                (path, [], entrytype, callback, path_prefix, in_chroot) )
        self.lock.release()
        if ensure:
            self.ensure()

    def getAllOfType(self, entrytype):
        if entrytype not in self.typeToObjs:
            return None
        else:
            return self.typeToObjs[entrytype]

    def update(self, entrytype):
        if entrytype not in self.typeToObjs:
            return
        self.lock.acquire()
        try:
            for instance in self.typeToObjs[entrytype]:
                instance.update()
        finally:
            self.lock.release()

    def _ensureInstance(
        self,
        instance,
        monEntry ):
        self.lock.acquire()
        try:
            curdir, failed, entrytype, callback, path_prefix, in_chroot = monEntry
            if instance in failed:
                return
            if instance not in self.activeDirs:
                self.activeDirs[instance] = []
            found = False
            for active in self.activeDirs[instance]:
                found = active.__class__ is entrytype
                if found:
                    break
            if not found:
                if entrytype not in self.typeToObjs:
                    self.typeToObjs[entrytype] = []
                try:
                    nonChrootPath = instance
                    if in_chroot and self.chroot is not None:
                        nonChrootPath = os.path.relpath(instance, self.chroot)
                        if '/..' in nonChrootPath:
                            #Punt on trying to get to a sane instance path
                            self.log.warning("The path '%s' is not rooted in '%s'", instance, self.chroot)
                            nonChrootPath = instance
                    if not nonChrootPath.startswith('/'):
                        if nonChrootPath.startswith("./"):
                            nonChrootPath = os.path.abspath(nonChrootPath)
                        else:
                            nonChrootPath = '/' + nonChrootPath
                    entry = entrytype(
                        self.module,
                        self,
                        nonChrootPath,
                        instance,
                        in_chroot,
                        self.chroot)
                    entry.ensure()
                    self.activeDirs[instance].append(entry)
                    self.typeToObjs[entrytype].append(entry)
                    if callback is not None:
                        callback(entry)
                except:
                    self.log.exception("Attempting to ensure configuration for '%s' failed", instance)
                    failed.append(instance)
        finally:
            self.lock.release()

    def run(self):
        minBackoffTime = 10
        maxBackoffTime = 240
        #Thread contention handler.
        while self.running:
            self.waitForContention.wait()
            if not self.running:
                break
            backoff = random.randint(minBackoffTime, maxBackoffTime)
            self.log.warning("Backing off inotify resources due to contention for %ds", backoff)
            for monitor in self.dirMonitors:
                monitor.switchToPolling()
            time.sleep(backoff)
            self.waitForContention.clear()
            for monitor in self.dirMonitors:
                monitor.switchToNotifier()

    def ensure(self):
        if not self.running:
            return
        self.lock.acquire()
        monitoringDirs = list(self.monitoringDirs)
        self.lock.release()
        for monEntry in monitoringDirs:
            curdir, failed, entrytype, callback, path_prefix, in_chroot \
                = monEntry
            pathStart = ''
            if path_prefix is not None:
                pathStart = path_prefix
            if in_chroot and self.chroot is not None:
                pathStart = self.chroot + pathStart
            self.lock.acquire()
            try:
                if monEntry not in self.monitoredDirs:
                    self.monitoredDirs.append(monEntry)
                    self.dirMonitors.append(
                        CsmakeServiceConfigNotifier(
                            manager=self,
                            fileinfo=monEntry,
                            actualPath=os.path.realpath(pathStart+curdir)))
            finally:
                self.lock.release()

class CsmakeServiceDaemon(threading.Thread):
    def __init__(self, module, provider, options):
        #Override init with any specific parameters desired
        #self.configManagerClass contains the configuration
        #  manager that the service will use
        threading.Thread.__init__(self)
        self.provider = provider
        self.configManagerClass = CsmakeServiceConfigManager
        self.configManager = None
        self.module = module
        self.log = module.log
        self.options = options
        self.stopListening = False
        self.ready = False
        self.endingCondition = threading.Condition()
        self.readyCondition = threading.Condition()
        self.exception = None
        self.process = None
        self.cwd = None
        self.port = options['port']
        if options['no-sudo']:
            if options['chroot'] is not None:
                self.log.error("Only root can chroot, but 'no-sudo' was selected as an option")
                raise ValueError("To chroot you must be able to sudo, but 'no-sudo' == True")

    def stop(self):
        self.endingCondition.acquire()
        self.stopListening = True
        self.endingCondition.notify_all()
        self.endingCondition.release()

    def stopAndJoin(self):
        self.stop()
        self.join()

    def _setupConfigs(self):
        #Before the service starts, the config manager needs to be
        #Set up with all the paths and handlers
        self.configManager.ensure()
        self.configManager.start()

    def _startListening(self):
        #If your daemon requires some setup to listen
        #  or it otherwise kicks off a service
        #Perform that here.  The guarantee is that
        #  When this returns, your service is listening.
        pass

    def _listeningLoop(self):
        #If your daemon requires a listening loop
        #Implement it here - do not exit the loop until
        #stopListening is True
        pass

    def _cleanup(self):
        #When the service has ended, this will be called for any cleanup
        #Work the service needs to do.
        pass

    def run(self):
        try:
            self.configManager = self.configManagerClass(
                self.module,
                self,
                self.cwd,
                self.options)
            self._setupConfigs()
            self._startListening()
            self._setReady()
            self._listeningLoop()
            self.endingCondition.acquire()
            if not self.stopListening:
                self.endingCondition.wait()
            self.endingCondition.release()
        except Exception as e:
            self.log.exception("The service failed to start: %s", str(e))
            self.exception = e
            raise
        finally:
            self.stopListening = True
            self._setReady()
            self._cleanup()
            if self.configManager is not None:
                self.configManager.stop()

    def isExecuting(self):
        return not self.stopListening

    def _setReady(self):
        if self.ready:
            return
        self.readyCondition.acquire()
        self.ready = True
        self.readyCondition.notify_all()
        self.readyCondition.release()

    def waitUntilReady(self):
        self.readyCondition.acquire()
        if not self.ready:
            self.readyCondition.wait()
        self.readyCondition.release()

class CsmakePortManager:
    @classmethod
    def _lock(clazz, log):
        lockdir = "/var/lock/csmake"
        lockfilename = "_CsmakePortManager.lock"
        fullpath = os.path.join(lockdir, lockfilename)
        lockfile = None
        try:
            if not os.path.exists(lockdir):
                os.makedirs(lockdir)
            lockfile = open(fullpath, 'a')
            log.devdebug("___ attempting lock %s", fullpath)
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            log.devdebug("LOCKED: %s", fullpath)
        except:
            if lockfile is not None:
                lockfile.close()
            log.exception("Failed to acquire lock for free port search")
        return lockfile

    @classmethod
    def _unlock(clazz, lockfile, log):
        lockdir = "/var/lock/csmake"
        lockfilename = "_CsmakePortManager.lock"
        fullpath = os.path.join(lockdir, lockfilename)
        try:
            fcntl.flock(lockfile, fcntl.LOCK_UN)
            log.devdebug("UNLOCKED: %s", fullpath)
        except:
            log.exception("Couldn't unlock: %s", fullpath)
        try:
            lockfile.close()
        except:
            log.exception("Couldn't close: %s", fullpath)

    @classmethod
    def findOpenTcpPort(clazz, interface, start, stop, log, sockethandler=None):
        openPort = None
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if sockethandler is not None:
            sock = sockethandler(sock)
        lockfile = clazz._lock(log)
        if isinstance(start, basestring):
            start = int(start)
        if isinstance(stop, basestring):
            stop = int(stop)
        try:
            for port in range(start, stop+1):
                try:
                    sock.bind((interface, port))
                    openPort = clazz(interface, port, sock, log, sockethandler)
                except socket.error as sockerr:
                    #This port is free
                    log.devdebug("Port %d is unavailable: %s", port, str(sockerr))
                if openPort is not None:
                    break
        finally:
            if lockfile is not None:
                clazz._unlock(lockfile, log)
        return openPort

    @classmethod
    def createPort(clazz, interface, port, log, sockethandler=None):
        try:
            return clazz(interface, port, None, log, sockethandler)
        except socket.error as soerr:
            if soerr.errno == 13:  #Permission denied - patch in NAT
                return CsmakeNATPortManager(interface, port, log, sockethandler)
            else:
                raise

    @classmethod
    def getUserPortRange(clazz, log):
        ports = subprocess.check_output(
            ['cat', '/proc/sys/net/ipv4/ip_local_port_range'] )
        portparts = ports.split()
        return portparts

    def __init__(self, interface, port, sock, log, sockethandler):
        self.interface = interface
        self.port = port
        self.log = log
        self.lockfile = None
        self.sock = sock
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            #SO_REUSEADDR is useful if you have to close and rebind/relisten
            #  in a hurry, but it also means that multiple binds can occur
            #  on the same address
            #self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sockethandler is not None:
                self.sock=sockethandler(self.sock)
            self.sock.bind((interface, port))
            self.log.debug("Bound %s:%s", interface, port)

    def cleanup(self):
        try:
            self.unbind()
        except:
            if hasattr(self, 'log'):
                self.log.exception("Unbind failed")
        try:
            self.unlock()
        except:
            if hasattr(self, 'log'):
                self.log.exception("Unlock failed")

    def __call__(self):
        self.cleanup()

    def lock(self):
        if self.lockfile is not None:
            return
        self.lockfile = self._lock(self.log)

    def unlock(self):
        if self.lockfile is None:
            return
        self._unlock(self.lockfile, self.log)
        self.lockfile = None

    def unbind(self):
        if self.sock is not None:
            self.sock.close()
            self.log.debug("freed %s:%s", self.interface, self.port)
            self.sock = None

    def realaddress(self):
        return (self.interface, self.port)

    def address(self):
        return (self.interface, self.port)

    def __del__(self):
        self.cleanup()

class CsmakeNATPortManager(CsmakePortManager):

    def __init__(self, interface, port, log, sockethandler):
        self.natted = False
        self.sock = None
        try:
            userlow, userhigh = CsmakePortManager.getUserPortRange(log)
        except:
            log.exception("No user range found, using 20000-21000")
            userlow, userhigh = ("20000","21000")
        self.bindport = CsmakePortManager.findOpenTcpPort(
            interface,
            userlow,
            userhigh,
            log,
            sockethandler )
        self.iptablesCommand = ['sudo', 'iptables',
             '--table', 'nat',
             '--append', 'OUTPUT',
             '--source', str(interface),
             '--protocol', 'tcp',
             '--dport', str(port),
             '--jump', 'REDIRECT',
             '--to-port', str(self.bindport.port) ]
        subprocess.check_call(
            self.iptablesCommand,
            stdout = log.out(),
            stderr = log.err())
        self.natted = True
        self.iptablesCommand[4] = '--delete'
        CsmakePortManager.__init__(self, interface, port, self.bindport.sock, log, sockethandler)

    def address(self):
        return self.bindport.address()

    def cleanup(self):
        #Clean up NAT
        if self.natted:
            subprocess.call(
                self.iptablesCommand,
                stdout = self.log.out(),
                stderr = self.log.err())
            self.natted = False
        self.bindport.cleanup()
        CsmakePortManager.cleanup(self)

class CsmakeServiceProvider:
    serviceProviders = {}
    portManagers = {}

    @classmethod
    def getServiceProvider(clazz, tag):
        if tag not in clazz.serviceProviders:
            return None
        return clazz.serviceProviders[tag]

    @classmethod
    def createServiceProvider(clazz, tag, module, **options):
        provider = clazz.getServiceProvider(tag)
        if provider is None:
            provider = clazz(module, tag, **options)
            clazz.serviceProviders[tag] = provider
        return provider

    @classmethod
    def hasServiceProvider(clazz, tag):
        return tag in clazz.serviceProviders

    @classmethod
    def disposeServiceProvider(clazz, tag):
        if tag not in clazz.serviceProviders:
            return
        clazz.serviceProviders[tag].endService()
        del clazz.serviceProviders[tag]

    def __init__(self, module, tag, **options):
        self.service = None
        self.serviceClass = CsmakeServiceDaemon
        self.tag = tag
        self.module = module
        self.log = module.log
        try:
            portparts = CsmakePortManager.getUserPortRange(self.log)
            self.lowerport = int(portparts[0])
            self.upperport = int(portparts[1])
        except Exception as e:
            self.log.debug("Failed to get port range, using defaults: (%s)", str(e))
            self.lowerport=20000
            self.upperport=24000
        self.options = options
        self._processOptions()

    def _customizeSocket(self, socket):
        return socket

    #Options processed in the base implementation
    # interfaces
    # port
    # port-range
    # chroot
    # no-sudo
    # Other options specific to your service should be handled in the
    #  override for this method
    def _processOptions(self):
        if 'interfaces' not in self.options:
            self.options['interfaces'] = 'localhost'
        interfaces = ','.join(self.options['interfaces'].split('\n')).split(',')
        self.options['interfaces'] = [
            x.strip() for x in interfaces if len(x.strip()) > 0 ]
        if 'chroot' not in self.options:
            self.options['chroot'] = None
        if 'no-sudo' not in self.options:
            self.options['no-sudo'] = False
        if 'port' not in self.options:
            lower = self.lowerport
            upper = self.upperport
            if 'port-range' in self.options:
                rangeParts = self.options['port-range'].split('-')
                if len(rangeParts) != 2:
                    self.log.error("Range in 'port-range' must be <lower>-<upper>")
                    self.log.error("    Got: %s", self.options['port-range'])
                    raise ValueError("'port-range' invalid")
                lower = int(rangeParts[0].strip())
                upper = int(rangeParts[0].strip())
            else:
                self.log.info("Range for ports not defined, using %d-%d", lower, upper)
            openPort = CsmakePortManager.findOpenTcpPort(
                interfaces[0],
                lower,
                upper,
                self.log,
                self._customizeSocket)
            if openPort is None:
                self.log.error("Ports %d-%d are all occupied", lower, upper)
                raise RuntimeError("No port could be found to run the service")
            self.options['port'] = openPort
        else:
            self.options['port'] = CsmakePortManager.createPort(
                interfaces[0],
                int(self.options['port']),
                self.log,
                self._customizeSocket )
        if 'interface-env' in self.options:
            self.module.env.env[self.options['interface-env']] = self.options['port'].address()[0]
        if 'port-env' in self.options:
            self.module.env.env[self.options['port-env']] = self.options['port'].address()[1]
        self.log.devdebug("Working with interfaces: %s", str(self.options['interfaces']))

    def startService(self):
        if self.service is not None:
            self.service.waitUntilReady()
            return self.service
        self.service = self.serviceClass(self.module, self, self.options)
        self.service.start()
        self.service.waitUntilReady()
        return self.service

    def isServiceExecuting(self):
        if self.service is not None:
            self.service.waitUntilReady()
            return self.service.isExecuting()
        return False

    def endService(self):
        if self.service is None:
            return None
        self.service.stopAndJoin()
        self.service = None
        try:
            if 'port' in self.options and self.options['port'] is not None \
               and not isinstance(self.options['port'], basestring):
                self.options['port'].cleanup()
        except Exception as e:
            self.module.log.debug("Attempt to free port object failed: %s", str(e))

