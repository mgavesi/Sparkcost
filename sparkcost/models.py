"""Cloud model catalog: LiteLLM price list + capabilities, with a local snapshot.

Usage:
    python3 -m sparkcost.models                       # top-vendor table
    python3 -m sparkcost.models --refresh             # refresh the snapshot from GitHub
    python3 -m sparkcost.models --vendor anthropic    # filter by vendor
    python3 -m sparkcost.models --csv                 # CSV output
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "litellm_snapshot.json"

# Peer set of GLM-5.3-Flash (the local model): only models with similar or
# better agentic/coding/vision/tool-use capability according to public
# benchmarks (Terminal-Bench 2.1, SWE-bench, Toolathlon, Artificial Analysis v4.3).
# Sources verified 2026-10-14: qubrid.com, llm-stats, intelligentliving, oxalpha.
# Lower-capability models are excluded: they are not a sensible comparison
# for break-even and replay.
PEER_MODELS = [
    # (exact key in the price list, short label, vendor)
    ("baseten/zai-org/GLM-5.3-Flash", "GLM 5.3 Flash (cloud)", "Z.ai"),  # the same model in the cloud
    # OpenAI: all recent flagship families (mini/nano/luna and legacy 4.x/3.x
    # excluded for lower capability, plus dated/-chat-latest/search/audio duplicates)
    ("gpt-6-astra", "GPT-6 Astra", "OpenAI"),
    ("gpt-6.1-sol", "GPT-6.1 Sol", "OpenAI"),
    ("gpt-6-sol", "GPT-6 Sol", "OpenAI"),
    ("gpt-5.6", "GPT-5.6", "OpenAI"),
    ("gpt-5.6-sol", "GPT-5.6 Sol", "OpenAI"),
    ("gpt-5.6-terra", "GPT-5.6 Terra", "OpenAI"),
    ("gpt-5.6-cyber", "GPT-5.6 Cyber", "OpenAI"),
    ("gpt-5.5", "GPT-5.5", "OpenAI"),
    ("gpt-5.5-cyber", "GPT-5.5 Cyber", "OpenAI"),
    ("gpt-5.4", "GPT-5.4", "OpenAI"),
    ("gpt-5.2", "GPT-5.2", "OpenAI"),
    ("gpt-5.1", "GPT-5.1", "OpenAI"),
    ("gpt-5", "GPT-5", "OpenAI"),
    # Anthropic: all current models (Haiku excluded for lower capability,
    # plus preview/region/provider-duplicate variants)
    ("claude-mythos-5-1", "Claude Mythos 5.1", "Anthropic"),
    ("claude-mythos-5", "Claude Mythos 5", "Anthropic"),
    ("claude-fable-5-1", "Claude Fable 5.1", "Anthropic"),
    ("claude-fable-5", "Claude Fable 5", "Anthropic"),
    ("claude-opus-5", "Claude Opus 5", "Anthropic"),
    ("claude-opus-5-5", "Claude Opus 5.5", "Anthropic"),
    ("claude-opus-4-8", "Claude Opus 4.8", "Anthropic"),
    ("claude-opus-4-7", "Claude Opus 4.7", "Anthropic"),
    ("claude-opus-4-6", "Claude Opus 4.6", "Anthropic"),
    ("claude-opus-4-5", "Claude Opus 4.5", "Anthropic"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", "Anthropic"),
    ("claude-sonnet-5", "Claude Sonnet 5", "Anthropic"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6", "Anthropic"),
    ("claude-sonnet-4-5", "Claude Sonnet 4.5", "Anthropic"),
    # Google / DeepSeek / Moonshot / Qwen / xAI
    ("gemini-3.8-flash", "Gemini 3.8 Flash", "Google"),  # direct peer (AA v4.3)
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro", "Google"),
    ("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", "DeepSeek"),  # SWE 80.6%
    ("moonshot/kimi-k3", "Kimi K3", "Moonshot"),
    ("dashscope/qwen-max", "Qwen Max", "Qwen"),
    ("xai/grok-4.6", "Grok 4.6", "xAI"),
]


def fetch_snapshot(force: bool = False) -> dict:
    """Load the local snapshot; download from GitHub if absent or --refresh."""
    if not force and SNAPSHOT.exists():
        age_h = (time.time() - SNAPSHOT.stat().st_mtime) / 3600
        with open(SNAPSHOT) as f:
            data = json.load(f)
        if age_h > 24:
            print(f"# snapshot age {age_h:.0f}h — use --refresh to update",
                  file=sys.stderr)
        return data
    return download_snapshot()


def download_snapshot() -> dict:
    import os
    print(f"# downloading {LITELLM_URL} ...", file=sys.stderr)
    with urllib.request.urlopen(LITELLM_URL, timeout=60) as r:
        data = json.load(r)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    # atomic write: tmp + rename (avoids partial reads during the refresh)
    tmp = SNAPSHOT.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, SNAPSHOT)
    print(f"# snapshot saved: {SNAPSHOT} ({len(data)} entries)", file=sys.stderr)
    return data


def snapshot_age_h() -> float | None:
    """Price-list snapshot age in hours (None if absent)."""
    if not SNAPSHOT.exists():
        return None
    return (time.time() - SNAPSHOT.stat().st_mtime) / 3600


# ---------------------------------------------------------------- P37 ------
# Independent second source: aitokenprice.com (api/models.json, site-verified
# prices). COMPARISON ONLY: never an override of the LiteLLM price list —
# the result is a consistency report.
ATP_URL = "https://aitokenprice.com/api/models.json"
ATP_SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "atp_snapshot.json"

# Rinomi note aitp vs chiavi LiteLLM (il matching normalizzato copre il resto).
ATP_ALIASES = {
    "baseten/zai-org/GLM-5.3-Flash": ["GLM-5.3 Flash"],
    "dashscope/qwen-max": ["Qwen3.8 Max", "Qwen Max"],
    "xai/grok-4.6": ["Grok 4.7", "Grok 4.6"],
}


def download_atp() -> list:
    """Download the aitokenprice price list and store it atomically."""
    import os
    print(f"# downloading {ATP_URL} ...", file=sys.stderr)
    req = urllib.request.Request(ATP_URL, headers={"User-Agent": "sparkcost-crosscheck/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    items = data.get("models", data) if isinstance(data, dict) else data
    ATP_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    tmp = ATP_SNAPSHOT.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(items, f)
    os.replace(tmp, ATP_SNAPSHOT)  # atomic: the dashboard re-reads without racing
    print(f"# aitp snapshot saved: {ATP_SNAPSHOT} ({len(items)} entries)", file=sys.stderr)
    return items


def load_atp(refresh: bool = False) -> list:
    if not refresh and ATP_SNAPSHOT.exists():
        with open(ATP_SNAPSHOT) as f:
            return json.load(f)
    return download_atp()


def atp_age_h() -> float | None:
    """aitokenprice snapshot age in hours (None if absent)."""
    if not ATP_SNAPSHOT.exists():
        return None
    return (time.time() - ATP_SNAPSHOT.stat().st_mtime) / 3600


def _norm(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _atp_price(m: dict) -> tuple:
    p = m.get("price") or {}
    return _num(p.get("input")), _num(p.get("output")), _num(p.get("cacheRead"))


def crosscheck(data: dict, atp_items: list) -> list[dict]:
    """Confronta i prezzi del peer set (LiteLLM) con aitokenprice.
    Ritorna righe {model, litellm, atp, delta, status} con status in
    OK | DELTA | NO_ATP | NO_PRICE (LEGACY-* if only a non-current version matched).
    Tolleranza 0.011 $/1M (un centesimo)."""
    by_norm: dict[str, list] = {}
    for m in atp_items:
        by_norm.setdefault(_norm(m.get("name", "")), []).append(m)

    out = []
    for key, label, _vendor in PEER_MODELS:
        row = _row_for_key(data, key, label, _vendor)
        lit = ({"in": row["in_per_1m_usd"], "out": row["out_per_1m_usd"],
                "cache": row["in_cache_per_1m_usd"]} if row else None)

        cand = None
        for alias in ATP_ALIASES.get(key, []):
            if _norm(alias) in by_norm:
                cand = by_norm[_norm(alias)]
                break
        if cand is None and _norm(label) in by_norm:
            cand = by_norm[_norm(label)]  # exact match
        if cand is None:  # fallback: containment (e.g. preview key -> short name)
            ns = _norm(label)
            hits = [(n, v) for n, v in by_norm.items()
                    if n and min(len(n), len(ns)) >= 8 and (n in ns or ns in n)]
            if len(hits) == 1:
                cand = hits[0][1]
            elif len(hits) > 1:
                # prefer current status, then the shortest name
                cand = sorted(hits, key=lambda h: (
                    all(m.get("status") != "current" for m in h[1]), len(h[0])))[0][1]

        if not cand:
            out.append({"model": label, "litellm": lit, "atp": None,
                        "delta": None, "status": "NO_ATP"})
            continue
        m = cand[0]
        ai, ao, ac = _atp_price(m)
        if ai is None or ao is None:
            out.append({"model": label, "litellm": lit,
                        "atp": {"in": ai, "out": ao, "cache": ac,
                                "status": m.get("status")},
                        "delta": None, "status": "NO_PRICE"})
            continue
        delta = {"in": round(ai - lit["in"], 3), "out": round(ao - lit["out"], 3)}
        if lit["cache"] and ac:
            delta["cache"] = round(ac - lit["cache"], 3)
        worst = max(abs(v) for v in delta.values())
        status = "OK" if worst < 0.011 else "DELTA"
        if m.get("status") != "current" and status == "OK":
            status = "LEGACY-OK"  # same price, but aitp no longer lists it as current
        out.append({"model": label, "litellm": lit,
                    "atp": {"in": ai, "out": ao, "cache": ac,
                            "status": m.get("status")},
                    "delta": delta, "status": status})
    return out


def render_crosscheck(rows: list[dict]) -> str:
    def f(v):
        return "—" if v is None else f"{v:,.2f}".replace(",", "'")

    hdr = (f"{'Model':<22} {'LiteLLM $ in/out':>22} "
           f"{'aitp $ in/out':>18} {'Δ in/out':>16}  result")
    lines = [hdr, "-" * len(hdr)]
    for r in rows:
        lit, atp = r["litellm"], r.get("atp")
        if lit and atp and atp.get("in") is not None:
            ltxt = f"{f(lit['in'])} / {f(lit['out'])}"
            atxt = f"{f(atp['in'])} / {f(atp['out'])}"
            dtxt = (f"{r['delta']['in']:+.2f} / {r['delta']['out']:+.2f}"
                    if r.get("delta") else "—")
        elif lit:
            ltxt, atxt, dtxt = f"{f(lit['in'])} / {f(lit['out'])}", "—", "—"
        else:
            ltxt, atxt, dtxt = "—", "—", "—"
        lines.append(f"{r['model'][:22]:<22} {ltxt:>22} {atxt:>18} {dtxt:>16}  {r['status']}")
    return "\n".join(lines)


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) else None


def _above_input_mult(entry: dict) -> float | None:
    """Input-price multiplier above the long-context threshold (e.g. 272k
    OpenAI: 2x), None if the price list does not define one."""
    base = _num(entry.get("input_cost_per_token"))
    above = _num(entry.get("input_cost_per_token_above_272k_tokens"))
    if base and above:
        return above / base
    return None


def extract(data: dict, limit: int | None = None) -> list[dict]:
    """Normalized rows: prices per 1M tokens, ctx, capability."""
    rows = []
    seen = set()
    wanted = PEER_MODELS if limit is None else PEER_MODELS[:limit]
    for key, label, vendor in wanted:
        entry = data.get(key)
        if not isinstance(entry, dict):
            # try variants: pick the shortest base key matching the prefix
            cand = sorted((k for k in data if k.startswith(key)), key=len)
            if not cand:
                continue
            entry = data[cand[0]]
        if key in seen:
            continue
        seen.add(key)
        mode = entry.get("mode", "?")
        rows.append({
            "model": label,
            "litellm_key": key,
            "vendor": vendor,
            "in_per_1m_usd": (_num(entry.get("input_cost_per_token")) or 0) * 1e6,
            "out_per_1m_usd": (_num(entry.get("output_cost_per_token")) or 0) * 1e6,
            "in_cache_per_1m_usd": (
                (_num(entry.get("cache_read_input_token_cost")) or 0) * 1e6
                or None
            ),
            "in_write_per_1m_usd": (
                (_num(entry.get("cache_creation_input_token_cost")) or 0) * 1e6
                or None
            ),
            "in_batches_per_1m_usd": (
                (_num(entry.get("input_cost_per_token_batches")) or 0) * 1e6
                or None
            ),
            "out_batches_per_1m_usd": (
                (_num(entry.get("output_cost_per_token_batches")) or 0) * 1e6
                or None
            ),
            "in_cache_batches_per_1m_usd": (
                (_num(entry.get("cache_read_input_token_cost_batches")) or 0) * 1e6
                or None
            ),
            "lc_input_mult": _above_input_mult(entry),
            "ctx_in": entry.get("max_input_tokens") or entry.get("max_tokens"),
            "ctx_out": entry.get("max_output_tokens"),
            "vision": bool(entry.get("supports_vision")),
            "reasoning": bool(entry.get("supports_reasoning")),
            "function_calling": bool(entry.get("supports_function_calling", mode == "chat")),
        })
    return rows


# Known local (self-hosted) models and their cloud counterparts for comparison.
# "match" = aliases (lowercase) searched in the server name/model detected from ps;
# the longest alias wins (e.g. glm-5.3-flash beats glm-5.3).
LOCAL_MODELS = [
    {"key": "baseten/zai-org/GLM-5.3-Flash", "label": "GLM 5.3 Flash",
     "vendor": "Z.ai", "match": ["glm-5.3-flash", "glm_5.3_flash"]},
    {"key": "baseten/zai-org/GLM-5.3-Fast", "label": "GLM 5.3 Fast",
     "vendor": "Z.ai", "match": ["glm-5.3-fast"]},
    {"key": "baseten/zai-org/GLM-5.3", "label": "GLM 5.3",
     "vendor": "Z.ai", "match": ["glm-5.3", "glm5.3"]},
    {"key": "baseten/zai-org/GLM-5.2", "label": "GLM 5.2",
     "vendor": "Z.ai", "match": ["glm-5.2"]},
    {"key": "baseten/zai-org/GLM-4.7", "label": "GLM 4.7",
     "vendor": "Z.ai", "match": ["glm-4.7"]},
    {"key": "deepseek/deepseek-v4-flash", "label": "DeepSeek V4 Flash",
     "vendor": "DeepSeek", "match": ["deepseek-v4-flash"]},
    {"key": "deepinfra/google/gemini-2.5-flash", "label": "Gemini 2.5 Flash",
     "vendor": "Google", "match": ["gemini-2.5-flash"]},
]


def _row_for_key(data: dict, key: str, label: str, vendor: str) -> dict | None:
    """Normalized row (same shape as extract) for a price-list key."""
    entry = data.get(key)
    if not isinstance(entry, dict):
        cand = sorted((k for k in data if k.startswith(key)), key=len)
        if not cand:
            return None
        entry = data[cand[0]]
    mode = entry.get("mode", "?")
    return {
        "model": label,
        "litellm_key": key,
        "vendor": vendor,
        "in_per_1m_usd": (_num(entry.get("input_cost_per_token")) or 0) * 1e6,
        "out_per_1m_usd": (_num(entry.get("output_cost_per_token")) or 0) * 1e6,
        "in_cache_per_1m_usd": (
            (_num(entry.get("cache_read_input_token_cost")) or 0) * 1e6 or None),
        "in_write_per_1m_usd": (
            (_num(entry.get("cache_creation_input_token_cost")) or 0) * 1e6 or None),
        "in_batches_per_1m_usd": (
            (_num(entry.get("input_cost_per_token_batches")) or 0) * 1e6 or None),
        "out_batches_per_1m_usd": (
            (_num(entry.get("output_cost_per_token_batches")) or 0) * 1e6 or None),
        "in_cache_batches_per_1m_usd": (
            (_num(entry.get("cache_read_input_token_cost_batches")) or 0) * 1e6 or None),
        "lc_input_mult": _above_input_mult(entry),
        "ctx_in": entry.get("max_input_tokens") or entry.get("max_tokens"),
        "ctx_out": entry.get("max_output_tokens"),
        "vision": bool(entry.get("supports_vision")),
        "reasoning": bool(entry.get("supports_reasoning")),
        "function_calling": bool(entry.get("supports_function_calling", mode == "chat")),
    }


def resolve_local_model(data: dict, detected: str | None,
                        override_key: str | None = None) -> dict:
    """Resolves the local model: explicit override, otherwise auto-detect
    from the server name detected in ps. Returns {key,label,detected,cloud_row}."""
    if override_key:
        for m in LOCAL_MODELS:
            if m["key"] == override_key:
                return {"key": m["key"], "label": m["label"], "detected": False,
                        "cloud_row": _row_for_key(data, m["key"], m["label"], m["vendor"])}
        # free-form key not in the catalog: still try to resolve it
        return {"key": override_key, "label": override_key, "detected": False,
                "cloud_row": _row_for_key(data, override_key, override_key, "?")}
    if detected:
        low = detected.lower()
        best = None
        for m in LOCAL_MODELS:
            for alias in m["match"]:
                if alias in low and (best is None or len(alias) > best[0]):
                    best = (len(alias), m)
        if best:
            m = best[1]
            return {"key": m["key"], "label": m["label"], "detected": True,
                    "cloud_row": _row_for_key(data, m["key"], m["label"], m["vendor"])}
    return {"key": None, "label": None, "detected": False, "cloud_row": None}


def render(rows: list[dict], as_csv: bool = False) -> str:
    if as_csv:
        import io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue()

    def fmt(v, suffix=""):
        if v is None:
            return "—"
        return f"{v:,.2f}".replace(",", "'") + suffix

    hdr = f"{'Model':<20} {'IN $/1M':>10} {'OUT $/1M':>10} {'Cache':>8} {'Ctx IN':>9} {'Vis':>4} {'Reas':>5} {'FC':>3}"
    lines = [hdr, "-" * len(hdr)]
    for r in rows:
        lines.append(
            f"{r['model']:<20} {fmt(r['in_per_1m_usd']):>10} "
            f"{fmt(r['out_per_1m_usd']):>10} "
            f"{fmt(r['in_cache_per_1m_usd']) if r['in_cache_per_1m_usd'] else '—':>8} "
            f"{(str(r['ctx_in'] or '—') if r['ctx_in'] else '—'):>9} "
            f"{'✓' if r['vision'] else '·':>4} "
            f"{'✓' if r['reasoning'] else '·':>5} "
            f"{'✓' if r['function_calling'] else '·':>3}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="sparkcost model catalog")
    ap.add_argument("--refresh", action="store_true", help="re-download the snapshot")
    ap.add_argument("--vendor", help="filter by vendor (substring)")
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--crosscheck", action="store_true",
                    help="verify peer-set prices on aitokenprice (second source)")
    ap.add_argument("--crosscheck-cached", action="store_true",
                    help="crosscheck senza rete: usa data/atp_snapshot.json")
    args = ap.parse_args()

    if args.crosscheck or args.crosscheck_cached:
        data = fetch_snapshot()
        try:
            atp = load_atp(refresh=args.crosscheck)  # default: scarica fresco
        except Exception as e:  # noqa: BLE001 — offline: fallback cache
            if not ATP_SNAPSHOT.exists():
                raise
            print(f"# aitp download failed ({e}), using the cache", file=sys.stderr)
            atp = load_atp()
        rows = crosscheck(data, atp)
        n_ok = sum(1 for r in rows if r["status"] == "OK")
        n_delta = sum(1 for r in rows if "DELTA" in r["status"])
        print(render_crosscheck(rows))
        print(f"\naligned {n_ok} | delta {n_delta} | "
              f"not on aitp {sum(1 for r in rows if r['status'] == 'NO_ATP')}")
        return 0

    data = download_snapshot() if args.refresh else fetch_snapshot()
    rows = extract(data, limit=args.limit)
    if args.vendor:
        v = args.vendor.lower()
        rows = [r for r in rows if v in r["vendor"].lower() or v in r["litellm_key"]]
    if not rows:
        print("No model found (check TOP_MODELS in sparkcost/models.py)",
              file=sys.stderr)
        return 1
    print(render(rows, as_csv=args.csv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
