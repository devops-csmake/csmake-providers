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
import os.path
import codecs
import git
import yaml

class GenerateGitChangeLog(CsmakeModule):
    """Purpose: Generate a changelog of the changes between two git hashes
       Library: csmake-providers
       Mapping: Use **yields-files to specify the output and the format
                For example:
                **yields-files =
                     <migration (log:changelog)> migration/changelog.txt
                Will generate a text log of the records
                Mapping types supported:
                    tsv - Tab separated values format
                        URL\tSHA1\tsummary\tauthor\tiso date of change
                    csv - Comma separated values format
                        URL, SHA1, summary, author, iso date of change
                    yaml - YAML formatted output
                    log - Simple text log format (like git log --oneline)
                        SHA1[:7] summary
                NOTE: To change the formatting, specialize GenerateGitChangeLog
                      and define _formatOutput and/or (re)define the appropriate
                      _<type>Formatter (see implementation comments)
       Options:
           old - The old ref/SHA-1 to compare
                 (branch:<name>, tag:<name>, <reference/sha>)
           new - The new ref/SHA-1 to compare
                 (branch:<name>, tag:<name>, <reference/sha>)
           repo - The git URL for the repo
           local - (OPTIONAL) Local location for repository
                   Default: %(RESULTS)s/<name of repo>
       Phases:
           build - Generate a change log based on the given ref/SHA1's
    """

    REQUIRED_OPTIONS = ['old', 'new', 'repo']


    #--------------------------------------------------------------
    # Formatter classes
    #   By defualt the formatting will attempt to instantiate a
    #   locally defined _<type>Formatter
    #--------------------------------------------------------------
    class _logFormatter:
        def nolog(self, fileobj, extrainfo={}):
            fileobj.write("*** No Changes Detected ***\n")
            if 'errortext' in extrainfo:
                fileobj.write("----- %s" % extrainfo['errortext'])

        def output(self, fileobj, changelog, extrainfo={}):
            if changelog['type'] == 'parent':
                for log in changelog['history']:
                    self.customize(log, extrainfo)
                    fileobj.write("%s\n" % self.formatRecord(log))
            else:
                self.diverged(fileobj, changelog, extrainfo)

        def customize(self, logentry, extrainfo):
            #Use this to create custom fields from the information present
            #Update the logentry dictionary directly.
            logentry.update(extrainfo)

        def diverged(self, fileobj, changelog, extrainfo):
            fileobj.write(
                "NOTE: Record history diverges\n")
            old = result['old']
            if old is not None:
                fileobj.write("----- Old Record:\n")
                self.customize(old, extrainfo)
                fileobj.write("   %s\n" % self.formatRecord(old))
            new = result['new']
            if new is not None:
                fileobj.write("----- New Record:\n")
                self.customize(new, extrainfo)
                fileobj.write("   %s\n" % self.formatRecord(new))
            common = result['common']
            if common is not None:
                fileobj.write("----- Common Record:\n")
                self.customize(common, extrainfo)
                fileobj.write("   %s\n" % self.formatRecord(common))

        def formatRecord(self, logentry):
            return "%(SHA1)0.7s %(summary)s" % logentry

    class _tsvFormatter(_logFormatter):
        def formatRecord(self, logentry):
            return "%(URL)s\t%(SHA1)s\t%(summary)s\t%(author)s\t%(isodate)s" % logentry
        def customize(self, logentry, extrainfo):
            GenerateGitChangeLog._logFormatter.customize(self, logentry, extrainfo)
            logentry['isodate'] = logentry['datetime'].isoformat()

    class _csvFormatter(_logFormatter):
        def formatRecord(self, logentry):
            return "%(URL)s,%(SHA1)s,\"%(summary)s\",\"%(author)s\",%(isodate)s" % logentry
        def customize(self, logentry, extrainfo):
            GenerateGitChangeLog._logFormatter.customize(self, logentry, extrainfo)
            logentry['isodate'] = logentry['datetime'].isoformat()

    class _yamlFormatter(_logFormatter):
        def nolog(self, fileobj, extrainfo):
            result = {'message': "*** No Change Detected ***"}
            result.update(extrainfo)
            yamltext = yaml.safe_dump(result)
            fileobj.write(yamltext)

        def output(self, fileobj, changelog, extrainfo={}):
            changelog.update(extrainfo)
            yamltext = yaml.safe_dump(changelog)
            fileobj.write(yamltext)

    #---------------------------------------------------------------
    #  _formatOutput
    #      Top function for formatting output
    #---------------------------------------------------------------

    def _formatOutput(self, changelog, files, extrainfo={}):
        for spec in files:
            classString = '_%sFormatter' % spec[1]
            if not hasattr(self, classString):
                self.log.error("File '%s' type '%s' does not have a output formatter defined", spec[0], spec[1])
            else:
                UTF8Writer = codecs.getwriter('utf8')
                with open(spec[0], 'w') as fileobj:
                    fileobj = UTF8Writer(fileobj)
                    formatter = getattr(self, classString)()
                    if changelog is None:
                        formatter.nolog(fileobj, extrainfo)
                    else:
                        formatter.output(fileobj, changelog, extrainfo)

    #---------------------------------------------------------------
    # csmake Phase implementations
    #---------------------------------------------------------------
    def build(self, options):
        if self.yieldsfiles is None:
            self.log.warning("**yields-files was not specified in section.   Nothing to do...")
            self.log.warning("   No changelog will be produced")
            self.log.passed()
            return None

        filespecs = []
        for index in self.yieldsfiles:
            location = index['location']
            if not location.startswith('/') and \
               not location.startswith('./'):
                   location = os.path.join(
                       self.env.env['RESULTS'],
                       index['location'] )
            filespecs.append((location, index['type']))

        repoURL = options['repo']
        findrefs = False
        nochange = False
        nochangeString = "Unknown reason"
        if len(options['old']) == 0 or options['old'] == '<unknown>':
            self.log.info("There is no valid previous version")
            nochangeString = "No valid previous version"
            nochange = True
        if options['old'] == options['new']:
            self.log.info("The old and new versions are the same, no change")
            nochangeString = "Old and new versions identical"
            nochange = True

        if nochange:
            self._formatOutput(None, filespecs, {'errortext': nochangeString})
            self.log.passed()
            return True

        if 'local' in options:
            localrepo = options['local']
            _, name = os.path.split(localrepo)
        else:
            _, localrepo = os.path.split(repoURL)
            name = localrepo
            localrepo = os.path.join(
                self.env.env['RESULTS'],
                localrepo )
        newref, newreftype = GitProvider.splitRepoReference(options['new'])
        oldref, oldreftype = GitProvider.splitRepoReference(options['old'])
        try:
            repo = git.Repo(localrepo)
        except git.exc.NoSuchPathError:
            GitProvider.fetchRepository(
                self.log,
                name,
                localrepo,
                repoURL,
                newref,
                newreftype,
                secure=False )
            repo = git.Repo(localrepo)
        remote, _ = GitProvider.ensureCsmakeRemote(repo, repoURL)
        try:
            new = GitProvider.getSHAFromRef(
                      self.log,
                      repo,
                      remote,
                      newref,
                      newreftype )
            old = GitProvider.getSHAFromRef(
                      self.log,
                      repo,
                      remote,
                      oldref,
                      oldreftype )
        except Exception as e:
            self.log.info("getSHA threw '%s' attempting to lookup ref, retrying", str(e))
            GitProvider.fetchRepository(
                self.log,
                name,
                localrepo,
                repo,
                newref,
                newreftype,
                secure=False )
            new = GitProvider.getSHAFromRef(
                      self.log,
                      repo,
                      remote,
                      newref,
                      newreftype )
            old = GitProvider.getSHAFromRef(
                      self.log,
                      repo,
                      remote,
                      oldref,
                      oldreftype )
        try:
            result = GitProvider.generateSpanLogInfo(
                self.log,
                localrepo,
                old,
                new,
                findrefs )
        except Exception as e:
            self.log.info("Span log threw '%s' attempting to fetch and try again", str(e))
            try:
                GitProvider.fetchRepository(
                    self.log,
                    name,
                    localrepo,
                    repo,
                    newref,
                    newreftype,
                    secure=False )
                result = GitProvider.generateSpanLogInfo(
                    self.log,
                    localrepo,
                    old,
                    new,
                    findrefs )
            except:
                self.log.exception("Attempt to generate git changelog failed")
                self.log.failed()
                return None

        self.log.devdebug("result == %s", str(result))
        self._formatOutput(result,filespecs,{'URL' : repoURL})
        self.log.passed()
