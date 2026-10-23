"""
Test della lettura dei parametri e della mappa ricavata dall'app TBBLink.

I modelli di frame qui sotto sono quelli trovati nel plugin KinergierPro
dell'app ufficiale, con l'indirizzo del dispositivo (0x11) al posto dello zero
che l'app riempie a runtime. Il formato della *risposta* non e' documentato:
i test fissano le due forme che il decodificatore accetta, non quella reale.

Esegui dalla radice del repository:

    python tests/test_protocollo.py
"""
import logging
import os
import sys
import types
from pathlib import Path

os.environ.update({
    "MQTT_PREFIX": "tbb/inverter",
    "LOG_LEVEL": "error",
    "ADDON_VERSION": "test",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tbb_inverter"))
import tbb_reader as T

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  -> ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


def crc_ok(frame):
    crc = T.crc16_modbus(frame[:-2])
    return frame[-2] == crc & 0xFF and frame[-1] == crc >> 8


# --------------------------------------------------- frame di lettura
# Intestazioni dei blocchi letti dall'app (senza CRC), indirizzo gia' a 0x11.
MODELLI_APP = {
    (0x03, 0x0000, 100): "7E FF 11 03 03 0C 00 00 00 64",
    (0x03, 0x0065, 78):  "7E FF 11 03 03 0C 00 65 00 4E",
    (0x03, 0x00CA, 51):  "7E FF 11 03 03 0C 00 CA 00 33",
    (0x33, 0x0000, 100): "7E FF 11 03 33 0C 00 00 00 64",
    (0x33, 0x0064, 100): "7E FF 11 03 33 0C 00 64 00 64",
    (0x33, 0x00D0, 31):  "7E FF 11 03 33 0C 00 D0 00 1F",
}
for (cmd, reg, n), atteso in MODELLI_APP.items():
    f = T.build_read_frame(cmd, reg, n)
    check(f"lettura {cmd:#04x}/{reg:#06x} x{n} coincide con il modello dell'app",
          f[:10] == bytes.fromhex(atteso) and len(f) == 12 and crc_ok(f), f.hex(" ").upper())

check("i blocchi diagnostici sono esattamente quelli dell'app",
      set(T.PARAM_BLOCKS) == set(MODELLI_APP), T.PARAM_BLOCKS)

# I due frame di lettura che usiamo gia' devono restare compatibili con lo schema.
check("lo schema riproduce anche il frame C0 gia' in uso",
      T.CMD_C0[:6] == bytes([0x7E, 0xFF, 0x11, 0x03, 0xC0, 0x08]) and crc_ok(T.CMD_C0))


# --------------------------------------------------- decodifica risposta
def risposta(cmd, valori, eco=None):
    """Risposta sintetica: 7E 11 FF 03 cmd LEN [eco reg,count] dati CRC."""
    dati = b"".join(v.to_bytes(2, "big") for v in valori)
    if eco is not None:
        dati = eco[0].to_bytes(2, "big") + eco[1].to_bytes(2, "big") + dati
    corpo = bytes([0x7E, 0x11, 0xFF, 0x03, cmd, 6 + len(dati) + 2]) + dati
    crc = T.crc16_modbus(corpo)
    return corpo + bytes([crc & 0xFF, crc >> 8])


r = risposta(0x03, [16, 1, 65535])
check("decodifica i dati subito dopo l'intestazione",
      T.decode_registers(r, 3) == [16, 1, 65535], T.decode_registers(r, 3))
r = risposta(0x03, [16, 1], eco=(0x5E, 2))
check("decodifica i dati preceduti dall'eco di registro e quantita'",
      T.decode_registers(r, 2) == [16, 1], T.decode_registers(r, 2))
check("una lunghezza incoerente non produce valori inventati",
      T.decode_registers(risposta(0x03, [1, 2, 3]), 2) is None)


# --------------------------------------------------- read_registers
class Linea:
    """Seriale finta: risponde alle letture con i valori del dizionario `regs`."""
    is_open = True

    def __init__(self, regs=None, guasta=None):
        self.regs, self.guasta = regs or {}, guasta
        self.out, self.scritto = b"", bytearray()

    @property
    def in_waiting(self):
        return len(self.out)

    def read(self, n):
        b, self.out = self.out[:n], self.out[n:]
        return b

    def write(self, b):
        self.scritto += b
        cmd, reg, n = b[4], b[6] << 8 | b[7], b[8] << 8 | b[9]
        if b[3] == 0x03 and len(b) == 12:
            r = risposta(cmd, [self.regs.get((cmd, reg + i), 0) for i in range(n)])
            if self.guasta == "crc":
                r = r[:-1] + bytes([r[-1] ^ 0xFF])
            elif self.guasta == "cmd":
                r = r[:4] + bytes([0xC0]) + r[5:]
            self.out = r
        else:   # scrittura: eco con indirizzi scambiati
            corpo = bytes([0x7E, 0x11, 0xFF]) + bytes(b[3:10])
            crc = T.crc16_modbus(corpo)
            self.out = corpo + bytes([crc & 0xFF, crc >> 8])
        return len(b)

    def reset_input_buffer(self):
        pass

    def flush(self):
        pass


T.time.sleep = lambda *a, **k: None
T.mqtt_client = types.SimpleNamespace(publish=lambda *a, **k: types.SimpleNamespace(rc=0))

T.ser_global = Linea({(0x03, 0x005E): 16, (0x03, 0x005F): 7})
check("legge i registri richiesti", T.read_registers(0x03, 0x005E, 2) == [16, 7],
      T.read_registers(0x03, 0x005E, 2))
T.ser_global = Linea(guasta="crc")
check("una risposta con CRC errato viene scartata", T.read_registers(0x03, 0x005E, 1) is None)
T.ser_global = Linea(guasta="cmd")
check("una risposta a un altro comando viene scartata", T.read_registers(0x03, 0x005E, 1) is None)
T.ser_global = None
check("senza porta seriale la lettura ritorna None", T.read_registers(0x03, 0x005E, 1) is None)


# --------------------------------------------------- rilettura dopo la scrittura
class Raccolta(logging.Handler):
    def __init__(self):
        super().__init__()
        self.righe = []

    def emit(self, record):
        self.righe.append((record.levelno, record.getMessage()))


racc = Raccolta()
T.log.addHandler(racc)
T.log.setLevel(logging.DEBUG)

linea = Linea({(0x03, 0x005E): 16, (0x03, 0x001F): 1})
T.ser_global = linea
check("la rilettura conferma un valore memorizzato", T.verifica_smartport(16) == 16)
check("la rilettura riporta la modalita' SmartPort per nome",
      any("Smart Gen" in m for _, m in racc.righe), racc.righe[-1:])

racc.righe.clear()
check("una rilettura diversa dal valore scritto viene restituita", T.verifica_smartport(20) == 16)
check("...e segnalata come avviso",
      any(lv == logging.WARNING and "invece di 20" in m for lv, m in racc.righe), racc.righe)

# cmd_smart_port: una scrittura, poi due letture (corrente e modalita')
linea = Linea({(0x03, 0x005E): 12, (0x03, 0x001F): 0})
T.ser_global = linea
T.cmd_smart_port(12)
tx = bytes(linea.scritto)
frames = [tx[i:i + 12] for i in range(0, len(tx), 12)]
tipi = [(f[3], f[4], f[6] << 8 | f[7]) for f in frames]
check("cmd_smart_port: scrive 0x005E e poi rilegge corrente e modalita'",
      tipi == [(0x06, 0x06, 0x005E), (0x03, 0x03, 0x005E), (0x03, 0x03, 0x001F)],
      [f"{a:#04x}/{b:#04x}/{c:#06x}" for a, b, c in tipi])
check("cmd_smart_port non tocca piu' i ritardi 0x0073/0x0074",
      not any(c in (0x0073, 0x0074) for _, _, c in tipi))


# --------------------------------------------------- mappa dei parametri
A, B = T.BANK_A_READ, T.BANK_B_READ
check("0x005E (banco A) e' la corrente massima del generatore",
      T.PARAM_NAMES[(A, 0x005E)][0] == "Edt_MaxAlternatorCurrent")
check("0x001F (banco A) e' la modalita' SmartPort",
      T.PARAM_NAMES[(A, 0x001F)][0] == "Cbo_ACFlexMode")
check("0x0073/0x0074 (banco B) sono i ritardi di commutazione, non uno sblocco",
      T.PARAM_NAMES[(B, 0x0073)][0] == "Edt_BatToUtilityDelay"
      and T.PARAM_NAMES[(B, 0x0074)][0] == "Edt_UtilityToBatDelay")
check("ogni voce della mappa appartiene a uno dei due banchi",
      all(c in (A, B) for c, _ in T.PARAM_NAMES))
check("le unita' dichiarate sono fra quelle previste",
      {u for _, _, u in T.PARAM_NAMES.values()} <= {"", "A", "%", "mV"})

# dump completo su una linea che risponde a tutto
T.ser_global = Linea({(0x33, 0x0073): 10, (0x33, 0x0074): 10, (0x03, 0x005E): 16})
racc.righe.clear()
check("il dump legge tutti e sei i blocchi", T.dump_parameters() == 6)
check("il dump riporta i ritardi per nome",
      any("0x0073" in m and "batteria -> rete" in m for _, m in racc.righe))
check("il dump non scrive nulla",
      all(T.ser_global.scritto[i + 3] == 0x03 for i in range(0, len(T.ser_global.scritto), 12)))

# --------------------------------------------------- comandi batteria
class Pubblicati:
    def __init__(self):
        self.ultimi = {}

    def publish(self, topic, payload=None, retain=False, **k):
        self.ultimi[topic] = payload
        return types.SimpleNamespace(rc=0)


def scritture(linea):
    tx = bytes(linea.scritto)
    return [tx[i:i + 12] for i in range(0, len(tx), 12) if tx[i + 3] == 0x06]


pub = Pubblicati()
T.mqtt_client = pub
for attiva, atteso in ((True, "7E FF 11 06 00 0C 03 F3 00 01"), (False, "7E FF 11 06 00 0C 03 F3 00 00")):
    T.ser_global = Linea()
    ok = T.cmd_full_charge(attiva)
    w = scritture(T.ser_global)
    check(f"carica completa {'ON' if attiva else 'OFF'}: frame identico a quello dell'app",
          ok and len(w) == 1 and w[0][:10] == bytes.fromhex(atteso) and crc_ok(w[0]),
          [x.hex(" ").upper() for x in w])
    check(f"carica completa {'ON' if attiva else 'OFF'}: stato pubblicato",
          pub.ultimi.get("tbb/inverter/bat_full_charge") == ("ON" if attiva else "OFF"))

T.ser_global = Linea({(0x33, 0x0072): 25})
ok = T.cmd_reserved_capacity(25)
w = scritture(T.ser_global)
check("capacita' riservata: scrive il banco B, registro 0x0072",
      ok and len(w) == 1 and w[0][:10] == bytes.fromhex("7E FF 11 06 66 0C 00 72 00 19"),
      [x.hex(" ").upper() for x in w])
check("capacita' riservata: pubblica il valore riletto",
      pub.ultimi.get("tbb/inverter/bat_reserved_capacity") == 25)

T.ser_global = Linea({(0x33, 0x0072): 30})       # l'inverter non ha memorizzato 25
racc.righe.clear()
T.cmd_reserved_capacity(25)
check("capacita' riservata: se la rilettura differisce pubblica il valore vero",
      pub.ultimi.get("tbb/inverter/bat_reserved_capacity") == 30)
check("...e lo segnala", any(lv == logging.WARNING for lv, _ in racc.righe))

for cattivo in (-1, 14, 81, 101, 20.5, "30"):
    T.ser_global = Linea()
    check(f"capacita' riservata {cattivo!r} rifiutata senza trasmettere",
          T.cmd_reserved_capacity(cattivo) is False and not T.ser_global.scritto)

# La regola dell'app: la riserva deve superare l'avviso di SOC basso (banco A 0x0091).
T.ser_global = Linea({(0x03, 0x0091): 20, (0x33, 0x0072): 21})
check("con l'avviso SOC a 20 %, una riserva di 20 % viene rifiutata",
      T.cmd_reserved_capacity(20) is False and not scritture(T.ser_global))
check("...e una di 21 % accettata",
      T.cmd_reserved_capacity(21) is True and len(scritture(T.ser_global)) == 1)
T.ser_global = Linea({(0x03, 0x0091): 8, (0x33, 0x0072): 15})
check("con l'avviso SOC a 8 % (il valore reale) il minimo resta 15 %",
      T.reserved_capacity_min() == 15 and T.cmd_reserved_capacity(15) is True)
T.ser_global = None
check("senza lettura dell'avviso vale il minimo assoluto di 15 %", T.reserved_capacity_min() == 15)


# --------------------------------------------------- eccezione di scrittura
class Rifiuta(Linea):
    """Risponde alle scritture con un'eccezione 0x86, come previsto dall'app."""

    def write(self, b):
        self.scritto += b
        corpo = bytes([0x7E, 0x11, 0xFF, 0x86]) + bytes(b[4:10])
        crc = T.crc16_modbus(corpo)
        self.out = corpo + bytes([crc & 0xFF, crc >> 8])
        return len(b)


T.ser_global = Rifiuta()
racc.righe.clear()
check("una risposta di eccezione 0x86 fa fallire la scrittura",
      T.send_write_sequence([T.build_frame(0x66, 0x0072, 20)]) is False)
check("...e viene segnalata", any("rifiutato" in m for _, m in racc.righe))
pub.ultimi.clear()
T.cmd_full_charge(True)
check("una carica completa rifiutata non pubblica uno stato falso",
      "tbb/inverter/bat_full_charge" not in pub.ultimi)


# --------------------------------------------------- rilettura periodica
pub.ultimi.clear()
T.ser_global = Linea({(0x03, 0x005E): 18, (0x03, 0x001F): 1, (0x33, 0x0072): 40,
                      (0x33, 0x005C): 5, (0x03, 0x0056): 14})
check("la rilettura periodica legge i cinque parametri", T.refresh_parameters() == 5)
check("...compresa la corrente massima da rete",
      pub.ultimi.get("tbb/inverter/grid_current_max") == 14, pub.ultimi)
check("...e pubblica SmartPort, modalita', capacita' riservata e carica da generatore",
      pub.ultimi.get("tbb/inverter/smart_port_a") == 18
      and pub.ultimi.get("tbb/inverter/smart_port_mode") == "Smart Gen"
      and pub.ultimi.get("tbb/inverter/bat_reserved_capacity") == 40
      and pub.ultimi.get("tbb/inverter/gen_charge_current") == 5, pub.ultimi)
check("la rilettura periodica non scrive nulla", not scritture(T.ser_global))

# --------------------------------------------------- comandi via MQTT
def comando(topic, payload, linea=None):
    T.ser_global = linea or Linea({(0x33, 0x0072): 25})
    cli = Pubblicati()
    T.mqtt_client = cli
    T.on_message(cli, None, types.SimpleNamespace(
        topic=f"tbb/inverter/{topic}", payload=str(payload).encode()))
    return cli.ultimi.get(f"tbb/inverter/{topic}/status"), scritture(T.ser_global)


for payload, esito in (("ON", "OK"), ("off", "OK"), ("1", "OK"), ("forse", "ERRORE")):
    st, w = comando("cmd/bat_full_charge", payload)
    check(f"cmd/bat_full_charge = {payload!r} -> {esito}",
          st == esito and (len(w) == 1) == (esito == "OK"), (st, len(w)))
for payload, esito in (("25", "OK"), ("25.0", "OK"), ("25.5", "ERRORE"),
                       ("nan", "ERRORE"), ("abc", "ERRORE"), ("150", "ERRORE"), ("10", "ERRORE")):
    st, w = comando("cmd/bat_reserved_capacity", payload)
    check(f"cmd/bat_reserved_capacity = {payload!r} -> {esito}",
          st == esito and (len(w) == 1) == (esito == "OK"), (st, len(w)))

sottoscritti = []
T.on_connect(types.SimpleNamespace(subscribe=lambda t: sottoscritti.extend(x for x, _ in t),
                                   publish=lambda *a, **k: types.SimpleNamespace(rc=0)),
             None, None, 0)
check("i nuovi comandi sono sottoscritti",
      {"tbb/inverter/cmd/bat_full_charge", "tbb/inverter/cmd/bat_reserved_capacity"} <= set(sottoscritti),
      sottoscritti)

T.log.removeHandler(racc)
T.ser_global = None
T.mqtt_client = None

print()
print("TUTTI I TEST PASSATI" if not fails else "FALLITI: " + ", ".join(fails))
sys.exit(1 if fails else 0)
