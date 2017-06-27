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

class GitLatestShaTag(CsmakeModuleAllPhase):
    """Purpose: Get the latest created tag from a formatted list of tags
       Library: csmake-providers
       Note: Lightweight tags (tags without messages) will use the commit
             date from the commit pointed to by the tag.
             This may cause apparent inconsistencies if committed and
             lightweight tags both match the format string.
       Options:
           repo - The git URL for the repo
           format - The name format of the tags to search
                    (all glob wildcards work)
           env - Environment variable to inject the SHA
           fetch-ref - (OPTIONAL) Reference to start search from
                   (use 'branch:<name>' or 'tag:<name>' or '<sha1>')
           local - (OPTIONAL) Local location for repository
                   Default: %(RESULTS)s/<name of repo>
       Phases:
           env, pull, sources - Gets the sha (will populate the env for following phases)
           * - Sets env to <unknown> (unless already populated)
    """

    REQUIRED_OPTIONS = ['repo', 'format', 'env']

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
        self.log.debug("Ref: %s, Reftype: %s", ref, reftype)
        GitProvider.fetchRepository(
            self.log,
            name,
            localrepo,
            repo,
            ref,
            reftype,
            secure=False )
        repoObject = git.Repo(localrepo)
        dateOfCurrent = repoObject.commit().authored_date
        tagList = []
        self.log.debug("Current date: %d", dateOfCurrent)
        for tag in repoObject.tags:
            #Is the tag a lightweight object?
            if tag.object.__class__ is git.Commit:
                #Yes.  Deal with the missing data.
                tagObject = {
                    'name':str(tag),
                    'commit':tag.object,
                    'date':tag.object.authored_date,
                    'authored_date':tag.object.authored_date,
                    'tag_sha':tag.object.hexsha,
                    'commit_sha':tag.object.hexsha
                }
            else:
                tagObject = {
                    'name':str(tag),
                    'commit':tag.object.object,
                    'date':tag.object.tagged_date,
                    'authored_date':tag.object.object.authored_date,
                    'tag_sha':tag.object.hexsha,
                    'commit_sha':tag.object.object.hexsha
                }
            self.log.debug(
                "Tag: %s, Date: %d",
                tagObject['name'],
                tagObject['authored_date'])
            if fnmatch.fnmatch(tagObject['name'], options['format']) \
               and tagObject['authored_date'] <= dateOfCurrent:
                tagList.append(tagObject)

        if len(tagList) == 0:
            self.log.failed()
            self.log.error("No tags found")
            return self.default(options)
        tagList.sort(key=lambda x: x['date'], reverse=True)
        tag = tagList[0]
        self.log.info("Tag found: %s (%s, %s)", tag['name'], tag['tag_sha'], tag['commit_sha'])
        result = tag['commit_sha']
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
