# DEV.md — sparkcost

Python tool "in the sparkDash style" for token/cost statistics of local inference (DGX Spark) and comparison with cloud providers.

## Target metric
Cost per 1M local tokens = (€/kWh × average kW) / (tok/s × 3600) × 1e6, computed on real measurements (nvidia-smi power draw + tensorfold counters), not on estimates.

## Phases

### P0 — Scaffolding ✅
- [x] Git repo `~/tools/sparkcost`, layout `sparkcost/`, `data/`, `tests/`
- Criterion: repo exists, git init ok ✅

### P1 — Cloud model catalog (price list + capability) ✅
- [x] `sparkcost/models.py`: LiteLLM JSON snapshot in `data/` (with timestamp), normalized extraction
- [x] CLI: `python3 -m sparkcost.models` → table of input/output prices per 1M tok, ctx, vision/reasoning/fc
- Criterion: table with ≥ 20 models from ≥ 5 vendors, snapshot saved

### P2 — Local metrics collector
- [x] `sparkcost/collect.py`: delta of the tensorfold `/metrics` endpoint (:8888, server name re-confirmed via ps) + nvidia-smi power
- [x] SQLite `data/sparkcost.sqlite`: `samples` table (ts, prefill_tok, decode_tok, watts) and `tokens_total`
- Criterion: two consecutive runs return consistent tok/s; DB rows grow

### P3 — Local cost engine
- [x] `sparkcost/localcost.py`: cost per 1M token from measured power, €/kWh rate, amortized hardware price
- [x] Config `data/config.yaml` (rate, hardware capex, amortization years, usd→eur)
- Criterion: output = local €/1M token + direct comparison with the vendors in the table

### P4 — sparkDash-style dashboard
- [x] `sparkcost/serve.py`: FastAPI + dark card page (auto-refresh), `/api/summary` endpoint
- Criterion: page opens on :8900, shows live local cost and the cloud table

### P5 — Tests + final commit
- [x] end-to-end smoke test, commit

### P6 — "Same tokens on the clouds" replay ✅ (2026-10-14, owner request)
- [x] `collect.detect_server` returns pid + uptime (ps -eo pid,etimes,args)
- [x] `localcost.replay_cost`: real prompt_total/gen_total → cost on each cloud price list, 2 scenarios (no cache / cache 90%); local cost of the period = real energy (W×uptime) + proportional amortization
- [x] Dashboard: "Your tokens on the clouds" section
- Criterion: API exposes `replay` with consistent numbers ✅
- urllib fix: ProxyHandler({}) to bypass the egress proxy on localhost (502)

### P7 — Fleet x2 + real capex ✅ (2026-10-14, owner request)
- [x] `n_sparks` in config (default 2): multiplies energy (measured watts = per unit) and amortization
- [x] real capex: €8,856.94 total → hardware_eur 4428.47/unit
- Criterion: CLI/API show fleet watts and x2 fixed cost ✅
- Note: pkill/pgrep with a pattern containing the process string kills its own shell — use `fuser -k <port>/tcp`

### P8 — Investment break-even ✅ (2026-10-14, owner request)
- [x] `localcost.breakeven`: real usage rate (counters/uptime) projected onto the month → cloud/month per model and scenario (no-cache / cache 90%) → payback = capex / monthly_savings
- [x] Local cost/month = fleet amortization + fleet energy 24/7 (€25/month at 156W, almost independent of tokens)
- [x] Dashboard: "Investment break-even" section; CLI: sorted payback table
- Format fix: B/billions, not "B" on thousands
- Criterion: API exposes `breakeven.scenarios` with payback_days ✅

### P9 — Requested layout: single table ✅ (2026-10-14, owner request)
- [x] Removed the separate "cloud price list" table
- [x] in/out €/1M prices on every row of the first table ("Your tokens on the clouds")
- Criterion: grep "Listino cloud" on / = 0; API replay.models[] includes in_eur_1m/out_eur_1m ✅

### P10 — €/1M prices in the break-even table too ✅ (2026-10-14, owner request)
- [x] `breakeven.scenarios[]` includes in_eur_1m/out_eur_1m
- [x] Break-even dashboard: in/out €/1M columns per row (7 columns total)
- Criterion: "in €/1M" header present; API scenario[0] with prices ✅

### P11 — Local €/1M in the table + realistic break-even ✅ (2026-10-14, owner challenged the numbers)
- [x] `replay.local_eur_1m`: local cost extrapolated per 1M token (€/1M on the real volume of the period) — column in the first table
- [x] Break-even: cached scenarios FIRST (realistic agentic case), calculation basis declared in the header
- [x] Optional `monthly_prompt_m`/`monthly_gen_m` in config to pin the monthly volume instead of the projection from the peak
- Context: €20,296/month GPT-5.5 no-cache = right math but worst case (2.3-day peak extrapolated + zero cache). With cache 90%: €4,739/month → 60-day payback.
- Criterion: API replay.local_eur_1m present; scenarios[0] is cached ✅

### P12 — Always-on fleet + real idle ✅ (2026-10-14, owner question about the fixed cost)
- [x] `always_on: true` in config: idle energy computed on 24/7 (fixed), variable = only the extra watts above idle
- [x] idle_watts corrected: 65W was a reading under load → 6 samples taken: stable **17W/unit** (16.9-17.9)
- [x] Fixed cost and break-even now consistent: €253/month = amortization 246 + idle energy 7 (the previously reported inconsistency)
- [x] Card renamed "variable (extra load)"
- Note: replay energy = instantaneous power × uptime (approximation; the real average would require continuous sampling with --loop)
- Criterion: fixed card == bk.local_month_eur ✅

### P13 — UI in English ✅ (2026-10-14, owner request)
- [x] Dashboard (serve.py HTML) fully in English: titles, headers, cards, fallback
- [x] Break-even `basis` translated in the engine (localcost.py)
- Criterion: Italian-text grep on / = 0; API basis in English ✅

### P14 — GLM-5.3-Flash peer set ✅ (2026-10-14, owner request)
- [x] TOP_MODELS → PEER_MODELS: only 11 models with capability ≥ GLM-5.3-Flash
- [x] Selection from public benchmarks (2026-10-14): GLM-5.3-Flash = Terminal-Bench 2.1 84.3 (close to Opus 4.8 85.0), Toolathlon 78.4, HLE+tools 55.3, AA v4.3 parity with Gemini 3.8 Flash on tool use/agentic
- [x] Excluded (lower capability, meaningless comparison): GPT-5.4 mini/nano/Luna, Haiku 5.5, DeepSeek V3.2/Reasoner, Kimi K2.6, Gemini 2.5 Pro, Gemini 3.5/3.8-lite, Grok Code Fast, Qwen Plus, MiniMax, Mistral
- Fix: extract() referenced TOP_MODELS → PEER_MODELS
- Criterion: API replay 11 models, breakeven 22 scenarios ✅

### P15 — Model selector (min 3) ✅ (2026-10-15, owner request)
- [x] Selection bar with chips/checkboxes: "Compared models"
- [x] Minimum 3 models (inline warning if you try to go below), default: GLM cloud + Gemini 3.8 Flash + GPT-5.5
- [x] Selection persisted in localStorage (browser), reapplied on reload
- [x] Both tables (replay + break-even) filtered by the selection
- [x] JS verified with node --check
- Criterion: selbar present, valid JS, API 11 models ✅

### P16 — Price refresh + local model selector ✅ (2026-10-15, owner request)
- [x] "Refresh prices" button: re-downloads the LiteLLM price list (atomic tmp+rename snapshot), shows the price list age in the header
- [x] "Local model" dropdown: Auto-detect (default, from the server name in ps) + override from LOCAL_MODELS (7 known models: GLM 5.3 Flash/Fast/5.3/5.2/4.7, DeepSeek V4 Flash, Gemini 2.5 Flash); persisted in localStorage
- [x] Local model highlighted in the table (★ + outline) when it matches a cloud peer
- [x] API: /api/summary?refresh=1&local=KEY
- [x] Verified: auto-detect GLM 5.3 Flash ✓, override GLM 5.3 ✓, refresh age 0.0h ✓, JS node --check ✓
- Criterion: refresh re-downloads (age→0), local model resolved from ps without override ✅

### P17 — Logo + total investment field ✅ (2026-10-15, owner request)
- [x] sparkcost logo (neon X) top left, textual title removed (static/logo.jpg, /logo.jpg endpoint)
- [x] Editable "Investment €" field: saved to data/config.yaml via /api/capex (PATCH of the hardware_total_eur row only, preserves comments), numbers refreshed on the fly
- [x] Migrated config: hardware_total_eur (TOTAL fleet capex); engine uses capex_total() with a backward-compatible fallback hardware_eur × n
- [x] Verified: logo HTTP 200 (439KB), JS node --check ok, capex 9000 → amortization 250/fixed 257 → restore 8856.94 ✓
- Criterion: capex editable from the UI and propagated to replay+breakeven ✅

### P18 — "Local effective" card vs table consistency ✅ (2026-10-15, owner challenged the numbers)
- Problem: the card showed 7.29 €/1M (projection from config: 40 tok/s × 8h ≈ 35M tok/month) while the table showed 0.03 €/1M (real measured: ~680M tokens in the period) — two different, contradictory formulas.
- [x] Card "local effective (measured)" now uses replay.local_eur_1m (same basis as the table)
- [x] Basis declared everywhere: "measured period (X h/days)" — _fmt_period for windows < 1 day (tensorfold restarted = counters reset)
- Note: tensorfold restarted (uptime 1h, counters from 0) → the €/1M measured on short windows is noisier; the break-even still projects onto the month
- Criterion: card == table (0.025) ✅

### P19 — New logo + black background + sparklines ✅ (2026-10-15, owner request)
- [x] New logo (X + wordmark, 1376x768) in static/logo.jpg, 110px header height with object-fit contain
- [x] Pure black page background (#000) and #0d0d0f cards/bars: no contrast break with the logo
- [x] SVG sparkline under each dynamic parameter (prompt, gen, fleet power, tok/s, variable, effective): 20 points, polyline with glow drop-shadow, circled end point
- [x] Palette from the logo colors: orange #ff6a45, cyan #2ec8e8, purple #8b7cf8, magenta #c76bd8, peach #ffb08a, light cyan #8adfff — one color per parameter, numeric value tinted the same color
- [x] History in localStorage (sparkcost.hist), max 20 points, accumulates across 10s refreshes
- [x] Static (active units, monthly fixed, tariff) without sparklines
- Criterion: JS node --check ok, palette present, logo 200/473KB, API ok ✅
- Note: history starts from zero (per-browser localStorage); it fills up in ~3 min of refreshes

### P20 — Area sparklines + live tok/s + refresh rate ✅ (2026-10-15, owner request)
- [x] sparkDash-style sparklines: area with vertical gradient (opacity 0.5→0.03) under the line, neon glow, circled end point
- [x] Live tok/s: the backend computes decode+prefill from the counter delta between API calls (_live_rates, read-only /metrics, no benchmark); static "tok/s" card replaced by "decode tok/s" + new "prefill tok/s" card; first call = baseline (null), then deltas
- [x] prompt/gen sparklines on the per-tick DELTAS (the cumulative would be a straight line)
- [x] Refresh 1s/5s/10s buttons (default 1s), selection persisted in localStorage (sparkcost.rate), async loop with setTimeout
- [x] Verified: JS ok, 3 buttons, rates {dt_s:3.12, prefill:0, decode:0} on the idle server (real value)
- Criterion: rates non-null from the second call ✅

### P21 — Footer status + drop variable card + prefill/decode fix ✅ (2026-10-15, owner request)
- [x] Status row (server · model · local model · price list age) moved to a fixed page footer (#sub); removed the sub from the top
- [x] "Variable (load extra)" card removed: at idle it showed 0.00 and misled (the variable cost is already inside local effective)
- [x] Fix for empty prefill/decode: now read directly from rates with a "—" fallback (before, they went through hist, which could be empty/stale); tick wrapped in try/catch that surfaces errors in the footer
- [x] DOM stub test with the real API: 10 cards rendered with values, variable absent
- Criterion: footer present, variable 0 matches, rates non-null ✅

### P22 — Selective sparklines + robust rate values ✅ (2026-10-15, owner request)
- [x] Sparklines ONLY on: decode tok/s (cyan), prefill tok/s (magenta), fleet power (orange), local effective (light cyan) — removed from prompt/generated tokens
- [x] prefill/decode never empty: value from rates with a last-known fallback in localStorage (sparkcost.rates) + "—" if never available
- [x] Robust backend rates: 30-sample rolling window (deque) instead of the 2-call delta — stable with multiple polling clients, discards post-restart samples, dt>=0.3s
- [x] Footer confirmed: "python3 :8888 · GLM-5.3-Flash-EXL3-4bpw-TensorFold · local model: GLM 5.3 Flash (auto-detected) · price list 1 h old"
- DOM stub (real data): 9 cards, 4 sparklines, numeric decode/prefill (0.0 idle), exact footer ✅

### P23 — tok/s "always zero": diagnosis and 30s window ✅ (2026-10-15, owner challenged the numbers)
- Diagnosis (test with 6 calls/2s): the rates work but are INSTANTANEOUS — at 10:22:50 they caught the message burst (prefill 144k, decode 2.7k), then true 0.0s because inference is bursty and the server is idle most of the time. Real average since restart: prefill 3,338 tok/s, decode 36.4 tok/s (2.2h uptime).
- [x] Backend: 30s sustained window (_WINDOW_S, deque maxlen 240) as the main number + instant_* for the peak; discards post-restart counters
- [x] Cards renamed "decode tok/s · avg 30s" / "prefill tok/s · avg 30s"
- [x] Verified: t0 baseline None -> t+8s an 8.3s window with 0.0 idle (correct)
- Note for the owner: 0.0 = no traffic in the last 30s, not a bug; during an active session the real values show up

### P24 — Break-even with subscriptions + Cache-Control + counter clarification ✅ (2026-10-15, owner requests)
- [x] Closed-weight (OpenAI/Anthropic/Google/xAI): break-even with consumer SUBSCRIPTIONS (config subscriptions, prices verified 2026-10: Plus/Pro 20/200, Claude Pro/Max 20/100, Google AI Pro/Ultra 19.99/99.99, SuperGrok 30/300) — 14 extra sub scenarios; open-weight (DeepSeek/Kimi/Qwen/Z.ai) stay per-token
- [x] Cache-Control: no-store on all responses (HTML+JSON) — the browser no longer serves stale JSON
- [x] Counters: they update ONLY while tensorfold is serving tokens (verified: 29.20M→29.42M between tests); stalled during idle/tool exec. They are cumulative since the server restart
- [x] Payback >10 years formatted in years
- Key insight: vs entry-level subscriptions (€18.60/month < local fixed €253/month) the payback is "never" — the honest comparison is: subs for human use, local for agentic/API volume
- Criterion: 14 sub scenarios in the API, Cache-Control on GET ✅

### P25 — Drop decode/prefill + editable rate + top-tier subscriptions ✅ (2026-10-15, owner requests)
- [x] decode tok/s and prefill tok/s cards removed from the dashboard (the rates stay in the API)
- [x] Editable "Energy €/kWh" field (default 0.28): /api/tariff → PATCH of the eur_per_kwh row, preserves comments; test 0.30→0.28 ok
- [x] Subscriptions ONLY top tier for the comparison with heavy usage: ChatGPT Pro 200, Claude Max 20x 200, Google AI Ultra 20x 200, SuperGrok Heavy 300 (USD/month) — 7 sub scenarios (one per closed-weight model)
- [x] Verified: 0 decode/prefill cards, rate saved/restored, JS ok
- Insight: top-tier subs €186-279/month vs local fixed €253/month → payback "never" or decades; but subs have volume caps, local has none (4.1B tokens/month)
- Criterion: subs top-tier only, rate editable and propagated ✅

### P26 — Break-even price verification + in_eff display fix ✅ (2026-10-15, owner challenged the numbers)
- Independent verification: all 11 models with prices consistent with the LiteLLM price list ×0.93; cloud/month recomputed by hand = API (€0.5 tolerance) → CALCULATIONS CORRECT
- BUT misleading display: in the "cache 90%" scenarios the "in €/1M" column showed the full list price (GPT-5.5: 4.65) while the calculation uses the blended one (0.883 = 10% list + 90% cache at 0.465)
- [x] New in_eff_eur_1m field for every scenario: the input price ACTUALLY used by the calculation
- [x] Break-even dashboard shows in_eff (fallback in_eur_1m), explanatory note under the table
- [x] Verified: GPT-5.5 cache 90% → in_eff 0.883; no-cache → 4.650; sub → 4.650
- Criterion: in_eff == the price used in the calculation for every scenario ✅

### P27 — Projected monthly costs (owner request) ✅ (2026-10-15)
- [x] First table redefined: "Monthly cost — local 24/7 vs cloud at your current token rate"
- [x] Local: fixed fleet monthly cost (amortization + 24/7 energy) = €252.98; open-weight: tokens projected onto the month at the current rate (11.01B prompt + 102M gen/month, cache 90%); closed-weight: top-tier SUBSCRIPTION only
- [x] "basis" column for each row: subscription plan / token @ current rate / amortization+energy
- [x] Break-even: closed-weight EXCLUDED from token scenarios (subs only); payback sorted ascending, never at the bottom
- [x] Fix: Python :.2f formatting in a JS template literal → toFixed()
- [x] Real DOM stub: table 1 (local 252.98, subs 186, GLM cloud 479.58 token), table 2 consistent, footer ok
- Insight: at the current rate GLM cloud tokens = €479.58/month > local €252.98; subs €186-279 fixed but with a volume cap
- Criterion: API replay.models[].month_cost_eur + month_basis; bk without token scenarios for closed-weight ✅

### P28 — Green headers + break-even consistent with subs ✅ (2026-10-15, owner request)
- [x] Column headers with a green background (#0f2a1c, acc text) on BOTH tables, like the local row
- [x] Break-even: subscription rows show "—" in the in/out €/1M columns (no token costs for closed-weight, same concept as table 1)
- [x] Real DOM stub: sub rows "— —", token rows with in_eff, JS ok
- Criterion: green thead x2, subs without prices ✅

### P29 — Editable model prices ✅ (2026-10-15, owner request)
- [x] Inline in/out €/1M inputs in table 1: defaults from the online price list (LiteLLM), the user can adapt them
- [x] Persistence in data/price_overrides.yaml (USD/1M, converted via usd_eur); they win over the price list on every load
- [x] ✎ badge on models with edited prices + amber border on the edited input
- [x] "Reset prices" button: deletes the overrides and goes back to the online price list (/api/price?action=clear)
- [x] Subscription rows (closed-weight): disabled inputs with tooltip (fixed cost; plans are edited in config)
- [x] Fix: overrides_applied only counted the "in" field → now per field; edited flag exposed in the API
- [x] Verified roundtrip: GLM cloud out 0.465→10 ⇒ month 409→1212.66, edited=True, applied=1; reset → 0.465/False/409.08
- Note: the cache price is editable only via API (field=cache), the UI exposes in/out
- Criterion: persistent override, applied to replay+break-even, working reset ✅

### P30 — Editable daily commitment + verified subscription prices ✅ (2026-10-15, owner requests)
- [x] Editable "Hours/day" field (default 8, range 0-24, step 0.5): /api/hours → PATCH of the hours_per_day row in the config
- [x] Monthly projection = observed hourly rate × hours_per_day × 30.44 (for replay AND break-even); basis declared in both ("8 h/day machine commitment, observed over X")
- [x] Local: fixed cost unchanged (€253 — amortization+24/7 energy, always on regardless of the commitment); open-weight scales with hours (8h→3.16B prompt/month, 16h→6.32B)
- [x] Subscription prices refined from Oct 2026 sources: Google AI Ultra 20x 199.99 (costbench 10/10), ChatGPT Pro 200, Claude Max 20x 200 (aipricing/techverdict), SuperGrok Heavy 300. Official pages (claude.ai/upgrade, chatgpt.com/#pricing, one.google.com/ai) behind login — note about a possible unconfirmed OpenAI $500 tier in the config comment
- [x] Verified: hours 16→8 roundtrip, projection scales linearly, JS ok
- Criterion: hours editable and propagated to replay+bk; sub prices updated ✅

### P31 — Truly editable prices + single-model comparison ✅ (2026-10-15, owner challenged the numbers)
- Fix for non-editable prices: the 1s refresh regenerated the innerHTML and destroyed the input while typing → tick() now returns immediately if a .pr field has focus (full pause of the loop)
- [x] Removed the "Compared models" bar (multiple chips): now a "Cloud model" dropdown — one model at a time
- [x] Table 1: always 2 rows (local + selected cloud), inline editable prices with ✎ badge/amber border, disabled for subs
- [x] Break-even: ONLY the scenarios of the selected model (dynamic title "X vs local"); selection persisted in localStorage (sparkcost.cloud)
- [x] Real DOM stub: 2 rows in table 1, 2 bk scenarios GLM cloud only, 2 price inputs, footer ok
- Insight: with hours=8 the projected volume drops to 3.15B prompt/month → GLM cloud cache (€138.75) becomes cheaper than local fixed (€253.48) → cache break-even "never", no-cache 42.4 months. The daily commitment is now the driver of the comparison
- Criterion: refresh pause on focus, single dropdown, filtered bk ✅

### P32 — Break-even dedup + editable out + full peer set ✅ (2026-10-15, three owner challenges)
- [x] Break-even: the same model repeated 2x → second row "└ same model" (verified DOM: GLM cloud no-cache + └ cache 90%)
- [x] out €/1M now EDITABLE in the break-even too (input per token row; it writes the same override field=out as table 1, so both scenarios update); sub rows: "—" and no inputs (verified GPT-5.5: 1 row, — —, 0 inputs, €186 never)
- [x] FULL peer set: 34 models — 13 OpenAI (GPT-5/5.1/5.2/5.4/5.5/5.6 + Sol/Terra/Cyber variants + GPT-6 Sol/Astra/6.1) + 14 Anthropic (Opus 4.5→5.5, Sonnet 4.5→5.5, Fable, Mythos) + 7 others (Gemini, DeepSeek, Kimi, Qwen, Grok, GLM cloud). Excluded mini/nano/luna, legacy 3.x/4.x, dated/region/provider duplicates
- out €/1M explanation given to the owner: list price per 1M generated tokens (LiteLLM ×0.93), not computed — it multiplies the generated tokens in the monthly cost
- Criterion: 34 models in the dropdown, bk with dedup, out editable in the bk, subs without inputs ✅

### P34 — Editable amortization (default 5 years) ✅ (2026-10-15, owner request)
- [x] Editable "Amort years" field (default 5, range 1-15, step 1): /api/amort → PATCH of the amort_years row in the config
- [x] Migrated config: amort_years 3 → 5 (requested default); amortization/month now 147.62 (was 246.03 with 3 years), local fixed 152.58
- [x] Verified roundtrip: 4 years → 184.52, 5 years → 147.62; propagates to the monthly fixed card, replay pro-rata, break-even and payback
- [x] JS node --check ok; input with 1-15 validation and inline error message
- Note: it was the last non-editable parameter in the bar (capex, rate, hours, amort now all editable)
- Criterion: default 5 years, editable, propagated everywhere ✅

### P36 — Optional amortization (private purchase) ✅ (2026-10-15, owner request)
- [x] "Depreciation" flag in the config (default true) + "Depreciate" checkbox in the dashboard next to Amort years; /api/depreciation
- [x] If false (Spark bought as a private purchase): amortization = 0, local cost = energy only (idle + tokens); Amort years input disabled
- [x] payback stays computed on the real capex spent (€8,800) — the investment happened even if it is not depreciable
- [x] amort_monthly() helper used in all 3 places (card, replay, break-even) via local_month_breakdown
- [x] Verified roundtrip: true → amortization 146.67/local 151.63; false → amortization 0/local 4.97 (energy only), capex 8800 unchanged, Kimi K3 payback 9 days; restore true ok
- Criterion: editable flag, consistent zeroing in every view, payback on the real capex ✅

### P37 — Cross-check against a second source (aitokenprice) ✅ (2026-10-15, owner request)
- [x] `models.py`: atomic download of https://aitokenprice.com/api/models.json → data/atp_snapshot.json; peer set ↔ aitp matching (explicit aliases Qwen Max→Qwen3.8 Max, Grok 4.6→4.7, GLM Flash; containment with a ≥8 char threshold to avoid GPT-5→GPT-5.5)
- [x] `python3 -m sparkcost.models --crosscheck` (fresh network) / `--crosscheck-cached` (offline)
- [x] API `/api/crosscheck` (cached; `?refresh=1` forces the download — never network in the 10s tick)
- [x] Result 2026-10-15: 34 peers → 26 aligned to the cent (11 current + 15 legacy), 1 real delta (Qwen Max: aitp lists gen 3.8 at 2/6 vs our 1.6/6.4), 7 not present on aitp (Cyber tier, GPT-5/5.1, Mythos)
- [x] Rule: COMPARISON ONLY, never overrides the LiteLLM price list
- Criterion: crosscheck CLI+API ok, dashboard integrates it (summary with replay+breakeven) ✅

### P38 — 5 improvements from external verification ✅ (2026-10-15, owner request, external reviewer input)
- [x] **Batch API -50%**: new scenario next to cache/no-cache where the price list exposes `*_batches` (27/34 models; GLM/DeepSeek/Kimi/Qwen/Grok no). Batch multipliers applied to input+output+cache-read; in the replay a "batch API" column and `month_batch_eur` (also for vendors with a subscription: comparison of programmatic API usage); batch column in the CLI. Verified: Sonnet 5.5 batch = exactly half of the cached one
- [x] **Cache write in the blend**: steady state = every miss (1-ch) written at the `cache_creation` list price (or 1.25x input if absent) — before, the cached case was underestimated
- [x] **0.22 €/kWh rate** (Eurostat AT non-household 2025: 0.241; 0.22 prudent) → fixed 152.13 €/month
- [x] **Long-context warning**: "⬆ Nx >272k" badge on models with `input_cost_per_token_above_272k_tokens` (e.g. GPT-5.5 2x, GPT-5.6 2x) — warning only, the replay stays at the base price
- [x] **External reviewer cleanup**: dead code L305 removed (energy_month recomputed from local_month_breakdown); L245 vs L96 idle divergence resolved (both on h_day in non-always_on mode); "cash payback" `capex_note` in the break-even when depreciation=false, shown in bksub
- Criteria: JS node --check ok, /api/summary with batch+lc+capex_note, dashboard 200, consistent numbers (Sonnet batch 41.12 = cached 82.24 / 2) ✅

### P39 — Persistent token ledger + up-to-date repaid capex ✅ (2026-10-15, owner request)
- [x] **data/token_ledger.json** (atomic tmp+rename write): accumulates the prompt/gen totals since sparkcost has been running; the Prometheus counters restart from zero at every server restart/reboot → the ledger detects the reset (counter < last_seen) and ADDS the new counter, no tokens lost; corrupted file → restarts clean without blocking the dashboard
- [x] 4 cases tested: first start (baseline = current counter), normal growth (delta), restart (sum), corruption (reset) ✅
- [x] **"Repaid so far" section**: cloud-equivalent cost of the HISTORICAL tokens vs local cost at the same measured rate → accumulated savings = share of the capex already repaid by real usage (up to date, refreshed at every tick)
- [x] "prompt/gen tokens (total)" cards now read from the ledger (persistent), fallback to counters if absent
- [x] API: `ledger` + `repaid` in /api/summary; live result: 146.6M historical prompt, local_cost €2.78, GPT-5.6 Cyber cloud €634 → 7.2% capex repaid
- Note: the tail between the last poll and the restart is unrecoverable but negligible (1s poll)
- Criteria: ledger roundtrip ok, JS node --check ok, dashboard 200, repaid populated ✅

### P40 — Time-weighted energy + persistent sampler ✅ (2026-10-15, owner request)
- [x] **Robust sampler** (`collect.py`): `sample_once()` ALWAYS reads watts (nvidia-smi), counters only if tensorfold answers — it keeps sampling even during a server restart; sqlite in WAL + busy_timeout (1 writer + dashboard reads); `--loop` uses sample_once instead of measure (no blocking window)
- [x] **`integrated_watts(window_s, min_span_s=300)`**: time-weighted average (trapezoid ∫P dt) from the DB samples; None if <2 samples, span <300s, table missing or empty DB → fallback to the spot reading
- [x] **report()**: watts = integration over the server uptime window when available; `energy_source` in the API ({mode: integrated|spot|measure-window, samples, span_s}); tested T1 no table / T2 exact trapezoid (10→30→10W over 1200s = 20W, not the arithmetic 16.7) / T3 short span → None / T4 parametric min_span
- [x] **systemd user service** `sparkcost-sampler.service` (30s loop, Restart=always, log /tmp/sparkcost-sampler.log) — Linger=yes already active → survives reboots, consistent with the P39 requirement
- [x] **Dashboard footer**: shows the source ("power ... time-weighted over N min (N samples)" / "spot reading (sampler warming up)")
- Note: with 2 samples/30s the report stays in "spot"; it switches to "integrated" automatically after 5 min of samples
- Criteria: syntax ok, JS ok, dashboard 200, sampler active, DB accumulating ✅

### P41 — Cluster users + alphabetical dropdown + AA score ✅ (2026-10-22, owner request)
- [x] Editable "Cluster users" parameter (default 2, range 1-50): /api/users; CLOUD model costs scale x N (tokens and subscriptions, in both the monthly and break-even tables); LOCAL fleet cost stays fixed and shared
- [x] Basis annotated: "x N users" on token and subscription rows; bksub shows the factor
- [x] "Cloud model" dropdown sorted alphabetically (localeCompare)
- [x] "AA <score>" badge next to the model name (first table) and in dropdown options: Artificial Analysis Intelligence Index, benchlm.ai snapshot 2026-10-20 (v4.3.x); AA_SCORES dict in models.py, attached in extract(); models missing from the top-100 (Cyber, Mythos, Sonnet 4.5) get no badge
- [x] Roundtrip verified: 3 users -> GLM 302.49 (x3), GPT-5.5 sub 558 (186x3); 2 users -> 201.66; bk/users exposed in the API
- Acceptance: editable and propagated users, A-Z dropdown, visible AA badge ✅

### P43 — "Repaid so far" table filtered to the selected model ✅ (2026-10-22, owner request)
- [x] Table 3 showed the first 8 ledger models (r.models.slice(0,8)) regardless of the selection
- [x] Now: ONLY the model selected in the dropdown (filter model===cloudModel), dynamic title "Repaid so far — <model> vs local"
- [x] If the model has no ledger history: one row of dashes (—) instead of disappearing
- [x] Verified with DOM stub: one GLM cloud row (€24.71 vs €36.02, 0.0% repaid); JS ok
- Note: table 2 (break-even) was already filtered correctly; the ledger table was the only culprit
- Acceptance: all 3 tables now show one model at a time (the selected one) ✅
### P44 — Fleet power: corrected measurement + side panel layout ✅ (2026-10-22, owner request)
- [x] MEASUREMENT BUG: integrated_watts() averaged the ENTIRE DB history (6.8 days, drowned in nightly idle) -> 15.8 W/unit; now a LAST-30-MIN window (min(uptime,1800s)) -> 57 W/unit, consistent with sparkDash (GPUs 56-64 W) and live nvidia-smi (59.24 W) — cross-checked 2026-10-22
- [x] UI clarity: "fleet power · all units" card + footer "power 114.0 W fleet = 57.0 W/unit × 2 units, time-weighted over 30 min" (the fleet multiplier was already applied; the measured value was wrong)
- [x] LAYOUT: the whole control bar (9 inputs/selects + 2 buttons) moved to a sticky LEFT SIDE PANEL (280px, collapses on top <900px); .main flex-1 with cards + 3 tables; fixed footer unchanged
- [x] DOM stub: T1 2 rows, T2/T3 1 row each, footer with W/unit, card labels ok; JS node --check ok
- Note: the sampler (sparkcost.collect --loop 60) writes samples to the DB — keep it alive for the 30-min window; spot fallback if there are not enough samples
- Acceptance: measurement consistent with sparkDash, side-panel layout ✅

### P45 — Logo top-left nel frame ✅ (2026-10-22, owner request)
- [x] Logo sparkcost spostato dal .main (era centrato sopra le card) al TOP-LEFT del side panel, sopra "Investment €" — altezza 110px → 44px (fit 280px panel)
- Acceptance: logo primo elemento del frame, layout side panel invariato ✅

### P46 — Fleet power multi-macchina (stile sparkDash) ✅ (2026-10-22, owner request)
- [x] data/fleet.yaml (gitignored, chmod 600): lista host con mode local|ssh, ip/port/user/password — credenziali prese dal caveau cifrato sparkDash (AES-256-GCM v2, formato node iv+tag+ct, decrypt ok; NON mostrate in chat)
- [x] collect.py: tabella power(ts,host,watts) + read_watts_ssh() via paramiko (nvidia-smi remoto, somma GPU) + sample_once() legge TUTTI gli host ogni ciclo + integrated_watts() P46: trapezoide per-host sommato, fallback legacy samples per unità
- [x] localcost.py: watts_unit = SOMMA/n_host_rispondenti (costi lineari → local_cost(watts)*n ricompone esatto); energy_source.per_host esposto all'API
- [x] serve.py footer: "· dgx-spark-01 40.3 W latest · dgx-spark-02 32.6 W latest" (mode per host: integrated/latest/spot/n-d)
- [x] VERIFICATO LIVE: spark-01 (local nvidia-smi) 40.3 W + spark-02 (SSH) 32.6 W = card fleet 72.9 W; footer "36.5 W/unit × 2 units"; 0 errori JS
- Note: host senza dati → spot SSH live; dopo 5 min di campioni il mode passa da latest a integrated; sshpass non necessario (paramiko); se cambiano le password rigenerare data/fleet.yaml
- Acceptance: potenza per singola macchina leggibile in dashboard + somma corretta ✅

### P47 — Tema dark/light + card 4+4 + ombra sparkline + pannello cluster ✅ (2026-10-22, owner request)
- [x] Toggle tema ☀️/🌙 accanto al logo: body.light con variabili CSS complete (bg/card/tx/mut/acc/b/warn/thbg/inputbg); scelta persistita in localStorage; override via ?theme=light|dark nell'URL
- [x] Colori hardcodati migrati a variabili (th header, tr.local, input, button)
- [x] Card grid: 4 colonne fisse (2 righe da 4), fallback 2/1 colonne <1500/<900px; padding 16-18px; valori 25px, label 12px
- [x] 8ª card "repaid so far" (griglia 4+4 uniforme): % ripagato del modello selezionato dal ledger persistente, con sparkline storica
- [x] Sparkline: ombra sfocata sotto la traccia (feGaussianBlur stdDeviation 2.2 sull'area, stile sparkDash) + gradiente
- [x] Pannello "⚙ Cluster machines (per-host power)" nel side panel (details): riga per macchina con name/mode local|ssh/ip/port/user/password; bottone Test (lettura live) e ✕; Save → POST /api/fleet (password MAI in URL, mai riverberate; vuota = mantiene la stored; sincronizza n_sparks)
- [x] Backend: collect.save_fleet() atomico chmod 600 + test_fleet_host() (fallback password stored); localcost.save_n_sparks(); report() espone fleet MASCHERATO (has_password bool, mai la password)
- [x] VERIFICATO LIVE: fleet/test spark-02 → {"ok":true,"watts":10.69} (idle notturna); save roundtrip preserva password; n_sparks=2 synced; footer integrated per-host (spark-01 56.1 W + spark-02 48.7 W = 104.9 W); entrambi i temi screenshotati; 0 errori JS
- Bugfix during dev: emoji JS come escape \uD83C\uDF19 diventava surrogate Python invalido all'encode UTF-8 dell'HTML → emoji reali nel sorgente
- Acceptance: tema commutabile, card uniformi su 2 righe, ombra sparkline, configurazione cluster completa con test live ✅

### P48 — Pannello configurazione: tutti i parametri di input ✅ (2026-10-22, owner request)
- [x] Side panel organizzato in sezioni: INVESTMENT & FLEET (investment €, number of machines, idle W/unit, USD→EUR) · ENERGY & USAGE (energy €/kWh, hours/day, amort years, always on 24/7, depreciate, fallback tok/s, in:out ratio, cache hit rate, cluster users) · MODELS (cloud + local) · Cluster machines (P47)
- [x] Nuovi campi editabili: n_sparks, idle_watts, usd_eur, assumed_tok_s, in_out_ratio, cache_hit_rate, always_on — popolati dal cfg nel tick, salvati su change
- [x] Endpoint POST /api/cfg: whitelist chiavi (_CFG_PARAMS), tipizzazione int/float, range-check (_CFG_RANGE), scrittura line-preserving in config.yaml; errori espliciti ("unknown keys: …", "allowed 0-10")
- [x] VERIFICATO LIVE: POST valido {cache_hit_rate:0.9} → ok saved; {hackme:1} → 400 unknown keys; {eur_per_kwh:99} → 400 allowed 0-10; campi popolati dal summary (n_sparks 2, idle 17, usd 0.93, tok/s 40, ratio 3, cache 0.9, always_on true); 0 errori JS
- Acceptance: tutti i parametri di input editabili dal pannello di configurazione ✅

### P49 — Struttura a 3 menu: Dash / Config / Statistics ✅ (2026-10-22 23:08, owner request)
- [x] Side panel ridotto a logo + tema + nav a 3 viste (persistite in localStorage, override ?view=dash|config|stats)
- [x] Dash: card 4+4 + le 3 tabelle di comparazione (com'era)
- [x] Config: tutti i parametri P48 spostati in griglia 3 colonne (Investment & Fleet · Energy & Usage · Models) + Cluster machines (P47) full-width
- [x] Statistics (nuovo): 4 card (fleet mean W, fleet peak W, peak single host, energy kWh) + finestra all/24h/7d + tabella eventi per mode
- [x] Backend: tabella power + colonna running (ALTER idempotente; flag fleet-wide dal server monitorato su questa macchina); stats.py (media trapezoidale implicita sui fleet-sum per ts, picco, split inference/idle/unknown, energia a cadenza mediana); GET /api/stats?window=
- [x] Semantica: inference = requests_running>0 (host-scoped, server su questa macchina); idle = running==0; unknown = flag assente (campioni pre-P49, decadranno); server irraggiungibile = escluso dallo split, resta in mean/peak
- [x] VERIFICATO LIVE: 3 viste HTTP 200; stats: fleet mean 100.7 W, peak 122.9 W, peak host 65.8 W, inference 66 samples mean 54.1 W vs idle 8 samples mean 11.7 W, unknown 906 (pre-flag); 0 errori JS
- Bugfix: come P47, emoji 💤 come escape \ud83d\udca4 nel JS → surrogate Python → UnicodeEncodeError su HTML.encode; risolto con emoji reali
- Acceptance: 3 menu funzionanti, statistics con media/picco/eventi inference-idle ✅

### P50 — Logo full-width + menu stile sparkDash ✅ (2026-10-23 06:51, owner request)
- [x] Logo sparkcost a PIENA LARGHEZZA del frame sinistro (width:100%, max-height 110px, object-fit contain); themeBtn spostato sotto il menu come il toggle luna di sparkDash
- [x] Menu stile sparkDash: sans-serif 14px (ui-sans-serif stack), voci grigie senza bordo, hover pill --navact, voce attiva con pill background + peso 600 (come "Overview" su sparkDash)
- [x] Bugfix specificità: la regola generica `.side button` (0,1,1) batteva `.navbtn` (0,1,0) mantenendo i bordi verdi → override con `.side .menu .navbtn`
- [x] Nuova variabile --navact per entrambi i temi (dark #1a2027, light #dde3ea)
- [x] VERIFICATO: screenshot dark+light, logo full-width, pill sull'attiva, 0 errori JS
- Acceptance: logo largo come il frame + menu identico a sparkDash ✅

### P51 — Logo dedicato al tema light ✅ (2026-10-23 07:13, owner request con allegato)
- [x] Nuovo static/logo-light.jpg (dal logo inviato da Marco, ritagliato auto via PIL: crop contenuto + 4% margine) — testo scuro su fondo chiaro
- [x] Logo dark ritagliato a sua volta (1124x540 da 1376x768) per riempire meglio il frame
- [x] Endpoint GET /logo-light.jpg; swap automatico del src in applyTheme() secondo il tema (persistito anche al reload via localStorage)
- [x] VERIFICATO: screenshot dark (logo chiaro su scuro) e light (logo scuro su chiaro) entrambi corretti; /logo-light.jpg 200 (91 KB); logo dark 200 (115 KB)
- Acceptance: logo che si adatta al tema ✅

### P52 — Sparkline solo su fleet power + font maggiorato ✅ (2026-10-23 07:45, owner request)
- [x] Sparkline di tendenza SOLO sulla card "fleet power · all units" (via da local effective e repaid so far: tengono il colore, perdono la tendenza)
- [x] Valori delle 8 card del Dash: 25px -> 32px
- [x] VERIFICATO: screenshot con solo fleet power sparklinata e carattere maggiore su tutti i meter
- Acceptance: una sola sparkline + font grande ✅

### P53 — Fix layout Config: allineamento parametri + Save cluster ✅ (2026-10-23 08:12, owner request)
- [x] Bug 1 (disallineamento): nella cgrid lbl e field erano DUE celle grid separate -> le label fluivano in colonne sbagliate. Fix: ogni parametro wrappato in <div class="cparam"> (13/13, incluse le 2 select MODELS) = UN solo grid item; select width:100%.
- [x] Bug 2 (Save fuori finestra): #fleetSave ereditava width:100% da .cgrid button e traboccava a destra di + add. Fix: .fbtns in colonna (Save SOTTO add) + override larghezza auto.
- [x] VERIFICATO programmaticamente (CDP): tutti i 13 parametri lblX==inpX (stessa x per colonna: 324/751/1177); saveSottoAdd=true, saveDentroBox=true, saveLarghezzaAuto=true. Screenshot conferma.
- Acceptance: parametri allineati + Save sotto add dentro la finestra ✅

### P54 — Fleet power LIVE: numero card = sparkline ✅ (2026-10-23 08:48, owner request)
- [x] Diagnosi: la card usava L.watts_fleet = media pesata temporale ultimi 30 min (base costi) che lagga la realtà fino a mezz'ora; la sparkline invece mostrava la discesa reale -> numero (105 W) non coerente con tendenza (21 W live segnalati da Marco)
- [x] Fix: stats.live_power() = somma dell'ULTIMO campione per host dal sampler (max age 180s, else None); iniettata in /api/summary come rep["live_power"]
- [x] JS: numero card + storico sparkline da powerNow (live, fallback L.watts_fleet se sampler fermo); footer distingue "X W live · cost basis Y W fleet" (la media 30min resta base dei costi)
- [x] VERIFICATO LIVE: card 71.1 W = live_power.fleet_w 71.1 W stesso istante; footer "71.1 W live · cost basis 91.5 W fleet"; sparkline e numero ora coerenti per costruzione (stessa serie)
- Acceptance: numero collegato alla sparkline ✅

### P55 — Toggle tema in basso a sinistra ✅ (2026-10-23 09:04, owner request)
- [x] .side flex-column a piena altezza viewport (height calc(100vh - 32px)); #themeBtn con margin-top:auto -> ancorato IN FONDO al frame sinistro, sotto il menu (come la luna di sparkDash)
- [x] Mobile (<900px): sidebar torna statica e il bottone torna subito sotto il menu (height auto, margin 6px)
- [x] VERIFICATO via CDP: btnFondoSide=true, btnSottoMenu=true, nelViewport=true (btn bottom 932 vs side bottom 949, viewport 957)
- Acceptance: toggle in basso a sinistra ✅

### P56 — Fleet power modello sparkDash: serie server-side + auto-refresh ✅ (2026-10-23 09:26, owner request)
- [x] Studio sorgente ufficiale https://github.com/MiaAI-Lab/sparkDash: metricsStore.ts (ring buffer server-fed, SPARKLINE_TAIL=30), fleetStats.ts (powerW = somma draw istantanei), poll 2s. Il browser NON accumula storia: una sola fonte verità.
- [x] Diagnosi vecchio codice: (1) il browser accumulava storia in localStorage mescolando vecchi punti a media 30-min con nuovi live -> sparkline incoerente; (2) la dashboard NON si auto-aggiornava MAI (un solo tick al load) -> numero "lento" fino a reload manuale
- [x] Fix backend: stats.power_series() = serie RAW dal DB sampler (somma per host per ts, coda 60 punti ~30min, cadence rilevata); iniettata come rep["power_series"]
- [x] Fix frontend: rimosso pushHist/sparkcost.hist (0 riferimenti rimasti); sparkline(ppts) diretta; numero card = power_series.last_w; footer "X W live · cost basis Y W"; auto-refresh setInterval 30s (document.hidden-aware)
- [x] Bugfix refactor: "key is not defined" (gid) + punti ora coppie [ts,w] -> vals estratti
- [x] VERIFICATO LIVE: card 23.3 W = power_series.last_w stesso istante; sparkline discesa reale 119->23 W su 60 punti; footer live/cost basis; 0 errori render
- Acceptance: numero e sparkline stessa serie server-side + aggiornamento automatico ✅

### P57 — Toggle tema sempre visibile (fixed viewport) ✅ (2026-10-23 10:18, owner request)
- [x] Requisito: il toggle ancorato al fondo della sidebar (P55) richiedeva scroll per essere visto -> diventa position:fixed bottom-left del VIEWPORT: sempre visibile, scroll o no
- [x] Bug 1: il footer di stato (position:fixed full-width, z-index 9) copriva il bottone (z5) -> z-index 10 + padding-left riservato nel footer (84px)
- [x] Bug 2: onTop=false nonostante z10 -> il bottone era dentro aside.side (sticky) che crea stacking context proprio; spostato a livello body, prima del footer
- [x] Mobile <900px: bottone torna statico sotto il menu, footer senza padding extra
- [x] VERIFICATO via CDP: onTop=true a scroll 0 E a fondo pagina (rect 24,707-66,741, viewport 757); screenshot fondo pagina conferma toggle sopra footer
- Acceptance: toggle sempre visibile senza scroll ✅

### P58 — Refresh fleet power veloce (cadenza sparkDash-like) ✅ (2026-10-23 11:11, owner request)
- [x] Diagnosi: catena lenta = sampler 30s (systemd unit P40) + dashboard poll 30s -> fino a 60s percepiti; API /api/summary invece 53ms; sample_once costa 0.55s
- [x] Fix systemd: sparkcost-sampler.service --loop 30 -> --loop 10 (daemon-reload + restart, unit preservata)
- [x] Fix frontend: auto-refresh 30s -> 5s; power_series max_points 60 -> 180 (finestra ~30min preservata alla nuova cadenza)
- [x] VERIFICATO: campioni freschi (eta 6s, gap 10-11s tra batch), serie 123 punti in transitorio (mediana scendera' a 10s man mano che i vecchi campioni a 30s escono dalla finestra 1h); smoke test render OK, footer 132 samples/30min
- Acceptance: refresh percepito ~7s medi (prima ~45s) ✅

### P59 — Statistics: istogramma distribuzione fleet power ✅ (2026-10-23 11:22, owner request)
- [x] stats.fleet_stats(): power_hist = 24 bin della distribuzione fleet (somma host per ts, range [0,max]) + cadence_s esposta
- [x] Frontend: div .histwrap con barre CSS theme-aware (var(--acc)), asse 0/metà/max W, tooltip per bin (range W: N samples), caption
- [x] Fix collaterale: sub non dice più fisso "cadence 30 s" ma usa la cadenza rilevata dal backend
- [x] VERIFICATO: API 24 bin, 2067 timestamp (=4134 host samples, tornano al centesimo); render OK con forma bimodale leggibile (idle cluster + inference cluster); smoke test screenshot
- Acceptance: istogramma in Statistics ✅

### P60 — Statistics: istogramma impilato per modalità (inference/idle/unknown) ✅ (2026-10-23 11:32, owner request)
- [x] Backend: fleet_stats() binna i WATT HOST per modalità (inf_ws/idle_ws/unk_ws raccolti nel loop), stessi 24 bin su [0, max host W]; bins=[upper_w, inf, idle, unk]; total = somma modalità (4242, tornano esatti)
- [x] Frontend: barre impilate (flex column), colori = palette card (inference arancio PALETTE[0], idle ciano PALETTE[1], unknown grigio var(--mut)), legenda con label identiche alla tabella, tooltip per segmento
- [x] Nota: l'asse max ora è 67 W (host) e non 126 W (fleet): coerente con la colonna "peak W (host)" della tabella
- [x] BUGFIX: escape \ud83d\udca4 in stringa Python -> surrogate non encodabili (UnicodeEncodeError su OGNI richiesta HTML). Fix: emoji 💤 letterale. Lesson: in file .py serviti come HTML, mai escape surrogate JS-style dentro stringhe Python
- [x] VERIFICATO: HTML encode OK (42809 B), HTTP 200, screenshot: stack corretto (idle ciano sinistra, inference arancio destra, unknown grigio), legenda, tooltip
- Acceptance: istogramma con le 3 componenti della tabella ✅

### P61 — Punteggio AA anche per il modello locale ✅ (2026-10-23 11:42, owner request)
- [x] models.aa_for_label(): lookup AA per label con fallback label+" (cloud)" — il punteggio misura il MODELLO, non il provider (stessi pesi/capacità serviti in locale)
- [x] resolve_local_model(): aa_score in tutte le 3 branche (override, free-form, auto-detect); local_options con aa_score
- [x] Frontend: footer "local model: X (AA 41.8) (auto-detected)"; selettore locale opzioni "— AA n.n"; riga LOCAL tabella mensile "— GLM 5.3 Flash [AA 41.8]" badge stile identico al cloud
- [x] VERIFICATO: API local_model.aa_score=41.8; HTML encode OK; screenshot: badge sulla riga locale + footer
- Acceptance: AA accanto al modello locale ✅

### P62 — Config: etichetta AA del modello locale ✅ (2026-10-23 11:55, owner request)
- [x] Badge #locAAbadge accanto al selettore locale in Config: "GLM 5.3 Flash · AA 41.8" (stile .badge, title con fonte)
- [x] Aggiornato a ogni tick: segue auto-detect E override manuale (nascosto se nessun modello risolto)
- [x] VERIFICATO: screenshot Config — badge sotto il selettore, verde accento; HTML encode OK; JS OK
- Acceptance: etichetta AA del locale in Config ✅
