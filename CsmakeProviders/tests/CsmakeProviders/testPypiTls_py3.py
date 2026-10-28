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
"""Unit tests for the TLS side of PypiProvider.py: the accept loop, the
certificate generation (openssl command lines) and the cert bundle/directory
configs.

subprocess, the listening socket and the proxy thread are mocked; the
shelling-out config manager is a FakeManager that records commands.  Real
temp files are used only where the unit's job is to read or write PEM text.

    python3 -m unittest discover -s CsmakeProviders/tests/CsmakeProviders \
        -t . -p 'test*_py3.py' -v
"""
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import types
import unittest
import unittest.mock

try:
    from . import providers_support as support
except ImportError:  # discovered without -t: flat module names
    import providers_support as support

PypiProvider = support.import_provider('PypiProvider')
Cert = PypiProvider.SSLCertificateManager

CERTS = '/certs'
ROOT_KEY = '/certs/csmake-pypi.certCA.key'
ROOT_CERT = '/certs/csmake-pypi-certCA.pem'
CERT_KEY = '/certs/csmake-pypi-cert.key'
CERT = '/certs/csmake-pypi-cert.crt'
ROOT_SUBJECT = ('/C=US/ST=CO/O=HPE/localityName=csmake/commonName=csmake Fake '
                'Signing Authority (remove immediately)/organizationalUnitName='
                'csmake/emailAddress=csmake@hpe.com')
CLIENT_SUBJECT = ('/C=US/ST=CO/O=HPE/localityName=csmake/commonName=localhost/'
                  'organizationalUnitName=csmake/emailAddress=csmake@hpe.com/'
                  'subjectAltName=DNS.1=localhost')


class CertificateTestCase(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.tmp = tempfile.mkdtemp(prefix='csmake-tls-')
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _patch(self, target, name, *args, **kwargs):
        patch = unittest.mock.patch.object(target, name, *args, **kwargs)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock


class testPypiTlsCertificates_py3(CertificateTestCase):

    def setUp(self):
        CertificateTestCase.setUp(self)
        self.check_call = self._patch(PypiProvider.subprocess, 'check_call')
        self.call = self._patch(PypiProvider.subprocess, 'call')

    def _certs(self, existing=(), **options):
        options.setdefault('certpath', CERTS)
        options.setdefault('interfaces', ['localhost'])
        self._patch(PypiProvider.os.path, 'exists',
                    side_effect=lambda path: path in existing)
        return Cert(types.SimpleNamespace(log=self.log), options)

    def _argv(self):
        return [c[0][0] for c in self.check_call.call_args_list]

    def _kwargs(self, index):
        return self.check_call.call_args_list[index][1]

    def test_generate_createsARootCaThenASignedCertificate(self):
        self._certs().generate()

        self.assertEqual(self.call.call_args_list, [
            unittest.mock.call(['mkdir', '-p', CERTS], stdout=None, stderr=None)])
        self.assertEqual(self._argv(), [
            ['openssl', 'genrsa', '-des3', '-out', ROOT_KEY,
             '-passout', 'env:__CSMAKE_PASS', '2048'],
            ['openssl', 'req', '-x509', '-new', '-nodes', '-batch',
             '-subj', ROOT_SUBJECT, '-key', ROOT_KEY, '-out', ROOT_CERT,
             '-passin', 'env:__CSMAKE_PASS'],
            ['openssl', 'genrsa', '-des3', '-out', CERT_KEY + '.orig',
             '-passout', 'env:__CSMAKE_PASS', '2048'],
            ['openssl', 'req', '-new', '-batch', '-subj', CLIENT_SUBJECT,
             '-key', CERT_KEY + '.orig', '-out', CERT + '.csr',
             '-passin', 'env:__CSMAKE_PASS'],
            ['openssl', 'x509', '-req', '-in', CERT + '.csr',
             '-CA', ROOT_CERT, '-CAkey', ROOT_KEY, '-CAcreateserial',
             '-out', CERT, '-passin', 'env:__CSMAKE_PASS', '-days', '5'],
            ['openssl', 'rsa', '-in', CERT_KEY + '.orig', '-out', CERT_KEY,
             '-passin', 'env:__CSMAKE_PASS']])
        self.assertEqual([], self.log.problems)

    def test_generate_opensslGetsAnEnvironmentCarryingOnlyTheDefaultPassword(self):
        with unittest.mock.patch.dict(os.environ, {'CSMAKE_TLS_MARKER': 'x'}):
            self._certs().generate()
            outer = dict(os.environ)

        for index in range(len(self._argv())):
            kwargs = self._kwargs(index)
            self.assertEqual((kwargs['stdout'], kwargs['stderr']), (None, None))
            self.assertEqual(kwargs['env']['__CSMAKE_PASS'], 'csmake-xyzzy-')
            self.assertEqual(kwargs['env']['CSMAKE_TLS_MARKER'], 'x')
        self.assertNotIn('__CSMAKE_PASS', outer)

    def test_generate_anExistingRootCaAndKeyAreReused(self):
        self._certs(existing=(ROOT_CERT, ROOT_KEY)).generate()

        self.call.assert_not_called()
        self.assertEqual([argv[:2] for argv in self._argv()], [
            ['openssl', 'genrsa'], ['openssl', 'req'], ['openssl', 'x509'],
            ['openssl', 'rsa']])
        self.assertEqual(self._argv()[2][3:9], [
            '-in', CERT + '.csr', '-CA', ROOT_CERT, '-CAkey', ROOT_KEY])

    def test_generate_aRootCaWithNeitherKeyNorDerivedCertIsRefused(self):
        certs = self._certs(existing=(ROOT_CERT,))

        with self.assertRaisesRegex(ValueError, 'root CA external'):
            certs.generate()

        self.check_call.assert_not_called()
        self.assertEqual(len(self.log.problems), 1)

    def test_generate_aFailingOpensslStopsTheSequence(self):
        self.check_call.side_effect = [
            None, support.called_process_error(['openssl', 'req'], 1)]

        with self.assertRaises(subprocess.CalledProcessError):
            self._certs().generate()

        self.assertEqual(self.check_call.call_count, 2)

    def test_generate_aMissingOpensslIsAnError(self):
        self.check_call.side_effect = FileNotFoundError('openssl')

        with self.assertRaises(FileNotFoundError):
            self._certs().generate()

        self.assertEqual(self.check_call.call_count, 1)

    def test_generate_passwordsCanNameAnEnvironmentVariable(self):
        self._certs(**{'certroot-key-password': 'env:ROOT_PW',
                       'certfile-key-password': 'env:CERT_PW'}).generate()

        argv = self._argv()
        self.assertEqual(argv[0][5:7], ['-passout', 'env:ROOT_PW'])
        self.assertEqual(argv[1][-2:], ['-passin', 'env:ROOT_PW'])
        self.assertEqual(argv[2][5:7], ['-passout', 'env:CERT_PW'])
        self.assertEqual(argv[3][-2:], ['-passin', 'env:CERT_PW'])
        self.assertEqual(argv[4][-4:-2], ['-passin', 'env:ROOT_PW'])
        self.assertEqual(argv[5][-2:], ['-passin', 'env:CERT_PW'])

    def test_generate_aLiteralRootPasswordTravelsInTheEnvironmentNotArgv(self):
        self._certs(**{'certroot-key-password': 'sekret'}).generate()

        for argv in self._argv():
            self.assertNotIn('sekret', ' '.join(argv))
        self.assertEqual(self._argv()[0][5:7], ['-passout', 'env:__CSMAKE_PASS_ROOT'])
        self.assertEqual(self._kwargs(0)['env']['__CSMAKE_PASS_ROOT'], 'sekret')

    def test_delete_removesWhatGenerateCreated(self):
        certs = self._certs()
        certs.generate()
        self.call.reset_mock()

        certs.delete()

        self.assertEqual(
            [c[0][0] for c in self.call.call_args_list],
            [['rm', ROOT_CERT], ['rm', ROOT_KEY], ['rm', CERT_KEY], ['rm', CERT]])

    def test_delete_leavesAPreExistingRootCaAndItsKeyAlone(self):
        certs = self._certs(existing=(ROOT_CERT, ROOT_KEY))
        certs.generate()

        certs.delete()

        self.assertEqual(
            [c[0][0] for c in self.call.call_args_list],
            [['rm', CERT_KEY], ['rm', CERT]])

    def test_processOptions_fillsInTheDefaults(self):
        self._patch(PypiProvider.tempfile, 'mkdtemp', return_value='/tmp/xyz')

        certs = Cert(types.SimpleNamespace(log=self.log), {})

        self.assertEqual(certs.options, {
            'no-certroot': False, 'certpath': '/tmp/xyz/tempcerts',
            'certfile': 'csmake-pypi-cert.crt',
            'certfile-key': 'csmake-pypi-cert.key',
            'certfile-key-password': None,
            'certroot-path': '/tmp/xyz/tempcerts',
            'certroot': 'csmake-pypi-certCA.pem',
            'certroot-key': 'csmake-pypi.certCA.key',
            'certroot-key-password': None})

    def test_processOptions_aProvidedRootNeedsItsKeyOrADerivedCertAndKey(self):
        with self.assertRaisesRegex(ValueError, "certroot-key"):
            Cert(types.SimpleNamespace(log=self.log),
                 {'certroot': 'ca.pem', 'certpath': CERTS})

        self.assertEqual(len(self.log.problems), 1)

    def test_processOptions_noCertrootNeedsACertAndItsKey(self):
        with self.assertRaisesRegex(ValueError, "no-certroot"):
            Cert(types.SimpleNamespace(log=self.log),
                 {'no-certroot': 'True', 'certpath': CERTS})

    def test_processOptions_noCertrootIsReadFromText(self):
        given = {'certfile': 'c.crt', 'certfile-key': 'c.key', 'certpath': CERTS}

        on = Cert(types.SimpleNamespace(log=self.log),
                  dict(given, **{'no-certroot': 'True'}))
        off = Cert(types.SimpleNamespace(log=self.log),
                   dict(given, **{'no-certroot': 'False'}))

        self.assertIs(on.options['no-certroot'], True)
        self.assertIs(off.options['no-certroot'], False)

    def test_bundlesAndCertFilesAreTracked(self):
        certs = self._certs()

        certs.addBundle('/a/bundle')
        certs.addBundle('/b/bundle')
        certs.removeBundle('/a/bundle')
        certs.removeBundle('/never/added')
        certs.addCertFile('/anchors/ca.pem')

        self.assertEqual(certs.certbundles(), ['/b/bundle'])
        self.assertEqual(certs.certfiles(), ['/anchors/ca.pem'])
        self.assertEqual(len(self.log.messages('debug')), 1)

    def test_prettyPrintDevDebug_isSilentUnlessDevOutputIsOn(self):
        certs = self._certs()
        certs.certPath = os.path.join(self.tmp, 'cert.crt')

        certs.prettyPrintDevDebug()  # would fail on the missing file if on

        self.assertEqual(self.log.messages('devdebug'), [])

    def test_prettyPrintDevDebug_logsTheCertAndEveryBundleAsText(self):
        certs = self._certs()
        certs.certPath = os.path.join(self.tmp, 'cert.crt')
        bundle = os.path.join(self.tmp, 'bundle.crt')
        for path, text in ((certs.certPath, 'CERT-LINE\n'),
                           (bundle, 'BUNDLE-1\nBUNDLE-2\n')):
            with open(path, 'w') as f:
                f.write(text)
        certs.addBundle(bundle)
        self.log.devoutput = True

        certs.prettyPrintDevDebug()

        lines = self.log.messages('devdebug')
        self.assertIn('CERT-LINE\n', lines)
        self.assertEqual([l for l in lines if l.startswith('BUNDLE')],
                         ['BUNDLE-1\n', 'BUNDLE-2\n'])

    def test_prettyPrintDevDebug_aMissingCertFileIsAnError(self):
        certs = self._certs()
        certs.certPath = os.path.join(self.tmp, 'absent.crt')
        self.log.devoutput = True

        with self.assertRaises(FileNotFoundError):
            certs.prettyPrintDevDebug()


def pem(name, lines=3):
    return (['-----BEGIN CERTIFICATE-----\n']
            + ['%s%d\n' % (name, i) for i in range(lines)]
            + ['-----END CERTIFICATE-----\n'])


class testPypiTlsConfigs_py3(CertificateTestCase):
    """SSLCertificateDirectoryConfig / SSLCertificateBundleConfig / Faux."""

    def setUp(self):
        CertificateTestCase.setUp(self)
        self.certManager = Cert(types.SimpleNamespace(log=self.log), {
            'certpath': CERTS, 'interfaces': ['localhost']})
        self.certManager.rootCACertPath = os.path.join(self.tmp, 'rootCA.pem')
        self.manager = support.FakeManager(
            self.log, daemon=types.SimpleNamespace(
                getCertificateManager=lambda: self.certManager))
        self.module = types.SimpleNamespace(log=self.log)

    def _config(self, clazz, path, fullpath=None):
        return clazz(self.module, self.manager, path, fullpath or path,
                     True, None)

    def test_directoryConfig_copiesTheRootCaIntoTheAnchorDirectory(self):
        anchors = os.path.join(self.tmp, 'anchors')
        ca = self.certManager.rootCACertPath
        inserted = os.path.join(anchors, 'rootCA.pem')
        config = self._config(PypiProvider.SSLCertificateDirectoryConfig,
                              '/anchors', anchors)

        config.ensure()

        self.assertEqual(self.manager.commands(), [
            ['mkdir', '-p', anchors], ['chmod', '777', anchors],
            ['mv', inserted, inserted + '.csmake.bkup'],
            ['touch', inserted], ['chmod', '777', inserted],
            ['cp', ca, inserted]])
        self.assertEqual(self.certManager.certfiles(), [inserted])

    def test_directoryConfig_aFailedCopyDoesNotRegisterTheCert(self):
        anchors = os.path.join(self.tmp, 'anchors')
        inserted = os.path.join(anchors, 'rootCA.pem')
        self.manager.results[('cp', self.certManager.rootCACertPath, inserted)] = \
            support.called_process_error(['cp'])
        config = self._config(PypiProvider.SSLCertificateDirectoryConfig,
                              '/anchors', anchors)

        with self.assertRaises(subprocess.CalledProcessError):
            config.ensure()

        self.assertEqual(self.certManager.certfiles(), [])

    def _bundleConfig(self):
        bundle = os.path.join(self.tmp, 'ca-certificates.crt')
        return self._config(PypiProvider.SSLCertificateBundleConfig, bundle), bundle

    def test_bundleConfig_prependsTheRootCaWithCatAndMovesItIntoPlace(self):
        call = self._patch(PypiProvider.subprocess, 'call', return_value=0)
        remove = self._patch(PypiProvider.os, 'remove')
        config, bundle = self._bundleConfig()
        ca = self.certManager.rootCACertPath

        config.ensure()

        call.assert_called_once_with(
            ['cat %s %s > ___csmake-pypi-cert.temp' % (ca, bundle)],
            shell=True, executable='/bin/bash', stdout=None, stderr=None)
        self.assertEqual(self.manager.commands(), [
            ['mkdir', '-p', self.tmp], ['chmod', '777', self.tmp],
            ['cp', bundle, bundle + '.csmake.bkup'], ['chmod', '777', bundle],
            ['mv', '___csmake-pypi-cert.temp', bundle]])
        self.assertEqual(self.certManager.certbundles(), [bundle])
        remove.assert_called_once_with('___csmake-pypi-cert.temp')

    def test_bundleConfig_aFailingCatIsLoggedButTheMoveIsStillTried(self):
        self._patch(PypiProvider.subprocess, 'call', return_value=1)
        self._patch(PypiProvider.os, 'remove')
        config, bundle = self._bundleConfig()

        config.ensure()

        self.assertEqual(len(self.log.problems), 1)
        self.assertIn('caused return of 1', self.log.problems[0])
        self.assertEqual(self.manager.commands()[-1][0], 'mv')

    def test_bundleConfig_aFailedMoveIsAnErrorAndTheBundleIsNotRegistered(self):
        self._patch(PypiProvider.subprocess, 'call', return_value=0)
        remove = self._patch(PypiProvider.os, 'remove')
        config, bundle = self._bundleConfig()
        self.manager.results[('mv', '___csmake-pypi-cert.temp', bundle)] = 1

        with self.assertRaisesRegex(RuntimeError, "certificate bundle"):
            config.ensure()

        self.assertEqual(self.certManager.certbundles(), [])
        remove.assert_called_once_with('___csmake-pypi-cert.temp')

    def _restore(self, bundle_lines, ca_lines=None, cp_result=None):
        previous = os.getcwd()
        os.chdir(self.tmp)   # restore() builds its temp file in the cwd
        self.addCleanup(os.chdir, previous)
        ca = self.certManager.rootCACertPath
        with open(ca, 'w') as f:
            f.writelines(ca_lines or pem('CA'))
        config, bundle = self._bundleConfig()
        with open(bundle, 'w') as f:
            f.writelines(bundle_lines)
        written = []

        def capture(command):
            with open(command[1]) as f:
                written.append(f.read())
        self.manager.hooks['cp'] = capture
        if cp_result is not None:
            self.manager.results[
                ('cp', '___csmake-pypi-bundle-del-cert.temp', bundle)] = cp_result
        self.certManager.addBundle(bundle)
        return config, bundle, written

    def test_bundleConfigRestore_takesOurRootCaOutOfTheBundle(self):
        # the bundle ensure() builds has the root CA first
        config, bundle, written = self._restore(
            pem('CA') + pem('X') + pem('Y'))

        self.assertTrue(config.restore(bundle, True))

        self.assertEqual(written, [''.join(pem('X') + pem('Y'))])
        self.assertEqual(self.manager.commands(), [[
            'cp', '___csmake-pypi-bundle-del-cert.temp', bundle]])
        self.assertEqual(self.certManager.certbundles(), [])
        self.assertFalse(os.path.exists('___csmake-pypi-bundle-del-cert.temp'))

    def test_bundleConfigRestore_findsTheRootCaInTheMiddleOfTheBundle(self):
        config, bundle, written = self._restore(
            pem('X') + pem('CA') + pem('Y'))

        config.restore(bundle, True)

        self.assertEqual(written, [''.join(pem('X') + pem('Y'))])

    def test_bundleConfigRestore_aBundleWithoutOurCaIsLeftAlone(self):
        config, bundle, written = self._restore(pem('X') + pem('Y'))

        self.assertTrue(config.restore(bundle, True))

        self.assertEqual(written, [])
        self.assertEqual(self.manager.commands(), [])

    def test_bundleConfigRestore_aFailedCopyBackIsOnlyAWarning(self):
        config, bundle, written = self._restore(
            pem('CA') + pem('X'), cp_result=1)

        self.assertTrue(config.restore(bundle, True))

        self.assertEqual(len(self.log.messages('warning')), 1)
        self.assertFalse(os.path.exists('___csmake-pypi-bundle-del-cert.temp'))

    def test_bundleConfigRestore_aMissingRootCaFileIsAnError(self):
        config, bundle, _ = self._restore(pem('CA'))
        os.remove(self.certManager.rootCACertPath)

        with self.assertRaises(FileNotFoundError):
            config.restore(bundle, True)

    def test_fauxCertDirectory_getsAReadmeExplainingWhyItExists(self):
        directory = os.path.join(
            self.tmp, PypiProvider.SSLCertificateManager.FAUX_CERT_DIR)
        os.mkdir(directory)
        config = self._config(
            PypiProvider.FauxCertBundleTargetDirectory, self.tmp)

        config.ensure()

        with open(os.path.join(directory, 'README')) as f:
            self.assertEqual(
                f.read(), "This is a temporary directory for the purpose of "
                          "supporting the PypiFacade")


class ScriptedService(PypiProvider.PypiService):
    """A PypiService whose stopListening is read from a script, so the accept
    loop can be driven without threads.  Each read of stopListening (the loop
    condition, and the SSLError branch) pops the next value; the last value
    repeats."""

    def __init__(self, reads, log):
        self._reads = list(reads)
        self.log = log
        self.accepting = False
        self.certManager = unittest.mock.Mock(name='certManager')

    @property
    def stopListening(self):
        return self._reads.pop(0) if len(self._reads) > 1 else self._reads[0]

    @stopListening.setter
    def stopListening(self, value):
        self._reads = [value]


class testPypiTlsAcceptLoop_py3(unittest.TestCase):

    def setUp(self):
        self.log = support.FakeLog()
        self.proxy = unittest.mock.patch.object(PypiProvider, 'PypiProxyThread')
        self.proxy_class = self.proxy.start()
        self.addCleanup(self.proxy.stop)

    def _service(self, *reads):
        service = ScriptedService(reads, self.log)
        service.listener = unittest.mock.Mock(name='listener')
        return service

    def test_startListening_listensOnTheAlreadyWrappedPortSocket(self):
        service = self._service(False)
        service.port = types.SimpleNamespace(
            sock='the-tls-socket', interface='127.0.0.1', port=8443)
        service.listener = None
        sock = unittest.mock.Mock()
        service.port.sock = sock

        service._startListening()

        self.assertIs(service.listener, sock)
        sock.listen.assert_called_once_with(100)
        self.assertEqual(self.log.messages('info'),
                         ['Pypi Facade listening on 127.0.0.1:8443'])

    def test_loop_aCompletedHandshakeStartsAProxyThread(self):
        service = self._service(False, True)
        seen = []
        service.listener.accept.side_effect = lambda: (
            seen.append(service.accepting) or ('conn', ('127.0.0.1', 5000)))

        service._listeningLoop()

        self.proxy_class.assert_called_once_with(
            'conn', ('127.0.0.1', 5000), service)
        self.proxy_class.return_value.start.assert_called_once_with()
        self.assertEqual(seen, [True])
        self.assertFalse(service.accepting)
        self.assertEqual([], self.log.problems)

    def test_loop_everyConnectionGetsItsOwnThreadInOrder(self):
        service = self._service(False, False, True)
        service.listener.accept.side_effect = [
            ('conn1', ('127.0.0.1', 1)), ('conn2', ('127.0.0.1', 2))]

        service._listeningLoop()

        self.assertEqual(
            [c[0][:2] for c in self.proxy_class.call_args_list],
            [('conn1', ('127.0.0.1', 1)), ('conn2', ('127.0.0.1', 2))])
        self.assertEqual(self.proxy_class.return_value.start.call_count, 2)

    def test_loop_aFailedHandshakeIsLoggedWithTheCertsAndServingContinues(self):
        # reads: loop test, SSLError branch (not stopping), loop test,
        # loop test (stop)
        service = self._service(False, False, False, True)
        service.listener.accept.side_effect = [
            ssl.SSLError('handshake failure'), ('conn', ('127.0.0.1', 5000))]

        service._listeningLoop()

        self.assertEqual(self.log.messages('exception')[0].split('\n')[0],
                         'An ssl error occurred')
        service.certManager.prettyPrintDevDebug.assert_called_once_with()
        self.assertEqual(self.proxy_class.call_count, 1)

    def test_loop_anSslErrorWhileShuttingDownIsOnlyDebugLogged(self):
        service = self._service(False, True)
        service.listener.accept.side_effect = ssl.SSLError('closed')

        service._listeningLoop()

        self.assertEqual(self.log.problems, [])
        self.assertEqual(len(self.log.messages('debug')), 1)
        service.certManager.prettyPrintDevDebug.assert_not_called()
        self.proxy_class.assert_not_called()

    def test_loop_anAcceptErrorIsLoggedAndServingContinues(self):
        service = self._service(False, False, True)
        service.listener.accept.side_effect = [
            socket.error(24, 'Too many open files'),
            ('conn', ('127.0.0.1', 5000))]

        service._listeningLoop()

        self.assertIn('The handler for the request failed to start',
                      self.log.problems[0])
        self.assertEqual(self.proxy_class.call_count, 1)

    def test_loop_aThreadThatCannotBeCreatedIsLoggedAndServingContinues(self):
        service = self._service(False, False, True)
        service.listener.accept.side_effect = [
            ('conn1', ('127.0.0.1', 1)), ('conn2', ('127.0.0.1', 2))]
        self.proxy_class.side_effect = [RuntimeError('no controller'),
                                        unittest.mock.DEFAULT]

        service._listeningLoop()

        self.assertEqual(len(self.log.problems), 1)
        self.assertEqual(self.proxy_class.call_count, 2)
        self.proxy_class.return_value.start.assert_called_once_with()

    def test_loop_doesNotAcceptOnceStopRequested(self):
        service = self._service(True)

        service._listeningLoop()

        service.listener.accept.assert_not_called()

    def test_cleanup_shutsDownThenClosesTheListener(self):
        service = self._service(False)

        service._cleanup()

        self.assertEqual(
            [c[0] for c in service.listener.method_calls],
            ['shutdown', 'close'])
        service.listener.shutdown.assert_called_once_with(socket.SHUT_RDWR)

    def test_cleanup_stillClosesWhenShutdownFails(self):
        service = self._service(False)
        service.listener.shutdown.side_effect = OSError(57, 'not connected')

        service._cleanup()

        service.listener.close.assert_called_once_with()
        self.assertIn('shutdown of pypi facade listener failed',
                      self.log.messages('info'))

    def test_cleanup_aCloseFailureIsOnlyLogged(self):
        service = self._service(False)
        service.listener.close.side_effect = OSError('bad descriptor')

        service._cleanup()

        self.assertEqual(self.log.problems, [])


if __name__ == '__main__':
    unittest.main()
