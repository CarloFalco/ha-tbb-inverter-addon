"""
Test di stabilita' e robustezza per tbb_reader.py.

Coprono i modi in cui l'add-on potrebbe degradare o consumare risorse senza
limite: linea RS485 rumorosa, payload MQTT ostili, errori imprevisti nel ciclo
principale. Nessun hardware, nessun broker.

Esegui dalla radice del repository:

    python tests/test_stability.py
"""
import os
import sys
import threading
import time
import types
from pathlib import Path

os.environ.update({
    "MQTT_PREFIX": "tbb/inverter",
    "ALLOW_RAW_COMMAND": "true",
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


def run_with_timeout(fn, seconds):
    """Esegue fn in un thread. Ritorna (finito_in_tempo, risultato)."""
    box = {}
    th = threading.Thread(target=lambda: box.update(r=fn()), daemon=True)
    th.start()
    th.join(timeout=seconds)
    return (not th.is_alive()), box.get("r")


# ============================================================ linea rumorosa
class NoisyLine:
    """Bus RS485 flottante: in_waiting non torna mai a zero."""
    is_open = True

    def __init__(self, payload=b"\x55"):
        self.payload, self.letti, self.flush = payload, 0, 0

    @property
    def in_waiting(self):
        return 8

    def read(self, n):
        self.letti += n
        return self.payload * n

    def reset_input_buffer(self):
        self.flush += 1

    def write(self, b):
        return len(b)


noisy = NoisyLine()
ok, buf = run_with_timeout(lambda: T.read_response(noisy, max_wait=1.5), 5.0)
check("una linea che non tace mai non blocca la lettura", ok)
check("il buffer resta entro il tetto di sicurezza",
      ok and len(buf) <= T.MAX_RESPONSE_BYTES, len(buf) if ok else "bloccata")
check("in overflow l'ingresso viene svuotato per risincronizzare", noisy.flush >= 1)

# il lock non deve restare preso: altrimenti i comandi MQTT si bloccherebbero
ok2, _ = run_with_timeout(lambda: T.read_frame(NoisyLine(), T.CMD_C0, 0xC0), 5.0)
check("read_frame su linea rumorosa termina", ok2)
libero = T.ser_lock.acquire(blocking=False)
if libero:
    T.ser_lock.release()
check("ser_lock viene sempre rilasciato (nessun deadlock)", libero)


class SlowDrip:
    """Un byte alla volta, all'infinito: il limite di tempo deve valere lo stesso."""
    is_open = True

    def __init__(self):
        self.letti = 0

    @property
    def in_waiting(self):
        time.sleep(0.002)
        return 1

    def read(self, n):
        self.letti += n
        return b"\x00" * n

    def reset_input_buffer(self):
        pass


t0 = time.monotonic()
ok3, buf3 = run_with_timeout(lambda: T.read_response(SlowDrip(), max_wait=0.5), 4.0)
dur = time.monotonic() - t0
check("il limite di tempo vale anche a flusso lento", ok3)
check("la lettura non sfora di molto il limite", ok3 and dur < 2.0, f"{dur:.2f}s")


# ============================================================ percorso normale
class GoodLine:
    """Risposta valida, poi silenzio: il caso normale non deve regredire."""
    is_open = True

    def __init__(self, data):
        self.data, self.served = data, False

    @property
    def in_waiting(self):
        return 0 if self.served else len(self.data)

    def read(self, n):
        self.served = True
        return self.data[:n]

    def reset_input_buffer(self):
        self.served = False

    def write(self, b):
        return len(b)


def make_c0():
    f = bytearray(198)
    f[0:6] = bytes([0x7E, 0xFF, 0x11, 0x03, 0xC0, 0x9C])
    f[50:52] = (53412).to_bytes(2, "big")
    f[52:54] = (142).to_bytes(2, "big")
    f[155] = 87
    crc = T.crc16_modbus(bytes(f[:196]))
    f[196], f[197] = crc & 0xFF, (crc >> 8) & 0xFF
    return bytes(f)


C0 = make_c0()
t0 = time.monotonic()
frame = T.read_frame(GoodLine(C0), T.CMD_C0, 0xC0)
dur = time.monotonic() - t0
check("una risposta valida viene ancora letta correttamente", frame == C0)
check("e in tempi rapidi (nessuna attesa inutile)", dur < 0.5, f"{dur:.3f}s")


# ============================================================ payload MQTT ostili
T.ser_global = GoodLine(b"")

check("un frame raw enorme viene rifiutato senza allocarlo",
      T.cmd_raw("AA " * 100_000) is False)
check("un frame raw oltre il tetto viene rifiutato",
      T.cmd_raw(" ".join(["AA"] * (T.MAX_RAW_FRAME + 1))) is False)
check("un frame raw di dimensione normale passa",
      T.cmd_raw("7E FF 11 03 C0 08 BA EB") is True)

t0 = time.monotonic()
T.cmd_raw("41 " * 2_000_000)          # ~6 MB di payload
check("un payload da 6 MB viene scartato subito", time.monotonic() - t0 < 0.5,
      f"{time.monotonic() - t0:.3f}s")


class Cli:
    def __init__(self):
        self.pub = []

    def publish(self, t, p=None, retain=False, **k):
        self.pub.append((t, p))
        return types.SimpleNamespace(rc=0)


for payload in [b"inf", b"-inf", b"nan", b"1e400", b"", b"\xff\xfe", b"1e309",
                b"99999999999999999999999", b"0x10", b"[]"]:
    cli = Cli()
    ok_msg, _ = run_with_timeout(
        lambda c=cli, pl=payload: T.on_message(
            c, None, types.SimpleNamespace(topic=T.T_CMD_SMART, payload=pl)), 3.0)
    esito = [p for t, p in cli.pub if t.endswith("/status")]
    check(f"payload SmartPort {payload!r} gestito senza eccezioni",
          ok_msg and esito == ["ERRORE"], esito)

cli = Cli()
T.on_message(cli, None, types.SimpleNamespace(topic=T.T_CMD_SMART, payload=b"101"))
check("SmartPort fuori scala rifiutato",
      [p for t, p in cli.pub if t.endswith("/status")] == ["ERRORE"])


# ============================================================ ciclo principale
class Ser:
    is_open = True

    def __init__(self):
        self._s = False

    @property
    def in_waiting(self):
        return 0 if self._s else len(C0)

    def read(self, n):
        self._s = True
        return C0[:n]

    def reset_input_buffer(self):
        self._s = False

    def write(self, b):
        return len(b)

    def close(self):
        pass


class Client(Cli):
    def subscribe(self, t): pass
    def loop_stop(self): pass
    def disconnect(self): pass


boom = {"n": 0}
real_poll = T.poll_once


def flaky_poll(ser):
    boom["n"] += 1
    if boom["n"] in (2, 3):
        raise ValueError("guasto imprevisto simulato")   # non e' un errore seriale
    return real_poll(ser)


cicli = {"n": 0}


def fake_sleep(sec):
    if sec >= T.POLL_INTERVAL:
        cicli["n"] += 1
        if cicli["n"] >= 6:
            raise KeyboardInterrupt


# stato pulito: i test precedenti hanno lasciato una seriale finta in ser_global
T.ser_global = None
T.open_serial = lambda: Ser()
T.setup_mqtt = lambda: Client()
T.poll_once = flaky_poll
T.time.sleep = fake_sleep

finito, _ = run_with_timeout(T.main, 15.0)
check("il ciclo principale sopravvive a un'eccezione imprevista", finito)
check("e continua a leggere dopo il guasto", boom["n"] >= 5, boom["n"])
soc = [t for t, _ in T.mqtt_client.pub if t == "tbb/inverter/soc"]
check("le pubblicazioni riprendono dopo il guasto", len(soc) >= 3, len(soc))
avail = [p for t, p in T.mqtt_client.pub if t.endswith("availability")]
check("durante il guasto le entita' passano a non disponibili", "offline" in avail, avail)

print()
print("TUTTI I TEST PASSATI" if not fails else "FALLITI: " + ", ".join(fails))
sys.exit(1 if fails else 0)
