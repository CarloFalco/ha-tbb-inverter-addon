"""
Banco di prova per tbb_reader.py — nessun hardware, nessun broker.

Esegui dalla radice del repository:

    python tests/test_reader.py
"""
import json
import os
import random
import sys
import types
from pathlib import Path

os.environ.update({
    "MQTT_PREFIX": "tbb/inverter",
    "MQTT_DISCOVERY": "true",
    "ALLOW_RAW_COMMAND": "false",
    "LOG_LEVEL": "warning",
    "ADDON_VERSION": "test",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tbb_inverter"))
import tbb_reader as T

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  -> ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- CRC
for label, hexs in [("C0", "7E FF 11 03 C0 08 BA EB"),
                    ("C1", "7E FF 11 03 C1 08 BB 7B"),
                    ("write", "7E FF 11 06 06 0C 00 5E 00 28 81 46")]:
    b = bytes(int(x, 16) for x in hexs.split())
    check(f"crc_frame_length riconosce il frame {label}",
          T.crc_frame_length(b) == len(b), T.crc_frame_length(b))

# frame + spazzatura in coda: il byte 5 (lunghezza dichiarata) disambigua i
# falsi positivi del CRC, che dopo un frame valido sono strutturalmente possibili
noisy = bytes(int(x, 16) for x in "7E FF 11 03 C0 08 BA EB".split()) + bytes([0x00, 0x11, 0x22, 0x33])
check("crc_frame_length usa la lunghezza dichiarata contro i falsi positivi",
      T.crc_frame_length(noisy) == 8, T.crc_frame_length(noisy))

# stesso caso ma con lunghezza dichiarata non plausibile: si ripiega sul match
# piu' lungo, che al peggio include qualche byte in eccesso (innocuo)
odd = bytearray(noisy)
odd[5] = 0xFF
check("senza lunghezza dichiarata valida si prende il match piu' lungo",
      T.crc_frame_length(bytes(odd)) is None or T.crc_frame_length(bytes(odd)) >= 8,
      T.crc_frame_length(bytes(odd)))

# frame corrotto: nessuna lunghezza valida
bad = bytearray(int(x, 16) for x in "7E FF 11 03 C0 08 BA EB".split())
bad[3] ^= 0xFF
check("crc_frame_length rifiuta un frame corrotto", T.crc_frame_length(bytes(bad)) is None)

# il CRC usa una tabella precalcolata: deve restare identico alla definizione
# bit-a-bit dello standard MODBUS
def _crc_riferimento(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


random.seed(20260822)
diverse = sum(
    1 for _ in range(5000)
    if T.crc16_modbus(d := bytes(random.getrandbits(8)
                                 for _ in range(random.randint(0, 64))))
    != _crc_riferimento(d)
)
check("il CRC a tabella coincide con quello bit-a-bit (5000 casi casuali)",
      diverse == 0, f"{diverse} differenze")

check("build_frame produce il frame documentato",
      T.build_frame(0x06, 0x005E, 40).hex(" ").upper() == "7E FF 11 06 06 0C 00 5E 00 28 81 46",
      T.build_frame(0x06, 0x005E, 40).hex(" ").upper())


# ---------------------------------------------------------------- frame finto
def make_c0():
    f = bytearray(198)
    f[0:6] = bytes([0x7E, 0xFF, 0x11, 0x03, 0xC0, 0x9C])
    f[14:16] = (1116).to_bytes(2, "big")        # ac_out_w
    f[16:18] = (2301).to_bytes(2, "big")        # ac_out2_v -> 230.1
    f[22:24] = (2310).to_bytes(2, "big")        # ac_in_v   -> 231.0
    f[24:26] = (2302).to_bytes(2, "big")        # ac_out_v  -> 230.2
    f[30:32] = (-12 & 0xFFFF).to_bytes(2, "big")  # ac_in_i -> -0.12
    f[36:38] = (485).to_bytes(2, "big")         # ac_out_i  -> 4.85
    f[38:40] = (100).to_bytes(2, "big")         # ac_out2_i -> 1.00
    f[40:42] = (5001).to_bytes(2, "big")        # ac_freq   -> 50.01
    f[50:52] = (53412).to_bytes(2, "big")       # bat_v     -> 53.412
    f[52:54] = (142).to_bytes(2, "big")         # bat_i     -> 14.2
    f[57], f[59], f[61], f[67] = 44, 38, 35, 21
    f[99] = 14
    f[155] = 87
    crc = T.crc16_modbus(bytes(f[:196]))
    f[196], f[197] = crc & 0xFF, (crc >> 8) & 0xFF
    return bytes(f)


c0 = make_c0()
check("il frame di prova ha un CRC coerente", T.crc_frame_length(c0) == 198, T.crc_frame_length(c0))

d = T.decode_c0(c0)
expected = {"ac_out_w": 1116, "ac_out_v": 230.2, "ac_out_i": 4.85, "ac_in_v": 231.0,
            "ac_in_i": -0.12, "ac_freq": 50.01, "bat_v": 53.412, "bat_i": 14.2,
            "soc": 87, "load_pct": 14, "t_heatsink": 38, "t_transformer": 44,
            "t_inverter": 35, "t_bat": 21}
for k, v in expected.items():
    check(f"decode_c0 {k} = {v}", abs(d[k] - v) < 1e-6 if isinstance(v, float) else d[k] == v,
          d.get(k))

# frame troncato: le chiavi mancanti NON devono comparire (niente zeri finti)
short = T.decode_c0(c0[:60])
check("frame corto: nessuno zero fittizio per soc", "soc" not in short, sorted(short))
check("frame corto: i campi presenti restano corretti", short.get("bat_v") == 53.412)


# ---------------------------------------------------------------- canali calcolati
der = T.apply_derived(T.decode_c0(c0))
check("bat_w = tensione x corrente batteria",
      abs(der["bat_w"] - round(53.412 * 14.2, 1)) < 1e-9, der.get("bat_w"))
check("bat_w e' positiva quando la batteria carica", der["bat_w"] > 0)
check("ac_in_w = tensione x corrente di rete",
      der["ac_in_w"] == round(231.0 * -0.12), der.get("ac_in_w"))
check("ac_in_w e' negativa quando si preleva dalla rete", der["ac_in_w"] < 0)
check("ac_out2_w = tensione x corrente uscita 2",
      der["ac_out2_w"] == round(230.1 * 1.00), der.get("ac_out2_w"))
check("ac_out_tot_w somma le due uscite",
      der["ac_out_tot_w"] == der["ac_out_w"] + der["ac_out2_w"], der.get("ac_out_tot_w"))
check("bat_status In carica", der["bat_status"] == "In carica")

scarica = T.apply_derived(T.decode_c0(c0[:52] + (-142 & 0xFFFF).to_bytes(2, "big") + c0[54:]))
check("bat_status In scarica", scarica["bat_status"] == "In scarica")
check("bat_w e' negativa in scarica", scarica["bat_w"] < 0, scarica.get("bat_w"))

riposo = T.apply_derived({"bat_v": 53.4, "bat_i": 0.0})
check("bat_status A riposo con corrente nulla", riposo["bat_status"] == "A riposo")
check("bat_w = 0 a riposo", riposo["bat_w"] == 0, riposo.get("bat_w"))

# dipendenze mancanti -> il canale non viene inventato
check("nessun bat_w senza la corrente di batteria",
      "bat_w" not in T.apply_derived({"bat_v": 53.4}))
check("nessun ac_out_tot_w con una sola uscita nota",
      "ac_out_tot_w" not in T.apply_derived({"ac_out_w": 1116}))
check("un frame corto non produce potenze fittizie",
      "bat_w" not in T.apply_derived(T.decode_c0(c0[:40])), )
check("apply_derived su un dizionario vuoto non solleva",
      T.apply_derived({}) == {})

# ac_out_tot_w dipende da ac_out2_w, a sua volta calcolato: l'ordine deve reggere
catena = T.apply_derived({"ac_out_w": 1000, "ac_out2_v": 230.0, "ac_out2_i": 2.0})
check("i canali calcolati possono dipendere l'uno dall'altro",
      catena["ac_out_tot_w"] == 1000 + catena["ac_out2_w"], catena.get("ac_out_tot_w"))

# ogni canale calcolato deve avere un'entita' in Home Assistant
sensor_keys = {row[0] for row in T.SENSORS}
mancanti = [k for k, _, _ in T.DERIVED if k not in sensor_keys]
check("ogni canale calcolato ha la sua entita'", not mancanti, mancanti)


# ---------------------------------------------------------------- seriale finta
class FakeSerial:
    def __init__(self, response=b"", fail=False):
        self.response, self.fail, self.written = response, fail, bytearray()
        self.is_open, self._served = True, False

    @property
    def in_waiting(self):
        return 0 if self._served else len(self.response)

    def read(self, n):
        self._served = True
        return self.response[:n]

    def write(self, b):
        if self.fail:
            raise T.serial.SerialException("dispositivo scollegato")
        self.written += b
        return len(b)

    def reset_input_buffer(self):
        pass

    def close(self):
        self.is_open = False


fs = FakeSerial(b"\x00\x00" + c0)          # rumore prima del delimitatore
got = T.read_frame(fs, T.CMD_C0, 0xC0)
check("read_frame trova 0x7E dopo il rumore e valida il CRC", got == c0, len(got or b""))
check("read_frame ha inviato il comando C0", bytes(fs.written) == T.CMD_C0)

check("read_frame scarta un comando inatteso",
      T.read_frame(FakeSerial(c0), T.CMD_C1, 0xC1) is None)
check("read_frame gestisce l'assenza di risposta",
      T.read_frame(FakeSerial(b""), T.CMD_C0, 0xC0) is None)

T.STRICT_CRC = True
corrupt = bytearray(c0)
corrupt[70] ^= 0xFF
check("strict_crc scarta il frame corrotto",
      T.read_frame(FakeSerial(bytes(corrupt)), T.CMD_C0, 0xC0) is None)
T.STRICT_CRC = False
check("senza strict_crc il frame corrotto passa comunque",
      T.read_frame(FakeSerial(bytes(corrupt)), T.CMD_C0, 0xC0) is not None)


# ---------------------------------------------------------------- MQTT finto
class FakeClient:
    def __init__(self):
        self.published, self.subscribed = [], []
        self._connected = True

    def publish(self, topic, payload=None, retain=False, **kw):
        self.published.append((topic, payload, retain))
        return types.SimpleNamespace(rc=0)

    def subscribe(self, topics):
        self.subscribed.extend(topics)

    def is_connected(self):
        return self._connected


mc = FakeClient()
T.mqtt_client = mc
T.publish(mc, {"pv_w": 1817, "soc": 87})
topics = [t for t, _, _ in mc.published]
check("publish invia un topic per chiave", "tbb/inverter/pv_w" in topics and "tbb/inverter/soc" in topics)
check("publish invia il JSON aggregato", "tbb/inverter/stato" in topics)
check("publish non inventa chiavi assenti", "tbb/inverter/bat_v" not in topics, topics)

payload = json.loads([p for t, p, _ in mc.published if t == "tbb/inverter/stato"][0])
check("il JSON aggregato contiene solo le chiavi lette", set(payload) == {"pv_w", "soc"})

# ---------------------------------------------------------------- discovery
items = T.discovery_payloads()
check("discovery genera un'entita' per sensore + lo slider", len(items) == len(T.SENSORS) + 1, len(items))
check("i topic di discovery sono unici", len({t for t, _ in items}) == len(items))
check("gli unique_id sono unici", len({p["unique_id"] for _, p in items}) == len(items))
for topic, p in items:
    json.dumps(p)  # deve essere serializzabile
    assert topic.startswith("homeassistant/")
check("ogni payload di discovery e' JSON valido e sotto il prefisso corretto", True)

number = [p for t, p in items if "/number/" in t][0]
check("lo slider SmartPort scrive sul topic di comando",
      number["command_topic"] == "tbb/inverter/cmd/smart_port")
check("ogni entita' ha l'availability topic",
      all(p["availability_topic"] == "tbb/inverter/availability" for _, p in items))
check("ogni entita' appartiene allo stesso dispositivo",
      len({p["device"]["identifiers"][0] for _, p in items}) == 1)

sensor_pv = [p for t, p in items if t.endswith("/pv_w/config")][0]
check("il sensore potenza FV ha device_class/state_class corretti",
      sensor_pv["device_class"] == "power" and sensor_pv["state_class"] == "measurement"
      and sensor_pv["unit_of_measurement"] == "W")
check("il sensore testuale bat_status non ha unita' o device_class",
      "unit_of_measurement" not in [p for t, p in items if t.endswith("/bat_status/config")][0])

mc2 = FakeClient()
T.publish_discovery(mc2, False)
check("discovery disabilitato rimuove le entita' (payload vuoto)",
      all(p == "" and r for _, p, r in mc2.published))

# ---------------------------------------------------------------- comandi
mc3 = FakeClient()
T.mqtt_client = mc3
T.ser_global = None   # nessuna seriale: i comandi devono fallire in modo pulito

msg = types.SimpleNamespace(topic="tbb/inverter/cmd/smart_port", payload=b"\xff\xfe non-utf8")
T.on_message(mc3, None, msg)   # non deve sollevare
check("payload non UTF-8 non fa crashare on_message",
      ("tbb/inverter/cmd/smart_port/status", "ERRORE") in [(t, p) for t, p, _ in mc3.published])

mc4 = FakeClient()
T.on_message(mc4, None, types.SimpleNamespace(topic="tbb/inverter/cmd/raw", payload=b"7E FF"))
check("cmd/raw e' rifiutato quando allow_raw_command e' disattivo",
      ("tbb/inverter/cmd/raw/status", "ERRORE") in [(t, p) for t, p, _ in mc4.published])

check("cmd_smart_port rifiuta valori fuori scala", T.cmd_smart_port(150) is False)

T.ser_global = FakeSerial(b"")
T.ALLOW_RAW_COMMAND = True
check("cmd_raw rifiuta hex non valido", T.cmd_raw("ZZ 12") is False)
check("cmd_raw rifiuta una stringa vuota", T.cmd_raw("   ") is False)
check("cmd_raw accetta un frame valido", T.cmd_raw("7E FF 11 03 C0 08 BA EB") is True)

T.ser_global = FakeSerial(b"", fail=True)
check("errore seriale durante la scrittura -> False, nessuna eccezione",
      T.send_write_sequence([T.CMD_C0]) is False)

# ---------------------------------------------------------------- availability
mc5 = FakeClient()
T._available = None
T.set_available(mc5, True)
T.set_available(mc5, True)
check("availability pubblicata una sola volta se non cambia",
      [(t, p) for t, p, _ in mc5.published] == [("tbb/inverter/availability", "online")])
T.set_available(mc5, False)
check("availability aggiornata al cambio di stato",
      mc5.published[-1][:2] == ("tbb/inverter/availability", "offline"))


class DeadClient(FakeClient):
    def publish(self, *a, **kw):
        return types.SimpleNamespace(rc=4)   # MQTT_ERR_NO_CONN


T._available = None
dead = DeadClient()
T.set_available(dead, True)
check("se il broker non risponde lo stato non viene memorizzato", T._available is None)

# ---------------------------------------------------------------- formattazione
check("_fmt sostituisce i valori mancanti", T._fmt(None, "6.1f") == "    --", repr(T._fmt(None, "6.1f")))
check("_fmt formatta i valori presenti", T._fmt(53.4123, "6.3f") == "53.412")
T.log_data({"pv_w": 1817, "soc": 87}, 1)   # non deve sollevare con dati parziali
check("log_data regge i dati parziali", True)

print()
print(f"{'TUTTI I TEST PASSATI' if not fails else 'FALLITI: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
