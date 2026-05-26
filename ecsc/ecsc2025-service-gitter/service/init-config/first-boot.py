#!/usr/bin/env python3

import secrets
import os

POSTGRESS_PASSWORD = secrets.token_hex(8)
JWT_SECRET = secrets.token_hex(32)

ENV_FILE = f"""
POSTGRES_URL=postgres://postgres:{POSTGRESS_PASSWORD}@postgres:5432/postgres
POSTGRESS_PASSWORD={POSTGRESS_PASSWORD}
JWT_SECRET={JWT_SECRET}
"""

with open("/init-config/.env", "w") as f:
    f.write(ENV_FILE)

with open("/init-config/postgress-password", "w") as f:
    f.write(POSTGRESS_PASSWORD)

with open("/init-config/jwt-secret", "w") as f:
    f.write(JWT_SECRET)


os.chmod('/init-config/.env', 0o400)
os.chmod('/init-config/postgress-password', 0o400)
os.chmod('/init-config/jwt-secret', 0o400)
