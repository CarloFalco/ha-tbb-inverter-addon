"""
Test di non regressione sulla SmartPort.

La 1.3.0 scriveva gli ampere (5-32) nel registro 0x005E, che invece accetta
0-100: l'inverter saturava al minimo di 5 A. Questo test confronta i frame
emessi oggi con quelli della 1.2.0, l'ultima versione funzionante, prendendola
direttamente dalla storia di git.

Esegui dalla radice del repository:

    python tests/test_regressione_smartport.py
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

os.environ.update({
    "MQTT_PREFIX": "tbb/inverter",
    "LOG_LEVEL": "error",
    "ADDON_VERSION": "test",
})
RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "tbb_inverter"))
import tbb_reader as T

RIFERIMENTO = "ca3fc60"          # v1.2.0: ultima versione con la SmartPort funzionante

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  -> ' + str(detail) if detail else ''}")
    if not cond:
        fails.append(name)


class Ser:
    is_open = True

    def __init__(self):
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


class Cli:
    def publish(self, *a, **k):
        return types.SimpleNamespace(rc=0)


def carica_versione_storica():
    """Importa tbb_reader dal commit di riferimento, o None se git non e' disponibile."""
    try:
        sorgente = subprocess.run(
            ["git", "show", f"{RIFERIMENTO}:tbb_inverter/tbb_reader.py"],
            cwd=RADICE, capture_output=True, text=True, timeout=30, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"NOTA  impossibile recuperare {RIFERIMENTO} da git ({e.__class__.__name__}):")
        print("      il confronto storico viene saltato, gli altri controlli restano.")
        return None

    percorso = Path(tempfile.gettempdir()) / "tbb_reader_v120.py"
    percorso.write_text(sorgente, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("tbb_reader_v120", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def accelera(modulo):
    """
    Neutralizza attese e lettura: qui interessano solo i byte trasmessi.

    Senza questo ogni scrittura costerebbe ~1,2 s fra ritardi fra i frame e
    attesa della risposta, e il confronto su tutta la scala 0-100 richiederebbe
    diversi minuti.
    """
    modulo.read_response = lambda *a, **k: b""
    modulo.time.sleep = lambda *a, **k: None
    return modulo


def frame_di(modulo, valore):
    modulo.ser_global = Ser()
    modulo.mqtt_client = Cli()
    modulo.cmd_smart_port(valore)
    return bytes(modulo.ser_global.written)


def frame_da_topic(topic, valore):
    T.ser_global = Ser()
    T.mqtt_client = Cli()
    T.on_message(Cli(), None, types.SimpleNamespace(
        topic=f"tbb/inverter/{topic}", payload=str(valore).encode()))
    return bytes(T.ser_global.written)


# --- confronto con la versione funzionante --------------------------------
accelera(T)
storico = carica_versione_storica()
if storico is not None:
    accelera(storico)
    diversi = []
    for pct in range(0, 101):
        if frame_di(storico, pct) != frame_da_topic("cmd/smart_port", pct):
            diversi.append(pct)
    check(f"i frame in percentuale sono identici alla {RIFERIMENTO} su tutta la scala 0-100",
          not diversi, f"differiscono a: {diversi[:10]}")

# --- il registro riceve 0-100, mai gli ampere -----------------------------
def registro_scritto(frame):
    for candidato in range(0, 101):
        if T.build_frame(0x06, 0x005E, candidato) in frame:
            return candidato
    return None


check("il topic in percentuale scrive il numero senza convertirlo",
      all(registro_scritto(frame_da_topic("cmd/smart_port", p)) == p
          for p in (0, 17, 40, 63, 100)))

# la regressione in una riga: 16 A non deve piu' finire grezzo nel registro
check("16 A non viene piu' scritto grezzo nel registro",
      registro_scritto(frame_da_topic("cmd/smart_port_a", 16)) != 16)
check("16 A diventa il valore di registro corretto",
      registro_scritto(frame_da_topic("cmd/smart_port_a", 16)) == T.amps_to_register(16))

# nessuna scrittura puo' uscire da 0-100, qualunque sia l'unita' di partenza
fuori = []
for amp in range(T.SMARTPORT_MIN_A, T.SMARTPORT_MAX_A + 1):
    reg = registro_scritto(frame_da_topic("cmd/smart_port_a", amp))
    if reg is None or not 0 <= reg <= 100:
        fuori.append((amp, reg))
check("ogni ampere dello slider produce un registro valido 0-100", not fuori, fuori)

print()
print("TUTTI I TEST PASSATI" if not fails else "FALLITI: " + ", ".join(fails))
sys.exit(1 if fails else 0)
