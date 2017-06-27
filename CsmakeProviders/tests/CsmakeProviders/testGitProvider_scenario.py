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
import os.path
import os
import unittest
import git
import subprocess
import datetime
from GitProvider import GitProvider

class testGitProvider_scenario(unittest.TestCase):

    def setUp(self):
        self.sourceGit = self.csmake_test.options['source-git']
        self.sourceGit = os.path.abspath(self.sourceGit)
        self.localGit = self.csmake_test.options['local-git']
        self.localGit = os.path.abspath(self.localGit)
        self.clonedGit = self.csmake_test.options['cloned-git']
        self.clonedGit = os.path.abspath(self.clonedGit)
        self.gitShas = self.csmake_test.options['git-diffrefs']
        self.gitShas = os.path.abspath(self.gitShas)
        self.repo = self.csmake_test.options['git-repo']
        self.gitTestRefFile = self.csmake_test.options['git-testref']
        self.gitTestRefFile = os.path.abspath(self.gitTestRefFile)
        self.shaindex = dict(map(lambda x: (x[1], x[0]), enumerate([
          'A',
          'B',
          'C:BranchA',
          'D:BranchA',
          'C',
          'D',
          'E:BranchB',
          'F:BranchB',
          "E':OrphanA",
          "E'A:OrphanA",
          'E',
          'Local A',
          'Local B:TopicA',
          'Local B:TopicB' ] ) ) )
        self.shadict = {}
        self.shalist = None
        with open(self.gitShas) as shafile:
            shalist = shafile.readlines()
        if shalist is None:
            self.assertTrue(False)
            return
        for branch, index in self.shaindex.iteritems():
            self.shadict[branch] = shalist[index].strip()

    def test_basicFetch(self):
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            GitProvider.determineRepoPath(self.localGit, self.repo)[1],
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            "master",
            "branch" )

        repo = git.Repo(os.path.join(
            self.localGit,
            self.repo ) )

        self.assertTrue(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "final.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "myorphan.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "another.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "anotherb.txt" ) ) )

    def test_basicFetchMasterBranchNoQualification(self):
        ref, refType = GitProvider.splitRepoReference('master')

        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            GitProvider.determineRepoPath(self.localGit, self.repo)[1],
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            None)

        repo = git.Repo(os.path.join(
            self.localGit,
            self.repo ) )

        self.assertTrue(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "final.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "myorphan.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "another.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "anotherb.txt" ) ) )

    def test_basicFetchCloned(self):
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.clonedGit, 
                self.repo ),
            "master",
            "branch" )

        self.assertTrue(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'final.txt' ) ) )
        self.assertTrue(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'local.mod' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "myorphan.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "another.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "anotherb.txt" ) ) )

    def test_basicFetchClonedTopicA(self):
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.clonedGit, 
                self.repo ),
            "TopicA",
            "branch" )

        self.assertTrue(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'final.txt' ) ) )
        self.assertTrue(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'localTopicA.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'local.mod' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "myorphan.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "another.txt" ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "anotherb.txt" ) ) )

    def test_basicFetchSourceTagOrphanAEprime(self):
        ref, refType = GitProvider.splitRepoReference("tag:orphan-a-eprime")
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType )


        self.assertTrue(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'myorphan.txt' ) ) )

        self.assertTrue(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'anotherb.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'final.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'localTopicA.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'local.mod' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "another.txt" ) ) )

    def test_basicFetchSourceGerritSimulation(self):
        ref, refType = GitProvider.splitRepoReference("changes/14/99299")
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType )


        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'myorphan.txt' ) ) )

        anotherbPath = os.path.join(
            self.localGit,
            self.repo, 
            'anotherb.txt' )

        self.assertTrue(os.path.exists(anotherbPath))

        with open(anotherbPath) as testfile:
            lines = testfile.readlines()
            self.assertEqual(lines[-1], "Mod\n")

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'final.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'localTopicA.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'local.mod' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "another.txt" ) ) )

    def test_basicFetchSourceSHARef(self):
        myref = None
        with open(self.gitTestRefFile) as testRefFile:
            line = testRefFile.readline()
            myref = line.split()[0].strip()
        self.assertTrue(myref is not None)
        ref, refType = GitProvider.splitRepoReference(myref)
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.clonedGit, 
                self.repo ),
            ref,
            refType )


        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'myorphan.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'anotherb.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'final.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'localTopicA.txt' ) ) )

        self.assertFalse(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            'local.mod' ) ) )

        self.assertTrue(os.path.exists(os.path.join(
            self.localGit,
            self.repo,
            "another.txt" ) ) )

        repo = git.Repo(os.path.join(self.localGit, self.repo))
        self.assertEqual(repo.head.commit.hexsha, ref)

    def test_getSHAFromRefAndEnsureRemote(self):
        ref, refType = GitProvider.splitRepoReference(None)

        localgitPath = os.path.join(
            self.localGit,
            self.repo )
        remotegitPath = "file://%s/%s" % (
            self.sourceGit,
            self.repo )

        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            localgitPath,
            remotegitPath,
            ref,
            refType )

        #We should be able to run through all the tags, shas, branches and other
        #  references in our test repository and resolve them all to shas
        repo = git.Repo(localgitPath)
        fakeurlIn = "http://fakegitrepo.doesnotexist/stuff.git"
        try:
            remote, oldurl = GitProvider.ensureCsmakeRemote(repo, fakeurlIn)
            self.csmake_test.log.error("ensureCsmakeRemote with bad url should fail")
            self.assertFalse(True)
        except git.exc.GitCommandError:
            pass
        remote, fakeurl = GitProvider.ensureCsmakeRemote(repo, remotegitPath)
        self.assertEqual(fakeurlIn, fakeurl)
        repo.delete_remote(remote)
        remote, prevurl = GitProvider.ensureCsmakeRemote(repo, remotegitPath)
        self.assertEqual("", prevurl)
        remote, actualurl = GitProvider.ensureCsmakeRemote(repo, remotegitPath)
        self.assertEqual(actualurl, remotegitPath)

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            "branch-a-c",
            'tag' )
        self.assertEqual(sha, self.shadict['C:BranchA'])

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            "branchA",
            "branch" )
        self.assertEqual(sha, self.shadict['D:BranchA'])

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            'branch-a-d',
            'branch' )
        self.assertEqual(None, sha)

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            'branch-a-d',
            'tag' )
        self.assertEqual(self.shadict['D:BranchA'], sha)

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            'changes/14/99299',
            None )
        self.assertEqual(self.shadict['F:BranchB'], sha)

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            "RANDOMnoise",
            'tag' )
        self.assertEqual(None, sha)

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            "RANDOMnoise",
            'branch' )
        self.assertEqual(None, sha)

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            "RANDOMnoise",
            None )
        self.assertEqual(None, sha)

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            'master',
            'branch' )
        self.assertEqual(self.shadict['E'], sha)

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            'orphan-a-eprime',
            'tag' )
        self.assertEqual(self.shadict["E':OrphanA"], sha)

        sha = GitProvider.getSHAFromRef(
            self.csmake_test.log,
            repo,
            remote,
            self.shadict['E:BranchB'],
            None )
        self.assertEqual(self.shadict['E:BranchB'], sha)


    def test_spanLogSimple(self):
        ref, refType = GitProvider.splitRepoReference(self.shadict['B'])
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType )

        result = GitProvider.generateSpanLogInfo(
            self.csmake_test.log,
            os.path.join(
                self.localGit,
                self.repo ),
            self.shadict['A'],
            self.shadict['B'] )

        print "Parent result: ", result

        self.assertEqual(result['type'], 'parent')
        self.assertEqual(len(result['history']), 1)
        self.assertTrue(result['history'][0]['summary'].startswith('B:'))

        #Verify that the datetime for the records are really utc.
        now = datetime.datetime.utcnow()
        then = result['history'][0]['datetime']
        delta = datetime.timedelta(minutes=10)
        self.csmake_test.log.info("Time delta: %s", str(now-then))
        self.assertTrue(now-then < delta)
        self.assertTrue(then-now < delta)

    def test_spanLogSimpleOnMasterWithRefs(self):
        ref, refType = GitProvider.splitRepoReference('branch:master')
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType )

        result = GitProvider.generateSpanLogInfo(
            self.csmake_test.log,
            os.path.join(
                self.localGit,
                self.repo ),
            self.shadict['A'],
            self.shadict['B'],
            True )

        print "Another parent result: ", result
        print result['history'][0]['refs']
        self.assertEqual(result['type'], 'parent')
        self.assertEqual(len(result['history']), 1)
        self.assertTrue(result['history'][0]['summary'].startswith('B:'))
        self.assertTrue('tags/b' in result['history'][0]['refs'])

    def test_spanLogMasterFullHistory(self):
        ref, refType = GitProvider.splitRepoReference('branch:master')
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType,
            secure=False )

        result = GitProvider.generateSpanLogInfo(
            self.csmake_test.log,
            os.path.join(
                self.localGit,
                self.repo ),
            self.shadict['A'],
            self.shadict['E'] )


        print "Another parent result: ", result
        self.assertEqual(result['type'], 'parent')
        self.assertEqual(len(result['history']), 4)
        self.assertTrue(result['history'][-1]['summary'].startswith('B:'))
        self.assertTrue(result['history'][0]['summary'].startswith('E:'))

    def test_spanLogDifferentTreeWithRefs(self):
        ref, refType = GitProvider.splitRepoReference(None)
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType )

        result = GitProvider.generateSpanLogInfo(
            self.csmake_test.log,
            os.path.join(
                self.localGit,
                self.repo ),
            self.shadict['E'],
            self.shadict["E'A:OrphanA"],
            True )

        print "different_tree result: ", result

        self.assertEqual(result['type'], 'different_tree')
        self.assertEqual(len(result['history']), 0)
        self.assertTrue(result['old']['summary'].startswith('E:'))
        self.assertTrue(result['new']['summary'].startswith("E'A:OrphanA:"))
        self.assertEqual(result['common'], None)
        self.assertTrue('tags/e' in result['old']['refs'])

    def test_spanLogDiverged(self):
        ref, refType = GitProvider.splitRepoReference('branch:master')
        
        GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType )

        result = GitProvider.generateSpanLogInfo(
            self.csmake_test.log,
            os.path.join(
                self.localGit,
                self.repo ),
            self.shadict['E'],
            self.shadict['D:BranchA'] )

        print "diverged result: ", result
        print result['common']
        self.assertEqual(result['type'], 'diverged')
        self.assertEqual(len(result['history']), 0)
        self.assertTrue(result['old']['summary'].startswith('E:'))
        self.assertTrue(result['new']['summary'].startswith("D:BranchA:"))
        self.assertTrue(result['common']['summary'].startswith('B:'))

    def test_badRepoRef(self):
        ref = GitProvider.splitRepoReference("this:is:bad")
        self.assertEqual(ref, (None, None))

    def test_badTagFetch(self):
        ref, refType = GitProvider.splitRepoReference('tag:thisdoesnotexist')

        result = GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType )

        self.assertFalse(result[0])
        self.assertEqual(result[1], "ERROR")

    def test_badBranchFetch(self):
        ref, refType = GitProvider.splitRepoReference('branch:thisdoesnotexist')

        result = GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType )

        self.assertFalse(result[0])
        self.assertEqual(result[1], "ERROR")

    def test_badRefFetch(self):
        ref, refType = GitProvider.splitRepoReference('thisdoesnotexist')

        result = GitProvider.fetchRepository(
            self.csmake_test.log,
            "testing",
            os.path.join(
                self.localGit,
                self.repo ),
            "file://%s/%s" % (
                self.sourceGit, 
                self.repo ),
            ref,
            refType )

        self.assertFalse(result[0])
        self.assertEqual(result[1], "ERROR")
