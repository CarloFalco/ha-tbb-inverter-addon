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
| [💾 Backup e ripristino](#-backup-e-ripristino-dei-parametri) | Salvare e ripristinare la configurazione dell'inverter |
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
| `diag_frames` | `false` | Segnala nel log i byte dei frame di lettura che cambiano dopo essere rimasti fermi. Solo diagnostica. |
| `diag_params` | `false` | Al primo ciclo legge i parametri di configurazione come l'app ufficiale e li riporta nel log. Non modifica nulla. Solo diagnostica. |
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
| **Tensione / Corrente / Potenza generatore** | V / A / W | `sensor.tbb_riio_sun_ii_gen_v` … |
| Frequenza generatore 🔧 | Hz | `sensor.tbb_riio_sun_ii_gen_freq` |
| Frequenza rete 🔧 | Hz | `sensor.tbb_riio_sun_ii_ac_in_freq` |
| **Potenza uscita AC totale** ⚙ | W | `sensor.tbb_riio_sun_ii_ac_out_tot_w` |
| Frequenza uscita 🔧 | Hz | `sensor.tbb_riio_sun_ii_ac_freq` |
| Carico | % | `sensor.tbb_riio_sun_ii_load_pct` |
| Tensione / Corrente / Potenza rete | V / A / W | `sensor.tbb_riio_sun_ii_ac_in_v` … |
| Temperature dissipatore / trasformatore / inverter 🔧 | °C | `sensor.tbb_riio_sun_ii_t_heatsink` … |
| **SmartPort registro** *(scrivibile)* | — | `number.tbb_riio_sun_ii_smart_port` |
| **SmartPort corrente** *(scrivibile)* | A | `number.tbb_riio_sun_ii_smart_port_a` |
| **SmartPort potenza** *(scrivibile)* | W | `number.tbb_riio_sun_ii_smart_port_w` |
| SmartPort modalità | — | `sensor.tbb_riio_sun_ii_smart_port_mode` |
| **Carica completa batteria** *(interruttore)* | — | `switch.tbb_riio_sun_ii_bat_full_charge` |
| **Capacità riservata batteria** *(scrivibile)* | % | `number.tbb_riio_sun_ii_bat_reserved_capacity` |
| **Corrente max carica da generatore** *(scrivibile)* | A | `number.tbb_riio_sun_ii_gen_charge_current` |
| Backup / Anteprima ripristino / Ripristina parametri *(pulsanti)* | — | `button.tbb_riio_sun_ii_param_backup` … |

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
| `ac_out_tot_w` — Potenza uscita AC totale | `ac_out_w` + `ac_out2_w` | — |
| `bat_status` — Stato batteria | segno di `bat_i` | *In carica* / *In scarica* / *A riposo* |

Un canale calcolato compare **solo se tutti i suoi ingressi sono presenti** nel
ciclo. Se una risposta arriva corta e manca la corrente di batteria, `bat_w` non
viene aggiornato invece di crollare a zero.

> **Le potenze in alternata non sono calcolate.** Rete (`ac_in_w`), generatore
> (`gen_w`), uscita 1 (`ac_out_w`) e uscita 2 (`ac_out2_w`) sono misurate
> dall'inverter e lette così come le riporta, con il loro segno. Fino alla 1.3.3
> `ac_in_w` e `ac_out2_w` erano il prodotto V × A, cioè potenza apparente — e
> su due grandezze lette dai byte sbagliati.

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
scrive `0x005E` con un frame singolo — come fa l'app ufficiale — e poi lo
**rilegge** insieme alla modalità della SmartPort. Un valore fuori scala viene
rifiutato senza trasmettere un solo byte.

> ⚠️ **Se hai usato una versione fino alla 1.3.3, controlla due parametri
> nell'app TBBLink.** Quelle versioni precedevano ogni scrittura con due frame
> creduti uno «sblocco», che in realtà impostavano a **10** il *ritardo di
> commutazione batteria → rete* e il *ritardo rete → batteria* (registri
> `0x0073` e `0x0074`). Se i tuoi valori erano diversi, vanno ripristinati
> dall'app. Dalla 2.0.1 l'add-on non li tocca più. Dettagli in
> [`PROTOCOLLO.md`](https://github.com/CarloFalco/ha-tbb-inverter-addon/blob/main/PROTOCOLLO.md).

#### Modalità della SmartPort

Il registro `0x005E` corrisponde, nell'app ufficiale, al campo *corrente
massima del generatore*. La SmartPort ha una modalità (registro `0x001F`):

| Valore | Modalità |
|:---:|---|
| 0 | Smart Load — la porta alimenta un carico |
| 1 | Smart Gen — alla porta è collegato un generatore |
| 2 | City GEN |

Dopo ogni scrittura il log riporta la modalità letta dall'inverter. Se è
*Smart Load*, è plausibile che la corrente impostata non abbia alcun effetto:
si tratta del limite di un generatore che non c'è.

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

#### Leggere i parametri come fa l'app

Con `diag_params: true`, al primo ciclo riuscito l'add-on legge i blocchi di
parametri che l'app TBBLink legge per popolare la sua schermata impostazioni, e
li riporta nel log: prima tutti i valori grezzi, poi quelli di cui conosciamo
il nome.

```
[NOTICE] PARAM A 0x001f =     0  Modalita' SmartPort (0 Smart Load, 1 Smart Gen, 2 City GEN)  [Cbo_ACFlexMode]
[NOTICE] PARAM A 0x005e =    16 A  Corrente massima generatore  [Edt_MaxAlternatorCurrent]
[NOTICE] PARAM B 0x0073 =    10  Ritardo commutazione batteria -> rete  [Edt_BatToUtilityDelay]
```

La lettura non modifica nulla. Il formato della risposta non è ancora stato
verificato su un inverter reale: se il log dice «formato non riconosciuto»,
copia quella riga, è esattamente l'informazione che serve per completarlo.
Confronta i valori con la schermata dell'app e poi rimetti `diag_params: false`.

#### Quando una scrittura non ha effetto

Il log riporta l'intera catena, dal comando MQTT ai byte sulla linea, fino alla
rilettura. Con `log_level: info` una scrittura produce:

```
[NOTICE] Comando ricevuto: tbb/inverter/cmd/smart_port_a = 16
[INFO] Conversione: 16.0 A -> registro 16  (identita')
[NOTICE] SmartPort -> registro 0x005E = 16  (interpretato come 16 A, ~3680 W; modalita' registro: ampere)
[INFO] TX 1/1 (12 byte): 7E FF 11 06 06 0C 00 5E 00 10 80 94
[INFO] RX 1/1 (12 byte): 7E 11 FF 06 06 0C 00 5E 00 10 8A F4
[NOTICE] Rilettura: 0x005E = 16  (confermato), modalita' SmartPort: Smart Load
```

Cosa guardare, nell'ordine:

| Sintomo nel log | Significato |
|---|---|
| manca «Comando ricevuto» | il comando non arriva: controlla il broker MQTT e il prefisso dei topic |
| «Conversione» mostra un registro diverso da quello atteso | è la modalità del registro: vedi la sezione sopra |
| il `TX` c'è ma l'inverter non cambia | i byte partono: confrontali con l'esempio stampato nel banner all'avvio |
| «L'inverter non ha risposto al frame» | plausibile se i sensori funzionano (alcuni firmware non rispondono alle scritture); se anche le letture sono ferme, il problema è la linea RS485 |
| `RX` con il valore riecheggiato | l'inverter ha **ricevuto** la scrittura — l'eco arriva per qualunque valore, quindi da solo non basta |
| «Rilettura … (confermato)» | il valore è **memorizzato**. Se la potenza non cambia, guarda la modalità della SmartPort |
| «Rilettura … invece di …» | l'inverter ha ricevuto ma **non memorizzato** il valore |
| «Rilettura di 0x005E non riuscita» | la lettura dei parametri non è ancora decodificata sul tuo firmware: prova `diag_params` e mandaci il log |
| «Porta seriale non disponibile» | l'adattatore USB non è aperto: vedi la sezione risoluzione dei problemi |

### Esito dei comandi

| Topic | Valori |
|---|---|
| `<prefix>/cmd/smart_port/status` | `OK` / `ERRORE` |
| `<prefix>/cmd/smart_port_a/status` | `OK` / `ERRORE` |
| `<prefix>/cmd/smart_port_w/status` | `OK` / `ERRORE` |
| `<prefix>/cmd/bat_full_charge/status` | `OK` / `ERRORE` — comando `ON` / `OFF` |
| `<prefix>/cmd/bat_reserved_capacity/status` | `OK` / `ERRORE` — comando intero 15-80, sopra l'avviso di SOC basso |
| `<prefix>/cmd/gen_charge_current/status` | `OK` / `ERRORE` — comando intero 1-100 |
| `<prefix>/cmd/param_backup/status` | `OK` / `ERRORE` |
| `<prefix>/cmd/param_restore_preview/status` | `OK` / `ERRORE` — payload: nome del file, o `PRESS` |
| `<prefix>/cmd/param_restore/status` | `OK` / `ERRORE` — payload: nome del file, o `PRESS` |
| `<prefix>/cmd/raw/status` | `OK` / `ERRORE` |

`ERRORE` arriva anche quando l'inverter risponde con un'**eccezione** (tipo
`0x86`): il frame è arrivato ma è stato rifiutato.

I frame trasmessi da una scrittura (`TX`) e le relative risposte (`RX`)
compaiono già con `log_level: info`, perché sono rari e sono la
prima cosa da guardare. Con `log_level: debug` si aggiungono anche i frame
esadecimali di **ogni ciclo di lettura**.

---

## 💾 Backup e ripristino dei parametri

L'add-on sa leggere e scrivere la configurazione dell'inverter come l'app
TBBLink. Tre pulsanti, nella sezione *Configurazione* del dispositivo:

| Pulsante | Cosa fa | Scrive sull'inverter? |
|---|---|:---:|
| **Backup parametri inverter** | Salva tutti i parametri in `/share/tbb_inverter/backup_<data>_<ora>.txt` | no |
| **Anteprima ripristino parametri** | Confronta `/share/tbb_inverter/ripristina.txt` con l'inverter e scrive nel log cosa cambierebbe | **no** |
| **Ripristina parametri inverter** | Scrive i valori diversi e li rilegge uno per uno | sì |

La cartella `/share` è quella condivisa di Home Assistant: la raggiungi con
l'add-on *Samba share* (cartella `share`) o con *File editor*/*Studio Code
Server*.

### Il file

Una riga per parametro: banco (`A` o `B`), registro, valore. Tutto ciò che
segue `#` è un commento.

```
# --- Parametri ripristinabili (93) ------------------------------
A 0x001f     1   # Modalita' SmartPort (0 Smart Load, 1 Smart Gen, 2 City GEN)  [Cbo_ACFlexMode]
A 0x005e     7   # Corrente massima generatore A  [Edt_MaxAlternatorCurrent]
B 0x002b 12000   # Ingresso AC: disconnetti sopra tensione batteria (12.00 V per blocco da 12 V = 48.00 V)  [lineEdit_ACI_DisconnectBAT]
B 0x005c     5   # Corrente massima di carica da generatore / AC in 2  [Edt_MaxGeneratorChargeCurrent]
...
# --- Solo lettura o non mappati, ignorati dal ripristino (367) ---
#~ A 0x0000  2300
#~ A 0x0004 48000
...
```

> ⚠️ **Le tensioni sono per blocco da 12 V.** Su un sistema a 48 V il valore
> va moltiplicato per 4: `12000` = 12,00 V × 4 = **48,00 V**. Il commento lo
> riporta già convertito. Per impostare 46,0 V scrivi `11500`, non `46000`.

### Procedura di ripristino

1. Premi **Backup parametri inverter**: è il tuo punto di ritorno.
2. Copia il backup (o un backup precedente) come `ripristina.txt` nella stessa
   cartella e, se serve, modifica i valori.
3. Premi **Anteprima ripristino parametri** e leggi il log:

   ```
   [NOTICE] ANTEPRIMA da ripristina.txt: 1 da modificare, 90 gia' uguali, 2 ignorati
   [NOTICE]   B 0x005c: 5 -> 15   Corrente massima di carica da generatore / AC in 2 [Edt_MaxGeneratorChargeCurrent]
   ```

4. Se le modifiche elencate sono quelle che vuoi, premi **Ripristina parametri
   inverter**.

### Cosa il ripristino non fa, di proposito

- **Non scrive i registri commentati** (`#~`): misure, dati di targa, registri
  di fabbrica. Il backup li contiene per completezza, ma riscriverli potrebbe
  danneggiare la configurazione. Ripristina solo i ~90 parametri che la
  schermata impostazioni dell'app sa scrivere.
- **Non riscrive valori uguali**: tocca solo ciò che cambia.
- **Non scrive `65535`**, che significa «non usato», né su un registro che
  sull'inverter vale 65535.
- **Non parte se anche una sola riga è sbagliata**: meglio nessuna modifica
  che metà.
- **Non accetta percorsi**: solo un nome di file `.txt` dentro
  `/share/tbb_inverter`.

Via MQTT si può indicare un file diverso da `ripristina.txt` mettendone il nome
nel payload di `cmd/param_restore_preview` o `cmd/param_restore`.

> I parametri della pagina *Battery* dell'app (corrente massima di carica,
> tensioni di assorbimento e mantenimento…) stanno nel banco A ma non sono
> ancora mappati: compaiono nel backup come righe commentate e il ripristino
> non li tocca.

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
| `ac_out2_v` / `ac_out2_i` / `ac_out2_w` | V / A / W | Seconda uscita AC |
| `ac_out_tot_w` ⚙ | W | Potenza totale erogata: somma delle due uscite |
| `ac_freq` | Hz | Frequenza di uscita |
| `load_pct` | % | Carico rispetto alla potenza nominale |

### 🏠 Ingresso rete

| Topic | Unità | Descrizione |
|---|:---:|---|
| `ac_in_v` | V | Tensione di rete |
| `ac_in_i` | A | Corrente **con segno**, come la riporta l'inverter |
| `ac_in_w` | W | Potenza di rete **con segno**, misurata dall'inverter |
| `ac_in_freq` 🔧 | Hz | Frequenza di rete: 0 quando la rete è assente |

### ⛽ Ingresso generatore

Quando la SmartPort lavora come **Smart Gen**, l'energia entra da qui e non
dall'ingresso di rete: tensione e corrente della SmartPort restano a zero,
quelle del generatore si muovono.

| Topic | Unità | Descrizione |
|---|:---:|---|
| `gen_v` | V | Tensione del generatore |
| `gen_i` | A | Corrente **con segno** |
| `gen_w` | W | Potenza **con segno**, misurata dall'inverter |
| `gen_freq` 🔧 | Hz | Frequenza del generatore |

> ⚠️ **Se aggiorni da una versione fino alla 1.3.3**, la tensione che vedevi
> come «Tensione rete» era in realtà quella del **generatore**, e la «Frequenza
> uscita» era quella della **rete**. Dalla 2.0.1 ogni grandezza è al suo posto:
> lo storico di quelle due entità cambia significato da quel momento.

### 🔋 Controlli della batteria

| Entità | Cosa fa |
|---|---|
| **Carica completa batteria** (interruttore) | Attiva o disattiva la carica completa («Battery Full Charge» nell'app TBBLink) |
| **Capacità riservata batteria** (15-80 %) | SOC che l'inverter tiene di riserva («Battery Reserved Capacity») |
| **Corrente max carica da generatore** (1-100 A) | Quanta corrente di carica la batteria può prendere dal generatore |

> 💡 **Il generatore non sale fino al tetto della SmartPort?** Il tetto
> (`SmartPort corrente`, registro `0x005E`) è un *massimo*: l'inverter preleva
> dal generatore solo quello che serve per il carico più la carica della
> batteria. Se la carica dal generatore è limitata, per esempio a 5 A, il
> generatore resta ben sotto il tetto. Alza la *Corrente max carica da
> generatore* e la potenza del generatore dovrebbe salire, fino al tetto.

> **Quanto può scendere la capacità riservata?** Le stesse regole dell'app:
> **almeno 15 %**, e comunque **sopra l'avviso di SOC basso** (pagina batteria
> dell'app); al massimo 80 %. L'ordine delle soglie è *protezione* (l'inverter
> spegne l'uscita) < *avviso* < *capacità riservata*. Abbassare la protezione
> non abbassa il minimo della riserva: il limite di 15 % resta.

Capacità riservata e corrente di carica vengono **rilette** dopo ogni modifica e ogni 10 minuti:
l'entità mostra il valore memorizzato dall'inverter, anche se lo cambi dall'app
o dal pannello.

La carica completa invece **non si può rileggere** — non lo fa neanche l'app
ufficiale. L'interruttore mostra l'ultimo comando inviato da Home Assistant:
è sconosciuto finché non lo usi la prima volta, e non si accorge di un cambio
fatto dall'app.

```yaml
action: switch.turn_on
target:
  entity_id: switch.tbb_riio_sun_ii_bat_full_charge
```

```yaml
action: number.set_value
target:
  entity_id: number.tbb_riio_sun_ii_bat_reserved_capacity
data:
  value: 30
```

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
