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
from Csmake.CsmakeModuleAllPhase import CsmakeModuleAllPhase
from CsmakeProviders.GitProvider import GitProvider
import os.path
import git
import fnmatch

class GitFirstRelevantSha(CsmakeModuleAllPhase):
    """Purpose: Get the first relevant sha from the given reference
                NOTE: This does not properly handle the case where
                      a starting reference is a composite of
                      several trees.
                      It will only resolve the left-most tree(s)
       Library: csmake-providers
       Options:
           repo - The git URL for the repo
           env - Environment variable to inject the SHA
           fetch-ref - (OPTIONAL) Reference to start search from
                   (use 'branch:<name>' or 'tag:<name>' or '<sha1>')
                   Default is branch:master
           local - (OPTIONAL) Local location for repository
                   Default: %(RESULTS)s/<name of repo>
       Phases:
           env, pull, sources - Gets the sha (will populate the env for following phases)
           * - Sets env to <unknown> (unless already populated)
    """

    REQUIRED_OPTIONS = ['repo', 'env']

    def env(self, options):
        return self.pull(options)

    def sources(self, options):
        return self.pull(options)

    def pull(self, options):
        repo = options['repo']
        if repo.startswith("file://./"):
            repo = repo.replace('.', os.path.abspath('.'), 1)
        findrefs = False
        result = None
        if 'local' in options:
            localrepo = options['local']
            _, name = os.path.split(localrepo)
        else:
            _, localrepo = os.path.split(repo)
            name = localrepo
            localrepo = os.path.join(
                './',
                self.env.env['RESULTS'],
                localrepo )
        fetchRef = None
        if 'fetch-ref' in options:
            fetchRef = options['fetch-ref']
        ref, reftype = GitProvider.splitRepoReference(fetchRef)
        self.log.debug("Starting Ref: %s, Reftype: %s", ref, reftype)
        GitProvider.fetchRepository(
            self.log,
            name,
            localrepo,
            repo,
            ref,
            reftype,
            secure=False )
        repoObject = git.Repo(localrepo)
        remote, _ = GitProvider.ensureCsmakeRemote(repoObject, repo)
        startsha = GitProvider.getSHAFromRef(
                        self.log,
                        repoObject,
                        remote,
                        ref,
                        reftype)
        if startsha is None:
            self.log.error("The reference %s could not be resolved from the given repo", ref)
            self.log.failed()
            return None
        parent = repoObject.commit(startsha)
        while True:
            if len(parent.parents) == 0:
                break
            parent = parent.parents[0]

        result = parent.hexsha
        self.env.addTransPhase(options['env'], result)
        self.log.passed()
        return result

    def default(self, options):
        result = '<unknown>'
        if options['env'] not in self.env.env:
            self.env.env[options['env']] = result
        else:
            result = self.env.env[options['env']]
        self.log.passed()
        return result
