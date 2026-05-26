#!/usr/bin/env bash

# USAGE: ./run.sh
# USAGE: ./run.sh gunicorn
# USAGE: ./run.sh demo.py
# USAGE: ./run.sh checker.py

if [[ "$VIRTUAL_ENV" == "" ]]; then
  echo "Please run within a virtualenv:"
  echo "  python3 -m venv venv"
  echo "  . venv/bin/activate"
  echo "  pip install -r src/requirements.txt"
  echo "  $0 $@"
  exit 1
fi

docker-compose up -d jitterish-mongo

export MONGO_HOST=localhost
export MONGO_PORT=8401
export MONGO_USER=jitterish_checker
export MONGO_PASSWORD=jitterish_checker

cd src

if [[ "$1" == "" ]]; then
  exec python demo.py
elif [[ "$1" == "gunicorn" ]]; then
  exec gunicorn -c gunicorn.conf.py "checker:app()"
else
  exec python "$@"
fi
