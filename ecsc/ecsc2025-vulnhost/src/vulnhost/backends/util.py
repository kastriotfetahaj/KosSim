import base64
import os


def generate_pw():
    return base64.urlsafe_b64encode(os.urandom(15)).decode()
