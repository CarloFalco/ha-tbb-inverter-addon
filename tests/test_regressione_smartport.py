"""
Test di non regressione sulla SmartPort.

Riferimento: il commit iniziale, dove la scrittura funzionava sul campo. Da
li' viene la verita' sperimentale su cosa contiene il registro 0x005E:

    scrivendo N grezzo,  N = 5..32  ->  l'inverter imposta N ampere
                         N < 5      ->  nessun effetto (sotto il minimo)
                         N > 32     ->  satura al massimo

Cioe' **il registro contiene ampere**. La 1.3.1 ha assunto il contrario
(registro = percentuale 0-100) e ha introdotto in `amps_to_register` un
fattore 100/32 = 3,125 che manda 16 A a fondo scala: e' la regressione che
questo test blocca.

Due controlli distinti, da non confondere:

 1. i byte trasmessi da `cmd_smart_port(N)` devono restare identici a quelli
    della versione funzionante, per ogni N -- il trasporto non deve muoversi;
 2. la catena di conversione deve portare N ampere al registro N.

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

RIFERIMENTO = "12bb125"          # commit iniziale: SmartPort verificata sul campo

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

    def flush(self):
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

    percorso = Path(tempfile.gettempdir()) / f"tbb_reader_{RIFERIMENTO}.py"
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
    modulo.time.sleep = lambda *a, **k: None
    if hasattr(modulo, "read_response"):
        modulo.read_response = lambda *a, **k: b""
    # Le versioni storiche tracciano con print(): un attributo di modulo con
    # quel nome ha la precedenza sulla builtin e zittisce 300 righe di frame.
    modulo.print = lambda *a, **k: None
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


# --- 1. il trasporto non e' cambiato --------------------------------------
# Per ogni valore di registro, i byte sulla seriale devono essere quelli della
# versione che funzionava: stesso sblocco, stesso CRC, stesso ordine.
accelera(T)
storico = carica_versione_storica()
if storico is not None:
    accelera(storico)
    diversi = [n for n in range(0, 101)
               if frame_di(storico, n) != frame_di(T, n)]
    check(f"cmd_smart_port(N) emette i byte della {RIFERIMENTO} per ogni N in 0-100",
          not diversi, f"differiscono a: {diversi[:10]}")

    # ...e il topic grezzo deve continuare a passare N senza toccarlo.
    diversi = [n for n in range(0, 101)
               if frame_di(storico, n) != frame_da_topic("cmd/smart_port", n)]
    check(f"il topic grezzo scrive come la {RIFERIMENTO} su tutta la scala 0-100",
          not diversi, f"differiscono a: {diversi[:10]}")


# --- 2. la conversione porta N ampere al registro N -----------------------
def registro_scritto(frame):
    """Ricava dal frame il valore finito nel registro 0x005E."""
    for candidato in range(0, 101):
        if T.build_frame(0x06, 0x005E, candidato) in frame:
            return candidato
    return None


check("il topic grezzo scrive il numero senza convertirlo",
      all(registro_scritto(frame_da_topic("cmd/smart_port", n)) == n
          for n in (0, 17, 40, 63, 100)))

# La regressione in una riga: 16 A deve tornare a essere il registro 16,
# non 50 come lo mandava la 1.3.1.
check("16 A finisce nel registro come 16 (non 50, come nella 1.3.1)",
      registro_scritto(frame_da_topic("cmd/smart_port_a", 16)) == 16,
      registro_scritto(frame_da_topic("cmd/smart_port_a", 16)))

sbagliati = [(a, registro_scritto(frame_da_topic("cmd/smart_port_a", a)))
             for a in range(T.SMARTPORT_MIN_A, T.SMARTPORT_MAX_A + 1)]
check("ogni ampere dello slider arriva al registro senza conversioni",
      all(a == reg for a, reg in sbagliati),
      [x for x in sbagliati if x[0] != x[1]][:10])

# Lo slider in watt passa per gli ampere: 230 W = 1 A al voltaggio predefinito.
sbagliati = [(a, registro_scritto(frame_da_topic("cmd/smart_port_w", a * T.SMARTPORT_VOLTAGE)))
             for a in range(T.SMARTPORT_MIN_A, T.SMARTPORT_MAX_A + 1)]
check("lo slider in watt arriva al registro corrispondente",
      all(a == reg for a, reg in sbagliati),
      [x for x in sbagliati if x[0] != x[1]][:10])

# Nessuna scrittura puo' uscire da 0-100, qualunque sia l'unita' di partenza.
fuori = [(a, reg) for a, reg in
         ((a, registro_scritto(frame_da_topic("cmd/smart_port_a", a)))
          for a in range(T.SMARTPORT_MIN_A, T.SMARTPORT_MAX_A + 1))
         if reg is None or not 0 <= reg <= 100]
check("ogni ampere dello slider produce un registro valido 0-100", not fuori, fuori)


# --- 3. nessuna scrittura esce dall'intervallo utile ----------------------
# L'inverter conferma con un ACK regolare qualunque valore, anche fuori scala:
# non c'e' un rifiuto su cui contare per accorgersi di un errore. L'unica
# difesa e' che la conversione non produca mai un registro fuori da
# MIN_A-MAX_A, che e' precisamente cio' che la 1.3.1 faceva da 11 A in su.
fuori = [a for a in range(T.SMARTPORT_MIN_A, T.SMARTPORT_MAX_A + 1)
         if not T.SMARTPORT_MIN_A <= registro_scritto(
             frame_da_topic("cmd/smart_port_a", a)) <= T.SMARTPORT_MAX_A]
check("nessuna posizione dello slider esce dall'intervallo utile",
      not fuori, f"{len(fuori)} valori: {fuori[:8]}")

# La stessa cosa in watt.
fuori = [a for a in range(T.SMARTPORT_MIN_A, T.SMARTPORT_MAX_A + 1)
         if not T.SMARTPORT_MIN_A <= registro_scritto(
             frame_da_topic("cmd/smart_port_w", a * T.SMARTPORT_VOLTAGE))
         <= T.SMARTPORT_MAX_A]
check("nemmeno lo slider in watt esce dall'intervallo utile",
      not fuori, f"{len(fuori)} valori: {fuori[:8]}")

# Controprova: con la conversione della 1.3.1, 22 valori su 28 sarebbero
# finiti fuori intervallo. Se questo controllo smette di valere, la formula
# sbagliata e' cambiata e il confronto va rivisto.
def reg_131(a):
    return max(0, min(100, round(a * 100 / T.SMARTPORT_MAX_A)))


fuori_131 = [a for a in range(T.SMARTPORT_MIN_A, T.SMARTPORT_MAX_A + 1)
             if not T.SMARTPORT_MIN_A <= reg_131(a) <= T.SMARTPORT_MAX_A]
check("controprova: la formula della 1.3.1 mandava fuori scala da 11 A in su",
      fuori_131 and fuori_131[0] == 11 and len(fuori_131) == 22,
      f"{len(fuori_131)} valori da {fuori_131[0] if fuori_131 else '-'} A")


# --- 4. la modalita' "percent" resta disponibile e coerente ---------------
T.SMARTPORT_REGISTER_UNIT = "percent"
try:
    check("in modalita' percent 32 A va a fondo scala (registro 100)",
          T.amps_to_register(32) == 100, T.amps_to_register(32))
    check("in modalita' percent il registro 50 vale meta' scala",
          round(T.register_to_amps(50)) == 16, T.register_to_amps(50))
finally:
    T.SMARTPORT_REGISTER_UNIT = "ampere"

check("tornati in modalita' ampere, 32 A resta il registro 32",
      T.amps_to_register(32) == 32)

# Un float non deve mai raggiungere build_frame: >> su float e' TypeError, e
# l'eccezione morirebbe dentro il thread di rete di paho.
check("un registro non intero viene rifiutato invece di sollevare",
      T.cmd_smart_port(20.5) is False)

print()
print("TUTTI I TEST PASSATI" if not fails else "FALLITI: " + ", ".join(fails))
sys.exit(1 if fails else 0)
