"""
TBB RiiO Sun II - RS485 Reader v1.0 (Home Assistant Add-on)
====================================================================
Inverter: RiiO Sun II 8.0S, 48V-8000VA

Connessione:
  RJ45 pin 3 (verde/bianco) -> A+ adattatore RS485
  RJ45 pin 6 (verde)        -> B- adattatore RS485
  RJ45 pin 7 (+12V)         -> NON COLLEGARE
  RJ45 pin 8 (GND)          -> GND adattatore (opzionale)

Comandi MQTT in ingresso (topic <prefix>/cmd/...):
  <prefix>/cmd/smart_port   <- valore 0-100 (%)
  <prefix>/cmd/raw          <- frame hex es. "7E FF 11 06 06 0C 00 5E 00 28 81 46"

Configurazione: letta da variabili d'ambiente (impostate da run.sh a partire
dalle opzioni dell'add-on in /data/options.json).
"""

import os
import serial
import threading
import time
import struct
import json
import paho.mqtt.client as mqtt

# ----------------------------------------------------------------
# SERIALE
PORT          = os.environ.get("SERIAL_PORT", "/dev/ttyUSB0")
BAUD          = int(os.environ.get("BAUD", "9600"))
TIMEOUT       = 2.0
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))  # secondi tra un ciclo di lettura e l'altro

# MQTT
MQTT_HOST     = os.environ.get("MQTT_HOST", "core-mosquitto")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER     = os.environ.get("MQTT_USER", "")
MQTT_PASS     = os.environ.get("MQTT_PASS", "")
MQTT_PREFIX   = os.environ.get("MQTT_PREFIX", "tbb/inverter")
MQTT_TIMEOUT  = 10
# ----------------------------------------------------------------

CMD_C0 = bytes([0x7E, 0xFF, 0x11, 0x03, 0xC0, 0x08, 0xBA, 0xEB])
CMD_C1 = bytes([0x7E, 0xFF, 0x11, 0x03, 0xC1, 0x08, 0xBB, 0x7B])

# Variabile globale per la porta seriale (usata anche dai callback MQTT)
ser_global = None
ser_lock   = threading.Lock()


# ================================================================
# CRC e costruzione frame
# ================================================================

def crc16_modbus(data: bytes) -> int:
    """CRC16/MODBUS: poly=0xA001, init=0xFFFF, little-endian."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


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


def send_write_sequence(frames: list[bytes], delay: float = 0.2) -> bool:
    """
    Invia una sequenza di frame di scrittura all'inverter.
    Ritorna True se tutti i frame sono stati inviati correttamente.
    """
    global ser_global
    if ser_global is None or not ser_global.is_open:
        print("  [!] Porta seriale non disponibile")
        return False

    with ser_lock:
        for frame in frames:
            try:
                ser_global.reset_input_buffer()
                ser_global.write(frame)
                print(f"  >> TX: {frame.hex(' ').upper()}")
                time.sleep(delay)
                # Leggi eventuale risposta (ACK)
                resp = ser_global.read(32)
                if resp:
                    print(f"  << RX: {resp.hex(' ').upper()}")
            except Exception as e:
                print(f"  [!] Errore invio frame: {e}")
                return False
    return True


# ================================================================
# Comandi inverter
# ================================================================

def cmd_smart_port(value: int) -> bool:
    """
    Imposta il valore SmartPort (registro 0x005E).
    value = percentuale 0-100
    Sequenza: sblocco reg 0x73, sblocco reg 0x74, scrittura reg 0x5E
    """
    if not 0 <= value <= 100:
        print(f"  [!] Valore SmartPort non valido: {value} (deve essere 0-100)")
        return False

    print(f"  Impostazione SmartPort = {value}%")
    frames = [
        build_frame(0x66, 0x0073, 0x000A),  # sblocco 1
        build_frame(0x66, 0x0074, 0x000A),  # sblocco 2
        build_frame(0x06, 0x005E, value),    # scrittura SmartPort
    ]
    return send_write_sequence(frames)


def cmd_raw(hex_string: str) -> bool:
    """
    Invia un frame raw specificato come stringa hex.
    Es: "7E FF 11 06 06 0C 00 5E 00 28 81 46"
    """
    try:
        frame = bytes([int(x, 16) for x in hex_string.strip().split()])
        print(f"  Invio frame raw: {frame.hex(' ').upper()}")
        return send_write_sequence([frame])
    except Exception as e:
        print(f"  [!] Frame raw non valido: {e}")
        return False


# ================================================================
# Lettura frame e decodifica
# ================================================================

def u16be(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def s16be(data: bytes, offset: int) -> int:
    v = u16be(data, offset)
    return v - 65536 if v >= 32768 else v


def read_frame(ser: serial.Serial, cmd: bytes, expected_cmd: int) -> bytes | None:
    with ser_lock:
        ser.reset_input_buffer()
        ser.write(cmd)
        time.sleep(0.15)
        raw = ser.read(256)
    if not raw:
        return None
    try:
        start = raw.index(0x7E)
    except ValueError:
        return None
    frame = raw[start:]
    if len(frame) < 8:
        return None
    if frame[4] != expected_cmd:
        return None
    return frame


def decode_c0(frame: bytes) -> dict:
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
        if "ac_out2_v" in d and "ac_out2_i" in d:
            d["ac_out2_w"]     = round(d["ac_out2_v"] * d["ac_out2_i"])
    except (IndexError, struct.error) as e:
        print(f"  [!] Errore decode C0: {e}")
    return d


def decode_c1(frame: bytes) -> dict:
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
    except (IndexError, struct.error) as e:
        print(f"  [!] Errore decode C1: {e}")
    return d


# ================================================================
# MQTT
# ================================================================

def publish(client: mqtt.Client, d0: dict, d1: dict):
    data = {}
    data.update({
        "ac_out_w":      d0.get("ac_out_w",      0),
        "ac_out_v":      d0.get("ac_out_v",      0),
        "ac_out_i":      d0.get("ac_out_i",      0),
        "ac_out2_w":     d0.get("ac_out2_w",     0),
        "ac_out2_v":     d0.get("ac_out2_v",     0),
        "ac_out2_i":     d0.get("ac_out2_i",     0),
        "ac_in_v":       d0.get("ac_in_v",       0),
        "ac_in_i":       d0.get("ac_in_i",       0),
        "ac_freq":       d0.get("ac_freq",        0),
        "bat_v":         d0.get("bat_v",          0),
        "bat_i":         d0.get("bat_i",          0),
        "soc":           d0.get("soc",            0),
        "t_heatsink":    d0.get("t_heatsink",     0),
        "t_transformer": d0.get("t_transformer",  0),
        "t_inverter":    d0.get("t_inverter",     0),
        "t_bat":         d0.get("t_bat",          0),
        "load_pct":      d0.get("load_pct",       0),
    })
    data.update({
        "pv_w":      d1.get("pv_w",      0),
        "pv_v":      d1.get("pv_v",      0),
        "mppt_i":    d1.get("mppt_i",    0),
        "mppt_temp": d1.get("mppt_temp", 0),
        "bat_v_bms": d1.get("bat_v_bms", 0),
    })
    for key, value in data.items():
        client.publish(f"{MQTT_PREFIX}/{key}", value, retain=True)
    client.publish(f"{MQTT_PREFIX}/stato", json.dumps(data), retain=True)


def on_message(client, userdata, msg):
    """Callback MQTT per i comandi in ingresso."""
    topic   = msg.topic
    payload = msg.payload.decode("utf-8").strip()
    print(f"\n  [CMD] topic={topic} payload={payload}")

    if topic == f"{MQTT_PREFIX}/cmd/smart_port":
        try:
            val = int(float(payload))
            ok = cmd_smart_port(val)
            status = "OK" if ok else "ERRORE"
            client.publish(f"{MQTT_PREFIX}/cmd/smart_port/status", status)
        except ValueError:
            print(f"  [!] Valore non valido: {payload}")

    elif topic == f"{MQTT_PREFIX}/cmd/raw":
        ok = cmd_raw(payload)
        status = "OK" if ok else "ERRORE"
        client.publish(f"{MQTT_PREFIX}/cmd/raw/status", status)


def print_data(d0: dict, d1: dict, cycle: int):
    bat_i   = d0.get("bat_i", 0)
    bat_dir = "scarica" if bat_i < 0 else "carica " if bat_i > 0 else "fermo  "
    ac_in_i = d0.get("ac_in_i", 0)
    ac_dir  = "rete->inv" if ac_in_i < 0 else "inv->rete"

    print(f"\n{'-'*55}")
    print(f"  Ciclo {cycle}  -  {time.strftime('%H:%M:%S')}")
    print(f"{'-'*55}")
    print(f"  PV:        {d1.get('pv_v',0):6.1f} V  "
          f"{d1.get('mppt_i',0):5.2f} A  "
          f"{d1.get('pv_w',0):5.0f} W  "
          f"(MPPT {d1.get('mppt_temp',0)}°C)")
    print(f"  AC Out:    {d0.get('ac_out_v',0):6.1f} V  "
          f"{d0.get('ac_out_i',0):5.2f} A  "
          f"{d0.get('ac_out_w',0):5.0f} W")
    print(f"  AC Out2:   {d0.get('ac_out2_v',0):6.1f} V  "
          f"{d0.get('ac_out2_i',0):5.2f} A  "
          f"{d0.get('ac_out2_w',0):5.0f} W")
    print(f"  AC In:     {d0.get('ac_in_v',0):6.1f} V  "
          f"{ac_in_i:+6.2f} A  ({ac_dir})")
    print(f"  Freq:      {d0.get('ac_freq',0):6.2f} Hz")
    print(f"  Batteria:  {d0.get('bat_v',0):6.3f} V  "
          f"{bat_i:+6.1f} A ({bat_dir})  "
          f"SOC {d0.get('soc','---'):3}%")
    print(f"  BAT BMS:   {d1.get('bat_v_bms',0):.3f} V")
    print(f"  Temp:      Heatsink {d0.get('t_heatsink','--'):3}°C  "
          f"Transformer {d0.get('t_transformer','--'):3}°C  "
          f"Inverter {d0.get('t_inverter','--'):3}°C  "
          f"BAT {d0.get('t_bat','--'):3}°C")
    print(f"  Carico:    {d0.get('load_pct','--'):3}%")


# ================================================================
# Main
# ================================================================

def main():
    global ser_global

    print("=" * 55)
    print("  TBB RiiO Sun II -- Reader v1.0 (Home Assistant Add-on)")
    print("=" * 55)
    print(f"  Porta:  {PORT}  Baud: {BAUD}")
    print(f"  MQTT:   {MQTT_HOST}:{MQTT_PORT}")
    print(f"  Prefix: {MQTT_PREFIX}")
    print(f"  Polling ogni {POLL_INTERVAL}s")
    print("=" * 55)
    print(f"  Comandi disponibili via MQTT:")
    print(f"    {MQTT_PREFIX}/cmd/smart_port  <- 0-100 (%)")
    print(f"    {MQTT_PREFIX}/cmd/raw         <- frame hex")
    print("=" * 55)

    # Connessione MQTT
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="tbb_inverter")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, MQTT_TIMEOUT)
        # Sottoscrivi ai topic di comando
        client.subscribe(f"{MQTT_PREFIX}/cmd/#")
        client.loop_start()
        print(f"  MQTT connesso a {MQTT_HOST}\n")
    except Exception as e:
        print(f"  [!] MQTT errore connessione: {e}")
        print("  Continuo senza MQTT...")

    # Connessione seriale
    try:
        ser_global = serial.Serial(
            port=PORT,
            baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=TIMEOUT,
        )
        print(f"  Porta {PORT} aperta!\n")
    except serial.SerialException as e:
        print(f"\n  [ERRORE] Impossibile aprire {PORT}: {e}")
        client.loop_stop()
        return

    cycle = 0
    try:
        while True:
            cycle += 1
            fc0 = read_frame(ser_global, CMD_C0, 0xC0)
            time.sleep(0.3)
            fc1 = read_frame(ser_global, CMD_C1, 0xC1)

            d0 = decode_c0(fc0) if fc0 else {}
            d1 = decode_c1(fc1) if fc1 else {}

            if d0 or d1:
                publish(client, d0, d1)
                print_data(d0, d1, cycle)
            else:
                print(f"  [!] Ciclo {cycle}: nessuna risposta")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n  Uscita.")
    finally:
        ser_global.close()
        client.loop_stop()
        client.disconnect()
        print("  Porta e MQTT chiusi.")


if __name__ == "__main__":
    main()
