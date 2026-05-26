#!/bin/bash
#
# This lets you configure a temporary GitHub PAT to access our enochecker3 fork
# without storing it on disk, as long as your tmpdir is actually in tmpfs.
#
# If you do not specify the GITHUB_PAT environment variable, you will be
# prompted to enter the PAT.
#
# For example, you can run `./with-pat.sh pip install -r src/requirements.txt`
# to install the checker dependencies. To install the dependencies for running
# the tests, run `./with-path.sh pip install -r tests/requirements.txt`

set -euo pipefail

if [ -n "${GITHUB_PAT:-}" ]; then
    pat="${GITHUB_PAT}"
else
    read -s -p 'Enter the GitHub PAT: ' pat
fi

# Create credential storage and temporary Git config
config="$(umask 077 && mktemp)"
credentials="$(umask 077 && mktemp)"
cleanup() {
    shred -u -- "${config}" "${credentials}"
}
trap cleanup EXIT
chmod 0600 "${config}" "${credentials}" # Just in case

# Set up PAT in the temporary Git config
export GIT_CONFIG_GLOBAL="${config}"
git config --global credential.https://github.com.helper "store --file ${credentials}"
cat > "${credentials}" <<<"https://token:${pat}@github.com"

"$@"

git config --global --unset credential.https://github.com.helper
# On exit, the config and credential files will be deleted
