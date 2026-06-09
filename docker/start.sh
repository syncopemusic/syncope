#!/bin/sh

set -e

echo "Starting Django..."

mkdir -p /app/db
uv run manage.py migrate --noinput
uv run manage.py loaddata syncope/fixtures/syncope/*.json

uv run manage.py runserver 0.0.0.0:8000