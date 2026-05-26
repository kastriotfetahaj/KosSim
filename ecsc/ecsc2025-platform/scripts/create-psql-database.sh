#!/usr/bin/env bash

set -e

DBNAME=$1
PASS=$2

echo "[1/3] Create database ..."
echo "CREATE DATABASE $DBNAME;" | psql -U saarsec

export CONFIG_DATABASE='{"ENGINE": "django.db.backends.postgresql_psycopg2", "NAME": "'$DBNAME'", "USER": "saarsec", "PASSWORD": "'$PASS'", "HOST": "127.0.0.1"}'

echo "[2/3] Create/update schema ..."
python3 manage.py migrate

echo "[3/3] Create admin user ..."
python3 manage.py createsuperuser

echo "[DONE]"
