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
from Csmake.CsmakeModule import CsmakeModule
from CsmakeProviders.GitProvider import GitProvider
import git
import shutil
import os.path

class GitDependent(CsmakeModule):
    """Purpose: Download dependency for a build from git
       Library: csmake-providers
       Options:
           URL    - Location of the repo
           name   - Name of the repo
           ref    - Reference to retrieve - defaults to remote 'master'
                       NOTE: master is a common convention not guaranteed
                       Also Note: Will resolve file://. to the appropriate
                                  absolute path
                    Optionally:
                        for tags, prefix with 'tag:'
                        for branches, prefix with 'branch:'
                        If the prefix isn't used, the logic will guess
                           and the guessing will be: SHA, tag, branch
                        If you happen to be doing other things with
                           the repository this points to and you
                           do not specify a prefix, and happen to have a local
                           branch named the same as a tag, you will end
                           up with this branch as the code base
                           ...Oh, and you shouldn't use this repo this way
                              this module will hard reset head.
                              Proceed at your own risk.
           local  - Directory to put the repo (will use substitutions)
           secure - (OPTIONAL) if True, will attempt fully secured access
                    to https repos.  Otherwise, it will disable
                    checking of the https host's certificate
           env - (OPTIONAL) Sets the name provided to the local path
                            in the csmake environment.
       Phases:
           pull, sources - Will download the specified git repo
           clean - will remove the specified git repo from local storage
       Dependencies:
           GitPython - apt-get install git-python"""

    REQUIRED_OPTIONS = ['URL', 'name', 'ref', 'local']

    def sources(self, options):
        return self.pull(options)

    def pull(self, options):
        self.log.debug("Options are: %s", str(options))
        #TODO: Do check for required parameters

        local = options["local"]
        name = options['name']
        (name, localRepo) = GitProvider.determineRepoPath(local, name)
        reporef = None
        if 'ref' in options:
            reporef = options['ref']
        (ref, reftype) = GitProvider.splitRepoReference(reporef)

        if ref is None:
            msg = "Reference '%s' is not understood" % ref
            self.log.error(msg)
            self.log.failed()
            return (False, "ERROR", msg)
        ref = self.env.doSubstitutions(ref)

        url = options['URL']
        if url.startswith("file://./"):
            url = url.replace('.', os.path.abspath('.'), 1)
        secure = False
        if 'secure' in options:
            secure = options['secure'] == 'True'

        if 'env' in options:
            self.env.env[options['env']] = localRepo

        return GitProvider.fetchRepository(
            self.log,
            name,
            localRepo,
            url,
            ref,
            reftype,
            secure=secure )

    def clean(self, options):
        local = self.env.doSubstitutions(options["local"])
        name = options['name']

        (name, path) = GitProvider.determineRepoPath(local, name)
        if 'env' in options:
            self.env.env[options['env']] = path
        try:
            shutil.rmtree(path)
        except Exception as e:
            self.log.info("Could not remove path '%s': %s", path, repr(e))
        self.log.passed()

    def default(self, options):
        local = options["local"]
        name = options['name']
        (name, localRepo) = GitProvider.determineRepoPath(local, name)
        if 'env' in options:
            self.env.env[options['env']] = localRepo
        self.log.passed()
