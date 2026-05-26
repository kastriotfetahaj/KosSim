
## Build JIT component
Use CLion (with configured clang toolchain), or do it manually:
```bash
cd service/jit
mkdir build
cd build
cmake -G Ninja .. -DCMAKE_CXX_COMPILER=clang++-18
ninja jit
```

## Build Rust components
```bash
cd service/dbengine
cargo build
```

```bash
cd service/website
cargo build
```

## Test checkerscripts
Prepare environment:
```bash
cd checker
python3 -m venv venv
. venv/bin/activate
pip install -r src/requirements.txt
```

Then use one of:
```
./run.sh demo.py  # (or short: ./run.sh)
./run.sh checker.py
./run.sh gunicorn
```

To run from PyCharm/RustRover/whatever, do:
- run `docker-compose up -d jitterish-mongo`
- set `MONGO_USER=jitterish_checker  MONGO_PASSWORD=jitterish_checker`


## Final validation
... at least on my machine...
```bash
git clone Jitterish Jitterish-tmp
cd Jitterish-tmp/service
docker compose -f ../meta/docker-compose.override.yml --project-directory . run --rm cleanup-source
scc .
docker compose up

cd ../checker
docker compose up

enochecker_test -a localhost -p 8400 -A 172.22.0.1
```

