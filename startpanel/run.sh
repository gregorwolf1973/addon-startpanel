#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Startpanel..."
bashio::log.info "SUPERVISOR_TOKEN present: $([ -n "${SUPERVISOR_TOKEN}" ] && echo yes || echo NO)"

exec python3 /app/server.py
