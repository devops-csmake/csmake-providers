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
from Csmake.CsmakeModuleAllPhase import CsmakeModuleAllPhase

class PypiStopFacade(CsmakeAspect, CsmakeModuleAllPhase):
    """Purpose: An module to end execution of a PypiFacade.
                May be used as an aspect.
                The advantage to using stop facade as an aspect
                when using PypiFacade as a regular section is that
                PypiStopFacade will be executed on exit of a section.
                If stop is used as a regular section, it will not
                be executed upon failure of a preceeding section.
                (Think of it like being put as a "finally" of the crosscut
                 section)
       Flags: tag - (OPTIONAL) should match the tag used for PypiFacade
       Phase: * - end execution of a PypiFacade.
              end - end execution of a PypiFacade as an aspect"""

    def _stopService(self):
        try:
            self._unregisterOtherClassOnExitCallback(
                "PypiFacade",
                "_stopFacade" )
        except:
            pass
        tag = '_'
        if 'tag' in self.options:
            tag = self.options['tag']
        PypiProvider.disposeServiceProvider(tag)
        self.log.passed()
        return True

    def default(self, options):
        self.options = options
        return self._stopService()

    def end(self, phase, options, step, stepoptions):
        self.options = options
        return self._stopService()
