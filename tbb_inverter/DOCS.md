# 📘 Documentazione — TBB Inverter Reader

Guida completa all'installazione, configurazione e integrazione dell'add-on in
Home Assistant.

| | |
|---|---|
| [🔌 Collegamento hardware](#-collegamento-hardware) | Cablaggio RJ45 ↔ RS485 |
| [⚙️ Opzioni](#-opzioni-dellagg-on) | Tutti i parametri configurabili |
| [🔗 Porta seriale stabile](#-porta-seriale-stabile) | Evitare che `/dev/ttyUSB0` cambi |
| [📡 Topic MQTT](#-topic-mqtt-pubblicati) | Elenco completo delle grandezze |
| [🏠 Sensori in Home Assistant](#-creare-i-sensori-in-home-assistant) | YAML pronto da copiare |
| [⚡ Energy Dashboard](#-energy-dashboard) | Da watt a kWh |
| [🎛️ Comandi di scrittura](#-comandi-di-scrittura) | SmartPort e frame raw |
| [🛠️ Risoluzione problemi](#-risoluzione-problemi) | Cosa fare quando non funziona |

---

## 🔌 Collegamento hardware

Serve un **adattatore USB ↔ RS485** collegato al Raspberry Pi (o alla macchina che
esegue Home Assistant) e cablato al connettore **RJ45** dell'inverter.

| RJ45 pin | Colore standard T568B | Segnale | Adattatore RS485 |
|:--------:|-----------------------|---------|------------------|
| **3** | verde / bianco | Dati A | **A+** *(a volte marcato `D+`)* |
| **6** | verde | Dati B | **B-** *(a volte marcato `D-`)* |
| **8** | marrone | GND | **GND** — opzionale, ma consigliato su cavi lunghi |
| **7** | marrone / bianco | +12 V | ❌ **NON collegare** |

```
   Inverter RJ45                    USB-RS485                Home Assistant
  ┌──────────────┐                ┌───────────┐             ┌─────────────┐
  │ pin 3 ───────┼── verde/bianco ┤ A+        │             │             │
  │ pin 6 ───────┼── verde ───────┤ B-    USB ├──────────── ┤ /dev/ttyUSB0│
  │ pin 8 ───────┼── marrone ─────┤ GND       │             │             │
  │ pin 7   ✕    │                └───────────┘             └─────────────┘
  └──────────────┘
```

> 💡 **Se non leggi nulla, prova a invertire A+ e B-.** È l'errore più comune e non
> danneggia nulla: la polarità RS485 non è standardizzata tra i produttori.

Parametri della linea, fissi lato inverter: **9600 baud, 8N1**, nessun controllo di
flusso.

---

## ⚙️ Opzioni dell'add-on

| Opzione | Default | Descrizione |
|---|---|---|
| `serial_port` | `/dev/ttyUSB0` | Percorso della porta seriale dell'adattatore RS485. Vedi [porta seriale stabile](#-porta-seriale-stabile). |
| `baudrate` | `9600` | Velocità della linea. L'inverter usa 9600: cambiala solo se sai cosa fai. |
| `poll_interval` | `5` | Secondi di pausa tra un ciclo di lettura e il successivo (1-3600). |
| `mqtt_host` | `core-mosquitto` | Host o IP del broker MQTT. |
| `mqtt_port` | `1883` | Porta del broker. |
| `mqtt_user` | *(vuoto)* | Utente MQTT. Lascia vuoto se il broker è aperto. |
| `mqtt_password` | *(vuoto)* | Password MQTT. |
| `mqtt_prefix` | `tbb/inverter` | Prefisso di tutti i topic pubblicati e dei comandi. |

**Broker Mosquitto ufficiale?** I default funzionano già: `core-mosquitto` è il
nome interno del container. Ti basta creare un utente Home Assistant dedicato e
inserirne le credenziali in `mqtt_user` / `mqtt_password`.

**Broker esterno?** Metti il suo IP in `mqtt_host` e le relative credenziali.

### Ogni quanto interrogare?

| `poll_interval` | Quando ha senso |
|:---:|---|
| `2`-`3` | Vuoi reattività quasi in tempo reale (più scritture nel database di HA) |
| `5` | **Consigliato** — buon compromesso tra dettaglio e carico |
| `15`-`30` | Ti interessa solo l'andamento giornaliero, database più snello |

---

## 🔗 Porta seriale stabile

Il nome `/dev/ttyUSB0` **non è garantito**: se scolleghi l'adattatore, o se hai
un'altra periferica USB seriale (una chiavetta Zigbee, per esempio), l'ordine di
enumerazione può cambiare e l'add-on smette di leggere.

Apri l'add-on **Terminal & SSH** (o accedi via SSH) ed esegui:

```bash
ls -l /dev/serial/by-id/
```

Otterrai qualcosa come:

```
usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0 -> ../../ttyUSB0
```

Usa il percorso completo come valore di `serial_port`:

```yaml
serial_port: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0
```

Questo identificativo è legato al chip dell'adattatore e non cambia mai.

---

## 📡 Topic MQTT pubblicati

Tutti i topic sono pubblicati con flag **retain**, sotto il prefisso configurato
(qui indicato come `<prefix>`, default `tbb/inverter`).

### ☀️ Fotovoltaico e MPPT

| Topic | Unità | Descrizione |
|---|:---:|---|
| `pv_v` | V | Tensione del campo fotovoltaico |
| `mppt_i` | A | Corrente in ingresso all'MPPT |
| `pv_w` | W | Potenza fotovoltaica prodotta |
| `mppt_temp` | °C | Temperatura del regolatore di carica |

### 🔋 Batteria

| Topic | Unità | Descrizione |
|---|:---:|---|
| `bat_v` | V | Tensione di batteria misurata dall'inverter |
| `bat_v_bms` | V | Tensione riportata dal BMS della batteria |
| `bat_i` | A | Corrente di batteria **con segno**: positiva = carica, negativa = scarica |
| `soc` | % | Stato di carica |
| `t_bat` | °C | Temperatura della batteria |

### 🔌 Uscite AC

| Topic | Unità | Descrizione |
|---|:---:|---|
| `ac_out_v` / `ac_out_i` / `ac_out_w` | V / A / W | Prima uscita AC |
| `ac_out2_v` / `ac_out2_i` / `ac_out2_w` | V / A / W | Seconda uscita AC (`ac_out2_w` è calcolato come V × A) |
| `ac_freq` | Hz | Frequenza di uscita |
| `load_pct` | % | Carico rispetto alla potenza nominale |

### 🏠 Ingresso rete

| Topic | Unità | Descrizione |
|---|:---:|---|
| `ac_in_v` | V | Tensione di rete |
| `ac_in_i` | A | Corrente **con segno**: negativa = stai prelevando dalla rete, positiva = stai immettendo |

### 🌡️ Temperature interne

| Topic | Unità | Descrizione |
|---|:---:|---|
| `t_heatsink` | °C | Dissipatore |
| `t_transformer` | °C | Trasformatore |
| `t_inverter` | °C | Stadio inverter |

### 📦 Topic aggregato

| Topic | Contenuto |
|---|---|
| `stato` | JSON con **tutte** le grandezze qui sopra in un unico messaggio |

```json
{"ac_out_w": 1116, "ac_out_v": 230.2, "bat_v": 53.412, "bat_i": 14.2,
 "soc": 87, "pv_w": 1817, "pv_v": 248.6, "mppt_i": 7.31, ...}
```

---

## 🏠 Creare i sensori in Home Assistant

Il modo più compatto è leggere **un solo topic** (`stato`) ed estrarre i valori con
`value_template`. Aggiungi in `configuration.yaml` e riavvia Home Assistant.

```yaml
mqtt:
  sensor:
    - name: "Inverter PV Potenza"
      unique_id: tbb_pv_w
      state_topic: "tbb/inverter/stato"
      value_template: "{{ value_json.pv_w }}"
      unit_of_measurement: "W"
      device_class: power
      state_class: measurement

    - name: "Inverter Batteria SOC"
      unique_id: tbb_soc
      state_topic: "tbb/inverter/stato"
      value_template: "{{ value_json.soc }}"
      unit_of_measurement: "%"
      device_class: battery
      state_class: measurement

    - name: "Inverter Batteria Tensione"
      unique_id: tbb_bat_v
      state_topic: "tbb/inverter/stato"
      value_template: "{{ value_json.bat_v }}"
      unit_of_measurement: "V"
      device_class: voltage
      state_class: measurement

    - name: "Inverter Batteria Corrente"
      unique_id: tbb_bat_i
      state_topic: "tbb/inverter/stato"
      value_template: "{{ value_json.bat_i }}"
      unit_of_measurement: "A"
      device_class: current
      state_class: measurement

    - name: "Inverter Uscita AC Potenza"
      unique_id: tbb_ac_out_w
      state_topic: "tbb/inverter/stato"
      value_template: "{{ value_json.ac_out_w }}"
      unit_of_measurement: "W"
      device_class: power
      state_class: measurement

    - name: "Inverter Temperatura Dissipatore"
      unique_id: tbb_t_heatsink
      state_topic: "tbb/inverter/stato"
      value_template: "{{ value_json.t_heatsink }}"
      unit_of_measurement: "°C"
      device_class: temperature
      state_class: measurement
```

Ripeti il blocco per le altre grandezze cambiando `name`, `unique_id`, la chiave in
`value_template` e i `device_class` / `unit_of_measurement` secondo le tabelle
sopra.

### Device class da usare

| Grandezza | `device_class` | `unit_of_measurement` |
|---|---|---|
| Potenze (`*_w`) | `power` | `W` |
| Tensioni (`*_v`) | `voltage` | `V` |
| Correnti (`*_i`) | `current` | `A` |
| Temperature (`t_*`, `mppt_temp`) | `temperature` | `°C` |
| `soc` | `battery` | `%` |
| `ac_freq` | `frequency` | `Hz` |
| `load_pct` | *(nessuna)* | `%` |

### Sensore "direzione batteria"

Comodo per le automazioni e le dashboard:

```yaml
template:
  - sensor:
      - name: "Inverter Stato Batteria"
        state: >
          {% set i = states('sensor.inverter_batteria_corrente') | float(0) %}
          {% if i > 0.5 %}In carica
          {% elif i < -0.5 %}In scarica
          {% else %}A riposo{% endif %}
        icon: >
          {% set i = states('sensor.inverter_batteria_corrente') | float(0) %}
          {% if i > 0.5 %}mdi:battery-charging
          {% elif i < -0.5 %}mdi:battery-arrow-down
          {% else %}mdi:battery{% endif %}
```

---

## ⚡ Energy Dashboard

L'inverter riporta **potenze istantanee (W)**, mentre la Energy Dashboard vuole
**energia cumulata (kWh)**. La conversione si fa con un helper di integrazione
(somma di Riemann).

**Impostazioni → Dispositivi e servizi → Helper → Crea helper → Integrale-Riemann**

| Campo | Valore |
|---|---|
| Sensore in ingresso | `sensor.inverter_pv_potenza` |
| Metodo di integrazione | Trapezoidale |
| Prefisso metrico | `k` (kilo) |
| Unità di tempo massima | Ore (h) |

Ottieni `sensor.inverter_pv_potenza_integral` in kWh, da aggiungere nella Energy
Dashboard come **Pannelli solari**. Ripeti il procedimento per l'uscita AC se vuoi
tracciare anche i consumi.

---

## 🎛️ Comandi di scrittura

L'add-on è in ascolto su `<prefix>/cmd/#` e può **scrivere** nell'inverter.

### SmartPort

Imposta il livello della SmartPort (registro `0x005E`) da 0 a 100 %. L'add-on invia
automaticamente la sequenza di sblocco richiesta dall'inverter.

```yaml
# Esempio di azione in un'automazione o in uno script
action: mqtt.publish
data:
  topic: tbb/inverter/cmd/smart_port
  payload: "40"
```

### Frame raw

Invia un frame RS485 arbitrario, byte in esadecimale separati da spazi. **CRC
incluso**: non viene calcolato dall'add-on.

```yaml
action: mqtt.publish
data:
  topic: tbb/inverter/cmd/raw
  payload: "7E FF 11 06 06 0C 00 5E 00 28 81 46"
```

### Esito dei comandi

Ogni comando pubblica il risultato su un topic dedicato:

| Topic | Valori |
|---|---|
| `<prefix>/cmd/smart_port/status` | `OK` / `ERRORE` |
| `<prefix>/cmd/raw/status` | `OK` / `ERRORE` |

Nella scheda **Log** trovi il dettaglio di ogni frame trasmesso (`>> TX:`) e delle
risposte ricevute (`<< RX:`).

> ⚠️ **`cmd/raw` scrive direttamente nei registri dell'inverter.** Un frame
> sbagliato può modificare parametri di funzionamento dell'impianto. Usalo solo se
> hai la documentazione del registro che stai toccando, e non esporre il broker
> MQTT su Internet senza autenticazione.

---

## 🛠️ Risoluzione problemi

### Nel log compare `[!] Ciclo N: nessuna risposta`

L'add-on trasmette ma l'inverter non risponde.

| Verifica | Come |
|---|---|
| **Polarità invertita** | Scambia A+ e B-. È la causa più frequente e non danneggia nulla. |
| **Cavo sul pin giusto** | Solo i pin 3 e 6 dell'RJ45 portano i dati. Un cavo Ethernet crimpato T568B ha verde/bianco sul 3 e verde sul 6. |
| **Adattatore giusto** | Serve RS485, non RS232 né TTL. |
| **Porta corretta** | Se hai più device USB seriali, potresti aver puntato quello sbagliato: usa il percorso `by-id`. |
| **Baudrate** | Deve restare `9600`. |

### `[ERRORE] Impossibile aprire /dev/ttyUSB0`

La porta non esiste o è occupata.

- Controlla che l'adattatore sia elencato: `ls -l /dev/serial/by-id/`
- Verifica che nessun'altra integrazione o add-on stia usando la stessa porta
  (Zigbee2MQTT, ZHA, ESPHome…)
- Scollega e ricollega l'adattatore, poi riavvia l'add-on

### `[!] MQTT errore connessione`

L'add-on prosegue in sola lettura locale (i valori compaiono nel log ma non in HA).

- Con Mosquitto come add-on, `mqtt_host` deve essere `core-mosquitto`
- Le credenziali MQTT sono quelle di un **utente Home Assistant**, non del sistema
- Con un broker esterno, verifica che la porta 1883 sia raggiungibile dall'host di HA

### I valori arrivano su MQTT ma non vedo i sensori

Home Assistant non crea i sensori da solo: vanno dichiarati in `configuration.yaml`
come mostrato [sopra](#-creare-i-sensori-in-home-assistant). Dopo averli aggiunti,
riavvia Home Assistant (non basta un ricaricamento della sola configurazione MQTT
la prima volta).

Per controllare che i messaggi arrivino davvero: **Impostazioni → Dispositivi e
servizi → MQTT → Configura → Ascolta un argomento**, e sottoscrivi
`tbb/inverter/#`.

### Alcuni valori restano a 0

Le risposte dell'inverter possono essere più corte del previsto: i campi mancanti
vengono pubblicati come `0`. Se un valore è stabilmente a zero mentre gli altri sono
corretti, quel dato probabilmente non è esposto dal tuo modello o firmware.

---

## 🔍 Il protocollo in breve

L'add-on interroga ciclicamente due frame di lettura:

| Comando | Frame inviato | Contenuto della risposta |
|---|---|---|
| **C0** | `7E FF 11 03 C0 08 BA EB` | AC in/out, batteria, SOC, temperature, carico |
| **C1** | `7E FF 11 03 C1 08 BB 7B` | PV, MPPT, tensione BMS |

I frame di scrittura seguono lo schema `7E FF 11 06 <cmd> 0C <reg_hi> <reg_lo>
<val_hi> <val_lo> <crc_lo> <crc_hi>`, con **CRC16/MODBUS** (polinomio `0xA001`,
init `0xFFFF`, little-endian).

> Il protocollo non è documentato dal produttore: è stato ricostruito per
> osservazione. Modelli o firmware diversi possono avere offset differenti.

---

## 💬 Supporto

Problemi, idee o registri decodificati da aggiungere?
[Apri una issue su GitHub](https://github.com/CarloFalco/ha-tbb-inverter-addon/issues)
allegando le righe di log rilevanti e il modello esatto del tuo inverter.
