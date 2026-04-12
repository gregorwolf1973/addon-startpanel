#!/usr/bin/with-contenv bashio

set -e

bashio::log.info "Starting Startpanel..."

export PORT=$(bashio::config 'port' '8099')
bashio::log.info "Using port: ${PORT}"

exec python3 /app/server.py
