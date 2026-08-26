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


# ---------------------------------------------------------------- SmartPort
# Il registro 0x005E accetta 0-100 e, sul RiiO Sun II, quel numero *sono* gli
# ampere: scrivere 20 imposta 20 A. Ampere e watt restano viste derivate, ma
# nella modalita' predefinita la conversione ampere->registro e' l'identita'.
# La 1.3.1 ci applicava un fattore 100/32 e mandava 16 A a fondo scala.
check("il registro 0 corrisponde a 0 A", T.register_to_amps(0) == 0,
      T.register_to_amps(0))
check("il registro contiene direttamente gli ampere",
      T.register_to_amps(100) == 100 and T.register_to_amps(50) == 50,
      (T.register_to_amps(100), T.register_to_amps(50)))
check("gli ampere tornano al registro corretto",
      T.amps_to_register(16) == 16, T.amps_to_register(16))
check("amps_to_register non esce mai da 0-100",
      T.amps_to_register(-999) == 0 and T.amps_to_register(9999) == 100)
check("watt = ampere x tensione nominale",
      T.amps_to_watt(10) == 10 * T.SMARTPORT_VOLTAGE, T.amps_to_watt(10))

# andata e ritorno su tutto l'intervallo utile dello slider in ampere
persi = [a for a in range(T.SMARTPORT_MIN_A, T.SMARTPORT_MAX_A + 1)
         if abs(T.register_to_amps(T.amps_to_register(a)) - a) > 0.5]
check("ogni ampere dello slider sopravvive all'andata e ritorno", not persi, persi)


class SmartCli:
    def __init__(self):
        self.pub = []

    def publish(self, t, p=None, retain=False, **k):
        self.pub.append((t, p))
        return types.SimpleNamespace(rc=0)


class OkSerial:
    """Seriale che accetta le scritture e non risponde nulla."""
    is_open = True

    def __init__(self, _=b""):
        self.written = bytearray()

    @property
    def in_waiting(self):
        return 0

    def read(self, n):
        return b""

    def write(self, b):
        self.written += b
        return len(b)

    def reset_input_buffer(self):
        pass

    def flush(self):
        pass


def scrivi(topic, payload):
    """Simula un comando MQTT e ritorna (esito, valore nel registro, stati)."""
    T.ser_global = OkSerial()
    cli = SmartCli()
    T.mqtt_client = cli
    T.on_message(cli, None, types.SimpleNamespace(
        topic=f"tbb/inverter/{topic}", payload=str(payload).encode()))
    stato = dict(cli.pub).get(f"tbb/inverter/{topic}/status")
    inviato = bytes(T.ser_global.written)
    reg = None
    for candidato in range(0, 101):
        if T.build_frame(0x06, 0x005E, candidato) in inviato:
            reg = candidato
            break
    return stato, reg, dict(cli.pub)


# LA REGRESSIONE: il topic grezzo deve scrivere il numero cosi' com'e'
for n in (0, 25, 40, 50, 75, 100):
    esito, reg, _ = scrivi("cmd/smart_port", n)
    check(f"cmd/smart_port = {n} scrive {n} nel registro (nessuna conversione)",
          esito == "OK" and reg == n, reg)

# Il registro contiene ampere: anche lo slider in A scrive il numero grezzo.
# La 1.3.1 ci metteva 50 (16 x 100/32), mandando 16 A a fondo scala.
esito, reg, stati = scrivi("cmd/smart_port_a", 16)
check("cmd/smart_port_a = 16 A scrive 16 nel registro", esito == "OK" and reg == 16, reg)
check("cmd/smart_port_a = 16 A non scrive piu' 50 (regressione 1.3.1)", reg != 50, reg)

esito, reg, _ = scrivi("cmd/smart_port_a", T.SMARTPORT_MAX_A)
check("la corrente massima scrive il proprio valore nel registro",
      reg == T.SMARTPORT_MAX_A, reg)

esito, reg, _ = scrivi("cmd/smart_port_w", 16 * T.SMARTPORT_VOLTAGE)
check("i watt corrispondenti a 16 A scrivono 16 nel registro", reg == 16, reg)

# le tre entita' restano coerenti dopo qualunque scrittura
for topic, valore in [("cmd/smart_port", 16), ("cmd/smart_port_a", 16),
                      ("cmd/smart_port_w", 16 * T.SMARTPORT_VOLTAGE)]:
    _, _, stati = scrivi(topic, valore)
    coerenti = (stati.get("tbb/inverter/smart_port") == 16
                and stati.get("tbb/inverter/smart_port_a") == 16
                and stati.get("tbb/inverter/smart_port_w") == 16 * T.SMARTPORT_VOLTAGE)
    check(f"{topic} aggiorna le tre entita' in modo coerente", coerenti,
          {k.rsplit('/', 1)[1]: v for k, v in stati.items() if "status" not in k})

# valori fuori scala: nessun byte deve raggiungere l'inverter
for topic, payload in [("cmd/smart_port", 150), ("cmd/smart_port", -5),
                       ("cmd/smart_port_a", 40), ("cmd/smart_port_a", 1),
                       ("cmd/smart_port_w", 99999)]:
    T.ser_global = OkSerial()
    cli = SmartCli()
    T.mqtt_client = cli
    T.on_message(cli, None, types.SimpleNamespace(
        topic=f"tbb/inverter/{topic}", payload=str(payload).encode()))
    check(f"{topic} = {payload} rifiutato senza toccare l'inverter",
          dict(cli.pub).get(f"tbb/inverter/{topic}/status") == "ERRORE"
          and len(T.ser_global.written) == 0, len(T.ser_global.written))

check("cmd_smart_port rifiuta oltre 100", T.cmd_smart_port(101) is False)
check("cmd_smart_port rifiuta sotto zero", T.cmd_smart_port(-1) is False)

# modalita' "percent": il registro torna a essere una percentuale, e le due
# convenzioni possibili sull'estremo inferiore restano entrambe rappresentabili.
_a0, _unita = T.SMARTPORT_A_AT_ZERO, T.SMARTPORT_REGISTER_UNIT
T.SMARTPORT_REGISTER_UNIT = "percent"
try:
    check("in percent, 16 A torna a scrivere 50 nel registro",
          T.amps_to_register(16) == 50, T.amps_to_register(16))
    T.SMARTPORT_A_AT_ZERO = 5
    check("con 0 % = 5 A, meta' registro da 18-19 A",
          round(T.register_to_amps(50)) in (18, 19), T.register_to_amps(50))
    check("con 0 % = 5 A, il minimo scrive 0 nel registro", T.amps_to_register(5) == 0)
finally:
    T.SMARTPORT_A_AT_ZERO, T.SMARTPORT_REGISTER_UNIT = _a0, _unita

check("in modalita' ampere la conversione e' l'identita'",
      T.amps_to_register(16) == 16 and T.register_to_amps(16) == 16)

# discovery: tre slider, stesso dispositivo. Lo slider grezzo non dichiara
# unita': in modalita' ampere chiamarlo "%" era meta' dell'equivoco.
sliders = {p["unique_id"].rsplit("_", 0)[0].replace(f"{T.DEVICE_ID}_", ""): p
           for t, p in T.discovery_payloads() if "/number/" in t}
check("discovery espone tre slider SmartPort", len(sliders) == 3, sorted(sliders))
check("lo slider grezzo copre 0-100",
      sliders["smart_port"]["min"] == 0 and sliders["smart_port"]["max"] == 100)
check("lo slider grezzo non dichiara un'unita' fuorviante",
      "unit_of_measurement" not in sliders["smart_port"],
      sliders["smart_port"].get("unit_of_measurement"))
check("lo slider in A copre l'intervallo utile",
      sliders["smart_port_a"]["min"] == T.SMARTPORT_MIN_A
      and sliders["smart_port_a"]["max"] == T.SMARTPORT_MAX_A)
check("lo slider in A e' etichettato in ampere",
      sliders["smart_port_a"]["unit_of_measurement"] == "A")
check("lo slider in W avanza di un ampere alla volta",
      sliders["smart_port_w"]["step"] == T.SMARTPORT_VOLTAGE)
check("i tre slider hanno topic di comando distinti",
      len({p["command_topic"] for p in sliders.values()}) == 3)

T.ser_global = None
T.mqtt_client = None


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

    def flush(self):
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
check("discovery genera un'entita' per sensore + i tre slider SmartPort",
      len(items) == len(T.SENSORS) + 3, len(items))
check("i topic di discovery sono unici", len({t for t, _ in items}) == len(items))
check("gli unique_id sono unici", len({p["unique_id"] for _, p in items}) == len(items))
for topic, p in items:
    json.dumps(p)  # deve essere serializzabile
    assert topic.startswith("homeassistant/")
check("ogni payload di discovery e' JSON valido e sotto il prefisso corretto", True)

numbers = {t.rsplit("/", 2)[1]: p for t, p in items if "/number/" in t}
check("lo slider SmartPort grezzo scrive sul proprio topic",
      numbers["smart_port"]["command_topic"] == "tbb/inverter/cmd/smart_port")
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

# --- carico su Home Assistant --------------------------------------------
# Le grandezze diagnostiche nascono spente: non producono stati e non finiscono
# nel recorder finche' l'utente non le abilita. Su un Raspberry Pi 3 la mole di
# scritture e' il vero costo dell'add-on, non la CPU.
sensori_diag = [p for t, p in items
                if "/sensor/" in t and p.get("entity_category") == "diagnostic"]
check("le grandezze diagnostiche esistono", len(sensori_diag) >= 5, len(sensori_diag))
check("ogni sensore diagnostico nasce disabilitato",
      all(p.get("enabled_by_default") is False for p in sensori_diag),
      [p["unique_id"] for p in sensori_diag if p.get("enabled_by_default") is not False])
check("la frequenza di uscita e' fra le diagnostiche",
      any(p["unique_id"].endswith("_ac_freq") for p in sensori_diag))
check("le grandezze operative restano abilitate",
      all("enabled_by_default" not in p for t, p in items
          if "/sensor/" in t and p.get("entity_category") != "diagnostic"))

# I tre slider SmartPort servono a governare l'impianto: non vanno spenti.
check("gli slider SmartPort restano abilitati",
      all("enabled_by_default" not in p for t, p in items if "/number/" in t))

check("l'intervallo di polling predefinito e' prudente per hardware modesto",
      T.POLL_INTERVAL >= 30, T.POLL_INTERVAL)

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
