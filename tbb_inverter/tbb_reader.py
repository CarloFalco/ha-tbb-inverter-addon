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
  <prefix>/cmd/smart_port     <- percentuale 0-100 dell'intervallo utile
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
import sys
import threading
import time

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
POLL_INTERVAL = _env_int("POLL_INTERVAL", 5)

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

# SmartPort: il registro 0x005E contiene direttamente gli ampere.
SMARTPORT_MIN_A   = _env_int("SMARTPORT_MIN_A", 5)
SMARTPORT_MAX_A   = _env_int("SMARTPORT_MAX_A", 32)
SMARTPORT_VOLTAGE = _env_int("SMARTPORT_VOLTAGE", 230)
STRICT_CRC        = _env_bool("STRICT_CRC", False)
LOG_LEVEL         = os.environ.get("LOG_LEVEL", "info").strip().lower()
ADDON_VERSION     = os.environ.get("ADDON_VERSION", "dev")

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

DEVICE_ID = "tbb_riio_sun_ii"

CMD_C0 = bytes([0x7E, 0xFF, 0x11, 0x03, 0xC0, 0x08, 0xBA, 0xEB])
CMD_C1 = bytes([0x7E, 0xFF, 0x11, 0x03, 0xC1, 0x08, 0xBB, 0x7B])

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
    """
    ser = ser_global
    if ser is None or not ser.is_open:
        log.warning("Porta seriale non disponibile: comando ignorato")
        return False

    with ser_lock:
        for frame in frames:
            try:
                ser.reset_input_buffer()
                ser.write(frame)
                log.debug("TX: %s", frame.hex(" ").upper())
                time.sleep(delay)
                resp = read_response(ser, first_wait=delay, max_wait=0.5)
                if resp:
                    log.debug("ACK: %s", resp.hex(" ").upper())
            except (serial.SerialException, OSError) as e:
                log.error("Errore invio frame: %s", e)
                return False
    return True


# ================================================================
# Comandi inverter
# ================================================================

def _smartport_span() -> int:
    """Ampiezza dell'intervallo utile, mai zero."""
    return max(1, SMARTPORT_MAX_A - SMARTPORT_MIN_A)


def amps_to_pct(amps: float) -> int:
    """Ampere -> percentuale dell'intervallo utile (min = 0 %, max = 100 %)."""
    return round((amps - SMARTPORT_MIN_A) * 100 / _smartport_span())


def pct_to_amps(pct: float) -> int:
    """Percentuale dell'intervallo utile -> ampere."""
    return round(SMARTPORT_MIN_A + pct * _smartport_span() / 100)


def amps_to_watt(amps: float) -> int:
    """Ampere -> watt alla tensione nominale configurata."""
    return round(amps * SMARTPORT_VOLTAGE)


def watt_to_amps(watt: float) -> int:
    """Watt -> ampere alla tensione nominale configurata."""
    return round(watt / SMARTPORT_VOLTAGE)


def cmd_smart_port(amps: int) -> bool:
    """
    Imposta il valore SmartPort scrivendo il registro 0x005E.

    Il registro contiene direttamente la **corrente in ampere**: le entita' in
    watt e in percentuale sono solo modi diversi di esprimere lo stesso valore
    e vengono convertite prima di arrivare qui.

    Sequenza: sblocco reg 0x73, sblocco reg 0x74, scrittura reg 0x5E.
    """
    if not SMARTPORT_MIN_A <= amps <= SMARTPORT_MAX_A:
        log.warning("Valore SmartPort non valido: %s A (ammessi %d-%d A)",
                    amps, SMARTPORT_MIN_A, SMARTPORT_MAX_A)
        return False

    log.log(25, "Impostazione SmartPort = %d A (%d W, %d%%)",
            amps, amps_to_watt(amps), amps_to_pct(amps))
    frames = [
        build_frame(0x66, 0x0073, 0x000A),  # sblocco 1
        build_frame(0x66, 0x0074, 0x000A),  # sblocco 2
        build_frame(0x06, 0x005E, amps),    # scrittura SmartPort
    ]
    if not send_write_sequence(frames):
        return False

    # Le tre entita' descrivono lo stesso registro: dopo una scrittura vanno
    # aggiornate tutte, da qualunque delle tre sia arrivato il comando.
    if mqtt_client is not None:
        mqtt_client.publish(T_SMART_STATE, amps_to_pct(amps), retain=True)
        mqtt_client.publish(T_SMART_STATE_A, amps, retain=True)
        mqtt_client.publish(T_SMART_STATE_W, amps_to_watt(amps), retain=True)
    return True


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
    """AC in/out, batteria, SOC, temperature, carico."""
    d = {}
    n = len(frame)
    try:
        if n > 15:
            d["ac_out_w"]      = u16be(frame, 14)
        if n > 17:
            d["ac_out2_v"]     = u16be(frame, 16) / 10.0
        if n > 25:
            d["ac_in_v"]       = u16be(frame, 22) / 10.0
            d["ac_out_v"]      = u16be(frame, 24) / 10.0
        if n > 39:
            d["ac_in_i"]       = s16be(frame, 30) / 100.0
            d["ac_out_i"]      = u16be(frame, 36) / 100.0
            d["ac_out2_i"]     = u16be(frame, 38) / 100.0
        if n > 41:
            d["ac_freq"]       = u16be(frame, 40) / 100.0
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
# Canali calcolati
# ================================================================

def _bat_status(d: dict) -> str:
    i = d["bat_i"]
    return "In carica" if i > 0.5 else "In scarica" if i < -0.5 else "A riposo"


# (chiave, dipendenze, calcolo)
#
# Le voci vengono valutate in ordine e scrivono nello stesso dizionario, quindi
# un canale calcolato puo' dipendere da uno definito piu' in alto (e' il caso di
# ac_out_tot_w, che usa ac_out2_w).
#
# Nota sui segni: bat_i e ac_in_i sono con segno, quindi lo sono anche le
# potenze derivate. bat_w positiva = batteria in carica; ac_in_w negativa =
# energia prelevata dalla rete.
DERIVED = [
    ("bat_w",        ("bat_v", "bat_i"),
     lambda d: round(d["bat_v"] * d["bat_i"], 1)),

    ("ac_in_w",      ("ac_in_v", "ac_in_i"),
     lambda d: round(d["ac_in_v"] * d["ac_in_i"])),

    ("ac_out2_w",    ("ac_out2_v", "ac_out2_i"),
     lambda d: round(d["ac_out2_v"] * d["ac_out2_i"])),

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
    ("ac_freq",       "Frequenza uscita",         "Hz",  "frequency",   "measurement", None,             2, False),
    ("load_pct",      "Carico",                   "%",   None,          "measurement", "mdi:gauge",      0, False),

    ("ac_in_v",       "Tensione rete",            "V",   "voltage",     "measurement", None,             1, False),
    ("ac_in_i",       "Corrente rete",            "A",   "current",     "measurement", None,             2, False),
    ("ac_in_w",       "Potenza rete",             "W",   "power",       "measurement", None,             0, False),

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

        ("smart_port", "SmartPort percentuale", "%",
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
                "min": minimo, "max": massimo, "step": passo,
                "unit_of_measurement": unit,
                "mode": "slider",
                "icon": icon,
                "entity_category": "config",
                "device": _device_block(),
                "origin": _origin_block(),
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
        log.info("MQTT Discovery: %d entita' pubblicate sotto '%s/'",
                 len(payloads), DISCOVERY_PREFIX)
    else:
        log.info("MQTT Discovery disabilitato: entita' rimosse da Home Assistant")


# ================================================================
# MQTT
# ================================================================

# topic -> (unita', limiti ammessi, conversione in ampere).
# I limiti sono funzioni perche' dipendono dalle opzioni lette all'avvio.
SMARTPORT_COMMANDS = {
    T_CMD_SMART:   ("%", lambda: (0, 100), pct_to_amps),
    T_CMD_SMART_A: ("A", lambda: (SMARTPORT_MIN_A, SMARTPORT_MAX_A), round),
    T_CMD_SMART_W: ("W", lambda: (amps_to_watt(SMARTPORT_MIN_A),
                                  amps_to_watt(SMARTPORT_MAX_A)), watt_to_amps),
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
    topics = [(t, 0) for t in SMARTPORT_COMMANDS] + [(T_CMD_RAW, 0)]
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


def on_message(client, userdata, msg):
    """Callback MQTT per i comandi in ingresso."""
    try:
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        log.log(25, "Comando ricevuto: %s = %s", msg.topic, payload)

        if msg.topic in SMARTPORT_COMMANDS:
            unita, limiti, in_ampere = SMARTPORT_COMMANDS[msg.topic]
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

            ok = cmd_smart_port(in_ampere(valore))
            client.publish(f"{msg.topic}/status", "OK" if ok else "ERRORE")

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
        f"  AC In:     {_fmt(g('ac_in_v'), '6.1f')} V  {_fmt(ac_in_i, '+6.2f')} A  ({ac_dir})",
        f"  Freq:      {_fmt(g('ac_freq'), '6.2f')} Hz",
        (f"  Batteria:  {_fmt(g('bat_v'), '6.3f')} V  {_fmt(g('bat_i'), '+6.1f')} A "
         f"({g('bat_status', '--')})  SOC {_fmt(g('soc'), '3')}%"),
        f"  BAT BMS:   {_fmt(g('bat_v_bms'), '.3f')} V",
        (f"  Potenze:   Batteria {_fmt(g('bat_w'), '+7.0f')} W   "
         f"Rete {_fmt(g('ac_in_w'), '+6.0f')} W   "
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
    global SMARTPORT_MIN_A, SMARTPORT_MAX_A, SMARTPORT_VOLTAGE

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


def banner():
    log.info("=" * 55)
    log.info("  TBB RiiO Sun II -- Reader %s (Home Assistant Add-on)", ADDON_VERSION)
    log.info("=" * 55)
    log.info("  Porta:     %s  Baud: %d", PORT, BAUD)
    log.info("  MQTT:      %s:%d  (prefix: %s)", MQTT_HOST, MQTT_PORT, MQTT_PREFIX)
    log.info("  Polling:   ogni %ds", POLL_INTERVAL)
    log.info("  Discovery: %s", "abilitato" if DISCOVERY else "disabilitato")
    log.info("  SmartPort: %d-%d A  (%d-%d W a %d V nominali)",
             SMARTPORT_MIN_A, SMARTPORT_MAX_A,
             amps_to_watt(SMARTPORT_MIN_A), amps_to_watt(SMARTPORT_MAX_A),
             SMARTPORT_VOLTAGE)
    log.info("  Comandi:   %s/cmd/smart_port[_a|_w]  |  raw %s",
             MQTT_PREFIX, "abilitato" if ALLOW_RAW_COMMAND else "disabilitato")
    log.info("=" * 55)


def poll_once(ser: serial.Serial) -> dict:
    """Esegue un ciclo di lettura completo (C0 + C1) e ritorna i dati decodificati."""
    fc0 = read_frame(ser, CMD_C0, 0xC0)
    time.sleep(0.1)
    fc1 = read_frame(ser, CMD_C1, 0xC1)

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
