#!/bin/bash
set -e

# load environment variables
ENV_FILE=.env
if [ ! -z "${ENV_FILE}" ]; then
    set -a
    source ${ENV_FILE}
    set +a
fi


# build image
docker compose -f docker-compose.yaml build
docker compose -f docker-compose.yaml push

# deploy stack
docker stack deploy --with-registry-auth -c docker-compose.yaml ton-vs-bot
