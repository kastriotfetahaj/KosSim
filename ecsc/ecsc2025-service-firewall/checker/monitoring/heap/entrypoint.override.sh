#!/bin/bash
uv pip install -r /heap/requirements.txt
chmod 777 /heap/output
exec /entrypoint.sh
