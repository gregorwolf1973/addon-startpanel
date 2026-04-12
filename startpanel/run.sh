#!/bin/sh
set -e

export PORT=$(bashio::config 'port')

exec python3 /app/server.py
