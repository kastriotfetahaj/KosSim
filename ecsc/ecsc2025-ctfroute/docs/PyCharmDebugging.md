# Debugging ctfroute with PyCharm

Getting the PyCharm debugger attached to ctfroute is unfortunately a bit more
tricky than just pressing debug from within the IDE, but it's generally still
possible.

## Installing pydevd-pycharm

The PyCharm debugger integrates with target processes through a python package called
`pydevd-pycharm`. When the PyCharm debugger is the one starting your code (it isn't
in our case) it will automagically inject and use it. The important detail is that your
version of PyCharm and of `pydevd-pycharm` must be "compatible". Here are some
things to consider when installing it.

When creating a debug config of type `Python Debug Server`, you are presented a
`pip install` command with a compatible version. However, releases of `pydevd-pycharm`
are often buggy. Use a search-engine and try a couple of newer versions if you are
having issues.

We don't put `pydevd-pycharm` into `pyproject.toml`. There is a high chance of people
needing different versions of it and there is enough room for confusion with this as
it is.

There is no `pip` in a uv-managed venv. If you activate the `uv` env and run
`pip` commands you are probably using your system pip. Use `uv pip install ...` instead.

`uv sync` will uninstall packages not listed in `pyproject.toml`, unless you add
`--inexact`.

## Debugging router1 in the docker setup

Setup:

- Make sure that you have an adequate version of `pydevd-pycharm` in your docker image
  - See above
  - You can add `PYCHARM_PYDEV_VERSION` to your `.env`
- If you changed the version, rebuild your docker images
- Create a debug config of type `Python Debug Server`
  - IDE host name: `10.43.2.1`
  - Port: `42424`
  - Path mappings:
    - `/abs/path/to/project`
      -> `/opt/ctfroute`
    - `/aps/path/to/project/.venv/lib/python3.13/site-packages`
      -> `/venv/lib/python3.13/site-packages`
- Make sure your firewall accepts TCP traffic to port 42424 from 10.43.2.1
  - `iptables -I INPUT 1 -p tcp --dport 42424 --source 10.43.2.11 -j ACCEPT`
- Symlink `debug.compose.override.yml` to `compose.override.yml`
  - `ln -s debug.compose.override.yml compose.override.yml`

Running:

- Start the debug server in PyCharm
- `docker compose restart router1`
  - Debugger should get attached
  - If the router can't connect to the debugger, it won't start

## Debugging vulnbox1 in the docker setup

Exactly the same as with router1, but use with port `42425` instead (don't forget
your firewall).

## Namespacing in unit-tests

Some unit tests drop into a namespace to test things that configure the network stack.
This is apparently incompatible with pycharms interactive debugger, I believe it is
because of threading. As a workaround, you can use the good old:

```py
import pdb; pdb.set_trace()
```

## Uncaught exceptions in the event loop

When enabling debugging, we register a noop exception handler, see
[debug.py](../ctfroute/ctfroute/debug.py). It simply calls the default handler,
but you can set a breakpoint on it to inspect the context.
