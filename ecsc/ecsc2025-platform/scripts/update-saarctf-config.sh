#!/bin/bash

# Script on the saarsec server to perform synchronization with game infrastructure.
# CRONTAB:
# PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# HOME=/root
# # saarCTF - push db to git and import vpn config
# 0 */4 * * *  /root/update-saarctf-config.sh >> /var/log/update-saarctf-config.log 2>&1

echo ""
echo "==========================="
echo ""

set -eux

cd /opt/saarctf-config
git add 2020 2020-test
git diff-index --quiet HEAD || git commit -m "Server updates $(date)" || true
git pull --rebase
git push

chown -R nginx:nginx /opt/saarctf-config/*

echo "Done."
