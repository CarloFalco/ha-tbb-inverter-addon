# Changelog

## 1.0.1

- Rimosso `build.yaml` (non più letto dal builder di Supervisor >= 2026.04.0)
- `Dockerfile` aggiornato con `FROM` diretto verso un'immagine base multi-arch
  (`ghcr.io/home-assistant/base-python`), come richiesto dal nuovo sistema di build
- Rimosso `armv7` dalle architetture supportate (i base image HA moderni
  coprono solo `amd64`/`aarch64`)

## 1.0.0

- Prima versione come add-on Home Assistant
- Configurazione (porta seriale, baud, MQTT, prefisso) spostata dalle
  costanti hardcoded alle opzioni dell'add-on
- Supporto architetture: armv7, aarch64, amd64
