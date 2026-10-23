"""P49: power statistics — mean/peak fleet power, inference vs idle events.

Reads the per-host `power` table (ts, host, watts, running). A sample counts
as INFERENCE when the monitored server on this machine reports
requests_running > 0; idle otherwise. Unknown running (server down, or the
sample predates the flag) is excluded from the inference/idle split but kept
in the overall mean/peak. Hosts offline during a sample simply have no row
there — their idle share is undercounted, never invented.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "sparkcost.sqlite"


def fleet_stats(window_s: int | None = None) -> dict | None:
    if not DB.exists() or DB.stat().st_size == 0:
        return None
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        since = int(time.time() - window_s) if window_s else 0
        base = "SELECT ts,host,watts,running FROM power WHERE watts IS NOT NULL"
        rows = con.execute(base + (" AND ts>=?" if since else "") + " ORDER BY ts",
                           (since,) if since else ()).fetchall()
        try:
            peak_rows = con.execute(base + " ORDER BY watts DESC LIMIT 1",
                                    (since,) if since else ()).fetchall()
        except sqlite3.OperationalError:
            peak_rows = []
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    if not rows:
        return None

    ts_min = min(r[0] for r in rows)
    ts_max = max(r[0] for r in rows)
    sum_fleet = 0.0   # watts summed over hosts, per sample ts
    per_ts: dict[int, float] = {}
    per_host_w: dict[str, list] = {}
    inf_n = idle_n = unk_n = 0
    inf_sum = idle_sum = unk_sum = 0.0
    inf_w = idle_w = unk_w = 0.0
    for ts, host, w, running in rows:
        per_ts[ts] = per_ts.get(ts, 0.0) + w
        per_host_w.setdefault(host, []).append(w)
        if running:
            inf_n += 1; inf_sum += w; inf_w = max(inf_w, w)
        elif running is not None:
            idle_n += 1; idle_sum += w; idle_w = max(idle_w, w)
        else:
            unk_n += 1; unk_sum += w; unk_w = max(unk_w, w)

    ts_sorted = sorted(per_ts)
    diffs = [b - a for a, b in zip(ts_sorted, ts_sorted[1:]) if b > a]
    cadence_s = sorted(diffs)[len(diffs) // 2] if diffs else 30
    peak_ts_fleet = max((per_ts[ts] for ts in ts_sorted), default=0.0)
    # peak overall: max single-sample host watt OR max summed fleet ts
    peak_host_w = max((max(v) for v in per_host_w.values()), default=0.0)
    return {
        "window_s": (ts_max - ts_min) if window_s is None else min(window_s, ts_max - ts_min or window_s),
        "samples": len(rows),
        "from_ts": ts_min, "to_ts": ts_max,
        "fleet_mean_w": (sum(per_ts.values()) / len(per_ts)) if per_ts else 0.0,
        "fleet_peak_w": peak_ts_fleet,
        "peak_host_w": peak_host_w,
        "peak_sample_w": max((r[2] for r in peak_rows), default=0.0),
        "inference": {"samples": inf_n, "mean_host_w": (inf_sum / inf_n) if inf_n else None,
                      "peak_host_w": inf_w or None},
        "idle": {"samples": idle_n, "mean_host_w": (idle_sum / idle_n) if idle_n else None,
                 "peak_host_w": idle_w or None},
        "unknown": {"samples": unk_n, "mean_host_w": (unk_sum / unk_n) if unk_n else None,
                    "peak_host_w": unk_w or None},
        "energy_kwh_est": sum(per_ts.values()) * cadence_s / 3.6e6,
    }


def power_series(max_points: int = 180, max_age_s: int = 3600) -> dict | None:
    """P56, modello sparkDash (metricsStore/ringBuffer): serie RAW fleet power
    = somma sui host per ogni ts del sampler, coda di max_points (~30 min: 180 @ 10s, P58).
    FONTE UNICA server-side per valore card + sparkline: il browser non accumula
    piu' storia locale (niente mix di vecchie medie 30-min con punti live)."""
    if not DB.exists() or DB.stat().st_size == 0:
        return None
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        since = int(time.time()) - max_age_s
        rows = con.execute(
            "SELECT ts,host,watts FROM power WHERE watts IS NOT NULL AND ts>=? ORDER BY ts",
            (since,)).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    if not rows:
        return None
    per_ts: dict[int, float] = {}
    for ts, _host, w in rows:
        per_ts[ts] = per_ts.get(ts, 0.0) + w
    ts_sorted = sorted(per_ts)
    if len(ts_sorted) < 2:
        return None
    diffs = [b - a for a, b in zip(ts_sorted, ts_sorted[1:]) if b > a]
    cadence = sorted(diffs)[len(diffs) // 2] if diffs else None
    tail = ts_sorted[-max_points:]
    return {"points": [[t, round(per_ts[t], 1)] for t in tail],
            "last_w": per_ts[ts_sorted[-1]], "cadence_s": cadence,
            "span_s": tail[-1] - tail[0]}


def live_power(max_age_s: int = 180) -> dict | None:
    """P54: fleet power LIVE dal sampler = somma dell'ultimo campione per host
    (solo host con un campione entro max_age_s). None se nessun dato fresco."""
    if not DB.exists() or DB.stat().st_size == 0:
        return None
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        now = int(time.time())
        rows = con.execute(
            "SELECT host,watts,ts FROM power WHERE watts IS NOT NULL AND ts>=? "
            "ORDER BY host,ts DESC", (now - max_age_s,)).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    if not rows:
        return None
    latest: dict[str, tuple[float, int]] = {}
    for host, w, ts in rows:  # ordinato per host,ts DESC: primo hit = piu' recente
        if host not in latest:
            latest[host] = (float(w), int(ts))
    if not latest:
        return None
    return {"fleet_w": sum(w for w, _ in latest.values()),
            "ts": max(ts for _, ts in latest.values()),
            "per_host": {h: {"watts": w, "age_s": now - ts} for h, (w, ts) in latest.items()}}
