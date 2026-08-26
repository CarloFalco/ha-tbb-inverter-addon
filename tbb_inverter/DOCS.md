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
| [🛡 Impronta sul sistema](#-impronta-sul-sistema) | Risorse usate e salute del Raspberry Pi |

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
| `poll_interval` | `30` | Secondi di pausa tra un ciclo di lettura e il successivo (1-3600). |

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
| `smartport_register_unit` | `ampere` | Cosa contiene il registro `0x005E`: `ampere` (il numero **sono** gli ampere) o `percent`. Vedi la verifica nei [comandi](#-comandi-di-scrittura). |
| `smartport_a_at_zero` | `0` | Solo con `percent`: corrente corrispondente al registro a 0. |
| `smartport_min_a` | `5` | Estremo inferiore dello slider in ampere. Sul RiiO Sun II il minimo è 5 A e l'inverter non scende sotto. |
| `smartport_max_a` | `32` | Estremo superiore dello slider in ampere (e corrente a registro 100 con `percent`). |
| `smartport_voltage` | `230` | Tensione usata per convertire ampere in watt nello slider in W. Impostala alla tua tensione di rete reale (es. `251`) se vuoi che i watt dello slider corrispondano alla potenza misurata. |
| `log_level` | `info` | `info` stampa la tabella dei valori ad ogni ciclo, `notice` solo gli eventi, `debug` aggiunge i frame esadecimali TX/RX. |

### Ogni quanto interrogare?

Ogni ciclo aggiorna **27 topic**. Il costo non è la lettura in sé — che dura
poche centinaia di millisecondi — ma il numero di aggiornamenti che ne derivano
in Home Assistant.

| `poll_interval` | Aggiornamenti al giorno | Quando ha senso |
|:---:|---:|---|
| `5` | ~467.000 | Solo se ti serve vedere le variazioni rapide di potenza, e HA gira su SSD |
| `15` | ~156.000 | Buon dettaglio, carico contenuto |
| `30` | ~78.000 | **Predefinito** — adatto a Raspberry Pi e microSD |
| `60` | ~39.000 | Ti interessa soprattutto risparmiare scritture |
| `300` | ~7.800 | Ti basta l'andamento giornaliero |

> Su Raspberry Pi 3 con Home Assistant su microSD, `30` è il valore da cui
> partire. Scendi solo se hai una ragione precisa per farlo.

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
| Temperatura MPPT 🔧 | °C | `sensor.tbb_riio_sun_ii_mppt_temp` |
| Tensione batteria | V | `sensor.tbb_riio_sun_ii_bat_v` |
| Tensione batteria BMS 🔧 | V | `sensor.tbb_riio_sun_ii_bat_v_bms` |
| Corrente batteria | A | `sensor.tbb_riio_sun_ii_bat_i` |
| **Potenza batteria** ⚙ | W | `sensor.tbb_riio_sun_ii_bat_w` |
| Stato di carica | % | `sensor.tbb_riio_sun_ii_soc` |
| Stato batteria | — | `sensor.tbb_riio_sun_ii_bat_status` |
| Temperatura batteria | °C | `sensor.tbb_riio_sun_ii_t_bat` |
| Tensione / Corrente / Potenza uscita AC | V / A / W | `sensor.tbb_riio_sun_ii_ac_out_v` … |
| Tensione / Corrente / Potenza uscita AC 2 | V / A / W | `sensor.tbb_riio_sun_ii_ac_out2_v` … |
| **Potenza uscita AC totale** ⚙ | W | `sensor.tbb_riio_sun_ii_ac_out_tot_w` |
| Frequenza uscita 🔧 | Hz | `sensor.tbb_riio_sun_ii_ac_freq` |
| Carico | % | `sensor.tbb_riio_sun_ii_load_pct` |
| Tensione / Corrente rete | V / A | `sensor.tbb_riio_sun_ii_ac_in_v` … |
| **Potenza rete** ⚙ | W | `sensor.tbb_riio_sun_ii_ac_in_w` |
| Temperature dissipatore / trasformatore / inverter 🔧 | °C | `sensor.tbb_riio_sun_ii_t_heatsink` … |
| **SmartPort registro** *(scrivibile)* | — | `number.tbb_riio_sun_ii_smart_port` |
| **SmartPort corrente** *(scrivibile)* | A | `number.tbb_riio_sun_ii_smart_port_a` |
| **SmartPort potenza** *(scrivibile)* | W | `number.tbb_riio_sun_ii_smart_port_w` |

Le voci con ⚙ sono [canali calcolati](#-canali-calcolati). `bat_status` vale
*In carica*, *In scarica* o *A riposo*, ricavato dal segno della corrente di
batteria.

Le voci con 🔧 sono **diagnostiche e nascono disabilitate**: servono a capire un
problema, non a governare l'impianto, e restano quasi immobili per ore. Finché
sono spente non producono stati e non finiscono nel database di Home Assistant.
Per accenderne una: *Impostazioni → Dispositivi → TBB RiiO Sun II →
Diagnostica*, poi l'interruttore nelle sue impostazioni. Non serve riavviare
l'add-on.

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

### SmartPort: tre slider, un solo valore

Il registro `0x005E` dell'inverter accetta un valore **0-100**, e su questo
firmware **quel numero sono gli ampere**: scrivere 20 imposta 20 A. Il
comportamento osservato sul RiiO Sun II è:

**Il dominio valido sono i numeri interi da 5 a 32**, un ampere alla volta.
Lo conferma anche l'app nativa, che non lascia scendere sotto 5 A né usare
valori frazionari. Fuori da quell'intervallo l'inverter accetta comunque la
scrittura, ma l'effetto non è definito.

**È un tetto, non un setpoint.** Il valore fissa il massimo che la SmartPort
può erogare: si vede solo quando sta *sotto* a quanto il carico sta già
chiedendo.

> ⚠️ **Attenzione a come lo verifichi: il carico rende il test cieco.**
> Il tetto più basso possibile è 5 A, cioè ~1,25 kW a 230 V (~1,26 kW a 251 V).
> Se il carico attaccato alla SmartPort assorbe **meno** di così, *nessuna*
> impostazione può avere un effetto visibile: le stai alzando tutte sopra la
> testa del carico.
>
> Con un carico da 1,3 kW, 27 delle 28 impostazioni legali sono già sopra
> l'assorbimento. La potenza resta identica per 6, 8, 16 e 32 A non perché la
> scrittura fallisca, ma perché non c'è niente da limitare.
>
> **Per una verifica valida serve un carico che assorba almeno 2,5-3 kW**
> (10-12 A). Allora impostando 5, 6, 7... 12 A la potenza deve seguire
> `ampere × tensione di rete`, e si vede subito se la scala è 1:1.

> L'inverter risponde con un ACK regolare — CRC valido e valore riecheggiato —
> a **qualunque** valore, anche fuori scala. Non dice mai di no: un ACK conferma
> che il frame è stato ricevuto, non che il parametro sia stato applicato.

| Entità | Unità | Intervallo | Cosa scrive nel registro |
|---|:---:|---|---|
| `number.tbb_riio_sun_ii_smart_port` | — | 0 → 100 | il numero stesso, senza conversioni |
| `number.tbb_riio_sun_ii_smart_port_a` | A | 5 → 32 | il numero stesso (16 A → 16) |
| `number.tbb_riio_sun_ii_smart_port_w` | W | 1150 → 7360 | i watt divisi per la tensione nominale |

**Sono tre viste della stessa cosa.** Scrivendone una, le altre due si
aggiornano da sole: non sono impostazioni indipendenti.

Per le automazioni conviene quella in ampere o in watt:

```yaml
action: number.set_value
target:
  entity_id: number.tbb_riio_sun_ii_smart_port_a
data:
  value: 16
```

In alternativa, direttamente su MQTT — un topic per unità:

```yaml
action: mqtt.publish
data:
  topic: tbb/inverter/cmd/smart_port_a
  payload: "16"
```

L'add-on converte nel valore di registro, verifica che sia nell'intervallo,
invia la sequenza di sblocco richiesta dall'inverter e scrive `0x005E`. Un
valore fuori scala viene rifiutato senza trasmettere un solo byte.

#### Se il tuo firmware interpreta il registro come percentuale

Non tutti i firmware devono per forza comportarsi come quello verificato qui.
L'opzione `smartport_register_unit` copre entrambe le convenzioni:

| Valore | Significato | Esempio |
|---|---|---|
| `ampere` *(default)* | il registro **è** la corrente | slider a 16 A → scrive 16 |
| `percent` | il registro è una percentuale 0-100 mappata su `smartport_a_at_zero` → `smartport_max_a` | slider a 16 A → scrive 50 |

**Come capire quale ti serve, in un minuto.** Porta lo slider **SmartPort
corrente** a 20 A e leggi la corrente sul display dell'inverter:

| Il display mostra | Modalità corretta |
|---|---|
| **~20 A** | `ampere` — è il default, non toccare nulla |
| **5 A** (cioè il minimo) o **~6-7 A** | `percent` |

In modalità `percent` valgono anche `smartport_a_at_zero` (corrente a registro
0) e `smartport_max_a` (corrente a registro 100), che definiscono la retta di
conversione.

> Lo slider **SmartPort registro** scrive sempre il numero che vedi, senza
> alcuna conversione, in entrambe le modalità: è la via di fuga se le altre
> due dovessero sbagliare.

#### Trovare dove l'inverter rilegge un parametro

L'add-on scrive nei registri ma non sa rileggerli: senza riscontro, «non ha
funzionato» e «ha funzionato ma non si vede» sono indistinguibili. L'opzione
`diag_frames` colma il buco.

I frame di lettura `C0`/`C1` sono lunghi ~198 byte e ne interpretiamo solo una
ventina: il resto contiene quasi certamente anche i parametri di
configurazione. Con `diag_frames: true` l'add-on confronta ogni frame con
quello precedente e segnala i byte cambiati — ma **solo quelli rimasti fermi
per almeno 3 cicli**. Le misure vive (tensioni, correnti, temperature)
oscillano di continuo e si filtrano da sole; un parametro sta immobile finché
qualcuno non lo cambia.

**Procedura:**

1. Attiva `diag_frames` e riavvia l'add-on.
2. Lascia passare una decina di cicli senza toccare nulla.
3. Cambia la SmartPort **dall'app nativa dell'inverter** (quella che
   sicuramente funziona), non da Home Assistant.
4. Guarda il log:

```
[NOTICE] DIAG C0[77 / 0x4D]: 05 -> 14  (5 -> 20, fermo da 12 cicli)  <-- OFFSET NON DECODIFICATO
```

Quell'offset è il punto in cui l'inverter rilegge la SmartPort, e i due valori
dicono anche in che unità la esprime. Da lì si può esporla come sensore e
verificare se le scritture dell'add-on attecchiscono davvero.

Ricordati di rimettere `diag_frames: false` quando hai finito.

#### Quando una scrittura non ha effetto

Il log riporta l'intera catena, dal comando MQTT ai byte sulla linea. Con
`log_level: info` una scrittura produce:

```
[NOTICE] Comando ricevuto: tbb/inverter/cmd/smart_port_a = 16
[INFO] Conversione: 16.0 A -> registro 16  (identita')
[NOTICE] SmartPort -> registro 0x005E = 16  (interpretato come 16 A, ~3680 W; modalita' registro: ampere)
[INFO] TX 1/3 (12 byte): 7E FF 11 06 66 0C 00 73 00 0A 98 F6
[INFO] TX 2/3 (12 byte): 7E FF 11 06 66 0C 00 74 00 0A 29 37
[INFO] TX 3/3 (12 byte): 7E FF 11 06 06 0C 00 5E 00 10 80 94
```

Cosa guardare, nell'ordine:

| Sintomo nel log | Significato |
|---|---|
| manca «Comando ricevuto» | il comando non arriva: controlla il broker MQTT e il prefisso dei topic |
| «Conversione» mostra un registro diverso da quello atteso | è la modalità del registro: vedi la sezione sopra |
| i tre `TX` ci sono ma l'inverter non cambia | i byte partono: confrontali con l'esempio stampato nel banner all'avvio |
| «L'inverter non ha risposto a nessuno dei 3 frame» | plausibile se i sensori funzionano (alcuni firmware non rispondono alle scritture); se anche le letture sono ferme, il problema è la linea RS485 |
| ogni `TX` ha il suo `RX` con il valore riecheggiato | **l'inverter ha accettato la scrittura**: il problema non è più nella trasmissione. Usa `diag_frames` per capire se il parametro cambia davvero |
| «Porta seriale non disponibile» | l'adattatore USB non è aperto: vedi la sezione risoluzione dei problemi |

### Esito dei comandi

| Topic | Valori |
|---|---|
| `<prefix>/cmd/smart_port/status` | `OK` / `ERRORE` |
| `<prefix>/cmd/smart_port_a/status` | `OK` / `ERRORE` |
| `<prefix>/cmd/smart_port_w/status` | `OK` / `ERRORE` |
| `<prefix>/cmd/raw/status` | `OK` / `ERRORE` |

I frame trasmessi da una scrittura (`TX n/3`) e le relative risposte
(`RX n/3`) compaiono già con `log_level: info`, perché sono rari e sono la
prima cosa da guardare. Con `log_level: debug` si aggiungono anche i frame
esadecimali di **ogni ciclo di lettura**.

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
| `smart_port` / `smart_port_a` / `smart_port_w` | Ultimo valore SmartPort impostato, nelle tre unità |

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

## 🛡 Impronta sul sistema

### Quanto consuma

| Risorsa | Valore tipico |
|---|---|
| CPU | trascurabile: circa 2 ms di calcolo per ciclo, cioè ogni `poll_interval` secondi |
| Memoria | costante. Un soak test di 10.000 cicli non mostra crescita |
| Thread | due: il ciclo di polling e la rete MQTT |
| Scritture su disco | nessuna: l'add-on non scrive file |
| Privilegi | solo `uart` (accesso alla seriale). Niente rete host, niente accesso privilegiato, nessuna API di Home Assistant |

Le letture sono protette da tetti espliciti: una risposta è limitata a 1024
byte e ogni lettura termina comunque entro il proprio limite di tempo, anche se
la linea RS485 non tace mai. Un frame `cmd/raw` oltre 64 byte viene rifiutato
prima di essere elaborato.

### Il vero costo è il database di Home Assistant

L'add-on è leggero, ma le **entità che crea non lo sono**: ogni ciclo aggiorna
27 topic, e il *recorder* di Home Assistant scrive nel database ogni valore che
cambia. Con `poll_interval: 5` sono centinaia di migliaia di righe al giorno.

Per questo, dalla 1.3.3, i valori predefiniti sono più prudenti: `poll_interval`
parte da **60 secondi** e le grandezze diagnostiche nascono **disabilitate**.

Su Home Assistant installato su **microSD** questo è il singolo fattore che più
logora la scheda, ed è una causa classica di sistemi che dopo mesi diventano
instabili o non si avviano più. Due contromisure, entrambe utili:

**1. Lascia spente le entità diagnostiche.** Temperature, tensione riportata dal
BMS e frequenza di uscita nascono già disabilitate: non producono stati e non
finiscono nel database finché non le abiliti tu. Le trovi nella sezione
*Diagnostica* del dispositivo, e si accendono in due clic senza riavviare
l'add-on. Se te ne serve una sola, abilita solo quella.

**2. Non registrare ciò che non ti serve.** In `configuration.yaml`:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.tbb_riio_sun_ii_t_*
      - sensor.tbb_riio_sun_ii_ac_out2_*
      - sensor.tbb_riio_sun_ii_bat_v_bms
      - sensor.tbb_riio_sun_ii_ac_freq
```

**3. Alza `poll_interval`.** È la leva più diretta: il carico scala linearmente.
Da 5 a 30 secondi le scritture scendono a un sesto, e per l'andamento
giornaliero non cambia nulla.

> ⚠️ **Se aggiorni da una versione precedente**, Home Assistant conserva le
> opzioni che avevi salvato: il nuovo valore predefinito **non** ti viene
> applicato da solo. Controlla `poll_interval` nella scheda Configurazione e
> portalo a 30 a mano.

Se puoi, **sposta Home Assistant su SSD o NVMe**: è il rimedio definitivo.

### Se il Raspberry Pi si blocca del tutto

Un add-on gira dentro un container e non può rendere irraggiungibile l'SSH: se
consumasse troppa memoria, il kernel terminerebbe il processo (OOM killer) e il
resto del sistema resterebbe in piedi. Un blocco totale ha quasi sempre una
causa a livello di sistema. In ordine di frequenza:

| Causa | Come riconoscerla |
|---|---|
| **Alimentatore insufficiente** | `dmesg \| grep -i voltage` mostra `Undervoltage detected`. È la causa numero uno, spesso peggiorata proprio dall'adattatore USB-RS485 che assorbe corrente |
| **microSD in degrado** | `dmesg \| grep -i mmc` e errori di I/O, filesystem che passa in sola lettura |
| **Memoria esaurita** | `dmesg \| grep -i "out of memory"` elenca il processo terminato |
| **Surriscaldamento** | `vcgencmd measure_temp`, throttling sopra gli 80 °C |

Comandi utili subito dopo un riavvio anomalo, dall'add-on **Terminal & SSH**:

```bash
dmesg -T | grep -iE "voltage|out of memory|mmc|I/O error|throttl" | tail -30
```

```bash
ha supervisor logs | tail -50
```

Per vedere quanta memoria sta usando davvero questo add-on, prima trova il suo
slug (installato da repository git, ha un prefisso generato):

```bash
ha addons list | grep -i -B2 -A2 tbb
```

poi:

```bash
ha addons stats SLUG_TROVATO_SOPRA
```

Se `memory_percent` resta stabile nel tempo, l'add-on non c'entra con il blocco.
Attiva anche l'interruttore **Watchdog** nella pagina dell'add-on: se dovesse
terminare in modo inatteso, Home Assistant lo riavvia da solo.

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
