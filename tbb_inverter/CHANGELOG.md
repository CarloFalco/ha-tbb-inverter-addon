# Changelog

## 1.1.0

### ✨ Novità

- **Creazione automatica delle entità (MQTT Discovery).** Sensori e slider
  SmartPort compaiono da soli in Home Assistant come un unico dispositivo
  *TBB RiiO Sun II*, con `device_class`, `state_class` e unità di misura già
  corretti: niente più sensori da scrivere a mano in `configuration.yaml`.
  Disattivabile con l'opzione `mqtt_discovery`.
- **SmartPort come slider.** Il comando è esposto anche come entità `number`
  scrivibile dall'interfaccia, non solo via topic MQTT.
- **Stato di disponibilità (LWT).** Se l'add-on si ferma o perde la porta
  seriale, le entità diventano *non disponibili* invece di restare congelate
  sull'ultimo valore ritenuto.
- **Broker MQTT rilevato automaticamente.** Lasciando `mqtt_host` vuoto, host,
  porta e credenziali vengono presi dal broker configurato in Home Assistant.
- **Nuovo sensore `bat_status`**: *In carica* / *In scarica* / *A riposo*.
- **Livello di log configurabile** (`log_level`), da `trace` a `fatal`.
- **Traduzioni italiano/inglese** per le opzioni nella scheda Configurazione.
- **Icona e logo** dell'add-on.

### 🐛 Correzioni

- **Un ciclo di polling durava ~4 secondi in più del necessario.** La lettura
  attendeva il timeout della porta seriale invece di fermarsi quando l'inverter
  smetteva di trasmettere. Con `poll_interval: 5` l'intervallo reale era di
  circa 9 secondi.
- **I frame ricevuti non venivano verificati.** Ora il CRC16/MODBUS della
  risposta viene controllato, individuando anche il confine del frame; con
  `strict_crc` le risposte non valide vengono scartate del tutto.
- **Le sottoscrizioni MQTT andavano perse dopo un riavvio del broker**, perché
  la `subscribe` veniva eseguita una volta sola all'avvio: i comandi smettevano
  di funzionare in silenzio. Ora avviene ad ogni connessione.
- **Se il broker non era raggiungibile all'avvio, non veniva più ritentato**
  e ogni pubblicazione andava persa. Ora la connessione è asincrona con
  riconnessione automatica a backoff progressivo.
- **I valori mancanti venivano pubblicati come `0`.** Un frame corto faceva
  comparire `soc: 0` o `bat_v: 0` nello storico di Home Assistant. Ora vengono
  pubblicate solo le grandezze effettivamente decodificate.
- **Un payload MQTT non UTF-8 sollevava un'eccezione nel thread di rete** di
  paho, potenzialmente interrompendo la ricezione dei comandi.
- **La sottoscrizione `cmd/#` riceveva anche i topic di stato pubblicati
  dall'add-on stesso.** Ora sono sottoscritti solo i due topic di comando.
- **Lo scollegamento dell'adattatore USB terminava l'add-on.** Ora la porta
  viene riaperta automaticamente e le entità passano a non disponibili nel
  frattempo.
- **`build.yaml` non era stato realmente rimosso** nella 1.0.1: quando presente
  aveva la precedenza sul `Dockerfile` e riportava in gioco Python 3.12,
  Alpine 3.19 e l'architettura `armv7` non più supportata.
- `io.hass.type` nel Dockerfile era `app` invece di `addon`.
- Rimosso l'import inutilizzato di `struct`.

### 🔒 Sicurezza

- Il topic `cmd/raw`, che scrive direttamente nei registri dell'inverter, è
  ora **disabilitato per impostazione predefinita**: va abilitato esplicitamente
  con l'opzione `allow_raw_command`.

### 🔧 Sviluppo

- Suite di test senza hardware (`tests/test_reader.py`): CRC, decodifica,
  gestione dei frame corti, discovery, comandi e disponibilità.
- Workflow GitHub Actions per lint (add-on, Python, shell), test e build
  multi-architettura su GHCR.

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
