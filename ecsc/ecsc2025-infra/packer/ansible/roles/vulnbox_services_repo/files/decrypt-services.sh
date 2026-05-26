#!/bin/sh
gpg -d -o services.tar.gz services.tar.gz.gpg
tar -xzf services.tar.gz
