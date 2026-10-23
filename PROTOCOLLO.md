# Protocollo RS485 del TBB RiiO Sun II

Riferimento tecnico per chi sviluppa l'add-on. Quanto segue è stato ricavato
per **analisi statica** dell'app ufficiale TBBLink (eseguibile `TBBLinking.exe`
e plugin `KinergierPro`, che gestisce anche il RiiO Sun II), senza eseguirla:
modelli di frame scritti nel binario, codice che compone le scritture, nomi dei
widget dell'interfaccia. Lo scopo è l'interoperabilità con un inverter di
proprietà; nessun codice dell'app è riportato qui.

Ogni affermazione è marcata:

- ✅ **verificato** sul campo, con l'inverter (RiiO Sun II 8.0S, ottobre 2026);
- 🔎 **ricavato** dall'app, coerente ma non ancora provato;
- ❓ **dedotto**, da confermare.

---

## Formato dei frame

Tutti i frame hanno la stessa struttura e lo stesso CRC16/MODBUS (poli `0xA001`,
init `0xFFFF`, little-endian in coda). ✅

```
 0   1   2   3     4    5     6-7       8-9      10-11
7E  FF  11  tipo  cmd  len   registro  valore    CRC        richiesta da 12 byte
7E  FF  11  03    cmd  08    CRC                            richiesta da 8 byte
```

| Byte | Significato |
|---|---|
| 0 | delimitatore `7E` |
| 1-2 | indirizzi: `FF 11` in richiesta, **`11 FF` in risposta** ✅ (`11` è l'indirizzo del dispositivo: nell'app è un segnaposto `00` riempito a runtime 🔎) |
| 3 | `03` lettura, `06` scrittura ✅ |
| 4 | comando |
| 5 | lunghezza totale del frame (`08` o `0C` nelle richieste) ✅ |
| 6-7 | registro, big-endian |
| 8-9 | valore da scrivere, oppure **numero di registri da leggere** 🔎 |

Una scrittura riceve come risposta lo **stesso frame con gli indirizzi
scambiati** e il CRC ricalcolato. ✅ L'inverter risponde così a *qualunque*
valore, anche fuori scala: l'ACK conferma la ricezione, non l'applicazione.

## Comandi di lettura delle misure

Frame da 8 byte, già usati dall'add-on (`C0`, `C1`) o presenti nell'app:

| Comando | Uso nell'add-on | Note |
|:---:|---|---|
| `C0` | ✅ rete, generatore, uscite, batteria, SOC, temperature | mappa sotto |
| `C1` | ✅ FV, MPPT, tensione BMS | |
| `C3` | — | 🔎 grandezze per fase dei modelli *Split Phase* |
| `A0`, `A1`, `00`, `C6`, `C7`, `AB` | — | 🔎 equivalenti di `C0`/`C1` per altri modelli (Tyrann, CK-II, Matrix) |

L'app copia il payload di ogni risposta in una struttura globale, una per
comando, e il pannello di monitoraggio legge i campi da lì: per ogni grandezza
si ricavano byte, scala e segno. 🔎

### Frame `C0` sul RiiO Sun II

Valori big-endian a 16 bit; l'offset è nel frame completo (payload + 6).
Mappa ricavata dal pannello di monitoraggio dell'app per il RiiO Sun II e
**verificata sul campo**: con la rete assente e la SmartPort in Smart Gen,
tensione × corrente del generatore coincide con la potenza riportata
(240,1 V × 3,81 A ≈ 915 W) e il bilancio energetico chiude entro il 4 %.
Il frame `C0` reale è lungo **170 byte**; un frame vero è nei test
(`tests/test_backup.py`).

| Byte | Grandezza | Scala | Segno | Chiave nell'add-on |
|:---:|---|:---:|:---:|---|
| 8 | potenza rete | W | sì | `ac_in_w` ✅ |
| 10 | **potenza generatore** | W | sì | `gen_w` ✅ positiva quando eroga |
| 14 | potenza uscita AC | W | sì | `ac_out_w` ✅ |
| 16 | potenza uscita AC 2 | W | sì | `ac_out2_w` ✅ |
| 20 | tensione rete | ÷10 | | `ac_in_v` ✅ |
| 22 | **tensione generatore** | ÷10 | | `gen_v` ✅ |
| 24 | tensione dell'inverter | ÷10 | | — |
| 26 | tensione uscita AC | ÷10 | | `ac_out_v` ✅ |
| 28 | tensione uscita AC 2 | ÷10 | | `ac_out2_v` ✅ |
| 30 | corrente rete | ÷100 | sì | `ac_in_i` ✅ |
| 32 | **corrente generatore** | ÷100 | sì | `gen_i` ✅ |
| 34 | corrente dell'inverter | ÷100 | sì | — |
| 36 | corrente uscita AC | ÷100 | sì | `ac_out_i` ✅ |
| 38 | corrente uscita AC 2 | ÷100 | sì | `ac_out2_i` ✅ |
| 40 | frequenza rete | ÷100 | | `ac_in_freq` ✅ |
| 42 | frequenza generatore | ÷100 | | `gen_freq` ✅ |
| 44 | frequenza uscita | ÷100 | | `ac_freq` ✅ |
| 50 | tensione batteria | ÷1000 | | `bat_v` ✅ |
| 52 | corrente batteria | ÷10 | sì | `bat_i` ✅ |
| 56-61, 66 | temperature | °C | | `t_*` ✅ |
| 155 | SOC | % | | `soc` ✅ |

> Fino alla 1.3.3 l'add-on leggeva il byte 22 come tensione di **rete**, il 16
> come tensione dell'uscita 2 e il 40 come frequenza di **uscita**. È il motivo
> per cui un vecchio log mostrava 235 V «di rete» con 0 A e 0 Hz, e 787 W di
> carico che non tornavano: la rete era assente, l'energia arrivava dal
> generatore.

## Banchi dei parametri

I parametri di configurazione stanno in due banchi, ciascuno con un comando di
lettura e uno di scrittura, in stile Modbus (scrittura = lettura × 2): 🔎

| Banco | Lettura | Scrittura | Contiene, fra l'altro |
|:---:|:---:|:---:|---|
| **A** | `0x03` | `0x06` | modalità SmartPort `0x001F`, corrente generatore `0x005E` |
| **B** | `0x33` | `0x66` | soglie e ritardi di rete, generatore, Smart Load, immissione |

Lettura di `n` registri da `r`: `7E FF 11 03 <cmd> 0C <r> <n> <CRC>`. Sono gli
stessi modelli che l'app usa per popolare la schermata impostazioni:

| Banco | Primo registro | Quanti |
|:---:|:---:|:---:|
| A | `0x0000` | 100 |
| A | `0x0065` | 78 |
| A | `0x00CA` | 51 |
| B | `0x0000` | 100 |
| B | `0x0064` | 100 |
| B | `0x00D0` | 31 |

✅ **Formato della risposta**: `7E 11 FF 03 <cmd> <len> <dati> <CRC>`. L'app
estrae i dati con `mid(6, lunghezza − 8)` — subito dopo l'intestazione, senza
eco — e li copia in un'immagine del banco a partire dal registro della
*richiesta*. Verificato sul campo su entrambi i banchi, con tutti e sei i
blocchi.

✅ **Dati di targa** (banco A): `0x0000` = 2300 (230,0 V nominali), `0x0001` =
5000 (50,00 Hz), `0x0004` = 48000 (sistema a 48 V), `0x0006` = 8000 (VA).

✅ **Le tensioni dei parametri sono per blocco da 12 V**: soglie come `12000`
o `11500` valgono ×4 su un sistema a 48 V (48,0 V, 46,0 V). Il fattore è la
tensione nominale di `0x0004` divisa per 12000. ❓ È una deduzione dai
valori, non trovata nel codice dell'app; i conti tornano su tutte le soglie
lette.

🔎 **Eccezioni**: una scrittura rifiutata riceve una risposta di tipo `0x86`
(`0x80 | 0x06`), come in Modbus. L'app la gestisce in un ramo a parte; dalla
2.0.1 l'add-on la tratta come errore.

**Ogni scrittura è un frame singolo.** L'app non invia alcuna sequenza di
sblocco prima di modificare un parametro. 🔎

---

## La SmartPort

### Il falso "sblocco" su `0x0073` / `0x0074`

Fino alla 1.3.3 l'add-on precedeva ogni scrittura della SmartPort con due frame
ritenuti uno sblocco:

```
7E FF 11 06 66 0C 00 73 00 0A ...    banco B, registro 0x0073 = 10
7E FF 11 06 66 0C 00 74 00 0A ...    banco B, registro 0x0074 = 10
```

Nell'app questi due registri sono **normali parametri**, presi da due campi
dell'interfaccia: 🔎

| Registro | Campo | Significato |
|:---:|---|---|
| `0x0073` | `Edt_BatToUtilityDelay` | ritardo di commutazione batteria → rete |
| `0x0074` | `Edt_UtilityToBatDelay` | ritardo di commutazione rete → batteria |

La sequenza catturata in origine era probabilmente l'invio di tre campi della
stessa schermata, due dei quali valevano 10. Dalla 2.0.1 l'add-on scrive solo
`0x005E`. **Chi ha usato le versioni precedenti dovrebbe controllare nell'app i
due ritardi**: a ogni comando SmartPort venivano riportati a 10.

### Carica completa della batteria

Non sta in nessuno dei due banchi: è un comando a sé, `0x00` sul registro
`0x03F3`. 🔎

```
7E FF 11 06 00 0C 03 F3 00 01 D1 5B     attiva
7E FF 11 06 00 0C 03 F3 00 00 10 9B     disattiva
```

È il valore della casella «Battery Full Charge» dell'app (`isChecked()`). L'app
**non lo rilegge**: mostra lo stato ricavandolo dall'eco della propria
scrittura, che riecheggia sempre il valore inviato. Non esiste una lettura nota
di questo stato.

### Capacità riservata della batteria

Banco B, registro `0x0072` (`Edt_BatReservedCapacity`): la percentuale di SOC
che l'inverter tiene di riserva. L'app scrive il numero digitato così com'è,
senza scala. I limiti del campo nell'app non sono stati estratti; l'add-on
accetta 0-100. 🔎

### Modalità e corrente

| Registro | Banco | Campo | Valori |
|:---:|:---:|---|---|
| `0x001F` | A | `Cbo_ACFlexMode` («Smart Port Modeset») | 🔎 `0` Smart Load, `1` Smart Gen, `2` City GEN |
| `0x005E` | A | `Edt_MaxAlternatorCurrent` | intero, ✅ 5-32 A nell'app |
| `0x005C` | B | `Edt_MaxGeneratorChargeCurrent` | corrente massima di **carica** da generatore, in A di carica 🔎 |

Il nome del campo dice «corrente massima dell'alternatore», cioè del
generatore. Sul RiiO Sun II l'app mostra il campo in tutte e tre le modalità,
quindi dal solo codice dell'interfaccia non si ricava in quale modalità abbia
effetto. ❓ Le prove sul campo — potenza piatta qualunque valore si imposti, con
un carico da 1,3 kW sulla SmartPort — sono compatibili con un parametro che in
modalità *Smart Load* non agisce affatto. La rilettura di `0x001F` dopo ogni
scrittura (dalla 2.0.1) lo chiarirà.

---

## Parametri scrivibili

Per ogni frame di scrittura che l'app sa comporre, il widget da cui prende il
valore. «Indice» = posizione nel menu a tendina; «decimale ×1000» = l'app
converte il numero digitato in millesimi (le tensioni sono in mV, come nella
misura `bat_v` del frame `C0`). Dove il significato è vuoto, il nome del campo
è l'unica informazione disponibile. 🔎

| Banco | Scrittura | Lettura | Registro | Campo nell'app | Significato | Tipo |
|:---:|:---:|:---:|:---:|---|---|---|
| A | `0x06` | `0x03` | `0x0010` | `comboBox_ACIL` | Logica ingresso AC (indice) | — |
| A | `0x06` | `0x03` | `0x0016` | `comboBox_ACOC` | Controllo uscita AC2 (indice) | — |
| A | `0x06` | `0x03` | `0x001f` | `Cbo_ACFlexMode` | Modalita' SmartPort (0 Smart Load, 1 Smart Gen, 2 City GEN) | indice |
| A | `0x06` | `0x03` | `0x003c` | `comboBox_BackflowEnable` | Anti-immissione abilitata (indice) | indice |
| A | `0x06` | `0x03` | `0x005d` | `Cbo_AcInByPassConnect` | Bypass ingresso AC (indice) | indice |
| A | `0x06` | `0x03` | `0x005e` | `Edt_MaxAlternatorCurrent` | Corrente massima generatore | intero |
| A | `0x06` | `0x03` | `0x00c1` | `comboBox_Relay1Func` | Funzione rele' 1 | intero |
| A | `0x06` | `0x03` | `0x00c2` | `comboBox_Relay2Func` | Funzione rele' 2 | intero |
| B | `0x66` | `0x33` | `0x0007` | `Cbo_IRD_DeviceEn` | Dispositivo IRD abilitato (indice) | indice |
| B | `0x66` | `0x33` | `0x0012` | `Cbo_GenLoadCtrl` | Generatore: controllo carico (indice) | indice |
| B | `0x66` | `0x33` | `0x0013` | `Edt_GenChargeStartDelay` | Generatore: ritardo avvio carica | intero |
| B | `0x66` | `0x33` | `0x0014` | `Edt_GenChargeStopDelay` | Generatore: ritardo arresto carica | intero |
| B | `0x66` | `0x33` | `0x0015` | `lineEdit_Gen_StartBatVolt` | Generatore: avvio sotto tensione batteria | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x0016` | `lineEdit_Gen_StopBatVolt` | Generatore: arresto sopra tensione batteria | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x0018` | `comboBox_Relay_UpHour`, `comboBox_Relay_UpMinute` |  | — |
| B | `0x66` | `0x33` | `0x0019` | `comboBox_Relay_DownHour`, `comboBox_Relay_DownMinute` |  | — |
| B | `0x66` | `0x33` | `0x001a` | `lineEdit_Gen_StartLoad` | Generatore: avvio sopra carico | intero |
| B | `0x66` | `0x33` | `0x001b` | `lineEdit_Gen_StopLoad` | Generatore: arresto sotto carico | intero |
| B | `0x66` | `0x33` | `0x001c` | `lineEdit_Gen_StartSOC` | Generatore: avvio sotto SOC | intero |
| B | `0x66` | `0x33` | `0x001d` | `lineEdit_Gen_StopSOC` | Generatore: arresto sopra SOC | intero |
| B | `0x66` | `0x33` | `0x001e` | `Edt_GenLoadStartDelay` | Generatore: ritardo avvio per carico | intero |
| B | `0x66` | `0x33` | `0x001f` | `Edt_GenLoadStopDelay` | Generatore: ritardo arresto per carico | intero |
| B | `0x66` | `0x33` | `0x0020` | `comboBox_ACIL` |  | — |
| B | `0x66` | `0x33` | `0x0021` | `checkBox_ACITime1`, `checkBox_ACITime2`, `checkBox_ACITime3` |  | — |
| B | `0x66` | `0x33` | `0x0022` | `comboBox_ACItime1_UpHour` |  | — |
| B | `0x66` | `0x33` | `0x0023` | `comboBox_ACItime1_DownHour`, `comboBox_ACItime1_DownMinute` |  | — |
| B | `0x66` | `0x33` | `0x0024` | `comboBox_ACItime2_UpHour`, `comboBox_ACItime2_UpMinute` |  | — |
| B | `0x66` | `0x33` | `0x0025` | `comboBox_ACItime2_DownHour`, `comboBox_ACItime2_DownMinute` |  | — |
| B | `0x66` | `0x33` | `0x0026` | `comboBox_ACItime3_UpHour`, `comboBox_ACItime3_UpMinute` |  | — |
| B | `0x66` | `0x33` | `0x0027` | `comboBox_ACItime3_DownHour`, `comboBox_ACItime3_DownMinute` |  | — |
| B | `0x66` | `0x33` | `0x0028` | `radioButton_AutoCharge` | Carica automatica | bool |
| B | `0x66` | `0x33` | `0x002a` | `lineEdit_ACI_ConnectBAT` | Ingresso AC: connetti sotto tensione batteria | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x002b` | `lineEdit_ACI_DisconnectBAT` | Ingresso AC: disconnetti sopra tensione batteria | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x002c` | `lineEdit_ACI_ConnectDelay`, `lineEdit_ACI_ConnectDelaySOC` | Ingresso AC: ritardo connessione | intero |
| B | `0x66` | `0x33` | `0x002d` | `lineEdit_ACI_DisconnectDelay`, `lineEdit_ACI_DisconnectDelaySOC` | Ingresso AC: ritardo disconnessione | intero |
| B | `0x66` | `0x33` | `0x002e` | `lineEdit_ACI_ConnectSOC` | Ingresso AC: connetti sotto SOC | intero |
| B | `0x66` | `0x33` | `0x002f` | `lineEdit_ACI_DisconnectSOC` | Ingresso AC: disconnetti sopra SOC | intero |
| B | `0x66` | `0x33` | `0x0030` | `comboBox_RelayCtrl` |  | intero |
| B | `0x66` | `0x33` | `0x0031` | `lineEdit_Gen_MinRuntime` | Generatore: tempo minimo di marcia | intero |
| B | `0x66` | `0x33` | `0x0032` | `lineEdit_Gen_StartIntervaltime` | Generatore: intervallo fra avvii | intero |
| B | `0x66` | `0x33` | `0x0033` | `comboBox_Relay1SigType` |  | indice |
| B | `0x66` | `0x33` | `0x0034` | `comboBox_Relay2SigType` |  | indice |
| B | `0x66` | `0x33` | `0x0035` | `lineEdit_Relay1TurnOnDelay` |  | intero |
| B | `0x66` | `0x33` | `0x0036` | `lineEdit_Relay2TurnOnDelay` |  | intero |
| B | `0x66` | `0x33` | `0x0037` | `lineEdit_Relay1TurnOffDelay` |  | intero |
| B | `0x66` | `0x33` | `0x0038` | `lineEdit_Relay2TurnOffDelay` |  | intero |
| B | `0x66` | `0x33` | `0x0039` | `lineEdit_Relay1PulseTime` |  | intero |
| B | `0x66` | `0x33` | `0x003a` | `lineEdit_Relay2PulseTime` |  | intero |
| B | `0x66` | `0x33` | `0x003b` | `comboBox_Relay1Func` |  | intero |
| B | `0x66` | `0x33` | `0x003c` | `comboBox_Relay2Func` |  | intero |
| B | `0x66` | `0x33` | `0x003e` | `Cbo_StopGenWhenGridIsVailid` | Ferma il generatore con rete presente (indice) | indice |
| B | `0x66` | `0x33` | `0x003f` | `comboBox_Relay3Func` |  | intero |
| B | `0x66` | `0x33` | `0x0040` | `comboBox_ACOC` | Controllo uscita AC2 (indice) | — |
| B | `0x66` | `0x33` | `0x0041` | `lineEdit_ACO_DisconnectBAT` | Uscita AC2: stacca sotto tensione batteria | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x0042` | `lineEdit_ACO_ConnectBAT` | Uscita AC2: attacca sopra tensione batteria | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x0043` | `lineEdit_ACO_DisconnectDelay`, `lineEdit_ACO_DisconnectDelaySOC` |  | intero |
| B | `0x66` | `0x33` | `0x0044` | `lineEdit_ACO_ConnectDelay`, `lineEdit_ACO_ConnectDelaySOC` |  | intero |
| B | `0x66` | `0x33` | `0x0045` | `checkBox_ACOTime1`, `checkBox_ACOTime2`, `checkBox_ACOTime3` |  | — |
| B | `0x66` | `0x33` | `0x0046` | `comboBox_ACOtime1_UpHour`, `comboBox_ACOtime1_UpMinute` |  | — |
| B | `0x66` | `0x33` | `0x0047` | `comboBox_ACOtime1_DownHour`, `comboBox_ACOtime1_DownMinute` |  | — |
| B | `0x66` | `0x33` | `0x0048` | `comboBox_ACOtime2_UpHour`, `comboBox_ACOtime2_UpMinute` |  | — |
| B | `0x66` | `0x33` | `0x0049` | `comboBox_ACOtime2_DownHour`, `comboBox_ACOtime2_DownMinute` |  | — |
| B | `0x66` | `0x33` | `0x004a` | `comboBox_ACOtime3_UpHour`, `comboBox_ACOtime3_UpMinute` |  | — |
| B | `0x66` | `0x33` | `0x004b` | `comboBox_ACOtime3_DownHour`, `comboBox_ACOtime3_DownMinute` |  | — |
| B | `0x66` | `0x33` | `0x004c` | `lineEdit_ACO_DisconnectSOC` | Uscita AC2: stacca sotto SOC | intero |
| B | `0x66` | `0x33` | `0x004d` | `lineEdit_ACO_ConnectSOC` | Uscita AC2: attacca sopra SOC | intero |
| B | `0x66` | `0x33` | `0x0051` | `lineEdit_ACI_ChargeDerate` | Ingresso AC: riduzione carica | intero |
| B | `0x66` | `0x33` | `0x0054` | `lineEdit_ACIChgMaxCurAtBatLv` | Ingresso AC: corrente max di carica a batteria bassa | intero |
| B | `0x66` | `0x33` | `0x0055` | `lineEdit_ACIStopCHGVolt` | Ingresso AC: ferma la carica sopra tensione | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x0056` | `lineEdit_ACIStopChargeSOC` | Ingresso AC: ferma la carica sopra SOC | intero |
| B | `0x66` | `0x33` | `0x005a` | `Cbo_AcInByPassConnect` | Bypass ingresso AC (indice) | indice |
| B | `0x66` | `0x33` | `0x005c` | `comboBox_ACOC`, `Edt_MaxGeneratorChargeCurrent`, `Edt_Acin2ChargeMaxCurrent` | Corrente massima di carica da generatore / AC in 2 | intero |
| B | `0x66` | `0x33` | `0x0060` | `comboBox_acinLvWarn` | Avviso sottotensione ingresso AC | indice |
| B | `0x66` | `0x33` | `0x0061` | `comboBox_mpptofflinewarn` | Avviso MPPT offline | indice |
| B | `0x66` | `0x33` | `0x0062` | `comboBox_SmartGenLVWarn` | Avviso sottotensione Smart Gen | indice |
| B | `0x66` | `0x33` | `0x0063` | `lineEdit_ACO_PV_ConnectPower` | Smart Load: attacca sopra potenza FV | intero |
| B | `0x66` | `0x33` | `0x0064` | `lineEdit_ACO_PV_DisconnectPower` | Smart Load: stacca sotto potenza FV | intero |
| B | `0x66` | `0x33` | `0x0065` | `lineEdit_ACO_PV_ConnectSOC` | Smart Load: attacca sopra SOC | intero |
| B | `0x66` | `0x33` | `0x0066` | `lineEdit_ACO_PV_DisconnectSOC` | Smart Load: stacca sotto SOC | intero |
| B | `0x66` | `0x33` | `0x0067` | `lineEdit_ACO_PV_ConnectBatVolt` | Smart Load: attacca sopra tensione batteria | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x0068` | `lineEdit_ACO_PV_DisconnectBatVolt` | Smart Load: stacca sotto tensione batteria | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x0069` | `lineEdit_ACO_PV_ConnectDelay` | Smart Load: ritardo aggancio | intero |
| B | `0x66` | `0x33` | `0x006a` | `lineEdit_ACO_PV_DisconnectDelay` | Smart Load: ritardo sgancio | intero |
| B | `0x66` | `0x33` | `0x006b` | `lineEdit_ACO_Load_ConnectPrecent` | Smart Load: attacca sopra carico | intero |
| B | `0x66` | `0x33` | `0x006c` | `lineEdit_ACO_Load_DisconnectPrecent` | Smart Load: stacca sotto carico | intero |
| B | `0x66` | `0x33` | `0x006d` | `lineEdit_ACO_Load_ConnectDelay` | Smart Load: ritardo aggancio per carico | intero |
| B | `0x66` | `0x33` | `0x006e` | `lineEdit_ACO_Load_DisconnectDelay` | Smart Load: ritardo sgancio per carico | intero |
| B | `0x66` | `0x33` | `0x0070` | `Edt_BatVoltBackToUtilityMode` | Torna alla rete sotto tensione batteria | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x0071` | `Edt_BatVoltBackToBatMode` | Torna alla batteria sopra tensione | decimale, x1000 (mV) |
| B | `0x66` | `0x33` | `0x0072` | `Edt_BatReservedCapacity` | Capacita' riservata della batteria | intero |
| B | `0x66` | `0x33` | `0x0073` | `Edt_BatToUtilityDelay` | Ritardo commutazione batteria -> rete | intero |
| B | `0x66` | `0x33` | `0x0074` | `Edt_UtilityToBatDelay` | Ritardo commutazione rete -> batteria | intero |
| B | `0x66` | `0x33` | `0x00dd` | `Cbo_ExternalAcInMeter` | Contatore esterno su ingresso AC (indice) | indice |
| B | `0x66` | `0x33` | `0x00ed` | `comboBox_FeedBackEnable` | Immissione in rete abilitata (indice) | indice |
| B | `0x66` | `0x33` | `0x00ee` | `Edt_FeedBackPower` | Potenza di immissione | intero |

L'app scrive anche alcuni valori **fissi**, da funzioni di collaudo e
calibrazione (prove di invecchiamento, taratura delle misure), e comandi con
codici `0x0A`, `0x0B`, `0x0E` sui registri `0x0000`-`0x0009`. Non sono
parametri utente, non sono riportati qui e l'add-on non deve inviarli.

---

## Come è stata ricavata la mappa

Per chi volesse ripetere o estendere l'analisi:

1. Il plugin è una DLL Qt5 a 32 bit (MinGW). Il CRC è *inlined* in ~60 punti:
   cercare la costante `0xA001` porta direttamente alle funzioni che
   compongono i frame.
2. I frame di lettura sono modelli statici nella sezione `.data`
   (`7E FF 00 03 …`).
3. Le scritture sono composte byte per byte sullo stack con valori letterali
   (`mov byte ptr [ebp-…], 0x7e`, poi `0xff`, `0x00`, `0x06`, comando, `0x0c`,
   registro): registro e comando si leggono direttamente nelle istruzioni.
4. Il valore viene da un widget letto poco prima (`ui + offset`). Il setupUi
   generato da Qt assegna a ogni offset il nome del widget subito dopo averlo
   creato, e da lì si risale al nome. Attenzione agli offset condivisi fra
   form diversi: va usato solo il form della schermata impostazioni.
5. Le etichette per modello (es. «Smart Port Mode:» sul RiiO) sono assegnate in
   una funzione che confronta il nome del modello con `RiiO`, `Tyrann`,
   `Matrix II`…
