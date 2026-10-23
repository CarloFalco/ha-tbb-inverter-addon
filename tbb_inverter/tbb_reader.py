"""
TBB RiiO Sun II - RS485 Reader (Home Assistant Add-on)
====================================================================
Inverter: RiiO Sun II 8.0S, 48V-8000VA

Connessione:
  RJ45 pin 3 (verde/bianco) -> A+ adattatore RS485
  RJ45 pin 6 (verde)        -> B- adattatore RS485
  RJ45 pin 7 (+12V)         -> NON COLLEGARE
  RJ45 pin 8 (GND)          -> GND adattatore (opzionale)

Comandi MQTT in ingresso (topic <prefix>/cmd/...):
  <prefix>/cmd/smart_port     <- valore grezzo del registro 0x005E (0-100)
  <prefix>/cmd/smart_port_a   <- corrente in ampere (5-32 per impostazione predefinita)
  <prefix>/cmd/smart_port_w   <- potenza in watt alla tensione nominale
                                 Tutti e tre scrivono lo stesso registro 0x005E.
  <prefix>/cmd/raw          <- frame hex es. "7E FF 11 06 06 0C 00 5E 00 28 81 46"
                               (solo se allow_raw_command e' abilitato)

Configurazione: letta da variabili d'ambiente (impostate da run.sh a partire
dalle opzioni dell'add-on in /data/options.json).
"""

import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import serial

# ----------------------------------------------------------------
# CONFIGURAZIONE (da variabili d'ambiente)
# ----------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, default)).strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    return str(os.environ.get(name, default)).strip().lower() in ("1", "true", "yes", "on")


# Seriale
PORT          = os.environ.get("SERIAL_PORT", "/dev/ttyUSB0")
BAUD          = _env_int("BAUD", 9600)
TIMEOUT       = 2.0
POLL_INTERVAL = _env_int("POLL_INTERVAL", 30)

# MQTT
MQTT_HOST     = os.environ.get("MQTT_HOST", "core-mosquitto")
MQTT_PORT     = _env_int("MQTT_PORT", 1883)
MQTT_USER     = os.environ.get("MQTT_USER", "")
MQTT_PASS     = os.environ.get("MQTT_PASS", "")
MQTT_PREFIX   = os.environ.get("MQTT_PREFIX", "tbb/inverter").strip("/")
MQTT_KEEPALIVE = 60

# Funzionalita'
DISCOVERY         = _env_bool("MQTT_DISCOVERY", True)
DISCOVERY_PREFIX  = os.environ.get("DISCOVERY_PREFIX", "homeassistant").strip("/")
ALLOW_RAW_COMMAND = _env_bool("ALLOW_RAW_COMMAND", False)

# SmartPort. Il registro 0x005E accetta un valore 0-100; quello che quel numero
# *significa* dipende dal firmware, e le due convenzioni possibili portano a
# frame completamente diversi. La scelta e' esplicita, non indovinata:
#
#   "ampere"  (predefinito) il registro contiene direttamente gli ampere.
#             Scrivere 20 -> 20 A. E' cio' che e' stato osservato sul campo:
#             0-4 nessun effetto (sotto il minimo dell'inverter), 5-32 -> 5-32 A,
#             oltre 32 l'inverter satura al proprio massimo.
#
#   "percent" il registro e' una percentuale: 0 -> SMARTPORT_A_AT_ZERO ampere,
#             100 -> SMARTPORT_MAX_A ampere, lineare fra i due.
#
# In entrambi i casi il valore canonico resta quello del registro: e' l'unico
# numero che viene davvero trasmesso, ampere e watt sono viste derivate.
SMARTPORT_REGISTER_UNIT = os.environ.get("SMARTPORT_REGISTER_UNIT", "ampere").strip().lower()
SMARTPORT_A_AT_ZERO = _env_int("SMARTPORT_A_AT_ZERO", 0)   # solo in modalita' "percent"
SMARTPORT_MIN_A     = _env_int("SMARTPORT_MIN_A", 5)    # estremi utili dello slider
SMARTPORT_MAX_A     = _env_int("SMARTPORT_MAX_A", 32)
SMARTPORT_VOLTAGE   = _env_int("SMARTPORT_VOLTAGE", 230)
STRICT_CRC        = _env_bool("STRICT_CRC", False)

# Diagnostica: sorveglia i frame di lettura e segnala quali byte cambiano.
# Serve a individuare dove l'inverter *rilegge* un parametro, l'unico modo per
# sapere se una scrittura ha davvero avuto effetto invece di dedurlo.
DIAG_FRAMES       = _env_bool("DIAG_FRAMES", False)
# Diagnostica: all'avvio legge i blocchi di parametri come fa l'app ufficiale e
# li riporta nel log, per confrontarli con quanto mostra la sua schermata.
DIAG_PARAMS       = _env_bool("DIAG_PARAMS", False)
DIAG_STABLE_CYCLES = 3    # cicli di immobilita' prima che un byte faccia notizia
LOG_LEVEL         = os.environ.get("LOG_LEVEL", "info").strip().lower()
ADDON_VERSION     = os.environ.get("ADDON_VERSION", "dev")

# Backup e ripristino dei parametri: la cartella condivisa di Home Assistant
# (mappata in config.yaml), raggiungibile da Samba e dall'editor di file.
BACKUP_DIR        = Path(os.environ.get("BACKUP_DIR", "/share/tbb_inverter"))
RESTORE_FILE      = "ripristina.txt"

# Topic derivati
T_AVAILABILITY = f"{MQTT_PREFIX}/availability"
T_STATE_JSON   = f"{MQTT_PREFIX}/stato"
T_CMD_RAW      = f"{MQTT_PREFIX}/cmd/raw"

# Tre modi di scrivere lo stesso registro: percentuale, ampere, watt.
T_CMD_SMART    = f"{MQTT_PREFIX}/cmd/smart_port"
T_CMD_SMART_A  = f"{MQTT_PREFIX}/cmd/smart_port_a"
T_CMD_SMART_W  = f"{MQTT_PREFIX}/cmd/smart_port_w"
T_SMART_STATE  = f"{MQTT_PREFIX}/smart_port"
T_SMART_STATE_A = f"{MQTT_PREFIX}/smart_port_a"
T_SMART_STATE_W = f"{MQTT_PREFIX}/smart_port_w"
T_SMART_MODE    = f"{MQTT_PREFIX}/smart_port_mode"

# Batteria: carica completa (on/off) e capacita' riservata (SOC minimo).
T_CMD_FULL_CHARGE   = f"{MQTT_PREFIX}/cmd/bat_full_charge"
T_FULL_CHARGE_STATE = f"{MQTT_PREFIX}/bat_full_charge"
T_CMD_RESERVED      = f"{MQTT_PREFIX}/cmd/bat_reserved_capacity"
T_RESERVED_STATE    = f"{MQTT_PREFIX}/bat_reserved_capacity"
T_CMD_GEN_CHARGE    = f"{MQTT_PREFIX}/cmd/gen_charge_current"
T_GEN_CHARGE_STATE  = f"{MQTT_PREFIX}/gen_charge_current"

# Backup, anteprima e ripristino dei parametri di configurazione.
T_CMD_BACKUP          = f"{MQTT_PREFIX}/cmd/param_backup"
T_CMD_RESTORE_PREVIEW = f"{MQTT_PREFIX}/cmd/param_restore_preview"
T_CMD_RESTORE         = f"{MQTT_PREFIX}/cmd/param_restore"

DEVICE_ID = "tbb_riio_sun_ii"

CMD_C0 = bytes([0x7E, 0xFF, 0x11, 0x03, 0xC0, 0x08, 0xBA, 0xEB])
CMD_C1 = bytes([0x7E, 0xFF, 0x11, 0x03, 0xC1, 0x08, 0xBB, 0x7B])

# Banchi dei parametri, ricavati dall'app ufficiale TBBLink (plugin KinergierPro,
# che gestisce anche il RiiO Sun II). Ogni banco ha un comando di lettura e uno
# di scrittura, in stile Modbus. Le scritture sono frame singoli: l'app non
# invia alcuna sequenza di sblocco prima di un parametro.
BANK_A_READ, BANK_A_WRITE = 0x03, 0x06
BANK_B_READ, BANK_B_WRITE = 0x33, 0x66

REG_SMARTPORT_MODE    = 0x001F    # banco A, indice del menu "Smart Port Modeset"
REG_SMARTPORT_CURRENT = 0x005E    # banco A, campo "Max Alternator Current"
REG_BAT_RESERVED      = 0x0072    # banco B, "Battery Reserved Capacity" (%)

# "Battery Full Charge": un comando a se', fuori dai due banchi. L'app scrive
# 7E FF 11 06 00 0C 03 F3 00 <0|1> e ricava lo stato dall'eco della propria
# scrittura: non esiste una lettura nota di questo valore.
CMD_FULL_CHARGE, REG_FULL_CHARGE = 0x00, 0x03F3

PARAM_REFRESH_S = 600     # ogni quanto rileggere i parametri esposti in HA

# Corrente massima di carica dal generatore (banco B). Sul campo, con 5 la carica
# dal generatore si fermava a ~5-6 A lato batteria: il valore e' in ampere di
# carica. Il limite superiore e' prudenziale, l'app non lo dichiara.
REG_GEN_CHARGE = 0x005C
GEN_CHARGE_MIN, GEN_CHARGE_MAX = 1, 100

REG_SYSTEM_VOLTAGE = 0x0004   # banco A: tensione nominale di sistema in mV (48000)

# Soglie SOC della pagina batteria dell'app (banco A). Sono legate fra loro e alla
# capacita' riservata da regole che l'app applica prima di inviare:
#   SOC Low Protect   3 .. min(40, avviso - 1, riservata - 1)
#   SOC Low Warning   max(5, protezione + 1) .. min(riservata - 1, charge enough - 1)
#   riservata         max(15, avviso + 1) .. 80
#   SOC Charge Enough max(30, avviso + 5) .. 99
REG_SOC_LOW_WARNING   = 0x0091
REG_SOC_LOW_PROTECT   = 0x0092
REG_SOC_CHARGE_ENOUGH = 0x0093
RESERVED_MIN, RESERVED_MAX = 15, 80

# Registri che l'app ufficiale sa scrivere dalla propria schermata impostazioni,
# per banco di lettura. Sono gli unici che il ripristino tocca: gli altri sono
# misure, dati di targa o parametri di fabbrica.
WRITABLE = {
    BANK_A_READ: frozenset({0x0010, 0x0016, 0x001F, 0x003C, 0x005D, 0x005E, 0x00C1, 0x00C2}),
    BANK_B_READ: frozenset(
        {0x0007, 0x0012, 0x0013, 0x0014, 0x0015, 0x0016}
        | set(range(0x0018, 0x0029))           # generatore, rele', fasce orarie rete
        | set(range(0x002A, 0x003D))           # soglie rete, generatore, rele'
        | {0x003E, 0x003F}
        | set(range(0x0040, 0x004E))           # uscita AC2
        | {0x0051, 0x0054, 0x0055, 0x0056, 0x005A, 0x005C, 0x0060, 0x0061, 0x0062}
        | set(range(0x0063, 0x006F))           # Smart Load
        | set(range(0x0070, 0x0075))           # soglie e ritardi batteria <-> rete
        | {0x00DD, 0x00ED, 0x00EE}
    ),
}
SMARTPORT_MODES = {0: "Smart Load", 1: "Smart Gen", 2: "City GEN"}

# Blocchi che l'app legge per popolare la schermata impostazioni:
# (comando di lettura, primo registro, numero di registri).
PARAM_BLOCKS = [
    (BANK_A_READ, 0x0000, 100),
    (BANK_A_READ, 0x0065, 78),
    (BANK_A_READ, 0x00CA, 51),
    (BANK_B_READ, 0x0000, 100),
    (BANK_B_READ, 0x0064, 100),
    (BANK_B_READ, 0x00D0, 31),
]

SERIAL_RETRY_DELAY = 10   # secondi tra due tentativi di riapertura della porta
MAX_FAILED_CYCLES  = 3    # cicli a vuoto dopo i quali le entita' diventano non disponibili

# Tetti di sicurezza. Una risposta reale sta in ~200 byte e un frame di
# scrittura in 12: questi limiti servono solo a impedire che una linea RS485
# rumorosa (bus flottante, adattatore guasto) o un payload MQTT malevolo
# facciano crescere la memoria senza limite.
MAX_RESPONSE_BYTES = 1024
MAX_RAW_FRAME      = 64


# ----------------------------------------------------------------
# LOGGING
# ----------------------------------------------------------------

# Livelli bashio -> livelli Python
_LEVELS = {
    "trace":   logging.DEBUG,
    "debug":   logging.DEBUG,
    "info":    logging.INFO,
    "notice":  25,
    "warning": logging.WARNING,
    "error":   logging.ERROR,
    "fatal":   logging.CRITICAL,
}
logging.addLevelName(25, "NOTICE")

log = logging.getLogger("tbb")
# Un payload MQTT arbitrario puo' contenere qualunque byte: senza questo il log
# fallirebbe su console non-UTF8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
log.addHandler(_handler)
log.setLevel(_LEVELS.get(LOG_LEVEL, logging.INFO))


# ----------------------------------------------------------------
# STATO CONDIVISO
# ----------------------------------------------------------------

ser_global = None
ser_lock   = threading.Lock()
mqtt_client = None
_available = None        # None = mai pubblicato, cosi' il primo stato viene sempre inviato
_crc_verified = False    # diventa True al primo frame con CRC valido


# ================================================================
# CRC e costruzione frame
# ================================================================

def _build_crc_table() -> list[int]:
    """Tabella CRC16/MODBUS: un byte per passo invece di otto bit."""
    table = []
    for value in range(256):
        crc = value
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        table.append(crc)
    return table


_CRC_TABLE = _build_crc_table()


def crc16_modbus(data: bytes) -> int:
    """CRC16/MODBUS: poly=0xA001, init=0xFFFF, little-endian."""
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ byte) & 0xFF]
    return crc


def crc_frame_length(raw: bytes) -> int | None:
    """
    Cerca la lunghezza del frame contenuto in `raw` verificando il CRC.

    Scorre il buffer calcolando il CRC in modo incrementale e, ad ogni
    posizione, controlla se i due byte successivi coincidono con il CRC
    corrente (little-endian): non serve conoscere in anticipo la lunghezza
    della risposta.

    Piu' posizioni possono superare il controllo (~1 su 65536 per posizione, e
    dopo un frame valido il CRC corrente si azzera). La scelta e' quindi:

    1. se il byte 5 -- che nei frame noti contiene la lunghezza totale --
       corrisponde a una posizione valida, si usa quella;
    2. altrimenti si prende la corrispondenza piu' lunga, perche' includere
       qualche byte di troppo e' innocuo (la decodifica usa offset assoluti)
       mentre troncare farebbe sparire i campi in fondo al frame.

    Ritorna None se nessuna lunghezza produce un CRC valido.
    """
    matches = []
    crc = 0xFFFF
    for i, byte in enumerate(raw):
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ byte) & 0xFF]
        n = i + 1
        if (n >= 6 and n + 2 <= len(raw)
                and raw[n] == (crc & 0xFF)
                and raw[n + 1] == ((crc >> 8) & 0xFF)):
            matches.append(n + 2)

    if not matches:
        return None
    declared = raw[5] if len(raw) > 5 else None
    if declared in matches:
        return declared
    return max(matches)


def build_frame(cmd: int, register: int, value: int) -> bytes:
    """
    Costruisce un frame di scrittura con CRC.
    cmd      = 0x06 (scrittura registro) o 0x66 (sblocco)
    register = indirizzo registro (uint16)
    value    = valore da scrivere (uint16)
    """
    frame = bytes([
        0x7E, 0xFF, 0x11,
        0x06,
        cmd,
        0x0C,
        (register >> 8) & 0xFF, register & 0xFF,
        (value   >> 8) & 0xFF, value   & 0xFF,
    ])
    crc = crc16_modbus(frame)
    return frame + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def build_read_frame(cmd: int, register: int, count: int) -> bytes:
    """
    Costruisce un frame di lettura di `count` registri a partire da `register`.
    cmd = 0x03 (banco A) o 0x33 (banco B). Stesso formato dei modelli usati
    dall'app ufficiale: 7E FF 11 03 <cmd> 0C <reg> <count> <crc>.
    """
    frame = bytes([
        0x7E, 0xFF, 0x11,
        0x03,
        cmd,
        0x0C,
        (register >> 8) & 0xFF, register & 0xFF,
        (count    >> 8) & 0xFF, count    & 0xFF,
    ])
    crc = crc16_modbus(frame)
    return frame + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


# ================================================================
# Seriale
# ================================================================

def open_serial() -> serial.Serial | None:
    """Apre la porta seriale. Ritorna None (senza sollevare) in caso di errore."""
    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=TIMEOUT,
            write_timeout=TIMEOUT,
        )
        log.info("Porta %s aperta (%d baud, 8N1)", PORT, BAUD)
        return ser
    except (serial.SerialException, OSError) as e:
        log.error("Impossibile aprire %s: %s", PORT, e)
        return None


def read_response(ser: serial.Serial, first_wait: float = 0.6,
                  idle_gap: float = 0.06, max_wait: float = 1.5) -> bytes:
    """
    Legge la risposta dell'inverter senza attendere il timeout della porta.

    Termina appena la linea resta silenziosa per `idle_gap` secondi, invece di
    bloccarsi finche' non arriva un numero fisso di byte: un ciclo di polling
    passa cosi' da ~4 s a poche centinaia di ms.
    """
    buf = bytearray()
    t0 = last = time.monotonic()
    overflow = False

    while True:
        now = time.monotonic()

        # Guardia assoluta, valutata PRIMA di leggere: se la linea non tace mai
        # (bus flottante, adattatore guasto) il ciclo deve comunque finire.
        # Senza questo controllo la lettura non termina, il buffer cresce
        # all'infinito e ser_lock resta preso, bloccando anche i comandi MQTT.
        if now - t0 >= max_wait:
            if buf:
                log.debug("Lettura chiusa dal limite di %.1fs (%d byte)",
                          max_wait, len(buf))
            break

        waiting = ser.in_waiting
        if waiting:
            chunk = ser.read(waiting)
            if len(buf) + len(chunk) > MAX_RESPONSE_BYTES:
                buf += chunk[:MAX_RESPONSE_BYTES - len(buf)]
                overflow = True
                break
            buf += chunk
            last = time.monotonic()
            continue

        if buf and now - last >= idle_gap:
            break
        if not buf and now - t0 >= first_wait:
            break
        time.sleep(0.005)

    if overflow:
        log.warning("Ricevuti piu' di %d byte: probabile rumore sulla linea "
                    "RS485. Ingresso svuotato per risincronizzare.",
                    MAX_RESPONSE_BYTES)
        try:
            ser.reset_input_buffer()
        except (serial.SerialException, OSError) as e:
            log.debug("Svuotamento ingresso fallito: %s", e)

    return bytes(buf)


def read_frame(ser: serial.Serial, cmd: bytes, expected_cmd: int) -> bytes | None:
    """Invia un comando di lettura e ritorna il frame di risposta validato."""
    global _crc_verified

    with ser_lock:
        ser.reset_input_buffer()
        ser.write(cmd)
        raw = read_response(ser)

    if not raw:
        return None
    log.debug("RX %02X: %s", expected_cmd, raw.hex(" ").upper())

    try:
        start = raw.index(0x7E)
    except ValueError:
        log.debug("Frame %02X: delimitatore 0x7E non trovato", expected_cmd)
        return None

    frame = raw[start:]
    if len(frame) < 8:
        log.debug("Frame %02X troppo corto (%d byte)", expected_cmd, len(frame))
        return None
    if frame[4] != expected_cmd:
        log.debug("Frame %02X: comando inatteso 0x%02X", expected_cmd, frame[4])
        return None

    length = crc_frame_length(frame)
    if length is not None:
        if not _crc_verified:
            _crc_verified = True
            log.info("Verifica CRC delle risposte attiva (frame di %d byte)", length)
        return frame[:length]

    # Nessuna lunghezza produce un CRC valido: frame corrotto o formato diverso
    # da quello atteso.
    if STRICT_CRC:
        log.warning("Frame %02X scartato: CRC non valido (%d byte)",
                    expected_cmd, len(frame))
        return None
    log.debug("Frame %02X: CRC non verificabile, uso il frame cosi' com'e'",
              expected_cmd)
    return frame


def send_write_sequence(frames: list[bytes], delay: float = 0.2) -> bool:
    """
    Invia una sequenza di frame di scrittura all'inverter.
    Ritorna True se tutti i frame sono stati inviati correttamente.

    Ogni frame trasmesso e la relativa risposta sono registrati a livello INFO:
    sono rari (solo comandi dell'utente) e sono la prima cosa da guardare
    quando l'inverter non sembra recepire una scrittura.
    """
    ser = ser_global
    if ser is None or not ser.is_open:
        log.warning("Porta seriale non disponibile: comando ignorato "
                    "(porta %s, %d frame scartati)", PORT, len(frames))
        return False

    # Il lock e' condiviso con il ciclo di polling: se la sequenza dovesse
    # attendere, e' un'informazione utile quanto i byte trasmessi.
    atteso = time.monotonic()
    with ser_lock:
        attesa = time.monotonic() - atteso
        if attesa > 0.05:
            log.debug("Attesi %.2fs per la porta seriale (ciclo di lettura in corso)",
                      attesa)
        muti = rifiuti = 0
        for n, frame in enumerate(frames, 1):
            try:
                ser.reset_input_buffer()
                scritti = ser.write(frame)
                ser.flush()          # i byte devono essere sulla linea prima dell'attesa
                log.info("TX %d/%d (%s byte): %s",
                         n, len(frames), scritti, frame.hex(" ").upper())
                time.sleep(delay)
                resp = read_response(ser, first_wait=delay, max_wait=0.5)
                if resp:
                    log.info("RX %d/%d (%d byte): %s",
                             n, len(frames), len(resp), resp.hex(" ").upper())
                    # Risposta di eccezione in stile Modbus: 0x80 | tipo, cioe'
                    # 0x86 per una scrittura. L'app TBBLink la gestisce a parte.
                    start = resp.find(0x7E)
                    if start >= 0 and len(resp) > start + 3 and resp[start + 3] & 0x80:
                        rifiuti += 1
                        log.warning("L'inverter ha rifiutato il frame %d/%d "
                                    "(risposta di eccezione %#04x)",
                                    n, len(frames), resp[start + 3])
                else:
                    muti += 1
                    log.info("RX %d/%d: nessuna risposta entro %.1fs",
                             n, len(frames), delay)
            except (serial.SerialException, OSError) as e:
                log.error("Errore invio frame %d/%d (%s): %s",
                          n, len(frames), frame.hex(" ").upper(), e)
                return False

    if muti == len(frames):
        # Non e' necessariamente un errore -- alcuni firmware non rispondono
        # alle scritture -- ma se la scrittura non ha effetto e' il primo
        # indizio che i frame non stanno arrivando all'inverter.
        log.warning("L'inverter non ha risposto %s: "
                    "verifica cablaggio A+/B-, terminazione e baud rate. "
                    "Il ciclo di lettura funziona? Se anche i sensori sono "
                    "fermi, il problema e' la linea, non il comando.",
                    "al frame" if len(frames) == 1 else f"a nessuno dei {len(frames)} frame")
    return rifiuti == 0


def decode_registers(frame: bytes, count: int) -> list[int] | None:
    """
    Estrae `count` valori u16 big-endian da una risposta di lettura.

    L'app TBBLink estrae i dati con mid(6, lunghezza - 8): subito dopo
    l'intestazione di 6 byte, prima del CRC, e li copia in un'immagine dei
    registri a partire dal registro della *richiesta*. Si accetta anche la
    forma con l'eco di registro e quantita' (4 byte) in testa, per prudenza.
    Qualunque altra lunghezza ritorna None invece di produrre valori inventati.
    """
    payload = frame[6:-2]
    if len(payload) == 2 * count:
        dati = payload
    elif len(payload) == 2 * count + 4:
        dati = payload[4:]
    else:
        return None
    return [(dati[2 * i] << 8) | dati[2 * i + 1] for i in range(count)]


def read_registers(cmd: int, register: int, count: int) -> list[int] | None:
    """
    Legge `count` registri di un banco di parametri. Ritorna None se la porta
    non e' disponibile, l'inverter non risponde o la risposta non e' decodificabile.
    La lettura non modifica nulla sull'inverter.
    """
    ser = ser_global
    if ser is None or not ser.is_open:
        return None
    tx = build_read_frame(cmd, register, count)
    try:
        with ser_lock:
            ser.reset_input_buffer()
            ser.write(tx)
            ser.flush()
            raw = read_response(ser, first_wait=0.3, max_wait=1.5)
    except (serial.SerialException, OSError) as e:
        log.error("Errore nella lettura dei registri %#06x: %s", register, e)
        return None

    log.debug("TX lettura: %s", tx.hex(" ").upper())
    if not raw:
        log.debug("Lettura %#04x/%#06x: nessuna risposta", cmd, register)
        return None
    log.debug("RX lettura (%d byte): %s", len(raw), raw.hex(" ").upper())

    start = raw.find(0x7E)
    frame = raw[start:] if start >= 0 else b""
    if len(frame) < 8 or frame[4] != cmd:
        log.info("Lettura %#04x/%#06x: risposta inattesa: %s",
                 cmd, register, raw.hex(" ").upper())
        return None
    length = crc_frame_length(frame)
    if length is None:
        log.info("Lettura %#04x/%#06x: CRC non valido: %s",
                 cmd, register, frame.hex(" ").upper())
        return None
    valori = decode_registers(frame[:length], count)
    if valori is None:
        log.info("Lettura %#04x/%#06x x%d: formato non riconosciuto (%d byte): %s",
                 cmd, register, count, length, frame[:length].hex(" ").upper())
    return valori


# ================================================================
# Comandi inverter
# ================================================================

def _registro_in_ampere() -> bool:
    """True se il registro 0x005E contiene direttamente gli ampere."""
    return SMARTPORT_REGISTER_UNIT != "percent"


def _smartport_span() -> float:
    """Ampere coperti da un'escursione del registro da 0 a 100. Mai zero."""
    return max(1e-9, SMARTPORT_MAX_A - SMARTPORT_A_AT_ZERO)


def register_to_amps(register: float) -> float:
    """Valore del registro (0-100) -> corrente in ampere."""
    if _registro_in_ampere():
        return float(register)
    return SMARTPORT_A_AT_ZERO + register * _smartport_span() / 100


def amps_to_register(amps: float) -> int:
    """
    Corrente in ampere -> valore da scrivere nel registro (0-100).

    In modalita' "ampere" e' l'identita': 16 A -> 16. Questa e' la conversione
    che la 1.3.1 sbagliava, moltiplicando per 100/32 = 3,125 e mandando 16 A a
    fondo scala.
    """
    if _registro_in_ampere():
        return max(0, min(100, round(amps)))
    register = (amps - SMARTPORT_A_AT_ZERO) * 100 / _smartport_span()
    return max(0, min(100, round(register)))


def amps_to_watt(amps: float) -> int:
    """Ampere -> watt alla tensione nominale configurata."""
    return round(amps * SMARTPORT_VOLTAGE)


def watt_to_amps(watt: float) -> float:
    """Watt -> ampere alla tensione nominale configurata."""
    return watt / SMARTPORT_VOLTAGE


def cmd_smart_port(register: int) -> bool:
    """
    Imposta il valore SmartPort scrivendo il registro 0x005E.

    `register` e' il valore 0-100 che l'inverter si aspetta, ed e' esattamente
    cio' che viene trasmesso: le entita' in ampere e in watt sono viste
    derivate, gia' convertite prima di arrivare qui.

    Un solo frame, come fa l'app ufficiale. Fino alla 1.3.3 la scrittura era
    preceduta da due frame creduti uno "sblocco" (0x66 su 0x0073 e 0x0074, valore
    10): l'app li tratta invece come normali parametri -- i ritardi di
    commutazione batteria->rete e rete->batteria -- e quei frame li
    sovrascrivevano a ogni comando.

    Dopo la scrittura il registro viene riletto: e' l'unico riscontro che il
    valore sia stato davvero memorizzato, dato che l'ACK dell'inverter
    riecheggia qualunque cosa.
    """
    if not isinstance(register, int):
        # build_frame fa >> e & : un float qui solleverebbe TypeError dentro il
        # thread di rete di paho, e la scrittura fallirebbe in silenzio.
        log.warning("Valore SmartPort non intero: %r (%s)", register, type(register).__name__)
        return False
    if not 0 <= register <= 100:
        log.warning("Valore SmartPort non valido: %s (il registro accetta 0-100)",
                    register)
        return False

    amps = round(register_to_amps(register))
    log.log(25, "SmartPort -> registro 0x005E = %d  (interpretato come %d A, ~%d W; "
                "modalita' registro: %s)",
            register, amps, amps_to_watt(amps),
            "ampere" if _registro_in_ampere() else "percent")

    # L'inverter conferma con un ACK regolare qualunque valore, anche fuori
    # scala: non dice mai di no. Fuori dall'intervallo utile dichiarato non
    # sappiamo pero' cosa ne faccia, quindi lo segnaliamo senza affermare un
    # comportamento che non abbiamo osservato.
    if _registro_in_ampere() and not SMARTPORT_MIN_A <= register <= SMARTPORT_MAX_A:
        log.warning("Il registro %d e' fuori dall'intervallo utile dichiarato "
                    "(%d-%d): l'inverter accettera' comunque la scrittura, ma "
                    "l'effetto non e' verificato.",
                    register, SMARTPORT_MIN_A, SMARTPORT_MAX_A)
    if not send_write_sequence([build_frame(BANK_A_WRITE, REG_SMARTPORT_CURRENT, register)]):
        return False
    letto = verifica_smartport(register)
    # Se la rilettura riesce, le entita' mostrano cio' che l'inverter ha
    # davvero memorizzato; altrimenti il valore appena inviato.
    publish_smartport(register if letto is None else letto)
    return True


def publish_smartport(register: int):
    """Le tre entita' SmartPort descrivono lo stesso registro: si aggiornano insieme."""
    if mqtt_client is None:
        return
    amps = round(register_to_amps(register))
    mqtt_client.publish(T_SMART_STATE, register, retain=True)
    mqtt_client.publish(T_SMART_STATE_A, amps, retain=True)
    mqtt_client.publish(T_SMART_STATE_W, amps_to_watt(amps), retain=True)


def verifica_smartport(atteso: int | None = None) -> int | None:
    """
    Rilegge corrente e modalita' della SmartPort e le riporta nel log.
    Ritorna il valore letto di 0x005E, o None se la rilettura non riesce.
    """
    letto = read_registers(BANK_A_READ, REG_SMARTPORT_CURRENT, 1)
    modo = read_registers(BANK_A_READ, REG_SMARTPORT_MODE, 1)
    nome_modo = (SMARTPORT_MODES.get(modo[0], f"sconosciuta ({modo[0]})")
                 if modo else "non letta")
    if modo and mqtt_client is not None:
        mqtt_client.publish(T_SMART_MODE, nome_modo, retain=True)
    if letto is None:
        log.info("Rilettura di 0x005E non riuscita (modalita' SmartPort: %s). "
                 "Con log_level debug il log riporta la risposta grezza.", nome_modo)
        return None
    if atteso is None or letto[0] == atteso:
        log.log(25, "Rilettura: 0x005E = %d%s, modalita' SmartPort: %s",
                letto[0], "  (confermato)" if atteso is not None else "", nome_modo)
    else:
        log.warning("Rilettura: 0x005E = %d invece di %d -- l'inverter non ha "
                    "memorizzato il valore (modalita' SmartPort: %s)",
                    letto[0], atteso, nome_modo)
    return letto[0]


def cmd_full_charge(attiva: bool) -> bool:
    """
    Attiva o disattiva la carica completa della batteria ("Battery Full Charge").

    Lo stato pubblicato e' quello dell'ultimo comando andato a buon fine: e' lo
    stesso che mostra l'app ufficiale, che non ha modo di rileggerlo.
    """
    valore = 1 if attiva else 0
    log.log(25, "Carica completa batteria -> %s  (comando %#04x, registro %#06x = %d)",
            "ATTIVA" if attiva else "DISATTIVA", CMD_FULL_CHARGE, REG_FULL_CHARGE, valore)
    if not send_write_sequence([build_frame(CMD_FULL_CHARGE, REG_FULL_CHARGE, valore)]):
        return False
    if mqtt_client is not None:
        mqtt_client.publish(T_FULL_CHARGE_STATE, "ON" if attiva else "OFF", retain=True)
    return True


def write_param(banco_scrittura: int, registro: int, valore: int, etichetta: str,
                topic_stato: str | None = None) -> int | None:
    """
    Scrive un parametro di un banco con un frame singolo e lo rilegge.

    Ritorna il valore che l'inverter ha memorizzato (quello inviato, se la
    rilettura non riesce), oppure None se la scrittura e' fallita o rifiutata.
    Con `topic_stato` pubblica il valore come stato dell'entita'.
    """
    lettura = BANK_A_READ if banco_scrittura == BANK_A_WRITE else BANK_B_READ
    banco = "A" if lettura == BANK_A_READ else "B"
    log.log(25, "%s -> %d  (banco %s, registro %#06x)", etichetta, valore, banco, registro)
    if not send_write_sequence([build_frame(banco_scrittura, registro, valore)]):
        return None

    letto = read_registers(lettura, registro, 1)
    if letto is None:
        log.info("Rilettura di %s non riuscita: uso il valore inviato", etichetta)
        stato = valore
    elif letto[0] != valore:
        log.warning("Rilettura: %s = %d invece di %d -- l'inverter non ha "
                    "memorizzato il valore", etichetta, letto[0], valore)
        stato = letto[0]
    else:
        log.log(25, "Rilettura: %s = %d  (confermato)", etichetta, letto[0])
        stato = letto[0]
    if topic_stato and mqtt_client is not None:
        mqtt_client.publish(topic_stato, stato, retain=True)
    return stato


def reserved_capacity_min() -> int:
    """
    Minimo ammesso per la capacita' riservata: max(15, avviso SOC basso + 1),
    la stessa regola dell'app. Se l'avviso non si legge vale il minimo assoluto.
    """
    avviso = read_registers(BANK_A_READ, REG_SOC_LOW_WARNING, 1)
    if avviso and avviso[0] < 100:
        return max(RESERVED_MIN, avviso[0] + 1)
    return RESERVED_MIN


def cmd_reserved_capacity(valore: int) -> bool:
    """
    Imposta la capacita' riservata della batteria (SOC minimo, %) e la rilegge.

    L'inverter riecheggia qualunque valore, quindi i limiti li imponiamo noi,
    con le regole dell'app: fra max(15, avviso SOC basso + 1) e 80. Sotto
    l'avviso la riserva perderebbe senso, e l'app non lo permette.
    """
    if not isinstance(valore, int) or not RESERVED_MIN <= valore <= RESERVED_MAX:
        log.warning("Capacita' riservata non valida: %r (ammessi %d-%d %%)",
                    valore, RESERVED_MIN, RESERVED_MAX)
        return False
    minimo = reserved_capacity_min()
    if valore < minimo:
        log.warning("Capacita' riservata %d %% rifiutata: deve superare l'avviso di SOC "
                    "basso, quindi almeno %d %% (regola dell'app TBBLink)", valore, minimo)
        return False
    return write_param(BANK_B_WRITE, REG_BAT_RESERVED, valore,
                       "capacita' riservata batteria (%)", T_RESERVED_STATE) is not None


def cmd_gen_charge_current(valore: int) -> bool:
    """Imposta la corrente massima di carica dal generatore (A) e la rilegge."""
    if not isinstance(valore, int) or not GEN_CHARGE_MIN <= valore <= GEN_CHARGE_MAX:
        log.warning("Corrente di carica da generatore non valida: %r (ammessi %d-%d A)",
                    valore, GEN_CHARGE_MIN, GEN_CHARGE_MAX)
        return False
    return write_param(BANK_B_WRITE, REG_GEN_CHARGE, valore,
                       "corrente max di carica da generatore (A)", T_GEN_CHARGE_STATE) is not None


def refresh_parameters() -> int:
    """
    Rilegge i parametri esposti come entita' e ne pubblica lo stato, cosi' Home
    Assistant mostra i valori dell'inverter -- anche quelli cambiati dall'app o
    dal pannello -- e non solo l'ultimo comando inviato da qui.
    Ritorna il numero di letture riuscite.
    """
    riuscite = 0
    corrente = read_registers(BANK_A_READ, REG_SMARTPORT_CURRENT, 1)
    if corrente:
        riuscite += 1
        publish_smartport(corrente[0])
    modo = read_registers(BANK_A_READ, REG_SMARTPORT_MODE, 1)
    if modo:
        riuscite += 1
        if mqtt_client is not None:
            mqtt_client.publish(T_SMART_MODE,
                                SMARTPORT_MODES.get(modo[0], f"sconosciuta ({modo[0]})"),
                                retain=True)
    riserva = read_registers(BANK_B_READ, REG_BAT_RESERVED, 1)
    if riserva:
        riuscite += 1
        if mqtt_client is not None:
            mqtt_client.publish(T_RESERVED_STATE, riserva[0], retain=True)
    carica_gen = read_registers(BANK_B_READ, REG_GEN_CHARGE, 1)
    if carica_gen:
        riuscite += 1
        if mqtt_client is not None:
            mqtt_client.publish(T_GEN_CHARGE_STATE, carica_gen[0], retain=True)
    log.debug("Parametri riletti: SmartPort %s, modalita' %s, capacita' riservata %s, "
              "carica da generatore %s", corrente, modo, riserva, carica_gen)
    return riuscite


def cmd_raw(hex_string: str) -> bool:
    """
    Invia un frame raw specificato come stringa hex.
    Es: "7E FF 11 06 06 0C 00 5E 00 28 81 46"
    """
    if not ALLOW_RAW_COMMAND:
        log.warning("Comando raw rifiutato: abilita 'allow_raw_command' "
                    "nella configurazione dell'add-on")
        return False

    # Un payload MQTT puo' essere enorme: scartiamo prima di allocare, invece
    # di convertire megabyte di testo per poi riversarli su una linea a 9600 baud.
    if len(hex_string) > MAX_RAW_FRAME * 4:
        log.warning("Frame raw rifiutato: %d caratteri, il massimo e' %d byte",
                    len(hex_string), MAX_RAW_FRAME)
        return False

    try:
        frame = bytes(int(x, 16) for x in hex_string.replace(",", " ").split())
    except ValueError as e:
        log.warning("Frame raw non valido: %s", e)
        return False
    if not frame:
        log.warning("Frame raw vuoto")
        return False
    if len(frame) > MAX_RAW_FRAME:
        log.warning("Frame raw rifiutato: %d byte, il massimo e' %d",
                    len(frame), MAX_RAW_FRAME)
        return False

    log.log(25, "Invio frame raw: %s", frame.hex(" ").upper())
    return send_write_sequence([frame])


# ================================================================
# Decodifica
# ================================================================

def u16be(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def s16be(data: bytes, offset: int) -> int:
    v = u16be(data, offset)
    return v - 65536 if v >= 32768 else v


def decode_c0(frame: bytes) -> dict:
    """
    AC in, generatore, uscite AC, batteria, SOC, temperature, carico.

    Gli offset di rete, generatore e uscite sono quelli che il pannello di
    monitoraggio dell'app TBBLink usa per il RiiO Sun II: per ogni grandezza la
    stessa coppia di byte, la stessa scala e lo stesso segno. Fino alla 1.3.3
    alcuni erano scambiati: il byte 22 -- pubblicato come tensione di rete --
    e' la tensione del generatore, e il byte 40 -- pubblicato come frequenza di
    uscita -- e' la frequenza della rete.
    """
    d = {}
    n = len(frame)
    try:
        if n > 11:
            d["ac_in_w"]       = s16be(frame, 8)
            d["gen_w"]         = s16be(frame, 10)
        if n > 15:
            d["ac_out_w"]      = s16be(frame, 14)
        if n > 17:
            d["ac_out2_w"]     = s16be(frame, 16)
        if n > 29:
            d["ac_in_v"]       = u16be(frame, 20) / 10.0
            d["gen_v"]         = u16be(frame, 22) / 10.0
            d["ac_out_v"]      = u16be(frame, 26) / 10.0
            d["ac_out2_v"]     = u16be(frame, 28) / 10.0
        if n > 39:
            d["ac_in_i"]       = s16be(frame, 30) / 100.0
            d["gen_i"]         = s16be(frame, 32) / 100.0
            d["ac_out_i"]      = s16be(frame, 36) / 100.0
            d["ac_out2_i"]     = s16be(frame, 38) / 100.0
        if n > 45:
            d["ac_in_freq"]    = u16be(frame, 40) / 100.0
            d["gen_freq"]      = u16be(frame, 42) / 100.0
            d["ac_freq"]       = u16be(frame, 44) / 100.0
        if n > 53:
            d["bat_v"]         = u16be(frame, 50) / 1000.0
            d["bat_i"]         = s16be(frame, 52) / 10.0
        if n > 67:
            d["t_transformer"] = frame[57]
            d["t_heatsink"]    = frame[59]
            d["t_inverter"]    = frame[61]
            d["t_bat"]         = frame[67]
        if n > 99:
            d["load_pct"]      = frame[99]
        if n > 155:
            d["soc"]           = frame[155]
    except IndexError as e:
        log.warning("Errore decode C0: %s", e)
    return d


def decode_c1(frame: bytes) -> dict:
    """PV, MPPT, tensione riportata dal BMS."""
    d = {}
    n = len(frame)
    try:
        if n > 9:
            d["pv_w"]      = u16be(frame, 8)
        if n > 11:
            d["mppt_i"]    = u16be(frame, 10) / 100.0
        if n > 19:
            d["bat_v_bms"] = u16be(frame, 18) / 1000.0
        if n > 23:
            d["pv_v"]      = u16be(frame, 22) / 10.0
        if n > 39:
            d["mppt_temp"] = u16be(frame, 38)
    except IndexError as e:
        log.warning("Errore decode C1: %s", e)
    return d


# ================================================================
# Diagnostica dei frame
# ================================================================

# Offset gia' interpretati dai decoder: nel confronto vengono etichettati, cosi'
# un byte che cambia si riconosce subito come misura nota o come incognita.
_OFFSET_NOTI = {
    "C0": {14: "ac_out_w", 15: "ac_out_w", 16: "ac_out2_v", 17: "ac_out2_v",
           22: "ac_in_v", 23: "ac_in_v", 24: "ac_out_v", 25: "ac_out_v",
           30: "ac_in_i", 31: "ac_in_i", 36: "ac_out_i", 37: "ac_out_i",
           38: "ac_out2_i", 39: "ac_out2_i", 40: "ac_freq", 41: "ac_freq",
           50: "bat_v", 51: "bat_v", 52: "bat_i", 53: "bat_i",
           57: "t_transformer", 59: "t_heatsink", 61: "t_inverter",
           67: "t_bat", 99: "load_pct", 155: "soc"},
    "C1": {8: "pv_w", 9: "pv_w", 10: "mppt_i", 11: "mppt_i",
           18: "bat_v_bms", 19: "bat_v_bms", 22: "pv_v", 23: "pv_v",
           38: "mppt_temp", 39: "mppt_temp"},
}

# nome frame -> {"last": bytes, "fermo": [cicli di immobilita' per offset]}
_diag_storia = {}


def _hexdump(frame: bytes, per_riga: int = 16) -> str:
    """Dump con offset decimali ed esadecimali, per leggerlo a occhio."""
    righe = []
    for base in range(0, len(frame), per_riga):
        blocco = frame[base:base + per_riga]
        righe.append(f"  {base:3d} 0x{base:02X} | {blocco.hex(' ').upper()}")
    return "\n".join(righe)


def diag_frame(nome: str, frame: bytes | None):
    """
    Confronta il frame con quello del ciclo precedente e segnala i byte
    cambiati, ma solo quelli che erano fermi da almeno DIAG_STABLE_CYCLES.

    Le misure vive (tensioni, correnti, temperature) ballano quasi ad ogni
    ciclo e vengono cosi' filtrate da sole; un parametro di configurazione,
    invece, resta immobile finche' qualcuno non lo cambia -- ed e' esattamente
    quello che vogliamo vedere. Cambia la SmartPort dall'app nativa e il byte
    che compare qui e' il punto in cui l'inverter la rilegge.
    """
    if not DIAG_FRAMES or not frame:
        return

    prec = _diag_storia.get(nome)
    if prec is None or len(prec["last"]) != len(frame):
        _diag_storia[nome] = {"last": frame, "fermo": [0] * len(frame)}
        log.info("DIAG %s: frame di riferimento, %d byte\n%s",
                 nome, len(frame), _hexdump(frame))
        return

    ultimo, fermo = prec["last"], prec["fermo"]
    cambi = []
    for i, byte in enumerate(frame):
        if byte == ultimo[i]:
            fermo[i] += 1
        else:
            if fermo[i] >= DIAG_STABLE_CYCLES:
                cambi.append((i, ultimo[i], byte, fermo[i]))
            fermo[i] = 0

    for offset, prima, dopo, cicli in cambi:
        etichetta = _OFFSET_NOTI.get(nome, {}).get(offset)
        log.log(25, "DIAG %s[%d / 0x%02X]: %02X -> %02X  (%d -> %d, "
                    "fermo da %d cicli)%s",
                nome, offset, offset, prima, dopo, prima, dopo, cicli,
                f"  gia' decodificato come {etichetta}" if etichetta
                else "  <-- OFFSET NON DECODIFICATO")

    prec["last"] = frame


# ================================================================
# Parametri di configurazione
# ================================================================

# (comando di lettura, registro) -> (campo dell'app TBBLink, significato, unita').
#
# Ricavata dal plugin KinergierPro dell'app ufficiale: per ogni frame di
# scrittura, il widget da cui l'app prende il valore. I comandi di scrittura
# corrispondenti sono 0x06 per il banco A e 0x66 per il banco B. Le unita'
# indicate "mV" sono quelle in cui l'app converte il campo prima di inviarlo;
# le altre sono il numero cosi' come appare nell'interfaccia, ancora da
# confermare sul campo con diag_params.
_A, _B = BANK_A_READ, BANK_B_READ
PARAM_NAMES = {
    (_A, 0x0010): ("comboBox_ACIL",              "Logica ingresso AC (indice)",          ""),
    (_A, 0x0016): ("comboBox_ACOC",              "Controllo uscita AC2 (indice)",        ""),
    (_A, 0x001F): ("Cbo_ACFlexMode",             "Modalita' SmartPort (0 Smart Load, 1 Smart Gen, 2 City GEN)", ""),
    (_A, 0x003C): ("comboBox_BackflowEnable",    "Anti-immissione abilitata (indice)",   ""),
    (_A, 0x005D): ("Cbo_AcInByPassConnect",      "Bypass ingresso AC (indice)",          ""),
    (_A, 0x005E): ("Edt_MaxAlternatorCurrent",   "Corrente massima generatore",          "A"),
    (_A, 0x0042): ("Edt_DeepUndervoltageProtect", "Batteria: sottotensione profonda (spegne l'inverter)", "mV"),
    (_A, 0x0043): ("Edt_UndervoltageProtect",    "Batteria: protezione sottotensione (spegne l'uscita)", "mV"),
    (_A, 0x0044): ("Edt_UndervoltageWarning",    "Batteria: avviso sottotensione",       "mV"),
    (_A, 0x0091): ("Edt_SOCLowWarning",          "Batteria: avviso SOC basso",           "%"),
    (_A, 0x0092): ("Edt_SOCLowProtect",          "Batteria: protezione SOC basso (spegne l'uscita)", "%"),
    (_A, 0x0093): ("Edt_SOCChargeEnough",        "Batteria: SOC di carica sufficiente",  "%"),
    (_A, 0x00C1): ("comboBox_Relay1Func",        "Funzione rele' 1",                     ""),
    (_A, 0x00C2): ("comboBox_Relay2Func",        "Funzione rele' 2",                     ""),

    (_B, 0x0007): ("Cbo_IRD_DeviceEn",           "Dispositivo IRD abilitato (indice)",   ""),
    (_B, 0x0012): ("Cbo_GenLoadCtrl",            "Generatore: controllo carico (indice)", ""),
    (_B, 0x0013): ("Edt_GenChargeStartDelay",    "Generatore: ritardo avvio carica",     ""),
    (_B, 0x0014): ("Edt_GenChargeStopDelay",     "Generatore: ritardo arresto carica",   ""),
    (_B, 0x0015): ("lineEdit_Gen_StartBatVolt",  "Generatore: avvio sotto tensione batteria", "mV"),
    (_B, 0x0016): ("lineEdit_Gen_StopBatVolt",   "Generatore: arresto sopra tensione batteria", "mV"),
    (_B, 0x001A): ("lineEdit_Gen_StartLoad",     "Generatore: avvio sopra carico",       ""),
    (_B, 0x001B): ("lineEdit_Gen_StopLoad",      "Generatore: arresto sotto carico",     ""),
    (_B, 0x001C): ("lineEdit_Gen_StartSOC",      "Generatore: avvio sotto SOC",          "%"),
    (_B, 0x001D): ("lineEdit_Gen_StopSOC",       "Generatore: arresto sopra SOC",        "%"),
    (_B, 0x001E): ("Edt_GenLoadStartDelay",      "Generatore: ritardo avvio per carico", ""),
    (_B, 0x001F): ("Edt_GenLoadStopDelay",       "Generatore: ritardo arresto per carico", ""),
    (_B, 0x0028): ("radioButton_AutoCharge",     "Carica automatica",                    ""),
    (_B, 0x002A): ("lineEdit_ACI_ConnectBAT",    "Ingresso AC: connetti sotto tensione batteria", "mV"),
    (_B, 0x002B): ("lineEdit_ACI_DisconnectBAT", "Ingresso AC: disconnetti sopra tensione batteria", "mV"),
    (_B, 0x002C): ("lineEdit_ACI_ConnectDelay",  "Ingresso AC: ritardo connessione",     ""),
    (_B, 0x002D): ("lineEdit_ACI_DisconnectDelay", "Ingresso AC: ritardo disconnessione", ""),
    (_B, 0x002E): ("lineEdit_ACI_ConnectSOC",    "Ingresso AC: connetti sotto SOC",      "%"),
    (_B, 0x002F): ("lineEdit_ACI_DisconnectSOC", "Ingresso AC: disconnetti sopra SOC",   "%"),
    (_B, 0x0031): ("lineEdit_Gen_MinRuntime",    "Generatore: tempo minimo di marcia",   ""),
    (_B, 0x0032): ("lineEdit_Gen_StartIntervaltime", "Generatore: intervallo fra avvii", ""),
    (_B, 0x003E): ("Cbo_StopGenWhenGridIsVailid", "Ferma il generatore con rete presente (indice)", ""),
    (_B, 0x0040): ("comboBox_ACOC",              "Controllo uscita AC2 (indice)",        ""),
    (_B, 0x0041): ("lineEdit_ACO_DisconnectBAT", "Uscita AC2: stacca sotto tensione batteria", "mV"),
    (_B, 0x0042): ("lineEdit_ACO_ConnectBAT",    "Uscita AC2: attacca sopra tensione batteria", "mV"),
    (_B, 0x004C): ("lineEdit_ACO_DisconnectSOC", "Uscita AC2: stacca sotto SOC",         "%"),
    (_B, 0x004D): ("lineEdit_ACO_ConnectSOC",    "Uscita AC2: attacca sopra SOC",        "%"),
    (_B, 0x0051): ("lineEdit_ACI_ChargeDerate",  "Ingresso AC: riduzione carica",        ""),
    (_B, 0x0054): ("lineEdit_ACIChgMaxCurAtBatLv", "Ingresso AC: corrente max di carica a batteria bassa", ""),
    (_B, 0x0055): ("lineEdit_ACIStopCHGVolt",    "Ingresso AC: ferma la carica sopra tensione", "mV"),
    (_B, 0x0056): ("lineEdit_ACIStopChargeSOC",  "Ingresso AC: ferma la carica sopra SOC", "%"),
    (_B, 0x005A): ("Cbo_AcInByPassConnect",      "Bypass ingresso AC (indice)",          ""),
    (_B, 0x005C): ("Edt_MaxGeneratorChargeCurrent", "Corrente massima di carica da generatore / AC in 2", ""),
    (_B, 0x0060): ("comboBox_acinLvWarn",        "Avviso sottotensione ingresso AC",     ""),
    (_B, 0x0061): ("comboBox_mpptofflinewarn",   "Avviso MPPT offline",                  ""),
    (_B, 0x0062): ("comboBox_SmartGenLVWarn",    "Avviso sottotensione Smart Gen",       ""),
    (_B, 0x0063): ("lineEdit_ACO_PV_ConnectPower", "Smart Load: attacca sopra potenza FV", ""),
    (_B, 0x0064): ("lineEdit_ACO_PV_DisconnectPower", "Smart Load: stacca sotto potenza FV", ""),
    (_B, 0x0065): ("lineEdit_ACO_PV_ConnectSOC", "Smart Load: attacca sopra SOC",        "%"),
    (_B, 0x0066): ("lineEdit_ACO_PV_DisconnectSOC", "Smart Load: stacca sotto SOC",      "%"),
    (_B, 0x0067): ("lineEdit_ACO_PV_ConnectBatVolt", "Smart Load: attacca sopra tensione batteria", "mV"),
    (_B, 0x0068): ("lineEdit_ACO_PV_DisconnectBatVolt", "Smart Load: stacca sotto tensione batteria", "mV"),
    (_B, 0x0069): ("lineEdit_ACO_PV_ConnectDelay", "Smart Load: ritardo aggancio",       ""),
    (_B, 0x006A): ("lineEdit_ACO_PV_DisconnectDelay", "Smart Load: ritardo sgancio",     ""),
    (_B, 0x006B): ("lineEdit_ACO_Load_ConnectPrecent", "Smart Load: attacca sopra carico", "%"),
    (_B, 0x006C): ("lineEdit_ACO_Load_DisconnectPrecent", "Smart Load: stacca sotto carico", "%"),
    (_B, 0x006D): ("lineEdit_ACO_Load_ConnectDelay", "Smart Load: ritardo aggancio per carico", ""),
    (_B, 0x006E): ("lineEdit_ACO_Load_DisconnectDelay", "Smart Load: ritardo sgancio per carico", ""),
    (_B, 0x0070): ("Edt_BatVoltBackToUtilityMode", "Torna alla rete sotto tensione batteria", "mV"),
    (_B, 0x0071): ("Edt_BatVoltBackToBatMode",   "Torna alla batteria sopra tensione",   "mV"),
    (_B, 0x0072): ("Edt_BatReservedCapacity",    "Capacita' riservata della batteria",   "%"),
    (_B, 0x0073): ("Edt_BatToUtilityDelay",      "Ritardo commutazione batteria -> rete", ""),
    (_B, 0x0074): ("Edt_UtilityToBatDelay",      "Ritardo commutazione rete -> batteria", ""),
    (_B, 0x00DD): ("Cbo_ExternalAcInMeter",      "Contatore esterno su ingresso AC (indice)", ""),
    (_B, 0x00ED): ("comboBox_FeedBackEnable",    "Immissione in rete abilitata (indice)", ""),
    (_B, 0x00EE): ("Edt_FeedBackPower",          "Potenza di immissione",                ""),
}
del _A, _B


# Le soglie di tensione dei parametri sono espresse per blocco da 12 V: su un
# sistema a 48 V "12000" vale 48,0 V. Il fattore si ricava dalla tensione
# nominale letta nel banco A; finche' non e' nota si mostra il valore per blocco.
_fattore_tensione = None


def _aggiorna_fattore_tensione(mv: int):
    global _fattore_tensione
    if 12000 <= mv <= 96000 and mv % 12000 == 0:
        _fattore_tensione = mv // 12000


def testo_valore(v: int, unita: str) -> str:
    """Valore leggibile per il log e per i file di backup."""
    if unita == "mV":
        base = f"{v / 1000:.2f} V per blocco da 12 V"
        if _fattore_tensione:
            return f"({base} = {v * _fattore_tensione / 1000:.2f} V)"
        return f"({base})"
    return unita


def dump_parameters() -> int:
    """
    Legge i blocchi di parametri come l'app ufficiale e li riporta nel log:
    prima i valori grezzi, dieci per riga, poi quelli di cui conosciamo il nome.
    Serve a confrontare la mappa con cio' che l'app mostra a schermo.
    Ritorna il numero di blocchi letti con successo.
    """
    letti = 0
    for cmd, primo, quanti in PARAM_BLOCKS:
        valori = read_registers(cmd, primo, quanti)
        banco = "A" if cmd == BANK_A_READ else "B"
        if valori is None:
            log.info("PARAM banco %s %#06x x%d: lettura non riuscita", banco, primo, quanti)
            continue
        letti += 1
        if (cmd, primo) == (BANK_A_READ, 0) and len(valori) > REG_SYSTEM_VOLTAGE:
            _aggiorna_fattore_tensione(valori[REG_SYSTEM_VOLTAGE])
        for base in range(0, quanti, 10):
            riga = " ".join(f"{v:5d}" for v in valori[base:base + 10])
            log.info("PARAM banco %s %#06x | %s", banco, primo + base, riga)
        for i, v in enumerate(valori):
            voce = PARAM_NAMES.get((cmd, primo + i))
            if voce:
                campo, significato, unita = voce
                extra = testo_valore(v, unita)
                log.log(25, "PARAM %s %#06x = %5d%s  %s  [%s]",
                        banco, primo + i, v, f" {extra}" if extra else "", significato, campo)
        time.sleep(0.1)
    return letti


# ================================================================
# Backup e ripristino dei parametri
# ================================================================

def scrivibile(lettura: int, registro: int) -> bool:
    """True se il ripristino puo' scrivere questo registro."""
    return registro in WRITABLE.get(lettura, ())


def read_all_parameters() -> tuple[dict, int]:
    """
    Legge tutti i blocchi di parametri. Ritorna ({(comando di lettura, registro):
    valore}, numero di blocchi letti): chi chiama decide se un risultato
    parziale e' accettabile.
    """
    valori, letti = {}, 0
    for cmd, primo, quanti in PARAM_BLOCKS:
        blocco = read_registers(cmd, primo, quanti)
        if blocco is None:
            log.warning("Lettura del blocco %s %#06x x%d non riuscita",
                        "A" if cmd == BANK_A_READ else "B", primo, quanti)
            continue
        letti += 1
        if (cmd, primo) == (BANK_A_READ, 0) and len(blocco) > REG_SYSTEM_VOLTAGE:
            _aggiorna_fattore_tensione(blocco[REG_SYSTEM_VOLTAGE])
        for i, v in enumerate(blocco):
            valori[(cmd, primo + i)] = v
        time.sleep(0.1)
    return valori, letti


def _riga_backup(lettura: int, registro: int, valore: int, commentata: bool) -> str:
    banco = "A" if lettura == BANK_A_READ else "B"
    riga = f"{'#~ ' if commentata else ''}{banco} {registro:#06x} {valore:5d}"
    voce = PARAM_NAMES.get((lettura, registro))
    if voce:
        campo, significato, unita = voce
        extra = testo_valore(valore, unita)
        riga += f"   # {significato}{f' {extra}' if extra else ''}  [{campo}]"
    return riga


def backup_parameters() -> Path | None:
    """
    Salva tutti i parametri letti in un file di testo modificabile, in
    BACKUP_DIR. Ritorna il percorso del file, o None se la lettura e' incompleta.
    """
    valori, letti = read_all_parameters()
    if letti < len(PARAM_BLOCKS):
        log.error("Backup annullato: letti %d blocchi di parametri su %d",
                  letti, len(PARAM_BLOCKS))
        return None

    ripristinabili = sorted(k for k in valori if scrivibile(*k))
    altri = sorted(k for k in valori if not scrivibile(*k))
    righe = [
        "# TBB RiiO Sun II - parametri di configurazione",
        f"# Salvati da TBB Inverter Reader {ADDON_VERSION} il {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "#",
        "# Formato:  <banco> <registro> <valore>   # commento",
        "# Per ripristinare: copia questo file come 'ripristina.txt' nella stessa",
        "# cartella, modifica se serve i valori, premi 'Anteprima ripristino' e,",
        "# se le modifiche elencate nel log sono quelle volute, 'Ripristina'.",
        "# Il ripristino scrive solo le righe non commentate, e solo i valori",
        "# diversi da quelli attuali. 65535 = non usato su questo modello.",
        "# Le tensioni sono per blocco da 12 V: 12000 = 12,00 V x 4 = 48,00 V a 48 V.",
        "#",
        f"# --- Parametri ripristinabili ({len(ripristinabili)}) " + "-" * 30,
        *(_riga_backup(k[0], k[1], valori[k], False) for k in ripristinabili),
        "#",
        f"# --- Solo lettura o non mappati, ignorati dal ripristino ({len(altri)}) " + "-" * 6,
        *(_riga_backup(k[0], k[1], valori[k], True) for k in altri),
        "",
    ]
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    percorso = BACKUP_DIR / f"backup_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    percorso.write_text("\n".join(righe), encoding="utf-8")
    log.log(25, "Backup dei parametri salvato in %s (%d ripristinabili, %d in sola lettura)",
            percorso, len(ripristinabili), len(altri))
    return percorso


_RIGA_PARAMETRO = re.compile(r"^([AB])\s+(0x[0-9a-fA-F]+|\d+)\s+(\d+)\s*(?:#.*)?$")


def parse_parameters(testo: str) -> tuple[list, list]:
    """
    Interpreta un file di parametri. Ritorna (voci, errori): ogni voce e'
    (comando di lettura, registro, valore, numero di riga). Le righe vuote e
    quelle che iniziano con # vengono ignorate.
    """
    voci, errori = [], []
    for n, riga in enumerate(testo.splitlines(), 1):
        riga = riga.strip()
        if not riga or riga.startswith("#"):
            continue
        m = _RIGA_PARAMETRO.match(riga)
        if not m:
            errori.append(f"riga {n}: formato non riconosciuto: {riga!r}")
            continue
        registro, valore = int(m.group(2), 0), int(m.group(3))
        if registro > 0xFFFF or valore > 0xFFFF:
            errori.append(f"riga {n}: registro o valore oltre 16 bit: {riga!r}")
            continue
        voci.append((BANK_A_READ if m.group(1) == "A" else BANK_B_READ, registro, valore, n))
    return voci, errori


def _file_parametri(nome: str) -> Path | None:
    """Solo un nome semplice dentro BACKUP_DIR: niente percorsi dal payload MQTT."""
    if not re.fullmatch(r"[\w.-]+\.txt", nome) or nome.startswith("."):
        log.error("Nome di file non valido: %r (serve un nome .txt in %s)", nome, BACKUP_DIR)
        return None
    return BACKUP_DIR / nome


def restore_parameters(nome: str = RESTORE_FILE, applica: bool = False) -> dict | None:
    """
    Confronta un file di parametri con i valori attuali dell'inverter e, con
    `applica`, scrive quelli diversi. Senza `applica` e' un'anteprima: elenca
    le modifiche nel log e non tocca nulla.

    Vengono scritte solo le righe di registri ripristinabili (WRITABLE), mai il
    valore 65535 (non usato) e mai un registro che sull'inverter vale 65535.
    Un file con anche una sola riga non valida viene rifiutato per intero.
    Ritorna un riepilogo, o None se il ripristino non e' partito.
    """
    tipo = "RIPRISTINO" if applica else "ANTEPRIMA"
    percorso = _file_parametri(nome)
    if percorso is None:
        return None
    if not percorso.is_file():
        log.error("%s: file non trovato: %s", tipo, percorso)
        return None
    voci, errori = parse_parameters(percorso.read_text(encoding="utf-8", errors="replace"))
    for errore in errori:
        log.error("%s: %s", tipo, errore)
    if errori:
        log.error("%s annullato: correggi le righe segnalate in %s", tipo, percorso)
        return None
    if not voci:
        log.error("%s annullato: nessun parametro in %s", tipo, percorso)
        return None

    attuali, letti = read_all_parameters()
    if letti < len(PARAM_BLOCKS):
        log.error("%s annullato: letti %d blocchi di parametri su %d",
                  tipo, letti, len(PARAM_BLOCKS))
        return None

    modifiche, ignorati, uguali = [], [], 0
    for lettura, registro, valore, n in voci:
        banco = "A" if lettura == BANK_A_READ else "B"
        chiave = f"{banco} {registro:#06x}"
        if not scrivibile(lettura, registro):
            ignorati.append(f"{chiave} (riga {n}): non ripristinabile")
        elif valore == 0xFFFF:
            ignorati.append(f"{chiave} (riga {n}): 65535 = non usato")
        elif (lettura, registro) not in attuali or attuali[(lettura, registro)] == 0xFFFF:
            ignorati.append(f"{chiave} (riga {n}): non usato su questo inverter")
        elif attuali[(lettura, registro)] == valore:
            uguali += 1
        else:
            modifiche.append((lettura, registro, attuali[(lettura, registro)], valore))

    log.log(25, "%s da %s: %d da modificare, %d gia' uguali, %d ignorati",
            tipo, percorso.name, len(modifiche), uguali, len(ignorati))
    for lettura, registro, prima, dopo in modifiche:
        voce = PARAM_NAMES.get((lettura, registro))
        log.log(25, "  %s %#06x: %d -> %d%s", "A" if lettura == BANK_A_READ else "B",
                registro, prima, dopo, f"   {voce[1]} [{voce[0]}]" if voce else "")
    for motivo in ignorati:
        log.info("  ignorato %s", motivo)

    riepilogo = {"modifiche": len(modifiche), "uguali": uguali, "ignorati": len(ignorati),
                 "scritti": 0, "falliti": 0}
    if not applica:
        return riepilogo

    for lettura, registro, _prima, dopo in modifiche:
        scrittura = BANK_A_WRITE if lettura == BANK_A_READ else BANK_B_WRITE
        voce = PARAM_NAMES.get((lettura, registro))
        etichetta = voce[1] if voce else f"registro {registro:#06x}"
        if write_param(scrittura, registro, dopo, etichetta) == dopo:
            riepilogo["scritti"] += 1
        else:
            riepilogo["falliti"] += 1
    log.log(25, "RIPRISTINO completato: %d scritti, %d falliti",
            riepilogo["scritti"], riepilogo["falliti"])
    refresh_parameters()
    return riepilogo


# Backup e ripristino durano decine di secondi: girano in un thread a parte,
# altrimenti bloccherebbero il loop di rete di paho fino a far scadere il
# keepalive MQTT. Uno alla volta.
_operazione_parametri = threading.Lock()
_ultimo_lavoro = None


def esegui_in_background(descrizione: str, funzione, topic_status: str):
    """Esegue `funzione` in un thread; pubblica OK se ritorna un esito riuscito."""
    global _ultimo_lavoro
    if not _operazione_parametri.acquire(blocking=False):
        log.warning("%s rifiutato: un'altra operazione sui parametri e' in corso", descrizione)
        if mqtt_client is not None:
            mqtt_client.publish(topic_status, "ERRORE")
        return

    def lavoro():
        ok = False
        try:
            esito = funzione()
            ok = esito is not None and not (isinstance(esito, dict) and esito.get("falliti"))
        except Exception:
            log.exception("%s: errore imprevisto", descrizione)
        finally:
            _operazione_parametri.release()
        if mqtt_client is not None:
            mqtt_client.publish(topic_status, "OK" if ok else "ERRORE")

    _ultimo_lavoro = threading.Thread(target=lavoro, name=descrizione, daemon=True)
    _ultimo_lavoro.start()


# ================================================================
# Canali calcolati
# ================================================================

def _bat_status(d: dict) -> str:
    i = d["bat_i"]
    return "In carica" if i > 0.5 else "In scarica" if i < -0.5 else "A riposo"


# (chiave, dipendenze, calcolo)
#
# Le voci vengono valutate in ordine e scrivono nello stesso dizionario, quindi
# un canale calcolato puo' dipendere da uno definito piu' in alto.
#
# Le potenze di rete, generatore e uscita 2 non sono piu' calcolate: l'inverter
# le misura e le riporta nel frame C0, con il proprio segno. Resta calcolata la
# potenza di batteria: bat_i e' con segno, quindi bat_w positiva = in carica.
DERIVED = [
    ("bat_w",        ("bat_v", "bat_i"),
     lambda d: round(d["bat_v"] * d["bat_i"], 1)),

    ("ac_out_tot_w", ("ac_out_w", "ac_out2_w"),
     lambda d: round(d["ac_out_w"] + d["ac_out2_w"])),

    ("bat_status",   ("bat_i",), _bat_status),
]


def apply_derived(data: dict) -> dict:
    """
    Aggiunge i canali calcolati a partire dalle grandezze lette.

    Un canale viene prodotto solo se tutte le sue dipendenze sono presenti: se
    un frame arriva corto e manca la corrente di batteria, `bat_w` semplicemente
    non compare, invece di finire a zero.
    """
    for key, deps, compute in DERIVED:
        if all(dep in data for dep in deps):
            try:
                data[key] = compute(data)
            except (TypeError, ValueError) as e:
                log.warning("Errore nel calcolo di %s: %s", key, e)
    return data


# ================================================================
# MQTT Discovery
# ================================================================

# key, nome, unita', device_class, state_class, icona, decimali, diagnostica
#
# L'ultimo campo marca le grandezze diagnostiche: finiscono nella sezione
# "Diagnostica" del dispositivo e nascono **disabilitate**. Sono quelle che
# servono a capire un problema, non a governare l'impianto -- temperature,
# tensione riportata dal BMS, frequenza di uscita -- e restano quasi immobili
# per ore. Tenerle spente evita di scrivere nel database di Home Assistant
# valori che nessuno guarda; si abilitano dall'interfaccia in due clic, senza
# riavviare l'add-on.
SENSORS = [
    ("pv_v",          "Tensione FV",              "V",   "voltage",     "measurement", None,             1, False),
    ("mppt_i",        "Corrente MPPT",            "A",   "current",     "measurement", None,             2, False),
    ("pv_w",          "Potenza FV",               "W",   "power",       "measurement", None,             0, False),
    ("mppt_temp",     "Temperatura MPPT",         "°C",  "temperature", "measurement", None,             0, True),

    ("bat_v",         "Tensione batteria",        "V",   "voltage",     "measurement", None,             3, False),
    ("bat_v_bms",     "Tensione batteria BMS",    "V",   "voltage",     "measurement", None,             3, True),
    ("bat_i",         "Corrente batteria",        "A",   "current",     "measurement", None,             1, False),
    ("bat_w",         "Potenza batteria",         "W",   "power",       "measurement", None,             0, False),
    ("soc",           "Stato di carica",          "%",   "battery",     "measurement", None,             0, False),
    ("t_bat",         "Temperatura batteria",     "°C",  "temperature", "measurement", None,             0, False),
    ("bat_status",    "Stato batteria",           None,  None,          None,          "mdi:battery",  None, False),

    ("ac_out_v",      "Tensione uscita AC",       "V",   "voltage",     "measurement", None,             1, False),
    ("ac_out_i",      "Corrente uscita AC",       "A",   "current",     "measurement", None,             2, False),
    ("ac_out_w",      "Potenza uscita AC",        "W",   "power",       "measurement", None,             0, False),
    ("ac_out2_v",     "Tensione uscita AC 2",     "V",   "voltage",     "measurement", None,             1, False),
    ("ac_out2_i",     "Corrente uscita AC 2",     "A",   "current",     "measurement", None,             2, False),
    ("ac_out2_w",     "Potenza uscita AC 2",      "W",   "power",       "measurement", None,             0, False),
    ("ac_out_tot_w",  "Potenza uscita AC totale", "W",   "power",       "measurement", None,             0, False),
    ("ac_freq",       "Frequenza uscita",         "Hz",  "frequency",   "measurement", None,             2, True),
    ("ac_in_freq",    "Frequenza rete",           "Hz",  "frequency",   "measurement", None,             2, True),
    ("load_pct",      "Carico",                   "%",   None,          "measurement", "mdi:gauge",      0, False),

    ("ac_in_v",       "Tensione rete",            "V",   "voltage",     "measurement", None,             1, False),
    ("ac_in_i",       "Corrente rete",            "A",   "current",     "measurement", None,             2, False),
    ("ac_in_w",       "Potenza rete",             "W",   "power",       "measurement", None,             0, False),

    # Ingresso generatore: e' da qui che entra l'energia quando la SmartPort
    # lavora come Smart Gen. Ricavato dal pannello GEN dell'app TBBLink.
    ("gen_v",         "Tensione generatore",      "V",   "voltage",     "measurement", None,             1, False),
    ("gen_i",         "Corrente generatore",      "A",   "current",     "measurement", None,             2, False),
    ("gen_w",         "Potenza generatore",       "W",   "power",       "measurement", None,             0, False),
    ("gen_freq",      "Frequenza generatore",     "Hz",  "frequency",   "measurement", None,             2, True),

    ("t_heatsink",    "Temperatura dissipatore",  "°C",  "temperature", "measurement", None,             0, True),
    ("t_transformer", "Temperatura trasformatore", "°C", "temperature", "measurement", None,             0, True),
    ("t_inverter",    "Temperatura inverter",     "°C",  "temperature", "measurement", None,             0, True),
]

DATA_KEYS = [s[0] for s in SENSORS]


def _device_block() -> dict:
    return {
        "identifiers": [DEVICE_ID],
        "name": "TBB RiiO Sun II",
        "manufacturer": "TBB Power",
        "model": "RiiO Sun II 8.0S (48V-8000VA)",
        "sw_version": ADDON_VERSION,
    }


def _origin_block() -> dict:
    return {
        "name": "TBB Inverter Reader",
        "sw_version": ADDON_VERSION,
        "support_url": "https://github.com/CarloFalco/ha-tbb-inverter-addon",
    }


def discovery_payloads() -> list[tuple[str, dict]]:
    """Costruisce (topic, payload) per ogni entita' esposta via MQTT Discovery."""
    items = []

    for key, name, unit, dev_cla, stat_cla, icon, precision, diag in SENSORS:
        payload = {
            "name": name,
            "unique_id": f"{DEVICE_ID}_{key}",
            "object_id": f"{DEVICE_ID}_{key}",
            "state_topic": f"{MQTT_PREFIX}/{key}",
            "availability_topic": T_AVAILABILITY,
            "device": _device_block(),
            "origin": _origin_block(),
        }
        if unit:
            payload["unit_of_measurement"] = unit
        if dev_cla:
            payload["device_class"] = dev_cla
        if stat_cla:
            payload["state_class"] = stat_cla
        if icon:
            payload["icon"] = icon
        if precision is not None:
            payload["suggested_display_precision"] = precision
        if diag:
            payload["entity_category"] = "diagnostic"
            # Creata ma spenta: non produce stati e non finisce nel recorder
            # finche' l'utente non la abilita.
            payload["enabled_by_default"] = False
        items.append((f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/{key}/config", payload))

    # SmartPort: tre slider che scrivono lo stesso registro, in unita' diverse.
    # chiave, nome, unita', comando, stato, min, max, passo, icona
    smartport = [
        ("smart_port_a", "SmartPort corrente", "A",
         T_CMD_SMART_A, T_SMART_STATE_A,
         SMARTPORT_MIN_A, SMARTPORT_MAX_A, 1, "mdi:current-ac"),

        ("smart_port_w", "SmartPort potenza", "W",
         T_CMD_SMART_W, T_SMART_STATE_W,
         amps_to_watt(SMARTPORT_MIN_A), amps_to_watt(SMARTPORT_MAX_A),
         SMARTPORT_VOLTAGE, "mdi:flash"),

        # Slider grezzo: scrive nel registro il numero cosi' com'e'. Non e' una
        # percentuale quando il registro contiene ampere -- etichettarlo "%"
        # era la meta' cosmetica dello stesso equivoco che rompeva le altre due.
        ("smart_port", "SmartPort registro", "" if _registro_in_ampere() else "%",
         T_CMD_SMART, T_SMART_STATE,
         0, 100, 1, "mdi:transmission-tower"),
    ]
    for key, name, unit, cmd_t, stat_t, minimo, massimo, passo, icon in smartport:
        items.append((
            f"{DISCOVERY_PREFIX}/number/{DEVICE_ID}/{key}/config",
            {
                "name": name,
                "unique_id": f"{DEVICE_ID}_{key}",
                "object_id": f"{DEVICE_ID}_{key}",
                "command_topic": cmd_t,
                "state_topic": stat_t,
                "availability_topic": T_AVAILABILITY,
                **({"unit_of_measurement": unit} if unit else {}),
                "min": minimo, "max": massimo, "step": passo,
                "mode": "slider",
                "icon": icon,
                "entity_category": "config",
                "device": _device_block(),
                "origin": _origin_block(),
            },
        ))

    comune = {
        "availability_topic": T_AVAILABILITY,
        "device": _device_block(),
        "origin": _origin_block(),
    }
    items.append((
        f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/smart_port_mode/config",
        {
            "name": "SmartPort modalita'",
            "unique_id": f"{DEVICE_ID}_smart_port_mode",
            "object_id": f"{DEVICE_ID}_smart_port_mode",
            "state_topic": T_SMART_MODE,
            "icon": "mdi:swap-horizontal",
            **comune,
        },
    ))
    items.append((
        f"{DISCOVERY_PREFIX}/switch/{DEVICE_ID}/bat_full_charge/config",
        {
            "name": "Carica completa batteria",
            "unique_id": f"{DEVICE_ID}_bat_full_charge",
            "object_id": f"{DEVICE_ID}_bat_full_charge",
            "command_topic": T_CMD_FULL_CHARGE,
            "state_topic": T_FULL_CHARGE_STATE,
            "payload_on": "ON", "payload_off": "OFF",
            "state_on": "ON", "state_off": "OFF",
            "icon": "mdi:battery-charging-100",
            "entity_category": "config",
            **comune,
        },
    ))
    items.append((
        f"{DISCOVERY_PREFIX}/number/{DEVICE_ID}/bat_reserved_capacity/config",
        {
            "name": "Capacita' riservata batteria",
            "unique_id": f"{DEVICE_ID}_bat_reserved_capacity",
            "object_id": f"{DEVICE_ID}_bat_reserved_capacity",
            "command_topic": T_CMD_RESERVED,
            "state_topic": T_RESERVED_STATE,
            "unit_of_measurement": "%",
            "min": RESERVED_MIN, "max": RESERVED_MAX, "step": 1,
            "mode": "box",
            "icon": "mdi:battery-lock",
            "entity_category": "config",
            **comune,
        },
    ))
    items.append((
        f"{DISCOVERY_PREFIX}/number/{DEVICE_ID}/gen_charge_current/config",
        {
            "name": "Corrente max carica da generatore",
            "unique_id": f"{DEVICE_ID}_gen_charge_current",
            "object_id": f"{DEVICE_ID}_gen_charge_current",
            "command_topic": T_CMD_GEN_CHARGE,
            "state_topic": T_GEN_CHARGE_STATE,
            "unit_of_measurement": "A",
            "min": GEN_CHARGE_MIN, "max": GEN_CHARGE_MAX, "step": 1,
            "mode": "box",
            "icon": "mdi:battery-charging-high",
            "entity_category": "config",
            **comune,
        },
    ))
    for key, nome, topic, icona in (
        ("param_backup", "Backup parametri inverter", T_CMD_BACKUP, "mdi:content-save"),
        ("param_restore_preview", "Anteprima ripristino parametri", T_CMD_RESTORE_PREVIEW,
         "mdi:file-compare"),
        ("param_restore", "Ripristina parametri inverter", T_CMD_RESTORE, "mdi:backup-restore"),
    ):
        items.append((
            f"{DISCOVERY_PREFIX}/button/{DEVICE_ID}/{key}/config",
            {
                "name": nome,
                "unique_id": f"{DEVICE_ID}_{key}",
                "object_id": f"{DEVICE_ID}_{key}",
                "command_topic": topic,
                "payload_press": "PRESS",
                "icon": icona,
                "entity_category": "config",
                **comune,
            },
        ))
    return items


def publish_discovery(client: mqtt.Client, enabled: bool):
    """
    Pubblica (o rimuove) le configurazioni di MQTT Discovery.

    I messaggi sono retained e idempotenti: vengono ripubblicati ad ogni
    connessione, cosi' un riavvio del broker non perde le entita'. Con
    `enabled=False` viene inviato un payload vuoto, che in Home Assistant
    equivale alla rimozione dell'entita'.
    """
    payloads = discovery_payloads()
    for topic, payload in payloads:
        body = json.dumps(payload, ensure_ascii=False) if enabled else ""
        client.publish(topic, body, retain=True)
    if enabled:
        spente = sum(1 for _, p in payloads
                     if p.get("enabled_by_default") is False)
        log.info("MQTT Discovery: %d entita' pubblicate sotto '%s/' "
                 "(%d diagnostiche, disabilitate finche' non le abiliti)",
                 len(payloads), DISCOVERY_PREFIX, spente)
    else:
        log.info("MQTT Discovery disabilitato: entita' rimosse da Home Assistant")


# ================================================================
# MQTT
# ================================================================

# topic -> (unita', limiti ammessi, conversione nel valore di registro 0-100).
# I limiti sono funzioni perche' dipendono dalle opzioni lette all'avvio.
#
# La prima riga usa l'identita': quel topic scrive nel registro esattamente il
# numero ricevuto, senza alcuna conversione. E' il comportamento della
# primissima versione funzionante e va lasciato intatto -- e' anche la via di
# fuga se le altre due unita' dovessero sbagliare conversione.
SMARTPORT_COMMANDS = {
    T_CMD_SMART:   ("(registro)", lambda: (0, 100), round),
    T_CMD_SMART_A: ("A", lambda: (SMARTPORT_MIN_A, SMARTPORT_MAX_A),
                    amps_to_register),
    T_CMD_SMART_W: ("W", lambda: (amps_to_watt(SMARTPORT_MIN_A),
                                  amps_to_watt(SMARTPORT_MAX_A)),
                    lambda w: amps_to_register(watt_to_amps(w))),
}


def _rc_failed(reason_code) -> bool:
    """True se il reason code MQTT indica un errore (paho 2.x o int)."""
    failure = getattr(reason_code, "is_failure", None)
    return bool(failure) if failure is not None else reason_code != 0


def set_available(client: mqtt.Client, available: bool):
    """Pubblica lo stato di disponibilita' solo quando cambia."""
    global _available
    if _available == available:
        return
    info = client.publish(T_AVAILABILITY, "online" if available else "offline",
                          retain=True)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        # Broker non ancora raggiungibile: non memorizziamo lo stato, cosi' il
        # prossimo ciclo riprova invece di restare bloccato su un valore mai
        # arrivato al broker.
        return
    _available = available
    log.log(25, "Entita' Home Assistant: %s",
            "disponibili" if available else "non disponibili")


def publish(client: mqtt.Client, data: dict):
    """
    Pubblica un topic per grandezza piu' il JSON aggregato.

    Vengono pubblicate solo le chiavi effettivamente decodificate: un frame
    corto non deve far comparire uno zero (SOC a 0, tensione a 0...) nello
    storico di Home Assistant.
    """
    for key, value in data.items():
        client.publish(f"{MQTT_PREFIX}/{key}", value, retain=True)
    client.publish(T_STATE_JSON, json.dumps(data, ensure_ascii=False), retain=True)


def on_connect(client, userdata, flags, reason_code, properties=None):
    if _rc_failed(reason_code):
        log.error("Connessione MQTT rifiutata: %s", reason_code)
        return
    log.info("MQTT connesso a %s:%d", MQTT_HOST, MQTT_PORT)

    # Le sottoscrizioni vanno rifatte ad ogni connessione: dopo un riavvio del
    # broker una subscribe fatta una volta sola all'avvio andrebbe persa.
    topics = ([(t, 0) for t in SMARTPORT_COMMANDS]
              + [(t, 0) for t in (T_CMD_FULL_CHARGE, T_CMD_RESERVED, T_CMD_GEN_CHARGE,
                                  T_CMD_BACKUP, T_CMD_RESTORE_PREVIEW, T_CMD_RESTORE,
                                  T_CMD_RAW)])
    client.subscribe(topics)
    log.debug("Sottoscritto a: %s", ", ".join(t for t, _ in topics))

    publish_discovery(client, DISCOVERY)

    # Ripubblica lo stato corrente di disponibilita' (il LWT potrebbe aver
    # lasciato "offline" ritenuto sul broker).
    state = _available
    client.publish(T_AVAILABILITY, "online" if state else "offline", retain=True)


def on_disconnect(client, userdata, flags, reason_code, properties=None):
    if _rc_failed(reason_code):
        log.warning("MQTT disconnesso (%s), riconnessione automatica in corso",
                    reason_code)


def _payload_intero(payload: str) -> int | None:
    """Intero da un payload MQTT; accetta "25" e "25.0", rifiuta decimali e NaN."""
    try:
        valore = float(payload)
        if valore != valore or valore != round(valore):
            return None
        return int(valore)
    except (ValueError, OverflowError):
        return None


def on_message(client, userdata, msg):
    """Callback MQTT per i comandi in ingresso."""
    try:
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        log.log(25, "Comando ricevuto: %s = %s", msg.topic, payload)

        if msg.topic in SMARTPORT_COMMANDS:
            unita, limiti, in_registro = SMARTPORT_COMMANDS[msg.topic]
            try:
                # OverflowError copre "inf": round() non sa convertirlo.
                valore = float(payload)
                if valore != valore:          # NaN
                    raise ValueError("NaN")
                round(valore)
            except (ValueError, OverflowError):
                log.warning("Valore SmartPort non numerico: %r", payload)
                client.publish(f"{msg.topic}/status", "ERRORE")
                return

            minimo, massimo = limiti()
            if not minimo <= valore <= massimo:
                log.warning("Valore SmartPort fuori scala: %s %s (ammessi %s-%s %s)",
                            valore, unita, minimo, massimo, unita)
                client.publish(f"{msg.topic}/status", "ERRORE")
                return

            registro = in_registro(valore)
            log.info("Conversione: %s %s -> registro %s%s",
                     valore, unita, registro,
                     "  (identita')" if float(registro) == float(valore) else "")
            ok = cmd_smart_port(registro)
            client.publish(f"{msg.topic}/status", "OK" if ok else "ERRORE")

        elif msg.topic == T_CMD_FULL_CHARGE:
            scelta = payload.strip().upper()
            if scelta in ("ON", "1", "TRUE"):
                ok = cmd_full_charge(True)
            elif scelta in ("OFF", "0", "FALSE"):
                ok = cmd_full_charge(False)
            else:
                log.warning("Comando carica completa non riconosciuto: %r (usa ON/OFF)",
                            payload)
                ok = False
            client.publish(f"{msg.topic}/status", "OK" if ok else "ERRORE")

        elif msg.topic in (T_CMD_RESERVED, T_CMD_GEN_CHARGE):
            valore = _payload_intero(payload)
            if valore is None:
                log.warning("Valore non numerico o non intero su %s: %r", msg.topic, payload)
                client.publish(f"{msg.topic}/status", "ERRORE")
                return
            comando = cmd_reserved_capacity if msg.topic == T_CMD_RESERVED else cmd_gen_charge_current
            ok = comando(valore)
            client.publish(f"{msg.topic}/status", "OK" if ok else "ERRORE")

        elif msg.topic == T_CMD_BACKUP:
            esegui_in_background("Backup parametri", backup_parameters, f"{msg.topic}/status")

        elif msg.topic in (T_CMD_RESTORE_PREVIEW, T_CMD_RESTORE):
            # Il pulsante invia PRESS: si usa il file predefinito. Via MQTT si
            # puo' indicare un altro file della stessa cartella.
            nome = payload.strip()
            if nome in ("", "PRESS"):
                nome = RESTORE_FILE
            applica = msg.topic == T_CMD_RESTORE
            esegui_in_background("Ripristino parametri" if applica else "Anteprima ripristino",
                                 lambda: restore_parameters(nome, applica),
                                 f"{msg.topic}/status")

        elif msg.topic == T_CMD_RAW:
            ok = cmd_raw(payload)
            client.publish(f"{T_CMD_RAW}/status", "OK" if ok else "ERRORE")

    except Exception:
        # Un'eccezione qui girerebbe nel thread di rete di paho e potrebbe
        # interrompere il loop MQTT: la assorbiamo e la registriamo.
        log.exception("Errore nella gestione del comando %s", msg.topic)


def setup_mqtt() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="tbb_inverter")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    # Last Will: se l'add-on muore, le entita' diventano non disponibili invece
    # di restare congelate sull'ultimo valore ritenuto.
    client.will_set(T_AVAILABILITY, "offline", retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    # connect_async + loop_start: la connessione viene ritentata all'infinito
    # anche se il broker non e' ancora pronto all'avvio di Home Assistant.
    client.connect_async(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
    client.loop_start()
    return client


# ================================================================
# Output a video
# ================================================================

def _fmt(value, spec: str, fallback: str = "--") -> str:
    """Formatta un valore, sostituendolo con `fallback` allineato se manca."""
    if value is None:
        width = "".join(c for c in spec.split(".")[0] if c.isdigit())
        return fallback.rjust(int(width) if width else len(fallback))
    try:
        return format(value, spec)
    except (TypeError, ValueError):
        return str(value)


def log_data(data: dict, cycle: int):
    if not log.isEnabledFor(logging.INFO):
        return

    g = data.get
    ac_in_i = g("ac_in_i")
    ac_dir = "--" if ac_in_i is None else ("rete->inv" if ac_in_i < 0 else "inv->rete")

    lines = [
        "-" * 55,
        f"  Ciclo {cycle}  -  {time.strftime('%H:%M:%S')}",
        "-" * 55,
        (f"  PV:        {_fmt(g('pv_v'), '6.1f')} V  {_fmt(g('mppt_i'), '5.2f')} A  "
         f"{_fmt(g('pv_w'), '5.0f')} W  (MPPT {_fmt(g('mppt_temp'), '')}°C)"),
        (f"  AC Out:    {_fmt(g('ac_out_v'), '6.1f')} V  {_fmt(g('ac_out_i'), '5.2f')} A  "
         f"{_fmt(g('ac_out_w'), '5.0f')} W"),
        (f"  AC Out2:   {_fmt(g('ac_out2_v'), '6.1f')} V  {_fmt(g('ac_out2_i'), '5.2f')} A  "
         f"{_fmt(g('ac_out2_w'), '5.0f')} W"),
        (f"  Rete:      {_fmt(g('ac_in_v'), '6.1f')} V  {_fmt(ac_in_i, '+6.2f')} A  "
         f"{_fmt(g('ac_in_w'), '+5.0f')} W  {_fmt(g('ac_in_freq'), '5.2f')} Hz  ({ac_dir})"),
        (f"  Generatore:{_fmt(g('gen_v'), '6.1f')} V  {_fmt(g('gen_i'), '+6.2f')} A  "
         f"{_fmt(g('gen_w'), '+5.0f')} W  {_fmt(g('gen_freq'), '5.2f')} Hz"),
        f"  Freq out:  {_fmt(g('ac_freq'), '6.2f')} Hz",
        (f"  Batteria:  {_fmt(g('bat_v'), '6.3f')} V  {_fmt(g('bat_i'), '+6.1f')} A "
         f"({g('bat_status', '--')})  SOC {_fmt(g('soc'), '3')}%"),
        f"  BAT BMS:   {_fmt(g('bat_v_bms'), '.3f')} V",
        (f"  Potenze:   Batteria {_fmt(g('bat_w'), '+7.0f')} W   "
         f"Rete {_fmt(g('ac_in_w'), '+6.0f')} W   "
         f"Gen {_fmt(g('gen_w'), '+6.0f')} W   "
         f"Uscite {_fmt(g('ac_out_tot_w'), '5.0f')} W"),
        (f"  Temp:      Heatsink {_fmt(g('t_heatsink'), '3')}°C  "
         f"Transformer {_fmt(g('t_transformer'), '3')}°C  "
         f"Inverter {_fmt(g('t_inverter'), '3')}°C  BAT {_fmt(g('t_bat'), '3')}°C"),
        f"  Carico:    {_fmt(g('load_pct'), '3')}%",
    ]
    log.info("\n%s", "\n".join(lines))


# ================================================================
# Main
# ================================================================

def validate_smartport_config():
    """
    Controlla i limiti SmartPort presi dalle opzioni.

    Un intervallo invertito o una tensione nulla produrrebbero entita' con
    min >= max, che Home Assistant rifiuta, e divisioni per zero nelle
    conversioni: meglio tornare ai valori predefiniti segnalandolo.
    """
    global SMARTPORT_MIN_A, SMARTPORT_MAX_A, SMARTPORT_VOLTAGE, SMARTPORT_A_AT_ZERO
    global SMARTPORT_REGISTER_UNIT

    if SMARTPORT_REGISTER_UNIT not in ("ampere", "percent"):
        log.warning("smartport_register_unit sconosciuto (%r): uso 'ampere'",
                    SMARTPORT_REGISTER_UNIT)
        SMARTPORT_REGISTER_UNIT = "ampere"
    if SMARTPORT_A_AT_ZERO >= SMARTPORT_MAX_A:
        log.warning("Mappatura SmartPort non valida (0 %% -> %d A, 100 %% -> %d A): "
                    "uso 0 -> 32 A", SMARTPORT_A_AT_ZERO, SMARTPORT_MAX_A)
        SMARTPORT_A_AT_ZERO, SMARTPORT_MAX_A = 0, 32
    if SMARTPORT_MIN_A >= SMARTPORT_MAX_A:
        log.warning("Intervallo SmartPort non valido (%d-%d A): uso 5-32 A",
                    SMARTPORT_MIN_A, SMARTPORT_MAX_A)
        SMARTPORT_MIN_A, SMARTPORT_MAX_A = 5, 32
    if SMARTPORT_MIN_A < 0 or SMARTPORT_MAX_A > 0xFFFF:
        log.warning("Intervallo SmartPort fuori dai limiti del registro: uso 5-32 A")
        SMARTPORT_MIN_A, SMARTPORT_MAX_A = 5, 32
    if SMARTPORT_VOLTAGE <= 0:
        log.warning("Tensione nominale SmartPort non valida (%d V): uso 230 V",
                    SMARTPORT_VOLTAGE)
        SMARTPORT_VOLTAGE = 230
    if _registro_in_ampere() and SMARTPORT_MAX_A > 100:
        # In modalita' "ampere" gli estremi dello slider sono anche valori di
        # registro: oltre 100 verrebbero silenziosamente troncati.
        log.warning("Con il registro in ampere il massimo non puo' superare 100 A "
                    "(richiesti %d): uso 32 A", SMARTPORT_MAX_A)
        SMARTPORT_MAX_A = 32
        if SMARTPORT_MIN_A >= SMARTPORT_MAX_A:
            SMARTPORT_MIN_A = 5


def banner():
    log.info("=" * 55)
    log.info("  TBB RiiO Sun II -- Reader %s (Home Assistant Add-on)", ADDON_VERSION)
    log.info("=" * 55)
    log.info("  Porta:     %s  Baud: %d", PORT, BAUD)
    log.info("  MQTT:      %s:%d  (prefix: %s)", MQTT_HOST, MQTT_PORT, MQTT_PREFIX)
    log.info("  Polling:   ogni %ds", POLL_INTERVAL)
    log.info("  Discovery: %s", "abilitato" if DISCOVERY else "disabilitato")
    if _registro_in_ampere():
        log.info("  SmartPort: il registro 0x005E contiene AMPERE (nessuna conversione)")
        log.info("             slider: %d-%d A  =  registro %d-%d",
                 SMARTPORT_MIN_A, SMARTPORT_MAX_A, SMARTPORT_MIN_A, SMARTPORT_MAX_A)
    else:
        log.info("  SmartPort: il registro 0x005E e' una PERCENTUALE")
        log.info("             registro 0-100  ->  %d-%d A  (slider utile %d-%d A)",
                 SMARTPORT_A_AT_ZERO, SMARTPORT_MAX_A,
                 SMARTPORT_MIN_A, SMARTPORT_MAX_A)
    log.info("             slider in watt: %d-%d W a %d V nominali",
             amps_to_watt(SMARTPORT_MIN_A), amps_to_watt(SMARTPORT_MAX_A),
             SMARTPORT_VOLTAGE)
    log.info("  Comandi:   %s/cmd/smart_port[_a|_w]  |  raw %s",
             MQTT_PREFIX, "abilitato" if ALLOW_RAW_COMMAND else "disabilitato")
    log.info("  Backup:    %s  (ripristino da %s)", BACKUP_DIR, RESTORE_FILE)
    if DIAG_PARAMS:
        log.info("  DIAGNOSTICA PARAMETRI ATTIVA: al primo ciclo riuscito verranno "
                 "letti e riportati i parametri di configurazione.")
    if DIAG_FRAMES:
        log.info("  DIAGNOSTICA FRAME ATTIVA: verranno segnalati i byte che "
                 "cambiano dopo essere stati fermi almeno %d cicli.",
                 DIAG_STABLE_CYCLES)

    # Frame di riferimento: si confrontano a occhio con una cattura dell'app
    # nativa senza dover far partire una scrittura.
    for a in (SMARTPORT_MIN_A, SMARTPORT_MAX_A):
        r = amps_to_register(a)
        log.info("  Esempio:   %d A -> registro %-3d -> %s",
                 a, r, build_frame(0x06, 0x005E, r).hex(" ").upper())
    log.info("=" * 55)


def poll_once(ser: serial.Serial) -> dict:
    """Esegue un ciclo di lettura completo (C0 + C1) e ritorna i dati decodificati."""
    fc0 = read_frame(ser, CMD_C0, 0xC0)
    time.sleep(0.1)
    fc1 = read_frame(ser, CMD_C1, 0xC1)

    diag_frame("C0", fc0)
    diag_frame("C1", fc1)

    data = {}
    if fc0:
        data.update(decode_c0(fc0))
    if fc1:
        data.update(decode_c1(fc1))
    return apply_derived(data)


def main():
    global ser_global, mqtt_client

    validate_smartport_config()
    banner()
    mqtt_client = setup_mqtt()

    cycle = 0
    failed = 0
    parametri_letti = not DIAG_PARAMS
    ultima_rilettura = None
    try:
        while True:
            # --- Porta seriale: apertura e riapertura automatica -------------
            if ser_global is None or not ser_global.is_open:
                ser_global = open_serial()
                if ser_global is None:
                    set_available(mqtt_client, False)
                    log.info("Nuovo tentativo tra %ds", SERIAL_RETRY_DELAY)
                    time.sleep(SERIAL_RETRY_DELAY)
                    continue

            # --- Ciclo di lettura --------------------------------------------
            cycle += 1
            try:
                data = poll_once(ser_global)
            except (serial.SerialException, OSError) as e:
                # Tipicamente: adattatore USB scollegato. Chiudiamo e lasciamo
                # che il giro successivo riapra la porta, invece di terminare.
                log.error("Errore sulla porta seriale: %s", e)
                try:
                    ser_global.close()
                except (serial.SerialException, OSError) as close_error:
                    log.debug("Chiusura porta fallita: %s", close_error)
                ser_global = None
                set_available(mqtt_client, False)
                time.sleep(SERIAL_RETRY_DELAY)
                continue
            except Exception:
                # Rete di sicurezza: qualunque errore imprevisto non deve far
                # morire l'add-on in silenzio. Lo registriamo con lo stack,
                # segnaliamo le entita' come non disponibili e riproviamo.
                log.exception("Errore imprevisto nel ciclo %d", cycle)
                failed += 1
                if failed >= MAX_FAILED_CYCLES:
                    set_available(mqtt_client, False)
                time.sleep(POLL_INTERVAL)
                continue

            if data and not parametri_letti:
                # Una sola volta, a linea verificata: i blocchi sono ~460
                # registri e non servono a ogni ciclo.
                log.info("DIAG PARAM: lettura dei parametri di configurazione")
                parametri_letti = dump_parameters() > 0

            if data and (ultima_rilettura is None
                         or time.monotonic() - ultima_rilettura >= PARAM_REFRESH_S):
                refresh_parameters()
                ultima_rilettura = time.monotonic()

            if data:
                failed = 0
                set_available(mqtt_client, True)
                publish(mqtt_client, data)
                log_data(data, cycle)
            else:
                failed += 1
                log.warning("Ciclo %d: nessuna risposta dall'inverter (%d di seguito)",
                            cycle, failed)
                if failed >= MAX_FAILED_CYCLES:
                    set_available(mqtt_client, False)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("Interruzione richiesta, uscita.")
    finally:
        if mqtt_client is not None:
            mqtt_client.publish(T_AVAILABILITY, "offline", retain=True)
            time.sleep(0.2)          # lascia il tempo di svuotare la coda
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        try:
            if ser_global is not None and ser_global.is_open:
                with ser_lock:
                    ser_global.close()
        except (serial.SerialException, OSError) as e:
            log.debug("Chiusura porta in uscita fallita: %s", e)
        log.info("Porta e MQTT chiusi.")


if __name__ == "__main__":
    main()
