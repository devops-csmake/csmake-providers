# <copyright>
# (c) Copyright 2021 Cardinal Peak Technologies
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
import socket
import ssl
import subprocess
import os
import os.path
import stat
import urllib2
import urlparse
import re
import random
import glob
import getpass
import time
import StringIO
import shutil
import logging
import sys
import tempfile
import functools
from SimpleHTTPServer import SimpleHTTPRequestHandler
from urllib2 import HTTPError
from CsmakeServiceProvider import CsmakeServiceProvider, CsmakeServiceDaemon
from CsmakeServiceProvider import CsmakeServiceConfigManager
from CsmakeServiceProvider import CsmakeServiceConfig
#PYPA packages
from packaging import version
from packaging import specifiers

class PullLinksThread(threading.Thread):
    """Results are in the form of (index, [(href, name)...])"""
    def __init__(self, index, paths, log, onfail=None):
        threading.Thread.__init__(self)
        self.index = index
        self.paths = paths
        self.path = None
        self.url = self.index
        self.onfail = onfail

        self.links = None
        self.exc_info = None
        self.log = log

    def getIndex(self):
        return self.index

    def getPath(self):
        return self.path

    def getUrl(self):
        return self.url

    def getPaths(self):
        return self.paths

    def getLinks(self):
        #Reraise the exception
        if self.exc_info is not None:
            raise self.exc_info[0], self.exc_info[1], self.exc_info[2]
        else:
            return (self.url, self.links)

    linkre = re.compile(r'\s*=\s*(\"|\')(?P<link>[^"]*)(\"|\')')

    def _doPaths(self, url, paths):
        success = False
        if paths is None:
            paths = ('',)
        elif type(paths) != tuple:
            raise TypeError("Paths must be a tuple of paths to try")
        originalurl = url
        for path in paths:
            url = originalurl
            if url[-1] != '/':
                url += '/'
            url = urlparse.urljoin(url, path)
            if url[-1] != '/':
                url += '/'

            buf = []
            self.links = []

            try:
                fd = urllib2.urlopen(url)
            except:
                self.exc_info = sys.exc_info()
                continue

            r = fd.read()
            while len(r) != 0:
                buf.append(r)
                r = fd.read()
            fd.close()
            self.log.devdebug("Page requested: %s", url)
            self.log.devdebug("Page pulled:\n%s", buf)
            success = True
            self.url = url
            self.path = path
            self.exc_info = None

            buf = ''.join(buf).split('<a ')[1:]
            buf = [ x.split('</a')[0].split('>',1) for x in buf ]
            for link in buf:
                #NOTE: It may be more correct to split on '=' and get the
                #      href that way.
                parts = link[0].split('href',1)
                if len(parts) < 2:
                    self.log.info("Link from '%s' malformed: %s", url, str(link))
                    continue
                match = PullLinksThread.linkre.match(parts[1])
                if match is None:
                    self.log.info("Link href from '%s' malformed: %s", url, str(link))
                    continue
                linkmatch = match.group('link')
                if linkmatch is not None:
                    linkmatch = urllib2.unquote(linkmatch)
                self.links.append((linkmatch, link[1]))
            break
        return success

    def run(self):
        try:
            if not self._doPaths(self.url, self.paths) and \
                self.onfail is not None:

                url, paths = self.onfail(self)
                if url is not None:
                    self._doPaths(url, paths)
        except Exception as e:
            self.exc_info = sys.exc_info()

class PypiContext:
    #Taken from pip/utils/__init__.py
    BZ2_EXTENSIONS = ('.tar.bz2', '.tbz')
    ZIP_EXTENSIONS = ('.zip',)
    WHEEL_EXTENSIONS = ('.whl',)
    TAR_EXTENSIONS = ('.tar.gz', '.tgz', '.tar')
    SUPPORTED_EXTENSIONS = \
        BZ2_EXTENSIONS + ZIP_EXTENSIONS + TAR_EXTENSIONS + WHEEL_EXTENSIONS

    #Version specifier operations boiled down to an re
    #Caution, uses a private member of Specifier, subject to revision
    SPECIFIER_OPS_RE = re.compile('|'.join(specifiers.Specifier._operators.keys()))

    def _splitReq(self, req):
        match = self.SPECIFIER_OPS_RE.search(req)
        if match is None:
            return (req, "")
        try:
            return (self._normalizePackageName(req[:match.start(0)]),
                    req[match.start(0):])
        except:
            self.log.exception("Invalid requirement given '%s'", req)
            return (req, "")

    #Implement the base http handler protocol
    #  Useful for initiating transfers without a real client
    class NullHTTPHandler:
        def __init__(self):
            self.wfile = StringIO.StringIO()

        def send_header(self, header, value):
            pass

        def end_headers(self):
            pass

        def send_response(self, response):
            pass

        def send_error(self, *params):
            pass

    class _SplitHeuristics:
        #This is the implementation of the version heuristics specified
        # in _splitPypiName (see below)

        def __init__(self, results, dashparts, filename, templates, log):
            self.dashparts = dashparts
            self.filename = filename
            self.results = results
            self.packageName = self.results['package']
            self.templates = templates
            self.log = log

        def getHeuristics(self):
            return [
                self.custom,
                self.majorMinorPatchAtEnd,
                self.majorMinorPatchStuffAtEnd,
                self.majorMinorAtEnd,
                self.majorMinorStuffAtEnd,
                self.versionHasEpoch,
                self.versionHasPlus,
                self.versionHasDashVNum,
                self.findAValidVersion,
                self.findLegacyParenedVersion,
                self.findDashVanything,
                self.assumeTheLastClauseIsaVersion ]

        def assumeTheLastClauseIsaVersion(self):
            #Implementation of 6c and 6d
            #This can only return legacy versions
            #A real version would have been snatched up by TD5 already.
            #First, 6c
            minparts = 3
            packageFound = self.results['package'] is not None
            if packageFound:
                minparts = 2
            self.log.devdebug("minparts (6c): %s, %s", minparts, self.results['package'])
            if len(self.dashparts) >= minparts:
                if len(self.dashparts[-1]) > 0 and self.dashparts[-1][0].isdigit():
                    #PEP-427 build tag
                    self.results['build'] = self.dashparts[-1]
                    self.results['version'] = version.LegacyVersion(self.dashparts[-2])
                    if not packageFound:
                        self.results['package'] = '-'.join(self.dashparts[:-2])
                    self.results['heuristic'] = '6c'
                    return True

            #It's not 6c, so 6d
            minparts = 2
            if packageFound:
                minparts = 1
            if len(self.dashparts) >= minparts:
                self.results['version'] = version.LegacyVersion(self.dashparts[-1])
                if not packageFound:
                    self.results['package'] = '-'.join(self.dashparts[:-1])
                self.results['heuristic'] = '6d'
                return True
            return False

        def findDashVanything(self):
            #Implementation of 6b
            backwards = list(self.dashparts)
            backwards.reverse()
            packageFound = self.results['package'] is not None
            if not packageFound:
                backwards = backwards[:-1]
            venditem = None
            vstartitem = None
            for index, item in enumerate(backwards):
                if item.startswith('v') or item.startswith('V'):
                    vstartitem = -index-1
                    venditem = None
                    buildmatch = -1
                    while vstartitem < buildmatch:
                        current = self.dashparts[buildmatch]
                        if len(current) > 0 and current[0].isdigit():
                            #This matches PEP-427's build tag
                            self.results['build'] = '-'.join(self.dashparts[buildmatch:])
                            venditem = buildmatch
                            break
                        buildmatch = buildmatch - 1
                    if not packageFound:
                        self.results['package'] = '-'.join(self.dashparts[:vstartitem])
                    if venditem is None:
                        vstring = '-'.join(self.dashparts[vstartitem:])
                    else:
                        vstring = '-'.join(self.dashparts[vstartitem:venditem])
                    try:
                        self.results['version'] = version.Version(vstring)
                    except version.InvalidVersion:
                        self.results['version'] = version.LegacyVersion(vstring)
                    self.results['heuristic'] = '6b'
                    return True
            return False

        def findLegacyParenedVersion(self):
            #Implementation of 6a
            backwards = list(self.dashparts)
            backwards.reverse()
            packageFound = self.results['package'] is not None
            if not packageFound:
                backwards = backwards[:-1]
            found = None
            venditem = None
            vstartitem = None
            for index, item in enumerate(backwards):
                if re.match(r"^[vV][(]", item):
                    forwards = -index-1
                    found = item
                    vstartitem = forwards
                    while ')' not in found:
                        forwards = forwards + 1
                        if forwards == 0:
                            #Nope, not a v(stuff) version...
                            return False
                        found = found + '-' + self.dashparts[forwards]
                    if not found.endswith(')'):
                        return False
                    else:
                        venditem = forwards
                        break
            if found is None:
                return False
            if venditem < -1:
                #Verify that if there's more beyond the
                #version that it's a PEP-427 compliant build tag
                current = self.dashparts[venditem + 1]
                if len(current) > 0 and not current[0].isdigit():
                    return False
                else:
                    self.results['build'] = '-'.join(self.dashparts[venditem+1:])
            try:
                self.results['version'] = version.Version(found[2:-1])
            except version.InvalidVersion:
                self.results['version'] = version.LegacyVersion(found[2:-1])
            if not packageFound:
                self.results['package'] = '-'.join(self.dashparts[:vstartitem])
            self.results['heuristic'] = '6a'
            return True

        def findAValidVersion(self):
            #Implementation of 5
            if self._checkMatchUsingTD3(None):
                self.results['heuristic'] = 'TD5'
                return True
            return False

        def versionHasDashVNum(self):
            #Implementation of 4g
            if self._checkMatchUsingTD3(r'^[vV][0-9]'):
                self.results['heuristic'] = 'TD4g'
                return True
            return False

        def versionHasEpoch(self):
            #Implementation of 4e
            if self._checkMatchUsingTD3(r'^[vV]?[0-9][!][0-9]'):
                self.results['heuristic'] = 'TD4e'
                return True
            return False

        def versionHasPlus(self):
            #Implementation of 4f
            if self._checkMatchUsingTD3(
                r'^[vV]?([0-9]+\!)?[0-9][0-9abrposte]*([.][0-9abrposte]+([.][0-9abrposte]+(-[0-9abrposte]+)?)?)?[+][^+]+' ):
                self.results['heuristic'] = 'TD4f'
                return True
            return False

        def majorMinorStuffAtEnd(self):
            #Implementation of 4d
            if self._checkEndWithDash(r'^[vV]?[0-9]+[.][0-9]+-[0-9].*$'):
                self.results['heuristic'] = 'TD4d'
                return True
            return False

        def majorMinorAtEnd(self):
            #Implementation of 4c
            if self._checkEnd(r'^[vV]?[0-9]+[.][0-9]+$'):
                self.results['heuristic'] = 'TD4c'
                return True
            return False

        def majorMinorPatchStuffAtEnd(self):
            #Implementation of 4b
            if self._checkEndWithDash(
                r"^[vV]?[0-9]+[.][0-9]+[.][0-9]+-[0-9].*$"):
                self.results['heuristic'] = 'TD4b'
                return True
            return False

        def majorMinorPatchAtEnd(self):
            #Implementation of 4a
            if self._checkEnd(r"^[vV]?[0-9]+[.][0-9]+[.][0-9]+$"):
                self.results['heuristic'] = 'TD4a'
                return True
            return False

        #######################################
        # Standard checking patterns
        def _checkEnd(self, matcher):
            if len(self.dashparts) >= 1:
                if re.match(matcher, self.dashparts[-1]):
                    try:
                        found = version.Version(self.dashparts[-1])
                    except version.InvalidVersion:
                        return False
                    self.results['version'] = found
                    if self.results['package'] is None:
                        self.results['package'] = '-'.join(self.dashparts[:-1])
                    return True
            return False

        def _checkEndWithDash(self, matcher):
            if len(self.dashparts) >= 2:
                firstString = '-'.join(self.dashparts[-2:])
                self.log.devdebug("firstString: %s", firstString)
                if re.match(matcher, firstString ):
                    try:
                        found = version.Version(firstString)
                    except version.InvalidVersion:
                        try:
                            found = version.Version(self.dashparts[-2])
                            self.results['build'] = self.dashparts[-1]
                        except version.InvalidVersion:
                            return False
                    self.results['version'] = found
                    if self.results['package'] is None:
                        self.results['package'] = '-'.join(self.dashparts[:-2])
                    return True
            return False

        def _checkMatchUsingTD3(self, matcher):
            #Passing None for matcher is the TD5 implementation
            packageFound = self.results['package'] is not None
            startpoint = 0 if packageFound else 1
            while startpoint < len(self.dashparts):
                endpoint = len(self.dashparts)
                buildTag = None
                while endpoint > startpoint:
                    vstring = '-'.join(self.dashparts[startpoint:endpoint])
                    self.log.devdebug("Checking: %s", vstring)
                    if matcher is None or re.match(matcher, vstring):
                        try:
                            found = version.Version(vstring)
                            self.results['version'] = found
                            if endpoint < len(self.dashparts):
                                self.results['build'] = '-'.join(self.dashparts[endpoint:])
                            if not packageFound:
                                self.results['package'] = '-'.join(self.dashparts[:startpoint])
                            return True
                        except version.InvalidVersion:
                            #If one of the dashparts previous to endpoint
                            # conforms to PEP-427's notion of a build tag
                            # try forming that into a build tag and try again
                            # A version section has to exist before
                            # the build tag by PEP-427, so prevent the
                            # build tag matching from eating in to what
                            # has to be the version tag (startpoint)
                            endpoint = endpoint - 1
                            current = None
                            while endpoint > startpoint:
                                current = self.dashparts[endpoint]
                                self.log.devdebug("Current PEP-427 trial: %s", current)
                                if len(current) > 0 and current[0].isdigit():
                                    break
                                else:
                                    self.log.devdebug("%s, %s",
                                        len(current),
                                        current[0].isdigit() if len(current) else '---')
                                current = None
                                endpoint = endpoint - 1
                            if current is None:
                                self.log.devdebug("No PEP-427 build tag found")
                                #No PEP-427 conformant build tag was found
                                break
                    else:
                        endpoint = endpoint - 1
                        current = None
                        while endpoint > startpoint:
                            current = self.dashparts[endpoint]
                            self.log.devdebug("Non-match: Current PEP-427 trial: %s", current)
                            if len(current) > 0 and current[0].isdigit():
                                break
                            else:
                                self.log.devdebug(
                                    "Non-match: %s, %s",
                                    len(current),
                                    current[0].isdigit() if len(current) else '---')
                            current = None
                            endpoint = endpoint - 1
                        if current is None:
                            self.log.devdebug("Non-match: No PEP-427 build tag found")
                            break
                startpoint = startpoint + 1
            return False

        #########################################3

        def custom(self):
            #Implementation of TD2
            if self.templates is None or len(self.templates) == 0:
                self.log.debug("No templates found")
                return False
            template = None
            #Package name is set then it is an exact match
            #on the first thing we find.
            if self.packageName is not None:
                template = self.templates[self.packageName][1]
            if template is None:
                testName = '-'.join(dashparts)
                count = 0
                while(testName not in self.templates):
                    count = count + 1
                    testName = '-'.join(dashparts[:-count])
                if testName not in self.templates:
                    self.log.debug('Could not find a custom template for "%s"', self.filename)
                    return False
                nonmatches, template = self.templates[testName]
                for nonmatch in nonmatches:
                    numdashes = nonmatch.count('-')+1
                    if len(dashparts) >= numdashes:
                        testName = '-'.join(dashparts[numdashes])
                        if testName == nonmatch:
                            self.log.debug('No template found for "%s"' % nonmatch)
                            return False
            #TODO: Execute template.
            self.log.info("TODO: Version parsing template execution incomplete")
            return False

    def _normalizePackageName(self, packagename):
        #Some pypi servers return #'s with information after it like md5
        return re.sub(r"[-_.]+", '-', packagename).lower()

    def _splitPypiName(self, filename, packageVersioningSchemes={}, packageName=None):
        #TODO: The packageVersioningSchemes is a dictionary of
        #  {'<package name>' :
        #     ([<non matching package names], <regular expression>) }
        #  Where the <regular expression> has two named groups
        #    1) package - the group that identifies the package name
        #    2) version - the group that identifies the version name
        #  If necessary, more parts of the version can be identified
        #    for really, really baroque versioning schemes using
        #    version_[a-z] group namings and they will be stitched
        #    together in the order named using .'s for and unfilled
        #    major and minor part from version followed by '+'
        #    with the rest of the parts concatenated with .'s in the
        #    alpha order of the _<letter>
        #  --This work may be useful to help limit package availability
        #  --It is tagged for future work if needed...it'll probably be
        #    eventually needed.
        #
        #Attempts to disgronify a filename into constituent parts based on
        #PEP-425 and PEP-440 (and referencing PEP-427 and PEP-427/PEP-491
        # because of build tags...and PEP-386 because the LooseVersion schema
        # may still be encountered even though it's superceded by PEP-440)
        #                     (can someone please slap the person who thought
        #                      it was a good idea to reuse the '-' delimiter
        #                      for PEP-425???  Just why...really, why...
        #                      I wouldn't complain except that package names
        #                      can contain dashes and start with numbers
        #                      after the dashes, and the version can
        #                      be only a major number, e.g.:
        #                          51degrees-mobile-detector-1.0.tar.gz
        #                          3-1-1.0.0.zip
        #                          m.y-2-4-py2.py3-none-any.whl (made up)
        #                          73.unlockItems-0.3.tar.gz
        #                          73.42-19.1-4-3-py2-none-any.whl
        #                          73.42.19.1-4-2.tar.bz2  (these two made up)
        #                      Don't forget, we'll need to handle all kinds
        #                      of stuff that isn't actually a real package as
        #                      well)
        # PEP-427/PEP-491 adds the possible concept of a build tag whose only
        # caveat is that it has to start with a number...
        #  {distribution}-{version}(-{build tag})?-{python tag}-{abi tag}-{platform tag}.whl
        #so, this breaks any reasonable form of computable versioning
        #from the filename.  Now, couple this with PEP-440's idea
        #of translating -# to .post# and you have a perfect storm
        #because a build number implies a pre-release but PEP-440 claims
        #(and developers have intended) the -# to be a post release roll.
        #  It may be the case that since PEP-427 is wheel related that
        #  we can ignore build tags for non-wheel files....but come on...
        #  Obviously, leaning solely on pip's filename -> version
        #     parsing (which is baroque at best) doesn't really
        #     do this justice, especially since we also have to handle
        #     setuptools requests as well and the various conflicting PEPs
        #     and the wild west mentality of developers trying what's cool
        #     versus what's sane.
        #     pip also tries to sort, which we don't need to do.
        #     pip also isn't necessarily worried about tracking
        #        multiple package versions over many requests.
        #  This all matters by the way because this is intended to be
        #  a facade for development production builds....which may
        #  have a build number in its scheme...and said build number
        #  must start with ... yup, a number.
        #  So, in order to actually get something even close to sanely
        #  computable out of this, first of all, the strong guidance is to
        #  use the local build mechanism in PEP-440 the '+' designator
        #  to supply a build number and completely forego use of the
        #  wheel's notion of a -#<stuff>* build tag (where <stuff>
        #  could be a whole bevy of dashes).  The + will be used to
        #  finger the actual version string.
        #  So, second guidance is don't use a dash in a local build designation
        #  designation, just don't - it'll get normalized to a '.' first of all
        #    and second of all it lowers the chances of the heuristics matching
        #    the intended versioning schema.
        #  Third, don't ever use a dash in a package name (but many do).
        #  Fourth, never use numbers in the package name.
        #  Fifth, never use '!' in the package name.
        #  Sixth, never use '.' in the package name (but many packages do that).
        #  Seventh, if you absolutely need to use a build tag and not
        #    a local build number with '+' then put somthing that
        #    makes it not a part of a proper PEP-440 version (like a
        #    letter, for example, apackage-V3!1.2.3-1b99.tar.gz ).
        #  Eighth, always at least use a major and minor number for your
        #    version.
        #  Following these guidelines should give your package version
        #      identification success with any python packaging technology
        #      (where the term "technology" is used loosely).
        #  Here are the technical decisions:
        #  0) Files with no '-' or no '.' are rejected (and no dash beyond
        #     the wheel designations will also be rejected).  Also, files
        #     that do not match the accepted list of extensions will also
        #     be rejected.  If there are no dashes remaining after
        #     the package name is identified, this is also rejected.
        #  1) Files that only have a single dash (before or after the package
        #     name is identified).  Will be treated as the version
        #     string, first as a PEP-440 conformant version, then
        #     as a legacy version.  No further heuristics are applied.
        #  2) TODO: An effort is made to match a package name for a versioning
        #     scheme template, starting with the text to the last dash
        #     and working forward to the starting dash.  It is possible
        #     that some packages have the same package name prefix.
        #     The versioning scheme template will need to list all suffix
        #     packages that the scheme does not apply to.
        #     Upon matching a name, an attempt will be made to apply the
        #     provided template.  If the template fails, the processing
        #     will raise a ValueError
        #     The resulting version string from the template processing
        #     will first be tried as a PEP-440 conforming version
        #     then a LegacyVersion
        #  3) Everything in the filename from where the version is
        #     determined to start up to the start of the wheel designations
        #     (or extension for non-wheels)
        #     will be taken as part of the version (i.e., nothing will be
        #     treated as meaningless junk at the end).  Failing that approach
        #     the dashes will be ciphoned off if they conform to the PEP-427
        #     notion of a build number and tried again.
        #  4) Anything that could be interpreted as a (PEP-440 conformant)
        #     version (according to the packaging module) based on
        #     dashes and the location of the text within the filename
        #     will be treated as the version, working from the end
        #     of the string backwards.
        #     Character sequences that will be used to determine "versionness"
        #     back to front in the string.
        #     will be as follows in priority order (The version must comply
        #     with PEP-440 as encoded by the packaging module to be accepted):
        #     a) a '-[vV]?[0-9]+[.][0-9]+[.][0-9]+$' sequence
        #     b) a '-[vV]?[0-9]+[.][0-9]+[.][0-9]+-[0-9].*$' sequence
        #        i) First as a whole version (Tech decision #3)
        #       ii) Then as a version with a build tag
        #     c) a '-[vV]?[0-9]+[.][0-9]+$' sequence
        #     d) a '-[vV]?[0-9]+[.][0-9]+-[0-9].*$' sequence
        #        i) First as a whole version (Tech decision #3)
        #       ii) Then as a version with a build tag
        #     e) a '-[vV]?[0-9]+![0-9]' sequence (PEP-440 doesn't seem to lock
        #        down the actual format of the epoch, but says the default
        #        is to be considered '0' and only seems to accept [0-9]*)
        #     f) a '-[vV]?[0-9][0-9abrposte]*(.[0-9abrposte]+(.[0-9abrposte]+)?)?)[+][^+]+' sequence
        #        multiple +'s are not accepted
        #        by packaging's Version, and the guidance
        #        seems to be that use of local versions is superior to
        #        use of a build tag and it seems safe enough to assume
        #        that a build tag and a local version will not both be used
        #        i.e., the build tag will be treated as the local version end.
        #     g) a '-[vV][0-9]' sequence to the next dash
        #  5) Failure to match with technical decision #4,
        #     technical decision #3 is leveraged, starting with
        #     the assumption that no dashes are used in the package name
        #     If no PEP-440 version is yielded, the leading dash and sequence to
        #     the next dash is removed from consideration (added back to the
        #     package name) and the heuristic is applied again.
        #  6) Failure to match with technical decision #5 will return
        #     a LegacyVersion object with the contents based on the following
        #     heuristic in order:
        #     a) The last -v(.*) or -V(.*) found, stripping ( and )
        #        must be followed by nothing or -[0-9].* for a build tag
        #        Not Matching: mypackage-s-v(OU812)-vvv-8GES*E)GA.tar.gz
        #        Matching: mypackage-s-v(OU812)-8TTJ@#@(T@).tar.gz
        #          like: package: mypackage-s
        #                version: OU812
        #                build: 8TTJ@#@(T@)
        #     b) The last -v<anything> found, if a conformant build tag
        #        is found, it will be fingered as a build tag
        #        (This and c goes a bit against Technical Decision #2
        #         but a build number would never be yielded if an effort
        #         wasn't made to find one, dashes may not actually mean
        #         very much in versioning for pypi, but they mean
        #         something more than nothing...)
        #        Matching: mypackage-s-v(OU812)-vvv-8GES*E)GA.tar.gz
        #          like: package: mypackage-s
        #                version: (OU812)-vvv
        #                build: 8GES*E)GA
        #        Matching: mypackage-s-v(OU812)-vvv-GES*E.tar.gz
        #          like: package: mypackage-s
        #                version: (OU812)-vvv-GES*E
        #                build: None
        #     c) The next to last -[0-9].* found where the last dash conforms
        #        to a build tag via PEP-427.
        #     d) The last -.* found

        """Returns:
             {'package': <package (normalized)>,
              'filename': <filename>,
              'version': <packaging Version or LegacyVersion object>,
              'build': <PEP-427 build tag>,
              'platform': <system platform>,
              'python': <python platform>,
              'abi': <python abi required>,
              'ext': <extension>,
              'heuristic': <versioning heuristic by method name>,
              'fragment': <If the url has a # in it, we'll stash that here>}

           The algorithm is, essentially, to walk backwards through '.'s
           because the dots actually provide the context necessary
           to determine what the dashes may mean and we want an extension
           out of the deal too.  The extension will also clue us in
           on the meaning of the dashes.

           If a filename fails to parse, ValueError will be raised"""

        result = {
            'package':None,
            'filename':None,
            'version':None,
            'isWheel':False,
            'build': None,
            'python':None,
            'abi':None,
            'platform':None,
            'ext':None,
            'heuristic':None,
            'fragment':'' }

        self.log.devdebug("Initial package name: %s", packageName)
        if packageName is not None:
            packageName = self._normalizePackageName(packageName)
        self.log.devdebug("Normalized package name: %s", packageName)

        #Opening move - if there's no dots, dispatch the problem immediately
        #Deal with fragments:
        parts = filename.split('#',1)
        if len(parts) > 1:
            result['fragment'] = '#' + parts[1]
        result['filename'] = parts[0]
        filename = result['filename']
        if '.' not in filename:
            raise ValueError("'%s' has no extension", filename)

        if '-' not in filename:
            raise ValueError("'%s' has no version", filename)

        #Break the filename into dots first
        dotparts = filename.split('.')

        #Determine the extension and if we have a wheel.
        ext = '.%s' % dotparts.pop()
        if ext not in self.SUPPORTED_EXTENSIONS:
            ext = ".%s%s" % (dotparts.pop(), ext)
            if ext not in self.SUPPORTED_EXTENSIONS:
                raise ValueError("'%s' does not have a valid pypi archive extension", filename)
        result['ext'] = ext
        isWheel = ext in self.WHEEL_EXTENSIONS
        result['isWheel'] = isWheel

        #Now take the remaining dot parts back in and find -'s
        dashparts = '.'.join(dotparts).split('-')
        if isWheel:
            if len(dashparts) < 4:
                raise ValueError("'%s' does not have a valid wheel designation", filename)
            result['python'] = dashparts[-3]
            result['abi'] = dashparts[-2]
            result['platform'] = dashparts[-1]
            dashparts = dashparts[:-3]

        #Technical decision 1
        if len(dashparts) == 2:
            try:
                found = version.Version(dashparts[1])
                result['version'] = found
                result['heuristic'] = '1'
                result['package'] = dashparts[0]
                return result
            except version.InvalidVersion:
                pass

        if packageName is not None:
            #Stripping off the package will be helpful if we have it
            result['package'] = packageName
            numpossibledashes = packageName.count('-') + 1
            while numpossibledashes:
            	proposedPackage = self._normalizePackageName(
                	'-'.join(dashparts[:numpossibledashes]))
                if proposedPackage != packageName:
                    numpossibledashes = numpossibledashes - 1
                else:
                    dashparts = dashparts[numpossibledashes:]

                    #Technical decision 1
                    if len(dashparts) == 1:
                        try:
                            found = version.Version(dashparts[0])
                            result['version'] = found
                            result['heuristic'] = '1'
                            return result
                        except version.InvalidVersion:
                            pass
                    break
            else:
                raise ValueError("Package name given, '%s', did not match package '%s'" % (packageName, proposedPackage))

        #Start working down the list of heuristics till one works.
        heuristicDriver = PypiContext._SplitHeuristics(
            result, dashparts, filename, packageVersioningSchemes, self.log)
        heuristics = heuristicDriver.getHeuristics()
        for heuristic in heuristics:
            if heuristic():
                return result

        #  If none work, raise ValueError
        raise ValueError("The version for file '%s' could not be determined", filename)

    def __init__(self, contextInfo, controller):
        self.controller = controller
        self.previous = None
        self.constraints = {}
        self.indicies = []
        if 'previous' in contextInfo:
            self.previous = self.controller.getContext(contextInfo['previous'])
            if self.previous is not None:
                self.constraints = dict(self.previous.constraints)
                self.indicies = list(self.previous.indicies)
        self.name = contextInfo['name']
        self.log = self.controller.log
        self.updateContext(contextInfo)

    def updateContext(self, contextInfo):
        self.processMoreConstraints(contextInfo)
        self.processMoreIndexes(contextInfo)

    #Every separate constraint is a 'or' - if two or more constraints need
    # to be considered together, then use the comma operator (as is done with
    #  pip, PEP-440), To specify several separate 'or' constraints together
    #  in a single string use '|' ('||' for the c sensitive will also be
    #  accepted and also mean 'or' in the exact same way)
    #  != 1.4.1 | >= 1.3.1 will render != 1.4.1 ineffective
    #  >= 1.3.1, != 1.4.1 will allow any 1.3.1 except 1.4.1 as you
    #  may expect.
    #This will limit the visible versions to the client
    def processMoreConstraints(self, contextInfo):
        resetList  = []
        if 'reset' in contextInfo:
            resetList = ';'.join(contextInfo['reset'].split('\n')).split(';')

        if 'constraints' in contextInfo:
            constraints = ';'.join(contextInfo['constraints'].split('\n')).split(';')
            for constraint in constraints:
                constraint = constraint.strip()
                if len(constraint) == 0:
                    continue
                package, specifierString = self._splitReq(constraint)
                if not specifierString:
                    self.log.info("Skipping constraint '%s'", constraint)
                    continue
                ors = specifierString.split('|')
                if package not in self.constraints or package in resetList:
                    self.constraints[package] = []
                for orSpec in ors:
                    if len(orSpec) == 0:
                        continue
                    self.constraints[package].append(
                        specifiers.SpecifierSet(orSpec) )
                self.log.debug(
                    "Constraint for '%s' is now: %s",
                    package,
                    str(self.constraints[package]))

    #Expand the pypi server/indicies to read
    def processMoreIndexes(self, contextInfo):
        if 'indicies' in contextInfo:
            indicies = ','.join(contextInfo['indicies'].split('\n')).split(',')
            indicies = [ x.strip() for x in indicies ]
            self.indicies.extend(indicies)

    def _startStandardHTMLPage(self, pagename):
        page = StringIO.StringIO()
        page.write('<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">')
        page.write("<html>\n<title>csmake PyPI Proxy</title>\n")
        page.write("<body>\n<h2>csmake PyPI Proxy: %s</h2>\n" % pagename)
        return page

    def _sendStandardHTMLPage(self, page, handler):
        page.write("</body>\n</html>\n")
        length = page.tell()
        page.seek(0)
        handler.send_response(200)
        handler.send_header("Content-type", "text/html")
        handler.send_header("Content-Length", str(length))
        handler.end_headers()
        shutil.copyfileobj(page, handler.wfile)
        page.close()

    def _isaBacklink(self, url, link):
        rellink = os.path.relpath(urlparse.urljoin(url,link),url)
        self.log.devdebug("'%s' is the relative path", rellink)
        self.log.devdebug("'%s' url - '%s' link", url, link)
        self.log.devdebug("url: %s", url)
        self.log.devdebug("link: %s", link)
        while rellink.startswith('..'):
            rellink = rellink.lstrip('..').lstrip('/')
        if len(rellink) == 0:
            self.log.devdebug("'%s' was a backlink", link)
            return True
        return False

    def listPackages(self, handler):
        packageCache, services = self.controller.getPypiImage()
        threads = []
        for index in self.indicies:
            if index not in services:
                services[index] = [False,{}]
            if not services[index][0]:
                linksThread = PullLinksThread(index, None, self.log)
                linksThread.start()
                threads.append(linksThread)
        for thread in threads:
            thread.join()
            try:
                self.controller.lockPackageList()
                index = thread.getIndex()
                try:
                    url, links = thread.getLinks()
                except:
                    self.log.exception("Pulling index '%s' failed", index)
                    continue
                services[index][0] = True
                for link in links:
                    targetlink = link[0]
                    if not targetlink.endswith('/'):
                        self.log.devdebug("'%s' is not a directory", targetlink)
                        continue
                    if self._isaBacklink(url, targetlink):
                        continue
                    if targetlink[-1] == '/':
                        targetlink = targetlink[:-1]
                    pathto, origpackage = os.path.split(targetlink)
                    package = self._normalizePackageName(origpackage)
                    self.log.devdebug("Adding package to image: %s", package)
                    if package not in services[index][1]:
                        services[index][1][package] = [False, targetlink]
                    else:
                        services[index][1][package][1] = targetlink
                    if package not in packageCache:
                        packageCache[package] = ({},{})
            finally:
                self.controller.unlockPackageList()
        page = self._startStandardHTMLPage(
            'Available packages in context: %s' % self.name)
        for package in packageCache.keys():
            page.write('<p><a href="%s/">%s</a></p>\n' % (package, package))
        self._sendStandardHTMLPage(page, handler)
        return True

    #Called by PullLinksThread if the pull fails
    def _onVersionPullLinksFailed(self, package, index, services, plt):
        self.log.devdebug("Pull of version failed for '%s' for index '%s'", package, index)
        self.listPackages(PypiContext.NullHTTPHandler())
        result = services[index][1][package][1]
        self.log.devdebug("After pulling all package list for index '%s': %s", index, str(result))
        if result is not None:
            return (index, (result,))
        else:
            self.log.devdebug("Package '%s' was not anywhere in the image: %s" % (package, str(services[index][1])))
            return (None, None)

    def listVersions(self, package, handler):
        #TODO: Limit availability of package versions if no active indicies
        #      appear in the list for the version

        origpackage = package
        package = self._normalizePackageName(package)
        packageCache, services = self.controller.getPypiImage()


        results = []
        threads = []
        for index in self.indicies:
            self.log.devdebug("Processing index '%s'", index)
            if index not in services:
                services[index] = [False,{}]
            self.controller.lockPackageList()
            if package not in services[index][1]:
                services[index][1][package] = [False, None]
            self.controller.unlockPackageList()
            hadlink = False

            try:
                self.controller.lockPackageList()
                if not services[index][1][package][0]:
                    link = services[index][1][package][1]
                    if link is None:
                        link = (origpackage, package)
                    else:
                        link = (link,)
                    self.log.devdebug("Pulling '%s' for package '%s'", link, origpackage)
                    linksThread = PullLinksThread(
                        index,
                        link,
                        self.log,
                        functools.partial(
                           self._onVersionPullLinksFailed,
                           package,
                           index,
                           services))
                    linksThread.start()
                    threads.append(linksThread)
                else:
                    self.log.devdebug("Package '%s' is already in index '%s'", package, index)
            finally:
                self.controller.unlockPackageList()
        for thread in threads:
            thread.join()
            index = thread.getIndex()
            try:
                url, links = thread.getLinks()
            except HTTPError as httpe:
                if httpe.code == 404:
                    self.log.debug(
                        "(NON-FAILURE) Links '%s' don't exist in index '%s'",
                        str(thread.getPaths()),
                        thread.getIndex() )
                else:
                    self.log.exception(
                        "Pulling index '%s' with paths '%s' failed",
                        thread.getIndex(),
                        str(thread.getPaths()) )
                continue
            except:
                self.log.exception(
                    "Pulling index '%s' with paths '%s' failed",
                    thread.getIndex(),
                    str(thread.getPaths()))
                continue
            self.controller.lockPackageList()
            services[index][1][package] = [True,url]
            self.controller.unlockPackageList()
            if package not in packageCache:
                packageCache[package] = ({},{})
            for link in links:
                if self._isaBacklink(url, link[0]):
                    continue
                if link[0][-1] == '/':
                    self.log.devdebug("'%s' is not a file - skipping", link[0])
                    continue
                path, filename = os.path.split(link[0])
                try:
                    filesplit = self._splitPypiName(
                        filename,
                        {}, #TODO: Add custom version schemes
                        package )
                except ValueError as e:
                    self.log.devdebug(
                        "link '%s' couldn't be versioned: %s", link[0], str(e))
                    continue

                if self._normalizePackageName(filesplit['package']) != package:
                    self.log.warning(
                        "package '%s' does not match package from file '%s': %s",
                        package,
                        link[0],
                        filesplit['package'] )
                self.log.devdebug("split version results for: %s", link[0])
                self.log.devdebug("   %s", str(filesplit))
                version = filesplit['version']

                #If the link is not relative, the link's full path will
                # be left unchanged.  If it is relative, it will properly
                # follow the url/html-ish relative href rules.
                #...annoying, we're carrying around the link and the filename
                #so we have to find and split out any fragment here as well
                linkpart = link[0].split('#')[0]
                abspart = ''
                parsed = urlparse.urlsplit(linkpart)
                if len(parsed.scheme) > 0:
                    linkparts = linkpart.split('/',3)
                    linkpart = linkparts[-1]
                    abspart = '/'.join(linkparts[:-1])
                fulllink = urlparse.urljoin(
                    url,
                    abspart + '/' + urllib2.quote(linkpart) )

                if filesplit['filename'] not in packageCache[package][0]:
                    packageCache[package][0][filesplit['filename']] = [
                        False,
                        [],
                        filesplit
                    ]
                packageCache[package][0][filesplit['filename']][1].append(fulllink)
                if version not in packageCache[package][1]:
                    packageCache[package][1][version] = {}
                if filesplit['filename'] not in packageCache[package][1][version]:
                    packageCache[package][1][version][filesplit['filename']] = [
                        [],
                        filesplit ]
                packageCache[package][1][version][filesplit['filename']][0].append(fulllink)

        if package not in packageCache:
            handler.send_error(404, "%s: Not Found" % package)
            return False

        #Filter all versions down to current context specification
        page = self._startStandardHTMLPage(
            'Files available for "%s" in context: %s' % (
                package,
                self.name ) )
        versions = packageCache[package][1].keys()
        self.log.devdebug(
            "Current constraints: %s", str(self.constraints))
        if package in self.constraints:
            versionset = []
            pkglimits = self.constraints[package]
            for constraint in pkglimits:
                versionset.extend(constraint.filter(versions))
            versions = list(set(versionset))
            self.log.devdebug(
                "Package: %s  &&  Versions: %s  &&  Constraints: %s",
                package,
                str(versions),
                str(pkglimits) )
        for version in versions:
            for filename, entry in packageCache[package][1][version].iteritems():
                page.write('<p><a href="%s%s">%s</a></p>\n' % (
                    urllib2.quote(filename),
                    entry[1]['fragment'],
                    filename))
        self._sendStandardHTMLPage(page, handler)
        return True

    def getPackage(self, package, filename, handler):
        #TODO: Limit availability of package if no active indicies
        #      appear in the list for the file
        package = self._normalizePackageName(package)
        filename = urllib2.unquote(filename)
        packageCache, services = self.controller.getPypiImage()
        listVersionsCalled = False
        if package not in packageCache:
            listVersionsCalled = True
            self.listVersions(package, PypiContext.NullHTTPHandler())
        if package not in packageCache:
            raise ValueError("Package %s is not available" % package)
        if filename not in packageCache[package][0]:
            if not listVersionsCalled:
                self.listVersions(package, PypiContext.NullHTTPHandler())
                listVersionsCalled = True
        if filename not in packageCache[package][0]:
            #Hack for old pip versions
            for cachedFile in packageCache[package][0]:
                if filename in cachedFile:
                    filename = cachedFile
                    break
            else:
                raise ValueError('Filename %s is not available' % filename)
        fileGetInfo = packageCache[package][0][filename]
        filepath = fileGetInfo[0]
        CHUNKSIZE = 102400
        if filepath:
            self.log.devdebug("Attempting to pull file from cache: %s", filepath)
            try:
                with open(filepath) as readfd:
                    readfd.seek(0,2)
                    length = readfd.tell()
                    readfd.seek(0)
                    handler.send_response(200)
                    handler.send_header('Content-type', 'application/octet-stream')
                    handler.send_header('Content-length', length)
                    handler.end_headers()
                    self.log.devdebug("length: %d", length)
                    writefd = handler.wfile
                    while True:
                        buf = readfd.read(CHUNKSIZE)
                        if len(buf) == 0:
                            break
                        writefd.write(buf)
                return True
            except:
                self.log.exception("Attempt to read cache failed, proceeding to pull the file")
                fileGetInfo[0] = False

        #Pull the file from the server and write it out
        pathsToTry = fileGetInfo[1]

        #  If one fails, try the next one.
        #TODO: The more indicies available
        #  the faster we should get bored waiting...the curve of timeout
        #  increase should be reasonably exponential up to a fixed time
        #  E.g., tout = MAXTIMEOUT/(2^len(pathsToTry))  ...
        #        loop
        #            if stuff failed then tout *= 2
        #TODO: After a fixed period of time, start the next transfer
        #      and compare the two, calculate the landing times
        #      for both transfers if it were an higher than average sized
        #      pypi file and take the one that would land faster if it's
        #      >20% - wait for the second transfer to catch where the
        #      first one left off.
        #
        #There's no good rhyme or reason to the order.  So shuffle it
        #  This will change the actual cache directory - that's actually ok :)
        random.shuffle(pathsToTry)
        cachepath = self.controller.getCachePath()

        CHUNKSIZE = 10240

        success = False
        for path in pathsToTry:
            cachefd = None
            cachefilepath = None
            try:
                try:
                    if cachepath is not None:
                        cachepackagepath = os.path.join(
                            cachepath,
                            package )
                        if not os.path.exists(cachepackagepath):
                            os.makedirs(cachepackagepath)
                        cachefilepath = os.path.join(
                            cachepackagepath,
                            filename )
                        cachefd = open(cachefilepath, 'w')
                except:
                    self.log.exception("Attempt to use cache at %s, failed", cachepath)
                    cachefilepath = None
                try:
                    netfd = urllib2.urlopen(path)
                    netinfo = netfd.info()
                    handler.send_response(200)
                    handler.send_header("Content-type", netinfo.gettype())
                    length = netinfo.getheader("Content-length")
                    if length is not None:
                        handler.send_header("Content-length", length)
                    handler.end_headers()
                    while True:
                        buf = netfd.read(CHUNKSIZE)
                        if not buf:
                            break
                        if cachefd is not None:
                            cachefd.write(buf)
                        handler.wfile.write(buf)
                    success = True
                    break
                except Exception as e:
                    if hasattr(e, "errno"):
                        if e.errno == 32 or e.errno == 104:
                            self.log.warning("Client ended communication early and the socket pipe was broken")
                            #Prevent wfile from flushing
                            if handler.wfile is not None:
                                handler.wfile._wbuf = None
                            return None
                    self.log.debug("Exception: %s", e.__class__.__name__)
                    self.log.exception("Attempt to read %s failed", path)
            finally:
                if cachefd is not None:
                    try:
                        cachefd.close()
                    except:
                        pass
                    cachefd = None
                    if success:
                        if cachefilepath is not None:
                            fileGetInfo[0] = cachefilepath
                    else:
                        try:
                            os.remove(cachefilepath)
                        except Exception as e:
                            self.log.info("Attempt to remove a failed cached file '%s' failed:%s", cachefilepath, str(e))
        else:
            raise ValueError(
                "The cache, nor any index could produce '%s'" % filename )
        return cachefilepath

    def parsePath(self, path, handler):
        if len(path) == 0:
            raise ValueError("Root path is invalid")
        if path[0] == '/':
            path = path[1:]
        pathparts = path.split('/')
        if len(pathparts) == 1:
            return self.listPackages(handler)
        if len(pathparts) == 2:
            return self.listVersions(pathparts[1], handler)
        if len(pathparts) == 3:
            return self.getPackage(pathparts[1], pathparts[2], handler)
        raise ValueError(
            "The path '%s' is invalid" % path)


class HideDistUtilsFile(CsmakeServiceConfig):
    def ensure(self):
        self._backupAndSetup(
            self.path,
            setup = False )
        CsmakeServiceConfig.ensure(self)

    def update(self):
        pass

class HidePipFile(CsmakeServiceConfig):
    def ensure(self):
        self._backupAndSetup(
            self.path,
            setup = False )
        CsmakeServiceConfig.ensure(self)

    def update(self):
        pass

class FauxCertBundleTargetDirectory(CsmakeServiceConfig):
    def ensure(self):
        self._backupAndSetup(
            os.path.join(
                self.path,
                SSLCertificateManager.FAUX_CERT_DIR,
                "README" ) )

        CsmakeServiceConfig.ensure(self)

    def writefile(self, fobj):
        fobj.write("This is a temporary directory for the purpose of supporting the PypiFacade")

class PypiController:
    """The controller's job is to make sense of requests and provides
       a control for clients to adjust package version availability.
       The controller accepts requests for paths of the form:
           <context> - list available packages in the given context
           <context>/<package> - list available versions in the given context
           <context>/<package>/<filename> - retrieve a specific package"""

    #So...the surest way to control pip and setuptools together
    #  is to control the user configuration because of
    #  virtual environments and the fact that setuptools doesn't
    #  doesn't have a way to control its behavior via environment
    #  variables.  Since we don't know for sure what user will be
    #  active when pip is invoked, we'll just do them all, plus
    #  create a home directory for the current user.
    #  Also, create backup files to restore if something's there.
    HOMES_TO_GROCK=['/root', '/home/*']

    def __init__(self, configManager, log, options):

        self.configManager = configManager
        self.log = log

        self.initialConstraints = None
        self.imagePackageLock = threading.RLock()

        log.devdebug("Options: %s", str(options))

        #Structure is proxyPypiImage[package] a tuple == (
        #      { <filename>: [<cache>, [<image locations>], <split record>]}
        #      { <version>:  {<filename> :
        #                           [<image locations>], <split record>]}} )
        #  The structure represents an overlay of all possible service paths
        #  The context instance will filter out any packages or versions not
        #  available to the context to ensure a context has an offering
        #  consistent with its active indexes.
        self.proxyPypiImage={}

        #Structure is serviceStatus[index] ==
        #    [<index pulled>, {<package> : [<version index pulled>, <path-to>]}]
        self.serviceStatus={}

        #Structure is packageVersioningSchemes[package] =
        #           <re fingering package name part, and version part>
        #    e.g.:
        #     r'(?P<package>mypackage).[-a-zA-Z0-9]+[-][-](?P<version>[0-9]+)'
        self.packageVersioningSchemes = {}

        self.log = log
        initialContext = None
        self.pipTimeout = "45" #default to 45 seconds.
        if 'timeout' in options:
            self.pipTimeout = options['timeout']
        self.defaultcontext='simple'
        if 'default-context' in options:
            self.defaultcontext=options['default-context']
        if 'constraining-indicies' in options:
            #We need to control the first pull to get
            #  the initial constraints from the repository
            #It may be desireable to pull this out so it can be
            #  done post-initialization...one of the side effects
            #  of doing this in post-initialization is that all the
            #  work will either need to be lost, or carefully
            #  integrated into the image and service statuses
            initialContext = PypiContext(
                {'indicies':options['constraining-indicies'],
                 'name':self.defaultcontext},
                self )
            nullhandler = PypiContext.NullHTTPHandler()
            initialContext.listPackages(nullhandler)
            #TODO: Speed this up dramatically with threading
            #      Need to make listVersions threadsafe first.
            newPackages = self.proxyPypiImage.keys()
            numPackages = len(newPackages)
            packagesCompleted = 0
            for package in newPackages:
                initialContext.listVersions(package, nullhandler)
                packagesCompleted += 1
                if packagesCompleted % 10 == 0:
                    self.log.info(
                        "Package init %s/%s completed",
                        packagesCompleted,
                        numPackages )
            constraintList=[]
            for package, image in self.proxyPypiImage.iteritems():
                versions = [str(x) for x in image[1].keys()]
                if len(versions) == 0:
                    continue
                constraintList.append("%s==%s" % (
                    package,
                    '|=='.join(versions)))
            self.log.debug("Initial Constraints: %s", str(constraintList))
            self.initialConstraints = constraintList

            initialContext.processMoreConstraints({
                'constraints': ';'.join(constraintList) })

        if initialContext is None:
            options['name'] = self.defaultcontext
            initialContext = PypiContext(options, self)
        else:
            initialContext.processMoreConstraints(options)
            initialContext.processMoreIndexes(options)

        self.cache = None
        if 'cache' in options:
            self.cache = options['cache']

            #Check to see if the cache exists
            if not os.path.exists(self.cache):
                os.makedirs(self.cache)
            else:
               #It exists - let's load the state into the pypi image
               self.log.info("Reading cache from: %s", self.cache)
               for package in os.listdir(self.cache):
                   package = initialContext._normalizePackageName(package)
                   packagepath = os.path.join(self.cache, package)
                   if os.path.isdir(packagepath):
                       if package not in self.proxyPypiImage:
                           self.proxyPypiImage[package] = ({}, {})
                       files = self.proxyPypiImage[package][0]
                       versions = self.proxyPypiImage[package][1]
                       for filename in os.listdir(packagepath):
                           try:
                               filesplit = initialContext._splitPypiName(
                                   filename,
                                   {},
                                   package )
                               if filesplit is None:
                                   raise ValueError(
                                       "Filename could not be split")
                           except ValueError:
                               self.log.error(
                                   "Non placable file for package '%s' in cache: %s",
                                   package,
                                   filename )
                               continue
                           if filename not in files:
                               files[filename] = [None, [], None]
                           if package != filesplit['package']:
                               self.log.warning(
                                   "Package name '%s' from cache != '%s' from filename: %s",
                                   package,
                                   filesplit['package'],
                                   filename )
                               self.log.warning(
                                   "   This may indicate a problem with the version id code or the cache" )
                           files[filename][0] = os.path.join(
                               self.cache,
                               package,
                               filename )
                           files[filename][2] = filesplit
                           version = filesplit['version']
                           if version not in versions:
                               versions[version] = {}
                           if filename not in versions[version]:
                               versions[version][filename] = [[], filesplit]

        self.contexts = {self.defaultcontext:initialContext}
        self.currentcontext = [self.defaultcontext]
        self.chroot = options['chroot']
        if self.chroot is None:
            self.chroot = '/'
        self.interface = options['interfaces'][0]
        self.port = options['port']
        self.executing = True

        class PipConfigureFile(CsmakeServiceConfig):

            def ensure(innerself):
                innerself._backupAndSetup(
                    os.path.join(
                        innerself.path,
                        ".config/pip/pip.conf" ))
                innerself._backupAndSetup(
                    os.path.join(
                        innerself.path,
                        '.pip/pip.conf' ),
                    setup = False )
                CsmakeServiceConfig.ensure(innerself)

            def writefile(innerself, fobj):
                #Write out the desired config
                extraLines = []
                certManager = innerself.manager.getDaemon().getCertificateManager()
                if len(certManager.certbundles()) <= 0:
                    self.log.error("There were no CA bundles to reference to install our temporary root CA")
                    if len(certManager.certfiles()) <= 0:
                        self.log.error("There were no CA files to reference, going to set trusted server")
                        part = 'localhost'
                        try:
                            part = self.getCurrentUrl().split('/')[2]
                            part = part.split(':')[0]
                        except:
                            self.log.warning("Cert installations all failed and cant even get the right url for trusted-host - using localhost, but something's probably really wrong here")
                            part = 'localhost'
                        extraLines.append('trusted-host=%s\n' % part)

                    else:
                        extraLines.append('cert=/%s\n' % os.path.relpath(certManager.certfiles()[0], self.chroot))
                else:
                    extraLines.append('cert=/%s\n' % os.path.relpath(certManager.certbundles()[0], self.chroot))
                fobj.write("""[global]
index-url=%s
verbose=true
timeout=%s
""" % (self.getCurrentUrl(),
       self.pipTimeout))
                for line in extraLines:
                    fobj.write(line)

        class DistUtilsConfigureFile(CsmakeServiceConfig):
            def ensure(innerself):
                innerself._backupAndSetup(
                    os.path.join(innerself.path, ".pydistutils.cfg") )
                CsmakeServiceConfig.ensure(innerself)

            def writefile(innerself, fobj):
                fobj.write("""[easy_install]
index-url=%s
""" % self.getCurrentUrl())

        self.DistUtilsConfigureFile = DistUtilsConfigureFile
        self.PipConfigureFile = PipConfigureFile

        self.configManager.register(
            DistUtilsConfigureFile,
            self.HOMES_TO_GROCK,
            ensure=False )

        self.configManager.register(
            PipConfigureFile,
            self.HOMES_TO_GROCK,
            ensure=False )

    def getPypiImage(self):
        return (self.proxyPypiImage, self.serviceStatus)

    def lockPackageList(self):
        self.imagePackageLock.acquire()

    def unlockPackageList(self):
        self.imagePackageLock.release()

    def getInitialConstraints(self):
        return self.initialConstraints

    def getCurrentUrl(self):
        return "%s/%s" % (
            "https://%s:%s" % self.port.address(),
            self.getCurrentContext())

    def shutdown(self):
        self.executing = False

    def getCachePath(self):
        return self.cache

    def registerContext(self, path, context):
        if path in self.contexts:
            result = self.contexts[path].updateContext(context)
        else:
            context['name'] = path
            result = PypiContext(context, self)
            self.contexts[path] = result

    def unregisterContext(self, path):
        if path in self.currentcontext:
            self.log.error("The context '%s' is currently on the stack", path)
            return False
        try:
            del self.contexts[path]
        except:
            pass
        return True

    def getContext(self, path):
        if path in self.contexts:
            return self.contexts[path]
        else:
            return None

    def getCurrentContext(self):
        return self.currentcontext[-1]

    def pushCurrentContext(self, path):
        if self.currentcontext[-1] == path:
            self.log.info("Attempt to push '%s' succeeded because it was already pushed on top", path)
            return True
        if path in self.currentcontext and self.currentcontext[-1] != path:
            self.log.warning("The context '%s' was already on the stack", path)
            self.log.warning("   Moving context back instead of pushing")
            self.popCurrentContext(path)
            self.pushCurrentContext(path)
        self.currentcontext.append(path)
        self.configManager.update(self.PipConfigureFile)
        self.configManager.update(self.DistUtilsConfigureFile)
        return True

    def popCurrentContext(self, path):
        if self.defaultcontext == path:
            self.log.error('The default context cannot be removed')
            self.currentcontext = [self.defaultcontext]
            self.configManager.update(self.PipConfigureFile)
            self.configManager.update(self.DistUtilsConfigureFile)
            return False
        try:
            index = self.currentcontext.index(path)
            self.currentcontext = self.currentcontext[:index]
            self.configManager.update(self.PipConfigureFile)
            self.configManager.update(self.DistUtilsConfigureFile)
            return True
        except ValueError:
            self.log.warning("The context '%s' was not on the stack", path)
            self.log.warning("   The context will return to '%s'", self.defaultcontext)
            self.currentcontext = [self.defaultcontext]
            self.configManager.update(self.PipConfigureFile)
            self.configManager.update(self.DistUtilsConfigureFile)
            return False

    def setDefaultContext(self, path):
        self.currentcontext = [self.defaultcontext]
        self.configManager.update(self.PipConfigureFile)
        self.configManager.update(self.DistUtilsConfigureFile)

    def doRequestedPath(self, path, handler):
        #The format of a request to the proxy server shall be:
        #  http(s)://proxyaddr:port/context/package/filename
        #  The default context shall be 'simple'
        #  A request where a context is undefined will default to simple
        if path.endswith('/'):
            path = path[:-1]
        originalPath = path
        if path.strip('/') in self.contexts:
            return self.contexts[path.strip('/')].listPackages(handler)
        path, target = os.path.split(path)
        if path.strip('/') in self.contexts:
            return self.contexts[path.strip('/')].listVersions(target, handler)
        path, package = os.path.split(path)
        if path.strip('/') in self.contexts:
            return self.contexts[path.strip('/')].getPackage(package, target, handler)
        self.log.warning(
           "Path given was '%s' but did not match an active context",
           originalPath)
        current = self.getCurrentContext()
        self.log.warning(
            "    defaulting to '%s' which is the current context", current)
        return self.getContext(current).parsePath(originalPath, handler)

class PypiProxyThread(threading.Thread, SimpleHTTPRequestHandler):
    """Handles a single connection"""
    def __init__(self, conn, addr, service):
        threading.Thread.__init__(self)
        try:
            service.log.devdebug("trying __init__")
            self.conn = conn
            self.addr = addr
            self.service = service
            service.log.devdebug("__init__ calling getController")
            self.controller = service.getController()
            service.log.devdebug("__init__ completed")
        except Exception as e:
            service.log.exception("__init__ failed")
            raise e

    def run(self):
        #__init__ will process the request and return the result
        self.service.log.devdebug("run called")
        SimpleHTTPRequestHandler.__init__(self, self.conn, self.addr, None)

    def do_GET(self):
        try:
            self.service.log.devdebug("do_GET called")
            if self.path == "/xyzzy/xzyyzl33t/...shuttingdownthefacade...":
                self.service.log.info("Service shutdown requested")
                self.send_error(503, "Service shutting down")
                return
            try:
                answer = self.controller.doRequestedPath(self.path, self)
            except ValueError:
                self.service.log.exception("Proxy request was not valid")
                self.send_error(404, "File not found")
        except Exception as e:
            #SimpleHTTPRequestHandler eats exceptions silently...not helpful...
            self.service.log.exception("Proxy request failed")
            self.send_error(500, "Internal Server Error on Pypi Proxy Facade: %s" % str(e))

    def do_POST(self):
        self.send_error(405, "The facade does not accept POST")

    def do_PUT(self):
        self.send_error(405, "The facade does not accept PUT")

    def do_DELETE(self):
        self.send_error(405, "The facade does not accept DELETE")

class SSLCertificateDirectoryConfig(CsmakeServiceConfig):
    def ensure(self):
        certManager = self.manager.getDaemon().getCertificateManager()
        self.certPath = certManager.getCARootPath()
        self.certPathDir, self.certPathName = os.path.split(self.certPath)
        self.certInsertPath = os.path.join(
            self.fullpath,
            self.certPathName)
        self._backupAndSetup(
            self.certInsertPath,
            in_chroot=False)
        self.manager.shellout(
            subprocess.check_call,
            ['cp', self.certPath, self.certInsertPath],
            False )
        certManager.addCertFile(self.certInsertPath)

    def update(self):
        pass

class SSLCertificateBundleConfig(CsmakeServiceConfig):
    def ensure(self):
        certManager = self.manager.getDaemon().getCertificateManager()
        self._backupAndSetup(
            self.path,
            moveOriginal=False,
            restoreInPlace=True )

        self.log.info("Adding CA Root cert to %s" % self.fullpath)
        tempname = "___csmake-pypi-cert.temp"
        result = subprocess.call(
            [ 'cat %s %s > %s' % (
                certManager.getCARootPath(),
                self.fullpath,
                tempname ) ],
            shell=True,
            executable="/bin/bash",
            stdout=self.log.out(),
            stderr=self.log.err() )
        try:
            if result != 0:
                self.log.error(
                    "Adding cert to %s caused return of %d",
                    self.fullpath,
                    result )

            result = self.manager.shellout(
                subprocess.call,
                ['mv', tempname, self.fullpath],
                False)
            if result != 0:
                self.log.error("Pushing the new certificate bundle, failed with code: %d", result)
                raise RuntimeError("Couldn't push a certificate bundle")
            certManager.addBundle(self.fullpath)
        except Exception as e:
            self.log.exception("Adding root cert failed")
            #raise e
            raise
        finally:
            try:
                os.remove(tempname)
            except:
                pass

    def update(self):
        pass

    def restore(self, bundle, in_chroot):
        certManager = self.manager.getDaemon().getCertificateManager()
        #chrootbundle = bundle
        #if in_chroot and self.chroot is not None:
        #    chrootbundle = self.chroot + bundle
        #certManager.removeBundle(chrootbundle)
        chrootbundle = self.fullpath
        certManager.removeBundle(self.fullpath)
        with open(certManager.getCARootPath()) as cert:
            with open(chrootbundle) as bundlefd:
                certlines = cert.readlines()
                actualcert = []
                found = False
                current = 0
                while not found:
                    found = '-----BEGIN CERTIFICATE-----' == certlines[current].strip()
                    current = current + 1
                start = current
                found = False
                current = -1
                while not found:
                    found = '-----END CERTIFICATE-----' == certlines[current].strip()
                    current = current - 1
                end = current
                actualcert = certlines[start:end]
                bundlelines = bundlefd.readlines()
        current = 0
        keepgoing = True
        found = False
        while keepgoing:
            try:
                index = bundlelines[current:].index(actualcert[0])
            except ValueError:
                keepgoing = False
                break
            for i, actual in enumerate(actualcert):
                if bundlelines[index+i] != actual:
                    current = index+len(actualcert)
                    continue
            found = True
            del bundlelines[index-1:index+len(actualcert)+2]
        if found:
            tempbundle = "___csmake-pypi-bundle-del-cert.temp"
            with open(tempbundle, 'w') as bundlefd:
                bundlefd.writelines(bundlelines)
            try:
                result = self.manager.shellout(
                    subprocess.call,
                    ['cp', tempbundle, chrootbundle],
                    False)
                if result != 0:
                    self.log.warning("Could not remove csmake cert from bundle")
            finally:
                try:
                    os.remove(tempbundle)
                except:
                    pass
        #The custom clean up was successful
        return True

class PypiServiceConfigManager(CsmakeServiceConfigManager):
    def __init__(self, module, daemon, cwd=None, options={}):
        CsmakeServiceConfigManager.__init__(self, module, daemon, cwd, options)
        self.currentHome = None

    def ensure(self):
        currentHome = os.path.expanduser('~')[1:]
        mybaseroot = '/'
        if self.chroot is not None:
            mybaseroot = self.chroot
        fullHome = os.path.join(
            mybaseroot,
            currentHome )
        try:
            try:
                #Eat the output (cheater way)
                self.shellout(
                    subprocess.check_output,
                    ['stat', '-c' , '', fullHome ],
                    in_chroot=False,
                    quiet_check=True )
                result = 0
            except:
                result = 1
            if result == 0:
                self.log.devdebug("The user home exists: %s", fullHome)
            else:
                self.log.devdebug("The user home does not exist, creating %s", fullHome)
                self.shellout(
                    subprocess.check_call,
                    ['mkdir', '-p', fullHome ],
                    in_chroot=False )
                self.currentHome = fullHome
        except:
            self.log.exception("Attempt to create home directory '%s' failed", currentHome)
            self.log.warning("The facade may not have completely contained pip")

        CsmakeServiceConfigManager.ensure(self)

    def clean(self):
        CsmakeServiceConfigManager.clean(self)
        if self.currentHome is not None:
            try:
                self.shellout(
                    subprocess.check_output,
                    ['rmdir', '-p', self.currentHome],
                    in_chroot = False,
                    quiet_check=True )
            except Exception as e:
                self.log.devdebug(
                    "The user home '%s' could not be fully deleted (this may be ok) %s: %s",
                    self.currentHome,
                    e.__class__.__name__,
                    str(e))

class PypiService(CsmakeServiceDaemon):
    def __init__(self, module, provider, options):
        CsmakeServiceDaemon.__init__(self, module, provider, options)
        self.certManager = provider.getCertificateManager()
        self.configManagerClass = PypiServiceConfigManager
        self.controller = None
        self.listenerraw = None
        self.listener = None
        self.interfaces = options['interfaces']
        self.accepting = False
        ciphers = subprocess.check_output(
            ['openssl', 'ciphers'])
        self.ciphers = ciphers.strip()
        #options['cabundle'] = clazz.certhandler.certbundles()[0]

    def getController(self):
        return self.controller

    def getCertificateManager(self):
        return self.certManager

    def _setupConfigs(self):
        self.configManager.register(
            FauxCertBundleTargetDirectory,
            ['/'],
            ensure=True )

        #Setup the SSL config management
        if not self.options['no-certroot']:
            self.configManager.register(
                SSLCertificateDirectoryConfig,
                SSLCertificateManager.CERT_DIRS,
                ensure=False)
            self.configManager.register(
                SSLCertificateBundleConfig,
                SSLCertificateManager.CERT_PATHS,
                ensure=True)

        self.controller = PypiController(self.configManager, self.log, self.options)
        #Setup hiding global distutils and pip configurations
        #TODO: Handle XDG_CONFIG_DIRS
        self.configManager.register(
            HidePipFile,
            ['/etc/pip.conf'],
            ensure=False )
        self.configManager.register(
            HideDistUtilsFile,
            ['/usr/lib/python*/distutils/distutils.cfg'],
            ensure=False )

        #Handle venvs
        venvsslpaths = []
        venvpippaths = []
        venvdistpaths = []
        for venv in self.options['venvs']:
            venvsslpaths.extend(
                [os.path.join(venv,x) for x in SSLCertificateManager.VENV_CERT_PATHS])
            venvpippaths.append(os.path.join(venv,"pip.conf"))
            venvdistpaths.append(os.path.join(venv,"distutils/distutils.cfg"))
        self.configManager.register(
            SSLCertificateBundleConfig,
            venvsslpaths,
            ensure=False)
        self.configManager.register(
            HidePipFile,
            venvpippaths,
            ensure=False)
        self.configManager.register(
            HideDistUtilsFile,
            venvdistpaths,
            ensure=False)

        CsmakeServiceDaemon._setupConfigs(self)

    def _startListening(self):
        self.listener = self.port.sock
        #self.port.lock()
        #self.port.unbind()
        #self.listenerraw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #self.listenerraw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        #self.listener = ssl.wrap_socket(
            #self.listenerraw,
            ##ssl_version=ssl.PROTOCOL_TLSv1_2,
            #ssl_version=ssl.PROTOCOL_SSLv23,
            #server_side=True,
            #ciphers=self.ciphers,
            #certfile=self.certManager.getCertPath(),
            #keyfile=self.certManager.getCertKeyPath() )
        ##Use the first interface in the list for now
        #address = self.port.address()
        #self.log.debug("Attepting to bind %s:%s", address[0], address[1])
        #self.listener.bind(address)
        #self.port.unlock()
        self.listener.listen(100)
        self.log.info("Pypi Facade listening on %s:%d", self.port.interface, self.port.port)

    def _listeningLoop(self):
        while not self.stopListening:
            try:
                self.accepting = True
                conn, addr = self.listener.accept()
                self.accepting = False
                self.log.devdebug("Connection accepted: %s:%d", conn, addr)
                handler = PypiProxyThread(conn,addr,self)
                self.log.devdebug("Starting handler for connection")
                handler.start()
            except ssl.SSLError as sslerr:
                if self.stopListening:
                    self.log.debug("An exception occurred with SSL during shutdown, this can be because the self-signed root CA was removed from the authority before the facade socket was completely closed: (%s)", str(sslerr))
                else:
                    self.log.exception("An ssl error occurred")
                    self.certManager.prettyPrintDevDebug()
            except Exception as e:
                self.log.exception("The handler for the request failed to start")

    def _cleanup(self):
        try:
            self.log.info("Attempting to shutdown socket")
            self.listener.shutdown(socket.SHUT_RDWR)
        except:
            self.log.info("shutdown of pypi facade listener failed")
        try:
            self.log.info("Attempting to close socket")
            self.listener.close()
        except:
            self.log.info("close of pypi facade listener failed")

    def stop(self):
        CsmakeServiceDaemon.stop(self)
        if self.controller is not None:
            self.controller.shutdown()
        #Force awake the connection to shut down
        address = self.port.address()
        if self.accepting:
            try:
                urllib2.urlopen(
                    "https://%s:%s/xyzzy/xzyyzl33t/...shuttingdownthefacade..." % address,
                    timeout=1)
            except:
                pass

class SSLCertificateManager:
    #NOTE: This does not handle virtualenv pip installs
    #      A pip configuration pointing pip at the certs is still
    #      required for handling this.
    CERT_PATHS=[
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/certs/ca-certificates.crt",
        "/usr/share/ssl/certs/ca-bundle.crt",
        "/usr/local/share/certs/ca-root.crt",
        "/etc/ssl/cert.pem",
        "/System/Library/OpenSSL/certs/cert.pem",
        "/usr/lib/python*/dist-packages/pip/_vendor/requests/cacert.pem",
        "/usr/local/lib/python*/dist-packages/pip/_vendor/requests/cacert.pem",
        "/usr/lib/python*/site-packages/pip/_vendor/requests/cacert.pem",
        "/usr/local/lib/python*/site-packages/pip/_vendor/requests/cacert.pem"
        "/usr/lib/python*/dist-packages/pip/_vendor/certifi/cacert.pem",
        "/usr/local/lib/python*/dist-packages/pip/_vendor/certifi/cacert.pem",
        "/usr/lib/python*/site-packages/pip/_vendor/certifi/cacert.pem",
        "/usr/local/lib/python*/site-packages/pip/_vendor/certifi/cacert.pem" 
    ]

    VENV_CERT_PATHS=[
        "lib/python*/site-packages/pip/_vendor/requests/cacert.pem",
        "lib/python*/site-packages/pip/_vendor/certifi/cacert.pem" ]

    FAUX_CERT_DIR="__csmake_pypifacade_faux_ca-trust"
    CERT_DIRS=[
        "/etc/pki/ca-trust/source/anchors",
        "/usr/local/share/ca-certificates",
        "/" + FAUX_CERT_DIR ]

    def __init__(self, module, options):
        self.module = module
        self.log = module.log
        self.options = options
        self._processOptions()
        self.bundles = []
        self.certFiles = []
        self.rootCACertPath = None
        self.certPath = None
        self.certKeyPath = None

    def addBundle(self, bundle):
        self.bundles.append(bundle)

    def removeBundle(self, bundle):
        try:
            self.bundles.remove(bundle)
        except ValueError as ve:
            self.log.debug("bundle '%s' not found in bundle list", bundle)

    def addCertFile(self, certFile):
        self.certFiles.append(certFile)

    def removeCertFile(self, certFile):
        try:
            self.bundles.remove(certFile)
        except ValueError as ve:
            self.log.debug("bundle '%s' not found in bundle list", bundle)

    def getCARootPath(self):
        return self.rootCACertPath

    def getCertPath(self):
        return self.certPath

    def getCertKeyPath(self):
        return self.certKeyPath

    def _processOptions(self):
        if 'no-certroot' not in self.options:
            self.options['no-certroot'] = False
        else:
            self.options['no-certroot'] = self.options['no-certroot'] == 'True'
        if 'certroot' in self.options \
            and 'certroot-key' not in self.options \
                 and ('certfile' not in self.options \
                      or 'certfile-key' not in self.options):
            self.log.error("When providing a certroot, you must either provide the root's key (unsafe), or a relevant certfile and certfile-key (safer) - PypiProvider cannot generate temporary certificates unless certroot-key is provided with certroot")
            raise ValueError("Must specify 'certroot-key' or 'certfile' and 'certfile-key' when providing 'certroot'")

        if self.options['no-certroot'] \
            and ('certfile' not in self.options \
                 or 'certfile-key' not in self.options):
            self.log.error("When using 'no-certroot', it implies that you have a certificate that can already be validated with the current CA authority, but no certificate was provided with 'certfile'.  A key 'certfile-key' is also required in order to use the certificate")
            raise ValueError("Must specify 'certfile' and 'certfile-key' when specifying 'no-certroot'")
        if 'certpath' not in self.options:
            self.options['certpath'] = os.path.join(
                tempfile.mkdtemp(),
                'tempcerts')
        if 'certfile' not in self.options:
            self.options['certfile'] = 'csmake-pypi-cert.crt'
        if 'certfile-key' not in self.options:
            self.options['certfile-key'] = 'csmake-pypi-cert.key'
        if 'certfile-key-password' not in self.options:
            self.options['certfile-key-password'] = None
        if 'certroot-path' not in self.options:
            self.options['certroot-path'] = self.options['certpath']
        if 'certroot' not in self.options:
            self.options['certroot'] = 'csmake-pypi-certCA.pem'
        if 'certroot-key' not in self.options:
            self.options['certroot-key'] = 'csmake-pypi.certCA.key'
        if 'certroot-key-password' not in self.options:
            self.options['certroot-key-password'] = None
        if 'no-certroot' not in self.options:
            self.options['no-certroot'] = False

    def prettyPrintDevDebug(self):
        if self.log.devoutput:
            with open(self.certPath) as certfile:
                self.log.devdebug("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%")
                self.log.devdebug("The Certificate path: %s", self.certPath)
                for line in certfile.readlines():
                    self.log.devdebug(line)
                self.log.devdebug("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%")
            for cert in self.certbundles():
                with open(cert) as certfile:
                    self.log.devdebug("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
                    self.log.devdebug("Bundle path: %s", cert)
                    for line in certfile.readlines():
                        self.log.devdebug(line)
                    self.log.devdebug("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")

    def generate(self):

        options = self.options
        self.interfaces = options['interfaces']
        self.log.devdebug("Interfaces for PypiService: %s", str(self.interfaces))

        #Inspired by: http://usrportage.de/archives/919-Batch-generating-SSL-certificates.html
        #  and: http://datacenteroverlords.com/2012/03/01/creating-your-own-ssl-certificate-authority/

        self.rootCACertPath = os.path.join(
            options['certroot-path'],
            options['certroot'] )
        self.rootCACertKeyPath = os.path.join(
            options['certroot-path'],
            options['certroot-key'] )

        self.certKeyPath = os.path.join(
            options['certpath'],
            options['certfile-key'] )
        self.certPath = os.path.join(
            options['certpath'],
            options['certfile'] )

        self.rootCACertExisted = os.path.exists(self.rootCACertPath)
        self.rootCACertKeyExisted = None

        self.certKeyExisted = None
        self.certExisted = None

        if self.rootCACertExisted or options['no-certroot']:
            #The root CA already exists.
            #We either need the key to proceed, or we need to already
            #Have a derived certificate and key - or we're hosed.
            self.rootCACertKeyExisted = os.path.exists(self.rootCACertKeyPath)
            if not self.rootCACertKeyExisted:
                self.certKeyExisted = os.path.exists(self.certKeyPath)
                self.certExisted = os.path.exists(self.certPath)
                if not (self.certKeyExisted and self.certExisted):
                    self.log.error("If a pre-created root CA is to be used, you must either provide its key (scary), or provide a certificate and its key already generated from this root CA")
                raise ValueError("A root CA external to PypiService was specified, but no derived certificates and no key to create derived certificates was given")

        #Create a shell environment with a csmake password
        #Just in case we need it.
        #Passwords passed in may be env:<envkey> or <password>
        #if env:<envkey> it is assumed that the password is in the shell
        #  execution environment under <envkey>.
        env = {}
        env.update(os.environ)
        env['__CSMAKE_PASS'] = 'csmake-xyzzy-'
        rootpassenv = '__CSMAKE_PASS'
        certpassenv = '__CSMAKE_PASS'

        if options['certroot-key-password'] is not None:
            if options['certroot-key-password'].startswith('env:'):
                rootpassenv = options['certroot-key-password'][4:]
            else:
                rootpassenv = '__CSMAKE_PASS_ROOT'
                env['__CSMAKE_PASS_ROOT'] = options['certroot-key-password']

        if options['certfile-key-password'] is not None:
            if options['certfile-key-password'].startswith('env:'):
                certpassenv = options['certfile-key-password'][4:]
            else:
                certpassenv = '__CSMAKE_PASS_CERT'
                env['__CSMAKE_PASS_CERT'] = options['certroot-key-password']

        #Do we need to install a root CA?
        if not options['no-certroot']:
            #Yes.  Does a root CA already exist?
            if not self.rootCACertExisted:
                #No.  Create one.  Does a key already exist?
                if not self.rootCACertKeyExisted:
                    self.log.debug("Creating certRootCAKey %s", self.rootCACertKeyPath)
                    #No. (No surprise) Generate one.
                    subprocess.call(
                        ['mkdir', '-p', options['certroot-path']],
                        stdout=self.log.out(),
                        stderr=self.log.err())
                    subprocess.check_call(
                        ['openssl', 'genrsa', '-des3', '-out',
                         self.rootCACertKeyPath,
                         '-passout',
                         'env:' + rootpassenv,
                         '2048' ],
                        stdout=self.log.out(),
                        stderr=self.log.err(),
                        env=env )

                #Now.  Generate the cert with the key
                self.log.debug("Creating certRootCA %s", self.rootCACertPath)
                subprocess.check_call(
                    [ 'openssl', 'req', '-x509', '-new', '-nodes', '-batch',
                      '-subj', '/C=US/ST=CO/O=HPE/localityName=csmake/commonName=csmake Fake Signing Authority (remove immediately)/organizationalUnitName=csmake/emailAddress=csmake@hpe.com',
                      '-key', self.rootCACertKeyPath,
                      '-out', self.rootCACertPath,
                      '-passin', 'env:' + rootpassenv ],
                    stdout=self.log.out(),
                    stderr=self.log.err(),
                    env=env )

        #Next - discover or generate the client certificate
        #Do we already have a certificate?
        if not self.certExisted:
            #No.  Do we already have a key?
            if not self.certKeyExisted:
                #No.  (No surprise) Generate one.
                self.log.debug("Creating certKey %s", self.certKeyPath)
                subprocess.check_call(
                    ['openssl', 'genrsa', '-des3', '-out',
                     self.certKeyPath + '.orig',
                     '-passout',
                     'env:' + certpassenv,
                     '2048' ],
                    stdout=self.log.out(),
                    stderr=self.log.err(),
                    env=env )

            #Now.  Generate the cert request with the key
            self.log.debug("Creating new req %s", self.certPath + '.csr')
            subprocess.check_call(
                ['openssl', 'req', '-new', '-batch',
                 '-subj', '/C=US/ST=CO/O=HPE/localityName=csmake/commonName=%s/organizationalUnitName=csmake/emailAddress=csmake@hpe.com/subjectAltName=DNS.1=%s' % (self.interfaces[0], self.interfaces[0]),
                 '-key', self.certKeyPath + '.orig',
                 '-out', self.certPath + '.csr',
                 '-passin', 'env:' + certpassenv ],
                stdout=self.log.out(),
                stderr=self.log.err(),
                env=env )

            #Sign the new certificate request
            self.log.debug("Creating new client req %s", self.certPath)
            subprocess.check_call(
                ['openssl', 'x509', '-req',
                 '-in', self.certPath + '.csr',
                 '-CA', self.rootCACertPath,
                 '-CAkey', self.rootCACertKeyPath,
                 '-CAcreateserial',
                 '-out', self.certPath,
                 '-passin', 'env:' + rootpassenv,
                 '-days', '5' ],
                stdout=self.log.out(),
                stderr=self.log.err(),
                env=env)

            #Strip the password on the client key
            self.log.debug("Stripping client password")
            subprocess.check_call(
                [ 'openssl', 'rsa',
                  '-in', self.certKeyPath + '.orig',
                  '-out', self.certKeyPath,
                  '-passin', 'env:' + certpassenv ],
                stdout=self.log.out(),
                stderr=self.log.err(),
                env=env )

    def delete(self):
        if not self.rootCACertExisted:
            subprocess.call(
                ['rm', self.rootCACertPath],
                stdout=self.log.out(),
                stderr=self.log.err() )
        if not self.rootCACertKeyExisted:
            subprocess.call(
                ['rm', self.rootCACertKeyPath],
                stdout=self.log.out(),
                stderr=self.log.err() )
        if not self.certKeyExisted:
            subprocess.call(
                ['rm', self.certKeyPath],
                stdout=self.log.out(),
                stderr=self.log.err() )
        if not self.certExisted:
            subprocess.call(
                ['rm', self.certPath],
                stdout=self.log.out(),
                stderr=self.log.err() )

    def certbundles(self):
        return self.bundles

    def certfiles(self):
        return self.certFiles

class PypiProvider(CsmakeServiceProvider):
    serviceProviders = {}

    def __init__(self, module, tag, **options):
        ciphers = subprocess.check_output(
            ['openssl', 'ciphers'])
        self.ciphers = ciphers.strip()
        CsmakeServiceProvider.__init__(self, module, tag, **options)
        self.serviceClass = PypiService

    def _customizeSocket(self, socket):
        return ssl.wrap_socket(
            socket,
            #ssl_version=ssl.PROTOCOL_TLSv1_2,
            ssl_version=ssl.PROTOCOL_SSLv23,
            server_side=True,
            ciphers=self.ciphers,
            certfile=self.certificateManager.getCertPath(),
            keyfile=self.certificateManager.getCertKeyPath() )

    def _processOptions(self):
        if 'interfaces' not in self.options:
            self.options['interfaces'] = 'localhost'
        originalInterfaces = self.options['interfaces']
        interfaces = ','.join(self.options['interfaces'].split('\n')).split(',')
        self.options['interfaces'] = [
            x.strip() for x in interfaces if len(x.strip()) > 0 ]

        self.certificateManager = SSLCertificateManager(self.module, self.options)
        self.certificateManager.generate()
        self.options['interfaces'] = originalInterfaces
        CsmakeServiceProvider._processOptions(self)
        if 'venvs' not in self.options:
            self.options['venvs'] = []
        else:
            venvs = ','.join(self.options['venvs'].split('\n')).split(',')
            self.options['venvs'] = [
                x.strip() for x in venvs if len(x.strip()) > 0 ]

    def getController(self):
        if self.service is None:
            return None
        else:
            return self.service.getController()

    def getCertificateManager(self):
        return self.certificateManager

    def endService(self):
        CsmakeServiceProvider.endService(self)
        self.certificateManager.delete()
