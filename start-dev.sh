#!/bin/bash

# cleanup
rm syncope/migrations/0*.py
rm db/database.sqlite3

# setup new db
uv run manage.py makemigrations
uv run manage.py migrate
uv run manage.py loaddata syncope/fixtures/syncope/*.json

# start server
uv run manage.py runserver
