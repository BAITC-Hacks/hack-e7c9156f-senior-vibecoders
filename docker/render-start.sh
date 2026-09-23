#!/bin/sh
set -e
envsubst '${PORT}' < /etc/nginx/templates/app.conf.template > /etc/nginx/conf.d/app.conf
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
exec nginx -g 'daemon off;'
