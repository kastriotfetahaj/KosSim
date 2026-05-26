These binaries implement small helper functions to delegate privileged operations from the checker process.
This is needed because the checker does not play nicely with capabilities, (and for that matter, neither does the `ip` binary, see [here](https://marcoguerri.github.io/2023/10/13/capabilities-and-docker.html)).

 - `tunctl` calls the `TUNSETIFF` `ioctl` on a file descriptor
 - `ip-wrapper` runs `ip ...` commands (with an allowlist to ensure that there are no insane shenanigans)
