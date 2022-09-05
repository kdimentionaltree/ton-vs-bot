#!/bin/bash
set -e

PASSWORD=$(cat $1)
BACKUP_DIR=/var/ton-backups

CONTAINER_ID=$(docker ps -f name=ton-vs-bot_postgres -q)
echo "Found container: $CONTAINER_ID"

docker exec -i $CONTAINER_ID bash -c "echo $PASSWORD > /root/.pgpass && chmod 600 /root/.pgpass && pg_dump -U user1 -w -d tonhelp" > $BACKUP_DIR/ton-vs-bot_postgres.sql
