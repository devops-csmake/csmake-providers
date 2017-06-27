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
from Csmake.FileManager import FileManager, FileSpec, FileInstance
import git
import yaml
import os.path

class GitTagRefs(CsmakeModule):
    """Purpose: Tag the refs from provided csversion mainfest files
       Library: csmake-providers
       Options:
           files - Regular file names or csmake file tracking
                   statements will work here.  Newline or comma delimited
                   Files either need to be a csversion manifest
                   or a yaml list of sources from a csversion manifest
           tag - Name of the tag to create
           multiref-allowed = (OPTIONAL) Default: False
                 If a single build can come from multiple sources
                 then set this to True
                 The first reference found will be set to the tag
                 All references will also be tagged with the following tag:
                      <tag>_<build label>
                 If this is false and multiple references are found,
                      the tagging will fail.
           message - (OPTIONAL) Adds a message to the tag
                     When this is used, it creates a new tag record.
           secure - (OPTIONAL) Default False
                    If True, https pulls will fail on invalid certs.
           local - (OPTIONAL) Local path for repositories
                   Default: %(RESULTS)s/<name of repo>
       Phases:
           tag - Tag the repo
       Notes:
           Expected format of the yaml file is a csversion sources
           styled format.
           The operation for many large repos will take some time
    """

    REQUIRED_OPTIONS = ['files', 'tag']

    def _processCsversionSources(self, sources, gitrefs):
        for source, build in sources.iteritems():
            for buildname, data in build.iteritems():
                if data[0] == 'git':
                    if source not in gitrefs:
                        gitrefs[source] = {}
                    url = data[1]['URL']
                    if url not in gitrefs[source]:
                        gitrefs[source][url] = []
                    gitrefs[source][url].append([data[1], buildname])

    def _createGitTagList(self, gitrefs):
        taglist = []
        for source, urldict in gitrefs.iteritems():
            for url, entries in urldict.iteritems():
                leadref = entries[0][0]['REF']
                for entry in entries:
                    if self.multiref:
                        taglist.append((
                            url,
                            "%s_%s" % (self.tag, entry[1]),
                            entry[0]['REF'] ) )
                    elif leadref != entry[0]['REF']:
                        self.log.error("Inconsistent references")
                        self.log.error("   For Repo: %s", url)
                        self.log.error("   In Build: %s", entry[1])
                        self.log.error("   Expected: %s", leadref)
                        self.log.error("   Got     : %s", entry[0]['REF'])
                        raise ValueError("Inconsistent References Detected")
                taglist.append((
                    url,
                    self.tag,
                    leadref ))
        return taglist

    def tag(self, options):
        self.tag = options['tag']
        self.message = None
        if 'message' in options:
            self.message = options['message']
        self.multiref = False
        if 'multiref-allowed' in options:
            self.multiref = options['multiref-allowed'] == 'True'
        self.secure = False
        if 'secure' in options:
            self.secure = options['secure'] == 'True'
        self.local = self.env.env['RESULTS']
        if 'local' in options:
            self.local = options['local']
        fileManager = self._getFileManager()
        files = self._parseCommaAndNewlineList(options['files'])
        references = fileManager.resolveFileMappings(files, True)
        self.log.devdebug(references)
        files = [ reference.index['location'] for reference in references ]
        gitrefs = {}
        for filepath in files:
            with open(filepath) as f:
                current = yaml.load(f)
            if 'sources' in current:
                self._processCsversionSources(current['sources'], gitrefs)
            else:
                for source in current:
                    self._processCsversionSources(source, gitrefs)
        try:
            taglist = self._createGitTagList(gitrefs)
        except ValueError:
            self.log.failed()
            return None
        self.log.devdebug(taglist)
        for url, tag, ref in taglist:
            if '(' in url or '(' in tag:
                self.log.warning("Invalid reference or url found: %s, %s", tag, url)
                continue
            _,localname = os.path.split(url)
            #We may want to consider adding a urltag of some sort
            #in to the local...
            #   however, we will probably be ok not to
            ref, reftype = GitProvider.splitRepoReference(ref)
            localRepo = os.path.join(
                    self.local,
                    localname )
            if url.startswith("file://./"):
                url = url.replace('.', os.path.abspath('.'), 1)
            if len(url.strip()) == 0:
                self.log.warning("A blank url was found for ref '%s'", url)
                continue
            GitProvider.fetchRepository(
                self.log,
                url,
                localRepo,
                url,
                ref,
                reftype,
                secure = self.secure )
            repoObj = git.Repo(localRepo)
            remote, oldurl = GitProvider.ensureCsmakeRemote(
                repoObj,
                url,
                self.log )
            #Duplicate tags are ok
            try:
                GitProvider.pushTag(
                    repoObj,
                    tag,
                    remote,
                    self.message )
            except git.exc.GitCommandError as gce:
                if gce.status == 128 and 'already exists' in gce.stderr:
                    self.log.info("The tag for '%s' already exists", localname)
                else:
                    raise


        self.log.passed()
        return None

