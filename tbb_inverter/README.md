# TBB Inverter Reader

Add-on Home Assistant per la lettura periodica via RS485 e la scrittura di
comandi verso un inverter **TBB RiiO Sun II 8.0S (48V-8000VA)**, con
pubblicazione dei dati su MQTT.

- Legge i frame `C0` (dati AC/batteria/temperature) e `C1` (dati PV/MPPT)
- Pubblica ogni valore come topic MQTT separato + un topic `stato` con JSON completo
- Accetta comandi in ingresso via MQTT: `smart_port` (0-100%) e `raw` (frame hex)

Vedi la scheda **Documentazione** dell'add-on per la configurazione completa.
