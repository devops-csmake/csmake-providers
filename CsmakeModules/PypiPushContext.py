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

class PypiPushContext(CsmakeAspect):
    """Purpose: An aspect or regular section to modify the versioning
                    behavior of pip installs for all csmake sections
                    that decide to refer to the named context in this section
                If the named context is referred to by multiple sections
                    the context will be reused and modified according to
                    the flags specified.
                A PypiFacade must be active to use this section.
                Use of the aspect moniker (&) in the section definition in
                    a csmakefile will cause this modification to be
                    temporary just during the execution of the joined section.
                Use of this section as a non-aspect will keep the context
                    alive until it is removed.  (See PypiPopContext)
                Contexts are managed as a stack to allow independence
                    of ordering.
       Flags: name - The name of the context to establish and push.
              tag - (OPTIONAL) Refers to the facade instance to change
                    Default is the default facade.
              previous - (OPTIONAL) The name of a context to inherit and modify.
                         If this is not used, no indicies and no constraints
                         will be applied from any other context - i.e.,
                         a (nearly) clean slate.
                         TODO: Limit the versions that listVersions
                               will supply based on indicies currently
                               active.  Also limit what getPackage
                               will return.
              indicies - (OPTIONAL) PyPI indicies to use or add
              reset - (OPTIONAL) Packages that need to have their
                                 requirements reset.
                                 If a named context is referred to multiple
                                 times, or if a previous context is
                                 brought forward, the constraints for a package
                                 will be "or'ed" together with changes
                                 specified by one of these sections.
                                 * If this is not the desired behavior, but
                                   instead a whole new requirement is required
                                   for a package, it can be listed in this
                                   option and the constraints will only be
                                   what is specified by the section.
                  Resets for constraints for multiple packages are either
                      *semi-colon* (;) or newline delimited.         
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
                  Constraints for multiple packages are either
                     *semi-colon* (;) or newline delimited.
        Phase: build - will create (or reuse) and push the named context until
                       the push is undone - either at the end of the
                       joined section if used as an aspect or when
                       undone by a PypiPopContext.  The named context
                       will take on the modifications given in the section.
        JoinPoints: start - will push the named context with the
                            modifications given in the section.
                    end - will pop the context - the context's modifications,
                          however will be retained in the named context for
                          its next reuse."""

    REQUIRED_OPTIONS=['name']

    def _pushContext(self, options):
        self.tag = '_'
        if 'tag' in options:
            self.tag = options['tag']
        service = PypiProvider.getServiceProvider(self.tag)
        controller = service.getController()
        controller.registerContext(options['name'], options)
        controller.pushCurrentContext(options['name'])
        self.log.passed()
        return True

    def build(self, options):
        return self._pushContext(options)

    def start__build(self, phase, options, step, stepoptions):
        return self._pushContext(options)

    def end__build(self, phase, options, step, stepoptions):
        self.tag = '_'
        if 'tag' in options:
            self.tag = options['tag']
        service = PypiProvider.getServiceProvider(self.tag)
        controller = service.getController()
        controller.popCurrentContext(options['name'])
        self.log.passed()
        return True

