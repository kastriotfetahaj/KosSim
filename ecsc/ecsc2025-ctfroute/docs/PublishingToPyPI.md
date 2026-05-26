# ctfroute-k8s

Bump the version appropriately!
```sh
$ cd ctfroute-k8s
$ uv version --bump minor 
```

Build the package (from its directory):

```sh
$ cd ctfroute-k8s
$ uv build
Building source distribution...
Building wheel from source distribution...
Successfully built ../dist/ctfroute_k8s-0.3.0.tar.gz
Successfully built .../dist/ctfroute_k8s-0.3.0-py3-none-any.whl
```

Notice that the dist lands in the project root!

Commit the changes!

```sh
$ git add ctfroute-k8s/pyproject.toml uv.lock
$ git commit -m "bump ctfroute-k8s version"  
$ git push
```

Publish to pypi, list the artifacts explicitly!
```sh
$ uv publish dist/ctfroute_k8s-0.3.0.tar.gz dist/ctfroute_k8s-0.3.0-py3-none-any.whl
Publishing 2 files https://upload.pypi.org/legacy/
Enter username ('__token__' if using a token): __token__
Enter password: ...
```
