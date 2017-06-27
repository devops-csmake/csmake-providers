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

class PypiDeleteContext(CsmakeModule):
    """Purpose: A module to delete a pypi named context
                A PypiFacade must be active to use this section.
                This will destroy a context created by
                   PypiCreateContext or PypiPushContext
                This will fail if a context is currently in use
                   on the context stack.
       Flags: name - The name of the context to delete.
              tag - (OPTIONAL) 
        Phase: build - will delete a named context"""

    REQUIRED_OPTIONS=['name']

    def build(self, options):
        self.tag = '_'
        if 'tag' in options:
            self.tag = options['tag']
        service = PypiProvider.getServiceProvider(self.tag)
        controller = service.getController()
        if controller.unregisterContext(options['name']):
            self.log.passed()
            return True
        else:
            self.log.failed()
            return False

