<img src="https://raw.githubusercontent.com/CarloFalco/ha-tbb-inverter-addon/main/tbb_inverter/logo.png" alt="TBB Inverter Reader" width="640">

# TBB Inverter Reader

**Porta il tuo inverter TBB RiiO Sun II dentro Home Assistant.**
Nessun cloud, nessun account, nessun gateway proprietario: solo un cavo RS485 e MQTT.

![Version](https://img.shields.io/badge/versione-1.0.1-1f8fff?style=for-the-badge)
![Arch](https://img.shields.io/badge/arch-aarch64%20%7C%20amd64-5ce1e6?style=for-the-badge)
![Protocol](https://img.shields.io/badge/RS485-%E2%86%92%20MQTT-ffb020?style=for-the-badge)

---

## Cosa fa

L'add-on interroga l'inverter **TBB RiiO Sun II 8.0S (48V - 8000VA)** sulla sua porta
RS485 (connettore RJ45) e traduce i dati in topic MQTT che Home Assistant può usare
subito: dashboard, automazioni, statistiche a lungo termine e Energy Dashboard.

| | |
|---|---|
| ☀️ **Produzione fotovoltaica** | Tensione, corrente e potenza MPPT, temperatura del regolatore |
| 🔋 **Batteria** | Tensione, corrente con segno (carica/scarica), SOC, temperatura, lettura BMS |
| 🔌 **Uscite AC** | Due uscite indipendenti: V, A, W — più frequenza di rete |
| 🏠 **Ingresso rete** | Tensione e corrente con segno, per capire se stai prelevando o immettendo |
| 🌡️ **Temperature** | Dissipatore, trasformatore, stadio inverter, batteria |
| 🎛️ **Comandi in scrittura** | Imposta la **SmartPort** (0-100 %) o invia frame RS485 grezzi |

---

## In tre passi

**1. Collega l'adattatore USB-RS485** al Raspberry Pi e all'RJ45 dell'inverter

| RJ45 pin | Filo | Adattatore RS485 |
|:--:|---|---|
| **3** | verde / bianco | **A+** |
| **6** | verde | **B-** |
| **8** | GND | GND *(opzionale)* |
| ~~7~~ | +12V | ⚠️ **non collegare** |

**2. Configura l'add-on** — nella scheda *Configurazione* indica la porta seriale e,
se serve, l'host del broker MQTT. Con il broker Mosquitto ufficiale i valori di
default vanno già bene.

**3. Avvia** e apri la scheda *Log*: entro pochi secondi vedrai il primo ciclo di
lettura con tutti i valori.

```
-------------------------------------------------------
  Ciclo 1  -  14:32:07
-------------------------------------------------------
  PV:         248.6 V   7.31 A   1817 W  (MPPT 41°C)
  AC Out:     230.2 V   4.85 A   1116 W
  AC In:      231.0 V  -0.12 A  (rete->inv)
  Batteria:    53.412 V  +14.2 A (carica )  SOC  87%
  Temp:      Heatsink  38°C  Transformer  44°C
  Carico:     14%
```

---

## Dati pubblicati

Ogni grandezza finisce su un topic dedicato sotto il prefisso configurato
(default `tbb/inverter`), più un topic `stato` con **tutto in un unico JSON**:

```
tbb/inverter/pv_w        1817
tbb/inverter/soc         87
tbb/inverter/bat_i       14.2
tbb/inverter/stato       {"pv_w":1817,"soc":87,"bat_i":14.2, ...}
```

Trovi l'elenco completo dei topic, gli esempi di sensore per `configuration.yaml`
e la guida alla risoluzione dei problemi nella scheda **📘 Documentazione**.

---

## Prima di installare

- ✅ Un **broker MQTT** raggiungibile (l'add-on ufficiale *Mosquitto broker* è perfetto)
- ✅ Un **adattatore USB-RS485** (i chip FTDI e CH340 sono i più affidabili)
- ✅ Home Assistant OS o Supervised su architettura `aarch64` o `amd64`

> ⚠️ **Attenzione ai comandi di scrittura.** I topic `cmd/…` scrivono davvero nei
> registri dell'inverter. Usa `cmd/raw` solo se sai esattamente cosa stai inviando:
> un frame sbagliato può alterare parametri di funzionamento dell'impianto.

---

<sub>Progetto non affiliato a TBB Power. Basato su reverse engineering del protocollo
RS485 dell'inverter — usalo a tuo rischio.</sub>
