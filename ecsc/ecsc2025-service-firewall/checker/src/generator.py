import dataclasses
import json
import random
import os
import pathlib
import secrets
import typing

from string import ascii_letters, digits, printable

from . import ftp, suspicious, types



@dataclasses.dataclass
class Config:
    '''Thresholds to fine-tune the biases in the randomness'''
    filename_is_generic_injection: float = 0.05
    filename_is_suspicious: float = 0.1
    filename_has_extension: float = 0.1
    string_include_suspicious: float = 0.15


# Load an override config if one is specified; otherwise, just use the defaults

if (config_file := os.getenv('GENERATOR_CONFIG')) is not None:
    config = Config(**json.loads(pathlib.Path(config_file).read_text()))
else:
    config = Config()


# Re-exports of things that are not in `secrets`.

random = secrets.SystemRandom()
sample = random.sample

T = typing.TypeVar('T')

def shuffled(iterable: typing.Iterable[T]) -> list[T]:
    '''Shuffles an iterable into a list.'''
    seq = list(iterable)
    random.shuffle(seq)
    return seq


# Custom generators

def bit() -> bool:
    '''Generates a random bit.'''
    return secrets.randbits(1) == 1

def bias(probability: float) -> bool:
    '''Generates a random biased bit that is True with the given probability.'''
    if probability <= 0.0:
        return False
    elif probability >= 1.0:
        return True
    return secrets.randbits(32) < 2**32 * probability

def select(probabilities: dict[T, float]) -> T | None:
    '''Selects an entry from the given probability map. The sum of probabilities must be <= 1.0, or they may be off.'''
    keys = []
    weights = []
    total = 0.0
    for key, probability in probabilities.items():
        keys.append(key)
        weights.append(int(2**32 * probability))
        total += probability
    if total < 1.0:
        keys.append(None)
        weights.append(int(2**32 * (1.0 - total)))
    return random.sample(keys, 1, counts=weights)[0]

def number(min_value: int, max_value: int) -> int:
    '''Returns a number in the given range (inclusive).'''
    return secrets.randbelow(max_value + 1 - min_value) + min_value

def pad(min_length: int, max_length: int, value: str, *, safe: bool = False, always: bool = False) -> str:
    '''Pads a string to a random length in the given range with random data (if padding is needed).'''
    if len(value) < min_length or always:
        alphabet = (ascii_letters + digits) if safe else printable
        target = number(min_length, max_length)
        if len(value) < target:
            padding = ''.join(random.choices(alphabet, k=target - len(value)))
            split = number(0, len(padding))
            return padding[:split] + value + padding[split:]
    return value

def safe_string(min_bytes: int = 8, max_bytes: int = 16) -> str:
    '''Generates a random "safe" string for the checker to use as a username or password.'''
    return secrets.choice([secrets.token_hex, secrets.token_urlsafe])(number(min_bytes, max_bytes))

def string(min_length: int, max_length: int) -> str:
    '''Generates a random string with all printable ASCII characters.'''
    length = number(min_length, max_length)
    if bias(config.string_include_suspicious):
        return pad(min_length, max_length, suspicious.string(0, max_length), always=True)
    else:
        return ''.join(random.choices(printable, k=length))

def filename(min_length: int = 4, max_length: int = 24, *, directory: bool = False, exclude: set[str] = set()) -> str:
    '''Generates a random filename.'''
    while True:
        match select({'suspicious': config.filename_is_suspicious, 'generic': config.filename_is_generic_injection}):
            case 'suspicious':
                name = suspicious.directory(min_length, max_length) if directory else suspicious.filename(min_length, max_length)
            case 'generic':
                name = pad(min_length, max_length, suspicious.string(0, max_length, banned_chars=suspicious.unsafe_in_filenames), safe=True)
            case _:
                name = safe_string(min_length, max_length)
                if bias(config.filename_has_extension):
                    name += '.' + suspicious.extension()
        if name not in exclude:
            return name

def flag_prefix(min_bytes: int = 1, max_bytes: int = 256) -> bytes:
    '''Generates a random prefix for the flag which does not overlap with valid IPv4 or IPv6 traffic.'''
    token = secrets.token_bytes(number(min_bytes, max_bytes))
    if token[0] >> 4 in (4, 6):
        return bytes([token[0] | 0x10]) + token[1:]
    else:
        return token

def flag_suffix(min_bytes: int = 1, max_bytes: int = 256) -> bytes:
    '''Generates a random suffix for the flag.'''
    return secrets.token_bytes(number(min_bytes, max_bytes))

def flag_noise(min_bytes: int = 30, max_bytes: int = 50) -> bytes:
    '''Generates random bytes to use as noise.'''
    return secrets.token_bytes(number(min_bytes, max_bytes))

def fwmark() -> int:
    '''
    Generates a valid firewall mark (non-zero u32) that we can use as a table index (0 < index < 32766).
    We have reserved priority/table 32765 in the entrypoint, so we're not returning that either.
    Note that tables < 256 are reserved by the system, so don't use those.
    '''
    return number(256, 32764)

def ftp_mode(ip_version: types.IPVersion) -> ftp.TransferMode:
    '''Returns a valid FTP transfer mode'''
    match ip_version:
        case 4: return secrets.choice([ftp.TransferMode.PASV, ftp.TransferMode.EPSV, ftp.TransferMode.PORT])
        case 6: return secrets.choice([ftp.TransferMode.EPSV, ftp.TransferMode.EPRT])


# Re-exports for easier customization

username = lambda: safe_string()
password = lambda: safe_string()
