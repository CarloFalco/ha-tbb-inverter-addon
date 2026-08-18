#!/usr/bin/with-contenv bashio

export SERIAL_PORT
export BAUD
export POLL_INTERVAL
export MQTT_HOST
export MQTT_PORT
export MQTT_USER
export MQTT_PASS
export MQTT_PREFIX

SERIAL_PORT=$(bashio::config 'serial_port')
BAUD=$(bashio::config 'baudrate')
POLL_INTERVAL=$(bashio::config 'poll_interval')
MQTT_HOST=$(bashio::config 'mqtt_host')
MQTT_PORT=$(bashio::config 'mqtt_port')
MQTT_USER=$(bashio::config 'mqtt_user')
MQTT_PASS=$(bashio::config 'mqtt_password')
MQTT_PREFIX=$(bashio::config 'mqtt_prefix')

bashio::log.info "Avvio TBB Inverter Reader"
bashio::log.info "Porta seriale: ${SERIAL_PORT}  Baud: ${BAUD}  Poll: ${POLL_INTERVAL}s"
bashio::log.info "MQTT: ${MQTT_HOST}:${MQTT_PORT}  Prefix: ${MQTT_PREFIX}"

exec python3 /tbb_reader.py
