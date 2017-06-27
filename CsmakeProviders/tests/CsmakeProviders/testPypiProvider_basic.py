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
import PypiProvider
import BaseHTTPServer
import SimpleHTTPServer
import threading
import shutil
import urllib2
import urlparse
import subprocess
import logging
import sys
import time
import TraceDumper
import ssl
import glob
import cgi
import urllib
from ConfigParser import RawConfigParser
from StringIO import StringIO

TraceDumper.trace_start("trace.html")

from packaging import version

#TODO Creating and tearing down a service needs to be deduped...
#     Also need to dedup the md5 test and the packages expected test
#TODO:Test for two versions of package to cache
#TODO:Test oddly named server side package directory like: os-refresh_config

#MUST: Test cert removal == build failure on MGMT


class testPypiProvider_basic(unittest.TestCase):

    def setUp(self):
        self.pipserver = None

    def tearDown(self):
        try:
            PypiProvider.PypiProvider.disposeServiceProvider('tag')
        except:
            pass
        try:
            self._stopTestPypiServer()
        except:
            pass

    def _newVersionResult(self):
        return {
            'package':None,
            'version':None,
            'isWheel':False,
            'build': None,
            'python':None,
            'abi':None,
            'platform':None,
            'ext':None,
            'heuristic':None }

    def _canonicalTestNames(self):
        #Purpose is to test each heuristic is working properly
        #  Huristics are not executed on packages with only
        #  one dash...it is assumed (TD1) to be a version
        #If a version is contraindicated in production, it should
        #  be added to this list.
        return [
            ('mypackage-stuff-1.3.2', {
                'heuristic':'TD4a',
                'version':version.Version('1.3.2'),
                'package':'mypackage-stuff',
                'build':None}, "majorMinorPatchAtEnd"),
            ('mypackage-stuff-1.3.2-2', {
                'heuristic':'TD4b',
                'version':version.Version('1.3.2-2'),
                'package':'mypackage-stuff',
                'build':None}, "majorMinorPatchStuffAtEnd"),
            ("mypackage-stuff-1.3.2-2sdoih09", {
                'heuristic':'TD4b',
                'version':version.Version('1.3.2'),
                'package':'mypackage-stuff',
                'build':'2sdoih09'}, "majorMinorPatchStuffAtEnd"),
            ('mypackage-stuff-4.5', {
                'heuristic':'TD4c',
                'version':version.Version('4.5'),
                'package':'mypackage-stuff',
                'build':None}, "majorMinorAtEnd" ),
            ('mypackage-stuff-4.5-1', {
                'heuristic':'TD4d',
                'version':version.Version('4.5-1'),
                'package':'mypackage-stuff',
                'build':None}, "majorMinorStuffAtEnd" ),
            ('mypackage-stuff-4.5-1gweg29h', {
                'heuristic':'TD4d',
                'version':version.Version('4.5'),
                'package':'mypackage-stuff',
                'build':'1gweg29h' }, "majorMinorStuffAtEnd" ),
            ('mypackage-stuff-4.5.4+325-3252gw', {
                'heuristic':'TD4f',
                'version':version.Version('4.5.4+325-3252gw'),
                'package':'mypackage-stuff',
                'build':None }, "versionHasPlus"),
            ('mypackage-stuff-4.5.4+325', {
                'heuristic':'TD4f',
                'version':version.Version('4.5.4+325'),
                'package':'mypackage-stuff',
                'build':None }, "versionHasPlus"),
            ("mypackage-stuff+morestuff-4.5.1+325-3tts+xx", {
                'heuristic':'TD4f',
                'version':version.Version("4.5.1+325"),
                'package':'mypackage-stuff+morestuff',
                'build':'3tts+xx'}, "versionHasPlus"),
            ("mypackage-stuff-4+morestuff-4.5.1+325-3tts+xx", {
                'heuristic':'TD4f',
                'version':version.Version("4+morestuff"),
                'package':'mypackage-stuff',
                'build':'4.5.1+325-3tts+xx'}, "versionHasPlus"),
            ("mypackage-stuff-v4+morestuff-4.5.1+325--3tts+xx", {
                'heuristic':'TD4f',
                'version':version.Version("4+morestuff"),
                'package':'mypackage-stuff',
                'build':'4.5.1+325--3tts+xx'}, "versionHasPlus"),
            ("mypackage-stuff+morestuff-4.5.post1+325-3-3tts+xx", {
                'heuristic':'TD4f',
                'version':version.Version("4.5.post1+325-3"),
                'package':'mypackage-stuff+morestuff',
                'build':'3tts+xx'}, "versionHasPlus"),
            ("yes!!-!!!4!3-3!4.2.3", {
                'heuristic':'TD4e',
                'version':version.Version("3!4.2.3"),
                'package':'yes!!-!!!4!3',
                'build':None}, "versionHasEpoch"),
            ("yes!!!!!-4!3-3!4.2.3", {
                'heuristic':'TD4e',
                'version':version.Version("4!3"),
                'package':'yes!!!!!',
                'build':'3!4.2.3'}, "versionHasEpoch"),
            ("yes!!!!!-4!3-3!4-3ddd.2.3", {
                'heuristic':'TD4e',
                'version':version.Version("4!3"),
                'package':'yes!!!!!',
                'build':'3!4-3ddd.2.3'}, "versionHasEpoch"),
            ("yes!!!!!-4!3-3+4-3ddd.2.3", {
                'heuristic':'TD4e',
                'version':version.Version("4!3-3+4-3ddd.2.3"),
                'package':'yes!!!!!',
                'build':None}, "versionHasEpoch"),
            ("yes!!!!!-4!3-3+4-3d!dd.2.3", {
                'heuristic':'TD4e',
                'version':version.Version("4!3-3+4"),
                'package':'yes!!!!!',
                'build':"3d!dd.2.3"}, "versionHasEpoch"),
            ("apackage-v3-3tv3", {
                'heuristic':'TD4g',
                'version':version.Version("3"),
                'package':'apackage',
                'build':'3tv3'}, "versionHasDashVNum"),
            ("apackage-v3-3tv3-v4.0.2-1f", {
                'heuristic':'TD4b',
                'version':version.Version("4.0.2"),
                'package':'apackage-v3-3tv3',
                'build':'1f'}, "majorMinorPatchStuffAtEnd"),
            ("apackage-v3-3tv3-v4.0.2-1f-ff", {
                'heuristic':'TD4g',
                'version':version.Version("3"),
                'package':'apackage',
                'build':'3tv3-v4.0.2-1f-ff'}, "versionHasDashVNum"),
            ("apackage-v3+-3tv3-v4.0.2-1f", {
                'heuristic':'TD4b',
                'version':version.Version("4.0.2"),
                'package':'apackage-v3+-3tv3',
                'build':'1f'}, "majorMinorPatchStuffAtEnd"),
            ("apackage-v3+-3tv3-v4.0.2-1f-ff", {
                'heuristic':'TD4g',
                'version':version.Version("4.0.2"),
                'package':'apackage-v3+-3tv3',
                'build':'1f-ff'}, "versionHasDashVNum"),
            ("mypackage-is-v4-super-2.4.1-11-5-3", {
                'heuristic':'TD5',
                'version':version.Version("2.4.1-11"),
                'package':'mypackage-is-v4-super',
                'build':'5-3'}, "findAValidVersion"),
            ("mypackage-is-v(42.4.1)-11-5-3", {
                'heuristic':'TD5',
                'version':version.Version("11-5"),
                'package':'mypackage-is-v(42.4.1)',
                'build':'3'}, "findAValidVersion"),
            ("mypackage-is-v(42.4.1)-11-fff-3", {
                'heuristic':'TD5',
                'version':version.Version("3"),
                'package':'mypackage-is-v(42.4.1)-11-fff',
                'build':None}, "findAValidVersion"),
            ("mypackage-is-v(42.4.1)-11-fff-f3", {
                'heuristic':'6a',
                'version':version.Version("42.4.1"),
                'package':'mypackage-is',
                'build':'11-fff-f3'}, "findLegacyParenedVersion"),
            ("mypackage-is-v(42.4.1)", {
                'heuristic':'6a',
                'version':version.Version("42.4.1"),
                'package':'mypackage-is',
                'build':None}, "findLegacyParenedVersion"),
            ("mypackage-is-v(42.4.1Thisisdog)-3iohagi", {
                'heuristic':'6a',
                'version':version.LegacyVersion("42.4.1Thisisdog"),
                'package':'mypackage-is',
                'build':"3iohagi"}, "findLegacyParenedVersion"),
            ("mypackage-is-v(42.4.1-Thisisdog)-3iohagi", {
                'heuristic':'6a',
                'version':version.LegacyVersion("42.4.1-Thisisdog"),
                'package':'mypackage-is',
                'build':"3iohagi"}, "findLegacyParenedVersion"),
            ("mypackage-is-v(42.4.1-1)-3iohagi", {
                'heuristic':'6a',
                'version':version.Version("42.4.1-1"),
                'package':'mypackage-is',
                'build':"3iohagi"}, "findLegacyParenedVersion"),
            ("mypackage-is-v(42.4.1Thisisdog)3iohagi", {
                'heuristic':'6b',
                'version':version.LegacyVersion("v(42.4.1Thisisdog)3iohagi"),
                'package':'mypackage-is',
                'build':None}, "findDashVanything"),
           ("mypackage-is-v(42.4.1Thisisdog)3io-hagi", {
                'heuristic':'6b',
                'version':version.LegacyVersion("v(42.4.1Thisisdog)3io-hagi"),
                'package':'mypackage-is',
                'build':None}, "findDashVanything"),
           ("mypackage-is-v(42.4.1Thisisdog)3i-33o-hagi", {
                'heuristic':'6b',
                'version':version.LegacyVersion("v(42.4.1Thisisdog)3i"),
                'package':'mypackage-is',
                'build':"33o-hagi"}, "findDashVanything"),
           ("mypackage-is-v(42.4.1Thisisdog)3i-33o-3hagi", {
                'heuristic':'6b',
                'version':version.LegacyVersion("v(42.4.1Thisisdog)3i-33o"),
                'package':'mypackage-is',
                'build':"3hagi"}, "findDashVanything"),
           ("mypackage-is-42.4.1Thisisdog3i-33o-hagi", {
                'heuristic':'6d',
                'version':version.LegacyVersion("hagi"),
                'package':'mypackage-is-42.4.1Thisisdog3i-33o',
                'build':None}, "assumeTheLastClauseIsaVersion"),
           ("mypackage-is-42.4.1Thisisdog3i-33o-3hagi", {
                'heuristic':'6c',
                'version':version.LegacyVersion("33o"),
                'package':'mypackage-is-42.4.1Thisisdog3i',
                'build':"3hagi"}, "assumeTheLastClauseIsaVersion"),
           ("functools32-3.2.3_1", {
                'heuristic':'6d',
                'version':version.LegacyVersion("3.2.3_1"),
                'package':'functools32',
                'build':None}, "assumeTheLastClauseIsaVersion"),
           ("pylibmc-1.1.1jarn1", {
                'heuristic':'6d',
                'version':version.LegacyVersion("1.1.1jarn1"),
                'package':'pylibmc',
                'build':None}, "assumeTheLastClauseIsaVersion")]

    def _basicCanonicalTestNames(self):
        return [
           ("oslo.i18n-2.3.0", {
                'heuristic':'1',
                'version':version.Version('2.3.0'),
                'package':'oslo.i18n',
                'build':None}),
            ('enum34-1.1.6', {
                'heuristic':'1',
                'version':version.Version('1.1.6'),
                'package':'enum34',
                'build':None}),
            ('mypackage-1.3.2', {
                'heuristic':'1',
                'version':version.Version('1.3.2'),
                'package':'mypackage',
                'build':None})]

    #This is not a comprehensive list, but a sampling of issues from the
    # main pypi server.
    PROBLEM_FILES=[
        "downloading.php?group_id=262159&amp;filename=pygts-0.1.3.tar.gz",
        "PyCifRW-3.6.1-py2.7-linux-i686.tar.gz",
        "0.3-pycante.tar.gz",
        "1.0-pycante.tar.gz",
        "index.php?module=Wiki&amp;action=attachment&amp;type=tool&amp;page=Pcapy&amp;file=pcapy-0.10.3.tar.gz",
        "fetch.php?media=projects:ostri-0.1.0.tgz",
        "v0.1.6-p6.tar.gz",
        "pyRXP-1.16-daily-unix.tar.gz",
        "pyreg-0.2.win32.zip",
        "fop-1.1-bin.tar.gz",
        "py-modularapp.tbz",
        "detail?name=pyminuit2-1.1.0.tar.gz",
        "pylsm-0.1-r34.orig.tar.gz",
        "mcvine-1.0beta-src.tgz",
        "LinkExchange-0.1dev-r25.tar.gz",
        "4-24-2014.zip",
        "jest-beta-3.tar.gz",
        "hurry.workflow-0.9.1-getpaid.tar.gz",
        "F2PY-2-latest.tar.gz",
        "css-scripts.tar.gz",
        "0.2.1-caipyrinha.tar.gz",
        "bzr-fastimport-0.11.0.final.0.tar.gz",
        "bzero-0.18-py2.3.tar.gz",
        "anntools-0.5.1-src.zip",
        "phprpc_3.0.1_py25.zip",
        "ulipad.3.7.zip",
        "RLtoolkit1.0b6.tgz",
        "splittar_0.1.tar.gz",
        "wmi10.zip",
        "OpenFlowEditor_0_4.tgz",
        "pygtkquery_0.2.tar.gz",
        "k8055dll_rev3_0_2.zip",
        "PyCon_UK_2007_PyQt_and_Qt_Designer_r2.zip",
        "oslo.i18n-2.4.0-py2.py3-none-any.whl",
        "oslo.i18n-2.4.0.tar.gz"
    ]
    #quintagroup packages also a huge problem
    #pyk8055-velleman   seriously?  k8055dll_rev3_0_2.zip -- good luck...
    #several packages do not publish a name with their packages...

    def _setupForStandardChrootedService(self, startService=True, startTestPypi=False):
        #This dedups the test setup
        #As tests are modified, replace the start up of the test
        #With this code

        #Returns {
        #   'fakeuser': A fake user that is added to the chroot
        #   'facadeport': The port that the facade will operate on
        #   'pypiport': The port that the test pypi server will operate on
        #   'testspath': The path to the tests data
        #   'mirrors': The path to the test pypi mirror directories
        #   'chroot': The path that the fake chroot is set up on
        #   'cache': The path to the facade's cache
        #   'chrootcertpath': The path to the certpath in the chroot
        #   'bundle': The ca bundle path in the chroot
        #   'certpath': The original cert path
        #   'certfrom': The path to where the original cert bundle lices
        #   'controller': A reference to the controller, None if not started
        #   'service' : A reference to the actual service object
        # }

        result = {}

        fakeuser = "xyzzy151235"
        result['fakeuser'] = fakeuser

        pypiport = "29988"
        if not startTestPypi:
            pypiport = None
        result['pypiport'] = pypiport

        facadeport = "25891"
        result['facadeport'] = facadeport

        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        result['testspath'] = testspath

        path = os.path.join(
            testspath,
            'pipmirrors' )
        result['mirrors'] = path

        chroot = os.path.join(
            testspath,
            'fakechroot')
        result['chroot'] = chroot

        cache = os.path.join(
            testspath,
            'cache' )
        result['cache'] = cache

        chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
        result['chrootcertpath'] = chrootcertpath

        bundle = os.path.join(
            chrootcertpath,
            'ca-certificates.crt')
        result['bundle'] = bundle

        #Create the root user path
        try:
            os.makedirs(os.path.join(chroot,'root'))
        except Exception as e:
            self.csmake_test.log.info("Could not create user root in chroot: %s", str(e))
            self.csmake_test.log.info("   Assuming this is ok, proceeding")

        #Create the fake user path
        try:
            os.makedirs(os.path.join(chroot,'home',fakeuser))
        except Exception as e:
            self.csmake_test.log.info("Could not create user %s in chroot: %s", fakeuser, str(e))
            self.csmake_test.log.info("   Assuming this is ok, proceeding")

        #Create the fake cert home
        certpath="/etc/ssl/certs/ca-certificates.crt"
        result['certpath'] = certpath

        certfrom=None

        try:
            os.makedirs(chrootcertpath)
        except Exception as e:
            self.csmake_test.log.info("Could not create certpath in chroot: %s", str(e))
            self.csmake_test.log.info("   Assuming this is ok, proceeding")

        testcert=os.path.join(testspath, 'ca-certificates.crt')
        result['testcert'] = testcert

        shutil.copy(testcert,chrootcertpath)
        certfrom=testcert
        result['certfrom'] = certfrom

        self.csmake_test.log.info("Certs copied to: %s   from: %s", chrootcertpath, testcert)
        if not os.path.exists(os.path.join(chrootcertpath, "ca-certificates.crt")):
            self.csmake_test.log.info("Certs do not exist at: %s", os.path.join(chrootcertpath, "cs-certificates.crt"))

        #Ensure the root we're going to use is valid
        try:
            ssl.create_default_context(cafile=bundle)
        except:
            self.csmake_test.log.error(
                "The bundle with the certificate '%s' is invalid",
                bundle )
            self.assertTrue(False)

        result['controller'] = None
        result['service'] = None
        try:
            if startTestPypi:
                self._startTestPypiServer(path, pypiport)
            if startService:
                service = PypiProvider.PypiProvider.createServiceProvider(
                    "tag",
                    self.csmake_test,
                    **{'default-context':'mytest',
                       'interfaces':'localhost',
                       'port':facadeport,
                       'chroot':chroot } )
                service.startService()
                controller = service.getController()
                result['controller'] = controller
                result['service'] = service
        except Exception as e:
            self.csmake_test.log.exception("Starting the testing failed")
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")
            raise
            #raise e
        return result

    def _cleanupStandardChrootedService(self, setupResult):
        #This dedups the test teardown
        try:
            PypiProvider.PypiProvider.disposeServiceProvider('tag')
        except:
            self.csmake_test.log.exception("endService failed")
        try:
            self._stopTestPypiServer()
        except:
            self.csmake_test.log.exception("stopTestPypiServer failed")
        chroot = setupResult['chroot']
        self.csmake_test.log.info("Removing %s", chroot)
        result = subprocess.call(
            ['sudo', 'rm', '-r', chroot],
            stdout=self.csmake_test.log.out(),
            stderr=self.csmake_test.log.err())
        self.assertFalse(os.path.exists(chroot))
        self.assertEqual(result, 0)


    #Test the functional correctness of version/package name parsing
    def test_basicVersionMatchSanity(self):
        canon = self._canonicalTestNames()
        for name, expected, method in canon:
            print "Testing: ", name
            result = self._newVersionResult()
            dashes = name.split('-')
            heuristics = PypiProvider.PypiContext._SplitHeuristics(
                result,
                dashes,
                name,
                {},
                self.csmake_test.log )
            self.assertTrue(getattr(heuristics,method)())
            for key, value in expected.iteritems():
                self.assertEqual(result[key], value)

    def test_filenameSplitCanon(self):
        #Cheater way to create a context...
        testcontext = PypiProvider.PypiContext(
            {'name':'testctxt'},self.csmake_test)
        canon = self._canonicalTestNames()
        for name, expected, method in canon:
            for ext in PypiProvider.PypiContext.SUPPORTED_EXTENSIONS:
                if ext in PypiProvider.PypiContext.WHEEL_EXTENSIONS:
                    ext = '-all-none-something' + ext
                filename = name + ext
                print "Testing: ", filename
                result = testcontext._splitPypiName(filename, {}, None)
                for key, value in expected.iteritems():
                    self.assertEqual(result[key], value)
                print "     with package name"
                result = testcontext._splitPypiName(filename, {}, expected['package'])
                for key, value in expected.iteritems():
                    if key == 'heuristic':
                        #It's possible that supplying the package name
                        #Just took this from a hard to an easy problem
                        #  However TDs past 5 are not so lucky.
                        #  TDs 2-5 use TD for their heuristic...
                        #     yes the distinction is lame...
                        if '-' not in \
                            name.split(expected['package'])[1][1:] \
                            and value.startswith('TD'):
                            value = '1'
                    if key == 'package':
                        value = testcontext._normalizePackageName(value)
                    self.assertEqual(result[key], value)

        canon = self._basicCanonicalTestNames()
        for name, expected in canon:
            for ext in PypiProvider.PypiContext.SUPPORTED_EXTENSIONS:
                if ext in PypiProvider.PypiContext.WHEEL_EXTENSIONS:
                    ext = '-all-none-something' + ext
                filename = name + ext
                print "Testing: ", filename
                result = testcontext._splitPypiName(filename, {}, None)
                for key, value in expected.iteritems():
                    self.assertEqual(result[key], value)
                result = testcontext._splitPypiName(filename, {}, expected['package'])

    def _startTestPypiServer(self, path, port, waitresponse=0, suffix=None):
        if self.pipserver is not None:
            return True

        class VirtualPathHTTPRequestHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
            def __init__(innerself, request, client_address, server):
                self.csmake_test.log.devdebug("Created vpath http request")
                #Simulate a slow network
                if waitresponse != 0:
                    self.csmake_test.log.info(
                        "Sleeping for %ds before responding",
                        waitresponse )
                    time.sleep(waitresponse)
                SimpleHTTPServer.SimpleHTTPRequestHandler.__init__(
                    innerself,
                    request,
                    client_address,
                    server )

            def translate_path(innerself, virtpath):
                #translate_path by default will tack on cwd...cute...
                self.csmake_test.log.devdebug("Path requested: %s", virtpath)
                logging.warning("Path requested: %s", virtpath)
                if virtpath.startswith('/'):
                    virtpath = virtpath[1:]
                fullpath = os.path.join(path, virtpath)
                fullpath = os.path.relpath(fullpath, os.getcwd())
                self.csmake_test.log.devdebug("Path translated: %s", fullpath)
                logging.warning("Path translated: %s", fullpath)
                result = SimpleHTTPServer.SimpleHTTPRequestHandler.translate_path(
                    innerself,
                    fullpath )
                if os.path.isdir(result):
                    if result[-1] != '/':
                        result += '/'
                    if innerself.path[-1] != '/':
                        innerself.path += '/'
                self.csmake_test.log.devdebug("Path massaged: %s", result)
                self.csmake_test.log.devdebug("innerself path: %s", innerself.path)
                logging.warning("Path massaged: %s", result)
                return result

            def list_directory(self, path):
                if suffix is None:
                    return SimpleHTTPServer.SimpleHTTPRequestHandler.list_directory(self, path)
                try:
                    list = os.listdir(path)
                except os.error:
                    self.send_error(404, "No permission to list directory")
                    return None
                list.sort(key=lambda a: a.lower())
                f = StringIO()
                displaypath = cgi.escape(urllib.unquote(self.path))
                f.write('<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">')
                f.write("<html>\n<title>Directory listing for %s</title>\n" % displaypath)
                f.write("<body>\n<h2>Directory listing for %s</h2>\n" % displaypath)
                f.write("<hr>\n<ul>\n")
                for name in list:
                    fullname = os.path.join(path, name)
                    displayname = linkname = name
                    # Append / for directories or @ for symbolic links
                    if os.path.isdir(fullname):
                        displayname = name + "/"
                        linkname = name + "/"
                    if os.path.islink(fullname):
                        displayname = name + "@"
                        # Note: a link to a directory displays with @ and links with /
                    f.write('<li><a href="%s%s">%s</a>\n'
                            % (urllib.quote(linkname), suffix, cgi.escape(displayname)))
                f.write("</ul>\n<hr>\n</body>\n</html>\n")
                length = f.tell()
                f.seek(0)
                self.send_response(200)
                encoding = sys.getfilesystemencoding()
                self.send_header("Content-type", "text/html; charset=%s" % encoding)
                self.send_header("Content-Length", str(length))
                self.end_headers()
                return f

        class PipServer(threading.Thread):
            def __init__(innerself):
                threading.Thread.__init__(innerself)
                innerself.server = None

            def run(innerself):
                innerself.server = BaseHTTPServer.HTTPServer(
                    ('localhost', port),
                    VirtualPathHTTPRequestHandler)
                innerself.server.serve_forever()

            def shutdown(innerself):
                if innerself.server is not None:
                    innerself.server.shutdown()
                innerself.join()

        self.pipserver = PipServer()
        self.pipserver.start()
        time.sleep(0.1)
        return True

    def _stopTestPypiServer(self):
        if self.pipserver is not None:
            self.pipserver.shutdown()
            self.pipserver = None
        return True

    def _fishLinksIntoList(self, page):
        self.csmake_test.log.debug('Fishing links from: %s', page)
        parts = page.split('<a ')[1:]
        files = []
        for part in parts:
            nametext=part[part.index('>')+1:part.index('<')]
            nearlylink = part.split('href=')[1][1:].split('>')[0]
            link = nearlylink.split('"')
            if len(link) == 1:
                link = nearlylink.split("'")
            link = link[0]
            files.append((link,nametext))
        self.csmake_test.log.debug("Links are: %s", str(files))
        return files


    def test_serverbasics(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            self._startTestPypiServer(path, pypiport)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{'default-context':'mytest',
                 'interfaces':'localhost',
                 'port':facadeport,
                 'constraining-indicies':
                     'http://localhost:%d/pypi-99:99:01' % pypiport,
                 'indicies':'http://localhost:%d/pypi-99:99:02' % pypiport,
                 'cache':cache,
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            #Try getting the index for pip
            #TODO: Need to add cert??
            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest'),
                cafile=chrootcert)
            data = indexresult.read()
            packages = self._fishLinksIntoList(data)
            expectedPackages = ['azure', 'leon', 'pip', 'ldap3', 'mysql-python', 'oslo-config']
            unexpectedFound = False
            for link,package in packages:
                try:
                    expectedPackages.remove(package)
                except:
                    print "Package '%s' unexpected" % package
                    unexpectedFound = True
            self.assertFalse(unexpectedFound)
            if len(expectedPackages) != 0:
                print "Packages not retrieved: ", expectedPackages

            self.assertEqual(len(expectedPackages), 0)
            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/pip'),
                cafile=chrootcert)
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            expectedFiles = [
                'pip-1.5.4-py2.py3-none-any.whl',
                'pip-6.1.1.tar.gz',
                'pip-6.1.1-py2.py3-none-any.whl']

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            fileresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/pip/pip-6.1.1-py2.py3-none-any.whl'),
                cafile=chrootcert)
            md5sum = self.csmake_test._fileMD5(fileresult)
            fileresult.close()

            with open(os.path.join(path,"pypi-99:99:01/pip/pip-6.1.1-py2.py3-none-any.whl")) as testfile:
                testmd5sum = self.csmake_test._fileMD5(testfile)
            self.assertEqual(md5sum, testmd5sum)

            cachedpip = os.path.join(cache, "pip/pip-6.1.1-py2.py3-none-any.whl")

            with open(cachedpip) as cachefile:
                cachemd5sum = self.csmake_test._fileMD5(cachefile)
            self.assertEqual(testmd5sum, cachemd5sum)

            with open(cachedpip, 'w') as cachefile:
                cachefile.write("My dog has fleas")

            fileresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/pip/pip-6.1.1-py2.py3-none-any.whl'),
                cafile=chrootcert)
            md5sum = self.csmake_test._fileMD5(fileresult)
            fileresult.close()

            with open(cachedpip) as cachefile:
                cachemd5sum = self.csmake_test._fileMD5(cachefile)

            self.assertEqual(md5sum, cachemd5sum)

            controller.registerContext('rad', {
                'reset':'pip',
                'constraints':'pip>=7'})
            controller.pushCurrentContext('rad')
            self.assertEqual(controller.getCurrentContext(), 'rad')

            parser = RawConfigParser()
            parser.read([os.path.join(chroot,'root/.pydistutils.cfg')])
            self.assertTrue(parser.has_section('easy_install'))
            self.assertTrue(parser.has_option('easy_install','index-url'))
            self.assertEqual(parser.get('easy_install','index-url'),"https://localhost:%s/rad"%facadeport)

            parser = RawConfigParser()
            parser.read([os.path.join(chroot,'root/.config/pip/pip.conf')])
            self.assertTrue(parser.has_section('global'))
            self.assertTrue(parser.has_option('global', 'index-url'))
            self.assertEqual(parser.get('global','index-url'),"https://localhost:%s/rad"%facadeport)
            self.assertTrue(parser.has_option('global', 'cert'))
            self.assertEqual(parser.get('global','cert'),certpath)

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'rad/pip'),
                cafile=chrootcert)
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            expectedFiles = [
                'pip-7.0.3-py2.py3-none-any.whl',
                'pip-7.0.3.tar.gz',
                'pip-7.0.2.tar.gz']

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/pip'),
                cafile=chrootcert)
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            expectedFiles = [
                'pip-1.5.4-py2.py3-none-any.whl',
                'pip-6.1.1.tar.gz',
                'pip-6.1.1-py2.py3-none-any.whl']

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            controller.popCurrentContext('rad')

            parser = RawConfigParser()
            parser.read([os.path.join(chroot,'root/.pydistutils.cfg')])
            self.assertTrue(parser.has_section('easy_install'))
            self.assertTrue(parser.has_option('easy_install','index-url'))
            self.assertEqual(parser.get('easy_install','index-url'),"https://localhost:%s/mytest"%facadeport)

            parser = RawConfigParser()
            parser.read([os.path.join(chroot,'root/.config/pip/pip.conf')])
            self.assertTrue(parser.has_section('global'))
            self.assertTrue(parser.has_option('global', 'index-url'))
            self.assertEqual(parser.get('global','index-url'),"https://localhost:%s/mytest"%facadeport)
            self.assertTrue(parser.has_option('global', 'cert'))
            self.assertEqual(parser.get('global','cert'),certpath)

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")
            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            result = subprocess.call(['sudo', 'rm', '-r', cache], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))

    def test_escaped_plus_file(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            self._startTestPypiServer(path, pypiport)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{'default-context':'mytest',
                 'interfaces':'localhost',
                 'port':facadeport,
                 'indicies':
                     'http://localhost:%d/pypi-99:99:03' % pypiport,
                 'cache':cache,
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            controller.registerContext('limited', {
                'previous':'mytest',
                'reset':'python-monascaclient',
                'constraints':'python-monascaclient~=1.0.21'})

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/python_monascaclient'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            expectedfiles = [
                'python-monascaclient-1.0.18.tar.gz',
                'python-monascaclient-1.0.19.tar.gz',
                'python_monascaclient-1.0.18-py2.py3-none-any.whl',
                urllib2.quote('python_monascaclient-1.0.21+HPCS9.0-py2.py3-none-any.whl'),
                'python_monascaclient-1.0.21-py2.py3-none-any.whl',
                'python_monascaclient-2015.1-py2.py3-none-any.whl' ]

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedfiles.remove(link)
                except:
                    print "File '%s' unexpected" % link
                    unexpectedFound = True

            if len(expectedfiles) != 0:
                print "Files not retrieved: ", expectedfiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedfiles),0)

            fileresult = urllib2.urlopen(
                urlparse.urljoin(
                    facadeurl,
                    'mytest/python_monascaclient/python_monascaclient-1.0.21%2BHPCS9.0-py2.py3-none-any.whl'),
                cafile=chrootcert )
            md5sum = self.csmake_test._fileMD5(fileresult)
            fileresult.close()

            with open(os.path.join(path,"pypi-99:99:03/python_monascaclient/python_monascaclient-1.0.21+HPCS9.0-py2.py3-none-any.whl")) as testfile:
                testmd5sum = self.csmake_test._fileMD5(testfile)
            self.assertEqual(md5sum, testmd5sum)

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'limited/python_monascaclient'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            expectedfiles = [
                urllib2.quote('python_monascaclient-1.0.21+HPCS9.0-py2.py3-none-any.whl'),
                'python_monascaclient-1.0.21-py2.py3-none-any.whl' ]

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedfiles.remove(link)
                except:
                    print "File '%s' unexpected" % link
                    unexpectedFound = True

            if len(expectedfiles) != 0:
                print "Files not retrieved: ", expectedfiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedfiles),0)

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")
            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            result = subprocess.call(['sudo', 'rm', '-r', cache], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result,0)

    def test_populateServerWithCache(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'savedcache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            self._startTestPypiServer(path, pypiport)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{'default-context':'mytest',
                 'interfaces':'localhost',
                 'port':facadeport,
                 'cache':cache,
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest'),
                cafile=chrootcert )
            data = indexresult.read()
            packages = self._fishLinksIntoList(data)
            expectedPackages = ['azure', 'pip']
            unexpectedFound = False
            for link, package in packages:
                try:
                    expectedPackages.remove(package)
                except:
                    print "Package '%s' unexpected" % package
                    unexpectedFound = True
            self.assertFalse(unexpectedFound)
            if len(expectedPackages) != 0:
                print "Packages not retrieved: ", expectedPackages

            self.assertEqual(len(expectedPackages), 0)
            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/pip'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            expectedFiles = [
                'pip-6.1.1-py2.py3-none-any.whl']

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            fileresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/pip/pip-6.1.1-py2.py3-none-any.whl'),
                cafile=chrootcert )
            md5sum = self.csmake_test._fileMD5(fileresult)
            fileresult.close()

            cachedpip = os.path.join(cache, "pip/pip-6.1.1-py2.py3-none-any.whl")
            with open(cachedpip) as cachefile:
                cachemd5sum = self.csmake_test._fileMD5(cachefile)

            self.assertEqual(md5sum, cachemd5sum)

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")

            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result, 0)

    #TODO:Check to ensure we're pulling our self signed cert out and all is
    #     still well with the ca bundle - including new certs added to the
    #     end of the bundle
    def test_startServerFromScratch(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            self._startTestPypiServer(path, pypiport)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{'default-context':'mytest',
                 'interfaces':'localhost',
                 'indicies':'http://localhost:%d/pypi-99:99:01' % pypiport,
                 'constraints':'pip==1.5.4',
                 'port':facadeport,
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest'),
                cafile=chrootcert )
            data = indexresult.read()
            packages = self._fishLinksIntoList(data)
            expectedPackages = ['azure', 'pip', 'leon', 'mysql-python']
            unexpectedFound = False
            for link, package in packages:
                try:
                    expectedPackages.remove(package)
                except:
                    print "Package '%s' unexpected" % package
                    unexpectedFound = True
            self.assertFalse(unexpectedFound)
            if len(expectedPackages) != 0:
                print "Packages not retrieved: ", expectedPackages

            self.assertEqual(len(expectedPackages), 0)

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/leon'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            #TODO: Do we want to serve eggs?
            expectedFiles = [
                'leon-0.4.1.tar.gz' ]

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/pip'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            expectedFiles = [
                'pip-1.5.4-py2.py3-none-any.whl' ]

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            #Overriding context
            controller.registerContext('rad', {
                'indicies':'http://localhost:%d/pypi-99:99:02' % pypiport,
                'constraints':'pip>=7'})
            controller.pushCurrentContext('rad')
            self.assertEqual(controller.getCurrentContext(), 'rad')

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'rad/pip'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            expectedFiles = [
                'pip-7.0.3-py2.py3-none-any.whl',
                'pip-7.0.3.tar.gz',
                'pip-7.0.2.tar.gz']

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'rad/azure'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            self.assertEqual(len(files),0)

            #Overriding context
            controller.registerContext('child', {
                'previous':'mytest',
                'indicies':'http://localhost:%d/pypi-99:99:02' % pypiport,
                'constraints':'pip>=7'})
            controller.pushCurrentContext('child')
            self.assertEqual(controller.getCurrentContext(), 'child')

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'child/pip/'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            expectedFiles = [
                'pip-7.0.3-py2.py3-none-any.whl',
                'pip-7.0.3.tar.gz',
                'pip-7.0.2.tar.gz',
                'pip-1.5.4-py2.py3-none-any.whl' ]

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'child/azure'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            expectedFiles = [
                'azure-0.10.0.zip',
                'azure-0.1.zip',
                'azure-0.5.2.zip',
                'azure-0.5.zip' ]

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            controller.pushCurrentContext('rad')
            self.assertEqual(controller.getCurrentContext(), 'rad')

            self.assertTrue(controller.popCurrentContext('rad'))
            self.assertEqual(controller.getCurrentContext(), 'mytest')

            self.assertFalse(controller.popCurrentContext('mytest'))
            self.assertEqual(controller.getCurrentContext(), 'mytest')

            self.assertTrue(controller.pushCurrentContext('child'))
            self.assertEqual(controller.getCurrentContext(), 'child')

            self.assertTrue(controller.pushCurrentContext('rad'))
            self.assertEqual(controller.getCurrentContext(), 'rad')

            self.assertTrue(controller.popCurrentContext('rad'))
            self.assertEqual(controller.getCurrentContext(), 'child')

            self.assertTrue(controller.pushCurrentContext('rad'))
            self.assertFalse(controller.popCurrentContext('xyzzy'))
            self.assertEqual(controller.getCurrentContext(), 'mytest')

            self.assertTrue(controller.pushCurrentContext('rad'))
            self.assertTrue(controller.pushCurrentContext('child'))

            self.assertTrue(controller.pushCurrentContext('mytest'))
            self.assertEqual(controller.getCurrentContext(), 'mytest')

            self.assertFalse(controller.popCurrentContext(controller.getCurrentContext()))
            self.assertEqual(controller.getCurrentContext(), 'mytest')

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")

            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result, 0)

    def test_pullFilesBeforeIndex(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            self._startTestPypiServer(path, pypiport)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{'default-context':'mytest',
                 'interfaces':'localhost',
                 'indicies':'http://localhost:%d/pypi-99:99:01' % pypiport,
                 'port':facadeport,
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            #Check that we can request a file out of the chute.
            fileresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/azure/azure-0.10.0.zip'),
                cafile=chrootcert )

            md5sum = self.csmake_test._fileMD5(fileresult)
            fileresult.close()
            with open(os.path.join(
                   path,
                   'pypi-99:99:01/azure/azure-0.10.0.zip')) as pypifile:
                pypimd5sum = self.csmake_test._fileMD5(pypifile)
            self.assertEqual(md5sum, pypimd5sum)

            #Now, check that we can request a file where the index
            # has been pulled from one repository and the file's not there
            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/pip'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are only the versions from the 01 mirror
            #There could be other files (the 6.1.1 tar.gz is in the pip
            #  02 mirror for example.
            expectedFiles = [
                'pip-1.5.4-py2.py3-none-any.whl',
                'pip-6.1.1-py2.py3-none-any.whl']

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            controller.registerContext('newerpip', {
                'indicies':'http://localhost:%d/pypi-99:99:02' % pypiport } )
            fileresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'newerpip/pip/pip-7.0.3.tar.gz'),
                cafile=chrootcert )

            md5sum = self.csmake_test._fileMD5(fileresult)
            fileresult.close()
            with open(os.path.join(
                   path,
                   'pypi-99:99:02/pip/pip-7.0.3.tar.gz')) as pypifile:
                pypimd5sum = self.csmake_test._fileMD5(pypifile)
            self.assertEqual(md5sum, pypimd5sum)

            #Now add a context where pip 7 is boxed out.
            controller.registerContext('olderpip', {
                'previous':'newerpip',
                'indicies':'http://localhost:%d/pypi-99:99:01' % pypiport,
                'constraints':'pip<7'
                } )

            #Now, check that we can request a file where the index
            # has been pulled from one repository and the file's not there
            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'olderpip/pip'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify files are the versions from the 01 mirror
            #And 02 mirror. They should be constrained to <7
            expectedFiles = [
                'pip-1.5.4-py2.py3-none-any.whl',
                'pip-6.1.1-py2.py3-none-any.whl',
                'pip-6.1.1.tar.gz']

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedFiles.remove(filename)
                except:
                    print "File '%s' unexpected" % filename
                    unexpectedFound = True

            if len(expectedFiles) != 0:
                print "Files not retrieved: ", expectedFiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedFiles),0)

            #TODO:  Interestingly, because of the way this test is put together
            #       pip 7 *is* in the file lookup table.  So, if you bypass
            #       the index for the package and just go straight for the
            #       file, it will not be filtered out....
            #       The fix isn't entirely straightforward, nor urgent
            #       as pip won't try to download a version it isn't told
            #       exists.
            """
            try:
                fileresult = urllib2.urlopen(
                    urlparse.urljoin(facadeurl, 'olderpip/pip/pip-7.0.3.tar.gz'),
                    cafile=chrootcert )
                self.csmake_test.log.error("pip 7 should not be accessible")
                self.csmake_test.log.debug("File content")
                buf = fileresult.read(100)
                buf = buf[:min(100,len(buf))]
                self.csmake_test.log.debug(buf)
                self.assertTrue(False)
            except urllib2.HTTPError:
                pass
            except:
                self.csmake_test.log.exception("We didn't get an HTTPError...")
                self.assertTrue(False)
            """

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")

            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result, 0)

    def test_clientInterrupt(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            #Simulate a slower network
            self._startTestPypiServer(path, pypiport, 7)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{'default-context':'mytest',
                 'interfaces':'localhost',
                 'indicies':'http://localhost:%d/pypi-99:99:02' % pypiport,
                 'port':facadeport,
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            #Simulate an impatient pip
            targetfile = urlparse.urljoin(
                facadeurl,
                'mytest/pip/pip-7.0.3.tar.gz')
            for x in range(1,3):
                try:
                    fileresult = urllib2.urlopen(
                        targetfile,
                        timeout=1,
                        cafile=chrootcert )
                    self.csmake_test.log.error(
                        "Pull from facade did not time out")
                    self.assertTrue(False)
                except urllib2.URLError as e:
                    pass
                except ssl.SSLError as e:
                    pass
                except:
                    self.csmake_test.log.exception("Unexpected exception")
                    self.assertTrue(False)
            fileresult = urllib2.urlopen(
                targetfile,
                cafile=chrootcert )

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")

            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result, 0)

    def test_multipleConstrainingIndicies(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            self._startTestPypiServer(path, pypiport)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{'default-context':'mytest',
                 'interfaces':'localhost',
                 'port':facadeport,
                 'constraining-indicies':
                     'http://localhost:%d/pypi-99:99:01\nhttp://localhost:%d/pypi-99:99:02' % (pypiport,pypiport),
                 'cache':cache,
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            #Try getting the index for pip
            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/pip'),
                cafile=chrootcert )
            data = indexresult.read()
            packages = self._fishLinksIntoList(data)
            expectedPackages = [
                'pip-1.5.4-py2.py3-none-any.whl',
                'pip-6.1.1-py2.py3-none-any.whl',
                'pip-6.1.1.tar.gz',
                'pip-7.0.2.tar.gz',
                'pip-7.0.3-py2.py3-none-any.whl',
                'pip-7.0.3.tar.gz'
            ]
            unexpectedFound = False
            for link, package in packages:
                try:
                    expectedPackages.remove(package)
                except:
                    print "Package '%s' unexpected" % package
                    unexpectedFound = True
            self.assertFalse(unexpectedFound)
            if len(expectedPackages) != 0:
                print "Packages not retrieved: ", expectedPackages

            self.assertEqual(len(expectedPackages), 0)
        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")

            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            result = subprocess.call(['sudo', 'rm', '-r', cache], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result, 0)

    def test_namesWithDashes(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            self._startTestPypiServer(path, pypiport)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{'default-context':'mytest',
                 'interfaces':'localhost',
                 'port':facadeport,
                 #'constraining-indicies':
                 'indicies':
                     'http://localhost:%d/pypi-99:99:03' % pypiport,
                 'cache':cache,
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            #Try getting the index for pip
            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/os-apply-config'),
                cafile=chrootcert )
            data = indexresult.read()
            packages = self._fishLinksIntoList(data)
            expectedPackages = [
                'os-apply-config-0.1.14.tar.gz'
            ]
            unexpectedFound = False
            for link, package in packages:
                try:
                    expectedPackages.remove(package)
                except:
                    print "Package '%s' unexpected" % package
                    unexpectedFound = True
            self.assertFalse(unexpectedFound)
            if len(expectedPackages) != 0:
                print "Packages not retrieved: ", expectedPackages

            self.assertEqual(len(expectedPackages), 0)

            fileresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'mytest/os-apply-config/os-apply-config-0.1.14.tar.gz'),
                cafile=chrootcert )

            md5sum = self.csmake_test._fileMD5(fileresult)
            fileresult.close()
            with open(os.path.join(
                   path,
                   'pypi-99:99:03/os-apply-config/os-apply-config-0.1.14.tar.gz')) as pypifile:
                pypimd5sum = self.csmake_test._fileMD5(pypifile)
            self.assertEqual(md5sum, pypimd5sum)

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")

            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            result = subprocess.call(['sudo', 'rm', '-r', cache], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result, 0)

    def test_checkSimpleCertDelete(self):
        service = self._setupForStandardChrootedService()
        serviceObj = service['service']
        chroot = service['chroot']
        bundle = service['bundle']
        testcert = service['testcert']
        try:
            #Ensure the generated certificate is in the bundle
            certManager = serviceObj.getCertificateManager()
            rootCA = certManager.getCARootPath()
            with open(rootCA) as newcert:
                certstring = ''.join(newcert.readlines())

            with open(bundle) as certbundle:
                bundlestring = ''.join(certbundle.readlines())

            self.assertTrue(certstring in bundlestring)

            #Ensure the root we're going to use is valid
            try:
                ssl.create_default_context(cafile=bundle)
            except:
                print "The bundle with the certificate '%s' is invalid" % bundle
                self.assertTrue(False)

            PypiProvider.PypiProvider.disposeServiceProvider('tag')

            with open(bundle) as certbundle:
                bundlestring = ''.join(certbundle.readlines())

            self.assertFalse(certstring in bundlestring)

            #Ensure the generated certificate is still valid
            try:
                ssl.create_default_context(cafile=bundle)
            except:
                print "The bundle '%s' was spoiled by the server" % bundle
                self.assertTrue(False)

            #Is the bundle the exact same as before
            try:
                subprocess.check_call(
                    ['diff', testcert, bundle],
                    stdout=self.csmake_test.log.out(),
                    stderr=self.csmake_test.log.err() )
            except:
                print "The bundle is not the same as the original, but should be"
                self.csmake_test.log.exception("     Exception")
                self.assertTrue(False)

        finally:
            self._cleanupStandardChrootedService(service)

    def test_userDeleted(self):
        service = self._setupForStandardChrootedService()
        chroot = service['chroot']
        bundle = service['bundle']
        testcert = service['testcert']
        chrootcertpath = service['chrootcertpath']
        fakeuser = service['fakeuser']
        fakeuserhome = os.path.join(chroot, "home", fakeuser)
        try:
            #TODO: Wait for controller to be ready
            #         dir monitor and fifo's too
            #  For now, we'll do a read loop until we get data
            ready = False
            timer = 110
            while not ready:
                time.sleep(0.1)
                timer = timer - 1
                if timer == 0:
                    print "fakeuser's fifo never started after 11 seconds"
                    self.assertTrue(False)
                try:
                    with open(os.path.join(fakeuserhome,'.pydistutils.cfg')) as readfake:
                        ready = len(readfake.read()) > 0
                except:
                    #File's not ready yet
                    if timer % 10 == 0:
                        print "still waiting for .pydistutils.cfg to come online"
                    pass

            self.assertTrue(ready)

            while not ready:
                time.sleep(0.1)
                timer = timer - 1
                if timer == 0:
                    print "fakeuser's fifo never started after 11 seconds"
                    self.assertTrue(False)
                try:
                    with open(os.path.join(fakeuserhome,'.config/pip/pip.conf')) as readfake:
                        ready = len(readfake.read()) > 0
                except:
                    #File's not ready yet
                    if timer % 10 == 0:
                        print "still waiting for pip.conf to come online"

            self.assertTrue(ready)

            #Delete the user directory
            result = subprocess.call(
                ['sudo', 'rm', '-rf', fakeuserhome] )
            self.assertEqual(result, 0)

        finally:
            self._cleanupStandardChrootedService(service)

    def test_checkCertDeleteWithNewCertsAppended(self):
        service = self._setupForStandardChrootedService()
        serviceObj = service['service']
        chroot = service['chroot']
        bundle = service['bundle']
        testcert = service['testcert']
        chrootcertpath = service['chrootcertpath']
        testspath = service['testspath']
        try:
            #Ensure the generated certificate is in the bundle
            certManager = serviceObj.getCertificateManager()
            rootCA = certManager.getCARootPath()
            with open(rootCA) as newcert:
                certstring = ''.join(newcert.readlines())

            with open(bundle) as certbundle:
                bundlestring = ''.join(certbundle.readlines())

            self.assertTrue(certstring in bundlestring)

            #Add some extra certs
            newcert = os.path.join(chrootcertpath, 'new.crt')
            result = subprocess.call(
                'cat %s %s > %s' % (
                    os.path.join(testspath, 'append.crt'),
                    bundle,
                    newcert),
                shell=True )
            self.assertEqual(result, 0)
            result = subprocess.call(
                ['mv', newcert, bundle] )
            self.assertEqual(result, 0)

            with open(bundle) as certbundle:
                bundlestring = ''.join(certbundle.readlines())

            self.assertTrue(certstring in bundlestring)

            #Ensure the root we're going to use is valid
            try:
                ssl.create_default_context(cafile=bundle)
            except:
                print "The bundle '%s' is invalid" % bundle
                self.assertTrue(False)

            PypiProvider.PypiProvider.disposeServiceProvider('tag')

            with open(bundle) as certbundle:
                bundlestring = ''.join(certbundle.readlines())

            self.assertFalse(certstring in bundlestring)

            #Ensure the generated certificate is still valid
            try:
                ssl.create_default_context(cafile=bundle)
            except:
                print "The bundle '%s' was spoiled by the server" % bundle
                self.assertTrue(False)

        finally:
            self._cleanupStandardChrootedService(service)

    def test_certDeletedByBuild(self):
        service = self._setupForStandardChrootedService()
        serviceObj = service['service']
        chroot = service['chroot']
        bundle = service['bundle']
        testcert = service['testcert']
        chrootcertpath = service['chrootcertpath']
        try:
            #Ensure the generated certificate is in the bundle
            certManager = serviceObj.getCertificateManager()
            rootCA = certManager.getCARootPath()
            with open(rootCA) as newcert:
                certstring = ''.join(newcert.readlines())

            with open(bundle) as certbundle:
                bundlestring = ''.join(certbundle.readlines())

            self.assertTrue(certstring in bundlestring)

            #Now restore the original bundle
            shutil.copy(testcert,chrootcertpath)

            with open(bundle) as certbundle:
                bundlestring = ''.join(certbundle.readlines())

            self.assertFalse(certstring in bundlestring)

            PypiProvider.PypiProvider.disposeServiceProvider('tag')

            with open(bundle) as certbundle:
                bundlestring = ''.join(certbundle.readlines())
            with open(testcert) as certbundle:
                origbundlestring = ''.join(certbundle.readlines())

            self.assertFalse(certstring in bundlestring)
            self.assertEqual(bundlestring, origbundlestring)

            for dirpath in PypiProvider.SSLCertificateManager.CERT_DIRS:
                certpath = os.path.join(chroot,dirpath[1:])
                if os.path.exists(certpath):
                    self.csmake_test.log.error(
                        "Path '%s' still exists",
                        certpath)
                self.assertFalse(os.path.exists(certpath))
            for bundlefile in PypiProvider.SSLCertificateManager.CERT_PATHS:
                bundlepath, _ = os.path.split(bundlefile)
                #These asserts are not actually valid in the context of the
                #tests - it's possible that a PypiFacade was executed
                #That created these backup files outside of testing
                #  These checks can be used in a clean environment to ensure
                #  that the pypi facade is behaving itself.
                #bkups = glob.glob(os.path.join(bundlepath,"*.bkup"))
                #self.csmake_test.log.debug("*.bkup files: %s", str(bkups))
                #self.assertEqual(
                #    len(bkups),
                #    0 )
                #temp = glob.glob(os.path.join(bundlepath,"*.temp"))
                #self.csmake_test.log.debug("*.temp files: %s", str(temp))
                #self.assertEqual(
                #    len(temp),
                #    0 )
                #csmakes = glob.glob(os.path.join(bundlepath,"*csmake*"))
                #self.csmake_test.log.debug("*csmake* files: %s", str(csmakes))
                #self.assertEqual(
                #    len(csmakes),
                #    0 )
                chbkups = glob.glob(os.path.join(chroot + bundlepath,"*.bkup"))
                self.csmake_test.log.debug("chroot *.bkup files: %s", str(chbkups))
                self.assertEqual(
                    len(chbkups),
                    0 )
                chtemp = glob.glob(os.path.join(chroot + bundlepath,"*.temp"))
                self.csmake_test.log.debug("chroot *.temp files: %s", str(chtemp))
                self.assertEqual(
                    len(chtemp),
                    0 )
                chcsmakes = glob.glob(os.path.join(chroot + bundlepath,"*csmake*"))
                self.csmake_test.log.debug("chroot *csmake* files: %s", str(chcsmakes))
                self.assertEqual(
                    len(chcsmakes),
                    0 )

            #Ensure the generated certificate is still valid
            try:
                ssl.create_default_context(cafile=bundle)
            except:
                print "The bundle '%s' was spoiled by the server" % bundle
                self.assertTrue(False)

        finally:
            self._cleanupStandardChrootedService(service)

    def test_configurationPypiChangeCorrectness(self):
        #Set up the chroot environment, but don't start the service
        service = self._setupForStandardChrootedService(startService=False)
        chroot = service['chroot']
        userhome = os.path.expanduser('~')[1:]
        fullHome = os.path.join(
            chroot,
            userhome )
        facadeport = service['facadeport']
        bundle = service['bundle']
        testcert = service['testcert']
        chrootcertpath = service['chrootcertpath']
        testspath = service['testspath']
        fakeuser = service['fakeuser']
        fakeuserhome = os.path.join(chroot, 'home', fakeuser)
        userpydist = os.path.join(fakeuserhome, '.pydistutils.cfg')
        with open(userpydist, 'w') as conffile:
            conffile.write("This is not a real distutils config")

        userpypipath = os.path.join(fakeuserhome, ".config/pip")
        userpypi = os.path.join(userpypipath, 'pip.conf')
        os.makedirs(userpypipath)
        with open(userpypi, 'w') as conffile:
            conffile.write("This is not a real pip config")

        py26distutils = os.path.join(chroot, "usr/lib/python2.6/distutils")
        py27distutils = os.path.join(chroot, "usr/lib/python2.7/distutils")
        os.makedirs(py26distutils)
        os.makedirs(py27distutils)
        py26cfg = os.path.join(py26distutils, "distutils.cfg")
        py27cfg = os.path.join(py27distutils, "distutils.cfg")

        with open(py26cfg, 'w') as conffile:
            conffile.write("This is not a real distutils 2.6 global config")
        with open(py27cfg, 'w') as conffile:
            conffile.write("This is not a real distutils 2.7 global config")
        self.assertTrue(os.path.exists(py26cfg))
        self.assertTrue(os.path.exists(py27cfg))

        #This time actually start the service
        service = self._setupForStandardChrootedService()
        try:
            self.assertTrue(os.path.exists(fullHome))
            self.assertFalse(os.path.exists(py26cfg))
            self.assertFalse(os.path.exists(py27cfg))
            with open(userpydist) as conffile:
                lines = conffile.readlines()
            distconfActual = [
                "[easy_install]\n",
                "index-url=https://localhost:%s/mytest\n" % facadeport ]
            self.assertEqual(distconfActual, lines)
            with open(userpypi) as conffile:
                lines = conffile.readlines()
            self.assertTrue(os.path.exists(bundle))
            pipconfActual = [
                "[global]\n",
                "index-url=https://localhost:%s/mytest\n" % facadeport,
                "cert=/%s\n" % os.path.relpath(bundle, chroot),
                "verbose=true\n",
                "timeout=45\n" ]
            self.assertEqual(pipconfActual, lines)

            PypiProvider.PypiProvider.disposeServiceProvider('tag')
            self.assertFalse(os.path.exists(fullHome))

            self.assertTrue(os.path.exists(py26cfg))
            self.assertTrue(os.path.exists(py27cfg))
            testphrase = "This is not a real"
            with open(userpydist) as conffile:
                result = conffile.read()
            self.assertEqual(testphrase, result[:len(testphrase)])
            with open(userpypi) as conffile:
                result = conffile.read()
            self.assertEqual(testphrase, result[:len(testphrase)])
            self.assertEqual(
                len(glob.glob(os.path.join(py26distutils, "*.bkup"))),
                0 )
            self.assertEqual(
                len(glob.glob(os.path.join(py27distutils, "*.bkup"))),
                0 )
            self.assertEqual(
                len(glob.glob(os.path.join(fakeuserhome, "*.bkup"))),
                0 )
            self.assertEqual(
                len(glob.glob(os.path.join(fakeuserhome, ".config/pip/pip.conf.bkup"))),
                0 )
            self.assertFalse(
                os.path.exists(
                    os.path.join(chroot, "root/.config/pip/pip.conf")))

        finally:
            self._cleanupStandardChrootedService(service)

    def test_MySQL_python_file(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            self._startTestPypiServer(path, pypiport)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{
                 'interfaces':'localhost',
                 'port':facadeport,
                 'indicies':
                     'http://localhost:%d/pypi-99:99:01\nhttp://localhost:%d/pypi-99:99:03' % (pypiport, pypiport),
                 'constraints':'MySQL-python==1.2.3',
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'simple/mysql-python'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify mysql package is in the list and only the version
            #specified
            expectedfiles = [
                'MySQL-python-1.2.3.tar.gz' ]

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedfiles.remove(link)
                except:
                    print "File '%s' unexpected" % link
                    unexpectedFound = True

            if len(expectedfiles) != 0:
                print "Files not retrieved: ", expectedfiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedfiles),0)

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")
            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result,0)

    def test_PEP503_handling(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            self._startTestPypiServer(path, pypiport)

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{
                 'interfaces':'localhost',
                 'port':facadeport,
                 'indicies':
                     'http://localhost:%d/pypi-99:99:02\nhttp://localhost:%d/pypi-99:99:03' % (pypiport, pypiport),
                 'constraints':'oslo.config>=2',
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'simple/oslo.config'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            #Verify mysql package is in the list and only the version
            #specified
            expectedfiles = [
                'oslo.config-3.4.0-py2.py3-none-any.whl',
                'oslo.config-2.7.0.tar.gz',
                'oslo.config-3.5.0-py2.py3-none-any.whl' ]

            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedfiles.remove(link)
                except:
                    print "File '%s' unexpected" % link
                    unexpectedFound = True

            if len(expectedfiles) != 0:
                print "Files not retrieved: ", expectedfiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedfiles),0)

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")
            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result,0)

    def test_hashesatendoflinks(self):
        pypiport = 29988
        facadeport = "25891"
        fakeuser = "xyzzy151235"
        testspath = os.path.join(
            os.getcwd(),
            self.csmake_test.options['test-dir'])
        path = os.path.join(
            testspath,
            'pipmirrors' )
        chroot = os.path.join(
            testspath,
            'fakechroot')
        cache = os.path.join(
            testspath,
            'cache' )

        try:
            #Create the root user path
            os.makedirs(os.path.join(chroot,'root'))

            #Create the home directory and put in a fake user
            os.makedirs(os.path.join(chroot, "home", fakeuser))

            #Create the fake cert home
            chrootcertpath = os.path.join(chroot, "etc/ssl/certs")
            certpath="/etc/ssl/certs/ca-certificates.crt"
            certfrom=None
            os.makedirs(chrootcertpath)
            if os.path.exists(certpath):
                shutil.copy(certpath, chrootcertpath)
                certfrom=certpath
            else:
                testcert=os.path.join(testspath, 'ca-certificates.crt')
                shutil.copy(testcert,chrootcertpath)
                certfrom=testcert
            chrootcert = os.path.join(chrootcertpath,'ca-certificates.crt')

            #NOTE: This is what makes this test interesting
            self._startTestPypiServer(path, pypiport, suffix="#thisshouldbe=strippedoff")

            facadeurl='https://localhost:%s/mytest' % facadeport

            service = PypiProvider.PypiProvider.createServiceProvider(
                'tag',
                self.csmake_test,
                **{
                 'interfaces':'localhost',
                 'port':facadeport,
                 'indicies':
                    'http://localhost:%d/pypi-99:99:01\nhttp://localhost:%d/pypi-99:99:02' % (pypiport,pypiport),
                 'chroot':chroot } )
            service.startService()
            controller = service.getController()

            indexresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'simple/pip'),
                cafile=chrootcert )
            data = indexresult.read()
            files = self._fishLinksIntoList(data)

            expectedfiles = [
                'pip-1.5.4-py2.py3-none-any.whl#thisshouldbe=strippedoff',
                'pip-6.1.1-py2.py3-none-any.whl#thisshouldbe=strippedoff',
                'pip-6.1.1.tar.gz#thisshouldbe=strippedoff',
                'pip-7.0.2.tar.gz#thisshouldbe=strippedoff',
                'pip-7.0.3-py2.py3-none-any.whl#thisshouldbe=strippedoff',
                'pip-7.0.3.tar.gz#thisshouldbe=strippedoff'
            ]
            unexpectedFound = False

            for link, filename in files:
                try:
                    expectedfiles.remove(link)
                except:
                    print "File '%s' unexpected" % link
                    unexpectedFound = True

            if len(expectedfiles) != 0:
                print "Files not retrieved: ", expectedfiles

            self.assertFalse(unexpectedFound)

            self.assertEqual(len(expectedfiles),0)

            fileresult = urllib2.urlopen(
                urlparse.urljoin(facadeurl, 'simple/pip/pip-6.1.1-py2.py3-none-any.whl#thisshouldbe=strippedoff'),
                cafile=chrootcert )

            md5sum = self.csmake_test._fileMD5(fileresult)
            fileresult.close()
            with open(os.path.join(
                   path,
                   'pypi-99:99:01/pip/pip-6.1.1-py2.py3-none-any.whl')) as pypifile:
                pypimd5sum = self.csmake_test._fileMD5(pypifile)
            self.assertEqual(md5sum, pypimd5sum)

        finally:
            try:
                PypiProvider.PypiProvider.disposeServiceProvider('tag')
            except:
                self.csmake_test.log.exception("endService failed")
            try:
                self._stopTestPypiServer()
            except:
                self.csmake_test.log.exception("stopTestPypiServer failed")
            print "Removing ", chroot
            result = subprocess.call(['sudo', 'rm', '-r', chroot], stdout=self.csmake_test.log.out())
            self.assertFalse(os.path.exists(chroot))
            self.assertEqual(result,0)
