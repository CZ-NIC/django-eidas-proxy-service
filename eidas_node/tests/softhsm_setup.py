"""
Testing the PKCS#11 shim layer.
Heavily inspired by from https://github.com/IdentityPython/pyXMLSecurity by leifj
under licence "As is", see https://github.com/IdentityPython/pyXMLSecurity/blob/master/LICENSE.txt
"""

import logging
import os
import shutil
import subprocess
import tempfile
import traceback
import unittest
from typing import Dict, List, Optional, Tuple

from eidas_node.tests.constants import DATA_DIR


def paths_for_component(component: str, default_paths: List[str]):
    env_path = os.environ.get(component)
    return [env_path] if env_path else default_paths


def find_alts(component_name, alts: List[str]) -> str:
    for a in alts:
        if os.path.exists(a):
            return a
    raise unittest.SkipTest("Required component is missing: {}".format(component_name))


def run_cmd(args, softhsm_conf=None) -> Tuple[bytes, bytes]:
    env = {}
    if softhsm_conf is not None:
        env['SOFTHSM_CONF'] = softhsm_conf
        env['SOFTHSM2_CONF'] = softhsm_conf
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out, err = proc.communicate()
    if err is not None and len(err) > 0:
        logging.error(err)
    if out is not None and len(out) > 0:
        logging.debug(out)
    rv = proc.wait()
    if rv:
        with open(softhsm_conf) as f:
            conf = f.read()
        msg = '[cmd: {cmd}] [code: {code}] [stdout: {out}] [stderr: {err}] [config: {conf}]'
        msg = msg.format(
            cmd=" ".join(args), code=rv, out=out.strip(), err=err.strip(), conf=conf,
        )
        raise RuntimeError(msg)
    return out, err


component_default_paths: Dict[str, List[str]] = {
    'P11_MODULE': [
        '/usr/lib/softhsm/libsofthsm2.so',
        '/usr/lib/x86_64-linux-gnu/softhsm/libsofthsm2.so',
        '/usr/lib/softhsm/libsofthsm.so',
        '/usr/lib64/softhsm/libsofthsm2.so',
    ],
    'P11_ENGINE': [
        '/usr/lib/ssl/engines/libpkcs11.so',
        '/usr/lib/engines/engine_pkcs11.so',
        '/usr/lib/x86_64-linux-gnu/engines-1.1/pkcs11.so',
        '/usr/lib64/engines-1.1/pkcs11.so',
        '/usr/lib64/engines-1.1/libpkcs11.so',
        '/usr/lib64/engines-3/pkcs11.so',
        '/usr/lib64/engines-3/libpkcs11.so',
        '/usr/lib/x86_64-linux-gnu/engines-3/pkcs11.so',
        '/usr/lib/x86_64-linux-gnu/engines-3/libpkcs11.so',
    ],
    'PKCS11_TOOL': [
        '/usr/bin/pkcs11-tool',
    ],
    'SOFTHSM': [
        '/usr/bin/softhsm2-util',
        '/usr/bin/softhsm',
    ],
    'OPENSSL': [
        '/usr/bin/openssl',
    ],
}

component_path: Dict[str, str] = {
    component_name: find_alts(component_name, paths_for_component(component_name, default_paths))
    for component_name, default_paths in component_default_paths.items()
}

softhsm_version = 1
if component_path['SOFTHSM'].endswith('softhsm2-util'):
    softhsm_version = 2

openssl_version = subprocess.check_output([component_path['OPENSSL'],
                                          'version']
                                          )[8:11].decode()

p11_test_files: List[str] = []
softhsm_conf: Optional[str] = None
softhsm_db: Optional[str] = None


def _temp_file() -> str:
    f = tempfile.NamedTemporaryFile(delete=False)
    p11_test_files.append(f.name)
    return f.name


def _temp_dir() -> str:
    d = tempfile.mkdtemp()
    p11_test_files.append(d)
    return d


@unittest.skipIf(component_path['P11_MODULE'] is None, "SoftHSM PKCS11 module not installed")
def setup() -> None:
    logging.debug("Creating test pkcs11 token using softhsm")
    try:
        global softhsm_conf
        softhsm_conf = _temp_file()
        logging.debug("Generating softhsm.conf")
        with open(softhsm_conf, "w") as f:
            if softhsm_version == 2:
                softhsm_db = _temp_dir()
                f.write("""
# Generated by test
directories.tokendir = %s
objectstore.backend = file
log.level = DEBUG
""" % softhsm_db)
            else:
                softhsm_db = _temp_file()
                f.write("""
# Generated by test
0:%s
""" % softhsm_db)

        logging.debug("Initializing the token")
        out, err = run_cmd([component_path['SOFTHSM'],
                            '--slot', '0',
                            '--label', 'test',
                            '--init-token',
                            '--pin', 'secret1',
                            '--so-pin', 'secret2'],
                           softhsm_conf=softhsm_conf)

        # logging.debug("Generating 1024 bit RSA key in token")
        # run_cmd([component_path['PKCS11_TOOL'],
        #          '--module', component_path['P11_MODULE'],
        #          '-l',
        #          '-k',
        #          '--key-type', 'rsa:1024',
        #          '--id', 'a1b2',
        #          '--label', 'test',
        #          '--pin', 'secret1'], softhsm_conf=softhsm_conf)

        hash_priv_key = _temp_file()
        logging.debug("Converting test private key to format for softhsm")
        run_cmd([component_path['OPENSSL'], 'pkcs8',
                 '-topk8',
                 '-inform', 'PEM',
                 '-outform', 'PEM',
                 '-nocrypt',
                 '-in', DATA_DIR / 'key.pem',
                 '-out', hash_priv_key], softhsm_conf=softhsm_conf)

        logging.debug("Importing the test key to softhsm")
        run_cmd([component_path['SOFTHSM'],
                 '--import', hash_priv_key,
                 '--token', 'test',
                 '--id', 'a1b2',
                 '--label', 'test',
                 '--pin', 'secret1'],
                softhsm_conf=softhsm_conf)
        run_cmd([component_path['PKCS11_TOOL'],
                 '--module', component_path['P11_MODULE'],
                 '-l',
                 '--pin', 'secret1', '-O'], softhsm_conf=softhsm_conf)
        signer_cert_pem = _temp_file()
        openssl_conf = _temp_file()
        logging.debug("Generating OpenSSL config for version {}".format(openssl_version))
        with open(openssl_conf, "w") as f:
            # Might be needed with some versions of openssl, but in more recent versions dynamic_path breaks it.
            # dynamic_path = (
            #     "dynamic_path = %s" % component_path['P11_ENGINE']
            #     if openssl_version.startswith(b'1.')
            #     else ""
            # )
            f.write("\n".join([
                "openssl_conf = openssl_def",
                "[openssl_def]",
                "engines = engine_section",
                "[engine_section]",
                "pkcs11 = pkcs11_section",
                "[req]",
                "distinguished_name = req_distinguished_name",
                "[req_distinguished_name]",
                "[pkcs11_section]",
                "engine_id = pkcs11",
                # dynamic_path,
                "MODULE_PATH = %s" % component_path['P11_MODULE'],
                "PIN = secret1",
                "init = 0",
            ]))

        with open(openssl_conf, "r") as f:
            logging.debug('-------- START DEBUG openssl_conf --------')
            logging.debug(f.readlines())
            logging.debug('-------- END DEBUG openssl_conf --------')
        logging.debug('-------- START DEBUG paths --------')
        logging.debug(run_cmd(['ls', '-ld', component_path['P11_ENGINE']]))
        logging.debug(run_cmd(['ls', '-ld', component_path['P11_MODULE']]))
        logging.debug('-------- END DEBUG paths --------')

        signer_cert_der = _temp_file()

        logging.debug("Generating self-signed certificate")
        run_cmd([component_path['OPENSSL'], 'req',
                 '-new',
                 '-x509',
                 '-subj', "/CN=Test Signer",
                 '-engine', 'pkcs11',
                 '-config', openssl_conf,
                 '-keyform', 'engine',
                 '-key', 'label_test',
                 '-passin', 'pass:secret1',
                 '-out', signer_cert_pem], softhsm_conf=softhsm_conf)

        run_cmd([component_path['OPENSSL'], 'x509',
                 '-inform', 'PEM',
                 '-outform', 'DER',
                 '-in', signer_cert_pem,
                 '-out', signer_cert_der], softhsm_conf=softhsm_conf)

        logging.debug("Importing certificate into token")

        run_cmd([component_path['PKCS11_TOOL'],
                 '--module', component_path['P11_MODULE'],
                 '-l',
                 '--slot-index', '0',
                 '--id', 'a1b2',
                 '--label', 'test',
                 '-y', 'cert',
                 '-w', signer_cert_der,
                 '--pin', 'secret1'], softhsm_conf=softhsm_conf)

        # TODO: Should be teardowned in teardown:
        os.environ['SOFTHSM_CONF'] = softhsm_conf
        os.environ['SOFTHSM2_CONF'] = softhsm_conf

    except Exception as ex:
        print("-" * 64)
        traceback.print_exc()
        print("-" * 64)
        logging.error("PKCS11 tests disabled: unable to initialize test token: %s" % ex)
        raise ex


def teardown() -> None:
    global p11_test_files
    for o in p11_test_files:
        if os.path.exists(o):
            if os.path.isdir(o):
                shutil.rmtree(o)
            else:
                os.unlink(o)
    p11_test_files = []
