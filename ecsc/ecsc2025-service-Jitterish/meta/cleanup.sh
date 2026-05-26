#!/usr/bin/env bash

set -ex

cd /service

find . -name "*_test.rs" -type f -delete
rm -rf jit/demo
rm -rf jit/tests
rm -rf jit/README.md
rm -rf frontend
rm -f website/src/tests.rs
sed -i "/BEGIN REMOVE IN PROD/,/END REMOVE IN PROD/d" dbengine/src/sandbox/sandbox.rs
sed -i "/BEGIN REMOVE IN PROD/,/END REMOVE IN PROD/d" dbengine/Cargo.toml
sed -i "/BEGIN REMOVE IN PROD/,/END REMOVE IN PROD/d" website/src/main.rs
sed -i "/BEGIN REMOVE IN PROD/,/END REMOVE IN PROD/d" docker-compose.yml

if grep -r -q "REMOVE IN PROD" .; then
  echo "not all prod patterns removed"
  exit 1
fi

echo "Done, source dir is clean."
