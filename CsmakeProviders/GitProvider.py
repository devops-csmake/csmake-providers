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
import git
import shutil
import os.path
import datetime

class GitProvider:

    @staticmethod
    def determineRepoPath(local, name):
        localRepo = os.path.join(
            local,
            name)
        return (name, localRepo)

    @staticmethod
    def splitRepoReference(reporef):
        if reporef is None:
            # By convention
            ref = 'master'
            reftype = 'branch'
        else:
            ref = reporef
            refparts = ref.split(':')
            if len(refparts) == 1:
                ref = refparts[0]
                reftype = None
            elif len(refparts) == 2:
                ref = refparts[1]
                reftype = refparts[0]
            else:
                return (None, None)

        return (ref, reftype)

    @staticmethod
    def _createLogRecord(record, repostruct):
        parts = ["SHA1", "ref", "refs", "message", "summary", "author", "datetime"]
        sha, ref = record.name_rev.split()
        refsdict = repostruct['refsdict']
        refs = []
        if sha in refsdict:
            refs = refsdict[sha]
        # The authored date is utc with a separate timezone offset
        #  This is verified in test_spanLogSimple
        dt = datetime.datetime.utcfromtimestamp(record.authored_date)
        result = dict(zip(
            parts,
            [sha, ref, refs, record.message, record.summary, record.author, dt]))

        result['author'] = unicode(result['author'])
        return result

    @staticmethod
    def _populateRefLookups(repo, reflookups):
        csmakeRemote = 'Csmake/'
        lenRemote = len(csmakeRemote)
        for ref in repo.refs:
            try:
                sha = ref.commit.hexsha
                name = ref.name
                if name.startswith(csmakeRemote):
                    name = name[lenRemote:]
                if sha not in reflookups:
                    reflookups[sha] = []
                reflookups[sha].append(name)
            except:
                # Not handling non commit refs for now
                pass

    @staticmethod
    def _fetchRemote(remote, log):
        try:
            if log is not None:
                log.debug("_fetchRemote - about to do remote.fetch()")
            remote.fetch('+refs/*:refs/remotes/Csmake/*', prune=True)
        except AssertionError:
            if log is not None:
                log.debug("_fetchRemote - in exception, trying remote.fetch() again")
            # Workaround for https://github.com/gitpython-developers/GitPython/issues/94
            remote.fetch('+refs/*:refs/remotes/Csmake/*', prune=True)
            if log is not None:
                log.debug("_fetchRemote - in exception, after second call to remote.fetch()")

    @staticmethod
    def pushTag(repo, tagname, remote, message=None):
        tag=repo.create_tag(tagname, message=message)
        remote.push(tag)

    @staticmethod
    def ensureCsmakeRemote(repo, URL, log=None):
        if log is not None:
            log.debug("starting ensureCsmakeRemote()")
        oldurl = ''
        remoteIsGood = False
        try:
            if log is not None:
                log.debug("Attempting to access Csmake remote references")
            remote = repo.remotes.Csmake
            oldurl = remote.url
            if remote.url != URL:
                if log is not None:
                    log.debug("Remote has changed location")
                repo.delete_remote(remote)
                raise AttributeError('Csmake')
        except Exception as e:
            if log is not None:
                log.debug("Attempting to create a new Csmake remote reference")
            repo.create_remote('Csmake', URL)
            remote = repo.remotes.Csmake
            if log is not None:
                log.debug("Attempting fetch with fresh remote - calling _fetchRemote()")
            GitProvider._fetchRemote(remote, log)

        return (remote, oldurl)

    @staticmethod
    def getSHAFromRef(csmakelog, repo, remote, ref, reftype):
        if reftype == 'tag':
            tagref = "tags/%s" % ref
            try:
                newSHA = remote.refs[tagref].commit.hexsha
            except (ValueError, IndexError):
                msg = "Tag '%s' did not resolve to a valid reference" % ref
                csmakelog.error(msg)
                return None
        elif reftype == 'branch':
            try:
                newSHA = remote.refs[ref].commit.hexsha
            except (ValueError, IndexError):
                # Perhaps the branch is a 'head'
                headref = 'heads/%s' % ref
                try:
                    newSHA = remote.refs[headref].commit.hexsha
                except (ValueError, IndexError):
                    msg = "Branch '%s' did not resolve to a valid reference" % ref
                    csmakelog.error(msg)
                    return None
        else:
            try:
                # OK, no, perhaps it's actually a branch
                #  or other kind of reference,
                #     e.g., changes (gerrit)
                newSHA = remote.refs[ref].commit.hexsha
            except (ValueError, IndexError):
                try:
                    # Try treating it as a tag or a SHA
                    newSHA = repo.commit(ref).hexsha
                except (ValueError, IndexError, git.exc.BadName, git.exc.BadObject):
                    # Try treating it as a head reference
                    headref = 'heads/%s' % ref
                    try:
                        newSHA = remote.refs[headref].commit.hexsha
                    except (ValueError, IndexError):
                        # Well rats - it looks like we're looking for
                        # something that just doesn't exist
                        msg = "Reference '%s' did not resolve to a valid reference" % ref
                        csmakelog.error(msg)
                        return None
        return newSHA


    @staticmethod
    # This method assumes you have already done a fetch into the local repo
    def generateSpanLogInfo(csmakelog, localRepo, oldSHA1, newSHA1, findRefs=False):
        """Dives through a local (pre-fetched) repo to collect
           the log history between the two SHAs.
           if 'findRefs' is True the generation will also
               drop any related references it finds into the
               result
               - this can take some time with a well worn repo
           Returns a dictionary that is keyed by a 'type' entry:
               Type: different_tree
               Contains: 'old' : The information about the old SHA
                         'new' : The information about the new SHA
               Type: diverged
               Contains: (same as different_tree, also with):
                         'common' : The information about the common
                                    commit between old and new
               Type: parent
               Contains: 'history' : A list of information about
                                     all of the commits after the
                                     old commit."""
        results = {
            'old' : None,
            'new' : None,
            'common' : None,
            'history' : [] }
        repostruct = {
            'parentsto' : [],
            'oldtocommon' : [],
            'lookup' : {},
            'refsdict' : {} }
        repo = git.Repo(localRepo)
        commit = repo.commit(newSHA1)
        repostruct['parentsto'].append(commit)
        repostruct['lookup'][commit.hexsha] = commit
        found = False
        if findRefs:
            GitProvider._populateRefLookups(repo, repostruct['refsdict'])
        for parent in commit.iter_parents():
            found = oldSHA1 == parent.hexsha
            if found:
                break
            repostruct['parentsto'].append(parent)
            repostruct['lookup'][parent.hexsha] = parent
        if not found:
            csmakelog.info("The new repo SHA diverged from the old SHA")
            oldcommit = repo.commit(oldSHA1)
            found = False
            common = None
            for parent in oldcommit.iter_parents():
                found = parent.hexsha in repostruct['lookup']
                if found:
                    common = parent
                    break
            results['old'] = GitProvider._createLogRecord(oldcommit, repostruct)
            results['new'] = GitProvider._createLogRecord(commit, repostruct)
            if not found:
                csmakelog.info("The new repo SHA is in a different tree from the old SHA")
                results['type'] = 'different_tree'
            else:
                results['type'] = 'diverged'
                results['common'] = GitProvider._createLogRecord(common, repostruct)
        else:
            results['type'] = 'parent'
            results['history'] = []
            for current in repostruct['parentsto']:
                results['history'].append(
                    GitProvider._createLogRecord(current, repostruct))
        return results

    @staticmethod
    def fetchRepository(log, name, localRepo, url, ref, reftype, env={}, secure=True):
        log.debug("Starting fetchRepository(); log should not be 'None' - is log None?: {0}".format(log is None))
        extendedResults = {
            'URL' : url,
            'oldURL' : url  # This will be changed if it's different
        }
        currentSHA = None
        try:
            repo = git.Repo(localRepo)
        except git.exc.NoSuchPathError:
            log.info("No local cache found for %s - creating one", name)
            repo = git.Repo.init(localRepo)

        config = None
        try:
            config = repo.config_writer()
            # Set up the secure https/insecure flag in the git config
            if not secure:
                log.warning("Setting repo request to be ssl insecure")
                config.set_value("http", "sslVerify", "false")
            else:
                log.info("Repo request will be secure access")
                config.set_value("http", "sslVerify", "true")

            # Set up the http.postBuffer to be obscenely large
            # GOZ-1828: http://stackoverflow.com/questions/6842687/the-remote-end-hung-up-unexpectedly-while-git-cloning
            log.info("Setting the http.postBuffer to 1048576000")
            config.set_value("http", "postBuffer", "1048576000")
        finally:
            if config is not None:
                config.write()
                del config

        if repo.is_dirty(True, True, True):
            log.error("GIT REPO REQUESTED *HAS UNCOMMITTED CHANGES")
            log.error("REFUSING TO PROCEED!!!")
            log.error(" - GitProvider would wipe out all local changes")
            log.failed()
            return (False, "ERROR", "Dirty Repository")

        # Get the current head, if one exists...
        try:
            currentSHA, currentRefName = repo.head.commit.name_rev.split()
        except:
            currentRefName = ''
            try:
                currentSHA = repo.head.commit.hexsha
            except:
                currentSHA = ''

        extendedResults['oldSHA1'] = currentSHA
        extendedResults['oldRef'] = currentRefName

        newSHA = None
        with repo.git.custom_environment(**env):
            log.debug("About to call GitProvider.ensureCsmakeRemote() with URL={0}".format(url))
            remote, oldurl = GitProvider.ensureCsmakeRemote(repo, url, log)
            extendedResults['oldURL'] = oldurl

        # Workaround for a bug in PythonGit or the way I'm storing refs
        #  from the refspec
        # TODO: Find or file defect
        # This will clear the problem with the remote asking for
        #  references that don't exist in the remote
        #  and will ensure a fetch occurs
        if oldurl is not None:
            repo.delete_remote(remote)
            log.debug("About to call GitProvider.ensureCsmakeRemote() with URL={0}".format(url))
            remote, _ = GitProvider.ensureCsmakeRemote(repo, url, log)

        newSHA = GitProvider.getSHAFromRef(
            log,
            repo,
            remote,
            ref,
            reftype)

        if newSHA is None:
            log.failed()
            return (False, "ERROR", "Invalid Reference - Reference not found")

        if currentSHA != newSHA:
            repo.head.reference = newSHA

        repo.head.reset(index=True, working_tree=True)
        log.passed()
        # Return the old and new SHA (current is actually old)
        extendedResults['SHA1'] = repo.head.commit.hexsha
        extendedResults['Ref'] = ref
        return ((currentSHA, repo.head.commit.hexsha), "OK", extendedResults)

