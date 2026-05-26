#!/bin/bash
set -ex

if [ -z "$ELASTIC_URL" ]; then
    echo "ELASTIC_URL is not set, exiting..."
    exit 1
fi

if [ -z "$ELASTIC_PASSWORD" ]; then
    echo "ELASTIC_PASSWORD is not set, extiting..."
    exit 1
fi

export ELASTIC_HOST="https://elastic:${ELASTIC_PASSWORD}@${ELASTIC_URL}"

while ! curl -sqk -u "elastic:$ELASTIC_PASSWORD" $ELASTIC_HOST; do
    echo "Waiting for elastic search to start...";
    sleep 3;
done

while ! curl -sqk -u "elastic:$ELASTIC_PASSWORD" "$ELASTIC_HOST/_cluster/health" \
    | grep -q '"status":"green"'; do
    echo "Waiting for Elasticsearch cluster to be green..."
    sleep 3
done

echo "Check if elasticsearch is initalized, otherwise do it"
if ! curl -s -u "elastic:$ELASTIC_PASSWORD" --insecure --head --show-error --fail "$ELASTIC_HOST/arkime_dstats_v30" && \
   ! curl -s -u "elastic:$ELASTIC_PASSWORD" --insecure --head --show-error --fail "$ELASTIC_HOST/arkime_users_v30" && \
   ! curl -s -u "elastic:$ELASTIC_PASSWORD" --insecure --head --show-error --fail "$ELASTIC_HOST/arkime_fields_v30" && \
   ! curl -s -u "elastic:$ELASTIC_PASSWORD" --insecure --head --show-error --fail "$ELASTIC_HOST/arkime_queries_v30" && \
   ! curl -s -u "elastic:$ELASTIC_PASSWORD" --insecure --head --show-error --fail "$ELASTIC_HOST/arkime_stats_v30" && \
   ! curl -s -u "elastic:$ELASTIC_PASSWORD" --insecure --head --show-error --fail "$ELASTIC_HOST/arkime_sequence_v30" && \
   ! curl -s -u "elastic:$ELASTIC_PASSWORD" --insecure --head --show-error --fail "$ELASTIC_HOST/arkime_hunts_v30" && \
   ! curl -s -u "elastic:$ELASTIC_PASSWORD" --insecure --head --show-error --fail "$ELASTIC_HOST/arkime_files_v30" && \
   ! curl -s -u "elastic:$ELASTIC_PASSWORD" --insecure --head --show-error --fail "$ELASTIC_HOST/arkime_lookups_v30"; then

   echo "Initializing elasticsearch..."
   (echo "INIT" | /opt/arkime/db/db.pl --insecure --esuser "elastic:$ELASTIC_PASSWORD" $ELASTIC_HOST init) || exit 1
   echo "Adding Arkime user"
   /opt/arkime/bin/arkime_add_user.sh "arkime" "Arkime User" "arkime" --admin --packetSearch --insecure -o elasticsearch=$ELASTIC_HOST|| exit 1
else
   echo "elasticsearch was already initalized, so initialization was skipped"
fi
