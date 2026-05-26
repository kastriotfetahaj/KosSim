Gitter
======

Authors:
* yvie (Yvonne K.) <!-- (primary) -->
* bazumo (Moritz S.) <!-- (primary) -->

Categories:
* Web
* Pwn
* Rev


Overview
--------

Git management platform, inspired by similar platforms such as github, gitlab, etc.

Features:
* Create and manage git repositories in a web frontend
* Clone repositories via SSH

Tech-Stack:

The service consists of three loosely-coupled parts:
* frontend:  
  Publically accessible web frontend and backend using Next.js/typescript running in Bun. This is the main component users interact with, when accessing the website.
* ssh:  
  OpenSSH daemon running a custom login shell (/opt/gitter-shell). The SSH wrapper is written in C++ and queries an internal API to implement user restrictions (described below).  
  The wrapper matches users according to the public key they used during SSH login. Permission to access the repository is checked, before a push or pull is allowed.
* internal:  
  API used by the SSH wrapper. Non-public and without authentication. Can query metadata of users and repositories. Written in JS using express and running in Bun.

<!-- Include an exhaustive overview of the service and its intended functionalities. Explain in detail the technological stack that you plan to adopt, but do not introduce the vulnerabilities yet -->

### Flag Store 1

Flag is stored as a file in a repository. The path to the repository and file is given as attack info.

<!-- Detail how flags are stored and what do they represent. Explain if you plan to use attack info and how -->

### Flag Store 2

Flag is stored in the repository's metadata (private description). The path to the repository is given as attack info.

<!-- Detail how flags are stored and what do they represent. Explain if you plan to use attack info and how -->


Vulnerabilities
---------------

<!-- Provide a high-level description of the vulnerabilities affecting each flag store. Include a proof-of-concept of the exploit, or - if this is not possible - a description of the attack flow. For each *vulnerability*, specify the intended difficulty level of the exploit, its *discoverability* by inspecting traffic dumps, etc., and *patchability*. Accepted values are *easy*, *medium*, *hard*. Vulnerabilities that are easy to exploit should be also easy to patch. On the other hand, it is fine to require more complex patches if the difficulty is also hard. It is also fine to keep the pathcability as easy if the discoverability is hard. Concerning discoverability, as a rule of thumb, there are 3 cases: *easy*, the exploit can be easily identified and reflected; *medium*, the exploit can be easily identified, but reflection is not trivial; *hard*, when identification and especially reflection are unlikely to be possible, e.g., if the connection is encrypted. We perfectly understand that precisely defining all possible vulnerabilities at this stage is difficult, but it's important to incorporate them during the design phase instead of adding some vulnerabilities at the end of the development -->

### Flag Store 1, Vuln 1

In the web frontend, the target file is obtained using `git checkout <revision>` and then subsequently read from the filesystem. If an attacker adds a symbolic link to their repository, they can read the link target by requesting that file's content.

* Difficulty: easy
* Discoverability: easy
* Patchability: easy
* Categories: misc

### Flag Store 1, Vuln 2

There is a path traversal when reading repository files:
```typescript
  const filepath = filepath_encoded.map(s => decodeURIComponent(s));

  const repo = await getRepository(
    organization,
    repository
  );
  ...
```

You can read other repository files by `..%2f..%2f<username>%2f<repo>%2f<file>`, e.g. for extracting flags`..%2f..%2f<username>%2fflag%2fflag.txt`

* Difficulty: easy
* Discoverability: easy
* Patchability: easy
* Categories: web

### Flag Store 2, Vuln 1

The SSH configuration allows port forwarding using `ssh -L <port>:localhost:<port>`. This enables an attacker to access the internal API. An attacker can then read the metadata of all repositories that belong to a given user by querying `http://internal:3000/get-repositories?user=<user>`

* Difficulty: easy
* Discoverability: hard
* Patchability: easy
* Categories: misc

### Flag Store 2, Vuln 2

The ssh-wrapper binary parses the invoked git command and returns an `std::optional<GitCommand>`. However, this optional is not validated before access. If an invalid command line is given, an uninitialized `GitCommand`-struct is accessed.

The `GitCommand` overlaps the same stack location as the base64-decoded ssh public key used for authentication. The struct starts at offset 0x40 of the buffer. The struct looks like this:
```
enum class GitPermission {
	READ = 0,
	WRITE = 1,
};

struct GitCommand {
	GitPermission permission;

	std::string repository;
	std::string user;
};
```

Therefore a carefully crafted public key can replace the user's name. Furthermore, the binary uses libc++ instead of libstdc++ (which is normally the default). This enables us to use the [short-string optimization](https://joellaity.com/2020/01/31/string.html) in order to change the user string without any address leak. Then, when access permissions are checked, the repositories of the changed user are loaded and the private description will be printed.

Note that this vuln does not enable access to the repository contents of the other user, as the optional is validated before granting repository access (but still after the access check).

* Difficulty: medium
* Discoverability: hard
* Patchability: medium
* Categories: pwn, rev

### Flag Store 2, Vuln 3

In the web frontend, the function `addContributor` is called inside an event handler. This means that this code runs in the browser and not in the backend. Therefore `addContributor` is exposed a next.js server action.

The additional argument to `addContributor` allows adding yourself to any repo. Need to figure out that this server function is called as a next.js server action and that you can just pass an additional argument in it.

* Difficulty: medium
* Discoverability: medium
* Patchability: easy
* Categories: web


Patches
-------

<!-- For each of the vulnerabilities reported in the previous section, outline a possible fix, can use diff files here to visualize changes but a text explanation is also required -->

### Flag Store 1, Vuln 1

Use the output of `git show <revision>:<path>` instead of reading the file content manually.

### Flag Store 1, Vuln 2

Check if file name contains `../` after url decode and abort in this case.

### Flag Store 2, Vuln 1

Add
```
AllowTcpForwarding No
```

to `/etc/ssh/sshd_config`

### Flag Store 2, Vuln 2

Invoke a small script as ssh entrypoint, before calling the binary to validate whether the given command is valid

For example in python:
```
import sys
import subprocess
import re

if re.match("^'(git-receive-pack|git-upload-pack) .+'$", sys.argv[2]):
    subprocess.call(["/opt/gitter-shell"] + sys.argv[1:])
```

### Flag Store 2, Vuln 3

remove third argument in

```typescript
export async function addContributor(repository_id: number, user_id: string, owner?: string): Promise<void> { ... }
```


Work Packages
-------------

<!-- Brief description of each work package -->


### WP 1: Basic Web-App

#### WP 1.1: Account-System

* Registration:
    * Users can create new accounts, with a unique username, a password and an ssh public-key (must also be unique)
* Login:
    * Users can login to their previously created account using their username and password
* Repository Management:
    * Ability to create empty repositories in the web frontend, which can then be cloned via SSH

#### WP 1.2: Web-based File-viewer

* Similar to the one used by github: https://github.com/torvalds/linux/blob/master/README

#### WP 1.3: Frontend Styling

* Making the frontend look sleek and fit the CTF theme

### WP 2: Internal API

* API to query access restrictions (used by the SSH wrapper)
* Endpoints:
  * Identify the user that has the given public key
  * Query permissions to repositories (read/write)
  * List repositorys for user (including description, which is the flag)
* Clean up old users and repositories

### WP 3: Infrastructure

#### WP 3.1: Reverse-Proxy

* Reverse Proxy to forward public API

#### WP 3.2: Web-App Database

* Database schema definitions for Web-App

### WP 4: SSH Wrapper

* Allows git clone/git push with access restrictions in place
* Prevent ZIP-Bombs/overly large repositories

### WP 5: Advanced Functionality

* Repository settings
  * Permissions
    * Read/Write-Access to repositories
    * Maybe public/private repositories (maybe only private repositories)

### WP 6: Checker

#### WP 6.1: User Registration

Test registering new users and authenticating.

#### WP 6.2: Repository Noise

Try creating a repository and using it without flag-related actions.

#### WP 6.3: Repository Flag-Retrieval

Try placing and retrieving the repository related flagstore flags.

#### WP 6.4: Description Flag-Retrieval

Try placing and retrieving the description related flagstore flags.

#### WP 6.5: Checker Exploits

Implement exploits for intended vulnerabilities.
