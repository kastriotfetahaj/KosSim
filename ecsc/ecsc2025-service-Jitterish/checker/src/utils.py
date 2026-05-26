import random
import string
import uuid


def generate_random_string(l: int = 8, alphanum: bool = True) -> str:
    s = string.ascii_letters + string.digits if alphanum else string.ascii_letters
    return ''.join(random.choice(s) for _ in range(l))


def generate_username() -> str:
    return generate_random_string(12, alphanum=False)


def generate_password() -> str:
    return generate_random_string(16, alphanum=True)

def generate_token() -> str:
    return str(uuid.uuid4())
