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
from CsmakeProviders.PypiProvider import PypiProvider
from Csmake.CsmakeAspect import CsmakeAspect

class PypiFacade(CsmakeAspect):
    """Purpose: An module (or aspect) to:
                Provide server-side control over pip installs in a build
                   (without setting up a mirror)
                Create or utilize a cache for pip in builds
                Provide limits on dependencies and on other pip or
                   easy_install installed components that may not otherwise
                   conform to the needs of all installed components
                Allow crafting of fine-tuned dependencies that may
                   vary for different virtual environments or may
                   differ for different parts of a build.
                   (Helpful in overcoming both under and over specified
                    requirements.txt files)
                Overcome limitations with proxy requirements not being
                   respected by dependent installs (cffi has/had this issue)
                Overcome limitations created by pip's requirement of
                   ssl to establish trusted servers.
                Provide a way for DIB type installs to manipulate
                   or lock down the requirements environment for the
                   purpose of its install and allow overriding such
                   manipulation to allow cooperation of components
                   at the build level as DIB elements are supposed
                   to remain fundamentally independent.
                Assertion: pip is unusable/unreliable in a production build
                           environment without a mechanism like this
                           controlling its behavior, caching its resulting
                           package pulls, and providing a mechanism to
                           draw from the cache in subsequent builds.
       Notes: * When used as a module - use PypiStopFacade to end the facade.
              To use as an aspect, begin the section declaration with the
              aspect moniker (&).
              * Only one facade can be running.  If it is necessary
              to have two different pypi behaviors utilize contexts.
              * Attempting to have multiple contexts used at the same time
              can be done in most circumstances by overriding the
              PIP_INDEX_URL to point to the context (drop the name of the
              context as the path in the index).  There are some cases
              where easy_install will be invoked to satisfy requirements
              for pip installs and PIP_INDEX_URL will be ignored, leaving
              the pushed context to serve the request.
       Flags: tag - (OPTIONAL) allows for multiple facades to be executing
                          at the same time.
                    If a tag is used and PypiStopFacade is also used,
                    the tag must be used with the PypiStopFacade section
                    as well.
              no-sudo - (OPTIONAL) Will prevent use of sudoing
                     (cannot be used with a chroot environment)
              phases - (OPTIONAL) Specify the phases the facade will activate
                     Default: build
                     If '*' is specified, every phase is active

              ::Network Controls::
              interfaces - (OPTIONAL) list of interfaces to listen on,
                           delimited by commas.  Currently only one
                           interface is supported in both the server and
                           the configuration of pip and easy_install in the
                           build.
                           Default is 'localhost'
              port - (OPTIONAL) The port for the Pypi proxy facade
                        to listen on pip requires ssl - although it trusts
                        localhost without this, you may choose a different
                        interface.  Implementation of SSL ensures that PyPI
                        access in a build will always be trusted.
                        Default is a free port in the range of
                        20000 - 24000 (see port-range)
              port-range - (OPTIONAL) A range for the ports for the
                        facade to listen on - a free port in the range
                        will be picked (NOTE: Does not attempt to avoid ports
                        occupied on CLOSE_WAIT and similar states).
              timeout - (OPTIONAL) Allows build to set a timeout (in seconds)
                        for the pip client to wait before bailing out.
                        Default is 45

              ::SSL Controls::
              certpath - (OPTIONAL) This will be the path to where the
                        ssl certificate pieces will be generated for the
                        proxy facade.  Use this if it is necessary to refer
                        to the certificates in the build.  The path
                        will be relative to the chroot as the chrooted
                        environment will need access.
                        Default is a temporary directory on the chrooted
                        system called /tempcerts.
                        If this path is led with a '/' it will not be
                        translated into a chroot path.
              certfile - (OPTIONAL) The actual ssl certificate file name
                         generated.  For best compatibility, the extension
                         should be .crt
                         Default: csmake-pypi-cert.crt
                         If the certfile specified already exists, the facade
                         will avoid generating one, however, certfile-key
                         must also be provided and certfile-key-password.
                         If you are providing your own certfile, you should
                         also consider setting no-certroot to True and ensure
                         that the authority for the certfile provided is
                         commonly available in all the various CA bundles
                         (don't forget the ones in places like "requests"
                         and in pip's "vendor" copy of the requests library.)
              certfile-key - (OPTIONAL) The path to the key file for the
                         certfile specified.  The file will be generated
                         if it doesn't exist.  If it does exist,
                         you must provide certfile-key-password as another
                         option for the key you are providing
                         Default: csmake-pypi-cert.key
              certfile-key-password - (OPTIONAL) The password for the
                         certfile-key provided.  If a certfile-key is generated,
                         the password provided will be used as the password
                         for the key file.
                         Default: csmake-xyzzy-
              certroot-path - (OPTIONAL) The path to use for all generation
                         or manipulation of CA certificates.
                         Default: certpath
              certroot - (OPTIONAL) The CA authority file used to generate
                         the certfile.  If the file path provided doesn't exist,
                         the facade will generate a self-signed authority.
                         If the path provided does exist, you must also
                         provide the key and password for the CA, or also
                         provide the certfile and certfile-key that are rooted
                         in this CA.
                         Default: csmake-pypi-certCA.pem
              certroot-key - (OPTIONAL) The key file that will be used to
                         generate a CA certificate (certroot).  If the path
                         provided doesn't exist, a key file will be generated.
                         If the path does exist, you should also provide the
                         password for the key using certroot-key-password.
                         Default: csmake-pypi-certCA.key
              certroot-key-password - (OPTIONAL) The password for the
                         certroot-key provided.  If a certroot-key is generated,
                         the password provided will be used as the password
                         for the key file.
                         Default: csmake-xyzzy-
              no-certroot - (OPTIONAL) When True, the facade will not
                         manipulate any CA bundle authorities.  It is
                         assumed if this is set to True, that the CA for the
                         certificate will already be available in the various
                         CA bundles (i.e., you have a purchased certificate,
                         or require installation of a CA authority on all
                         systems before building).
                         Default: False

              ::Pypi/Pip Package Availablity/Context Controls::
              default-context - (OPTIONAL) The base context name to use
                                Default is 'simple'
              indicies - (OPTIONAL) List of indexes that the facade should
                         consult when proxying for the build.  These may be
                         trusted or untrusted sources.
              constraining-indicies - (OPTIONAL)
                         Like 'indicies' this is a list of consulted indicies.
                         This has the additional property that the contents
                         of these indicies will be used to produce an initial
                         set of version constraints - allowing a common pip
                         practice of limiting a mirror to a specific set
                         of installs to control versioning to be the jumping
                         off point for the version constraints for the proxy.
                         (for large mirrors, this may take some time)
                         (this should only be used against mirrors that have
                          limited contents as a means to establishing version
                          control over pip)
              cache - (OPTIONAL) Directory to establish a build cache of all
                                 used pip packages.
              NOTE: If none of indicies, constraining_indicies, or cachd
                    the proxy will behave like an empty mirror.
              chroot - (OPTIONAL) Location in the file system to treat as
                                  root - useful for image builds like DIB
                                  where pip configuration files and
                                  SSL configuration files will be consulted
                                  in a chrooted environment.
              constraints - (OPTIONAL) requirements.txt (PEP-440) definitions
                                  to use to limit access to versions
                                  of specific packages.  As in PEP-440
                                  the comma is used to denote an "AND" syntax
                                  This will also support the use of an "OR"
                                  syntax (|) or (||) to allow a string of
                                  specific allowed versions to be specified
                                  or other PEP-440 style sequences.
                            For example:
                               pip==6.1.1 | ==1.5.2 | ==1.5.3 | ~=1.7, !=1.7.3
                                  would only allow version 6.1.1, 1.5.2,
                                  or 1.5.3 or any 1.7.* of pip except 1.7.3.
                  Constraints for multiple packages may be specified
                      and are either *semi-colon* delimited or newline
                      delimited.
              venvs - (OPTIONAL) a comma or new-line delimited list of
                      paths to virtualenvs to use with the facade.
                      It is necessary to list any virtualenv's you which
                      to install against the facade even if the virtualenv
                      doesn't yet exist (that's ok, but not ideal).
                      The facade will ensure that pip and setuptools installs
                      will go through the facade when operating in the
                      virtualenv.
        Phase: build - will start the proxy - if the proxy is
                       already started - the request will be ignored.
        JoinPoints: start__build - will launch the proxy
                    end__build - will stop and clean up the proxy"""

    def __init__(self, env, log):
        CsmakeAspect.__init__(self, env, log)

    def __repr__(self):
        return "<<%s Csmake Module>>" % self.__class__.__name__

    def __str__(self):
        return self.__repr__()

    def __getattr__(self, name):
        if name.startswith('_'):
            self.log.error("__getattr__ should not be invoked for items that begin with '_': %s", name)
            self.log.error("    Failing lookup")
            raise AttributeError(name)
        self.log.devdebug("__getattr__ Looking up '%s': returning 'default", name)
        return self._startFacade


    def _startFacade(self, options):
        #This shouldn't be necessary - PypiStopFacade should be
        #  where a yields-files, for example, would go.
        phase = self.engine.getPhase()
        if 'phases' in options:
            targetPhases = self._parseCommaAndNewlineList(options['phases'])
        else:
            targetPhases = ['build']
        if phase not in targetPhases:
            self.log.skipped()
            self._dontValidateFiles()
            self._absorbNewMappedFiles()
            return None
        self._dontValidateFiles()
        self.tag = '_'
        if 'tag' in options:
            self.tag = options['tag']
            del options['tag']
        self._registerOnExitCallback("_stopFacade")
        self.service = PypiProvider.createServiceProvider(self.tag, self, **options)
        self.service.startService()
        controller = self.service.getController()
        if self.service.isServiceExecuting():
            self.log.passed()
        else:
            self.log.failed()
        return controller

    def _stopFacade(self):
        PypiProvider.disposeServiceProvider(self.tag)
        self.log.passed()
        try:
            self._unregisterOnExitCallback("_stopFacade")
        except:
            pass

    def _joinPointLookup(self, joinpoint, phase, options):
        self.log.devdebug("lookup aspect id: %s", self.log.params['AspectId'])
        self.log.devdebug("lookup options are: %s", str(options))
        self.log.devdebug("lookup aspect address: %s", hex(id(self)))
        if 'phases' in options:
            if options['phases'] == '*':
                phases = None
            else:
                phases = self._parseCommaAndNewlineList(options['phases'])
        else:
            phases = 'build'

        if phases is None or phase in phases:
            if joinpoint == 'start':
                return self._poweron
            elif joinpoint == 'end':
                return self._poweroff
            else:
                return None

    def _poweron(self, phase, options, step, stepoptions):
        return self._startFacade(options)

    def _poweroff(self, phase, options, step, stepoptions):
        self._stopFacade()
        return True

