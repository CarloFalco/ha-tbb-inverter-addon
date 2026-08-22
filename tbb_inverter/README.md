<img src="https://raw.githubusercontent.com/CarloFalco/ha-tbb-inverter-addon/main/tbb_inverter/logo.png" alt="TBB Inverter Reader" width="640">

# TBB Inverter Reader

**Porta il tuo inverter TBB RiiO Sun II dentro Home Assistant.**
Nessun cloud, nessun account, nessun gateway proprietario: solo un cavo RS485 e MQTT.

![Version](https://img.shields.io/badge/versione-1.2.0-1f8fff?style=for-the-badge)
![Arch](https://img.shields.io/badge/arch-aarch64%20%7C%20amd64-5ce1e6?style=for-the-badge)
![Setup](https://img.shields.io/badge/YAML%20richiesto-nessuno-ffb020?style=for-the-badge)

---

## Cosa fa

L'add-on interroga l'inverter **TBB RiiO Sun II 8.0S (48V - 8000VA)** sulla sua porta
RS485 (connettore RJ45) e crea **da solo** tutte le entità in Home Assistant, pronte
per dashboard, automazioni, statistiche a lungo termine e Energy Dashboard.

| | |
|---|---|
| ☀️ **Produzione fotovoltaica** | Tensione, corrente e potenza MPPT, temperatura del regolatore |
| 🔋 **Batteria** | Tensione, corrente e **potenza** con segno, SOC, stato carica/scarica, temperatura, BMS |
| 🔌 **Uscite AC** | Due uscite indipendenti: V, A, W, **totale** — più frequenza e carico |
| 🏠 **Ingresso rete** | Tensione, corrente e **potenza** con segno: sai subito se prelevi o immetti |
| 🌡️ **Temperature** | Dissipatore, trasformatore, stadio inverter, batteria |
| 🎚️ **SmartPort** | Uno slider in Home Assistant per impostarla da 0 a 100 % |

---

## In tre passi

**1. Collega l'adattatore USB-RS485** al Raspberry Pi e all'RJ45 dell'inverter

| RJ45 pin | Filo | Adattatore RS485 |
|:--:|---|---|
| **3** | verde / bianco | **A+** |
| **6** | verde | **B-** |
| **8** | GND | GND *(opzionale)* |
| ~~7~~ | +12V | ⚠️ **non collegare** |

**2. Indica la porta seriale** nella scheda *Configurazione*. Se usi l'add-on
*Mosquitto broker*, **non serve altro**: host e credenziali MQTT vengono rilevati
automaticamente.

**3. Avvia.** Entro pochi secondi trovi il dispositivo pronto in
*Impostazioni → Dispositivi e servizi → MQTT → **TBB RiiO Sun II***, con tutti i
sensori già configurati. Nessuno YAML da scrivere.

```
-------------------------------------------------------
  Ciclo 1  -  14:32:07
-------------------------------------------------------
  PV:        248.6 V   7.31 A   1817 W  (MPPT 41°C)
  AC Out:    230.2 V   4.85 A   1116 W
  AC In:     231.0 V   -0.12 A  (rete->inv)
  Batteria:   53.412 V  +14.2 A (In carica)  SOC  87%
  Potenze:   Batteria    +758 W   Rete    -28 W   Uscite  1346 W
  Temp:      Heatsink  38°C  Transformer  44°C
  Carico:     14%
-------------------------------------------------------
```

---

## Fatto bene

- 🔎 **CRC verificato** su ogni risposta: nessun valore inventato dal rumore di linea
- 🚦 **Entità che diventano *non disponibili*** se l'add-on si ferma o perde la
  seriale — un buco nel grafico, non una linea piatta finta
- 🔁 **Si riprende da solo**: adattatore USB scollegato o broker riavviato, l'add-on
  riconnette senza intervento
- ⚙ **Canali calcolati**: potenza di batteria, di rete e uscita totale, ricavate
  dalle letture ad ogni ciclo
- 🕳️ **Nessuno zero fittizio**: se un dato non arriva, il sensore non viene aggiornato
- 🔒 **Scritture grezze disattivate** per impostazione predefinita

---

## Prima di installare

- ✅ Un **broker MQTT** (l'add-on ufficiale *Mosquitto broker* è perfetto e non
  richiede configurazione)
- ✅ Un **adattatore USB-RS485** (i chip FTDI e CH340 sono i più affidabili)
- ✅ Home Assistant OS o Supervised su architettura `aarch64` o `amd64`

Cablaggio dettagliato, elenco delle entità, Energy Dashboard e risoluzione dei
problemi sono nella scheda **📘 Documentazione**.

---

<sub>Progetto non affiliato a TBB Power. Basato su reverse engineering del protocollo
RS485 dell'inverter — usalo a tuo rischio.</sub>
