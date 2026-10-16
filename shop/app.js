'use strict';
/* Shop Quoter – plain JS, no build step.
   All business numbers live in data.settings (edited on the Settings screen).
   DEFAULTS below only seeds the first launch. */

const KEY = 'shopapp.v1';
const STATUSES = ['Quoted', 'Deposit', 'Designing', 'Cutting', 'Finishing', 'Shipped', 'Paid'];
const DEPOSIT_IDX = STATUSES.indexOf('Deposit');

/* ---------------- defaults (first launch only) ---------------- */
function defaults() {
  const zeroFees = { txPct: 0, procPct: 0, procFixed: 0, listing: 0 };
  return {
    settings: {
      electricity: 0.135,
      laborRate: 26,
      nonBillablePct: 40,
      wastePct: 10,
      paybackMonths: 24,
      targetMarginPct: 35,
      minProfitPct: 10,
      marketWarnPct: 30,
      dueSoonDays: 3,
      filamentPerKg: 21,
      inks: [
        { id: 'm2', name: 'xTool M2 ink cartridge', price: 100, ml: 40 },
        { id: 'o1', name: 'xTool O1 ink', price: 300, ml: 750 },
      ],
      channels: [
        { id: 'etsy', name: 'Etsy', txPct: 6.5, procPct: 3, procFixed: 0.25, listing: 0.20, verify: true },
        { id: 'fb', name: 'Facebook Marketplace', ...zeroFees },
        { id: 'direct', name: 'Direct', ...zeroFees },
        { id: 'referral', name: 'Referral', ...zeroFees },
      ],
      machines: [
        { id: 'a1-1', name: 'Bambu A1 #1', price: 579, life: 10000, kw: 0.12, consumable: 0, billableHrs: 40, fixedMonthly: 0, inkId: '', note: '', ph: {} },
        { id: 'a1-2', name: 'Bambu A1 #2', price: 579, life: 10000, kw: 0.12, consumable: 0, billableHrs: 40, fixedMonthly: 0, inkId: '', note: '', ph: {} },
        { id: 'm2', name: 'xTool M2 (laser + CMYK inkjet)', price: 1300, life: 8000, kw: 0.10, consumable: 0, billableHrs: 20, fixedMonthly: 0, inkId: 'm2', note: 'Ink is charged per ml on the quote.', ph: {} },
        { id: 'co2', name: 'Omtech 60W CO2', price: 4000, life: 10000, kw: 0.70, consumable: 0.15, billableHrs: 20, fixedMonthly: 0, inkId: '', note: 'Tube $300 / 2,000 hrs = $0.15/hr.', ph: {} },
        { id: 'o1', name: 'xTool O1 (UV printer)', price: 3900, life: 8000, kw: 0.15, consumable: 0, billableHrs: 20, fixedMonthly: 33.25, inkId: 'o1',
          note: 'Printhead $399/yr = $33.25/month FIXED (added to recovery). Life and kW are placeholders.', ph: { life: true, kw: true } },
      ],
    },
    jobs: [],
    products: [
      { id: 'p-test', name: 'TEST – sample 3D-printed item', machineId: 'a1-1', machineMin: 60, materialCost: 0, grams: 25, inkMl: 0,
        laborMin: 15, shipping: 0, channelId: 'etsy', pastPrice: 12 },
    ],
    quote: blankQuote(),
  };
}
function blankQuote() {
  return { itemName: '', qty: 1, machineId: '', machineMin: '', materialCost: '', grams: '', inkMl: '',
    laborMin: '', shipping: '', channelId: '', marketPrice: '', salePrice: '' };
}

/* ---------------- tiny helpers ---------------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const num = v => { const n = parseFloat(v); return isFinite(n) ? n : 0; };
const div = (a, b) => (b ? a / b : 0);
const money = n => (n < 0 ? '-$' : '$') + Math.abs(n).toFixed(2);
const pctStr = n => (n * 100).toFixed(1) + '%';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ymd = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const todayStr = () => ymd(new Date());
const clone = o => JSON.parse(JSON.stringify(o));
function daysUntil(str) {
  if (!str) return null;
  const [y, m, d] = str.split('-').map(Number);
  const t = new Date(y, m - 1, d), n = new Date();
  return Math.round((t - new Date(n.getFullYear(), n.getMonth(), n.getDate())) / 864e5);
}

/* ---------------- storage ---------------- */
let data;
let storageOK = true;
function load() {
  const d = defaults();
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return normalize(JSON.parse(raw));
  } catch (e) { storageOK = false; }
  return d;
}
function normalize(p) {
  const d = defaults();
  const out = Object.assign(d, p);
  out.settings = Object.assign(d.settings, p.settings || {});
  out.quote = Object.assign(blankQuote(), p.quote || {});
  ['jobs', 'products'].forEach(k => { if (!Array.isArray(out[k])) out[k] = []; });
  out.settings.machines.forEach(m => { m.ph = m.ph || {}; });
  return out;
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) { storageOK = false; toast('Could not save – storage blocked!', true); }
}

/* ---------------- calculations ---------------- */
function machineRates(m, s) {
  const wear = div(num(m.price), num(m.life)) + num(m.kw) * num(s.electricity) + num(m.consumable);
  const recovery = div(div(num(m.price), num(s.paybackMonths)) + num(m.fixedMonthly), num(m.billableHrs));
  return { wear, recovery };
}
function monthlyTarget(s) {
  return s.machines.reduce((t, m) => t + div(num(m.price), num(s.paybackMonths)) + num(m.fixedMonthly), 0);
}
const effLabor = s => num(s.laborRate) * (1 + num(s.nonBillablePct) / 100);
const inkRate = ink => (ink ? div(num(ink.price), num(ink.ml)) : 0);

function calcQuote(q, s) {
  const m = s.machines.find(x => x.id === q.machineId);
  const ch = s.channels.find(x => x.id === q.channelId) || { txPct: 0, procPct: 0, procFixed: 0, listing: 0, name: '(no channel)' };
  const ink = m && s.inks.find(i => i.id === m.inkId);
  const qty = Math.max(1, num(q.qty));
  const rates = m ? machineRates(m, s) : { wear: 0, recovery: 0 };
  const buffer = 1 + num(s.wastePct) / 100;
  const other = num(q.materialCost);
  const filament = num(q.grams) * num(s.filamentPerKg) / 1000;
  const inkCost = num(q.inkMl) * inkRate(ink);
  const hrs = num(q.machineMin) / 60;
  const parts = {
    other, filament, ink: inkCost,
    materials: (other + filament + inkCost) * buffer,
    wear: hrs * rates.wear,
    recovery: hrs * rates.recovery,
    labor: num(q.laborMin) / 60 * effLabor(s),
    ship: num(q.shipping) / qty,
  };
  const base = parts.materials + parts.wear + parts.recovery + parts.labor + parts.ship;
  const fixedFee = (num(ch.procFixed) + num(ch.listing)) / qty;     // per-order fees spread over qty
  const feePct = (num(ch.txPct) + num(ch.procPct)) / 100;
  const priceFor = margin => { const d = 1 - feePct - margin / 100; return d > 0 ? (base + fixedFee) / d : NaN; };
  const floor = priceFor(num(s.minProfitPct));
  const target = priceFor(num(s.targetMarginPct));
  const profitAt = p => p - base - fixedFee - feePct * p;
  return { qty, m, ch, ink, parts, base, fixedFee, feePct, floor, target, profitAt,
    marginAt: p => (p > 0 ? profitAt(p) / p : 0), feesAt: p => fixedFee + feePct * p };
}

/* ---------------- field builder (color-coded) ---------------- */
let editJob = null, editJobOrig = null, editProd = null, editProdOrig = null;
const rootOf = name => ({ settings: data.settings, quote: data.quote, job: editJob, prod: editProd })[name];
function resolve(bind) {
  const p = bind.split('.');
  let o = rootOf(p[0]);
  for (let i = 1; i < p.length - 1; i++) o = o[p[i]];
  return [o, p[p.length - 1], p];
}
/* kind: money (green) | time (blue) | amount (orange) | pct (purple) | text (gray) */
function fld(label, bind, kind, o = {}) {
  const [obj, key] = resolve(bind);
  const v = obj[key];
  let input;
  if (o.opts) {
    input = `<select data-bind="${bind}">${o.opts.map(([val, lab]) =>
      `<option value="${esc(val)}"${String(val) === String(v) ? ' selected' : ''}>${esc(lab)}</option>`).join('')}</select>`;
  } else if (o.area) {
    input = `<textarea data-bind="${bind}" rows="3">${esc(v)}</textarea>`;
  } else {
    const t = o.type || (['money', 'time', 'amount', 'pct'].includes(kind) ? 'number' : 'text');
    const extra = t === 'number' ? ` step="any"${o.neg ? '' : ' min="0" inputmode="decimal"'}` : '';
    input = `<input type="${t}" data-bind="${bind}" value="${esc(v)}"${extra}>`;
  }
  return `<label class="fld f-${kind}${o.placeholder ? ' ph' : ''}"><span class="lab">${label}${o.placeholder ? '<b class="phbadge">PLACEHOLDER – replace</b>' : ''}</span>${input}${o.hint ? `<small>${o.hint}</small>` : ''}</label>`;
}
const legendHTML = '<span style="background:var(--green)">$ money</span><span style="background:var(--blue)">time</span>' +
  '<span style="background:var(--orange)">amounts</span><span style="background:var(--purple)">percent</span><span style="background:var(--gray)">text / choice</span>';
const machineOpts = () => data.settings.machines.map(m => [m.id, m.name]);
const channelOpts = () => data.settings.channels.map(c => [c.id, c.name]);

/* ---------------- input hooks ---------------- */
document.addEventListener('input', e => {
  const el = e.target, b = el.dataset && el.dataset.bind;
  if (!b) return;
  const [o, k, p] = resolve(b);
  o[k] = el.type === 'number' ? (el.value === '' ? '' : num(el.value)) : el.value;
  if (p[0] === 'settings') {
    if (p[1] === 'machines' && o.ph && o.ph[k]) { delete o.ph[k]; el.closest('.fld').classList.remove('ph'); el.closest('.fld').querySelector('.phbadge')?.remove(); }
    save(); updateDerived();
  } else if (p[0] === 'quote') { save(); renderQuoteOut(); }
});

/* ---------------- dashboard ---------------- */
function monthProfit() {
  const pre = todayStr().slice(0, 7);
  return data.jobs.filter(j => (j.date || '').startsWith(pre)).reduce((t, j) => t + num(j.profit), 0);
}
function dashHTML() {
  const target = monthlyTarget(data.settings), got = monthProfit();
  const pct = target > 0 ? got / target : 0;
  return `<div class="dash"><div class="top"><span>Profit logged this month</span><b>${money(got)}</b></div>
    <div class="top"><span>Equipment recovery target</span><b>${money(target)}</b></div>
    <div class="bar"><i class="${pct >= 1 ? 'done' : ''}" style="width:${Math.max(0, Math.min(100, pct * 100))}%"></i></div>
    <small>${(pct * 100).toFixed(0)}% of target${got >= target ? ' – target hit 🎉' : ' – ' + money(target - got) + ' to go'}</small></div>`;
}

/* ---------------- SETTINGS screen ---------------- */
function buildSettings() {
  const s = data.settings;
  const ink = s.inks.map((k, i) => `
    <div class="row2">
      ${fld(esc(k.name) + ' – price ($)', `settings.inks.${i}.price`, 'money')}
      ${fld('ml in it', `settings.inks.${i}.ml`, 'amount')}
    </div><div class="calc">Ink cost: <b id="ink-${i}"></b> per ml</div>`).join('');
  const ch = s.channels.map((c, i) => `
    <h3 style="margin:6px 0">${fld('Channel name', `settings.channels.${i}.name`, 'text')}</h3>
    <div class="row2">
      ${fld('Transaction fee (%)', `settings.channels.${i}.txPct`, 'pct')}
      ${fld('Payment fee (%)', `settings.channels.${i}.procPct`, 'pct')}
    </div><div class="row2">
      ${fld('Payment fee per order ($)', `settings.channels.${i}.procFixed`, 'money')}
      ${fld('Listing fee per order ($)', `settings.channels.${i}.listing`, 'money')}
    </div>${c.verify ? '<p><span class="verify">verify current rates</span></p>' : ''}`).join('<hr>');
  const mach = s.machines.map((m, i) => `
    <div class="card">
      ${fld('Machine name', `settings.machines.${i}.name`, 'text')}
      <div class="row2">
        ${fld('Purchase price ($)', `settings.machines.${i}.price`, 'money')}
        ${fld('Expected life (hrs)', `settings.machines.${i}.life`, 'amount', { placeholder: m.ph.life })}
      </div><div class="row2">
        ${fld('Avg power (kW)', `settings.machines.${i}.kw`, 'amount', { placeholder: m.ph.kw })}
        ${fld('Consumable ($/hr)', `settings.machines.${i}.consumable`, 'money')}
      </div><div class="row2">
        ${fld('Billable hrs / month', `settings.machines.${i}.billableHrs`, 'time')}
        ${fld('Fixed monthly cost ($)', `settings.machines.${i}.fixedMonthly`, 'money')}
      </div>
      ${fld('Ink this machine uses', `settings.machines.${i}.inkId`, 'text', { opts: [['', 'None'], ...s.inks.map(k => [k.id, k.name])] })}
      ${fld('Notes', `settings.machines.${i}.note`, 'text')}
      <div class="calc">Wear rate: <b id="wear-${i}"></b>/hr<br>Recovery rate: <b id="rec-${i}"></b>/hr</div>
      <button class="btn danger small" data-act="delMachine" data-i="${i}">Delete this machine</button>
    </div>`).join('');
  $('#settingsForm').innerHTML = `
    <section class="card"><h2>General</h2>
      ${fld('Electricity ($ per kWh)', 'settings.electricity', 'money')}
      ${fld('Labor rate ($ per hour)', 'settings.laborRate', 'money', { hint: 'Charged on ATTENDED minutes only (design, setup, finishing, packing).' })}
      ${fld('Non-billable time load (%)', 'settings.nonBillablePct', 'pct', { hint: 'Added to labor for content, quoting, admin.' })}
      <div class="calc">Effective labor: <b id="effLabor"></b> per hour</div>
      ${fld('Material waste / failure buffer (%)', 'settings.wastePct', 'pct')}
      ${fld('Payback window (months)', 'settings.paybackMonths', 'time')}
      ${fld('Target profit margin (%)', 'settings.targetMarginPct', 'pct')}
      ${fld('Minimum profit at floor (%)', 'settings.minProfitPct', 'pct')}
      ${fld('Warn if target is above market by (%)', 'settings.marketWarnPct', 'pct')}
      ${fld('Job “due soon” warning (days)', 'settings.dueSoonDays', 'time')}
    </section>
    <section class="card"><h2>Fees <span class="verify">verify current rates</span></h2>${ch}</section>
    <section class="card"><h2>Materials</h2>
      ${fld('PLA / PETG filament ($ per kg)', 'settings.filamentPerKg', 'money')}
      <div class="calc">Filament cost: <b id="perG"></b> per gram</div>
      ${ink}
      <small>Sheet materials (wood, acrylic…) are entered per job on the Quote screen.</small>
    </section>
    <h2>Machines</h2>${mach}
    <button class="btn" data-act="addMachine">+ Add machine</button>
    <section class="card"><h2>Backup</h2>
      <button class="btn good" data-act="export">Export backup (JSON)</button>
      <button class="btn" data-act="import">Import backup (JSON)</button>
      <small>Importing replaces everything on this phone.${storageOK ? '' : ' <b>Storage is blocked – export often!</b>'}</small>
    </section>`;
  updateDerived();
}
function updateDerived() {
  const s = data.settings;
  const set = (id, t) => { const e = document.getElementById(id); if (e) e.textContent = t; };
  set('effLabor', money(effLabor(s)));
  set('perG', '$' + (num(s.filamentPerKg) / 1000).toFixed(4));
  s.inks.forEach((k, i) => set('ink-' + i, '$' + inkRate(k).toFixed(3)));
  s.machines.forEach((m, i) => { const r = machineRates(m, s); set('wear-' + i, '$' + r.wear.toFixed(3)); set('rec-' + i, '$' + r.recovery.toFixed(3)); });
  $$('.dashbox').forEach(e => { e.innerHTML = dashHTML(); });
}

/* ---------------- QUOTE screen ---------------- */
function costFields(root) {
  return `
    ${fld('Machine', root + '.machineId', 'text', { opts: machineOpts() })}
    ${fld('Sales channel', root + '.channelId', 'text', { opts: channelOpts() })}
    <div class="row2">
      ${fld('Machine min / unit', root + '.machineMin', 'time')}
      ${fld('ATTENDED labor min / unit', root + '.laborMin', 'time')}
    </div><div class="row2">
      ${fld('Other material $ / unit', root + '.materialCost', 'money', { hint: 'Sheet wood, acrylic, etc.' })}
      ${fld('Filament (grams / unit)', root + '.grams', 'amount')}
    </div><div class="row2">
      ${fld('Ink used (ml / unit)', root + '.inkMl', 'amount')}
      ${fld('Shipping / packaging $ (whole order)', root + '.shipping', 'money')}
    </div>`;
}
function fixRefs(o) {
  const s = data.settings;
  if (!s.machines.some(m => m.id === o.machineId)) o.machineId = s.machines[0]?.id || '';
  if (!s.channels.some(c => c.id === o.channelId)) o.channelId = s.channels[0]?.id || '';
}
function buildQuote() {
  fixRefs(data.quote);
  $('#quoteForm').innerHTML = `<div class="card">
    ${fld('Item name', 'quote.itemName', 'text')}
    ${fld('Quantity', 'quote.qty', 'amount')}
    ${costFields('quote')}
    <div class="row2">
      ${fld('Market price $ / unit', 'quote.marketPrice', 'money', { hint: 'What similar items sell for.' })}
      ${fld('Your sale price $ / unit', 'quote.salePrice', 'money', { hint: 'Optional – checks it against the floor.' })}
    </div>
    <button class="btn small danger" data-act="clearQuote">Clear form</button></div>`;
  renderQuoteOut();
}
function renderQuoteOut() {
  const q = data.quote, s = data.settings, r = calcQuote(q, s), p = r.parts, qty = r.qty;
  const bad = isNaN(r.floor) || isNaN(r.target);
  const sale = num(q.salePrice), market = num(q.marketPrice);
  let h = '';
  const feesT = bad ? 0 : r.feesAt(r.target);
  h += `<div class="card"><h2>Cost per unit</h2><table class="tbl">
    <tr><td>Materials + ${num(s.wastePct)}% buffer<small>other ${money(p.other)} · filament ${money(p.filament)} · ink ${money(p.ink)}</small></td><td>${money(p.materials)}</td></tr>
    <tr><td>Machine wear</td><td>${money(p.wear)}</td></tr>
    <tr><td>Machine recovery</td><td>${money(p.recovery)}</td></tr>
    <tr><td>Labor (attended, incl. ${num(s.nonBillablePct)}% load)</td><td>${money(p.labor)}</td></tr>
    <tr><td>Shipping / packaging per unit</td><td>${money(p.ship)}</td></tr>
    <tr><td>Fees – ${esc(r.ch.name)} (at target price)</td><td>${money(feesT)}</td></tr>
    <tr class="sum"><td>Cost per unit</td><td>${money(r.base + feesT)}</td></tr></table></div>`;
  if (bad) {
    h += `<div class="flag red">Fees + margin add up to 100% or more, so no price can work. Lower a margin or fee in Settings.</div>`;
  } else {
    h += `<div class="price floor"><div class="plabel">FLOOR PRICE – never go below</div>
      <div class="pval">${money(r.floor)} <small>per unit</small></div>
      <div>Total for ${qty}: <b>${money(r.floor * qty)}</b> · profit ${money(r.profitAt(r.floor) * qty)} (${num(s.minProfitPct)}%)</div></div>
      <div class="price target"><div class="plabel">TARGET PRICE</div>
      <div class="pval">${money(r.target)} <small>per unit</small></div>
      <div>Total for ${qty}: <b>${money(r.target * qty)}</b> · profit ${money(r.profitAt(r.target) * qty)} (${num(s.targetMarginPct)}%)</div></div>`;
    if (sale > 0) {
      if (sale < r.floor - 0.005) {
        h += `<div class="flag red">🚩 BELOW FLOOR: ${money(sale)} is ${money(r.floor - sale)} under the floor of ${money(r.floor)}. Don't take it.<br>
          Profit at this price: ${money(r.profitAt(sale))}/unit (${pctStr(r.marginAt(sale))}). Order total ${money(sale * qty)}.</div>`;
      } else {
        h += `<div class="flag ok">Your price ${money(sale)}/unit is at or above the floor. Profit ${money(r.profitAt(sale))}/unit (${pctStr(r.marginAt(sale))}). Order total ${money(sale * qty)}.</div>`;
      }
    }
    if (market > 0) {
      const over = r.target / market - 1;
      if (over > num(s.marketWarnPct) / 100) {
        h += `<div class="flag warn">⚠️ Target is ${(over * 100).toFixed(0)}% above market (${money(market)}). If you match market your margin is <b>${pctStr(r.marginAt(market))}</b> (${money(r.profitAt(market))}/unit)${market < r.floor ? ' – that is BELOW your floor' : ''}.</div>`;
      } else {
        h += `<div class="flag info">Target vs market (${money(market)}): ${over >= 0 ? '+' : ''}${(over * 100).toFixed(0)}%. Margin at market: ${pctStr(r.marginAt(market))}.</div>`;
      }
    }
  }
  h += `<div class="rules"><b>Discount rules:</b> discounts only for a bigger quantity or a longer deadline – and never below the floor price.</div>
    <button class="btn primary big" data-act="saveAsJob">Save as job</button>`;
  $('#quoteOut').innerHTML = h;
}
function saveAsJob() {
  const q = data.quote, s = data.settings, r = calcQuote(q, s);
  if (!String(q.itemName).trim()) return toast('Enter an item name first', true);
  if (isNaN(r.target)) return toast('Fix the fee/margin settings first', true);
  const unit = num(q.salePrice) > 0 ? num(q.salePrice) : r.target;
  const mats = [num(q.materialCost) > 0 && `other ${money(num(q.materialCost))}/unit`, num(q.grams) > 0 && `${num(q.grams)} g filament`,
    num(q.inkMl) > 0 && `${num(q.inkMl)} ml ink`].filter(Boolean).join(', ');
  const job = { id: nextJobId(), date: todayStr(), customer: '', item: q.itemName.trim(), qty: r.qty,
    quoted: Math.round(unit * r.qty * 100) / 100, deposit: 'N', due: '', status: 'Quoted',
    machine: r.m ? r.m.name : '', materials: mats, channel: r.ch.name, profit: '', notes: '' };
  data.jobs.push(job); save();
  show('jobs'); openJob(job);
  toast('Job created – add customer and due date');
}

/* ---------------- JOBS ---------------- */
function nextJobId() {
  const max = data.jobs.reduce((m, j) => { const x = /^J-(\d+)$/.exec(j.id); return x ? Math.max(m, +x[1]) : m; }, 0);
  return 'J-' + String(max + 1).padStart(3, '0');
}
function dueInfo(j) {
  const d = daysUntil(j.due);
  if (d === null || j.status === 'Paid') return { cls: '', label: j.due ? 'Due ' + j.due : 'No due date' };
  if (d < 0) return { cls: 'overdue', label: `OVERDUE ${-d} day${d === -1 ? '' : 's'} (${j.due})` };
  if (d === 0) return { cls: 'soon', label: 'Due TODAY' };
  if (d <= num(data.settings.dueSoonDays)) return { cls: 'soon', label: `Due in ${d} day${d === 1 ? '' : 's'} (${j.due})` };
  return { cls: '', label: `Due ${j.due} (in ${d} days)` };
}
const byDue = (a, b) => (a.due || '9999').localeCompare(b.due || '9999') || a.id.localeCompare(b.id);
function jobCard(j, withAdvance) {
  const di = dueInfo(j);
  let adv = '';
  if (withAdvance) {
    const idx = STATUSES.indexOf(j.status), next = STATUSES[idx + 1];
    if (next) {
      const blocked = idx + 1 > DEPOSIT_IDX && j.deposit !== 'Y';
      adv = blocked
        ? `<button class="btn danger adv" data-act="advance" data-id="${esc(j.id)}">Deposit received? (tap = yes)</button>`
        : `<button class="btn good adv" data-act="advance" data-id="${esc(j.id)}">→ ${next}</button>`;
    }
  }
  return `<div class="job ${di.cls}"><div class="main" data-act="editJob" data-id="${esc(j.id)}">
    <div class="title">${esc(j.item || '(no item)')} ×${num(j.qty)}</div>
    <div class="meta">${esc(j.id)} · ${esc(j.customer || 'no customer')} · ${esc(j.channel)}</div>
    <div><span class="pill ${j.status === 'Paid' ? 'paid' : ''}">${j.status}</span>${money(num(j.quoted))}${j.deposit === 'Y' ? ' · deposit ✓' : ' · no deposit'}${j.profit !== '' && j.profit != null ? ' · profit ' + money(num(j.profit)) : ''}</div>
    <div class="due">${di.label}</div></div>${adv}</div>`;
}
function renderWeek() {
  const list = data.jobs.filter(j => j.status !== 'Paid').sort(byDue);
  $('#weekList').innerHTML = list.length ? list.map(j => jobCard(j, true)).join('')
    : '<div class="empty">Nothing open. Add a job on the Jobs or Quote screen.</div>';
}
function renderJobs() {
  const pre = todayStr().slice(0, 7);
  const by = {};
  data.jobs.filter(j => (j.date || '').startsWith(pre)).forEach(j => { by[j.channel || '(none)'] = (by[j.channel || '(none)'] || 0) + num(j.profit); });
  const rows = Object.keys(by).map(k => `<tr><td>${esc(k)}</td><td>${money(by[k])}</td></tr>`).join('');
  const tot = Object.values(by).reduce((a, b) => a + b, 0);
  $('#jobsSummary').innerHTML = `<div class="card"><h2>Profit by channel – ${pre}</h2>
    ${rows ? `<table class="tbl">${rows}<tr class="sum"><td>Total</td><td>${money(tot)}</td></tr></table>` : '<small>No profit logged this month yet.</small>'}</div>`;
  const open = data.jobs.filter(j => j.status !== 'Paid').sort(byDue);
  const paid = data.jobs.filter(j => j.status === 'Paid').sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  $('#jobsList').innerHTML = [...open, ...paid].map(j => jobCard(j, false)).join('') || '<div class="empty">No jobs yet.</div>';
}
function advance(id) {
  const j = data.jobs.find(x => x.id === id);
  if (!j) return;
  const idx = STATUSES.indexOf(j.status), next = STATUSES[idx + 1];
  if (!next) return;
  if (idx + 1 > DEPOSIT_IDX && j.deposit !== 'Y') {
    j.deposit = 'Y'; save(); renderWeek(); return toast('Deposit marked received – tap again to move on');
  }
  j.status = next; save(); renderWeek(); updateDerived();
  toast(`${j.item}: ${next}`);
}
function openJob(j) {
  editJobOrig = j || null;
  editJob = j ? clone(j) : { id: nextJobId(), date: todayStr(), customer: '', item: '', qty: 1, quoted: '', deposit: 'N', due: '',
    status: 'Quoted', machine: data.settings.machines[0]?.name || '', materials: '', channel: data.settings.channels[0]?.name || '', profit: '', notes: '' };
  const withCur = (list, cur) => (cur && !list.includes(cur) ? [...list, cur] : list).map(x => [x, x]);
  openSheet(j ? 'Edit job ' + esc(j.id) : 'New job', `
    <div class="row2">${fld('Job ID', 'job.id', 'text')}${fld('Date', 'job.date', 'text', { type: 'date' })}</div>
    ${fld('Customer', 'job.customer', 'text')}
    ${fld('Item', 'job.item', 'text')}
    <div class="row2">${fld('Quantity', 'job.qty', 'amount')}${fld('Quoted price $ (total)', 'job.quoted', 'money')}</div>
    <div class="row2">
      ${fld('Deposit received?', 'job.deposit', 'text', { opts: [['N', 'N – No'], ['Y', 'Y – Yes']] })}
      ${fld('Due date', 'job.due', 'time', { type: 'date' })}
    </div>
    ${fld('Status', 'job.status', 'text', { opts: STATUSES.map(x => [x, x]), hint: 'Can’t go past Deposit until deposit received = Y.' })}
    <div class="row2">
      ${fld('Machine', 'job.machine', 'text', { opts: withCur(data.settings.machines.map(m => m.name), editJob.machine) })}
      ${fld('Channel', 'job.channel', 'text', { opts: withCur(data.settings.channels.map(c => c.name), editJob.channel) })}
    </div>
    ${fld('Materials needed', 'job.materials', 'text')}
    ${fld('Actual profit $', 'job.profit', 'money', { neg: true })}
    ${fld('Notes', 'job.notes', 'text', { area: true })}`,
    `<div class="btnrow"><button class="btn primary" data-act="saveJob">Save</button>
      ${j ? '<button class="btn danger" data-act="delJob">Delete</button>' : '<button class="btn" data-act="closeSheet">Cancel</button>'}</div>`);
}
function saveJob() {
  const j = editJob;
  if (!String(j.id).trim()) return toast('Job ID is needed', true);
  if (data.jobs.some(x => x !== editJobOrig && x.id === j.id)) return toast('That job ID is already used', true);
  if (STATUSES.indexOf(j.status) > DEPOSIT_IDX && j.deposit !== 'Y') return toast('Set deposit received = Y before moving past Deposit', true);
  if (editJobOrig) Object.assign(editJobOrig, j); else data.jobs.push(j);
  save(); closeSheet(); refresh(); toast('Job saved');
}
function delJob() {
  if (!confirm('Delete job ' + editJobOrig.id + '?')) return;
  data.jobs = data.jobs.filter(x => x !== editJobOrig);
  save(); closeSheet(); refresh();
}

/* ---------------- PRODUCTS ---------------- */
function renderProducts() {
  const s = data.settings;
  $('#prodList').innerHTML = data.products.map(p => {
    const r = calcQuote({ ...p, qty: 1 }, s), past = num(p.pastPrice);
    let cmp = '';
    if (past > 0 && !isNaN(r.floor)) {
      cmp = past < r.floor - 0.005
        ? `<div class="flag red">🚩 You charged ${money(past)} – ${money(r.floor - past)} UNDER floor</div>`
        : `<div class="flag ok">You charged ${money(past)} – ${money(past - r.floor)} over floor</div>`;
    }
    return `<div class="card"><h2>${esc(p.name)}</h2>
      <table class="tbl"><tr><td>Floor price</td><td>${money(r.floor)}</td></tr><tr><td>Target price</td><td>${money(r.target)}</td></tr></table>${cmp}
      <div class="btnrow"><button class="btn primary" data-act="quoteProd" data-id="${esc(p.id)}">Quote this</button>
      <button class="btn" data-act="editProd" data-id="${esc(p.id)}">Edit</button></div></div>`;
  }).join('') || '<div class="empty">No products yet.</div>';
}
function openProd(p) {
  editProdOrig = p || null;
  editProd = p ? clone(p) : { id: 'p' + Date.now(), name: '', machineId: '', machineMin: '', materialCost: '', grams: '', inkMl: '',
    laborMin: '', shipping: '', channelId: '', pastPrice: '' };
  fixRefs(editProd);
  openSheet(p ? 'Edit product' : 'New product', `
    ${fld('Product name', 'prod.name', 'text')}
    ${costFields('prod')}
    ${fld('Price you actually charged $ / unit', 'prod.pastPrice', 'money', { hint: 'Compared against the floor price on the list.' })}`,
    `<div class="btnrow"><button class="btn primary" data-act="saveProd">Save</button>
      ${p ? '<button class="btn danger" data-act="delProd">Delete</button>' : '<button class="btn" data-act="closeSheet">Cancel</button>'}</div>`);
}
function saveProd() {
  if (!String(editProd.name).trim()) return toast('Enter a product name', true);
  if (editProdOrig) Object.assign(editProdOrig, editProd); else data.products.push(editProd);
  save(); closeSheet(); refresh();
}
function delProd() {
  if (!confirm('Delete ' + editProdOrig.name + '?')) return;
  data.products = data.products.filter(x => x !== editProdOrig);
  save(); closeSheet(); refresh();
}
function quoteProd(id) {
  const p = data.products.find(x => x.id === id);
  if (!p) return;
  data.quote = { ...blankQuote(), itemName: p.name, qty: 1, machineId: p.machineId, machineMin: p.machineMin, materialCost: p.materialCost,
    grams: p.grams, inkMl: p.inkMl, laborMin: p.laborMin, shipping: p.shipping, channelId: p.channelId };
  save(); show('quote');
}

/* ---------------- sheet / toast / nav ---------------- */
function openSheet(title, body, actions) {
  const sh = $('#sheet');
  sh.innerHTML = `<div class="sheet-head"><h2>${title}</h2><button class="btn ghost" data-act="closeSheet">✕ Close</button></div>
    <div class="sheet-body">${body}</div><div class="sheet-actions">${actions}</div>`;
  sh.hidden = false; document.body.classList.add('noscroll');
}
function closeSheet() {
  $('#sheet').hidden = true; document.body.classList.remove('noscroll');
  editJob = editJobOrig = editProd = editProdOrig = null;
}
let toastTimer;
function toast(msg, err) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'toast' + (err ? ' err' : ''); t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
}
let current = 'week';
function refresh() {
  ({ week: renderWeek, jobs: renderJobs, quote: buildQuote, products: renderProducts, settings: buildSettings })[current]();
  updateDerived();
}
function show(name) {
  current = name;
  $$('.screen').forEach(s => { s.hidden = s.id !== 'screen-' + name; });
  $$('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
  try { history.replaceState(null, '', '#' + name); } catch (e) { /* ignore */ }
  refresh(); window.scrollTo(0, 0);
}

/* ---------------- backup ---------------- */
function exportBackup() {
  const blob = new Blob([JSON.stringify({ app: 'shop-quoter', version: 1, exportedAt: new Date().toISOString(), data }, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `shop-backup-${todayStr()}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  toast('Backup downloaded');
}
$('#importFile').addEventListener('change', e => {
  const f = e.target.files[0]; e.target.value = '';
  if (!f) return;
  f.text().then(txt => {
    const inc = JSON.parse(txt), d = inc.data || inc;
    if (!d.settings || !Array.isArray(d.settings.machines) || !Array.isArray(d.jobs)) throw new Error('shape');
    if (!confirm('Replace ALL data on this phone with this backup?')) return;
    data = normalize(d); save(); refresh(); toast('Backup imported');
  }).catch(() => toast('That file is not a valid backup', true));
});

/* ---------------- clicks ---------------- */
document.addEventListener('click', e => {
  const t = e.target.closest('[data-tab],[data-act]');
  if (!t) return;
  if (t.dataset.tab) return show(t.dataset.tab);
  const id = t.dataset.id, find = list => data[list].find(x => x.id === id);
  ({
    advance: () => advance(id),
    editJob: () => openJob(find('jobs')),
    newJob: () => openJob(null),
    saveJob, delJob, closeSheet,
    newProd: () => openProd(null),
    editProd: () => openProd(find('products')),
    saveProd, delProd,
    quoteProd: () => quoteProd(id),
    saveAsJob,
    clearQuote: () => { data.quote = blankQuote(); save(); buildQuote(); },
    addMachine: () => {
      data.settings.machines.push({ id: 'm' + Date.now(), name: 'New machine', price: 0, life: 0, kw: 0, consumable: 0, billableHrs: 0, fixedMonthly: 0, inkId: '', note: '', ph: {} });
      save(); buildSettings();
    },
    delMachine: () => {
      const m = data.settings.machines[+t.dataset.i];
      if (confirm('Delete ' + m.name + '?')) { data.settings.machines.splice(+t.dataset.i, 1); save(); buildSettings(); }
    },
    export: exportBackup,
    import: () => $('#importFile').click(),
  })[t.dataset.act]?.();
});

/* ---------------- start ---------------- */
data = load();
$$('[data-legend]').forEach(e => { e.innerHTML = legendHTML; });
show(['week', 'jobs', 'quote', 'products', 'settings'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'week');
if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
