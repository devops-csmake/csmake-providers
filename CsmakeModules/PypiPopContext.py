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
from Csmake.CsmakeModule import CsmakeModule

class PypiPopContext(CsmakeModule):
    """Purpose: A module that will undo the application of a context
                  restoring the previons pypi context
                A PypiFacade must be active to use this section.
       Flags: name - The name of the context to establish and push.
              tag - (OPTIONAL) The facade to reference
                    Default is the default facade (no tag specified)
       Phase: build - will remove the named pypi context and all other
                       contexts that were pushed after this context."""

    REQUIRED_OPTIONS=['name']

    def build(self, options):
        self.tag = '_'
        if 'tag' in options:
            self.tag = options['tag']
        service = PypiProvider.getServiceProvider(self.tag)
        controller = service.getController()
        controller.popCurrentContext(options['name'])
        self.log.passed()
        return True

