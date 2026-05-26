#!/bin/sh -u

CLEANUP=30

while true; do
    psql $POSTGRES_URL -c "DELETE FROM users WHERE created_at < current_timestamp - interval '$CLEANUP' minute;"

    find /home/git/repositories -type d -maxdepth 1 -mindepth 1 -mmin +$CLEANUP -exec rm -rf {} \;
    find /home/git/.gitter-keys -type f -mmin +$CLEANUP -delete

    sleep 10m
done
