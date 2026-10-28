# <copyright>
# (c) Copyright 2026 Autumn Patterson
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
"""Test-only helper: make sure csmake core (CsmakeCore) can be imported.

The plugin modules import from CsmakeCore (the core package's current name).
CsmakeCore is taken from sys.path, else from the sibling checkout
<repo parent>/csmake; if neither exists the test module is skipped.

(Formerly this also aliased the retired 'Csmake' name to CsmakeCore; the
production imports no longer need that, and testLegacyImports_py3.py guards
against them regressing.)
"""
import importlib.util
import os
import sys
import unittest

# <repo>/CsmakeProviders/tests/CsmakeProviders/csmake_alias.py
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
CORE_CHECKOUT = os.path.join(os.path.dirname(REPO), 'csmake')


def _on_path(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ImportError:
        return False


def install():
    """Make 'import CsmakeCore.X' work; SkipTest if csmake core is absent."""
    if _on_path('CsmakeCore'):
        return
    if not os.path.isdir(os.path.join(CORE_CHECKOUT, 'CsmakeCore')):
        raise unittest.SkipTest("csmake core not found")
    sys.path.insert(0, CORE_CHECKOUT)
