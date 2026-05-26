import argparse
import hashlib
import logging
import pathlib
import shlex
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import textwrap
import typing

random = secrets.SystemRandom()

class LogFormatter(logging.Formatter):
    '''Formats log messages nicely'''
    FORMATTERS = {
        level: logging.Formatter(f'{prefix}%(message)s{suffix}')
        for level, (prefix, suffix) in {
            logging.DEBUG:    ('\x1b[37;2m', '\x1b[0m'),
            logging.INFO:     ('',           ''),
            logging.WARNING:  ('\x1b[33m',   '\x1b[0m'),
            logging.ERROR:    ('\x1b[31m',   '\x1b[0m'),
            logging.CRITICAL: ('\x1b[31;1m', '\x1b[0m'),
        }.items()
    }

    def format(self, record):
        formatter = LogFormatter.FORMATTERS.get(record.levelno) or LogFormatter.FORMATTERS[logging.INFO]
        return formatter.format(record)


def run_command(*command: str | pathlib.Path, check: bool = True):
    logger = logging.getLogger(__name__)
    logger.debug('+ ' + ' '.join(shlex.quote(str(arg)) for arg in command))
    process = subprocess.run([str(arg) for arg in command], capture_output=True, check=check)
    logger.debug(process.stdout.decode(errors='ignore'))
    return process

def output(*command: str | pathlib.Path):
    '''Runs a command and returns its output'''
    return run_command(*command).stdout

def check(*command: str | pathlib.Path):
    '''Runs a command and returns whether it completed successfully'''
    return run_command(*command, check=False).returncode == 0

def run(*command: str | pathlib.Path):
    '''Runs a command'''
    run_command(*command)

def hash_file(path: pathlib.Path, hash_function: typing.Callable[[], typing.Any] = hashlib.sha256) -> bytes:
    hasher = hash_function()
    with open(path, 'rb') as stream:
        while True:
            try:
                data = stream.read(8192)
                if not data:
                    break
            except EOFError:
                break
            hasher.update(data)
    return hasher.digest()


class BuildRun:
    '''The state of a build run'''
    def __init__(self, log: logging.Logger, skip: set['Target'] = set(), force: set['Target'] = set(), force_all: bool = False):
        self.log = log
        self._skip = skip
        self._force = force
        self._force_all = force_all
        self._active: set['Target'] = set()
        self._finished: set['Target'] = set()

    def is_skipped(self, target: 'Target'):
        return target in self._skip

    def is_active(self, target: 'Target'):
        return target in self._active

    def is_finished(self, target: 'Target'):
        return target in self._finished

    def force(self, target: 'Target') -> bool:
        return self._force_all or target in self._force

    def enter(self, target: 'Target'):
        self._active.add(target)

    def leave(self, target: 'Target'):
        self._active.remove(target)
        self._finished.add(target)


class Target:
    '''A target'''
    __by_name = {}

    @staticmethod
    def find(name: str) -> 'Target':
        target = Target.__by_name.get(name, None)
        if target is not None:
            return target
        raise KeyError(f'No target with the name {name!r} exists')

    def __init__(self, name: str, dependencies: list['Target'] = [], always: bool = False):
        if name in Target.__by_name:
            raise KeyError(f'A target with the name {name!r} already exists')
        Target.__by_name[name] = self

        self.name = name
        self.dependencies = dependencies
        self.always = always
        self._formatted = f'\x1b[7m{name}\x1b[27m'

    def make(self, run: BuildRun) -> bool:
        '''Builds the target. Returns True if anything changed and dependent targets need to be built also.'''
        if run.is_active(self):
            run.log.warning(f'Skipping {self._formatted} (dependency loop detected)')
        elif run.is_skipped(self):
            run.log.debug(f'Skipping {self._formatted} (explicit skip)')
        elif not self.always and run.is_finished(self):
            run.log.debug(f'Not re-building {self._formatted} (already built this run)')
        else:
            run.enter(self)
            dependency_changed = False
            for dependency in self.dependencies:
                dependency_changed |= dependency.make(run)
            run.leave(self)
            if dependency_changed:
                run.log.info(f'Building {self._formatted} (dependency changed)')
            elif not self.up_to_date():
                run.log.info(f'Building {self._formatted} (not up-to-date)')
            elif run.force(self):
                run.log.info(f'Building {self._formatted} (explicitly requested)')
            else:
                run.log.info(f'Not rebuilding {self._formatted} (target is up-to-date)')
                return False
            self.build()
            return True
        return False

    def build(self):
        '''(Re-)builds this target'''
        pass

    def up_to_date(self) -> bool:
        '''Checks whether this target is still up-to-date'''
        return True

    def output(self, name: str | None) -> pathlib.Path | None:
        '''Returns the path for the named output, or the default output'''
        return None


class Certificates:
    @staticmethod
    def check_key_for_certificate(*, certificate: pathlib.Path, key: pathlib.Path) -> bool:
        '''Checks that the key belongs to the certificate'''
        if not certificate.is_file() or not key.is_file():
            return False
        # Check if the key matches the certificate still
        crt_modulus = output('openssl', 'x509', '-noout', '-modulus', '-in', certificate)
        key_modulus = output('openssl', 'rsa', '-noout', '-modulus', '-in', key)
        return crt_modulus == key_modulus

    @staticmethod
    def check_is_signed_by(*, certificate: pathlib.Path, ca: pathlib.Path) -> bool:
        '''Checks that the certificate is signed by the given CA certificate'''
        return certificate.is_file() and ca.is_file() and check('openssl', 'verify', '-CAfile', ca, ca, certificate)

    @staticmethod
    def get_fingerprint(certificate: pathlib.Path) -> str:
        raw_fingerprint = output('openssl', 'x509', '-noout', '-in', certificate, '-sha256', '-fingerprint')
        raw_fingerprint = raw_fingerprint.decode()
        PREFIX = 'sha256 Fingerprint='
        if not raw_fingerprint.startswith(PREFIX):
            raise ValueError(f'Unexpected output for certificate fingerprint: {raw_fingerprint!r}')
        fingerprint = raw_fingerprint[len(PREFIX):].strip().replace(':', '').lower()
        if len(fingerprint) != hashlib.sha256().digest_size * 2 or any(char not in '0123456789abcdef' for char in fingerprint):
            raise ValueError(f'Invalid fingerprint: {fingerprint}')
        return fingerprint

    @staticmethod
    def jks_get_fingerprint(keystore: pathlib.Path, alias: str) -> str:
        raw_fingerprint = output('keytool', '-list', '-keystore', keystore, '-storepass', 'changeit', '-alias', alias)
        raw_fingerprint = raw_fingerprint.decode()
        PREFIX = 'Certificate fingerprint (SHA-256): '
        for line in raw_fingerprint.split('\n'):
            if line.startswith(PREFIX):
                fingerprint = line[len(PREFIX):].replace(':', '').lower()
                if len(fingerprint) != hashlib.sha256().digest_size * 2 or any(char not in '0123456789abcdef' for char in fingerprint):
                    raise ValueError(f'Invalid fingerprint: {fingerprint:!r}')
                return fingerprint
        raise ValueError(f'No fingerprint found in keytool output: {raw_fingerprint!r}')


class CACertificate(Target):
    '''Generates a CA certificate'''
    def __init__(self, name: str, *, certificate: pathlib.Path, key: pathlib.Path, rsa_bits: int = 4096, days: int = 90, subject: str = '/'):
        super().__init__(name)
        self.certificate = certificate
        self.key = key
        self.rsa_bits = rsa_bits
        self.days = days
        self.subject = subject

    def up_to_date(self) -> bool:
        return self.certificate.is_file() and self.key.is_file() and Certificates.check_key_for_certificate(certificate=self.certificate, key=self.key)

    def build(self):
        self.certificate.parent.mkdir(parents=True, exist_ok=True)
        self.key.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.cnf') as config:
            config.write(textwrap.dedent('''
                [ca_certificate]
                subjectKeyIdentifier = hash
                authorityKeyIdentifier = keyid, issuer
                basicConstraints = critical, CA:true
                keyUsage = critical, digitalSignature, cRLSign, keyCertSign
            '''))
            config.flush()
            config = pathlib.Path(config.name).resolve()
            run('openssl', 'req', '-x509', '-newkey', f'rsa:{self.rsa_bits}', '-nodes', '-days', f'{self.days}', '-extensions', 'ca_certificate', '-config', config, '-subj', self.subject, '-keyout', self.key, '-out', self.certificate)

    def output(self, name: str | None) -> pathlib.Path | None:
        match name:
            case 'certificate' | None: return self.certificate
            case 'key': return self.key
            case _: return None

class TLSCertificate(Target):
    '''Generates a normal TLS certificate and signs it with the specified CA certificate target'''
    def __init__(self, name: str, *, ca: CACertificate, certificate: pathlib.Path, key: pathlib.Path, common_name: str, subject_alt_name: str, rsa_bits: int = 4096, days: int = 90):
        super().__init__(name, dependencies=[ca])
        self.ca = ca
        self.certificate = certificate
        self.key = key
        self.rsa_bits = rsa_bits
        self.days = days
        self.cn = common_name
        self.san = subject_alt_name

    def up_to_date(self) -> bool:
        return self.certificate.is_file() and self.key.is_file() and Certificates.check_key_for_certificate(certificate=self.certificate, key=self.key) and Certificates.check_is_signed_by(certificate=self.certificate, ca=self.ca.certificate)

    def build(self):
        self.certificate.parent.mkdir(parents=True, exist_ok=True)
        self.key.parent.mkdir(parents=True, exist_ok=True)
        serial = '0x' + hashlib.sha256(self.name.encode()).hexdigest()[:16].upper()
        with tempfile.NamedTemporaryFile(suffix='.csr') as csr, tempfile.NamedTemporaryFile(mode='w+', suffix='.cnf') as config:
            config.write(textwrap.dedent(f'''
                [tls_certificate]
                subjectKeyIdentifier = hash
                authorityKeyIdentifier = keyid, issuer
                basicConstraints = critical, CA:false
                keyUsage = critical, digitalSignature
                extendedKeyUsage = critical, serverAuth, clientAuth
                subjectAltName = {self.san}
            '''))
            config.flush()
            csr = pathlib.Path(csr.name).resolve()
            config = pathlib.Path(config.name).resolve()
            run('openssl', 'req', '-newkey', f'rsa:{self.rsa_bits}', '-nodes', '-subj', f'/CN={self.cn}', '-keyout', self.key, '-out', csr)
            run('openssl', 'x509', '-req', '-days', f'{self.days}', '-set_serial', serial, '-in', csr, '-out', self.certificate, '-CA', self.ca.certificate, '-CAkey', self.ca.key, '-extensions', 'tls_certificate', '-extfile', config)

    def output(self, name: str | None) -> pathlib.Path | None:
        match name:
            case 'certificate' | None: return self.certificate
            case 'key': return self.key
            case _: return None


class RandomFile(Target):
    '''Generates a file with random data'''
    def __init__(self, name: str, *, path: pathlib.Path, length: int, alphabet: str = string.ascii_letters + string.digits):
        super().__init__(name)
        self.path = path
        self.length = length
        self.alphabet = alphabet

    def up_to_date(self) -> bool:
        return self.path.is_file() and len(self.path.read_bytes()) == self.length

    def build(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(''.join(random.choices(self.alphabet, k = self.length)))

    def output(self, name: str | None) -> pathlib.Path | None:
        match name:
            case 'file' | None: return self.path
            case _: return None


class FixedFile(Target):
    '''Creates a file with fixed contents'''
    def __init__(self, name: str, *, path: pathlib.Path, content: str | bytes):
        super().__init__(name)
        self.path = path
        self.content = content if isinstance(content, bytes) else content.encode()

    def up_to_date(self) -> bool:
        return self.path.is_file() and self.path.read_bytes() == self.content

    def build(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self.content)

    def output(self, name: str | None) -> pathlib.Path | None:
        match name:
            case 'file' | None: return self.path
            case _: return None


class CopyFile(Target):
    '''Copies a file'''
    def __init__(self, name: str, *, source: Target | pathlib.Path, target: pathlib.Path, source_output: str | None = None):
        super().__init__(name, [source] if isinstance(source, Target) else [])
        self.target = target
        if not isinstance(source, Target):
            assert source_output is None, 'Cannot specify source_output for CopyFile if source is already a path'
            self.source = source
        else:
            path = source.output(source_output)
            assert path is not None, f'Source {source.name} does not have an output named "{source_output}"'
            self.source = path

    def up_to_date(self) -> bool:
        if not self.source.exists():
            raise RuntimeError(f'{self.name}: Cannot update target file {self.target} from non-existent source file {self.source}')
        if not self.source.is_file():
            raise RuntimeError(f'{self.name}: Source file {self.source} is not a file')
        if not self.target.exists():
            return False
        if not self.target.is_file():
            raise RuntimeError(f'{self.name}: Target file {self.target} is not a file')
        if self.target.stat().st_mode != self.source.stat().st_mode:
            return False # Mode changed
        if hash_file(self.target) != hash_file(self.source):
            return False # Contents changed
        return True

    def build(self):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.source, self.target)

    def output(self, name: str | None) -> pathlib.Path | None:
        match name:
            case 'file' | None: return self.target
            case _: return None


class Directory(Target):
    '''Ensures that a directory exists (though you should prefer ensuring directory creation directly in other targets)'''
    def __init__(self, name: str, path: pathlib.Path):
        super().__init__(name)
        self.path = path

    def up_to_date(self) -> bool:
        return self.path.is_dir()

    def build(self):
        self.path.mkdir(parents=True, exist_ok=True)

    def output(self, name: str | None) -> pathlib.Path | None:
        match name:
            case 'directory' | None: return self.path
            case _: return None


class RecursiveChown(Target):
    '''Recursively changes the owner and group of a directory tree'''
    def __init__(self, name: str, dependencies: list[Target] = [], *, path: pathlib.Path, uid: int, gid: int):
        super().__init__(name, dependencies)
        self.path = path
        self.uid = uid
        self.gid = gid

    def up_to_date(self) -> bool:
        return False # Will always run

    def build(self):
        if not self.path.exists():
            raise RuntimeError(f'{self.name}: Target directory {self.path} does not exist')
        if sys.version_info >= (3, 13):
            chown = lambda path: shutil.chown(path, self.uid, self.gid, follow_symlinks=False)
        else:
            chown = lambda path: shutil.chown(path, self.uid, self.gid) if not path.is_symlink() else None
        if sys.version_info >= (3, 12):
            walk = type(self.path).walk
        else:
            import os
            walk = lambda path, top_down=True: ((pathlib.Path(dirpath), dirnames, filenames) for dirpath, dirnames, filenames in os.walk(path, topdown=top_down))
        if self.path.is_dir():
            for directory, subdirectories, files in walk(self.path, top_down=False):
                for file in files:
                    chown(directory / file)
                for subdirectory in subdirectories:
                    chown(directory / subdirectory)
                chown(directory)
        else:
            chown(self.path)



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('state', help='State directory', type=pathlib.Path, default=pathlib.Path('/state'))
    parser.add_argument('-f', '--force', help='Forcibly regenerate everything', action='store_true')
    parser.add_argument('--create', help='Create the state directory if it does not exist', action='store_true')
    parser.add_argument('--log-level', help='Log level', choices=('debug', 'info', 'warning', 'error', 'critical'), default='info')
    parser.add_argument('--skip', help='Skip this target', metavar='TARGET', action='append', default=[])
    parser.add_argument('targets', help='Specific targets to build', nargs='*')
    args = parser.parse_args()

    logger = logging.getLogger(__name__)
    handler = logging.StreamHandler()
    handler.setFormatter(LogFormatter())
    logger.setLevel(args.log_level.upper())
    logger.addHandler(handler)

    state = args.state
    if not state.exists():
        if args.create:
            state.mkdir()
        else:
            raise RuntimeError(f'State directory {args.state} does not exist (did you forget to mount it?)')

    # Generate a CA certificate and signing key
    ca = CACertificate('CA certificate', certificate=state / 'internal/ca/ca.crt', key=state / 'internal/ca/ca.key', subject='/CN=CZECHPOINT INC. CORPORATE CA')

    # Setup for the DB: We need a TLS certificate, an admin password, user passwords, and a storage directory.
    db_tls   = TLSCertificate('Database TLS certificates', ca=ca, certificate=state / 'db/tls/tls.crt', key=state / 'db/tls/tls.key', common_name='db', subject_alt_name='DNS:db,IP:10.0.0.3')
    db_admin = RandomFile('Database password (admin)', path=state / 'db/secrets/admin', length=32)
    db_auth  = RandomFile('Database password (authentication)', path=state / 'db/secrets/authentication', length=32)
    db_ftp   = RandomFile('Database password (ftp)', path=state / 'db/secrets/ftp', length=32)
    db_stats = RandomFile('Database password (stats)', path=state / 'db/secrets/stats', length=32)
    db_data  = Directory('Database storage directory', state / 'db/data')
    db_perms = RecursiveChown('Database file permissions', [db_tls], path=state / 'db/tls', uid=999, gid=999)
    db = Target('Database setup', [db_tls, db_admin, db_auth, db_ftp, db_stats, db_data, db_perms])

    # Setup for the FTP server: We need a TLS certificate, the CA certificate, and a storage directory
    ftp_tls = TLSCertificate('FTP TLS certificates', ca=ca, certificate=state / 'ftp/tls/tls.crt', key=state / 'ftp/tls/tls.key', common_name='ftp', subject_alt_name='DNS:ftp,IP:10.0.0.2')
    ftp_ca_cert = CopyFile('FTP CA certificate', source=ca, target=state / 'ftp/tls/ca.crt')
    ftp_data = Directory('FTP storage directory', state / 'ftp/data')
    ftp_db = CopyFile('FTP database password', source=db_ftp, target=state / 'ftp/secrets/db')
    ftp = Target('FTP', [ftp_tls, ftp_ca_cert, ftp_data, ftp_db])

    # SNMP
    snmp_community = RandomFile('SNMP auth community', path=state / 'snmp/secrets/auth_community', length=32)
    snmp_data = Directory('Agent persistent storage', state / 'snmp/data')
    snmp_perms = RecursiveChown('Agent storage permissions', [snmp_data], path=state / 'snmp/data', uid=1161, gid=1161)
    snmp = Target('SNMP', [snmp_community, snmp_data, snmp_perms])

    # Setup for the firewall: We need the CA certificate.
    firewall_ca_cert = CopyFile('Firewall CA certificate', source=ca, target=state / 'firewall/tls/ca.crt')
    firewall_db = CopyFile('Frontend database password', source=db_auth, target=state / 'firewall/secrets/db')
    firewall = Target('Firewall', [firewall_ca_cert, firewall_db])

    # The default target just initializes everything
    default = Target('Default', [ca, ftp, db, snmp, firewall])

    # Build whatever we need or want to build
    skip_targets = set(Target.find(skip) for skip in args.skip)
    want_targets = set(Target.find(want) for want in (args.targets or ['Default']))
    current_run = BuildRun(logger, skip=skip_targets, force_all=args.force)
    for target in want_targets:
        target.make(current_run)
