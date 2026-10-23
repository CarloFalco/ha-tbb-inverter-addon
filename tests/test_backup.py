"""
Backup e ripristino dei parametri, e decodifica dei frame veri di un inverter.

I dati non sono inventati: parametri e frame vengono dal log di un RiiO Sun II
8.0S reale (diag_params e diag_frames attivi, SmartPort in modalita' Smart Gen,
rete assente). I frame C0/C1 sono quelli del "Ciclo 1" di quel log, e i valori
attesi sono quelli che l'add-on ha mostrato a video in quel ciclo.

Esegui dalla radice del repository:

    python tests/test_backup.py
"""
import os
import sys
import tempfile
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


# ------------------------------------------------- dati dal campo
PARAMETRI_DAL_LOG = """
A 0x0000 |  2300  5000  2500   100 48000    32  8000 65535     0 65535
A 0x000a |     0 65535 65535 65535 65535 65535     2     0     0     1
A 0x0014 |     1     0 65535     1     1 65535     0     1     0     0
A 0x001e |     0     1     0     1     1     0     0 65535 65535 65535
A 0x0028 | 65535 65535 65535 65535 65535 65535 65535 65535 65535 65535
A 0x0032 |  2300 65535 65535 65535 65535 65535     0     1     0 65535
A 0x003c | 65535 65535 65535 65535 13300 13100  9900 10500 11000 65535
A 0x0046 |    30   300   200    30     8   240    18     1 13000     1
A 0x0050 |  2650  1750   500   500     0     0    14    50    20     0
A 0x005a |   100    50     0     1     7 65535     0     0     0     0
A 0x0065 |     0     0     0     0     0     0     0     0     0     0
A 0x006f |     0     0     0     0     0     0     0     0     0     0
A 0x0079 |     0     0     0     0     0     0     0     0     0     0
A 0x0083 |     0     0     0     0     0     0     0     0     0     0
A 0x008d |     0     0     0   100     8     5    80    30    55    50
A 0x0097 |   100     1 65535 65535 65535 65535 65535 65535 65535 65535
A 0x00a1 | 65535 65535 65535 65535 65535 65535 65535 65535 65535 65535
A 0x00ab | 65535 65535 65535 65535 65535    85   305   415
A 0x00ca |   629   146  4104   313 49727   629  1619  1514   100     0
A 0x00d4 |     0     1   146   162    44  4416     0     0     0     0
A 0x00de |     0     0     0     0     0     0     0     0     0     0
A 0x00e8 |     0     0     0     0     0     0     0     0     0     0
A 0x00f2 |     0     0     0     0     0     0     0     0     0     0
A 0x00fc |     0
B 0x0000 |     3     1     1     0    10     0     0     0     0     0
B 0x000a |     0     0     0     0     0     0     0     0     0    10
B 0x0014 |    60 11500 12000     0     0     0    80    50    30    80
B 0x001e |    30   180     2     0     0     0     0     0     0     0
B 0x0028 |     0     0 10000 12000    10    60    30    80     1   180
B 0x0032 |    30     0     1     0    10    30    30     3     3     0
B 0x003c |     7     0     1     0     0 12000 12500    10    60     0
B 0x0046 |     0     0     0     0     0     0    50    80     0     0
B 0x0050 |     6    10 15500    30   400 13000    80     0     0     1
B 0x005a |     0     0     5     0     0     0     1     0     1  3000
B 0x0064 |  1000    80    50 12500 12000    60    10    80   100    60
B 0x006e |    10     1 11000 13000    15    10    10     0     0     0
B 0x0078 |     0     0     0     0     0     0     0     0 17226 12592
B 0x0082 | 12594 12343 12336 13616     0     0     0     0     0     0
B 0x008c |     0     0     0     0     0     0     0     0     0     0
B 0x0096 |     0     0     0     0     0     0     0     0     0     0
B 0x00a0 |     0     0     0     0     0     0     0     0     0     0
B 0x00aa |     0     0     0     0     0     0     0     0     0     0
B 0x00b4 |     0     0     0     0     0     0     0     0     0     0
B 0x00be |     0     0     0     0     0     0     0     0     0     0
B 0x00d0 |  4400     1     0     0     0 27355 37720   592     0     3
B 0x00da |    17     1     1     0     1     5     0     0     0     0
B 0x00e4 |     0     0     0     0     0     0     0     0     0     0
B 0x00ee |     0
"""


def registri_dal_log():
    regs = {}
    for riga in PARAMETRI_DAL_LOG.strip().splitlines():
        testa, valori = riga.split("|")
        banco, primo = testa.split()
        cmd = T.BANK_A_READ if banco == "A" else T.BANK_B_READ
        for i, v in enumerate(valori.split()):
            regs[(cmd, int(primo, 16) + i)] = int(v)
    return regs


FRAME_C0 = """
7E 11 FF 03 C0 AA 40 67 00 00 03 93 FE DC 02 72 00 00 02 B8 00 03 09 61 09 63 09 63 09 5F 00 00
01 7D FF 83 01 21 00 00 00 00 13 8C 13 8C C2 3F 00 32 C1 70 00 81 00 1A 00 39 00 1F 00 31 00 00
00 00 00 16 00 02 05 34 00 00 00 00 00 00 00 00 00 00 00 1F 00 00 14 10 00 00 00 00 11 40 02 08
11 30 00 04 00 06 00 04 00 08 01 FC 03 E8 01 38 01 A9 00 00 00 3D 00 FA 00 07 00 01 00 1C 00 07
00 00 00 00 00 18 00 2A 00 5F 01 0D 00 00 00 00 00 00 00 00 00 00 00 00 00 04 64 3A 00 00 00 00
01 00 01 A4 00 00 00 00 B4 C7
"""
FRAME_C1 = (
    "7E 11 FF 03 C1 D0 00 01 01 39 02 75 00 92 10 08 01 39 C2 3F 02 75 06 53 05 EA 00 64 00 00 00 00 "
    "00 01 00 92 00 A2 00 2C 11 40" + " 00" * 164 + " AA F0"
)


def frame(testo):
    return bytes.fromhex(" ".join(testo.split()))


# ------------------------------------------------- frame veri: C0 e C1
c0, c1 = frame(FRAME_C0), frame(FRAME_C1)
check("il frame C0 reale e' lungo 170 byte e ha un CRC valido",
      len(c0) == 170 and T.crc_frame_length(c0) == 170, (len(c0), T.crc_frame_length(c0)))
check("il frame C1 reale e' lungo 208 byte e ha un CRC valido",
      len(c1) == 208 and T.crc_frame_length(c1) == 208, (len(c1), T.crc_frame_length(c1)))

d = T.apply_derived({**T.decode_c0(c0), **T.decode_c1(c1)})
CICLO_1 = {
    "pv_v": 161.9, "mppt_i": 6.29, "pv_w": 313, "mppt_temp": 44,
    "ac_out_v": 240.3, "ac_out_i": 2.89, "ac_out_w": 626,
    "ac_out2_v": 239.9, "ac_out2_i": 0.0, "ac_out2_w": 0,
    "ac_in_v": 0.3, "ac_in_i": 0.0, "ac_in_w": 0, "ac_in_freq": 0.0,
    "gen_v": 240.1, "gen_i": 3.81, "gen_w": 915, "gen_freq": 50.04, "ac_freq": 50.04,
    "bat_v": 49.52, "bat_i": 12.9, "bat_v_bms": 49.727, "soc": 58,
    "t_heatsink": 31, "t_transformer": 57, "t_inverter": 49, "t_bat": 22, "load_pct": 4,
}
diversi = {k: (d.get(k), v) for k, v in CICLO_1.items()
           if d.get(k) is None or abs(d[k] - v) > 1e-6}
check("il frame C0/C1 reale si decodifica come il Ciclo 1 del log", not diversi, diversi)
check("generatore: tensione x corrente coerente con la potenza misurata (entro il 5 %)",
      abs(d["gen_v"] * d["gen_i"] - d["gen_w"]) / d["gen_w"] < 0.05,
      round(d["gen_v"] * d["gen_i"]))
entra = d["pv_w"] + d["gen_w"] + max(0, d["ac_in_w"])
esce = d["ac_out_w"] + d["ac_out2_w"] + max(0, d["bat_w"])
check("il bilancio energetico chiude entro il 5 %", abs(entra - esce) / entra < 0.05,
      f"entra {entra} W, esce {esce:.0f} W")


# ------------------------------------------------- inverter finto
class Inverter:
    """Risponde a letture e scritture come l'inverter reale; ricorda le scritture."""
    is_open = True

    def __init__(self, regs, muti=()):
        self.regs, self.muti = dict(regs), set(muti)
        self.out, self.scritture = b"", []

    @property
    def in_waiting(self):
        return len(self.out)

    def read(self, n):
        b, self.out = self.out[:n], self.out[n:]
        return b

    def write(self, b):
        tipo, cmd, reg, val = b[3], b[4], b[6] << 8 | b[7], b[8] << 8 | b[9]
        if tipo == 0x03:
            if (cmd, reg) in self.muti:
                self.out = b""
                return len(b)
            dati = b"".join(self.regs.get((cmd, reg + i), 0).to_bytes(2, "big") for i in range(val))
            corpo = bytes([0x7E, 0x11, 0xFF, 0x03, cmd, 6 + len(dati) + 2]) + dati
        else:
            self.scritture.append((cmd, reg, val))
            lettura = {0x06: 0x03, 0x66: 0x33}.get(cmd)
            if lettura is not None:
                self.regs[(lettura, reg)] = val
            corpo = bytes([0x7E, 0x11, 0xFF]) + bytes(b[3:10])
        crc = T.crc16_modbus(corpo)
        self.out = corpo + bytes([crc & 0xFF, crc >> 8])
        return len(b)

    def reset_input_buffer(self):
        pass

    def flush(self):
        pass


class Client:
    def __init__(self):
        self.pub = {}

    def publish(self, topic, payload=None, retain=False, **k):
        self.pub[topic] = payload
        return types.SimpleNamespace(rc=0)


T.time.sleep = lambda *a, **k: None
cartella = Path(tempfile.mkdtemp(prefix="tbb_backup_"))
T.BACKUP_DIR = cartella
T.mqtt_client = Client()


def nuovo_inverter(**k):
    T.ser_global = Inverter(registri_dal_log(), **k)
    return T.ser_global


# ------------------------------------------------- backup
inv = nuovo_inverter()
percorso = T.backup_parameters()
check("il backup crea un file nella cartella condivisa",
      percorso is not None and percorso.parent == cartella and percorso.is_file(), percorso)
testo = percorso.read_text(encoding="utf-8")
righe = testo.splitlines()
check("il backup non scrive nulla sull'inverter", not inv.scritture, inv.scritture)
check("il backup contiene tutti i registri letti",
      sum(1 for r in righe if r.lstrip("#~ ")[:2] in ("A ", "B ")) == len(registri_dal_log()),
      sum(1 for r in righe if r.lstrip("#~ ")[:2] in ("A ", "B ")))
check("i parametri ripristinabili sono righe attive",
      any(r.startswith("B 0x005c     5") for r in righe), [r for r in righe if "0x005c" in r])
check("i registri di sola lettura sono commentati",
      any(r.startswith("#~ A 0x0000  2300") for r in righe)
      and not any(r.startswith("A 0x0000") for r in righe))
check("le tensioni sono riportate per blocco da 12 V e per il sistema a 48 V",
      any("0x002b" in r and "12.00 V per blocco da 12 V = 48.00 V" in r for r in righe),
      [r for r in righe if "0x002b" in r])
voci, errori = T.parse_parameters(testo)
check("il file di backup si rilegge senza errori", not errori, errori[:3])
check("rilette solo le righe ripristinabili",
      voci and all(T.scrivibile(c, r) for c, r, _, _ in voci), len(voci))

nuovo_inverter(muti={(T.BANK_B_READ, 0x0064)})
quanti_prima = len(list(cartella.iterdir()))
check("con un blocco illeggibile il backup viene annullato",
      T.backup_parameters() is None and len(list(cartella.iterdir())) == quanti_prima)


# ------------------------------------------------- anteprima e ripristino
def scrivi_ripristino(contenuto):
    (cartella / T.RESTORE_FILE).write_text(contenuto, encoding="utf-8")


scrivi_ripristino(testo)
inv = nuovo_inverter()
base = T.restore_parameters(applica=False)
check("anteprima di un backup appena fatto: niente da cambiare",
      base is not None and base["modifiche"] == 0 and not inv.scritture, base)
# Anche un backup intatto ha qualche riga ignorata: parametri scrivibili che su
# questo modello valgono 65535 (A 0x0016, A 0x003C), mai scritti.
check("...ignorando i parametri non usati su questo modello", base and base["ignorati"] == 2, base)

modificato = (testo.replace("B 0x005c     5", "B 0x005c    15")
                   .replace("A 0x005e     7", "A 0x005e     8")
              + "\nA 0x0000  9999\nB 0x0072 65535\nA 0x0016     1\n")
scrivi_ripristino(modificato)
inv = nuovo_inverter()
r = T.restore_parameters(applica=False)
check("l'anteprima trova le due modifiche", r and r["modifiche"] == 2, r)
check("...ignora sola lettura, 65535 e registri non usati sull'inverter",
      r and r["ignorati"] == base["ignorati"] + 3, r)
check("...e non scrive nulla", not inv.scritture, inv.scritture)

r = T.restore_parameters(applica=True)
check("il ripristino scrive esattamente le due modifiche",
      sorted(inv.scritture) == [(0x06, 0x005E, 8), (0x66, 0x005C, 15)], inv.scritture)
check("...e le conferma in rilettura", r and r["scritti"] == 2 and r["falliti"] == 0, r)
check("...senza toccare dati di targa, 65535 o registri inutilizzati",
      not any(reg in (0x0000, 0x0016, 0x0072) for _, reg, _ in inv.scritture))
check("dopo il ripristino le entita' vengono aggiornate",
      T.mqtt_client.pub.get("tbb/inverter/gen_charge_current") == 15
      and T.mqtt_client.pub.get("tbb/inverter/smart_port_a") == 8, T.mqtt_client.pub)

inv = nuovo_inverter()
scrivi_ripristino(modificato + "B 0x0072 venti\n")
check("una riga non valida fa rifiutare tutto il file",
      T.restore_parameters(applica=True) is None and not inv.scritture, inv.scritture)
check("un file mancante viene rifiutato", T.restore_parameters("manca.txt", True) is None)
for nome in ("../segreti.txt", "/etc/passwd", "con spazio.txt", ".nascosto.txt", "file.sh"):
    check(f"nome di file non sicuro rifiutato: {nome!r}",
          T.restore_parameters(nome, applica=True) is None and not inv.scritture)


# ------------------------------------------------- comandi via MQTT
def comando(topic, payload, attendi=True):
    cli = Client()
    T.mqtt_client = cli
    T.on_message(cli, None, types.SimpleNamespace(
        topic=f"tbb/inverter/{topic}", payload=str(payload).encode()))
    if attendi and T._ultimo_lavoro is not None:
        T._ultimo_lavoro.join(10)
    return cli.pub.get(f"tbb/inverter/{topic}/status")


nuovo_inverter()
check("il pulsante di backup risponde OK", comando("cmd/param_backup", "PRESS") == "OK")
scrivi_ripristino(modificato)
inv = nuovo_inverter()
check("il pulsante di anteprima risponde OK senza scrivere",
      comando("cmd/param_restore_preview", "PRESS") == "OK" and not inv.scritture)
check("il pulsante di ripristino applica le modifiche",
      comando("cmd/param_restore", "PRESS") == "OK" and len(inv.scritture) == 2, inv.scritture)

T._operazione_parametri.acquire()
try:
    check("una seconda operazione mentre la prima e' in corso viene rifiutata",
          comando("cmd/param_backup", "PRESS", attendi=False) == "ERRORE")
finally:
    T._operazione_parametri.release()

inv = nuovo_inverter()
check("cmd/gen_charge_current = 15 scrive il banco B, registro 0x005C",
      comando("cmd/gen_charge_current", "15") == "OK" and inv.scritture == [(0x66, 0x005C, 15)],
      inv.scritture)
for cattivo in ("0", "101", "7.5", "dieci"):
    inv = nuovo_inverter()
    check(f"cmd/gen_charge_current = {cattivo!r} rifiutato senza scrivere",
          comando("cmd/gen_charge_current", cattivo) == "ERRORE" and not inv.scritture)

# Corrente massima da rete: Power Assist dell'ingresso AC 1, banco A 0x0056.
# Sul campo valeva 14 A, ed e' il tetto dei ~3,2 kW presi dalla rete in carica completa.
inv = nuovo_inverter()
check("la corrente massima da rete letta dal campo vale 14 A",
      inv.regs[(T.BANK_A_READ, 0x0056)] == 14)
check("cmd/grid_current_max = 8 scrive il banco A, registro 0x0056, con il comando 0x06",
      comando("cmd/grid_current_max", "8") == "OK" and inv.scritture == [(0x06, 0x0056, 8)],
      inv.scritture)
check("...e la conferma in rilettura",
      T.mqtt_client.pub.get("tbb/inverter/grid_current_max") == 8, T.mqtt_client.pub)
for cattivo in ("4", "33", "10.5", "tanto"):
    inv = nuovo_inverter()
    check(f"cmd/grid_current_max = {cattivo!r} rifiutato senza scrivere",
          comando("cmd/grid_current_max", cattivo) == "ERRORE" and not inv.scritture)
check("il backup rende ripristinabile la corrente massima da rete",
      T.scrivibile(T.BANK_A_READ, 0x0056))

T.ser_global = None
T.mqtt_client = None

print()
print("TUTTI I TEST PASSATI" if not fails else "FALLITI: " + ", ".join(fails))
sys.exit(1 if fails else 0)
