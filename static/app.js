// The signed-in app. The server is the real guard on permissions; the checks here
// only decide which buttons to show.
import { capture, countTo, drawLine, glide, growBars, pageChange, pop, reduced, slideTo, stagger } from './motion.js';

const TABS = [
  ['home', 'Overview', 'home', 'Home'], ['meals', 'Meals', 'bowl', 'Meals'], ['bazar', 'Bazar', 'cart', 'Bazar'],
  ['bills', 'Bills', 'bolt', 'Bills'], ['payments', 'Payments', 'wallet', 'Pay'], ['dwellers', 'Dwellers', 'users', 'People'],
  ['settings', 'Settings', 'gear', 'Settings'],
];
const S = {
  me: null, mess: 'BlueBlood', months: [], ym: null, tab: 'home', d: null,
  sideFilter: null, bazarFilter: null, open: new Set(), nums: new Map(), users: null, joining: false,
  pending: 0, adminName: '', adminCodeExpires: null,
};
const view = document.getElementById('view');
const sheet = document.getElementById('sheet');

// ---- helpers ---------------------------------------------------------------

const esc = v => String(v ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const fmt = (n, dp = 0) => {
  const text = Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp });
  return Number(text.replace(/,/g, '')) === 0 ? text : (n < 0 ? '−' : '') + text;
};
const tk = (n, dp = 0) => { const s = fmt(n, dp); return s.startsWith('−') ? `−৳${s.slice(1)}` : `৳${s}`; };
const qty = n => String(Math.round(n * 100) / 100);
const monthName = ym => new Date(`${ym}-01T00:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
const shortDate = iso => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : 'No date');
const FORMATS = { tk: n => tk(n), tk2: n => tk(n, 2), qty };

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
const member = id => S.d.members.find(m => m.id === id);
const calcFor = id => S.d.calc.members.find(r => r.id === id);
const side = id => S.d.sides.find(s => s.id === id);
const lastDay = () => `${S.ym}-${String(S.d.days).padStart(2, '0')}`;
const defaultDate = () => (today().startsWith(S.ym) ? today() : lastDay());
const isAdmin = () => S.me?.role === 'admin';
const mineId = () => S.d?.me.member_id ?? null;
const canEditMember = id => isAdmin() || id === mineId();
const canEditBill = b => isAdmin() || b.owner_id === S.me.id;

const hue = name => [...String(name)].reduce((h, c) => (h * 31 + c.codePointAt(0)) % 360, 7) % 90 + 195;
const initials = name => [...String(name).trim().split(/\s+/).slice(0, 2).map(w => [...w][0] ?? '')].join('').toUpperCase();
const avatar = name => `<span class="avatar" style="--h:${hue(name)}" aria-hidden="true">${esc(initials(name))}</span>`;

const ICONS = {
  home: 'M3 11l9-8 9 8M5 9.500V20h14V9.500',
  bowl: 'M3 11h18a9 9 0 0 1-18 0zM8 4c0 2 2 2 2 4M13 4c0 2 2 2 2 4',
  cart: 'M3 4h2l2.400 11h10.200L20 8H6.200M9.500 20a1 1 0 1 0 0-.01M17 20a1 1 0 1 0 0-.01',
  bolt: 'M13 3L5 14h6l-1 7 8-11h-6z',
  wallet: 'M3 7a2 2 0 0 1 2-2h13v3M3 7v11a2 2 0 0 0 2 2h15V8H5a2 2 0 0 1-2-1zM16 14h.01',
  users: 'M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 20v-2a4 4 0 0 0-3-3.900M16 2.100a4 4 0 0 1 0 7.800',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.400 15a1.700 1.700 0 0 0 .3 1.800l.1.100a2 2 0 1 1-2.800 2.800l-.1-.1a1.700 1.700 0 0 0-2.900 1.200V21a2 2 0 1 1-4 0v-.1a1.700 1.700 0 0 0-2.900-1.200l-.1.100a2 2 0 1 1-2.800-2.800l.1-.1a1.700 1.700 0 0 0-1.200-2.900H3a2 2 0 1 1 0-4h.1a1.700 1.700 0 0 0 1.200-2.900l-.1-.1a2 2 0 1 1 2.800-2.800l.1.100a1.700 1.700 0 0 0 2.900-1.200V3a2 2 0 1 1 4 0v.1a1.700 1.700 0 0 0 2.900 1.200l.1-.1a2 2 0 1 1 2.800 2.800l-.1.100a1.700 1.700 0 0 0 1.200 2.900h.1a2 2 0 1 1 0 4h-.1a1.700 1.700 0 0 0-1.500 1z',
  edit: 'M4 20h4L19 9a2.800 2.800 0 0 0-4-4L4 16zM13.500 6.500l4 4',
  trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6',
  lock: 'M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4',
  plus: 'M12 5v14M5 12h14',
  left: 'M15 5l-7 7 7 7',
  right: 'M9 5l7 7-7 7',
  down: 'M5 9l7 7 7-7',
  crown: 'M4 18h16l1-11-5.500 4L12 5 8.500 11 3 7z',
};
const icon = name => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[name]}"/></svg>`;
const count = (key, value, format) => `<span class="num" data-count="${value}" data-key="${esc(key)}" data-fmt="${format}">${FORMATS[format](value)}</span>`;

async function api(method, path, body) {
  const res = await fetch(`/api/${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { location.href = '/login'; throw new Error('Please sign in'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Could not save. Try again.');
  return data;
}
const monthApi = (method, path, body) => api(method, `months/${S.ym}${path}`, body);

let toastTimer;
function toast(message, bad) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = `toast show${bad ? ' bad' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, bad ? 4500 : 2200);
}

// ---- sheets ----------------------------------------------------------------

function openSheet(html) {
  sheet.classList.remove('closing');
  sheet.innerHTML = `<div class="grab" aria-hidden="true"></div>${html}`;
  sheet.showModal();
}

function closeSheet() {
  if (!sheet.open) return Promise.resolve();
  return new Promise(resolve => {
    const finish = () => { sheet.classList.remove('closing'); if (sheet.open) sheet.close(); resolve(); };
    if (reduced()) { finish(); return; }
    sheet.classList.add('closing');
    setTimeout(finish, 240);
  });
}
sheet.addEventListener('cancel', e => { e.preventDefault(); if (!S.joining) closeSheet(); });
sheet.addEventListener('click', e => {
  if (e.target.closest('[data-close]') || (e.target === sheet && !S.joining)) closeSheet();
});

/* Drag the handle down on a phone to dismiss. */
sheet.addEventListener('pointerdown', e => {
  if (!e.target.closest('.grab') || S.joining) return;
  const startY = e.clientY;
  sheet.setPointerCapture(e.pointerId);
  const move = ev => { sheet.style.transform = `translateY(${Math.max(0, ev.clientY - startY)}px)`; };
  const up = ev => {
    sheet.removeEventListener('pointermove', move);
    sheet.removeEventListener('pointerup', up);
    sheet.style.transform = '';
    if (ev.clientY - startY > 90) closeSheet();
  };
  sheet.addEventListener('pointermove', move);
  sheet.addEventListener('pointerup', up);
});

/* fields: {name, label, type, value, hint, options:[[value,label]], inputmode} */
function formSheet({ title, intro, fields, submit, onSubmit, onOpen }) {
  openSheet(`<form class="dlg" novalidate>
    <h2 id="sheet-title">${esc(title)}</h2>
    ${intro ? `<p>${esc(intro)}</p>` : ''}
    ${fields.map(fieldHtml).join('')}
    <div class="err" role="alert"></div>
    <div class="actions">
      <button type="button" class="btn" data-close>Cancel</button>
      <button type="submit" class="btn primary">${esc(submit)}</button>
    </div>
  </form>`);
  const form = sheet.querySelector('form');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = form.querySelector('[type=submit]');
    btn.disabled = true;
    btn.classList.add('busy');
    try {
      const values = {};
      for (const f of fields) {
        const el = form.elements.namedItem(f.name);
        values[f.name] = f.type === 'checkbox' ? el.checked : el.value.trim();
      }
      await onSubmit(values);
      await closeSheet();
    } catch (err) {
      form.querySelector('.err').textContent = err.message;
      btn.disabled = false;
      btn.classList.remove('busy');
    }
  });
  form.querySelector('input:not([type=checkbox]), select')?.focus();
  onOpen?.(form);
}

function fieldHtml(f) {
  const attrs = `name="${esc(f.name)}"`;
  if (f.type === 'checkbox') {
    return `<label class="check"><input type="checkbox" ${attrs} ${f.value ? 'checked' : ''}>
      <span>${esc(f.label)}${f.hint ? `<small>${esc(f.hint)}</small>` : ''}</span></label>`;
  }
  const control = f.type === 'select'
    ? `<select ${attrs}>${f.options.map(([v, l]) =>
        `<option value="${esc(v)}" ${String(v) === String(f.value) ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`
    : `<input ${attrs} type="${f.type || 'text'}" value="${esc(f.value)}" ${f.inputmode ? `inputmode="${f.inputmode}"` : ''}
        ${f.min ? `min="${f.min}"` : ''} ${f.max ? `max="${f.max}"` : ''} autocomplete="off">`;
  return `<label class="field"><span>${esc(f.label)}</span>${control}${f.hint ? `<small>${esc(f.hint)}</small>` : ''}</label>`;
}

function confirmSheet({ title, body, confirm, onConfirm }) {
  openSheet(`<div class="dlg">
    <h2 id="sheet-title">${esc(title)}</h2><p>${esc(body)}</p>
    <div class="err" role="alert"></div>
    <div class="actions">
      <button type="button" class="btn" data-close>Cancel</button>
      <button type="button" class="btn danger solid" data-confirm>${esc(confirm)}</button>
    </div></div>`);
  const btn = sheet.querySelector('[data-confirm]');
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      await onConfirm();
      await closeSheet();
    } catch (err) {
      sheet.querySelector('.err').textContent = err.message;
      btn.disabled = false;
    }
  };
}

// ---- loading and rendering -------------------------------------------------

// Meal cells save on blur, so a click on another tab starts a save and a page
// load together. load() waits here so it never reads the month before the save.
let mealSaves = Promise.resolve();

function parseHash() {
  const [, ym, tab] = location.hash.match(/^#\/(\d{4}-\d{2})\/(\w+)/) || [];
  return { ym, tab };
}

let loadCount = 0;

async function load(direction = 'none') {
  const thisLoad = ++loadCount;
  await mealSaves;
  const target = parseHash();
  const months = (await api('GET', 'months')).months;
  const ym = months.includes(target.ym) ? target.ym : months[0] || null;
  const tab = TABS.some(t => t[0] === target.tab) ? target.tab : 'home';
  const data = ym ? await api('GET', `months/${ym}`) : null;
  const accounts = ['settings', 'dwellers'].includes(tab) && isAdmin() ? await api('GET', 'users') : null;
  if (thisLoad !== loadCount) return;   // the person already moved on; a newer load wins
  S.months = months;
  if (accounts) noteAccounts(accounts);
  const newPage = tab !== S.tab;
  const show = () => {
    S.ym = ym; S.tab = tab; S.d = data;
    render();
    if (newPage) scrollTo(0, 0);
  };
  // The very first paint has nothing to slide away from, so it just appears.
  if (S.painted) await pageChange(show, direction); else show();
  S.painted = true;
  afterPaint(true);
}

function noteAccounts(data) {
  S.users = data.users;
  S.adminCodeExpires = data.admin_code_expires;
  S.pending = data.users.filter(u => u.status === 'pending').length;
}

function go(ym, tab) {
  const hash = `#/${ym}/${tab}`;
  if (location.hash === hash) load().catch(showError); else location.hash = hash;
}

function showError(err) {
  view.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
}

function navHtml(short) {
  const hide = short ? ['settings'] : [];
  return `<div class="navlist"><span class="nav-ind"></span>${TABS.filter(t => !hide.includes(t[0])).map(([id, label, ic, tiny]) =>
    `<a href="#/${S.ym ?? ''}/${id}" ${id === S.tab ? 'aria-current="page"' : ''} aria-label="${label}">${icon(ic)}<span>${short ? tiny : label}</span>${id === 'dwellers' && S.pending ? `<i class="badge" aria-label="${S.pending} waiting">${S.pending}</i>` : ''}</a>`).join('')}</div>`;
}

function renderShell() {
  document.title = S.mess;
  const rail = document.getElementById('rail'), dock = document.getElementById('dock'), top = document.getElementById('top');
  const brand = `<div class="brand"><span class="drop" aria-hidden="true"></span><b>${esc(S.mess)}</b></div>`;
  const keep = id => document.querySelector(`#${id} .nav-ind`)?.getAttribute('style') || '';
  const railStyle = keep('rail'), dockStyle = keep('dock');
  rail.innerHTML = `${brand}${navHtml(false)}
    <a class="me-chip" href="#/${S.ym ?? ''}/settings">${avatar(S.me.name)}
      <div><b>${esc(S.me.name)}</b><small>${isAdmin() ? 'Admin' : 'Dweller'}</small></div></a>`;
  dock.innerHTML = navHtml(true);
  const title = TABS.find(t => t[0] === S.tab)?.[1] ?? '';
  const index = S.months.indexOf(S.ym);
  top.innerHTML = `${brand}<h1>${esc(title)}</h1><div class="spacer"></div>
    ${S.ym ? `<div class="monthnav">
      <button class="ico" data-action="month-step" data-step="1" aria-label="Older month" ${index >= S.months.length - 1 ? 'disabled' : ''}>${icon('left')}</button>
      <label class="monthlabel"><span>${esc(monthName(S.ym))}</span>
        <select id="monthSelect" aria-label="Month">${S.months.map(m =>
          `<option value="${m}" ${m === S.ym ? 'selected' : ''}>${esc(monthName(m))}</option>`).join('')}</select></label>
      <button class="ico" data-action="month-step" data-step="-1" aria-label="Newer month" ${index <= 0 ? 'disabled' : ''}>${icon('right')}</button>
    </div>` : ''}
    ${isAdmin() ? '<button class="btn hide-phone" data-action="new-month">New month</button>' : ''}
    <a class="top-avatar" href="#/${S.ym ?? ''}/settings" aria-label="Settings">${avatar(S.me.name)}</a>`;
  // Restore the highlight's old position first, so it slides instead of jumping.
  [[rail, railStyle, true], [dock, dockStyle, false]].forEach(([box, style, vertical]) => {
    const ind = box.querySelector('.nav-ind'), active = box.querySelector('[aria-current]');
    if (style) {
      ind.setAttribute('style', style);
      requestAnimationFrame(() => slideTo(ind, active, vertical));
    } else {
      ind.style.transition = 'none';
      slideTo(ind, active, vertical);
      void ind.offsetWidth;
      ind.style.transition = '';
    }
  });
}

function render() {
  renderShell();
  const views = { home: homeView, meals: mealsView, bazar: bazarView, bills: billsView, payments: paymentsView, dwellers: dwellersView, settings: settingsView };
  if (!S.ym && S.tab !== 'settings') {
    view.innerHTML = `<div class="card"><p class="empty">No months yet.</p>
      ${isAdmin() ? '<p class="empty"><button class="btn primary" data-action="new-month">Start a month</button></p>' : ''}</div>`;
    return;
  }
  view.innerHTML = views[S.tab]();
  const todayRow = view.querySelector('tr.today');
  if (todayRow) todayRow.closest('.grid-wrap').scrollTop = todayRow.offsetTop - 80;
}

function afterPaint(entering) {
  view.querySelectorAll('[data-count]').forEach(el => {
    const key = el.dataset.key, to = Number(el.dataset.count);
    const from = S.nums.has(key) ? S.nums.get(key) : (entering ? to * .6 : to);
    countTo(el, from, to, FORMATS[el.dataset.fmt]);
    S.nums.set(key, to);
  });
  if (entering) {
    stagger(view);
    growBars(view);
    view.querySelectorAll('.spark .line').forEach(drawLine);
  }
  const seg = view.querySelector('.seg');
  if (seg) slideTo(seg.querySelector('.thumb'), seg.querySelector('[aria-pressed="true"]'));
}

/** Applies fresh month data: moved rows glide, new ones grow in, deleted ones melt. */
function update(data, message) {
  const before = capture(view);
  S.d = data;
  render();
  glide(view, before);
  afterPaint(false);
  if (message) toast(message);
}
const save = async (promise, message) => update(await promise, message);

// ---- overview --------------------------------------------------------------

const dueText = n => (n > 0 ? `<span class="owes">${tk(n)}</span>`
  : n < 0 ? `<span class="gets">Gets ${tk(-n)}</span>` : '<span>Settled</span>');
const balanceText = n => (Math.abs(n) < 0.005 ? 'Even'
  : n > 0 ? `Owes ${tk(n, 2)}` : `Gets ${tk(-n, 2)}`);

function sideChips(action, selected, withTotals) {
  const { sides, calc } = S.d;
  return `<div class="chips"><button class="chip" data-action="${action}" data-id="" aria-pressed="${!selected}">All sides</button>
    ${sides.map(s => {
      const info = calc.sides.find(x => x.id === s.id);
      return `<button class="chip" data-action="${action}" data-id="${s.id}" aria-pressed="${selected === s.id}">
        ${esc(s.name)}${withTotals ? ` · ${tk(info.total_due)}` : ` · ${info.people}`}</button>`;
    }).join('')}</div>`;
}

function mineCard() {
  const id = mineId();
  if (!id) return `<section class="card my-share" data-in><h2>You're not in ${esc(monthName(S.ym))}</h2>
    <p class="note">Everything here is visible to you, but it doesn't include you.</p></section>`;
  const r = calcFor(id);
  return `<section class="card my-share" data-in>
    <small class="note" style="margin:0">Your share</small>
    <div class="big ${r.due > 0 ? 'owes' : r.due < 0 ? 'gets' : ''}">${r.due < 0 ? 'You get ' : ''}${count('mine-due', Math.abs(r.due), 'tk')}</div>
    <dl>
      <dt>Rent</dt><dd>${tk(r.rent)}</dd>
      <dt>Service charge</dt><dd>${tk(r.service, 2)}</dd>
      <dt>Meals (${qty(r.meals)})</dt><dd>${tk(r.meal_cost, 2)}</dd>
      <dt>Your bazar</dt><dd>${tk(-r.bazar)}</dd>
      <dt>Paid</dt><dd>${tk(-r.paid)}</dd>
    </dl></section>`;
}

function dailyChart() {
  const { days, members, meals } = S.d;
  const totals = Array.from({ length: days }, (_, i) => members.reduce((a, m) => a + (meals[m.id]?.[i + 1] || 0), 0));
  const max = Math.max(...totals, 1);
  const x = i => (i / Math.max(days - 1, 1)) * 600, y = v => 112 - (v / max) * 100;
  const line = totals.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  return `<div class="spark" data-days='${JSON.stringify(totals)}'>
    <svg viewBox="0 0 600 120" preserveAspectRatio="none" role="img" aria-label="Meals per day">
      <path class="area" d="${line} L600 120 L0 120 Z"/><path class="line" d="${line}"/>
      <line class="cursor" x1="0" x2="0" y1="0" y2="120"/></svg>
    <span class="tip"></span></div>`;
}

function homeView() {
  const { calc, members, sides } = S.d;
  if (!members.length) return emptyMembers();
  const spenders = [...members].sort((a, b) => calcFor(b.id).bazar - calcFor(a.id).bazar);
  const top = Math.max(...spenders.map(m => calcFor(m.id).bazar), 1);
  const bars = spenders.map(m => {
    const r = calcFor(m.id);
    return `<li data-k="bar-${m.id}"><button data-action="bazar-of" data-id="${m.id}">
      <span class="who">${esc(m.name)}</span>
      <span class="track"><span class="fill" data-bar style="--p:${(r.bazar / top * 100).toFixed(1)}%"></span></span>
      <span class="num">${tk(r.bazar)}</span></button></li>`;
  }).join('');
  const shown = sides.filter(s => !S.sideFilter || s.id === S.sideFilter);
  const groups = shown.filter(s => members.some(m => m.side_id === s.id)).map(s => {
    const info = calc.sides.find(x => x.id === s.id);
    const rows = members.filter(m => m.side_id === s.id).map(m => {
      const r = calcFor(m.id), open = S.open.has(m.id);
      return `<li class="payitem ${open ? 'open' : ''}" data-k="pay-${m.id}">
        <button class="payrow" data-action="toggle-pay" data-id="${m.id}" aria-expanded="${open}">
          ${avatar(m.name)}
          <span class="row-main"><b>${esc(m.name)}${m.id === mineId() ? ' <span class="tag you">You</span>' : ''}</b>
            <small>${qty(r.meals)} meals · bazar ${tk(r.bazar)}</small></span>
          <span class="amt">${dueText(r.due)}</span><span class="chev">${icon('down')}</span>
        </button>
        <div class="fold"><div><dl>
          <dt>Rent</dt><dd>${tk(r.rent)}</dd><dt>Service charge</dt><dd>${tk(r.service, 2)}</dd>
          <dt>Meal balance</dt><dd>${balanceText(r.balance)}</dd><dt>Total</dt><dd>${tk(r.total, 2)}</dd>
          <dt>Paid</dt><dd>${tk(r.paid)}</dd></dl></div></div></li>`;
    }).join('');
    return `<div class="side-label"><span>${esc(s.name)} · ${info.people} ${info.people === 1 ? 'person' : 'people'}</span><span class="num">${tk(info.total_due)}</span></div>
      <ul class="rows">${rows}</ul>`;
  }).join('');

  return `${requestNotice()}<div class="hero-row">
    <section class="hero" data-in><div class="fluid" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <small>${esc(S.mess)} · still to collect</small><b>${count('hero', calc.total_due, 'tk')}</b>
      <p>${tk(calc.total_paid)} paid so far in ${esc(monthName(S.ym))}</p></section>
    ${mineCard()}
  </div>
  <section class="kpis" aria-label="Month totals">
    <div class="kpi" data-in><b>${count('rate', calc.meal_rate, 'tk2')}</b><span>Meal rate</span></div>
    <div class="kpi" data-in><b>${count('bazar', calc.total_bazar, 'tk')}</b><span>Total bazar</span></div>
    <div class="kpi" data-in><b>${count('meals', calc.total_meals, 'qty')}</b><span>Total meals</span></div>
    <div class="kpi" data-in><b>${count('shared', calc.shared_per_head, 'tk')}</b><span>Shared bills each</span></div>
  </section>
  <div class="grid-2 stack">
    <section class="card" data-in><div class="card-head"><div><h2>Meals each day</h2><p>Move across the line to see a day</p></div></div>${dailyChart()}</section>
    <section class="card" data-in><div class="card-head"><div><h2>Who bought bazar</h2><p>Select a name to see their list</p></div></div><ul class="bars">${bars}</ul></section>
  </div>
  <section class="card" data-in>
    <div class="card-head"><div><h2>Who pays what</h2><p>Rent + service charge + meal balance − paid, rounded up</p></div></div>
    ${sides.length > 1 ? sideChips('side-filter', S.sideFilter, true) : ''}${groups}
  </section>`;
}

function requestNotice() {
  if (!isAdmin() || !S.pending) return '';
  const who = S.pending === 1 ? '1 person is' : `${S.pending} people are`;
  return `<section class="notice" data-in data-k="notice"><div><b>${who} waiting to join</b><p>Approve them so they can sign in.</p></div>
    <a class="btn primary small" href="#/${S.ym}/dwellers">Review</a></section>`;
}

function requestsCard() {
  if (!isAdmin() || !S.users) return '';
  const waiting = S.users.filter(u => u.status === 'pending');
  if (!waiting.length) return '';
  const rows = waiting.map(u => `<li class="row" data-k="req-${u.id}">${avatar(u.name)}
    <div class="row-main"><b>${esc(u.name)}</b><small>${esc(u.username)} · ${esc(u.email)}</small></div>
    <span class="card-actions"><button class="btn small primary" data-action="approve-user" data-id="${u.id}">Approve</button>
      <button class="btn small danger" data-action="decline-user" data-id="${u.id}">Decline</button></span></li>`).join('');
  return `<section class="card" data-in data-k="requests"><div class="card-head"><div><h2>Join requests</h2>
    <p>Only approve people you know. Approving lets them read everything in the mess.</p></div></div><ul class="rows">${rows}</ul></section>`;
}

function emptyMembers() {
  return `<div class="card"><p class="empty">Add your dwellers first, then meals and bazar can be recorded.</p>
    <p class="empty"><a class="btn primary" href="#/${S.ym}/dwellers">Go to Dwellers</a></p></div>`;
}

// ---- meals -----------------------------------------------------------------

function todayCard() {
  const id = mineId();
  if (!id || !today().startsWith(S.ym)) return '';
  const day = Number(today().slice(8));
  const value = S.d.meals[id]?.[day] ?? 0;
  return `<section class="card today-card" data-in>
    <div><h2>Your meals today</h2><p>Half meals are fine. Saves as you tap.</p></div>
    <div class="stepper">
      <button data-action="meal-step" data-step="-0.5" aria-label="Fewer meals">−</button>
      <output id="todayMeals" aria-live="polite">${qty(value)}</output>
      <button data-action="meal-step" data-step="0.5" aria-label="More meals">+</button>
    </div></section>`;
}

function mealsView() {
  const { members, meals, days, calc } = S.d;
  if (!members.length) return emptyMembers();
  const dayTotal = d => members.reduce((a, m) => a + (meals[m.id]?.[d] || 0), 0);
  const todayNum = today().startsWith(S.ym) ? Number(today().slice(8)) : 0;
  let rows = '';
  for (let d = 1; d <= days; d++) {
    const date = new Date(`${S.ym}-${String(d).padStart(2, '0')}T00:00:00`);
    const cells = members.map((m, col) => {
      const v = meals[m.id]?.[d];
      const open = canEditMember(m.id);
      return `<td class="${m.id === mineId() ? 'mine' : ''}"><input data-meal data-m="${m.id}" data-d="${d}" data-col="${col}" inputmode="decimal"
        aria-label="${esc(m.name)}, day ${d}" value="${v ?? ''}" class="${v === 0 ? 'zero' : ''}" ${open ? '' : 'readonly tabindex="-1"'}></td>`;
    }).join('');
    rows += `<tr class="${d === todayNum ? 'today' : ''}">
      <td class="day sticky">${d}<small>${date.toLocaleDateString('en-GB', { weekday: 'short' })}</small></td>
      ${cells}<td class="sum" id="day-${d}">${qty(dayTotal(d))}</td></tr>`;
  }
  const note = isAdmin() ? 'As admin you can edit every column.' : 'You can edit your own column. Everyone else\'s is view only.';
  return `${todayCard()}<section class="card" data-in>
    <div class="card-head"><div><h2>Daily meals</h2><p>${note} Cells save when you move on; arrow keys and Enter move between them.</p></div></div>
    <div class="grid-wrap"><table class="meals">
      <thead><tr><th class="sticky">Day</th>${members.map(m => `<th class="${m.id === mineId() ? 'mine' : ''}">${esc(m.name)}</th>`).join('')}<th>Total</th></tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr><td class="day sticky">Total</td>${members.map(m =>
        `<td id="tot-${m.id}" class="${m.id === mineId() ? 'mine' : ''}">${qty(calcFor(m.id).meals)}</td>`).join('')}<td id="tot-all">${qty(calc.total_meals)}</td></tr></tfoot>
    </table></div></section>`;
}

async function saveMeal(input) {
  if (input.readOnly) return;
  const value = input.value.trim();
  const previous = input.dataset.saved ?? input.defaultValue;
  if (value === previous) return;
  if (value !== '' && !(Number(value) >= 0 && Number(value) <= 100)) {
    input.value = previous;
    toast('Meals must be a number from 0 to 100', true);
    return;
  }
  const memberId = Number(input.dataset.m), day = Number(input.dataset.d);
  try {
    S.d = await monthApi('PUT', '/meals', { member_id: memberId, day, qty: value });
    input.dataset.saved = value;
    input.classList.toggle('zero', value !== '' && Number(value) === 0);
    input.classList.remove('saved');
    void input.offsetWidth;
    input.classList.add('saved');
    showMealTotals(memberId, day);
  } catch (err) {
    input.value = previous;
    toast(err.message, true);
  }
}

function showMealTotals(memberId, day) {
  const dayTotal = S.d.members.reduce((a, m) => a + (S.d.meals[m.id]?.[day] || 0), 0);
  // These cells are gone if the view changed while the save was running.
  const show = (id, n) => { const el = document.getElementById(id); if (el) { el.textContent = qty(n); pop(el); } };
  show(`day-${day}`, dayTotal);
  show(`tot-${memberId}`, calcFor(memberId).meals);
  show('tot-all', S.d.calc.total_meals);
}

function moveInGrid(input, key) {
  const col = Number(input.dataset.col), day = Number(input.dataset.d);
  const target = {
    ArrowUp: [col, day - 1], ArrowDown: [col, day + 1], Enter: [col, day + 1],
    ArrowLeft: [col - 1, day], ArrowRight: [col + 1, day],
  }[key];
  const next = view.querySelector(`[data-meal][data-col="${target[0]}"][data-d="${target[1]}"]`);
  if (next && !next.readOnly) { next.focus(); next.select(); } else if (key === 'Enter') input.blur();
}

// ---- bazar -----------------------------------------------------------------

function rowActions(canEdit, editAction, deleteAction, id) {
  if (!canEdit) return `<span class="locked" title="View only" aria-label="View only">${icon('lock')}</span>`;
  return `<span class="row-actions">
    <button class="ico" data-action="${editAction}" data-id="${id}" aria-label="Edit">${icon('edit')}</button>
    <button class="ico danger" data-action="${deleteAction}" data-id="${id}" aria-label="Delete">${icon('trash')}</button></span>`;
}

function bazarView() {
  const { members, bazar, calc } = S.d;
  if (!members.length) return emptyMembers();
  if (!members.some(m => m.id === S.bazarFilter)) S.bazarFilter = null;
  const shown = S.bazarFilter ? bazar.filter(b => b.member_id === S.bazarFilter) : bazar;
  const chips = [`<button class="chip" data-action="bazar-filter" data-id="" aria-pressed="${!S.bazarFilter}">Everyone ${tk(calc.total_bazar)}</button>`,
    ...members.map(m => `<button class="chip" data-action="bazar-filter" data-id="${m.id}" aria-pressed="${S.bazarFilter === m.id}">
      ${esc(m.name)} ${tk(calcFor(m.id).bazar)}</button>`)].join('');
  let list = '', lastDate = null;
  for (const b of shown) {
    if (b.date !== lastDate) {
      const sum = shown.filter(x => x.date === b.date).reduce((a, x) => a + x.amount, 0);
      if (lastDate !== null) list += '</ul>';
      list += `<div class="day-head"><span>${shortDate(b.date)}</span><span class="num">${tk(sum)}</span></div><ul class="rows">`;
      lastDate = b.date;
    }
    const who = member(b.member_id)?.name;
    list += `<li class="row" data-k="bz-${b.id}">${avatar(who)}
      <div class="row-main"><b>${esc(b.item) || 'No item name'}</b><small>${esc(who)}${b.member_id === mineId() ? ' <span class="tag you">You</span>' : ''}</small></div>
      <span class="amt">${b.amount ? tk(b.amount, b.amount % 1 ? 2 : 0) : '—'}</span>
      ${rowActions(canEditMember(b.member_id), 'edit-bazar', 'delete-bazar', b.id)}</li>`;
  }
  if (lastDate !== null) list += '</ul>';
  const canAdd = isAdmin() || mineId();
  return `<section class="card" data-in>
    <div class="card-head"><div><h2>Bazar</h2><p>Everything bought for the mess. Anyone can read it; you can change your own.</p></div>
      ${canAdd ? `<div class="card-actions"><button class="btn primary" data-action="add-bazar">${icon('plus')}Add bazar</button></div>` : ''}</div>
    <div class="chips">${chips}</div>
    ${shown.length ? list : '<p class="empty">No bazar recorded here yet.</p>'}
  </section>`;
}

function bazarFields(b) {
  const fields = [
    { name: 'date', label: 'Date', type: 'date', value: b?.date ?? defaultDate(), min: `${S.ym}-01`, max: lastDay() },
    { name: 'item', label: 'Item', value: b?.item ?? '' },
    { name: 'amount', label: 'Amount (৳)', value: b?.amount ?? '', inputmode: 'decimal' },
  ];
  if (isAdmin()) {
    fields.unshift({ name: 'member_id', label: 'Bought by', type: 'select', value: b?.member_id ?? S.bazarFilter ?? mineId() ?? '',
      options: S.d.members.map(m => [m.id, m.name]) });
  }
  return fields;
}

// ---- bills -----------------------------------------------------------------

function billRows(bills) {
  if (!bills.length) return '<p class="empty">No bills here yet.</p>';
  const rows = bills.map(b => {
    const share = S.d.calc.bills.find(x => x.id === b.id);
    return `<li class="row" data-k="bl-${b.id}"><div class="row-main"><b>${esc(b.name)}</b>
      <small>${b.breakdown ? `<span>${esc(b.breakdown)}</span>` : ''}<span>${b.owner_name ? `Added by ${esc(b.owner_name)}` : 'Added by the admin'}</span>
      ${b.round_up ? '' : '<span class="tag">Not rounded</span>'}</small></div>
      <span class="amt">${tk(b.amount, b.amount % 1 ? 2 : 0)}<br><small style="color:var(--muted);font-weight:500">${tk(share.per_head, b.round_up ? 0 : 2)} each</small></span>
      ${rowActions(canEditBill(b), 'edit-bill', 'delete-bill', b.id)}</li>`;
  }).join('');
  return `<ul class="rows">${rows}</ul>`;
}

function billsView() {
  const { bills, sides, calc, members } = S.d;
  const mySide = S.d.me.side_id;
  const shared = bills.filter(b => b.side_id === null);
  const canAddShared = isAdmin() || mineId();
  const cards = sides.map(s => {
    const info = calc.sides.find(x => x.id === s.id);
    const parts = [];
    if (!s.bills_charged) parts.push('These bills are tracked here but not added to the service charge.');
    if (s.addon) parts.push(`Fixed add-on: ${tk(s.addon)} per person.`);
    const canAdd = isAdmin() || s.id === mySide;
    return `<section class="card" data-in data-k="side-${s.id}">
      <div class="card-head"><div><h2>${esc(s.name)} side</h2>
        <p>${info.people} ${info.people === 1 ? 'person' : 'people'} · service charge ${tk(info.service_charge, 2)} each</p></div>
        <div class="card-actions">
          ${canAdd ? `<button class="btn small" data-action="add-bill" data-side="${s.id}">${icon('plus')}Add bill</button>` : ''}
          ${isAdmin() ? `<button class="btn small" data-action="edit-side" data-id="${s.id}">Side settings</button>
            <button class="btn small danger" data-action="delete-side" data-id="${s.id}">Delete</button>` : ''}
        </div></div>
      ${billRows(bills.filter(b => b.side_id === s.id))}
      ${parts.length ? `<p class="note">${esc(parts.join(' '))}</p>` : ''}
    </section>`;
  }).join('');
  return `<section class="card" data-in>
    <div class="card-head"><div><h2>Shared by everyone</h2><p>Split between all ${members.length} dwellers · ${tk(calc.shared_per_head)} each</p></div>
      ${canAddShared ? `<div class="card-actions"><button class="btn small" data-action="add-bill" data-side="">${icon('plus')}Add bill</button></div>` : ''}</div>
    ${billRows(shared)}
  </section>${cards}
  ${isAdmin() ? `<p data-in><button class="btn" data-action="add-side">${icon('plus')}Add side</button></p>` : ''}`;
}

function billFields(b, sideId) {
  const sides = isAdmin() ? S.d.sides : S.d.sides.filter(s => s.id === S.d.me.side_id);
  return [
    { name: 'name', label: 'Bill name', value: b?.name ?? '' },
    { name: 'amount', label: 'Amount (৳)', value: b ? (b.breakdown || b.amount) : '', hint: 'A sum works too, like 100+30+150', inputmode: 'text' },
    { name: 'side_id', label: 'Shared by', type: 'select', value: b ? (b.side_id ?? '') : sideId,
      options: [['', 'Everyone'], ...sides.map(s => [s.id, `${s.name} side`])] },
    { name: 'round_up', label: 'Round each share up to a whole taka', type: 'checkbox', value: b ? b.round_up : true },
  ];
}

function sideFields(s) {
  return [
    { name: 'name', label: 'Side name', value: s?.name ?? '', hint: 'South, North, Roof, or anything you like' },
    { name: 'bills_charged', label: "Add this side's bills to its service charge", type: 'checkbox', value: s ? s.bills_charged : true,
      hint: 'Turn off to track the bills without charging them here' },
    { name: 'addon', label: 'Fixed add-on per person (৳)', value: s?.addon ?? 0, inputmode: 'decimal' },
  ];
}

// ---- payments --------------------------------------------------------------

function paymentsView() {
  const { payments, members, calc } = S.d;
  if (!members.length) return emptyMembers();
  const rows = payments.map(p => {
    const who = member(p.member_id)?.name;
    return `<li class="row" data-k="py-${p.id}">${avatar(who)}
      <div class="row-main"><b>${esc(who)}${p.member_id === mineId() ? ' <span class="tag you">You</span>' : ''}</b>
        <small>${shortDate(p.date)}${p.note ? ` · ${esc(p.note)}` : ''}</small></div>
      <span class="amt ${p.amount < 0 ? 'owes' : 'gets'}">${tk(p.amount, p.amount % 1 ? 2 : 0)}</span>
      ${rowActions(canEditMember(p.member_id), 'edit-payment', 'delete-payment', p.id)}</li>`;
  }).join('');
  const whole = Math.max(calc.total_paid + Math.max(calc.total_due, 0), 1);
  const percent = Math.min(100, Math.max(0, calc.total_paid / whole * 100));
  const canAdd = isAdmin() || mineId();
  return `<section class="card" data-in>
    <div class="card-head"><div><h2>Payments</h2><p>${tk(calc.total_paid)} paid · ${tk(calc.total_due)} still due</p></div>
      ${canAdd ? `<div class="card-actions"><button class="btn primary" data-action="add-payment">${icon('plus')}Add payment</button></div>` : ''}</div>
    <ul class="bars" style="margin-bottom:12px"><li><span class="track" style="display:block;height:10px;border-radius:99px;background:var(--sunk);overflow:hidden">
      <span class="fill" data-bar style="display:block;height:100%;width:${percent.toFixed(1)}%;background:linear-gradient(90deg,#5b82ff,var(--accent));border-radius:99px;transform-origin:left"></span></span></li></ul>
    ${payments.length ? `<ul class="rows">${rows}</ul>` : '<p class="empty">No payments yet.</p>'}
  </section>`;
}

function paymentFields(p) {
  const fields = [
    { name: 'amount', label: 'Amount (৳)', value: p?.amount ?? '', inputmode: 'text', hint: 'A negative amount adds a charge instead, like −223' },
    { name: 'date', label: 'Date', type: 'date', value: p ? (p.date ?? '') : today() },
    { name: 'note', label: 'Note', value: p?.note ?? '' },
  ];
  if (isAdmin()) {
    fields.unshift({ name: 'member_id', label: 'From', type: 'select', value: p?.member_id ?? mineId() ?? '', options: S.d.members.map(m => [m.id, m.name]) });
  }
  return fields;
}

// ---- dwellers --------------------------------------------------------------

function dwellersView() {
  const { members, sides, calc } = S.d;
  const shown = sides.filter(s => !S.sideFilter || s.id === S.sideFilter);
  const cards = shown.map(s => {
    const info = calc.sides.find(x => x.id === s.id);
    const people = members.filter(m => m.side_id === s.id).map(m => {
      const r = calcFor(m.id);
      return `<div class="person" data-k="m-${m.id}">${avatar(m.name)}
        <div class="who"><b><span class="n">${esc(m.name)}</span>
          ${m.role === 'admin' ? `<span class="tag admin">${icon('crown')}Admin</span>` : ''}${m.id === mineId() ? '<span class="tag you">You</span>' : ''}</b>
          <small>${tk(m.rent)} rent · ${qty(r.meals)} meals${m.user_id ? '' : ' · no account'}</small></div>
        ${isAdmin() ? `<span class="row-actions"><button class="ico" data-action="edit-member" data-id="${m.id}" aria-label="Edit ${esc(m.name)}">${icon('edit')}</button>
          <button class="ico danger" data-action="delete-member" data-id="${m.id}" aria-label="Remove ${esc(m.name)}">${icon('trash')}</button></span>` : ''}
      </div>`;
    }).join('');
    return `<section class="card" data-in data-k="ds-${s.id}">
      <div class="card-head"><div><h2>${esc(s.name)} side</h2><p>${info.people} ${info.people === 1 ? 'person' : 'people'}</p></div>
        ${isAdmin() ? `<div class="card-actions"><button class="btn small" data-action="edit-side" data-id="${s.id}">Side settings</button></div>` : ''}</div>
      ${people ? `<div class="people">${people}</div>` : '<p class="empty">Nobody on this side yet.</p>'}
    </section>`;
  }).join('');
  return `${requestsCard()}<div class="card-head" data-in style="margin-bottom:10px">
      <div><p>Bills re-split automatically when someone joins or leaves.</p></div>
      ${isAdmin() ? `<div class="card-actions"><button class="btn" data-action="add-side">${icon('plus')}Add side</button>
        <button class="btn primary" data-action="add-member">${icon('plus')}Add dweller</button></div>` : ''}</div>
    ${sides.length > 1 ? sideChips('side-filter', S.sideFilter, false) : ''}${cards}`;
}

async function memberFields(m) {
  const users = (await api('GET', 'users')).users;
  const taken = new Set(S.d.members.filter(x => x.user_id && x.id !== m?.id).map(x => x.user_id));
  return [
    { name: 'name', label: 'Name', value: m?.name ?? '' },
    { name: 'side_id', label: 'Side', type: 'select', value: m?.side_id ?? S.d.sides[0]?.id, options: S.d.sides.map(s => [s.id, s.name]) },
    { name: 'rent', label: 'Monthly rent (৳)', value: m?.rent ?? 0, inputmode: 'decimal' },
    { name: 'user_id', label: 'Account', type: 'select', value: m?.user_id ?? '', hint: 'Linking lets this person sign in and edit their own entries',
      options: [['', 'No account'], ...users.filter(u => !taken.has(u.id)).map(u => [u.id, `${u.name} (${u.username})`])] },
  ];
}

// ---- settings --------------------------------------------------------------

function themeNow() {
  try { return localStorage.getItem('bb-theme') || 'system'; } catch { return 'system'; }
}

function settingsView() {
  const u = S.me;
  const theme = themeNow();
  const codeUntil = S.adminCodeExpires
    ? new Date(S.adminCodeExpires * 1000).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : null;
  const accounts = isAdmin() && S.users ? S.users.filter(a => a.status === 'active').map(a => `<li class="row" data-k="u-${a.id}">${avatar(a.name)}
      <div class="row-main"><b>${esc(a.name)} ${a.role === 'admin' ? '<span class="tag admin">Admin</span>' : ''}</b><small>${esc(a.username)} · ${esc(a.email)}</small></div>
      ${a.id === u.id ? '' : `<span class="row-actions"><button class="ico" data-action="make-admin" data-id="${a.id}" aria-label="Make ${esc(a.name)} the admin" title="Make admin">${icon('crown')}</button>
        <button class="ico danger" data-action="delete-user" data-id="${a.id}" aria-label="Remove ${esc(a.name)}'s account" title="Remove account">${icon('trash')}</button></span>`}</li>`).join('') : '';
  return `<div class="grid-2 stack">
    <section class="card" data-in><div class="card-head"><div><h2>Your profile</h2><p>Your name shows across the mess.</p></div></div>
      <form class="form-grid" id="profileForm" novalidate>
        ${fieldHtml({ name: 'name', label: 'Name', value: u.name })}
        ${fieldHtml({ name: 'username', label: 'Username', value: u.username })}
        ${fieldHtml({ name: 'email', label: 'Email', type: 'email', value: u.email })}
        <div class="err" role="alert"></div><div><button class="btn primary" type="submit">Save profile</button></div>
      </form></section>
    <section class="card" data-in><div class="card-head"><div><h2>Change password</h2><p>This signs you out of your other devices.</p></div></div>
      <form class="form-grid" id="passwordForm" novalidate>
        ${fieldHtml({ name: 'current', label: 'Current password', type: 'password' })}
        ${fieldHtml({ name: 'password', label: 'New password', type: 'password', hint: 'At least 8 characters' })}
        <div class="err" role="alert"></div><div><button class="btn primary" type="submit">Change password</button></div>
      </form></section>
    </div>
    <section class="card" data-in><div class="card-head"><div><h2>Appearance</h2><p>Saved on this device.</p></div></div>
      <div class="seg" role="group" aria-label="Theme"><span class="thumb"></span>
        ${[['system', 'System'], ['light', 'Light'], ['dark', 'Dark']].map(([id, label]) =>
          `<button data-action="theme" data-theme-choice="${id}" aria-pressed="${theme === id}">${label}</button>`).join('')}</div></section>
    ${isAdmin() ? '' : `<section class="card" data-in><div class="card-head"><div><h2>${esc(S.mess)}</h2><p>Your admin is ${esc(S.adminName)}.</p></div></div></section>`}
    ${isAdmin() ? `<section class="card" data-in><div class="card-head"><div><h2>Mess</h2><p>You're the admin. Only you can change this.</p></div></div>
      <form class="form-grid" id="messForm" novalidate>
        ${fieldHtml({ name: 'mess_name', label: 'Mess name', value: S.mess })}
        <div class="err" role="alert"></div>
        <div class="card-actions"><button class="btn primary" type="submit">Save name</button>
          ${S.ym ? `<button class="btn" type="button" data-action="new-month">New month</button>
            <button class="btn danger" type="button" data-action="delete-month">Delete ${esc(monthName(S.ym))}</button>` : ''}</div>
      </form></section>
      <section class="card" data-in><div class="card-head"><div><h2>Accounts</h2><p>There is one admin. Passing the crown makes you a dweller.</p></div></div>
        <ul class="rows">${accounts}</ul></section>
      <section class="card" data-in><div class="card-head"><div><h2>Invite a new admin</h2>
        <p>For someone without an account. They choose Admin when joining and enter this code. It works once, for 24 hours, and you become a dweller when it's used.</p></div></div>
        ${codeUntil ? `<p class="note">A code is active until ${esc(codeUntil)}.</p>` : ''}
        <div class="card-actions" style="margin-top:10px"><button class="btn" data-action="admin-code">${codeUntil ? 'Replace code' : 'Create admin code'}</button>
          ${codeUntil ? '<button class="btn danger" data-action="cancel-admin-code">Cancel code</button>' : ''}</div></section>` : ''}
    <p data-in><button class="btn danger" data-action="logout">Sign out</button></p>`;
}

function bindForm(id, run) {
  document.addEventListener('submit', async e => {
    if (e.target.id !== id) return;
    e.preventDefault();
    const form = e.target, btn = form.querySelector('[type=submit]'), err = form.querySelector('.err');
    err.textContent = '';
    btn.disabled = true;
    try {
      await run(Object.fromEntries(new FormData(form).entries()), form);
    } catch (error) {
      err.textContent = error.message;
    }
    btn.disabled = false;
  });
}

bindForm('profileForm', async v => {
  const out = await api('PUT', 'me', v);
  S.me = out.user;
  S.d = S.ym ? await api('GET', `months/${S.ym}`) : null;
  renderShell();
  toast('Profile saved');
});
bindForm('passwordForm', async (v, form) => {
  await api('PUT', 'me/password', v);
  form.reset();
  toast('Password changed');
});
bindForm('messForm', async v => {
  S.mess = (await api('PUT', 'settings', v)).mess_name;
  renderShell();
  toast('Mess name saved');
});

// ---- joining ---------------------------------------------------------------

function showJoin(join) {
  S.joining = true;
  const names = join.unclaimed.map(m =>
    `<button class="chip" type="button" data-claim="${m.id}">${esc(m.name)}</button>`).join('');
  openSheet(`<div class="dlg">
    <h2 id="sheet-title">Welcome, ${esc(S.me.name)}. You're the admin.</h2>
    <p>Let's put you in ${esc(monthName(join.ym))} too.</p>
    ${names ? `<div class="field"><span>Are you already listed? Pick your name.</span><div class="join-names">${names}</div></div>` : ''}
    <form class="form-grid" id="joinForm" novalidate>
      ${fieldHtml({ name: 'side_id', label: names ? "If you're new, choose your side" : 'Choose your side', type: 'select', value: join.sides[0]?.id,
        options: join.sides.map(s => [s.id, s.name]) })}
      <div class="err" role="alert"></div>
      <button class="btn primary wide" type="submit">Continue</button>
    </form></div>`);
  const finish = async body => {
    await api('POST', 'join', body);
    S.joining = false;
    await closeSheet();
    toast(`Welcome to ${S.mess}`);
    await load();
  };
  const fail = error => { sheet.querySelector('.err').textContent = error.message; };
  sheet.querySelectorAll('[data-claim]').forEach(b => b.addEventListener('click', () => finish({ member_id: Number(b.dataset.claim) }).catch(fail)));
  sheet.querySelector('#joinForm').addEventListener('submit', e => {
    e.preventDefault();
    finish({ side_id: Number(e.target.elements.namedItem('side_id').value) }).catch(fail);
  });
}

// ---- actions ---------------------------------------------------------------

const actions = {
  'month-step'(_, el) {
    const next = S.months[S.months.indexOf(S.ym) + Number(el.dataset.step)];
    if (next) { pendingDirection = Number(el.dataset.step) > 0 ? 'right' : 'left'; go(next, S.tab); }
  },
  'new-month'() {
    const latest = S.months[0];
    let next = today().slice(0, 7);
    if (latest) {
      const [y, m] = latest.split('-').map(Number);
      next = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
    }
    const fields = [{ name: 'month', label: 'Month', type: 'month', value: next }];
    if (S.months.length) {
      fields.push({ name: 'copy_from', label: 'Copy setup from', type: 'select', value: latest,
        hint: 'Dwellers, rent, sides and bills carry over. Meals, bazar and payments start empty.',
        options: [...S.months.map(m => [m, monthName(m)]), ['', 'Nothing, start blank']] });
    }
    formSheet({
      title: 'Start a new month', submit: 'Create month', fields,
      onSubmit: async v => {
        await api('POST', 'months', v);
        go(v.month, v.copy_from ? 'bills' : 'dwellers');
        toast(v.copy_from ? "Month created. Check this month's bills." : 'Month created');
      },
    });
  },
  'delete-month'() {
    const ym = S.ym;
    confirmSheet({
      title: `Delete ${monthName(ym)}?`, confirm: 'Delete month',
      body: 'This permanently removes its meals, bazar, bills and payments. Other months stay as they are.',
      onConfirm: async () => {
        const { months } = await api('DELETE', `months/${ym}`);
        S.months = months;
        toast('Month deleted');
        if (months[0]) go(months[0], 'settings'); else { location.hash = ''; load().catch(showError); }
      },
    });
  },
  async 'add-member'() {
    formSheet({ title: 'Add dweller', submit: 'Add dweller', fields: await memberFields(),
      intro: `Joins ${monthName(S.ym)}. Shared bills are split again to include them.`,
      onSubmit: v => save(monthApi('POST', '/members', v), `${v.name} added`) });
  },
  async 'edit-member'(id) {
    const m = member(id);
    formSheet({ title: `Edit ${m.name}`, submit: 'Save', fields: await memberFields(m),
      onSubmit: v => save(monthApi('PUT', `/members/${id}`, v), 'Saved') });
  },
  'delete-member'(id) {
    const m = member(id), r = calcFor(id);
    const paid = S.d.payments.filter(p => p.member_id === id).length;
    confirmSheet({
      title: `Remove ${m.name} from ${monthName(S.ym)}?`, confirm: 'Remove dweller',
      body: `This also deletes their ${qty(r.meals)} meals, ${tk(r.bazar)} of bazar and ${paid} ${paid === 1 ? 'payment' : 'payments'} from this month, which changes everyone's share. Other months stay as they are.`,
      onConfirm: () => save(monthApi('DELETE', `/members/${id}`), `${m.name} removed`),
    });
  },
  'add-bazar': () => formSheet({ title: 'Add bazar', submit: 'Add', fields: bazarFields(),
    onSubmit: v => save(monthApi('POST', '/bazar', v), 'Bazar added') }),
  'edit-bazar'(id) {
    const b = S.d.bazar.find(x => x.id === id);
    formSheet({ title: 'Edit bazar', submit: 'Save', fields: bazarFields(b),
      onSubmit: v => save(monthApi('PUT', `/bazar/${id}`, v), 'Saved') });
  },
  'delete-bazar'(id) {
    const b = S.d.bazar.find(x => x.id === id);
    confirmSheet({ title: 'Delete this bazar entry?', body: `${b.item || 'Item'}, ${tk(b.amount)}, bought by ${member(b.member_id)?.name}.`,
      confirm: 'Delete', onConfirm: () => save(monthApi('DELETE', `/bazar/${id}`), 'Deleted') });
  },
  'bazar-of'(id) {
    S.bazarFilter = id;
    go(S.ym, 'bazar');
  },
  'bazar-filter'(id) {
    S.bazarFilter = id || null;
    const before = capture(view);
    render();
    glide(view, before);
  },
  'side-filter'(id) {
    S.sideFilter = id || null;
    const before = capture(view);
    render();
    glide(view, before);
    afterPaint(false);
  },
  'toggle-pay'(id, el) {
    const item = el.closest('.payitem');
    const open = !item.classList.contains('open');
    item.classList.toggle('open', open);
    el.setAttribute('aria-expanded', open);
    if (open) S.open.add(id); else S.open.delete(id);
  },
  async 'meal-step'(_, el) {
    const id = mineId(), day = Number(today().slice(8));
    const value = Math.max(0, (S.d.meals[id]?.[day] ?? 0) + Number(el.dataset.step));
    const output = document.getElementById('todayMeals');
    output.textContent = qty(value);
    pop(output);
    (S.d.meals[id] ??= {})[day] = value;
    mealSaves = mealSaves.then(async () => {
      try {
        S.d = await monthApi('PUT', '/meals', { member_id: id, day, qty: value });
        const cell = view.querySelector(`[data-m="${id}"][data-d="${day}"]`);
        if (cell) { cell.value = qty(value); cell.defaultValue = qty(value); delete cell.dataset.saved; }
        showMealTotals(id, day);
      } catch (err) { toast(err.message, true); await load(); }
    });
  },
  'add-bill': (_, el) => formSheet({ title: 'Add bill', submit: 'Add', fields: billFields(null, el.dataset.side),
    onSubmit: v => save(monthApi('POST', '/bills', v), 'Bill added') }),
  'edit-bill'(id) {
    const b = S.d.bills.find(x => x.id === id);
    formSheet({ title: `Edit ${b.name}`, submit: 'Save', fields: billFields(b),
      onSubmit: v => save(monthApi('PUT', `/bills/${id}`, v), 'Saved') });
  },
  'delete-bill'(id) {
    const b = S.d.bills.find(x => x.id === id);
    confirmSheet({ title: `Delete ${b.name}?`, body: `${tk(b.amount)} will come out of this month's split.`,
      confirm: 'Delete', onConfirm: () => save(monthApi('DELETE', `/bills/${id}`), 'Deleted') });
  },
  'add-side': () => formSheet({ title: 'Add side', submit: 'Add', fields: sideFields(),
    intro: 'A side is a set of dwellers who share their own bills.',
    onSubmit: v => save(monthApi('POST', '/sides', v), 'Side added') }),
  'edit-side'(id) {
    const s = side(id);
    formSheet({ title: `${s.name} side settings`, submit: 'Save', fields: sideFields(s),
      onSubmit: v => save(monthApi('PUT', `/sides/${id}`, v), 'Saved') });
  },
  'delete-side'(id) {
    const s = side(id);
    const count = S.d.bills.filter(b => b.side_id === id).length;
    confirmSheet({ title: `Delete ${s.name} side?`,
      body: `Its ${count} ${count === 1 ? 'bill' : 'bills'} will be deleted too. A side with dwellers can't be deleted.`,
      confirm: 'Delete side', onConfirm: () => save(monthApi('DELETE', `/sides/${id}`), 'Side deleted') });
  },
  'add-payment': () => formSheet({ title: 'Add payment', submit: 'Add', fields: paymentFields(),
    onSubmit: v => save(monthApi('POST', '/payments', v), 'Payment added') }),
  'edit-payment'(id) {
    const p = S.d.payments.find(x => x.id === id);
    formSheet({ title: 'Edit payment', submit: 'Save', fields: paymentFields(p),
      onSubmit: v => save(monthApi('PUT', `/payments/${id}`, v), 'Saved') });
  },
  'delete-payment'(id) {
    const p = S.d.payments.find(x => x.id === id);
    confirmSheet({ title: 'Delete this payment?', body: `${tk(p.amount)} from ${member(p.member_id)?.name}.`,
      confirm: 'Delete', onConfirm: () => save(monthApi('DELETE', `/payments/${id}`), 'Deleted') });
  },
  'make-admin'(id) {
    const a = S.users.find(x => x.id === id);
    confirmSheet({ title: `Make ${a.name} the admin?`, confirm: 'Make admin',
      body: 'There can be only one admin, so you will become a regular dweller and lose admin rights.',
      onConfirm: async () => { await api('POST', `users/${id}/make-admin`); location.reload(); } });
  },
  async 'approve-user'(id) {
    const person = S.users.find(u => u.id === id);
    const options = await api('GET', 'join-options');
    const listed = options.unclaimed.find(m => m.name.toLowerCase() === person.name.toLowerCase());
    const fields = options.ym ? [
      { name: 'who', label: 'Who is this?', type: 'select', value: listed?.id ?? 'new',
        hint: `They'll join ${monthName(options.ym)} and any past months under the same name.`,
        options: [['new', 'A new dweller'], ...options.unclaimed.map(m => [m.id, `Already listed as ${m.name}`])] },
      { name: 'side_id', label: 'Side', type: 'select', value: options.sides[0]?.id, options: options.sides.map(s => [s.id, s.name]) },
      { name: 'rent', label: 'Monthly rent (৳)', value: 0, inputmode: 'decimal' },
    ] : [];
    formSheet({
      title: `Approve ${person.name}?`, intro: `${person.username} · ${person.email}`, submit: 'Approve', fields,
      onOpen(form) {
        const who = form.elements.namedItem('who');
        if (!who) return;
        const sync = () => ['side_id', 'rent'].forEach(n => {
          form.elements.namedItem(n).closest('.field').hidden = who.value !== 'new';
        });
        who.addEventListener('change', sync);
        sync();
      },
      onSubmit: async v => {
        const body = v.who === 'new' || !v.who ? { side_id: v.side_id, rent: v.rent } : { member_id: v.who };
        const before = capture(view);
        noteAccounts(await api('POST', `users/${id}/approve`, body));
        S.d = S.ym ? await api('GET', `months/${S.ym}`) : null;
        render();
        glide(view, before);
        afterPaint(false);
        toast(`${person.name} approved`);
      },
    });
  },
  'decline-user'(id) {
    const person = S.users.find(u => u.id === id);
    confirmSheet({ title: `Decline ${person.name}?`, confirm: 'Decline',
      body: 'Their account will be deleted. They can ask again by creating a new one.',
      onConfirm: async () => {
        const before = capture(view);
        noteAccounts(await api('DELETE', `users/${id}`));
        render();
        glide(view, before);
        toast(`${person.name} declined`);
      } });
  },
  async 'admin-code'() {
    const { code } = await api('POST', 'admin-code');
    noteAccounts(await api('GET', 'users'));
    render();
    afterPaint(false);
    openSheet(`<div class="dlg"><h2 id="sheet-title">Admin code</h2>
      <p>Send this privately. It won't be shown again, and anyone who uses it becomes the admin.</p>
      <output class="code-box">${esc(code)}</output>
      <div class="actions"><button type="button" class="btn primary" data-close>Done</button></div></div>`);
  },
  async 'cancel-admin-code'() {
    await api('DELETE', 'admin-code');
    noteAccounts(await api('GET', 'users'));
    render();
    afterPaint(false);
    toast('Code cancelled');
  },
  'delete-user'(id) {
    const a = S.users.find(x => x.id === id);
    confirmSheet({ title: `Remove ${a.name}'s account?`, confirm: 'Remove account',
      body: 'They will no longer be able to sign in. Their meals, bazar and payments stay in the sheet.',
      onConfirm: async () => {
        const before = capture(view);
        noteAccounts(await api('DELETE', `users/${id}`));
        S.d = S.ym ? await api('GET', `months/${S.ym}`) : null;
        render();
        glide(view, before);
        toast('Account removed');
      } });
  },
  theme(_, el) {
    const choice = el.dataset.themeChoice;
    const apply = () => {
      try { if (choice === 'system') localStorage.removeItem('bb-theme'); else localStorage.setItem('bb-theme', choice); } catch { /* per-device only */ }
      if (choice === 'system') delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = choice;
    };
    pageChange(apply, 'theme');
    view.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', b === el));
    const seg = view.querySelector('.seg');
    slideTo(seg.querySelector('.thumb'), el);
  },
  async logout() {
    await api('POST', 'logout');
    location.href = '/login';
  },
};

let pendingDirection = 'none';

document.addEventListener('click', e => {
  const el = e.target.closest('[data-action]');
  if (!el || el.disabled) return;
  Promise.resolve(actions[el.dataset.action](Number(el.dataset.id) || 0, el)).catch(err => toast(err.message, true));
});
document.addEventListener('change', e => {
  if (e.target.id !== 'monthSelect') return;
  const moved = S.months.indexOf(e.target.value) - S.months.indexOf(S.ym);
  pendingDirection = moved > 0 ? 'right' : 'left';
  go(e.target.value, S.tab);
});
view.addEventListener('focusout', e => {
  if (e.target.matches('[data-meal]')) mealSaves = mealSaves.then(() => saveMeal(e.target));
});
view.addEventListener('focusin', e => { if (e.target.matches('[data-meal]') && !e.target.readOnly) e.target.select(); });
view.addEventListener('keydown', e => {
  if (!e.target.matches('[data-meal]')) return;
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter'].includes(e.key)) {
    e.preventDefault();
    moveInGrid(e.target, e.key);
  }
});
view.addEventListener('pointermove', e => {
  const chart = e.target.closest('.spark');
  if (!chart) return;
  const totals = JSON.parse(chart.dataset.days);
  const box = chart.getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
  const index = Math.round(ratio * (totals.length - 1));
  const left = index / Math.max(totals.length - 1, 1);
  const cursor = chart.querySelector('.cursor');
  cursor.setAttribute('x1', left * 600);
  cursor.setAttribute('x2', left * 600);
  const tip = chart.querySelector('.tip');
  tip.textContent = `Day ${index + 1}: ${qty(totals[index])} meals`;
  tip.style.left = `${Math.min(Math.max(left * 100, 12), 88)}%`;
});
addEventListener('hashchange', () => {
  const next = parseHash();
  let direction = pendingDirection;
  pendingDirection = 'none';
  if (direction === 'none' && next.tab !== S.tab) {
    const order = TABS.map(t => t[0]);
    direction = order.indexOf(next.tab) > order.indexOf(S.tab) ? 'left' : 'right';
  }
  load(direction).catch(showError);
});
addEventListener('resize', () => {
  [['rail', true], ['dock', false]].forEach(([id, vertical]) => {
    const box = document.getElementById(id);
    slideTo(box.querySelector('.nav-ind'), box.querySelector('[aria-current]'), vertical);
  });
});

async function boot() {
  const me = await api('GET', 'me');
  S.me = me.user;
  S.mess = me.mess_name;
  S.adminName = me.admin_name;
  S.pending = me.pending;
  await load();
  if (me.join) showJoin(me.join);
  if (isAdmin()) setInterval(() => { if (!document.hidden) watchRequests().catch(() => {}); }, 20000);
}

/** Tells the admin about new join requests while the app is open. */
async function watchRequests() {
  const { pending, user } = await api('GET', 'me');
  if (user.role !== S.me.role) { location.reload(); return; }   // someone took over as admin
  if (pending === S.pending) return;
  const more = pending > S.pending;
  if (['dwellers', 'settings'].includes(S.tab)) noteAccounts(await api('GET', 'users'));
  S.pending = pending;
  if (sheet.open) return;
  const before = capture(view);
  render();
  glide(view, before);
  afterPaint(false);
  if (more) toast('Someone is waiting to join');
}
boot().catch(showError);
