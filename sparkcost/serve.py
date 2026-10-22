"""sparkDash-style dashboard: dark theme, cards, area sparklines, refresh rate. stdlib only.

    python3 -m sparkcost.serve            # http://127.0.0.1:8900

Endpoints:
    /                     dashboard
    /logo.jpg             logo (static/logo.jpg)
    /api/summary          JSON report (?refresh=1 re-downloads the price list, ?local=KEY local-model override)
    /api/capex?value=X    saves the total fleet investment to data/config.yaml
    /api/tariff?value=X   saves the energy tariff eur_per_kwh to data/config.yaml
    /api/hours?value=X    saves the time commitment hours_per_day to data/config.yaml
    /api/price            saves/clears edited prices (model, field=in|out|cache, value | action=clear)
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .localcost import report, save_capex, save_tariff, save_hours, save_amort_years, save_depreciation, save_users, save_price, clear_price

PORT = 8900

LOGO = Path(__file__).resolve().parent / "static" / "logo.jpg"
# Trend palette: orange, cyan, violet, magenta, peach, light cyan
PALETTE = ["#ff6a45", "#2ec8e8", "#8b7cf8", "#c76bd8", "#ffb08a", "#8adfff"]

HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>sparkcost</title><style>
:root{--bg:#000;--card:#0d0d0f;--tx:#dbe4ee;--mut:#7d8ea0;--acc:#4ade80;--b:#1c1c22;--warn:#fbbf24}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);
font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:24px 24px 56px}
h2{font-size:14px;margin:26px 0 10px;color:var(--tx)}
.hdr{margin-bottom:14px}.hdr img{height:110px;max-width:420px;object-fit:contain;display:block}
.sub{color:var(--mut);font-size:12px;margin-bottom:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--b);border-radius:10px;padding:14px}
.card .v{font-size:22px;font-weight:700}
.card .l{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.card svg{display:block;margin-top:8px;width:100%;height:30px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--b);border-radius:10px;overflow:hidden;margin-bottom:8px}
th{font-size:11px;text-transform:uppercase;letter-spacing:.5px;background:#0f2a1c;color:var(--acc);text-align:left;padding:10px 12px;border-bottom:1px solid var(--b)}
td{padding:8px 12px;border-bottom:1px solid var(--b)}tr:last-child td{border:none}
tr.local td{background:#0f2a1c;color:var(--acc);font-weight:700}
tr.mine td{outline:1px solid var(--acc)}
tr.cheapest td{color:var(--warn)}
td.num{text-align:right}th.num{text-align:right}
td .basis{color:var(--mut);font-size:10px}
.bar{background:var(--card);border:1px solid var(--b);border-radius:10px;padding:12px 14px;margin-bottom:20px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.bar .lbl{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin:0 6px 0 0}
.bar select,.bar input{background:#000;color:var(--tx);border:1px solid var(--b);border-radius:8px;padding:5px 8px;font:inherit;font-size:12px}
.bar input{width:110px;text-align:right}
.bar button{background:#000;color:var(--acc);border:1px solid var(--acc);border-radius:8px;
padding:5px 14px;font:inherit;font-size:12px;cursor:pointer}
.bar button:disabled{color:var(--mut);border-color:var(--b);cursor:wait}
.bar .rt{padding:4px 10px;font-size:11px;color:var(--mut);border-color:var(--b)}
tr.hd-red th{background:#4a1520;color:#ffb08a}
.bar .rt.on{color:var(--acc);border-color:var(--acc)}
.bar .sep{flex:1}
td input.pr{background:#000;color:var(--tx);border:1px solid transparent;border-radius:6px;
padding:2px 6px;font:inherit;font-size:12px;text-align:right;width:72px}
td input.pr:hover{border-color:var(--b)}td input.pr:focus{border-color:var(--acc);outline:none}
td input.pr.edited{border-color:var(--warn);color:var(--warn)}
td input.pr:disabled{color:var(--mut);border-color:transparent}
.badge{color:var(--warn);font-size:10px;margin-left:4px}
#locwarn,#capexsaved,#tariffsaved,#hourssaved{color:var(--warn);font-size:11px;margin-left:6px}
#capexsaved,#tariffsaved,#hourssaved,#amortsaved,#userssaved{color:var(--acc)}
.footer{position:fixed;left:0;right:0;bottom:0;background:var(--bg);border-top:1px solid var(--b);
padding:8px 24px;font-size:12px;color:var(--mut);z-index:9}
</style></head><body>
<div class="hdr"><img src="/logo.jpg" alt="sparkcost"></div>
<div class="cards" id="cards"></div>

<div class="bar">
 <span class="lbl">Investment &euro;</span>
 <input id="capex" type="number" step="0.01" min="0" placeholder="8856.94">
 <span id="capexsaved"></span>
 <span class="lbl">&nbsp;&nbsp;Energy &euro;/kWh</span>
 <input id="tariff" type="number" step="0.01" min="0" placeholder="0.28">
 <span id="tariffsaved"></span>
 <span class="lbl">&nbsp;&nbsp;Hours/day</span>
 <input id="hours" type="number" step="0.5" min="0" max="24" placeholder="8">
 <span id="hourssaved"></span>
 <span class="lbl">&nbsp;&nbsp;Amort years</span>
 <input id="amort" type="number" step="1" min="1" max="15" placeholder="5">
 <span id="amortsaved"></span>
 <label class="chip" id="deprchip" title="uncheck if the Spark was bought privately: capex not depreciated, local cost = energy only">
  <input id="depr" type="checkbox" checked> Depreciate</label>
 <span class="sep"></span>
 <span class="lbl">&nbsp;&nbsp;Cluster users</span>
 <input id="users" type="number" step="1" min="1" max="50" placeholder="2">
 <span id="userssaved"></span>
 <span class="sep"></span>
 <span class="lbl">Cloud model</span>
 <select id="cloudsel"></select>
 <span class="sep"></span>
 <span class="lbl">Local model</span>
 <select id="locsel"><option value="">Auto-detect…</option></select>
 <span id="locwarn"></span>
 <span class="sep"></span>
 <button id="resetBtn" title="Restore online price list">&#8634; Reset prices</button>
 <button id="refreshBtn">&#8635; Refresh prices</button>
</div>

<h2>Monthly cost &mdash; local 24/7 vs cloud at your current token rate</h2>
<div class="sub" id="replaysub"></div>
<table><thead><tr class="hd-red"><th>Model</th><th class="num">in &euro;/1M</th><th class="num">out &euro;/1M</th>
<th class="num">month cost</th><th class="num">batch API</th><th>basis</th></tr></thead>
<tbody id="replay"></tbody></table>
<div class="sub">edit in/out prices to adapt them (amber border = edited, ✎ badge) &middot; AA = Artificial Analysis Intelligence Index (2026-10-20) &middot; open-weight: token cost projected monthly at your current hourly rate x Hours/day, x Cluster users (cache 90% incl. cache-write on misses; batch API = batch price list for non-interactive work) &middot; &#11014;Nx &gt;272k = long-context surcharge on input above the threshold &middot; closed-weight: fixed top-tier subscription x Cluster users &middot; local: fleet fixed cost, always on (shared between users)</div>

<h2>Investment break-even &mdash; <span id="bkmodel" style="color:var(--acc)"></span> vs local</h2>
<div class="sub" id="bksub"></div>
<table><thead><tr><th>Model</th><th class="num">in &euro;/1M</th><th class="num">out &euro;/1M</th><th>scenario</th><th class="num">cloud/month</th>
<th class="num">savings/month</th><th class="num">payback</th></tr></thead>
<tbody id="bk"></tbody></table>
<div class="sub">payback = months of cloud savings needed to repay the investment, at the current usage rate projected monthly &middot; scenarios: no-cache, cache 90% (incl. cache-write), batch API (where the price list exposes batch prices) &middot; in &euro;/1M = effective input price used by the calculation (read-only here) &middot; out &euro;/1M editable (same override as the first table) &middot; open-weight scenarios per-token, closed-weight top-tier subscription</div>

<h2>Repaid so far &mdash; <span id="rp2model" style="color:var(--acc)"></span> vs local (investment covered by real usage)</h2>
<div class="sub" id="rpsub"></div>
<table><thead><tr><th>Model</th><th class="num">cloud cached (total)</th><th class="num">local cost (total)</th><th class="num">savings</th><th class="num">repaid</th></tr></thead>
<tbody id="rp2"></tbody></table>
<div class="sub">cumulative totals from data/token_ledger.json &mdash; persistent across server restarts and reboots (counters reset is detected and folded in) &middot; local cost at the measured rate applied to the whole history &middot; repaid = share of the investment already covered by real usage, up to date</div>
<div class="footer" id="sub">loading...</div>
<script>
const fmt=n=>n==null||isNaN(n)?'':n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(0)+'k':''+Math.round(n);
const eur=n=>n==null||isNaN(n)?'':'€'+(+n).toFixed(2);
const e1=n=>n==null||isNaN(n)?'—':(+n).toFixed(2);
const PALETTE=['#ff6a45','#2ec8e8','#8b7cf8','#c76bd8','#ffb08a','#8adfff'];
const DEF_CLOUD='GLM 5.3 Flash (cloud)';
let cloudModel=localStorage.getItem('sparkcost.cloud')||DEF_CLOUD;
let locBuilt=false, localLabel=null;
let localOverride=localStorage.getItem('sparkcost.local')||'';
let hist={};
try{const h=JSON.parse(localStorage.getItem('sparkcost.hist'));if(h&&typeof h==='object')hist=h;}catch(e){}

function pushHist(key,val){
 if(!hist[key])hist[key]=[];
 if(val!=null&&!isNaN(val))hist[key].push(+val);
 if(hist[key].length>20)hist[key]=hist[key].slice(-20);
 localStorage.setItem('sparkcost.hist',JSON.stringify(hist));
}
function sparkline(key,color){
 const pts=hist[key]||[];
 if(pts.length<2)return '';
 const w=100,h=30,pad=2;
 const mn=Math.min(...pts),mx=Math.max(...pts),rg=(mx-mn)||1;
 const xy=pts.map((v,i)=>[pad+i*(w-2*pad)/(pts.length-1), h-pad-((v-mn)/rg)*(h-2*pad)]);
 const line='M'+xy.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' L');
 const area=line+` L${xy[xy.length-1][0].toFixed(1)},${h} L${xy[0][0].toFixed(1)},${h} Z`;
 const gid='g'+key;
 const last=xy[xy.length-1];
 return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
  <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
   <stop offset="0" stop-color="${color}" stop-opacity="0.5"/>
   <stop offset="1" stop-color="${color}" stop-opacity="0.03"/>
  </linearGradient></defs>
  <path d="${area}" fill="url(#${gid})"/>
  <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" opacity="0.95"
   style="filter:drop-shadow(0 0 3px ${color})"/>
  <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.2" fill="${color}"
   style="filter:drop-shadow(0 0 3px ${color})"/></svg>`;
}

function buildLocalSelector(d){
 const sel=document.getElementById('locsel');
 const opts=[['','Auto-detect'+(d.server&&d.server.name?' ('+d.server.name+')':'')]];
 for(const o of (d.local_options||[]))opts.push([o.key,o.label]);
 sel.innerHTML='';
 for(const [v,t] of opts){
  const op=document.createElement('option');
  op.value=v;op.textContent=t;
  sel.appendChild(op);
 }
 sel.value=localOverride;
 if(localOverride && !d.local_options.some(o=>o.key===localOverride))sel.value='';
}

function buildCloudSelector(models){
 const sel=document.getElementById('cloudsel');
 if(!models.some(m=>m.model===cloudModel))cloudModel=DEF_CLOUD;
 sel.innerHTML='';
 const sorted=models.slice().sort((a,b)=>a.model.localeCompare(b.model));
 for(const m of sorted){
  const op=document.createElement('option');
  op.value=m.model;
  op.textContent=m.model+(m.aa_score!=null?`  —  AA ${m.aa_score.toFixed(1)}`:'');
  if(m.model===cloudModel)op.selected=true;
  sel.appendChild(op);
 }
}

async function tick(force){ try{
 // full pause while a price field is in focus: re-rendering would destroy the edit
 const ae=document.activeElement;
 if(ae&&ae.classList&&ae.classList.contains('pr'))return;
 const params=[];
 if(force)params.push('refresh=1');
 if(localOverride)params.push('local='+encodeURIComponent(localOverride));
 const q=params.length?'?'+params.join('&'):'';
 const d=await(await fetch('/api/summary'+q)).json();
 if(d.error){document.getElementById('sub').textContent='error: '+d.error;return;}
 const L=d.local, cfg=d.cfg, rp=d.replay, lm=d.local_model||{};
 localLabel=lm.label||null;
 document.getElementById('sub').textContent=
  `${d.server.backend||'?'} :${d.server.port||'?'} · ${d.server.model||'?'} · local model: ${lm.label||'?'}${lm.detected?' (auto-detected)':''}`+
  (d.snapshot_age_h!=null?` · price list ${d.snapshot_age_h<1?Math.round(d.snapshot_age_h*60)+' min':d.snapshot_age_h.toFixed(0)+' h'} old`:'')+
  (()=>{const es=d.energy_source||{};
   if(es.mode==='integrated')return ` · power ${(+L.watts_fleet).toFixed(1)} W fleet time-weighted over ${Math.round(es.span_s/60)} min (${es.samples} samples)`;
   if(es.mode==='spot')return ' · power spot reading (sampler warming up)';
   return '';})();
 const ci=document.getElementById('capex');
 if(document.activeElement!==ci && d.capex_eur!=null)ci.value=(+d.capex_eur).toFixed(2);
 const ti=document.getElementById('tariff');
 if(document.activeElement!==ti && cfg.eur_per_kwh!=null)ti.value=(+cfg.eur_per_kwh).toFixed(2);
 const hi=document.getElementById('hours');
 if(document.activeElement!==hi && cfg.hours_per_day!=null)hi.value=+cfg.hours_per_day;
 const ai=document.getElementById('amort');
 if(document.activeElement!==ai && cfg.amort_years!=null)ai.value=+cfg.amort_years;
 ai.disabled=cfg.depreciation===false;
 const ui=document.getElementById('users');
 if(document.activeElement!==ui && cfg.users!=null)ui.value=+cfg.users;
 const de=document.getElementById('depr');
 if(de)de.checked=cfg.depreciation!==false;

 pushHist('power',L.watts_fleet);pushHist('eff',L.eff_eur_1m);
 // sparklines ONLY on: fleet power, local effective
 const cards=[
  ['active units',(cfg.n_sparks||1)+' Spark',null,null],
  ['prompt tokens (total)',fmt(+(d.ledger?d.ledger.prompt_total:d.counters.prompt_total)||0),null,null],
  ['generated tokens (total)',fmt(+(d.ledger?d.ledger.gen_total:d.counters.gen_total)||0),null,null],
  ['fleet power',(L.watts_fleet||0).toFixed(1)+' W','power',PALETTE[0]],
  ['local effective (measured)','€'+(+L.eff_eur_1m).toFixed(2)+'/1M','eff',PALETTE[5]],
  ['monthly fixed','€'+(+L.fixed_month_eur).toFixed(0),null,null],
  ['tariff',cfg.eur_per_kwh+' €/kWh',null,null]];
 document.getElementById('cards').innerHTML=cards.map(c=>{
  const spark=(c[2]&&hist[c[2]]&&hist[c[2]].length>1)?sparkline(c[2],c[3]):'';
  const vc=c[3]?` style="color:${c[3]}"`:'';
  return `<div class="card"><div class="l">${c[0]}</div><div class="v"${vc}>${c[1]}</div>${spark}</div>`;
 }).join('');

 if(!locBuilt && rp){buildLocalSelector(d);locBuilt=true;}
 if(rp)buildCloudSelector(rp.models);

 // TABLE 1: local + ONLY the selected cloud model
 const rep=document.getElementById('replay');
 if(rp){
  const period=rp.uptime_days<1?(rp.uptime_days*24).toFixed(1)+' h':rp.uptime_days.toFixed(1)+' days';
  document.getElementById('replaysub').textContent=
   `projected on ${(rp.pt_m_month/1e9).toFixed(2)}B prompt + ${(rp.gt_m_month/1e6).toFixed(0)}M gen per month (${rp.projection_basis||'24/7'}) · `+
   (rp.local_month_parts?
    `local month: ${eur(rp.local_month_eur)} = amortization ${eur(rp.local_month_parts.amort)} + idle energy ${eur(rp.local_month_parts.idle_energy)} + token energy ${eur(rp.local_month_parts.token_energy)} (fleet 24/7)`:
    `local month: ${eur(rp.local_month_eur)} (amortization ${eur(rp.amort_month_eur)} + energy ${eur(rp.energy_month_eur)}, fleet 24/7)`);
  const sel=rp.models.find(m=>m.model===cloudModel)||rp.models[0];
  let rh=`<tr class="local"><td>→ LOCAL DGX Spark (fleet 24/7)</td><td class="num">${e1(rp.local_eur_1m)}</td><td class="num">—</td><td class="num">${eur(rp.local_month_eur)}</td><td class="num">—</td><td><span class="basis">amortization + energy, no volume cap</span></td></tr>`;
  if(sel){
   const mine=localLabel&&sel.model===localLabel;
   const ed=sel.edited?`<span class="badge" title="edited price">✎</span>`:'';
   const aa=sel.aa_score!=null?`<span class="badge" title="Artificial Analysis Intelligence Index (benchlm.ai, 2026-10-20)">AA ${sel.aa_score.toFixed(1)}</span>`:'';
   const dis=sel.month_sub?' disabled title="fixed subscription cost - edit plans in data/config.yaml"':'';
   const lc=sel.lc_mult?`<span class="badge" style="color:var(--warn)" title="input price x${sel.lc_mult} above the long-context threshold (LiteLLM price list)">&#11014; ${sel.lc_mult}x &gt;272k</span>`:'';
   const mb=sel.month_batch_eur!=null?`<td class="num">${eur(sel.month_batch_eur)}</td>`:'<td class="num">&mdash;</td>';
   rh+=`<tr class="${mine?'mine':''}"><td>${sel.model}${mine?' ★':''} ${aa}${ed}${lc}</td>`+
    `<td class="num"><input class="pr${sel.edited?' edited':''}" data-model="${sel.model}" data-field="in" value="${(+sel.in_eur_1m).toFixed(3)}"${dis}></td>`+
    `<td class="num"><input class="pr${sel.edited?' edited':''}" data-model="${sel.model}" data-field="out" value="${(+sel.out_eur_1m).toFixed(3)}"${dis}></td>`+
    `<td class="num">${eur(sel.month_cost_eur)}</td>${mb}<td><span class="basis">${sel.month_basis}</span></td></tr>`;
  }
  rep.innerHTML=rh;
 } else { rep.innerHTML='<tr><td colspan="5">server uptime unavailable</td></tr>'; }

 // TABLE 2: break-even for the selected cloud model ONLY
 const bk=document.getElementById('bk');
 if(d.breakeven){
  const b=d.breakeven;
  const scen=b.scenarios.filter(s=>s.model===cloudModel);
  document.getElementById('bkmodel').textContent=cloudModel;
  document.getElementById('bksub').textContent=
   `investment ${eur(b.capex)} · calculation basis: ${b.basis} · `+
   `local cost/month ${eur(b.local_month_eur)} = amortization ${eur(b.local_month_parts?.amort??b.amort_month_eur)} + idle energy ${eur(b.local_month_parts?.idle_energy??b.energy_month_eur)} + token energy ${eur(b.local_month_parts?.token_energy??0)}`+
   (b.capex_note?` &middot; ${b.capex_note}`:'');
  let bh=''; let prevModel=null;
  scen.forEach(s=>{
   const isSub=s.scenario.includes('(sub)');
   const pb=s.payback_days?(s.payback_days<400?s.payback_days.toFixed(0)+' days':s.payback_days<3650?s.payback_months.toFixed(1)+' months ('+(s.payback_months/12).toFixed(1)+' years)':(s.payback_months/12).toFixed(1)+' years'):'never';
   // same model as the previous row: "└" instead of repeating it
   const name=(s.model===prevModel)?'└ same model':s.model;
   prevModel=s.model;
   bh+=`<tr><td>${name}</td><td class="num">${isSub?'—':e1(s.in_eff_eur_1m??s.in_eur_1m)}</td>`+
    `<td class="num">${isSub?'—':`<input class="pr" data-model="${s.model}" data-field="out" value="${(+s.out_eur_1m).toFixed(3)}">`}</td>`+
    `<td>${s.scenario}</td><td class="num">${eur(s.cloud_month_eur)}</td><td class="num">${eur(s.savings_month_eur)}</td><td class="num">${pb}</td></tr>`;
  });
  bk.innerHTML=bh||'<tr><td colspan="7">no token scenario for subscriptions</td></tr>';
 } else { bk.innerHTML='<tr><td colspan="7">usage rate not yet available</td></tr>'; }

 // TABELLA 3: repaid so far (ledger persistente, up to date)
 {
  const rp2=document.getElementById('rp2');
  if(d.repaid){
   const r=d.repaid;
   document.getElementById('rpsub').textContent=
    `cumulative ${(r.prompt_total/1e9).toFixed(2)}B prompt + ${(r.gen_total/1e6).toFixed(0)}M gen since ${new Date((r.first_ts||0)*1000).toLocaleDateString()} · local cost ${eur(r.local_cost_eur)} at the measured rate · investment ${eur(r.capex)}`;
   document.getElementById('rp2model').textContent=cloudModel;
   const selRows=r.models.filter(m=>m.model===cloudModel);
   rp2.innerHTML=(selRows.length?selRows:[{model:cloudModel,cloud_cached_eur:null,savings_cached_eur:null,repaid_pct:0}]).map(m=>
    `<tr><td>${m.model}</td><td class="num">${m.cloud_cached_eur==null?'—':eur(m.cloud_cached_eur)}</td><td class="num">${eur(r.local_cost_eur)}</td><td class="num">${m.savings_cached_eur==null?'—':eur(m.savings_cached_eur)}</td><td class="num">${m.repaid_pct.toFixed(1)}%</td></tr>`
   ).join('');
  } else rp2.innerHTML='<tr><td colspan="5">ledger warming up (fills on the next refresh)</td></tr>';
 }
 }catch(err){document.getElementById('sub').textContent='render error: '+err.message;console.error(err);}}

let rate=+(localStorage.getItem('sparkcost.rate')||1);
if(![1,5,10].includes(rate))rate=1;
function applyRateBtns(){document.querySelectorAll('.rt').forEach(b=>b.classList.toggle('on',+b.dataset.s===rate));}
document.querySelectorAll('.rt').forEach(b=>b.addEventListener('click',()=>{
 rate=+b.dataset.s;localStorage.setItem('sparkcost.rate',rate);
 applyRateBtns();tick();
}));
applyRateBtns();

document.getElementById('refreshBtn').addEventListener('click',async()=>{
 const btn=document.getElementById('refreshBtn');
 btn.disabled=true;btn.textContent='Updating price list…';
 try{await tick(true);}finally{btn.disabled=false;btn.textContent='⟳ Refresh prices';}
});
document.getElementById('resetBtn').addEventListener('click',async()=>{
 const btn=document.getElementById('resetBtn');
 btn.disabled=true;
 try{await(await fetch('/api/price?action=clear')).json();await tick();}
 finally{btn.disabled=false;}
});
document.getElementById('locsel').addEventListener('change',e=>{
 localOverride=e.target.value;
 localStorage.setItem('sparkcost.local',localOverride);
 document.getElementById('locwarn').textContent='';
 tick();
});
document.getElementById('cloudsel').addEventListener('change',e=>{
 cloudModel=e.target.value;
 localStorage.setItem('sparkcost.cloud',cloudModel);
 tick();
});
document.getElementById('capex').addEventListener('change',async e=>{
 const v=parseFloat(e.target.value);
 const out=document.getElementById('capexsaved');
 if(!(v>0)){out.textContent='invalid value';setTimeout(()=>out.textContent='',2500);return;}
 const r=await(await fetch('/api/capex?value='+encodeURIComponent(v))).json();
 if(r.ok){out.textContent='saved ✓';await tick();}
 else out.textContent=r.error||'error';
 setTimeout(()=>out.textContent='',2500);
});
document.getElementById('tariff').addEventListener('change',async e=>{
 const v=parseFloat(e.target.value);
 const out=document.getElementById('tariffsaved');
 if(!(v>0)){out.textContent='invalid value';setTimeout(()=>out.textContent='',2500);return;}
 const r=await(await fetch('/api/tariff?value='+encodeURIComponent(v))).json();
 if(r.ok){out.textContent='saved ✓';await tick();}
 else out.textContent=r.error||'error';
 setTimeout(()=>out.textContent='',2500);
});
document.getElementById('amort').addEventListener('change',async e=>{
 const v=parseFloat(e.target.value);
 const out=document.getElementById('amortsaved');
 if(!(v>=1)||v>15){out.textContent='1-15 only';setTimeout(()=>out.textContent='',2500);return;}
 const r=await(await fetch('/api/amort?value='+encodeURIComponent(v))).json();
 if(r.ok){out.textContent='saved ✓';await tick();}
 else out.textContent=r.error||'error';
 setTimeout(()=>out.textContent='',2500);
});
document.getElementById('users').addEventListener('change',async e=>{
 const v=parseInt(e.target.value,10);
 const out=document.getElementById('userssaved');
 if(!(v>=1)||v>50){out.textContent='1-50 only';setTimeout(()=>out.textContent='',2500);return;}
 const r=await(await fetch('/api/users?value='+encodeURIComponent(v))).json();
 if(r.ok){out.textContent='saved ✓';await tick();}
 else out.textContent=r.error||'error';
 setTimeout(()=>out.textContent='',2500);
});
document.getElementById('depr').addEventListener('change',async e=>{
 const r=await(await fetch('/api/depreciation?value='+e.target.checked)).json();
 if(r.ok)await tick();
});
document.getElementById('hours').addEventListener('change',async e=>{
 const v=parseFloat(e.target.value);
 const out=document.getElementById('hourssaved');
 if(!(v>0)||v>24){out.textContent='0-24 only';setTimeout(()=>out.textContent='',2500);return;}
 const r=await(await fetch('/api/hours?value='+encodeURIComponent(v))).json();
 if(r.ok){out.textContent='saved ✓';await tick();}
 else out.textContent=r.error||'error';
 setTimeout(()=>out.textContent='',2500);
});
document.addEventListener('change',async e=>{
 const inp=e.target;
 if(!inp.classList||!inp.classList.contains('pr')||inp.disabled)return;
 const v=parseFloat(String(inp.value).replace(',','.'));
 if(!(v>0)){await tick();return;}
 const r=await(await fetch('/api/price?model='+encodeURIComponent(inp.dataset.model)+
   '&field='+inp.dataset.field+'&value='+encodeURIComponent(v))).json();
 if(r.ok)await tick();else console.error(r.error);
});
(async function loop(){try{await tick();}catch(e){}setTimeout(loop,rate*1000);})();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")  # never serve stale JSON/HTML
        self.end_headers()
        self.wfile.write(body)

    def _save_param(self, q, saver) -> None:
        try:
            v = float((q.get("value") or ["0"])[0])
            if v <= 0:
                raise ValueError("value must be positive")
            saver(v)
            self._send(200, json.dumps({"ok": True, "value": v}).encode(),
                       "application/json")
        except (ValueError, TypeError) as e:
            self._send(400, json.dumps({"ok": False, "error": str(e)}).encode(),
                       "application/json")

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/summary":
            try:
                rep = report(refresh=q.get("refresh") == ["1"],
                             local_key=(q.get("local") or [None])[0])
                payload = json.dumps(rep, indent=None, default=str)
                self._send(200, payload.encode(), "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"error": str(e)}).encode(),
                           "application/json")
        elif u.path == "/api/capex":
            self._save_param(q, save_capex)
        elif u.path == "/api/tariff":
            self._save_param(q, save_tariff)
        elif u.path == "/api/hours":
            self._save_param(q, save_hours)
        elif u.path == "/api/amort":
            self._save_param(q, save_amort_years)
        elif u.path == "/api/depreciation":
            enabled = q.get("value", ["true"])[0].lower() not in ("false", "0", "no")
            save_depreciation(enabled)
            self._send(200, json.dumps({"ok": True, "depreciation": enabled}).encode(),
                       "application/json")
        elif u.path == "/api/users":
            self._save_param(q, save_users)
        elif u.path == "/api/price":
            try:
                if q.get("action") == ["clear"]:
                    clear_price((q.get("model") or [None])[0])
                    self._send(200, json.dumps({"ok": True, "cleared": True}).encode(),
                               "application/json")
                    return
                model = (q.get("model") or [""])[0]
                field = (q.get("field") or [""])[0]
                v = float((q.get("value") or ["0"])[0])
                if not model or field not in ("in", "out", "cache") or v <= 0:
                    raise ValueError("bad params: model, field(in|out|cache), value>0")
                usd = report()["cfg"]["usd_eur"]
                save_price(model, field, v, usd)
                self._send(200, json.dumps({"ok": True, "model": model, "field": field,
                                            "eur_1m": v}).encode(),
                           "application/json")
            except (ValueError, TypeError) as e:
                self._send(400, json.dumps({"ok": False, "error": str(e)}).encode(),
                           "application/json")
        elif u.path == "/api/crosscheck":
            # P37: LiteLLM vs aitokenprice price-list consistency (read-only;
            # network only with ?refresh=1, never in the 10s dashboard tick)
            try:
                from . import models as M
                data = M.fetch_snapshot()
                try:
                    atp = M.load_atp(refresh=q.get("refresh") == ["1"])
                except Exception as e:  # noqa: BLE001 — offline: cache o errore esplicito
                    if not M.ATP_SNAPSHOT.exists():
                        raise
                    atp = M.load_atp()
                rows = M.crosscheck(data, atp)
                self._send(200, json.dumps({"rows": rows,
                                            "atp_age_h": M.atp_age_h()
                                            }).encode(), "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"error": str(e)}).encode(),
                           "application/json")
        elif u.path == "/logo.jpg":
            try:
                self._send(200, LOGO.read_bytes(), "image/jpeg")
            except OSError:
                self._send(404, b"logo not found", "text/plain")
        elif u.path == "/":
            self._send(200, HTML.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *a) -> None:  # silence request logging
        pass


def main() -> None:
    print(f"sparkcost su http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
