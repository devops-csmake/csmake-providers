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
"""Test-only helpers shared by the *_py3.py unit tests (nothing here is
production code).

The tests are unit tests: every external boundary (subprocess, urlopen, the
csmake config manager that shells out, GitPython) is replaced by a fake from
this module.  The fakes honour the real APIs' type contracts so that they
keep catching bytes-versus-str mistakes:

* FakeCheckOutput / FakeManager.shellout(subprocess.check_output, ...) return
  BYTES unless text=True / universal_newlines=True / encoding= was passed.
* FakeResponse.read() returns bytes and .info() is a real HTTPMessage.
* FakeHandler.wfile is a BytesIO, as binary as a socket's wfile, and
  send_header() refuses bytes values.

pyinotify is Linux-only but CsmakeServiceProvider.py imports it
unconditionally; it is only used to watch config files, which none of these
tests exercise, so where the real package is absent a stub that fails loudly
if it is actually used goes into sys.modules.
"""
import email.message
import http.client
import importlib
import io
import os
import re
import subprocess
import sys
import traceback
import types
import unittest
import urllib.error

# <repo>/CsmakeProviders/tests/CsmakeProviders/providers_support.py
PROVIDERS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
REPO = os.path.dirname(PROVIDERS_DIR)

# Third party packages the providers need; absent ones skip, not fail.
OPTIONAL_LIBS = ('git', 'gitdb', 'yaml', 'packaging', 'pygments')

# What chmod accepts as an octal mode; notably not Python 3's '0o640'.
CHMOD_MODE = re.compile(r'^[0-7]{1,4}$')


def ensure_pyinotify():
    try:
        import pyinotify  # noqa: F401  (the real thing, e.g. on Linux)
        return
    except ImportError:
        pass
    stub = types.ModuleType('pyinotify')
    stub.__csmake_test_stub__ = True
    stub.ProcessEvent = type('ProcessEvent', (object,), {})

    def _unavailable(name):
        raise AttributeError(
            "pyinotify is stubbed in these tests; '%s' means a test is "
            "exercising file watching, which it must not" % name)
    stub.__getattr__ = _unavailable
    sys.modules['pyinotify'] = stub


def import_provider(name):
    """Import CsmakeProviders/<name>.py as a flat top level module."""
    ensure_pyinotify()
    if PROVIDERS_DIR not in sys.path:
        sys.path.insert(0, PROVIDERS_DIR)
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        if (exc.name or '').split('.')[0] in OPTIONAL_LIBS:
            raise unittest.SkipTest("%s needs '%s', which is not installed" % (
                name, exc.name))
        raise


class FakeLog(object):
    """The surface of csmake's log that the providers touch.  Everything
    logged is kept in .records as (level, text)."""
    devoutput = False

    def __init__(self):
        self.records = []

    def _record(self, level, msg, args):
        self.records.append((level, msg % args if args else msg))

    def debug(self, msg, *args):
        self._record('debug', msg, args)

    def devdebug(self, msg, *args):
        pass

    def info(self, msg, *args):
        self._record('info', msg, args)

    def warning(self, msg, *args):
        self._record('warning', msg, args)

    def error(self, msg, *args):
        self._record('error', msg, args)

    def exception(self, msg, *args):
        self._record('exception', msg, args)
        self.records[-1] = ('exception',
                            self.records[-1][1] + '\n' + traceback.format_exc())

    def passed(self):
        self.records.append(('passed', ''))

    def failed(self):
        self.records.append(('failed', ''))

    def out(self):
        return None

    def err(self):
        return None

    def messages(self, *levels):
        return [text for level, text in self.records if level in levels]

    @property
    def problems(self):
        """Errors and swallowed exceptions."""
        return self.messages('error', 'exception')


def _wants_text(kwargs):
    return bool(kwargs.get('text') or kwargs.get('universal_newlines')
                or kwargs.get('encoding') or kwargs.get('errors'))


def process_output(outcome, kwargs):
    """What check_output would hand back for scripted bytes `outcome`."""
    if isinstance(outcome, BaseException):
        raise outcome
    assert isinstance(outcome, bytes), "script check_output output as bytes"
    if _wants_text(kwargs):
        return outcome.decode(kwargs.get('encoding') or 'utf-8',
                              kwargs.get('errors') or 'strict')
    return outcome


class FakeCheckOutput(object):
    """Stands in for subprocess.check_output.

    Scripted with {command tuple: bytes or exception}; records every call
    as (command list, kwargs)."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        return process_output(self.script[tuple(args)], kwargs)


def called_process_error(command, returncode=1, output=b''):
    return subprocess.CalledProcessError(returncode, command, output=output)


class FakeManager(object):
    """Stands in for CsmakeServiceConfigManager: records what would have been
    shelled out instead of running it.

    results maps a command tuple to bytes (for check_output), a return code
    (for call) or an exception to raise.  Unscripted commands succeed."""
    chroot = None
    noSudo = True
    cwd = None

    def __init__(self, log, results=None):
        self.log = log
        self.results = results or {}
        self.calls = []

    def shellout(self, subprocess_call, command, in_chroot=True, sudo=True,
                 quiet_check=False, with_user_env=False):
        self.calls.append((subprocess_call, list(command), in_chroot))
        outcome = self.results.get(tuple(command))
        if subprocess_call is subprocess.check_output:
            return process_output(b'' if outcome is None else outcome, {})
        if isinstance(outcome, BaseException):
            raise outcome
        if subprocess_call is subprocess.call:
            return 0 if outcome is None else outcome
        return outcome

    def commands(self, name=None):
        return [command for _, command, _ in self.calls
                if name is None or command[0] == name]


class FakeResponse(io.BytesIO):
    """What urllib.request.urlopen returns for a successful request."""

    def __init__(self, body, headers=None):
        io.BytesIO.__init__(self, body)
        self.headers = http.client.HTTPMessage()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def info(self):
        return self.headers


class FakeUrlopen(object):
    """Stands in for urllib.request.urlopen, scripted by exact URL.

    routes maps url -> body bytes, (body bytes, {header: value}) or an
    exception to raise.  Unscripted URLs are 404s."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, *args, **kwargs):
        self.calls.append(url)
        route = self.routes.get(url)
        if route is None:
            route = urllib.error.HTTPError(
                url, 404, 'Not Found', email.message.Message(), None)
        if isinstance(route, BaseException):
            if isinstance(route, urllib.error.HTTPError):
                route.close()  # nothing reads the body; avoids a ResourceWarning
            raise route
        if isinstance(route, bytes):
            route = (route, {})
        return FakeResponse(*route)


class FakeHandler(object):
    """The BaseHTTPRequestHandler surface that PypiContext writes to."""

    def __init__(self):
        self.wfile = io.BytesIO()
        self.status = None
        self.headers = []
        self.errors = []
        self.ended = False

    def send_response(self, code):
        self.status = code

    def send_header(self, keyword, value):
        assert not isinstance(value, bytes), "header values are str"
        self.headers.append((keyword, str(value)))

    def end_headers(self):
        self.ended = True

    def send_error(self, code, message=None):
        self.errors.append((code, message))

    def header(self, name):
        for keyword, value in self.headers:
            if keyword.lower() == name.lower():
                return value
        return None
