This is an example VPN client for the service.
Feel free to use it, patch it, break it, etc., but don't feel compelled to use it.
It is [the only thing] here to make your life easier.

WARNING: Running this _will_ route 10.0.0.0/8 through the VPN by default. Specify `--exclude` to exclude certain networks.

The provided Dockerfile and Compose file should serve as a reference for what you need to run this client.
For example, you can use `docker compose run --rm client [arguments]` to start a temporary container that runs the VPN client.
