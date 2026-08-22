# 📘 Documentazione — TBB Inverter Reader

Guida completa all'installazione, configurazione e integrazione dell'add-on in
Home Assistant.

| | |
|---|---|
| [🔌 Collegamento hardware](#-collegamento-hardware) | Cablaggio RJ45 ↔ RS485 |
| [⚙️ Opzioni](#-opzioni-dellagg-on) | Tutti i parametri configurabili |
| [🔗 Porta seriale stabile](#-porta-seriale-stabile) | Evitare che `/dev/ttyUSB0` cambi |
| [🏠 Le entità in Home Assistant](#-le-entità-in-home-assistant) | Create da sole, senza YAML |
| [⚙ Canali calcolati](#-canali-calcolati) | Potenze ricavate dalle letture |
| [⚡ Energy Dashboard](#-energy-dashboard) | Da watt a kWh |
| [🎛️ Comandi di scrittura](#-comandi-di-scrittura) | SmartPort e frame raw |
| [📡 Topic MQTT](#-topic-mqtt) | Riferimento completo dei topic |
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

### Connessione

| Opzione | Default | Descrizione |
|---|---|---|
| `serial_port` | `/dev/ttyUSB0` | Percorso della porta seriale dell'adattatore RS485. Vedi [porta seriale stabile](#-porta-seriale-stabile). |
| `baudrate` | `9600` | Velocità della linea. L'inverter usa 9600: cambiala solo se sai cosa fai. |
| `poll_interval` | `5` | Secondi di pausa tra un ciclo di lettura e il successivo (1-3600). |

### MQTT

| Opzione | Default | Descrizione |
|---|---|---|
| `mqtt_host` | *(vuoto)* | **Lascia vuoto** per usare automaticamente il broker configurato in Home Assistant. Compilalo solo per un broker esterno. |
| `mqtt_port` | `1883` | Usata solo se hai compilato `mqtt_host`. |
| `mqtt_user` | *(vuoto)* | Usato solo se hai compilato `mqtt_host`. |
| `mqtt_password` | *(vuoto)* | Usata solo se hai compilato `mqtt_host`. |
| `mqtt_prefix` | `tbb/inverter` | Prefisso di tutti i topic pubblicati e dei comandi. |

> 🎉 **Con l'add-on *Mosquitto broker* non devi configurare nulla.** Lasciando
> `mqtt_host` vuoto, l'add-on chiede host, porta e credenziali direttamente al
> Supervisor. Compila i campi solo se il tuo broker è su un'altra macchina.

### Funzionalità

| Opzione | Default | Descrizione |
|---|---|---|
| `mqtt_discovery` | `true` | Crea automaticamente le entità in Home Assistant. Disattivalo solo se preferisci definire i sensori a mano. |
| `discovery_prefix` | `homeassistant` | Cambialo solo se hai personalizzato il prefisso di discovery dell'integrazione MQTT. |
| `allow_raw_command` | `false` | Abilita il topic `cmd/raw`. Vedi [l'avviso](#frame-raw). |
| `strict_crc` | `false` | Scarta le risposte con CRC non valido invece di provare comunque a decodificarle. |
| `log_level` | `info` | `info` stampa la tabella dei valori ad ogni ciclo, `notice` solo gli eventi, `debug` aggiunge i frame esadecimali TX/RX. |

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

## 🏠 Le entità in Home Assistant

Con `mqtt_discovery` attivo (impostazione predefinita) **non devi scrivere alcuno
YAML**. Al primo avvio l'add-on crea un dispositivo **TBB RiiO Sun II** con tutte
le entità già configurate:

**Impostazioni → Dispositivi e servizi → MQTT → TBB RiiO Sun II**

### Entità create

| Entità | Unità | `entity_id` |
|---|:---:|---|
| Potenza FV | W | `sensor.tbb_riio_sun_ii_pv_w` |
| Tensione FV | V | `sensor.tbb_riio_sun_ii_pv_v` |
| Corrente MPPT | A | `sensor.tbb_riio_sun_ii_mppt_i` |
| Temperatura MPPT | °C | `sensor.tbb_riio_sun_ii_mppt_temp` |
| Tensione batteria | V | `sensor.tbb_riio_sun_ii_bat_v` |
| Tensione batteria BMS | V | `sensor.tbb_riio_sun_ii_bat_v_bms` |
| Corrente batteria | A | `sensor.tbb_riio_sun_ii_bat_i` |
| **Potenza batteria** ⚙ | W | `sensor.tbb_riio_sun_ii_bat_w` |
| Stato di carica | % | `sensor.tbb_riio_sun_ii_soc` |
| Stato batteria | — | `sensor.tbb_riio_sun_ii_bat_status` |
| Temperatura batteria | °C | `sensor.tbb_riio_sun_ii_t_bat` |
| Tensione / Corrente / Potenza uscita AC | V / A / W | `sensor.tbb_riio_sun_ii_ac_out_v` … |
| Tensione / Corrente / Potenza uscita AC 2 | V / A / W | `sensor.tbb_riio_sun_ii_ac_out2_v` … |
| **Potenza uscita AC totale** ⚙ | W | `sensor.tbb_riio_sun_ii_ac_out_tot_w` |
| Frequenza uscita | Hz | `sensor.tbb_riio_sun_ii_ac_freq` |
| Carico | % | `sensor.tbb_riio_sun_ii_load_pct` |
| Tensione / Corrente rete | V / A | `sensor.tbb_riio_sun_ii_ac_in_v` … |
| **Potenza rete** ⚙ | W | `sensor.tbb_riio_sun_ii_ac_in_w` |
| Temperature dissipatore / trasformatore / inverter | °C | *(diagnostica)* |
| **SmartPort** *(slider scrivibile)* | % | `number.tbb_riio_sun_ii_smart_port` |

Le voci con ⚙ sono [canali calcolati](#-canali-calcolati). `bat_status` vale
*In carica*, *In scarica* o *A riposo*, ricavato dal segno della corrente di
batteria.

### Disponibilità

Tutte le entità seguono il topic `<prefix>/availability`. Se l'add-on si ferma o
perde la porta seriale, passano a **non disponibili** invece di restare bloccate
sull'ultimo valore letto: i grafici mostrano un buco, non una linea piatta finta.

### Sensori a mano (senza discovery)

<details>
<summary>Se preferisci definire i sensori in <code>configuration.yaml</code></summary>

Imposta `mqtt_discovery: false` e usa il topic aggregato `stato`, che contiene
tutte le grandezze in un unico JSON:

```yaml
mqtt:
  sensor:
    - name: "Inverter PV Potenza"
      unique_id: tbb_pv_w
      state_topic: "tbb/inverter/stato"
      value_template: "{{ value_json.pv_w }}"
      availability_topic: "tbb/inverter/availability"
      unit_of_measurement: "W"
      device_class: power
      state_class: measurement

    - name: "Inverter Batteria SOC"
      unique_id: tbb_soc
      state_topic: "tbb/inverter/stato"
      value_template: "{{ value_json.soc }}"
      availability_topic: "tbb/inverter/availability"
      unit_of_measurement: "%"
      device_class: battery
      state_class: measurement
```

Ripeti il blocco cambiando `name`, `unique_id` e la chiave in `value_template`,
usando questa corrispondenza:

| Grandezza | `device_class` | `unit_of_measurement` |
|---|---|---|
| Potenze (`*_w`) | `power` | `W` |
| Tensioni (`*_v`) | `voltage` | `V` |
| Correnti (`*_i`) | `current` | `A` |
| Temperature (`t_*`, `mppt_temp`) | `temperature` | `°C` |
| `soc` | `battery` | `%` |
| `ac_freq` | `frequency` | `Hz` |
| `load_pct` | *(nessuna)* | `%` |

</details>

---

## ⚙ Canali calcolati

Alcune entità non arrivano dall'inverter ma vengono ricavate dalle grandezze
lette, ad ogni ciclo:

| Entità | Calcolo | Come leggere il segno |
|---|---|---|
| `bat_w` — Potenza batteria | `bat_v` × `bat_i` | **positiva** = batteria in carica, **negativa** = in scarica |
| `ac_in_w` — Potenza rete | `ac_in_v` × `ac_in_i` | **negativa** = stai prelevando dalla rete, **positiva** = stai immettendo |
| `ac_out2_w` — Potenza uscita AC 2 | `ac_out2_v` × `ac_out2_i` | — |
| `ac_out_tot_w` — Potenza uscita AC totale | `ac_out_w` + `ac_out2_w` | — |
| `bat_status` — Stato batteria | segno di `bat_i` | *In carica* / *In scarica* / *A riposo* |

Un canale calcolato compare **solo se tutti i suoi ingressi sono presenti** nel
ciclo. Se una risposta arriva corta e manca la corrente di batteria, `bat_w` non
viene aggiornato invece di crollare a zero.

> ⚠️ **Precisione sui canali AC.** Sulla batteria, che è in continua, tensione ×
> corrente dà la potenza reale in watt, esatta. Sui canali in alternata
> (`ac_in_w`, `ac_out2_w`) lo stesso prodotto dà la **potenza apparente** (VA):
> coincide con i watt solo se il fattore di potenza è vicino a 1. Con carichi
> fortemente induttivi aspettati una sovrastima. `ac_out_w` invece è misurato
> direttamente dall'inverter, quindi è potenza reale.

### Aggiungerne altri

Sono definiti in una sola tabella in `tbb_reader.py`:

```python
DERIVED = [
    ("bat_w", ("bat_v", "bat_i"), lambda d: round(d["bat_v"] * d["bat_i"], 1)),
    ...
]
```

Ogni voce dichiara la chiave, le sue dipendenze e il calcolo. Le voci sono
valutate in ordine, quindi un canale può dipendere da uno definito prima
(`ac_out_tot_w` usa `ac_out2_w`). Aggiunta la riga, serve la voce corrispondente
in `SENSORS` perché l'entità compaia in Home Assistant — un test lo verifica.

---

## ⚡ Energy Dashboard

L'inverter riporta **potenze istantanee (W)**, mentre la Energy Dashboard vuole
**energia cumulata (kWh)**. La conversione si fa con un helper di integrazione
(somma di Riemann).

**Impostazioni → Dispositivi e servizi → Helper → Crea helper → Integrale-Riemann**

| Campo | Valore |
|---|---|
| Sensore in ingresso | `sensor.tbb_riio_sun_ii_pv_w` |
| Metodo di integrazione | Trapezoidale |
| Prefisso metrico | `k` (kilo) |
| Unità di tempo massima | Ore (h) |

Ottieni un sensore in kWh da aggiungere nella Energy Dashboard come **Pannelli
solari**. Ripeti il procedimento con `sensor.tbb_riio_sun_ii_ac_out_tot_w` se
vuoi tracciare i consumi di entrambe le uscite.

---

## 🎛️ Comandi di scrittura

### SmartPort

Il modo più semplice è lo **slider** creato da discovery
(`number.tbb_riio_sun_ii_smart_port`): trascinalo, oppure usalo in un'automazione.

```yaml
action: number.set_value
target:
  entity_id: number.tbb_riio_sun_ii_smart_port
data:
  value: 40
```

In alternativa, direttamente su MQTT:

```yaml
action: mqtt.publish
data:
  topic: tbb/inverter/cmd/smart_port
  payload: "40"
```

L'add-on invia automaticamente la sequenza di sblocco richiesta dall'inverter
prima di scrivere il registro `0x005E`.

### Frame raw

> ⚠️ **Disabilitato per impostazione predefinita.** Attiva `allow_raw_command`
> nella configurazione per usarlo. Questo topic scrive **direttamente** nei
> registri dell'inverter: un frame sbagliato può modificare parametri di
> funzionamento dell'impianto. Usalo solo se hai la documentazione del registro
> che stai toccando, e non esporre il broker MQTT su Internet senza
> autenticazione.

Byte in esadecimale separati da spazi, **CRC incluso** (non viene calcolato
dall'add-on):

```yaml
action: mqtt.publish
data:
  topic: tbb/inverter/cmd/raw
  payload: "7E FF 11 06 06 0C 00 5E 00 28 81 46"
```

### Esito dei comandi

| Topic | Valori |
|---|---|
| `<prefix>/cmd/smart_port/status` | `OK` / `ERRORE` |
| `<prefix>/cmd/raw/status` | `OK` / `ERRORE` |

Con `log_level: debug` la scheda **Log** mostra il dettaglio di ogni frame
trasmesso (`TX:`) e delle risposte ricevute (`ACK:`).

---

## 📡 Topic MQTT

Tutti i topic sono pubblicati con flag **retain**, sotto il prefisso configurato
(qui `<prefix>`, default `tbb/inverter`). Vengono pubblicate **solo le grandezze
effettivamente decodificate**: se un frame arriva incompleto, il topic
corrispondente non viene aggiornato invece di finire a zero.

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
| `bat_w` ⚙ | W | Potenza di batteria **con segno**: `bat_v` × `bat_i` |
| `bat_status` | — | *In carica* / *In scarica* / *A riposo* |
| `soc` | % | Stato di carica |
| `t_bat` | °C | Temperatura della batteria |

### 🔌 Uscite AC

| Topic | Unità | Descrizione |
|---|:---:|---|
| `ac_out_v` / `ac_out_i` / `ac_out_w` | V / A / W | Prima uscita AC |
| `ac_out2_v` / `ac_out2_i` / `ac_out2_w` ⚙ | V / A / W | Seconda uscita AC (`ac_out2_w` è calcolato come V × A) |
| `ac_out_tot_w` ⚙ | W | Potenza totale erogata: somma delle due uscite |
| `ac_freq` | Hz | Frequenza di uscita |
| `load_pct` | % | Carico rispetto alla potenza nominale |

### 🏠 Ingresso rete

| Topic | Unità | Descrizione |
|---|:---:|---|
| `ac_in_v` | V | Tensione di rete |
| `ac_in_i` | A | Corrente **con segno**: negativa = stai prelevando dalla rete, positiva = stai immettendo |
| `ac_in_w` ⚙ | W | Potenza di rete **con segno**: `ac_in_v` × `ac_in_i` |

### 🌡️ Temperature interne

| Topic | Unità | Descrizione |
|---|:---:|---|
| `t_heatsink` | °C | Dissipatore |
| `t_transformer` | °C | Trasformatore |
| `t_inverter` | °C | Stadio inverter |

### 📦 Topic di servizio

| Topic | Contenuto |
|---|---|
| `stato` | JSON con tutte le grandezze lette nell'ultimo ciclo |
| `availability` | `online` / `offline` — usato da tutte le entità |
| `smart_port` | Ultimo valore SmartPort impostato con successo |

```json
{"ac_out_w": 1116, "ac_out_v": 230.2, "bat_v": 53.412, "bat_i": 14.2,
 "bat_status": "In carica", "soc": 87, "pv_w": 1817, "pv_v": 248.6, ...}
```

---

## 🛠️ Risoluzione problemi

### Nel log compare `Ciclo N: nessuna risposta dall'inverter`

L'add-on trasmette ma l'inverter non risponde.

| Verifica | Come |
|---|---|
| **Polarità invertita** | Scambia A+ e B-. È la causa più frequente e non danneggia nulla. |
| **Cavo sul pin giusto** | Solo i pin 3 e 6 dell'RJ45 portano i dati. Un cavo Ethernet crimpato T568B ha verde/bianco sul 3 e verde sul 6. |
| **Adattatore giusto** | Serve RS485, non RS232 né TTL. |
| **Porta corretta** | Se hai più device USB seriali, potresti aver puntato quello sbagliato: usa il percorso `by-id`. |
| **Baudrate** | Deve restare `9600`. |

Imposta `log_level: debug` per vedere i byte effettivamente ricevuti: se non
compare nessuna riga `RX`, il problema è nel cablaggio.

### `Impossibile aprire /dev/ttyUSB0`

La porta non esiste o è occupata. L'add-on riprova ogni 10 secondi, non serve
riavviarlo a mano.

- All'avvio il log elenca i dispositivi seriali disponibili: controlla che il tuo
  compaia
- Verifica che nessun'altra integrazione o add-on stia usando la stessa porta
  (Zigbee2MQTT, ZHA, ESPHome…)
- Scollega e ricollega l'adattatore

### `Nessun broker MQTT disponibile`

L'add-on non parte perché non trova un broker.

- Installa l'add-on ufficiale **Mosquitto broker** e lascia `mqtt_host` vuoto
- Oppure compila `mqtt_host`, `mqtt_port` e le credenziali del tuo broker esterno

### Non vedo il dispositivo in Home Assistant

- Controlla che `mqtt_discovery` sia `true`
- L'integrazione **MQTT** deve essere configurata in Home Assistant
  (*Impostazioni → Dispositivi e servizi*)
- Se hai cambiato `discovery_prefix`, deve coincidere con quello dell'integrazione
- Riavvia l'add-on: i messaggi di discovery vengono ripubblicati ad ogni
  connessione

Per verificare che i messaggi arrivino: **Impostazioni → Dispositivi e servizi →
MQTT → Configura → Ascolta un argomento**, e sottoscrivi `tbb/inverter/#`.

### Le entità risultano "non disponibili"

Significa che l'add-on non sta leggendo dall'inverter: guarda il log, di solito è
la porta seriale. È il comportamento voluto — meglio un buco nel grafico che un
valore vecchio spacciato per attuale.

### Alcuni valori non si aggiornano mai

Le risposte dell'inverter possono essere più corte del previsto: i campi mancanti
non vengono pubblicati. Se una grandezza resta ferma mentre le altre cambiano,
probabilmente non è esposta dal tuo modello o firmware.

### Riavvio automatico dopo un crash

Nella pagina dell'add-on, attiva l'interruttore **Watchdog**: Home Assistant lo
riavvierà da solo se dovesse terminare in modo inatteso.

---

## 🔍 Il protocollo in breve

L'add-on interroga ciclicamente due frame di lettura:

| Comando | Frame inviato | Contenuto della risposta |
|---|---|---|
| **C0** | `7E FF 11 03 C0 08 BA EB` | AC in/out, batteria, SOC, temperature, carico |
| **C1** | `7E FF 11 03 C1 08 BB 7B` | PV, MPPT, tensione BMS |

I frame di scrittura seguono lo schema `7E FF 11 06 <cmd> 0C <reg_hi> <reg_lo>
<val_hi> <val_lo> <crc_lo> <crc_hi>`, con **CRC16/MODBUS** (polinomio `0xA001`,
init `0xFFFF`, little-endian). Il byte in posizione 5 contiene la lunghezza
totale del frame.

Il CRC delle risposte viene verificato individuando il confine del frame: al
primo frame validato il log riporta

```
[INFO] Verifica CRC delle risposte attiva (frame di N byte)
```

Se questa riga non compare mai, il CRC non è verificabile sul tuo firmware e
l'add-on decodifica comunque (a meno che `strict_crc` sia attivo).

> Il protocollo non è documentato dal produttore: è stato ricostruito per
> osservazione. Modelli o firmware diversi possono avere offset differenti.

---

## 💬 Supporto

Problemi, idee o registri decodificati da aggiungere?
[Apri una issue su GitHub](https://github.com/CarloFalco/ha-tbb-inverter-addon/issues)
allegando le righe di log rilevanti (con `log_level: debug`) e il modello esatto
del tuo inverter.
