# Changelog

## 1.3.3

### 🐛 La SmartPort torna a rispondere

Dalla 1.3.0 la SmartPort non recepiva piu' i valori impostati. La 1.3.1 aveva
individuato la causa nel punto giusto -- la conversione -- ma con la premessa
sbagliata, e ne aveva corretto solo meta'.

**Causa.** Il registro `0x005E` accetta 0-100, ma su questo firmware **quel
numero sono direttamente gli ampere**: scrivere 20 imposta 20 A, sotto 5 non
succede nulla, sopra 32 l'inverter satura. La 1.3.1 assumeva invece che fosse
una percentuale e in `amps_to_register` moltiplicava per 100/32 = 3,125: lo
slider a 16 A scriveva 50, cioe' fondo scala. Restava esatto solo lo slider in
percentuale, l'unico senza conversione.

**Verificato, non dedotto.** I byte che `cmd_smart_port` mette sulla linea sono
identici a quelli della primissima versione funzionante per **ogni** valore da
0 a 100 -- sequenza di sblocco, CRC e ordine compresi. Il trasporto non e' mai
regredito: c'e' un test che lo confronta con il sorgente preso da git. La
regressione era solo nel numero che arrivava fin li'.

**Quanto era sbagliato il valore.** Con il fattore 3,125, da 11 A in su il
registro finiva oltre il fondoscala utile -- 22 posizioni dello slider su 28:

| Slider in ampere | Registro scritto | Dentro l'intervallo utile? |
|---|---|---|
| 5 - 10 A | 16 - 31 | si', ma corrente sbagliata (16-31 A) |
| **11 - 32 A** | **34 - 100** | **no, oltre il fondoscala** |

Qualunque valore d'uso reale cadeva nella seconda riga.

> **Nota sulla SmartPort.** Le prove sul campo mostrano che il registro fissa
> un **tetto** di corrente, non un valore da erogare: si vede solo quando sta
> sotto a quanto il carico sta gia' chiedendo. Con un carico da 5,3 A,
> impostare 6, 8 o 16 A non cambia nulla, e non perche' la scrittura fallisca.
> L'inverter, dal canto suo, risponde con un ACK regolare (CRC valido, valore
> riecheggiato) a qualunque valore, anche fuori scala: l'ACK conferma la
> ricezione del frame, non l'applicazione del parametro.

**Correzione.** Ampere e watt tornano a scrivere il valore che l'inverter si
aspetta:

| Slider | Prima (1.3.1) | Ora |
|---|---|---|
| 16 A | registro 50 (= fondo scala) | registro 16 |
| 32 A | registro 100 | registro 32 |
| 3680 W | registro 50 | registro 16 |

Lo slider grezzo continua a scrivere il numero cosi' com'e' e non e' piu'
etichettato come percentuale: quando il registro contiene ampere, quel "%" era
la meta' cosmetica dello stesso equivoco. Si chiama ora **SmartPort registro**
(stessa entita', stesso `entity_id`).

### ✨ Novita'

- Nuova opzione `smartport_register_unit` (`ampere` predefinito, oppure
  `percent`): copre entrambe le convenzioni possibili senza toccare il codice.
  La documentazione descrive una verifica di un minuto per stabilire quale usa
  il tuo firmware. `smartport_a_at_zero` resta, e vale solo in `percent`.
- **Il log segue la scrittura da capo a fondo.** Gia' con `log_level: info`
  compaiono il comando ricevuto, la conversione applicata, il valore di
  registro e tutti e tre i frame trasmessi con la relativa risposta:

  ```
  [NOTICE] Comando ricevuto: tbb/inverter/cmd/smart_port_a = 16
  [INFO] Conversione: 16.0 A -> registro 16  (identita')
  [NOTICE] SmartPort -> registro 0x005E = 16  (interpretato come 16 A, ~3680 W; ...)
  [INFO] TX 1/3 (12 byte): 7E FF 11 06 66 0C 00 73 00 0A 98 F6
  [INFO] RX 1/3: nessuna risposta entro 0.2s
  ```

  Se l'inverter non risponde a nessuno dei tre frame viene segnalato
  esplicitamente, distinguendo il caso innocuo (firmware che non risponde alle
  scritture) da quello reale (linea RS485 muta). Con la porta chiusa il log
  dice quale porta e quanti frame sono stati scartati, invece di un generico
  "non disponibile".
- **Avviso prima di trasmettere** quando il valore di registro cade fuori
  dall'intervallo utile dichiarato. L'inverter lo accettera' comunque -- non
  rifiuta nulla -- ma l'effetto non e' verificato.
- Il banner di avvio stampa i **frame di riferimento** per gli estremi dello
  slider: si confrontano a occhio con una cattura dell'app nativa senza dover
  far partire una scrittura.

### 🍂 Meno carico su Home Assistant

Su un Raspberry Pi 3 il costo di questo add-on non e' la CPU -- il ciclo di
lettura dura poche centinaia di millisecondi -- ma il numero di aggiornamenti
che riversa in Home Assistant. Ogni ciclo tocca 27 topic, e il recorder scrive
nel database ogni valore che cambia. Due valori predefiniti sono stati
ricalibrati di conseguenza:

- **`poll_interval` passa da 5 a 30 secondi.** Il carico scala linearmente:
  si passa da ~467.000 aggiornamenti al giorno a ~78.000. Per l'andamento
  giornaliero non cambia nulla; chi vuole vedere le variazioni rapide di
  potenza puo' sempre riabbassarlo, l'opzione e' sempre esistita ed accetta
  1-3600 secondi.
- **Le grandezze diagnostiche nascono disabilitate.** Temperature (MPPT,
  dissipatore, trasformatore, inverter), tensione riportata dal BMS e
  frequenza di uscita -- sei entita' -- servono a capire un problema, non a
  governare l'impianto, e restano quasi immobili per ore. Finche' sono spente
  non producono stati e non finiscono nel database. Si accendono dalla sezione
  *Diagnostica* del dispositivo, in due clic e senza riavviare l'add-on.

La frequenza di uscita e' stata spostata fra le diagnostiche: e' bloccata sul
valore di rete per giorni interi. La temperatura della batteria resta invece
fra le grandezze normali, perche' e' l'unica temperatura con valore operativo.

> ⚠️ **Aggiornando da una versione precedente**, Home Assistant conserva le
> opzioni gia' salvate: il nuovo `poll_interval` **non** viene applicato da
> solo. Controllalo nella scheda Configurazione e portalo a 30 a mano.

### 🔎 Diagnostica: trovare dove l'inverter rilegge un parametro

Nuova opzione `diag_frames`. L'add-on scrive nei registri ma non sa rileggerli:
senza riscontro, "non ha funzionato" e "ha funzionato ma non si vede" sono
indistinguibili, ed e' esattamente l'ambiguita' in cui si erano arenate le due
diagnosi precedenti.

Attivandola, ogni frame di lettura viene confrontato con il precedente e i byte
cambiati vengono segnalati -- ma solo quelli fermi da almeno 3 cicli. Le misure
vive oscillano di continuo e si filtrano da sole; un parametro di
configurazione resta immobile finche' qualcuno non lo cambia:

```
[NOTICE] DIAG C0[77 / 0x4D]: 05 -> 14  (5 -> 20, fermo da 12 cicli)  <-- OFFSET NON DECODIFICATO
```

Si attiva, si cambia il valore **dall'app nativa** e si legge quale offset si
muove: quello e' il punto in cui l'inverter rilegge il parametro, e i due
valori ne rivelano anche l'unita'. Da spegnere quando non serve.

### 🛡 Correzioni minori

- `ser.flush()` dopo ogni scrittura: i byte sono sulla linea prima che inizi
  l'attesa della risposta, invece di restare eventualmente nel buffer del
  driver.
- `cmd_smart_port` rifiuta un valore non intero invece di lasciar sollevare
  `TypeError` dentro `build_frame`. L'eccezione sarebbe finita nel thread di
  rete di paho e la scrittura sarebbe fallita in silenzio.
- Con il registro in ampere, un `smartport_max_a` oltre 100 verrebbe troncato
  dal registro: ora viene segnalato e riportato a 32.

## 1.3.1

### 🐛 Correzione della regressione introdotta dalla 1.3.0

Nella 1.3.0 la SmartPort ha smesso di rispondere: qualunque valore si
impostasse, l'inverter restava a 5 A. Le entità in Home Assistant si
aggiornavano correttamente fra loro e il log riportava la scrittura, ma il
numero che arrivava all'inverter era sbagliato.

**Causa.** La 1.3.0 partiva dal presupposto che il registro `0x005E`
contenesse la corrente in ampere e scriveva quindi valori 5-32. Il registro
accetta invece **0-100**, come faceva la 1.2.0. Scrivendoci 5-32 si finiva in
fondo alla scala — fra 1,6 A e 10,2 A — e l'inverter saturava al proprio
minimo di 5 A per quasi tutto l'intervallo.

**Correzione.** Il valore canonico torna a essere quello del registro (0-100):

- Il topic `cmd/smart_port` e l'entità in percentuale scrivono di nuovo il
  numero **così com'è**, senza conversioni. I frame trasmessi sono
  byte-per-byte identici a quelli della 1.2.0 funzionante, su tutta la scala
  — c'è un test che lo verifica confrontando le due implementazioni.
- Le entità in ampere e in watt restano, ma come **viste derivate**:
  convertono nel valore di registro prima di scrivere (16 A → 50).

### ✨ Novità

- Nuova opzione `smartport_a_at_zero` (predefinito `0`): la corrente
  corrispondente al registro a 0. Insieme a `smartport_max_a` definisce la
  mappatura lineare registro → ampere, e copre entrambe le convenzioni
  possibili senza modifiche al codice.
- La documentazione descrive una **verifica di un minuto** per stabilire quale
  convenzione usi il tuo firmware: porta lo slider in percentuale a 50 e leggi
  la corrente sul display dell'inverter.

## 1.3.0

> ⚠️ **Questa versione ha una regressione sulla SmartPort, corretta nella
> 1.3.1.** La premessa su cui si basava — "il registro contiene ampere" — si
> è rivelata sbagliata alla prova sul campo. Le note qui sotto restano come
> testimonianza storica; per il comportamento corretto vedi la 1.3.1.


### ✨ Novità

- **Tre entità scrivibili per la SmartPort**, tre viste dello stesso registro.
  Scrivendone una, le altre due si aggiornano da sole:

  | Entità | Unità | Intervallo | Passo |
  |---|:---:|---|---|
  | `number.tbb_riio_sun_ii_smart_port_a` | A | 5 → 32 | 1 A |
  | `number.tbb_riio_sun_ii_smart_port_w` | W | 1150 → 7360 | 230 W (= 1 A) |
  | `number.tbb_riio_sun_ii_smart_port` | % | 0 → 100 | 1 % |

- Tre topic MQTT corrispondenti: `cmd/smart_port`, `cmd/smart_port_a`,
  `cmd/smart_port_w`, ognuno con il proprio `/status`.
- Nuove opzioni `smartport_min_a` (5), `smartport_max_a` (32) e
  `smartport_voltage` (230): se la tua SmartPort ha un intervallo diverso, i
  tre slider si riadattano senza modifiche al codice. Valori incoerenti
  (intervallo invertito, tensione nulla) vengono segnalati e riportati ai
  predefiniti invece di generare entità rotte.
- I valori fuori scala vengono rifiutati **prima** di toccare l'inverter, su
  tutte e tre le unità.

## 1.2.0

### ✨ Novità

- **Canali calcolati.** Nuove entità ricavate dalle grandezze lette, create
  automaticamente come tutte le altre:

  | Entità | Calcolo | Segno |
  |---|---|---|
  | **Potenza batteria** (`bat_w`) | tensione × corrente di batteria | positiva = in carica |
  | **Potenza rete** (`ac_in_w`) | tensione × corrente di rete | negativa = prelievo dalla rete |
  | **Potenza uscita AC totale** (`ac_out_tot_w`) | somma delle due uscite | — |

  Un canale calcolato viene pubblicato solo se tutti i suoi ingressi sono
  presenti: se un frame arriva corto, `bat_w` non compare invece di finire a
  zero.
- Il riepilogo nel log mostra una riga **Potenze** con batteria, rete e uscite.

### 🛡 Stabilità e sicurezza

- **La lettura seriale poteva non terminare mai.** Se la linea RS485 non
  restava mai in silenzio (bus flottante senza terminazione, adattatore
  guasto, altro dispositivo che trasmette in continuazione), il ciclo di
  lettura ignorava il proprio limite di tempo: il buffer cresceva **senza
  limite**, il lock della porta restava preso e anche i comandi MQTT si
  bloccavano. Ora il limite di tempo vale sempre e la risposta è tetto a
  1024 byte, con svuotamento dell'ingresso per risincronizzare.
- **Un payload MQTT enorme su `cmd/raw` veniva convertito prima di essere
  validato.** Ora i frame oltre 64 byte sono rifiutati senza allocare nulla:
  un payload da 6 MB viene scartato in millisecondi.
- **`inf` come valore SmartPort sollevava un'eccezione non gestita**
  (`OverflowError` non era intercettato). Ora risponde `ERRORE` come ogni
  altro valore non valido.
- **Un errore imprevisto nel ciclo di lettura terminava l'add-on in
  silenzio.** Ora viene registrato con lo stack, le entità passano a non
  disponibili e il polling riprende.
- Il CRC usa una tabella precalcolata: **~3× più veloce** a parità di
  risultato (verificato su 5000 casi casuali contro la definizione
  bit-a-bit), meno CPU sul Raspberry Pi.
- Nuova suite `tests/test_stability.py`: linea rumorosa, payload ostili,
  assenza di deadlock, tenuta del ciclo principale agli errori imprevisti.
  Un soak test di 10.000 cicli non mostra perdite di memoria né di thread.

### 🔧 Sviluppo

- I valori derivati (`ac_out2_w` e `bat_status`, già presenti) sono stati
  spostati nello stesso meccanismo dichiarativo `DERIVED`: aggiungere un canale
  significa ora aggiungere una riga e la sua entità.
- Un test verifica che ogni canale calcolato abbia la propria entità in Home
  Assistant, così non se ne può aggiungere uno dimenticando di esporlo.

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
  Alpine 3.19 e l'architettura `armv7` non più supportata. Ora l'immagine
  base è dichiarata solo nel `Dockerfile` (`ARG BUILD_FROM`): senza
  `build.yaml` il Supervisor non passa più `BUILD_FROM` e lascia decidere al
  `Dockerfile`, che diventa l'unica fonte di verità per CI e installazioni
  locali.
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
  multi-architettura su GHCR, basati sulle action mantenute di
  `home-assistant/builder`: quella monolitica è deprecata e ricavava
  l'immagine base da `build.yaml`.
- Rimosse da `config.yaml` le chiavi `boot` e `stage`, che ripetevano il
  valore predefinito e facevano fallire il linter ufficiale degli add-on.

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
