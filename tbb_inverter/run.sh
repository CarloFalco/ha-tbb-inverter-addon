#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

export SERIAL_PORT BAUD POLL_INTERVAL
export MQTT_HOST MQTT_PORT MQTT_USER MQTT_PASS MQTT_PREFIX
export MQTT_DISCOVERY DISCOVERY_PREFIX ALLOW_RAW_COMMAND STRICT_CRC
export LOG_LEVEL ADDON_VERSION

SERIAL_PORT=$(bashio::config 'serial_port')
BAUD=$(bashio::config 'baudrate')
POLL_INTERVAL=$(bashio::config 'poll_interval')
MQTT_PREFIX=$(bashio::config 'mqtt_prefix')
MQTT_DISCOVERY=$(bashio::config 'mqtt_discovery')
DISCOVERY_PREFIX=$(bashio::config 'discovery_prefix')
ALLOW_RAW_COMMAND=$(bashio::config 'allow_raw_command')
STRICT_CRC=$(bashio::config 'strict_crc')
LOG_LEVEL=$(bashio::config 'log_level')
# ADDON_VERSION arriva gia' dal Dockerfile (BUILD_VERSION); l'API del Supervisor
# e' solo un raffinamento e non deve far fallire l'avvio se non risponde.
ADDON_VERSION=$(bashio::addon.version 2>/dev/null || echo "${ADDON_VERSION:-unknown}")

# ---------------------------------------------------------------------------
# Broker MQTT
#
# Se `mqtt_host` e' vuoto usiamo il broker configurato in Home Assistant
# (integrazione MQTT / add-on Mosquitto): host, porta e credenziali arrivano
# dal servizio del Supervisor, senza doverli ricopiare a mano.
# ---------------------------------------------------------------------------
if bashio::config.has_value 'mqtt_host'; then
    MQTT_HOST=$(bashio::config 'mqtt_host')
    MQTT_PORT=$(bashio::config 'mqtt_port')
    MQTT_USER=$(bashio::config 'mqtt_user')
    MQTT_PASS=$(bashio::config 'mqtt_password')
    bashio::log.info "Broker MQTT configurato manualmente: ${MQTT_HOST}:${MQTT_PORT}"
elif bashio::services.available 'mqtt'; then
    MQTT_HOST=$(bashio::services 'mqtt' 'host')
    MQTT_PORT=$(bashio::services 'mqtt' 'port')
    MQTT_USER=$(bashio::services 'mqtt' 'username')
    MQTT_PASS=$(bashio::services 'mqtt' 'password')
    bashio::log.info "Broker MQTT rilevato da Home Assistant: ${MQTT_HOST}:${MQTT_PORT}"
else
    bashio::exit.nok \
        "Nessun broker MQTT disponibile. Installa l'add-on 'Mosquitto broker' \
oppure compila 'mqtt_host' nella configurazione di questo add-on."
fi

# ---------------------------------------------------------------------------
# Porta seriale
# ---------------------------------------------------------------------------
if ! bashio::fs.device_exists "${SERIAL_PORT}"; then
    bashio::log.warning "La porta '${SERIAL_PORT}' non esiste (ancora)."
    bashio::log.warning "Dispositivi seriali disponibili:"
    ls -l /dev/serial/by-id/ 2>/dev/null || bashio::log.warning "  nessuno in /dev/serial/by-id/"
    ls -1 /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
    bashio::log.warning "L'add-on riprovera' ad aprirla periodicamente."
fi

bashio::log.info "Avvio TBB Inverter Reader ${ADDON_VERSION}"
bashio::log.info "Porta seriale: ${SERIAL_PORT}  Baud: ${BAUD}  Poll: ${POLL_INTERVAL}s"
bashio::log.info "Prefix MQTT: ${MQTT_PREFIX}  Discovery: ${MQTT_DISCOVERY}"

exec python3 -u /tbb_reader.py
