"""Local metrics collector: inference server counters + GPU power.

Regola (skill inference-server-metrics): il nome/porta del server si riconferma
da `ps`, mai dati per scontati. Solo letture, mai benchmark sull'endpoint live.

Uso:
    python3 -m sparkcost.collect            # snapshot attuale
    python3 -m sparkcost.collect --measure  # 10s window: prefill+decode tok/s
    python3 -m sparkcost.collect --loop 60  # appende un sample al DB ogni 60s
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DB = DATA / "sparkcost.sqlite"


def detect_server() -> dict | None:
    """Trova il server di inferenza da ps (tensorfold/vllm/sglang), con pid e uptime."""
    out = subprocess.run(["ps", "-eo", "pid,etimes,args"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if ("rank 0" in line or "serve" in line) and "--port" in line and \
                re.search(r"tensorfold|vllm|sglang", line):
            parts = line.split(None, 2)
            try:
                pid, uptime_s, rest = int(parts[0]), int(parts[1]), parts[2]
            except (ValueError, IndexError):
                continue
            port_m = re.search(r"--port (\d+)", rest)
            name_m = re.search(r"--name (\S+)", rest)
            model_m = re.search(r"models--(\S+?)/snapshots", rest)
            if port_m:
                return {
                    "pid": pid,
                    "uptime_s": uptime_s,
                    "backend": rest.split()[0].split("/")[-1],
                    "name": name_m.group(1) if name_m else "?",
                    "model": model_m.group(1).replace("Mia-AiLab--", "").replace("--", "/")
                    if model_m else "?",
                    "port": int(port_m.group(1)),
                }
    return None


# Opener diretto: bypassa http_proxy/https_proxy (il proxy di egress risponde 502 su localhost)
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read_counters(port: int) -> dict:
    try:
        text = _OPENER.open(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{port}/metrics returned HTTP {e.code}: server failing or a proxy.")
    except urllib.error.URLError as e:
        raise SystemExit(f"{port}/metrics non raggiungibile ({e.reason}): server giu? Verifica con ps.")

    def f(pat: str) -> float | None:
        m = re.search(pat, text, re.M)
        return float(m.group(1)) if m else None

    prefix_m = re.search(r"^(\w+):prompt_tokens_total", text, re.M)
    p = prefix_m.group(1) if prefix_m else "tensorfold"
    return {
        "prefix": p,
        "prompt_total": f(rf"^{p}:prompt_tokens_total (\S+)"),
        "gen_total": f(rf"^{p}:generation_tokens_total (\S+)"),
        "running": f(rf"^{p}:requests_running (\S+)"),
        "waiting": f(rf"^{p}:requests_waiting (\S+)"),
        "ttft_avg_s": (lambda s, c: s / c if s and c else None)(
            f(rf"^{p}:time_to_first_token_seconds_sum (\S+)"),
            f(rf"^{p}:time_to_first_token_seconds_count (\S+)"),
        ),
        "mtp_accept": (lambda a, d: a / d if a and d else None)(
            f(rf"^{p}:mtp_accepted_total (\S+)"),
            f(rf"^{p}:mtp_drafted_total (\S+)"),
        ),
    }


def read_watts() -> float | None:
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10)
    try:
        return float(r.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def integrated_watts(window_s: int | None = None, min_span_s: int = 300) -> dict | None:
    """Time-weighted average (trapezoid) of the power samples in the DB: energy
    vera = ∫P dt, non una lettura casuale. window_s limita agli ultimi N
    secondi (None = tutto lo storico). Ritorna None se campioni insufficienti
    (<2 o span < min_span_s): il chiamante fa fallback alla lettura puntuale.
    Note: watts are per unit (GPU 0 of this host); the fleet multiplies."""
    if not DB.exists() or DB.stat().st_size == 0:
        return None
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        if window_s:
            rows = con.execute(
                "SELECT ts,watts FROM samples WHERE watts IS NOT NULL AND ts>=? ORDER BY ts",
                (int(time.time() - window_s),)).fetchall()
        else:
            rows = con.execute(
                "SELECT ts,watts FROM samples WHERE watts IS NOT NULL ORDER BY ts").fetchall()
    except sqlite3.OperationalError:
        return None  # tabella assente / DB non ancora inizializzato
    finally:
        con.close()
    if len(rows) < 2:
        return None
    span = rows[-1][0] - rows[0][0]
    if span < min_span_s:
        return None
    energy_j = sum((rows[i][1] + rows[i + 1][1]) / 2 * (rows[i + 1][0] - rows[i][0])
                   for i in range(len(rows) - 1))
    return {"watts_avg": energy_j / span, "samples": len(rows), "span_s": span,
            "from_ts": rows[0][0], "to_ts": rows[-1][0]}


def measure(window_s: int = 10) -> dict:
    """Counter deltas over a window: prefill/decode tok/s + power."""
    srv = detect_server()
    if not srv:
        raise SystemExit("No inference server found in ps.")
    a = read_counters(srv["port"])
    w1 = read_watts()
    t0 = time.monotonic()
    time.sleep(window_s)
    dt = time.monotonic() - t0
    b = read_counters(srv["port"])
    w2 = read_watts()
    return {
        "server": srv,
        "window_s": round(dt, 1),
        "watts": w2 if w2 is not None else w1,
        "prefill_tok_s": (b["prompt_total"] - a["prompt_total"]) / dt if a["prompt_total"] and b["prompt_total"] else 0,
        "decode_tok_s": (b["gen_total"] - a["gen_total"]) / dt if a["gen_total"] and b["gen_total"] else 0,
        "counters": b,
    }


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")   # 1 writer (sampler) + letture dashboard
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("""CREATE TABLE IF NOT EXISTS samples(
        ts INTEGER PRIMARY KEY, server TEXT, prompt_total INTEGER,
        gen_total INTEGER, watts REAL)""")
    return con


def sample_once() -> dict:
    """Un campione robusto: watts SEMPRE (serve all'integrazione anche quando
    the inference server is down/restarting), counters only if available."""
    srv = detect_server()
    c = {}
    if srv:
        try:
            c = read_counters(srv["port"])
        except SystemExit:
            c = {}  # server presente ma /metrics non risponde: watt bastano
    return {"server": srv, "counters": c, "watts": read_watts()}


def store_sample(m: dict) -> None:
    con = _db()
    c = m.get("counters") or {}
    pt, gt = c.get("prompt_total"), c.get("gen_total")
    con.execute(
        "INSERT OR REPLACE INTO samples VALUES(?,?,?,?,?)",
        (int(time.time()), (m.get("server") or {}).get("name"),
         int(pt) if pt else None, int(gt) if gt else None, m.get("watts")))
    con.commit()
    con.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true", help="10s delta window")
    ap.add_argument("--loop", type=int, default=0, help="sample into the DB every N seconds")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.loop:
        print(f"sampling every {args.loop}s -> {DB} (ctrl-c to stop)")
        while True:
            m = sample_once()  # robust: watts always, counters when the server is up
            store_sample(m)
            c, w = m["counters"], m["watts"]
            print(f"{time.strftime('%H:%M:%S')} {w if w is not None else '?'} W | "
                  f"prompt {c.get('prompt_total') or '-'} gen {c.get('gen_total') or '-'}")
            time.sleep(args.loop)

    m = measure(10) if args.measure else None
    if m:
        if not args.json:
            print(f"server  : {m['server']['backend']} :{m['server']['port']} ({m['server']['model']})")
            print(f"window : {m['window_s']}s | power {m['watts']} W | running {int(m['counters']['running'] or 0)}")
            print(f"prefill: {m['prefill_tok_s']:.1f} tok/s")
            print(f"decode : {m['decode_tok_s']:.1f} tok/s")
            c = m["counters"]
            print(f"totals : prompt {c['prompt_total']:,.0f} | gen {c['gen_total']:,.0f}")
            if c.get("ttft_avg_s"):
                print(f"TTFT avg: {c['ttft_avg_s']:.2f}s | MTP accept {c['mtp_accept']*100:.1f}%")
        else:
            print(json.dumps(m, indent=2, default=str))
    else:
        srv = detect_server()
        c = read_counters(srv["port"]) if srv else {}
        print(json.dumps({"server": srv, "watts": read_watts(), "counters": c},
                         indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
