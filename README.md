<div align="center">

<img src="tbb_inverter/logo.png" alt="TBB Inverter Reader" width="680">

**Add-on Home Assistant per leggere e comandare l'inverter TBB RiiO Sun II via RS485 → MQTT.**

[![Add-on version](https://img.shields.io/badge/add--on-1.3.0-1f8fff?style=flat-square)](tbb_inverter/CHANGELOG.md)
[![Architectures](https://img.shields.io/badge/arch-aarch64%20%7C%20amd64-5ce1e6?style=flat-square)](tbb_inverter/config.yaml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-add--on-41bdf5?style=flat-square&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/addons/)
[![Lint](https://img.shields.io/github/actions/workflow/status/CarloFalco/ha-tbb-inverter-addon/lint.yaml?branch=main&style=flat-square&label=lint%20%26%20test)](../../actions/workflows/lint.yaml)

[![Aggiungi il repository a Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FCarloFalco%2Fha-tbb-inverter-addon)

</div>

---

## Cos'è

L'inverter **TBB RiiO Sun II 8.0S (48V - 8000VA)** espone un connettore RJ45 con un
bus RS485 e un protocollo proprietario non documentato. Questo add-on lo interroga
ciclicamente, decodifica i frame, ne verifica il CRC e pubblica ogni grandezza su
MQTT — creando **da solo** le entità in Home Assistant via MQTT Discovery.

Funziona in locale: nessun cloud, nessun account, nessun gateway del produttore.
Nessuno YAML da scrivere.

| | |
|---|---|
| ☀️ **Fotovoltaico** | Tensione, corrente, potenza MPPT e temperatura del regolatore |
| 🔋 **Batteria** | Tensione, corrente e potenza con segno, SOC, stato carica/scarica, temperatura, BMS |
| 🔌 **Uscite AC** | Due uscite indipendenti (V / A / W), potenza totale, frequenza e carico |
| 🏠 **Ingresso rete** | Tensione, corrente e potenza con segno (prelievo o immissione) |
| 🌡️ **Temperature** | Dissipatore, trasformatore, stadio inverter, batteria |
| 🎚️ **SmartPort** | Tre slider sincronizzati (A, W, %), più invio di frame RS485 grezzi |

---

## Installazione

1. **Aggiungi questo repository** ad Home Assistant — [clicca qui](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FCarloFalco%2Fha-tbb-inverter-addon)
   oppure *Impostazioni → Add-on → Store → ⋮ → Repository* e incolla:

   ```
   https://github.com/CarloFalco/ha-tbb-inverter-addon
   ```

2. **Installa** *TBB Inverter Reader* dallo store.
3. **Configura** porta seriale e broker MQTT nella scheda *Configurazione*.
4. **Avvia** e controlla la scheda *Log*.

📘 **[Documentazione completa →](tbb_inverter/DOCS.md)** — cablaggio, opzioni, topic
MQTT, sensori YAML pronti da copiare, Energy Dashboard e risoluzione problemi.

---

## Collegamento

```
   Inverter RJ45                    USB-RS485                Home Assistant
  ┌──────────────┐                ┌───────────┐             ┌─────────────┐
  │ pin 3 ───────┼── verde/bianco ┤ A+        │             │             │
  │ pin 6 ───────┼── verde ───────┤ B-    USB ├──────────── ┤ /dev/ttyUSB0│
  │ pin 8 ───────┼── marrone ─────┤ GND       │             │             │
  │ pin 7   ✕    │  (+12V, NC)    └───────────┘             └─────────────┘
  └──────────────┘
```

9600 baud, 8N1. Se non arrivano risposte, prova a **invertire A+ e B-**: è l'errore
più comune e non danneggia nulla.

---

## Struttura del repository

```
.
├── repository.yaml            # metadati del repository di add-on
├── ruff.toml                  # regole di lint Python
├── tests/
│   └── test_reader.py         # suite senza hardware né broker
├── .github/workflows/         # lint, test e build multi-arch
└── tbb_inverter/
    ├── config.yaml            # opzioni e schema dell'add-on
    ├── Dockerfile             # immagine base Home Assistant + Python
    ├── run.sh                 # entrypoint bashio (opzioni → variabili d'ambiente)
    ├── tbb_reader.py          # polling RS485, decodifica, discovery, publish MQTT
    ├── requirements.txt
    ├── translations/          # etichette delle opzioni (it, en)
    ├── icon.png / logo.png    # immagini mostrate nello store
    ├── DOCS.md                # scheda "Documentazione" nell'add-on
    ├── README.md              # scheda "Info" nell'add-on
    └── CHANGELOG.md
```

Per eseguire i test in locale (non serve hardware):

```bash
pip install -r tbb_inverter/requirements.txt && python tests/test_reader.py
```

---

## Protocollo

Due frame di lettura interrogati a rotazione:

| Comando | Frame | Risposta |
|---|---|---|
| **C0** | `7E FF 11 03 C0 08 BA EB` | AC in/out, batteria, SOC, temperature, carico |
| **C1** | `7E FF 11 03 C1 08 BB 7B` | PV, MPPT, tensione BMS |

Scrittura: `7E FF 11 06 <cmd> 0C <reg_hi> <reg_lo> <val_hi> <val_lo> <crc_lo> <crc_hi>`
con **CRC16/MODBUS** (poly `0xA001`, init `0xFFFF`, little-endian).

Il protocollo è stato ricostruito per osservazione: modelli o firmware diversi
possono avere offset differenti. Se decodifichi nuovi registri,
[una issue](https://github.com/CarloFalco/ha-tbb-inverter-addon/issues) è benvenuta.

---

<div align="center">
<sub>Progetto non affiliato a TBB Power · Usalo a tuo rischio · Manutentore: <a href="https://github.com/CarloFalco">Carlo Falcomer</a></sub>
</div>
