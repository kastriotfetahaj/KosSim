> [!NOTE]
> This code was used to host the A/D-CTF of ECSC 2025 and saarCTF 2025. The Authors are
> working on making it stable and well-documented enough so it can become a reliable
> tool used by the entire CTF community. The state published here has several
> limitations (see below) and primarily serves to satisfy your curiosity.
> The documentation in `./docs` is instructive, but should not be relied upon.

> [!Caution]
> Do not use this code as-as and expect it to work for hosting an A/D CTF. The people 
> who operated it so far had written it themselves and knew exactly what its 
> limitations are and how it can be safely interacted with. There are several "features" 
> that are known to scale poorly or simply not work under some conditions. 
> ctfroute primarily configures networking subsystems in the linux kernel, unexpected 
> changes made by other software can very well crash ctfroute or make the host 
> inaccessible via network, etc.

# ctfroute

ctfroute aspires to make A/D-CTF networking less of a pain. Instead of a gazillion
hacked up bash-scripts and automation-tools, you write one configuration file and
deploy a single python process onto your routers, start it, and it should _just work_ ™.

Very much __work in progress__.

## `ctfroute` vs `ctftest` vs. `ctfroute-k8s`

There are three python packages in this repo, each with their own dir and
`pyproject.toml`. `ctftest` is a sister module for `ctfroute` which primarily
contains tooling for integration-testing `ctfroute`. The reason for making `ctftest` a
separate package / module is so we can have a lower bar for code-quality and third party
dependencies on our testing code, which just makes our live easier when scripting up
integration tests.

The key aspects of this setup are these:

- `ctftest` MAY import code from `ctfroute`
- `ctfroute` MUST NOT import code from `ctftest` 
  - ... except in tests (`ctfroute/tests`)
- `ctfroute` MUST work without `ctftest` and it's dependencies installed

For development, you don't need to install both projects separately, instead the 
repo-root contains a "meta package", `ctfroute-develop` that includes and installs 
both packages as workspaces. Just run `uv sync` and hack away.

The third package `ctfroute-k8s` contains code ctfroute and other python applications 
can use to work with k8s CRDs that represent ctfroute configuration. It is packed 
separately so it can be used by used as a dependency for MIT-licensed software.

Consequentially, `ctfroute-k8s` may never depend on `ctfroute` or `ctftest`.

## License 

`ctftest` and `ctfroute` are `GPL-2.0-or-later` the rest is `MIT`.
