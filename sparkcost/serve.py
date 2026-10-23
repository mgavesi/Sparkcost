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

from .localcost import report, save_capex, save_tariff, save_hours, save_amort_years, save_depreciation, save_users, save_n_sparks, save_cfg_params, save_price, clear_price
from .collect import save_fleet, test_fleet_host
from .stats import fleet_stats, live_power

PORT = 8900

LOGO = Path(__file__).resolve().parent / "static" / "logo.jpg"
LOGO_LIGHT = Path(__file__).resolve().parent / "static" / "logo-light.jpg"  # P51: testo scuro per tema light
# Trend palette: orange, cyan, violet, magenta, peach, light cyan
PALETTE = ["#ff6a45", "#2ec8e8", "#8b7cf8", "#c76bd8", "#ffb08a", "#8adfff"]

HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>sparkcost</title><style>
:root{--bg:#000;--card:#0d0d0f;--tx:#dbe4ee;--mut:#7d8ea0;--acc:#4ade80;--b:#1c1c22;--warn:#fbbf24;--thbg:#0f2a1c;--inputbg:#000;--navact:#1a2027}
body.light{--bg:#eef1f5;--card:#fff;--tx:#1b2530;--mut:#5c6b7a;--acc:#0b8f4d;--b:#d7dde4;--warn:#b45309;--thbg:#e2f3ea;--inputbg:#fff;--navact:#dde3ea}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);
font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:24px 24px 56px}
h2{font-size:14px;margin:26px 0 10px;color:var(--tx)}
.hdr{margin-bottom:10px}
.hdr img{width:100%;height:auto;max-height:110px;object-fit:contain;display:block}
#themeBtn{display:inline-block;width:auto;background:transparent;color:var(--mut);border:none;border-radius:8px;padding:8px 10px;font-size:16px;cursor:pointer;margin:auto 0 0;line-height:1;align-self:flex-start}
#themeBtn:hover{color:var(--tx);background:var(--navact)}
.sub{color:var(--mut);font-size:12px;margin-bottom:20px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}
@media(max-width:1500px){.cards{grid-template-columns:repeat(2,1fr)}}
@media(max-width:900px){.cards{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--b);border-radius:12px;padding:16px 18px}
.card .v{font-size:32px;font-weight:700}
.card .l{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
.card svg{display:block;margin-top:8px;width:100%;height:30px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--b);border-radius:10px;overflow:hidden;margin-bottom:8px}
th{font-size:11px;text-transform:uppercase;letter-spacing:.5px;background:var(--thbg);color:var(--acc);text-align:left;padding:10px 12px;border-bottom:1px solid var(--b)}
td{padding:8px 12px;border-bottom:1px solid var(--b)}tr:last-child td{border:none}
tr.local td{background:var(--thbg);color:var(--acc);font-weight:700}
tr.mine td{outline:1px solid var(--acc)}
tr.cheapest td{color:var(--warn)}
td.num{text-align:right}th.num{text-align:right}
td .basis{color:var(--mut);font-size:10px}
.wrap{display:flex;gap:20px;align-items:flex-start}
.side{width:280px;flex-shrink:0;background:var(--card);border:1px solid var(--b);border-radius:12px;padding:16px;position:sticky;top:16px;display:flex;flex-direction:column;height:calc(100vh - 32px);overflow-y:auto}
.side .lbl{display:block;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin:12px 0 4px}
.side .sech{display:block;color:var(--acc);font-size:10px;letter-spacing:1.2px;text-transform:uppercase;margin:16px 0 2px;border-bottom:1px solid var(--b);padding-bottom:3px;font-weight:700}
.field{display:flex;align-items:center;gap:6px;margin-top:2px}
.field input,.side select{flex:1;min-width:0;background:var(--inputbg);color:var(--tx);border:1px solid var(--b);border-radius:8px;padding:6px 8px;font:inherit;font-size:12px;box-sizing:border-box}
.field input:focus,.side select:focus{border-color:var(--acc);outline:none}
.saved{color:var(--acc);font-size:11px;white-space:nowrap}
.side button{display:block;width:100%;background:var(--inputbg);color:var(--acc);border:1px solid var(--acc);border-radius:8px;padding:6px 0;font:inherit;font-size:12px;cursor:pointer;margin-top:10px}
.side button:disabled{color:var(--mut);border-color:var(--b);cursor:wait}
.fleetbox{margin-top:16px;border:1px solid var(--b);border-radius:8px;padding:8px 10px}
.fleetbox summary{cursor:pointer;font-size:12px;color:var(--mut);user-select:none}
.fleethint{color:var(--mut);font-size:10px;margin:6px 0}
.frow{display:grid;grid-template-columns:1.2fr 62px 52px;gap:4px;margin:6px 0;border:1px solid var(--b);border-radius:6px;padding:6px}
.frow input,.frow select{width:100%;background:var(--inputbg);color:var(--tx);border:1px solid var(--b);border-radius:6px;padding:4px 6px;font:inherit;font-size:11px;box-sizing:border-box}
.frow button{display:inline-block;width:auto;padding:4px 8px;margin:0;font-size:11px}
.fbtns{display:flex;flex-direction:column;align-items:flex-start;gap:6px;margin-top:6px}
.cgrid .fbtns button,.side .fbtns button{width:auto;display:inline-block;padding:6px 12px;margin:0;flex:0 0 auto}
#fleetMsg{font-size:10px;color:var(--acc)}
.fres{font-size:10px;color:var(--acc);grid-column:1/-1;min-height:12px}
.side .chip{display:flex;align-items:center;gap:6px;font-size:12px;margin-top:10px;cursor:pointer}
.menu{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.side .menu .navbtn{display:block;width:100%;background:transparent;color:var(--mut);border:1px solid transparent;border-radius:8px;padding:9px 12px;font:500 14px/1.3 ui-sans-serif,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;cursor:pointer;text-align:left;margin:0;letter-spacing:0;box-shadow:none}
.side .menu .navbtn:hover{background:var(--navact);color:var(--tx)}
.side .menu .navbtn.active{background:var(--navact);color:var(--tx);font-weight:600;border-color:transparent}
.view[hidden]{display:none}
.cgrid{display:grid;grid-template-columns:repeat(3,minmax(220px,1fr));gap:0 28px;align-items:start}
@media(max-width:1200px){.cgrid{grid-template-columns:1fr 1fr}}
@media(max-width:700px){.cgrid{grid-template-columns:1fr}}
.cparam{min-width:0}.cparam select{width:100%;box-sizing:border-box}
.cgrid .lbl{display:block;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin:12px 0 4px}
.cgrid .field input,.cgrid select{flex:1;min-width:0;background:var(--inputbg);color:var(--tx);border:1px solid var(--b);border-radius:8px;padding:6px 8px;font:inherit;font-size:12px;box-sizing:border-box}
.cgrid .field input:focus,.cgrid select:focus{border-color:var(--acc);outline:none}
.cgrid .chip{display:flex;align-items:center;gap:6px;font-size:12px;margin-top:10px;cursor:pointer}
.cgrid .sech{display:block;color:var(--acc);font-size:10px;letter-spacing:1.2px;text-transform:uppercase;margin:16px 0 2px;border-bottom:1px solid var(--b);padding-bottom:3px;font-weight:700;grid-column:1/-1}
.cgrid button{display:block;width:100%;background:var(--inputbg);color:var(--acc);border:1px solid var(--acc);border-radius:8px;padding:6px 0;font:inherit;font-size:12px;cursor:pointer;margin-top:10px}
.cgrid button:disabled{color:var(--mut);border-color:var(--b);cursor:wait}
.cgrid .fleetbox{grid-column:1/-1}
.winrow{display:flex;gap:6px;align-items:center;margin-bottom:14px}
.winrow .lbl{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.winbtn{display:inline-block;width:auto;background:var(--inputbg);color:var(--tx);border:1px solid var(--b);border-radius:8px;padding:4px 12px;font:inherit;font-size:12px;cursor:pointer;margin:0}
.winbtn.active{border-color:var(--acc);color:var(--acc);font-weight:700}
.main{flex:1;min-width:0}
@media (max-width:900px){.wrap{flex-direction:column}.side{width:100%;position:static;height:auto}#themeBtn{margin:6px 0 0}}
tr.hd-red th{background:#4a1520;color:#ffb08a}
.bar .rt.on{color:var(--acc);border-color:var(--acc)}
.bar .sep{flex:1}
td input.pr{background:var(--inputbg);color:var(--tx);border:1px solid transparent;border-radius:6px;
padding:2px 6px;font:inherit;font-size:12px;text-align:right;width:72px}
td input.pr:hover{border-color:var(--b)}td input.pr:focus{border-color:var(--acc);outline:none}
td input.pr.edited{border-color:var(--warn);color:var(--warn)}
td input.pr:disabled{color:var(--mut);border-color:transparent}
.badge{color:var(--warn);font-size:10px;margin-left:4px}
#locwarn{color:var(--warn);font-size:11px}
.footer{position:fixed;left:0;right:0;bottom:0;background:var(--bg);border-top:1px solid var(--b);
padding:8px 24px;font-size:12px;color:var(--mut);z-index:9}
</style></head><body>
<div class="wrap">
<aside class="side">
 <div class="hdr"><img id="logoImg" src="/logo.jpg" alt="sparkcost"></div>
 <nav class="menu">
  <button class="navbtn active" data-view="dash" type="button">&#128202; Dash</button>
  <button class="navbtn" data-view="config" type="button">&#9881; Config</button>
  <button class="navbtn" data-view="stats" type="button">&#9889; Statistics</button>
 </nav>
 <button id="themeBtn" type="button" title="dark / light">&#9728;&#65039;</button>
</aside>
<div class="main">
<div id="view-dash" class="view">
<div class="cards" id="cards"></div>



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
</div>
 <div id="view-config" class="view" hidden>
  <h2>Configuration &mdash; all input parameters</h2>
  <div class="sub">changes save on edit (saved &check; badge) &middot; passwords are stored server-side (0600) and never echoed</div>
  <div class="cgrid">
 
 <span class="sech">Investment &amp; fleet</span>
 <div class="cparam"><span class="lbl">Investment &euro;</span> <div class="field"><input id="capex" type="number" step="0.01" min="0" placeholder="8856.94"><span class="saved" id="capexsaved"></span></div></div>
 <div class="cparam"><span class="lbl">Number of machines</span> <div class="field"><input id="cfg_n_sparks" type="number" step="1" min="1" max="64"><span class="saved" id="cfgsaved_n_sparks"></span></div></div>
 <div class="cparam"><span class="lbl">Idle W / unit</span> <div class="field"><input id="cfg_idle_watts" type="number" step="1" min="1" max="2000"><span class="saved" id="cfgsaved_idle_watts"></span></div></div>
 <div class="cparam"><span class="lbl">USD &rarr; EUR</span> <div class="field"><input id="cfg_usd_eur" type="number" step="0.01" min="0" max="10"><span class="saved" id="cfgsaved_usd_eur"></span></div></div>
 <span class="sech">Energy &amp; usage</span>
 <div class="cparam"><span class="lbl">Energy &euro;/kWh</span> <div class="field"><input id="tariff" type="number" step="0.01" min="0" placeholder="0.28"><span class="saved" id="tariffsaved"></span></div></div>
 <div class="cparam"><span class="lbl">Hours/day</span> <div class="field"><input id="hours" type="number" step="0.5" min="0" max="24" placeholder="8"><span class="saved" id="hourssaved"></span></div></div>
 <div class="cparam"><span class="lbl">Amort years</span> <div class="field"><input id="amort" type="number" step="1" min="1" max="15" placeholder="5"><span class="saved" id="amortsaved"></span></div></div>
 <label class="chip" title="fleet powered 24/7: idle energy counts on all hours">
  <input id="cfg_always_on" type="checkbox"> Always on 24/7</label><span class="saved" id="cfgsaved_always_on"></span>
 <label class="chip" id="deprchip" title="uncheck if the Spark was bought privately: capex not depreciated, local cost = energy only">
  <input id="depr" type="checkbox" checked> Depreciate</label>
 <div class="cparam"><span class="lbl">Fallback tok/s (idle server)</span> <div class="field"><input id="cfg_assumed_tok_s" type="number" step="1" min="1" max="100000"><span class="saved" id="cfgsaved_assumed_tok_s"></span></div></div>
 <div class="cparam"><span class="lbl">In:Out token ratio</span> <div class="field"><input id="cfg_in_out_ratio" type="number" step="1" min="1" max="1000"><span class="saved" id="cfgsaved_in_out_ratio"></span></div></div>
 <div class="cparam"><span class="lbl">Cache hit rate (0-1)</span> <div class="field"><input id="cfg_cache_hit_rate" type="number" step="0.01" min="0" max="1"><span class="saved" id="cfgsaved_cache_hit_rate"></span></div></div>
 <div class="cparam"><span class="lbl">Cluster users</span> <div class="field"><input id="users" type="number" step="1" min="1" max="50" placeholder="2"><span class="saved" id="userssaved"></span></div></div>
 <span class="sech">Models</span>
 <div class="cparam"><span class="lbl">Cloud model</span>
 <select id="cloudsel"></select></div>
 <div class="cparam"><span class="lbl">Local model</span>
 <select id="locsel"><option value="">Auto-detect&hellip;</option></select></div>
 <span id="locwarn"></span>
 <button id="resetBtn" title="Restore online price list">&#8634; Reset prices</button>
 <button id="refreshBtn">&#8635; Refresh prices</button>
 <details class="fleetbox"><summary>&#9881; Cluster machines (per-host power)</summary>
  <div class="fleethint">name + mode local/ssh + ip/port/user &middot; password stored server-side (0600, never shown) &mdash; empty = keep stored &middot; Save syncs n_sparks</div>
  <div id="fleetRows"></div>
  <div class="fbtns"><button id="fleetAdd" type="button">+ add</button><button id="fleetSave" type="button">Save</button><span id="fleetMsg"></span></div>
 </details>
  </div>
 </div>
 <div id="view-stats" class="view" hidden>
  <h2>Power statistics &mdash; fleet</h2>
  <div class="sub" id="statssub"></div>
  <div class="winrow"><span class="lbl">Window:</span>
   <button class="winbtn active" data-w="0" type="button">all</button>
   <button class="winbtn" data-w="86400" type="button">24 h</button>
   <button class="winbtn" data-w="604800" type="button">7 d</button></div>
  <div class="cards" id="statcards"></div>
  <table><thead><tr><th>mode</th><th class="num">samples</th><th class="num">mean W (host)</th><th class="num">peak W (host)</th></tr></thead>
  <tbody id="statrows"></tbody></table>
  <div class="sub">inference = sample with the monitored server reporting requests_running &gt; 0 &middot; idle = requests_running == 0 &middot; samples with the server unreachable are excluded from the split but kept in the overall mean/peak &middot; unknown = samples predating the P49 flag &middot; energy estimated at the sampler cadence &middot; peak W is the max summed fleet power in one sample</div>
 </div>
</div>
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
   <stop offset="0" stop-color="${color}" stop-opacity="0.55"/>
   <stop offset="1" stop-color="${color}" stop-opacity="0.04"/>
  </linearGradient>
  <filter id="f${gid}" x="-20%" y="-60%" width="140%" height="220%"><feGaussianBlur stdDeviation="2.2"/></filter></defs>
  <path d="${area}" fill="${color}" opacity="0.22" filter="url(#f${gid})"/>
  <path d="${area}" fill="url(#${gid})"/>
  <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" opacity="0.95"
   style="filter:drop-shadow(0 0 3px ${color})"/>
  <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="2.2" fill="${color}"
   style="filter:drop-shadow(0 0 3px ${color})"/></svg>`;
}

const themeBtn=document.getElementById('themeBtn');
function showView(v){
 document.querySelectorAll('.navbtn').forEach(x=>x.classList.toggle('active',x.dataset.view===v));
 ['dash','config','stats'].forEach(k=>{const el=document.getElementById('view-'+k); if(el)el.hidden=k!==v;});
 try{localStorage.setItem('sc-view',v)}catch(e){}
 if(v==='stats')loadStats();
}
(()=>{const p=new URLSearchParams(location.search).get('view');
 let v=(p&&['dash','config','stats'].includes(p))?p:(((()=>{try{return localStorage.getItem('sc-view')}catch(e){return null}})())||'dash');
 document.addEventListener('DOMContentLoaded',()=>showView(v));})();
document.querySelectorAll('.navbtn').forEach(b=>b.onclick=()=>showView(b.dataset.view));
let statsWin=0;
async function loadStats(){
 const d=await(await fetch('/api/stats?window='+statsWin)).json();
 if(d.error){document.getElementById('statssub').textContent='error: '+d.error;return;}
 if(!d){document.getElementById('statssub').textContent='no power samples yet';return;}
 const f=n=>n==null?'\u2014':(+n).toFixed(1);
 const ek=n=>n==null?'\u2014':(+n).toFixed(2)+' kWh';
 const span=d.window_s?`${Math.round(d.window_s/60)} min window`:'';
 document.getElementById('statssub').textContent=`${d.samples} host samples over ${span} \u00b7 cadence 30 s`;
 const cards=[['fleet mean power',f(d.fleet_mean_w)+' W',null,null],
  ['fleet peak power',f(d.fleet_peak_w)+' W',null,null],
  ['peak single host',f(d.peak_sample_w)+' W',null,null],
  ['energy (window)',ek(d.energy_kwh_est),null,null]];
 document.getElementById('statcards').innerHTML=cards.map(c=>`<div class="card"><div class="l">${c[0]}</div><div class="v">${c[1]}</div></div>`).join('');
 const row=(lbl,m)=>`<tr><td>${lbl}</td><td class="num">${m.samples}</td><td class="num">${m.mean_host_w==null?'\u2014':f(m.mean_host_w)+' W'}</td><td class="num">${m.peak_host_w==null?'\u2014':f(m.peak_host_w)+' W'}</td></tr>`;
 document.getElementById('statrows').innerHTML=
  row('\u26a1 inference (running &gt; 0)',d.inference||{samples:0})+
  row('💤 idle (running = 0)',d.idle||{samples:0})+
  (d.unknown&&d.unknown.samples?row('? unknown (no flag)',d.unknown):'');
}
document.getElementById('view-stats').addEventListener('click',async e=>{
 if(!e.target.classList.contains('winbtn'))return;
 document.querySelectorAll('.winbtn').forEach(x=>x.classList.toggle('active',x===e.target));
 statsWin=+e.target.dataset.w; await loadStats();
});

function applyTheme(t){document.body.classList.toggle('light',t==='light');themeBtn.textContent=t==='light'?'🌙':'\u2600\uFE0F';
 const li=document.getElementById('logoImg'); if(li)li.src=t==='light'?'/logo-light.jpg':'/logo.jpg';
 try{localStorage.setItem('sc-theme',t)}catch(e){}}
applyTheme((()=>{const p=new URLSearchParams(location.search).get('theme');
 if(p==='light'||p==='dark')return p;
 try{return localStorage.getItem('sc-theme')||'dark'}catch(e){return 'dark'}})());
themeBtn.onclick=()=>applyTheme(document.body.classList.contains('light')?'dark':'light');

let fleetCache=[],fleetLoaded=false;
const escF=v=>String(v??'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
function renderFleet(){
 const box=document.getElementById('fleetRows');
 box.innerHTML=fleetCache.map((h,i)=>`<div class="frow" data-i="${i}">
  <input class="fname" placeholder="name" value="${escF(h.name)}">
  <select class="fmode"><option value="local"${h.mode==='local'?' selected':''}>local</option><option value="ssh"${h.mode!=='local'?' selected':''}>ssh</option></select>
  <input class="fport" placeholder="22" value="${escF(h.port||22)}">
  <input class="fip" placeholder="ip" value="${escF(h.ip)}" style="grid-column:span 3">
  <input class="fuser" placeholder="user" value="${escF(h.user)}">
  <input class="fpass" type="password" placeholder="${h.has_password?'(stored)':'password'}" style="grid-column:span 3">
  <button class="ftest" type="button">Test</button><button class="fdel" type="button">\u2715</button>
  <span class="fres"></span></div>`).join('')||'<div class="fres">no machines yet \u2014 add one</div>';
}
function collectRow(row){return{name:row.querySelector('.fname').value.trim(),mode:row.querySelector('.fmode').value,ip:row.querySelector('.fip').value.trim(),port:parseInt(row.querySelector('.fport').value)||22,user:row.querySelector('.fuser').value.trim(),password:row.querySelector('.fpass').value};}
function collectRows(){return[...document.querySelectorAll('#fleetRows .frow')].map(collectRow);}
document.getElementById('fleetAdd').onclick=()=>{fleetCache.push({mode:'ssh',port:22});renderFleet();};
document.getElementById('fleetSave').onclick=async()=>{
 const r=await(await fetch('/api/fleet',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hosts:collectRows()})})).json();
 const el=document.getElementById('fleetMsg');
 el.textContent=r.ok?'saved \u2713 \u2014 n_sparks synced':'error: '+(r.error||'?');
 setTimeout(()=>el.textContent='',5000); if(r.ok){fleetLoaded=false;tick(true);} };
document.getElementById('fleetRows').addEventListener('click',async e=>{
 const row=e.target.closest('.frow'); if(!row)return;
 if(e.target.classList.contains('fdel')){fleetCache.splice(+row.dataset.i,1);renderFleet();return;}
 if(!e.target.classList.contains('ftest'))return;
 const res=row.querySelector('.fres'); res.textContent='testing\u2026';
 const r=await(await fetch('/api/fleet/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({host:collectRow(row)})})).json();
 res.textContent=r.ok?('\u2713 '+(+r.watts).toFixed(1)+' W'):('\u2715 '+(r.error||'fail'));
});

const CFG_NUM={n_sparks:[1,64,'int'],usd_eur:[0,10,'float'],idle_watts:[1,2000,'float'],assumed_tok_s:[1,100000,'int'],in_out_ratio:[1,1000,'int'],cache_hit_rate:[0,1,'float']};
for(const [k,[mn,mx,ty]] of Object.entries(CFG_NUM)){
 const el=document.getElementById('cfg_'+k); if(!el)continue;
 el.addEventListener('change',async()=>{
  let v=parseFloat(el.value);
  const out=document.getElementById('cfgsaved_'+k);
  if(isNaN(v)||v<mn||v>mx){if(out){out.textContent=mn+'-'+mx;setTimeout(()=>out.textContent='',2500);}return;}
  if(ty==='int')v=Math.round(v);
  const body={};body[k]=v;
  const r=await(await fetch('/api/cfg',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  if(r.ok){if(out)out.textContent='saved \u2713';await tick(true);} else if(out)out.textContent=r.error||'error';
  if(out)setTimeout(()=>out.textContent='',2500);
 });
}
const aoEl=document.getElementById('cfg_always_on');
if(aoEl)aoEl.addEventListener('change',async e=>{
 const r=await(await fetch('/api/cfg',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({always_on:e.target.checked})})).json();
 const out=document.getElementById('cfgsaved_always_on');
 if(out){out.textContent=r.ok?'saved \u2713':(r.error||'error');setTimeout(()=>out.textContent='',2500);}
 if(r.ok)await tick(true);
});

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
 if(d.fleet&&!fleetLoaded){fleetCache=d.fleet;fleetLoaded=true;renderFleet();}
 localLabel=lm.label||null;
 document.getElementById('sub').textContent=
  `${d.server.backend||'?'} :${d.server.port||'?'} · ${d.server.model||'?'} · local model: ${lm.label||'?'}${lm.detected?' (auto-detected)':''}`+
  (d.snapshot_age_h!=null?` · price list ${d.snapshot_age_h<1?Math.round(d.snapshot_age_h*60)+' min':d.snapshot_age_h.toFixed(0)+' h'} old`:'')+
  (()=>{const es=d.energy_source||{};
   if(es.mode==='integrated'){let s=` · power ${d.live_power&&d.live_power.fleet_w!=null?(+d.live_power.fleet_w).toFixed(1)+' W live · cost basis ':''}${(+L.watts_fleet).toFixed(1)} W fleet = ${(+L.watts).toFixed(1)} W/unit × ${L.n_sparks} units, time-weighted over ${Math.round(es.span_s/60)} min (${es.samples} samples)`;
    if(es.per_host)s+=' · '+Object.entries(es.per_host).map(([k,v])=>v?`${k} ${(+v.watts).toFixed(1)} W ${v.mode}`:`${k} n/d`).join(' · ');
    return s;}
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
 for(const k of ['n_sparks','usd_eur','idle_watts','assumed_tok_s','in_out_ratio','cache_hit_rate']){const el=document.getElementById('cfg_'+k); if(el&&document.activeElement!==el&&d.cfg[k]!=null)el.value=d.cfg[k];}
 const ao=document.getElementById('cfg_always_on'); if(ao&&document.activeElement!==ao)ao.checked=d.cfg.always_on!==false;

 // P54: numero+sparkline fleet power dalla serie LIVE del sampler (ultimo campione/host,
 // max 180s); fallback alla media 30-min (L.watts_fleet) se il sampler non ha dati freschi.
 // La media 30-min resta la base dei costi (footer: "cost basis").
 const powerNow=(d.live_power&&d.live_power.fleet_w!=null)?+d.live_power.fleet_w:L.watts_fleet;
 pushHist('power',powerNow);pushHist('eff',L.eff_eur_1m);
 // sparkline ONLY on fleet power (P52); gli altri meter sono senza tendenza
 let rpct=null;
 if(d.repaid){const rm=(d.repaid.models||[]).find(m=>m.model===cloudModel);
  if(rm&&rm.cloud_cached_eur!=null&&d.repaid.capex)rpct=Math.max(0,(rm.cloud_cached_eur-d.repaid.local_cost_eur))/d.repaid.capex*100;}
 if(rpct!=null)pushHist('repaid',rpct);
 const cards=[
  ['active units',(cfg.n_sparks||1)+' Spark',null,null],
  ['prompt tokens (total)',fmt(+(d.ledger?d.ledger.prompt_total:d.counters.prompt_total)||0),null,null],
  ['generated tokens (total)',fmt(+(d.ledger?d.ledger.gen_total:d.counters.gen_total)||0),null,null],
  ['fleet power · all units',(powerNow||0).toFixed(1)+' W','power',PALETTE[0]],
  ['local effective (measured)','€'+(+L.eff_eur_1m).toFixed(2)+'/1M',null,PALETTE[5]],
  ['monthly fixed','€'+(+L.fixed_month_eur).toFixed(0),null,null],
  ['tariff',cfg.eur_per_kwh+' €/kWh',null,null],
  ['repaid so far',rpct==null?'\u2014':rpct.toFixed(1)+'%',null,PALETTE[2]]];
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
                # P54: potenza fleet LIVE (ultimo campione sampler per host) per la card Dash
                rep["live_power"] = live_power()
                payload = json.dumps(rep, indent=None, default=str)
                self._send(200, payload.encode(), "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"error": str(e)}).encode(),
                           "application/json")
        elif u.path == "/api/stats":
            # P49: power statistics (mean/peak fleet, inference vs idle events)
            try:
                w = int((q.get("window") or ["0"])[0] or 0)
                self._send(200, json.dumps(fleet_stats(w or None)).encode(),
                           "application/json")
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
        elif u.path == "/logo-light.jpg":
            # P51: logo chiaro per il tema light (testo scuro su fondo chiaro)
            if LOGO_LIGHT.exists():
                self._send(200, LOGO_LIGHT.read_bytes(), "image/jpeg")
            else:
                self._send(404, b"logo not found", "text/plain")
        elif u.path == "/logo.jpg":
            try:
                self._send(200, LOGO.read_bytes(), "image/jpeg")
            except OSError:
                self._send(404, b"logo not found", "text/plain")
        elif u.path == "/":
            self._send(200, HTML.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        """P47: fleet config + live test. JSON body; passwords never in URLs
        and never echoed back."""
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            return self._send(400, b'{"error":"bad json"}', "application/json")
        if u.path == "/api/fleet":
            try:
                hosts = body.get("hosts") or []
                save_fleet(hosts)
                save_n_sparks(len([h for h in hosts if h.get("name")]))
                self._send(200, json.dumps({"ok": True}).encode(), "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"ok": False, "error": str(e)}).encode(),
                           "application/json")
        elif u.path == "/api/fleet/test":
            try:
                self._send(200, json.dumps(test_fleet_host(body.get("host") or {})).encode(),
                           "application/json")
            except Exception as e:  # noqa: BLE001
                self._send(500, json.dumps({"ok": False, "error": str(e)}).encode(),
                           "application/json")
        elif u.path == "/api/cfg":
            try:
                saved = save_cfg_params(body if isinstance(body, dict) else {})
                self._send(200, json.dumps({"ok": True, "saved": saved}).encode(),
                           "application/json")
            except ValueError as e:
                self._send(400, json.dumps({"ok": False, "error": str(e)}).encode(),
                           "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *a) -> None:  # silence request logging
        pass


def main() -> None:
    print(f"sparkcost su http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
