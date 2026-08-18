# Documentazione — TBB Inverter Reader

## Collegamento hardware

Adattatore USB-RS485 collegato al Raspberry Pi, cablato al connettore RJ45
dell'inverter:

| RJ45 pin | Segnale        | Adattatore RS485 |
|----------|----------------|-------------------|
| 3        | verde/bianco   | A+                |
| 6        | verde          | B-                |
| 7        | +12V           | NON collegare     |
| 8        | GND            | GND (opzionale)   |

## Opzioni

| Opzione         | Default            | Descrizione                                             |
|-----------------|--------------------|-----------------------------------------------------------|
| `serial_port`   | `/dev/ttyUSB0`     | Percorso della porta seriale dell'adattatore RS485         |
| `baudrate`      | `9600`             | Velocità seriale                                           |
| `poll_interval` | `5`                | Secondi tra un ciclo di lettura e l'altro                  |
| `mqtt_host`     | `core-mosquitto`   | Host/IP del broker MQTT                                    |
| `mqtt_port`     | `1883`             | Porta del broker MQTT                                      |
| `mqtt_user`     | *(vuoto)*          | Utente MQTT                                                 |
| `mqtt_password` | *(vuoto)*          | Password MQTT                                               |
| `mqtt_prefix`   | `tbb/inverter`     | Prefisso dei topic pubblicati                               |

> Suggerimento: se usi il broker Mosquitto ufficiale installato come add-on
> HA, `mqtt_host: core-mosquitto` funziona senza modifiche. Se usi un broker
> esterno (come nello script originale), imposta qui il suo IP e le
> credenziali.

## Porta seriale stabile

Il nome `/dev/ttyUSBx` può cambiare se l'adattatore viene scollegato o se ci
sono altre periferiche USB seriali. Per un percorso stabile, apri **Impostazioni
→ Add-on → Terminale & SSH** (o accedi via SSH) ed esegui:

```
ls -l /dev/serial/by-id/
```

e usa il percorso `by-id` risultante (es.
`/dev/serial/by-id/usb-FTDI_...-if00-port0`) come valore di `serial_port`.

## Topic MQTT pubblicati (sotto `<prefix>/`)

`ac_out_w`, `ac_out_v`, `ac_out_i`, `ac_out2_w`, `ac_out2_v`, `ac_out2_i`,
`ac_in_v`, `ac_in_i`, `ac_freq`, `bat_v`, `bat_i`, `soc`, `t_heatsink`,
`t_transformer`, `t_inverter`, `t_bat`, `load_pct`, `pv_w`, `pv_v`, `mppt_i`,
`mppt_temp`, `bat_v_bms`, oltre a `stato` (JSON con tutti i valori).

## Comandi MQTT in ingresso

- `<prefix>/cmd/smart_port` ← valore 0-100 (%)
- `<prefix>/cmd/raw` ← frame hex, es. `7E FF 11 06 06 0C 00 5E 00 28 81 46`

Lo stato di ogni comando viene pubblicato su `<prefix>/cmd/<comando>/status`
(`OK` o `ERRORE`).

## Log

Scheda **Log** dell'add-on: mostra la connessione seriale/MQTT e, ad ogni
ciclo di polling, i valori letti.
