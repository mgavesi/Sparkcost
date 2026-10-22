"""Local cost engine: EUR/1M token from measured power + amortization,
compared against the cloud price list (models.py).

Usage:
    python3 -m sparkcost.localcost            # comparison table
    python3 -m sparkcost.localcost --measure  # measure tok/s and watts first (10s window)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import deque
from pathlib import Path

import yaml

from . import models
from .collect import detect_server, integrated_watts, measure, read_counters, read_watts

CONFIG = Path(__file__).resolve().parent.parent / "data" / "config.yaml"
PRICE_OVERRIDES = Path(__file__).resolve().parent.parent / "data" / "price_overrides.yaml"


# Live tok/s state: sliding window of samples (ts, pt, gt) from /metrics.
# Read-only: no load is generated on the endpoint (skill rule).
# maxlen 240: with several clients polling at 1s it still covers >= 30s of history.
_samples: deque = deque(maxlen=240)
_WINDOW_S = 30.0


def _live_rates(counters: dict) -> dict | None:
    """Prefill and decode tok/s from the counters.

    Sustained (30s): window average — the main figure, readable, shows the real
    activity level instead of instantaneous bursts.
    Instantaneous (>=0.3s): the true peak of the last instant.
    An idle server returns 0.0 after >30s: not a bug, just no traffic.
    """
    pt, gt = counters.get("prompt_total"), counters.get("gen_total")
    if pt is None or gt is None:
        return None
    now = time.time()
    _samples.append((now, pt, gt))
    # sustained base: the OLDEST sample within the window (restart-safe)
    base = None
    for ts, p, g in _samples:
        if now - ts > _WINDOW_S:
            continue
        if p > pt or g > gt:  # counters reset: discard
            continue
        if base is None or ts < base[0]:
            base = (ts, p, g)
    if base is None or now - base[0] < 0.5:
        return None
    dt = now - base[0]
    out = {
        "dt_s": round(dt, 2),
        "prefill_tok_s": max(0.0, (pt - base[1]) / dt),
        "decode_tok_s": max(0.0, (gt - base[2]) / dt),
    }
    # istantaneo: il campione piu' RECENTE con dt >= 0.3s
    inst = None
    for ts, p, g in _samples:
        di = now - ts
        if di >= 0.3 and p <= pt and g <= gt:
            if inst is None or ts > inst[0]:
                inst = (ts, p, g)
    if inst:
        di = now - inst[0]
        out["instant_prefill_tok_s"] = max(0.0, (pt - inst[1]) / di)
        out["instant_decode_tok_s"] = max(0.0, (gt - inst[2]) / di)
    return out


def capex_total(cfg: dict) -> float:
    """Total fleet investment: hardware_total_eur (new) or hardware_eur * n (old)."""
    if cfg.get("hardware_total_eur") is not None:
        return float(cfg["hardware_total_eur"])
    return float(cfg["hardware_eur"]) * int(cfg.get("n_sparks", 1))


def local_month_breakdown(cfg: dict, watts: float | None) -> dict:
    """Split the fleet's monthly cost into three parts:
    - straight-line capex amortization
    - idle energy (24/7 if always_on, otherwise only working hours)
    - extra token-related energy: power above idle x working hours
      (this is the local 'token-related cost': scales with hours_per_day)
    Single source for replay_cost and breakeven: same basis, always.
    """
    n = int(cfg.get("n_sparks", 1))
    h_day = float(cfg.get("hours_per_day", 8))
    tariff = cfg["eur_per_kwh"]
    idle_w = cfg["idle_watts"]
    amort = amort_monthly(cfg)
    idle_hours = 24 if cfg.get("always_on") else h_day
    idle_eur = idle_w * n / 1000 * idle_hours * 30.44 * tariff
    extra_w = max((watts or idle_w) - idle_w, 0.0) * n
    token_eur = extra_w / 1000 * h_day * 30.44 * tariff
    return {"amort": amort, "idle_energy": idle_eur, "token_energy": token_eur,
            "total": amort + idle_eur + token_eur}


def save_config(cfg: dict) -> None:
    """Riscrive data/config.yaml (usato dalla dashboard per il capex)."""
    CONFIG.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))


def save_capex(total: float) -> None:
    """Updates only the hardware_total_eur line in the config (preserves comments)."""
    text = CONFIG.read_text()
    if re.search(r"^hardware_total_eur:", text, re.M):
        text = re.sub(r"^hardware_total_eur:.*$", f"hardware_total_eur: {total}",
                      text, flags=re.M)
    else:
        text = text.rstrip() + f"\nhardware_total_eur: {total}  # investimento TOTALE fleet\n"
    CONFIG.write_text(text)


def save_tariff(eur_kwh: float) -> None:
    """Updates only the eur_per_kwh line in the config (preserves comments)."""
    text = CONFIG.read_text()
    if re.search(r"^eur_per_kwh:", text, re.M):
        text = re.sub(r"^eur_per_kwh:.*$", f"eur_per_kwh: {eur_kwh}",
                      text, flags=re.M)
    else:
        text = text.rstrip() + f"\neur_per_kwh: {eur_kwh}\n"
    CONFIG.write_text(text)


def save_hours(h: float) -> None:
    """Updates only the hours_per_day line in the config (preserves comments)."""
    text = CONFIG.read_text()
    if re.search(r"^hours_per_day:", text, re.M):
        text = re.sub(r"^hours_per_day:.*$", f"hours_per_day: {h}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\nhours_per_day: {h}\n"
    CONFIG.write_text(text)


def save_amort_years(years: float) -> None:
    """Updates only the amort_years line in the config (preserves comments)."""
    text = CONFIG.read_text()
    if re.search(r"^amort_years:", text, re.M):
        text = re.sub(r"^amort_years:.*$", f"amort_years: {years}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\namort_years: {years}\n"
    CONFIG.write_text(text)


def amort_monthly(cfg: dict) -> float:
    """Monthly fleet amortization; 0 if depreciation=false
    (Spark bought as a private individual: capex is not a business cost)."""
    if not cfg.get("depreciation", True):
        return 0.0
    return capex_total(cfg) / (cfg["amort_years"] * 12)


def save_depreciation(enabled: bool) -> None:
    """Updates only the depreciation line in the config (preserves comments)."""
    text = CONFIG.read_text()
    flag = "true" if enabled else "false"
    if re.search(r"^depreciation:", text, re.M):
        text = re.sub(r"^depreciation:.*$", f"depreciation: {flag}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\ndepreciation: {flag}\n"
    CONFIG.write_text(text)


def save_users(n: float) -> None:
    """Aggiorna solo la riga users nel config (preserva commenti)."""
    n = max(1, int(round(n)))
    text = CONFIG.read_text()
    if re.search(r"^users:", text, re.M):
        text = re.sub(r"^users:.*$", f"users: {n}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\nusers: {n}\n"
    CONFIG.write_text(text)


def load_price_overrides() -> dict:
    """User-edited prices: {model: {in_usd,out_usd,cache_usd}}."""
    if not PRICE_OVERRIDES.exists():
        return {}
    data = yaml.safe_load(PRICE_OVERRIDES.read_text()) or {}
    return data if isinstance(data, dict) else {}


def apply_price_overrides(rows: list[dict], overrides: dict) -> int:
    """Applies user overrides to the price-list rows (in USD/1M). Returns how many."""
    n = 0
    for r in rows:
        o = overrides.get(r["model"])
        if not isinstance(o, dict):
            continue
        r["_edited"] = True
        if o.get("in_usd") is not None:
            r["in_per_1m_usd"] = float(o["in_usd"]); n += 1
        if o.get("out_usd") is not None:
            r["out_per_1m_usd"] = float(o["out_usd"]); n += 1
        if o.get("cache_usd") is not None:
            r["in_cache_per_1m_usd"] = float(o["cache_usd"]) or None; n += 1
    return n


def _fleet_public() -> list:
    """P47: fleet hosts masked (no password, only has_password) for the UI."""
    from .collect import load_fleet
    return [{"name": h["name"], "mode": h.get("mode", "ssh"), "ip": h.get("ip", ""),
             "port": h.get("port", 22), "user": h.get("user", ""),
             "has_password": bool(h.get("password"))} for h in load_fleet()]


def save_n_sparks(n: int) -> None:
    """P47: sync n_sparks with the number of machines configured in the fleet
    panel (preserves comments, same pattern as save_users)."""
    n = max(1, int(n))
    text = CONFIG.read_text()
    if re.search(r"^n_sparks:", text, re.M):
        text = re.sub(r"^n_sparks:.*$", f"n_sparks: {n}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\nn_sparks: {n}\n"
    CONFIG.write_text(text)


def save_price(model: str, field: str, eur_1m: float, usd_eur: float) -> None:
    """Saves an edited price (UI input in EUR/1M, stored in USD/1M)."""
    key = {"in": "in_usd", "out": "out_usd", "cache": "cache_usd"}[field]
    data = load_price_overrides()
    entry = data.setdefault(model, {})
    entry[key] = round(eur_1m / usd_eur, 6)
    PRICE_OVERRIDES.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def clear_price(model: str | None = None) -> None:
    """Deletes overrides (all, or a single model's): back to the online price list."""
    if model is None:
        PRICE_OVERRIDES.unlink(missing_ok=True)
        return
    data = load_price_overrides()
    data.pop(model, None)
    if data:
        PRICE_OVERRIDES.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    else:
        PRICE_OVERRIDES.unlink(missing_ok=True)


def load_cfg() -> dict:
    return yaml.safe_load(CONFIG.read_text())


# ---------------------------------------------------------------- P39 ------
# Persistent token ledger: Prometheus counters reset to zero at every restart
# of the inference server (or machine reboot). The ledger sums the deltas and
# keeps the historical TOTAL since sparkcost started running; atomic write
# (tmp+rename) on every change, like the price-list snapshot.
LEDGER = CONFIG.parent / "token_ledger.json"


def _ledger_update(counters: dict) -> dict | None:
    """Accumulates the current counters into the persistent ledger.

    Convention: last_prompt/last_gen are the last SEEN counter values;
    if the current counter is >= last_seen -> normal delta; if it is lower the
    server restarted (restart/reboot) -> add the current counter (the tail
    lost between the last poll and the restart is unrecoverable, negligible
    at a 1s poll). Returns the updated ledger, None if there is nothing to read.
    """
    if not counters.get("prompt_total") and not counters.get("gen_total"):
        return None
    now = time.time()
    led = {"prompt_total": 0.0, "gen_total": 0.0, "last_prompt": None,
           "last_gen": None, "first_ts": now, "last_ts": now}
    if LEDGER.exists():
        try:
            led.update(json.loads(LEDGER.read_text()))
        except Exception:  # noqa: BLE001 — corrupted file: restart clean, dashboard never blocks
            pass
    lp, lg = led.get("last_prompt"), led.get("last_gen")
    pt = float(counters["prompt_total"] or 0)
    gt = float(counters["gen_total"] or 0)
    if lp is None:
        dp, dg = pt, gt  # first start: count the server's current window too (since its last restart)
    elif pt >= lp:
        dp, dg = pt - lp, gt - (lg or 0.0)
    else:  # counter reset: server restart/reboot
        dp, dg = pt, gt
    led["prompt_total"] = float(led.get("prompt_total", 0.0)) + dp
    led["gen_total"] = float(led.get("gen_total", 0.0)) + dg
    led["last_prompt"], led["last_gen"], led["last_ts"] = pt, gt, now
    if dp > 0 or dg > 0 or lp is None:
        tmp = LEDGER.with_suffix(".tmp")
        tmp.write_text(json.dumps(led))
        os.replace(tmp, LEDGER)
    return led


def local_cost(cfg: dict, watts: float, tok_s: float) -> dict:
    """Local cost with an honest fixed/variable attribution.

    n_sparks: number of active fleet units — multiplies energy (measured power
    is per unit) and amortization. tok_s is the aggregate throughput.
    Variable: under-load energy per generated token.
    Fixed monthly: hardware amortization + idle energy in the unused hours.
    Effective: variable + fixed spread over the month's tokens.
    """
    n = int(cfg.get("n_sparks", 1))
    h = cfg["hours_per_day"]
    days = 30.44
    tariff = cfg["eur_per_kwh"]
    amort_month = amort_monthly(cfg)
    extra_w = None
    if cfg.get("always_on"):
        # Fleet always on: idle energy is fixed 24/7; the variable cost is
        # only the power extra above idle while generating.
        idle_kwh_month = cfg["idle_watts"] * n / 1000 * 24 * days
        idle_eur_month = idle_kwh_month * tariff
        extra_w = max(watts - cfg["idle_watts"], 0.0) * n
        kwh_per_1m = extra_w / (3.6 * tok_s) if tok_s > 0 else float("inf")
        var_eur_1m = kwh_per_1m * tariff
    else:
        # Machine powered off outside working hours: idle only during the
        # working hours (same basis as local_month_breakdown, which uses
        # idle_hours = h_day: otherwise card and break-even would diverge)
        idle_kwh_month = cfg["idle_watts"] * n / 1000 * h * days
        idle_eur_month = idle_kwh_month * tariff
        extra_w = max(watts - cfg["idle_watts"], 0.0) * n
        kwh_per_1m = extra_w / (3.6 * tok_s) if tok_s > 0 else float("inf")
        var_eur_1m = kwh_per_1m * tariff
    fixed_month = amort_month + idle_eur_month
    tokens_month = tok_s * 3600 * h * days
    eff_eur_1m = var_eur_1m + (fixed_month / tokens_month * 1e6 if tokens_month else 0)
    return {
        "n_sparks": n, "watts": watts, "watts_fleet": watts * n, "tok_s": tok_s,
        "always_on": bool(cfg.get("always_on")), "extra_watts": extra_w,
        "var_eur_1m": var_eur_1m, "kwh_per_1m": kwh_per_1m,
        "amort_month_eur": amort_month, "idle_eur_month": idle_eur_month,
        "fixed_month_eur": fixed_month, "tokens_month": tokens_month,
        "eff_eur_1m": eff_eur_1m,
    }


def _fmt_period(days: float) -> str:
    """Formats a time window: hours below 1 day, otherwise days."""
    return f"{days*24:.1f} h" if days < 1 else f"{days:.1f} days"


def replay_cost(cfg: dict, counters: dict, srv: dict, rows: list[dict],
                watts: float | None) -> dict | None:
    """Replays the same tokens generated locally against cloud price lists.

    - prompt_total / gen_total: real server counters
    - local cost of the period: real energy (measured power x uptime)
      + amortization share proportional to uptime
    - cloud cost: prompt_total x price_in + gen_total x price_out,
      in two scenarios: without cache and with cache_hit_rate on prompt tokens
    """
    pt, gt = counters.get("prompt_total"), counters.get("gen_total")
    uptime = (srv or {}).get("uptime_s")
    if not pt or not uptime:
        return None
    usd = cfg["usd_eur"]
    ch = cfg.get("cache_hit_rate", 0.9)
    n = int(cfg.get("n_sparks", 1))
    watts = watts or cfg["idle_watts"]

    # fleet: n unita' attive -> energia e ammortamento moltiplicati
    energy_kwh = watts * n * uptime / 3.6e6
    var_eur = energy_kwh * cfg["eur_per_kwh"]
    amort_month = amort_monthly(cfg)
    amort_share = amort_month * uptime / (30.44 * 86400)
    local_eur = var_eur + amort_share

    # Monthly projection from the observed hourly rate x the daily time
    # commitment (hours_per_day, default 8, editable): the machine works h
    # hours a day, not 24. Local = fixed (amortization + idle energy 24/7,
    # always on); open-weight = projected tokens; closed-weight = subscription.
    h_day = float(cfg.get("hours_per_day", 8))
    hours_u = uptime / 3600
    pt_m = pt / hours_u * h_day * 30.44
    gt_m = gt / hours_u * h_day * 30.44
    proj_basis = (f"{h_day:g} h/day machine commitment, observed over "
                  f"{_fmt_period(uptime / 86400)}")
    subs_cfg = cfg.get("subscriptions") or {}
    n_users = int(cfg.get("users", 2))
    parts = local_month_breakdown(cfg, watts)
    amort_month_full = parts["amort"]
    energy_month = parts["idle_energy"] + parts["token_energy"]
    local_month = parts["total"]

    models_out = []
    for r in rows:
        if not r["in_per_1m_usd"] and not r["out_per_1m_usd"]:
            continue
        nocache = (pt * r["in_per_1m_usd"] + gt * r["out_per_1m_usd"]) / 1e6 * usd
        cache_price = r.get("in_cache_per_1m_usd")
        wp = r.get("in_write_per_1m_usd")
        if cache_price:
            # the blend includes the cache CREATION cost: at steady state
            # every miss (share 1-ch) is written (the list's cache_creation
            # price, or 1.25x input if not exposed)
            write_price = wp if wp else r["in_per_1m_usd"] * 1.25
            blend_in = (1 - ch) * (r["in_per_1m_usd"] + write_price) + ch * cache_price
            cached = (pt * blend_in + gt * r["out_per_1m_usd"]) / 1e6 * usd
        else:
            blend_in = r["in_per_1m_usd"]
            cached = nocache
        # Batch API scenario: only if the price list exposes batch prices
        # (OpenAI/Anthropic -50%; i moltiplicatori batch si applicano a input,
        # output e prezzi cache)
        bi, bo = r.get("in_batches_per_1m_usd"), r.get("out_batches_per_1m_usd")
        if bi and bo:
            m_in = bi / r["in_per_1m_usd"] if r["in_per_1m_usd"] else 0.5
            m_out = bo / r["out_per_1m_usd"] if r["out_per_1m_usd"] else 0.5
            b_in = r["in_per_1m_usd"] * m_in
            b_cache = cache_price * m_in if cache_price else None
            b_write = ((wp if wp else r["in_per_1m_usd"] * 1.25) * m_in) if cache_price else None
            b_blend = ((1 - ch) * (b_in + b_write) + ch * b_cache) if b_cache else b_in
            batch = (pt * b_blend + gt * r["out_per_1m_usd"] * m_out) / 1e6 * usd
            batch_month = (pt_m * b_blend + gt_m * r["out_per_1m_usd"] * m_out) / 1e6 * usd
        else:
            batch = batch_month = None
        # monthly cost: subscription (top tier) for closed-weight models,
        # projected tokens at the current rate for open-weight models
        plans = subs_cfg.get(r["vendor"])
        if plans:
            top = max(plans, key=lambda x: x["usd"])
            month_cost = top["usd"] * usd * n_users
            month_basis = f"subscription: {top['plan']} x {n_users} users"
            month_sub = True
        else:
            month_cost = (pt_m * blend_in + gt_m * r["out_per_1m_usd"]) / 1e6 * usd * n_users
            month_basis = f"token @ current rate (cache {int(ch*100)}%) x {n_users} users"
            month_sub = False
        models_out.append({
            "model": r["model"], "vendor": r["vendor"],
            "cost_nocache_eur": nocache, "cost_cached_eur": cached,
            "cost_batch_eur": batch,
            "month_cost_eur": month_cost, "month_basis": month_basis,
            "month_batch_eur": batch_month * n_users if batch_month is not None else None,
            "aa_score": r.get("aa_score"),
            "users": n_users,
            "month_sub": month_sub, "edited": bool(r.get("_edited")),
            "lc_mult": r.get("lc_input_mult"),
            "in_eur_1m": r["in_per_1m_usd"] * usd,
            "out_eur_1m": r["out_per_1m_usd"] * usd,
            "cache_eur_1m": (r["in_cache_per_1m_usd"] or r["in_per_1m_usd"]) * usd,
            "vision": r["vision"], "reasoning": r["reasoning"],
        })
    models_out.sort(key=lambda x: x["cost_cached_eur"])
    return {
        "prompt_total": int(pt), "gen_total": int(gt),
        "uptime_s": uptime, "uptime_days": uptime / 86400,
        "n_sparks": n, "watts_per_unit": watts, "watts_fleet": watts * n,
        "energy_kwh": energy_kwh,
        "var_eur": var_eur, "amort_share_eur": amort_share,
        "local_eur": local_eur,
        "local_eur_1m": local_eur / (((pt + gt) or 1) / 1e6),
        "pt_m_month": pt_m, "gt_m_month": gt_m, "projection_basis": proj_basis,
        "local_month_eur": local_month, "local_month_parts": parts,
        "amort_month_eur": amort_month_full, "energy_month_eur": energy_month,
        "token_energy_month_eur": parts["token_energy"],
        "cache_hit_rate": ch,
        "models": models_out,
    }


def breakeven(cfg: dict, counters: dict, srv: dict, rows: list[dict],
              watts: float | None) -> dict | None:
    """Investment break-even: how many months of cloud savings are needed to
    repay the Sparks at the current usage rate (projected monthly).

    local_month: fleet amortization + fleet energy at measured power 24/7
    (on this hardware consumption is almost independent of tokens).
    savings = cloud_month - local_month; payback = capex / savings.
    """

    # Monthly volume: use the configured one if present (realistic),
    # otherwise project the observed rate in the window (it may be a peak).
    pt, gt = counters.get("prompt_total"), counters.get("gen_total")
    uptime = (srv or {}).get("uptime_s")
    if not pt or not uptime:
        return None
    n = int(cfg.get("n_sparks", 1))
    usd = cfg["usd_eur"]
    ch = cfg.get("cache_hit_rate", 0.9)
    n_users = int(cfg.get("users", 2))
    watts = watts or cfg["idle_watts"]
    days = uptime / 86400

    # Volume mensile: se configurato usa quello (realistico), altrimenti
    # projects the rate observed in the window (it may be a peak).
    pt_m_cfg, gt_m_cfg = cfg.get("monthly_prompt_m"), cfg.get("monthly_gen_m")
    if pt_m_cfg and gt_m_cfg:
        pt_m, gt_m = pt_m_cfg * 1e6, gt_m_cfg * 1e6
        basis = f"configured volume ({pt_m_cfg:,.0f}M prompt + {gt_m_cfg:,.0f}M gen per month)"
    else:
        h_day = float(cfg.get("hours_per_day", 8))
        hours_u = uptime / 3600
        pt_m = pt / hours_u * h_day * 30.44
        gt_m = gt / hours_u * h_day * 30.44
        basis = (f"projection from observed hourly rate ({pt/hours_u/1e6:,.0f}M prompt + "
                 f"{gt/hours_u/1e6:,.1f}M gen per hour) x {h_day:g} h/day machine commitment, "
                 f"observed over {_fmt_period(days)}")
    capex = capex_total(cfg)
    parts = local_month_breakdown(cfg, watts)
    amort_month = parts["amort"]
    energy_month = parts["idle_energy"] + parts["token_energy"]
    local_month = parts["total"]

    out = []
    for r in rows:
        if not r["in_per_1m_usd"] and not r["out_per_1m_usd"]:
            continue
        # closed-weight: subscription only (top tier), no token scenarios
        if (cfg.get("subscriptions") or {}).get(r["vendor"]):
            continue
        cloud_nocache = (pt_m * r["in_per_1m_usd"] + gt_m * r["out_per_1m_usd"]) / 1e6 * usd
        cache_price = r.get("in_cache_per_1m_usd")
        wp = r.get("in_write_per_1m_usd")
        if cache_price:
            write_price = wp if wp else r["in_per_1m_usd"] * 1.25
            blend_in = (1 - ch) * (r["in_per_1m_usd"] + write_price) + ch * cache_price
        else:
            blend_in = r["in_per_1m_usd"]
        cloud_cached = (pt_m * blend_in + gt_m * r["out_per_1m_usd"]) / 1e6 * usd
        bi, bo = r.get("in_batches_per_1m_usd"), r.get("out_batches_per_1m_usd")
        if bi and bo:
            m_in = bi / r["in_per_1m_usd"] if r["in_per_1m_usd"] else 0.5
            m_out = bo / r["out_per_1m_usd"] if r["out_per_1m_usd"] else 0.5
            b_in = r["in_per_1m_usd"] * m_in
            b_cache = cache_price * m_in if cache_price else None
            b_write = ((wp if wp else r["in_per_1m_usd"] * 1.25) * m_in) if cache_price else None
            b_blend = ((1 - ch) * (b_in + b_write) + ch * b_cache) if b_cache else b_in
            cloud_batch = (pt_m * b_blend + gt_m * r["out_per_1m_usd"] * m_out) / 1e6 * usd
        else:
            cloud_batch = None
        scens = [("no-cache", cloud_nocache * n_users, r["in_per_1m_usd"])]
        if cache_price:
            scens.append((f"cache {int(ch*100)}%", cloud_cached * n_users, blend_in))
        if cloud_batch is not None:
            scens.append(("batch API", cloud_batch * n_users, b_blend))
        for scen, cloud, in_eff in scens:
            savings = cloud - local_month
            payback_m = capex / savings if savings > 0 else None
            out.append({
                "model": r["model"], "scenario": scen, "aa_score": r.get("aa_score"),
                # in_eff = the input price EFFECTIVELY used in the calculation
                # (list price for no-cache; blended cache+list for cached)
                "in_eur_1m": r["in_per_1m_usd"] * usd,
                "in_eff_eur_1m": in_eff * usd,
                "out_eur_1m": r["out_per_1m_usd"] * usd,
                "cloud_month_eur": cloud, "savings_month_eur": savings,
                "payback_months": payback_m,
                "payback_days": payback_m * 30.44 if payback_m else None,
            })
    # Closed-weight models: in the real world human chat usage goes through
    # monthly SUBSCRIPTIONS, not tokens. A subscription covers its owner's
    # typical usage at a fixed cost: that is the honest break-even comparison.
    # (Per-token APIs remain available for heavy programmatic usage.)
    for m in rows:
        plans = (cfg.get("subscriptions") or {}).get(m["vendor"], [])
        for plan in plans:
            cloud = plan["usd"] * usd * n_users
            savings = cloud - local_month
            payback_m = capex / savings if savings > 0 else None
            out.append({
                "model": m["model"], "scenario": f"{plan['plan']} (sub)", "aa_score": m.get("aa_score"),
                "in_eur_1m": m["in_per_1m_usd"] * usd,
                "in_eff_eur_1m": m["in_per_1m_usd"] * usd,
                "out_eur_1m": m["out_per_1m_usd"] * usd,
                "cloud_month_eur": cloud, "savings_month_eur": savings,
                "payback_months": payback_m,
                "payback_days": payback_m * 30.44 if payback_m else None,
            })
    # payback crescente; mai (None) in fondo
    out.sort(key=lambda x: (x["payback_months"] is None, x["payback_months"] or 0))
    bk = {
        "capex": capex, "usage_days": days,
        "prompt_per_day": pt / days, "gen_per_day": gt / days,
        "prompt_m_month": pt_m, "gen_m_month": gt_m,
        "amort_month_eur": amort_month, "energy_month_eur": energy_month,
        "token_energy_month_eur": parts["token_energy"],
        "local_month_parts": parts, "users": n_users,
        "local_month_eur": local_month, "basis": basis, "scenarios": out,
    }
    if not cfg.get("depreciation", True):
        # "cash" payback: the spent capex stays in the calculation even at zero amortization
        bk["capex_note"] = ("cash payback: the full investment is counted even "
                            "though depreciation is off")
    return bk


def blended_cloud(row: dict, ratio: float, usd_eur: float) -> float | None:
    if not row["in_per_1m_usd"] and not row["out_per_1m_usd"]:
        return None
    return (ratio * row["in_per_1m_usd"] + row["out_per_1m_usd"]) / (ratio + 1) * usd_eur


def repaid(cfg: dict, ledger: dict | None, rows: list[dict],
           local_eur_1m: float | None) -> dict | None:
    """Capex repaid by real usage, up to date (P39).

    Compares the cloud-equivalent cost of the LEDGER's historical tokens
    (since sparkcost started running, surviving server restarts) with the
    local cost of the same tokens at the measured rate. The difference is
    the accumulated savings: the share of capex that usage has already repaid.
    Stated basis: measured local rate applied to the whole history.
    """
    if not ledger or not (ledger.get("prompt_total") or ledger.get("gen_total")):
        return None
    pt = float(ledger.get("prompt_total") or 0)
    gt = float(ledger.get("gen_total") or 0)
    capex = capex_total(cfg)
    usd = cfg["usd_eur"]
    ch = cfg.get("cache_hit_rate", 0.9)
    mtok = (pt + gt) / 1e6
    local_cost_eur = (local_eur_1m or 0.0) * mtok
    out = []
    for r in rows:
        if not r["in_per_1m_usd"] and not r["out_per_1m_usd"]:
            continue
        cloud_nocache = (pt * r["in_per_1m_usd"] + gt * r["out_per_1m_usd"]) / 1e6 * usd
        cache_price = r.get("in_cache_per_1m_usd")
        wp = r.get("in_write_per_1m_usd")
        if cache_price:
            write_price = wp if wp else r["in_per_1m_usd"] * 1.25
            blend_in = (1 - ch) * (r["in_per_1m_usd"] + write_price) + ch * cache_price
        else:
            blend_in = r["in_per_1m_usd"]
        cloud_cached = (pt * blend_in + gt * r["out_per_1m_usd"]) / 1e6 * usd
        savings = cloud_cached - local_cost_eur
        out.append({
            "model": r["model"],
            "cloud_nocache_eur": cloud_nocache,
            "cloud_cached_eur": cloud_cached,
            "savings_cached_eur": savings,
            "repaid_pct": max(0.0, savings) / capex * 100.0,
        })
    out.sort(key=lambda x: x["savings_cached_eur"], reverse=True)
    return {"prompt_total": pt, "gen_total": gt,
            "first_ts": ledger.get("first_ts"), "last_ts": ledger.get("last_ts"),
            "local_cost_eur": local_cost_eur, "capex": capex, "models": out}


def report(do_measure: bool = False, refresh: bool = False,
           local_key: str | None = None) -> dict:
    cfg = load_cfg()
    srv = detect_server()
    tok_s, watts, measured = cfg["assumed_tok_s"], cfg["idle_watts"], False
    energy_source: dict = {"mode": "assumed"}
    if do_measure:
        m = measure(10)
        watts = m["watts"] or watts
        if m["decode_tok_s"] > 0 or m["prefill_tok_s"] > 0:
            tok_s = max(m["decode_tok_s"], m["prefill_tok_s"])
            measured = True
        energy_source = {"mode": "measure-window"}
    else:
        # P41: time-weighted power (trapezoid) over the LAST 30 MIN (bounded by
        # uptime if shorter) — il rate operativo ATTUALE, non la media di tutto
        # lo storico affogata nell'idle (15.8 W/unit vs 58 W live, cross-check
        # sparkDash/nvidia-smi 2026-10-22). Fallback: lettura spot nvidia-smi.
        integ = (integrated_watts(window_s=min(int(srv["uptime_s"]), 1800))
                 if srv and srv.get("uptime_s") else None)
        if integ:
            # P46: per-host mode -> watts_unit = SOMMA/n_host rispondenti; i costi
            # sono lineari quindi local_cost(watts=unit)*n ricompone la somma esatta.
            watts = integ.get("watts_unit", integ["watts_avg"])
            energy_source = {"mode": "integrated", "samples": integ["samples"],
                             "span_s": integ["span_s"], "from_ts": integ["from_ts"],
                             "to_ts": integ["to_ts"]}
            if integ.get("per_host"):
                energy_source["per_host"] = integ["per_host"]
        else:
            watts = read_watts() or watts
            energy_source = {"mode": "spot"}
    lc = local_cost(cfg, watts, tok_s)
    data = models.download_snapshot() if refresh else models.fetch_snapshot()
    rows = models.extract(data)
    ov = load_price_overrides()
    ov_applied = apply_price_overrides(rows, ov)
    ratio = cfg["in_out_ratio"]
    table = []
    for r in rows:
        bl = blended_cloud(r, ratio, cfg["usd_eur"])
        if bl is not None:
            table.append({"model": r["model"], "vendor": r["vendor"],
                          "blended_eur_1m": bl,
                          "in_eur_1m": r["in_per_1m_usd"] * cfg["usd_eur"],
                          "out_eur_1m": r["out_per_1m_usd"] * cfg["usd_eur"],
                          "ctx_in": r["ctx_in"], "vision": r["vision"],
                          "reasoning": r["reasoning"]})
    table.sort(key=lambda x: x["blended_eur_1m"])
    counters = read_counters(srv["port"]) if srv else {}
    detected_name = srv.get("name") if srv else None
    local_model = models.resolve_local_model(
        data, detected_name, local_key or cfg.get("local_model_key"))
    replay = replay_cost(cfg, counters, srv, rows, watts)
    bk = breakeven(cfg, counters, srv, rows, watts)
    # P39: ledger persistente + capex ripagato dall'uso reale
    led = None
    if counters:
        try:
            led = _ledger_update(counters)
        except Exception:  # noqa: BLE001 — il ledger non deve mai bloccare il report
            led = None
    rep = None
    if led:
        rp_local_1m = replay["local_eur_1m"] if replay else lc.get("eff_eur_1m")
        try:
            rep = repaid(cfg, led, rows, rp_local_1m)
        except Exception:  # noqa: BLE001
            rep = None
    rates = _live_rates(counters) if counters else None
    # Aligns the card's effective costs with the measured data (same basis as
    # the table): the old eff (assumed tok/s x hours_per_day) contradicted the
    # 24/7 high-volume fleet and showed 7.29 EUR/1M against 0.03 measured.
    if replay:
        lc["eff_eur_1m"] = replay["local_eur_1m"]
        lc["var_eur_1m"] = replay["var_eur"] / (((replay["prompt_total"] + replay["gen_total"]) or 1) / 1e6)
        lc["basis"] = f"measured period ({_fmt_period(replay['uptime_days'])})"
    else:
        lc["basis"] = "assumed regime (tok/s and hours from config)"
    return {"cfg": cfg, "local": lc, "measured": measured, "cloud": table,
            "server": srv or {}, "counters": counters, "replay": replay,
            "rates": rates, "ledger": led, "repaid": rep, "fleet": _fleet_public(),
            "energy_source": energy_source,
            "breakeven": bk, "local_model": local_model,
            "capex_eur": capex_total(cfg),
            "local_options": [{"key": m["key"], "label": m["label"]}
                              for m in models.LOCAL_MODELS],
            "snapshot_age_h": models.snapshot_age_h(),
            "price_overrides": {k: sorted(v.keys()) for k, v in ov.items()},
            "overrides_applied": ov_applied}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="re-download the price list before the report")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = report(args.measure, refresh=args.refresh)
    if args.json:
        import json
        print(json.dumps(rep, indent=2, default=str))
        return 0
    lc, cfg = rep["local"], rep["cfg"]
    src = "live measurement" if rep["measured"] else f"assumed {lc['tok_s']:.0f} tok/s (config)"
    print(f"== LOCAL COST ({src}) — {lc['n_sparks']} Spark fleet ==")
    print(f"power {lc['watts_fleet']:.0f} W ({lc['n_sparks']} x {lc['watts']:.0f} W) | "
          f"{lc['tok_s']:.0f} tok/s agg. | {lc['kwh_per_1m']:.2f} kWh/1M tok")
    print(f"variable: EUR {lc['var_eur_1m']:.2f}/1M tok")
    _m = "24/7" if cfg.get("always_on") else f"{24-cfg['hours_per_day']}h non-active"
    print(f"fixed    : EUR {lc['fixed_month_eur']:.0f}/month "
          f"(amortization {lc['amort_month_eur']:.0f} + idle {lc['idle_eur_month']:.0f}, fleet {_m})")
    print(f"=> EUR {lc['eff_eur_1m']:.2f}/1M token ({lc.get('basis', 'assumed')})\n")
    print(f"== CLOUD COMPARISON (blend {cfg['in_out_ratio']}:1 in:out, USD->EUR {cfg['usd_eur']}) ==")
    print(f"{'Model':<26} {'blend EUR/1M':>12} {'in':>8} {'out':>8}  {'ctx':>9}  cap.")
    loc = lc["eff_eur_1m"]
    print(f">>> LOCAL DGX Spark        {loc:>12.2f} {'':>8} {'':>8}  {'1048576':>9}  local")
    for r in rep["cloud"]:
        caps = ("V" if r["vision"] else "") + ("R" if r["reasoning"] else "")
        print(f"{r['model']:<26} {r['blended_eur_1m']:>12.2f} "
              f"{r['in_eur_1m']:>8.2f} {r['out_eur_1m']:>8.2f}  {str(r['ctx_in'] or '-'):>9}  {caps}")

    rp = rep.get("replay")
    if rp:
        print(f"\n== YOUR TOKENS ON THE CLOUD (same tokens generated locally) ==")
        print(f"period: {rp['uptime_days']:.1f} days | {rp['prompt_total']/1e6:,.1f}M prompt + "
              f"{rp['gen_total']/1e6:,.2f}M generated")
        print(f"actual local cost: EUR {rp['local_eur']:.2f} "
              f"({rp['local_eur_1m']:.2f} EUR/1M extrapolated) "
              f"(energy {rp['energy_kwh']:.1f} kWh = {rp['var_eur']:.2f} + amort. {rp['amort_share_eur']:.2f})\n")
        print(f"{'Model':<26} {'no cache':>12} {'cache 90%':>14} {'batch API':>12} {'vs local':>10}")
        for m in rp["models"][:15]:
            ratio_s = f"x{m['cost_cached_eur']/rp['local_eur']:.1f}" if rp['local_eur'] > 0 else "-"
            _b = m.get("cost_batch_eur")
            _bs = f"EUR {_b:>8.2f}" if _b is not None else "     —"
            print(f"{m['model']:<26} EUR {m['cost_nocache_eur']:>8.2f} "
                  f"EUR {m['cost_cached_eur']:>9.2f} {_bs:>12} {ratio_s:>10}")

    bk = rep.get("breakeven")
    if bk:
        print(f"\n== INVESTMENT BREAK-EVEN (EUR {bk['capex']:,.2f}) ==")
        print(f"calculation basis: {bk['basis']}")
        print(f"-> {bk['prompt_m_month']/1e9:,.2f}B prompt + {bk['gen_m_month']/1e6:,.0f}M gen/month")
        print(f"local cost/month: EUR {bk['local_month_eur']:.0f} (amort {bk['amort_month_eur']:.0f} + energy {bk['energy_month_eur']:.0f})\n")
        print(f"{'Model':<26} {'scenario':>10} {'cloud/month':>11} {'savings':>10} {'payback':>12}")
        for s in bk["scenarios"][:14]:
            if s["payback_days"]:
                pb = f"{s['payback_days']:.0f} days" if s["payback_days"] < 400 else f"{s['payback_months']:.1f} months"
            else:
                pb = "never"
            print(f"{s['model']:<26} {s['scenario']:>10} EUR {s['cloud_month_eur']:>8.0f} "
                  f"EUR {s['savings_month_eur']:>8.0f} {pb:>12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
