// Sign in, join, forgot password, reset password and the waiting screen.
import { reduced, slideTo } from './motion.js';

const card = document.getElementById('card');
const esc = v => String(v ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let mess = 'BlueBlood';
let hasAdmin = true;
let needsCode = true;

async function post(path, body) {
  const res = await fetch(`/api/${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Something went wrong. Try again.');
  return data;
}

const input = ({ name, label, type = 'text', hint, autocomplete, value = '' }) => `
  <label class="field">
    <span>${esc(label)}</span>
    <input name="${name}" type="${type}" value="${esc(value)}" autocomplete="${autocomplete || 'off'}"
      ${type === 'email' ? 'inputmode="email"' : ''} autocapitalize="off" spellcheck="false">
    ${hint ? `<small>${esc(hint)}</small>` : ''}
  </label>`;

const PERSON_FIELDS = [
  { name: 'name', label: 'Your name', autocomplete: 'name' },
  { name: 'username', label: 'Username', hint: 'Letters, numbers, dots or underscores', autocomplete: 'username' },
  { name: 'email', label: 'Email', type: 'email', hint: 'Used if you forget your password', autocomplete: 'email' },
  { name: 'password', label: 'Password', type: 'password', hint: 'At least 8 characters', autocomplete: 'new-password' },
];
const CODE_FIELD = input({ name: 'admin_code', label: 'Admin code', hint: 'A one-time code. Each code makes one person the admin.' });

const roleText = {
  dweller: { title: 'Join the mess', intro: () => `Ask to join ${mess}. The admin approves new accounts.`, submit: 'Ask to join' },
  admin: { title: 'Join as admin', intro: () => `You'll run ${mess}. The current admin becomes a dweller.`, submit: 'Join as admin' },
};

const SCREENS = {
  login: () => ({
    title: 'Welcome back',
    intro: `Sign in to ${mess}.`,
    fields: [
      { name: 'login', label: 'Username or email', autocomplete: 'username' },
      { name: 'password', label: 'Password', type: 'password', autocomplete: 'current-password' },
    ],
    submit: 'Sign in',
    foot: `<button type="button" class="linkish" data-go="forgot">Forgot password?</button>
           <p>New here? <button type="button" class="linkish" data-go="signup">Create an account</button></p>`,
    run: async v => { await post('login', v); location.href = '/'; },
  }),
  signup: () => ({
    title: roleText.dweller.title,
    intro: roleText.dweller.intro(),
    before: `<div class="seg wide" role="group" aria-label="Join as"><span class="thumb"></span>
        <button type="button" data-role="dweller" aria-pressed="true">Dweller</button>
        <button type="button" data-role="admin" aria-pressed="false">Admin</button></div>`,
    fields: PERSON_FIELDS,
    after: `<div class="code-fold"><div>${CODE_FIELD}</div></div>`,
    submit: roleText.dweller.submit,
    foot: `<p>Already have one? <button type="button" class="linkish" data-go="login">Sign in</button></p>`,
    run: async (v, form) => {
      await post('signup', { ...v, as_admin: form.dataset.join === 'admin' });
      location.href = '/';
    },
  }),
  setup: () => ({
    title: 'Set up your mess',
    intro: "You'll be the admin. Everyone else joins after this.",
    fields: [{ name: 'mess_name', label: 'Mess name', value: mess }, ...PERSON_FIELDS],
    after: needsCode ? CODE_FIELD : '',
    submit: 'Create mess',
    foot: `<p>Already have an account? <button type="button" class="linkish" data-go="login">Sign in</button></p>`,
    run: async v => { await post('signup', { ...v, as_admin: true }); location.href = '/'; },
  }),
  forgot: () => ({
    title: 'Forgot your password?',
    intro: "Enter your account's email and we'll send a reset link.",
    fields: [{ name: 'email', label: 'Email', type: 'email', autocomplete: 'email' }],
    submit: 'Send reset link',
    foot: `<button type="button" class="linkish" data-go="login">Back to sign in</button>`,
    run: async v => {
      const out = await post('forgot', v);
      show('sent', { devLink: out.dev_link });
    },
  }),
  reset: ({ token }) => ({
    title: 'Choose a new password',
    intro: 'This signs you out of every device.',
    fields: [
      { name: 'password', label: 'New password', type: 'password', hint: 'At least 8 characters', autocomplete: 'new-password' },
      { name: 'again', label: 'Type it again', type: 'password', autocomplete: 'new-password' },
    ],
    submit: 'Save new password',
    foot: `<button type="button" class="linkish" data-go="login">Back to sign in</button>`,
    run: async v => {
      if (v.password !== v.again) throw new Error("The passwords don't match");
      await post('reset', { token, password: v.password });
      history.replaceState(null, '', '/login');
      show('done');
    },
  }),
};

function panelHtml(screen) {
  return `<form class="auth-form" novalidate>
    <h2>${esc(screen.title)}</h2>
    <p class="intro">${esc(screen.intro)}</p>
    ${screen.before ?? ''}
    ${screen.fields.map(input).join('')}
    ${screen.after ?? ''}
    <div class="err" role="alert"></div>
    <button type="submit" class="btn primary wide">${esc(screen.submit)}</button>
    <div class="auth-foot">${screen.foot}</div>
  </form>`;
}

function messagePanel(title, body, extra = '') {
  return `<div class="auth-form">
    <div class="tick" aria-hidden="true"></div>
    <h2>${esc(title)}</h2><p class="intro">${esc(body)}</p>${extra}
    <div class="auth-foot"><button type="button" class="linkish" data-go="login">Back to sign in</button></div>
  </div>`;
}

/** Swaps the panel while the card smoothly changes height. */
function swap(html) {
  const from = card.offsetHeight;
  card.innerHTML = html;
  if (!reduced()) {
    const to = card.offsetHeight;
    if (from) card.animate([{ height: `${from}px` }, { height: `${to}px` }], { duration: 420, easing: 'cubic-bezier(.22,1,.36,1)' });
    [...card.firstElementChild.children].forEach((el, i) => el.animate(
      [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'none' }],
      { duration: 420, delay: 40 + i * 28, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' }));
  }
}

function setRole(form, role) {
  form.dataset.join = role;
  const text = roleText[role];
  form.querySelector('h2').textContent = text.title;
  form.querySelector('.intro').textContent = text.intro();
  form.querySelector('[type=submit]').textContent = text.submit;
  form.querySelector('.code-fold').classList.toggle('open', role === 'admin');
  form.querySelectorAll('[data-role]').forEach(b => b.setAttribute('aria-pressed', b.dataset.role === role));
  slideTo(form.querySelector('.thumb'), form.querySelector(`[data-role="${role}"]`));
}

function show(name, data = {}) {
  if (name === 'sent') {
    const dev = data.devLink
      ? `<div class="devnote"><b>Test build</b><p>Email isn't connected yet, so here is the link it would send.</p>
         <a class="btn wide" href="${esc(data.devLink)}">Open reset link</a></div>` : '';
    swap(messagePanel('Check your email', 'If that email has an account, a reset link is on its way. It works for one hour.', dev));
    return;
  }
  if (name === 'done') {
    swap(messagePanel('Password changed', 'You can sign in with your new password now.'));
    return;
  }
  const screen = SCREENS[name](data);
  swap(panelHtml(screen));
  const form = card.querySelector('form');
  if (form.querySelector('.seg')) {
    setRole(form, 'dweller');
    form.querySelector('.seg').addEventListener('click', e => {
      const role = e.target.closest('[data-role]')?.dataset.role;
      if (role) setRole(form, role);
    });
  }
  form.querySelector('input')?.select();
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = form.querySelector('[type=submit]');
    const err = form.querySelector('.err');
    const values = Object.fromEntries(new FormData(form).entries());
    err.textContent = '';
    btn.disabled = true;
    btn.classList.add('busy');
    try {
      await screen.run(values, form);
    } catch (error) {
      err.textContent = error.message;
      if (!reduced()) form.animate(
        [{ transform: 'translateX(0)' }, { transform: 'translateX(-7px)' }, { transform: 'translateX(6px)' },
          { transform: 'translateX(-3px)' }, { transform: 'translateX(0)' }], { duration: 340 });
      btn.disabled = false;
      btn.classList.remove('busy');
    }
  });
}

card.addEventListener('click', e => {
  const target = e.target.closest('[data-go]');
  if (!target) return;
  show(target.dataset.go === 'signup' && !hasAdmin ? 'setup' : target.dataset.go);
});

async function waiting() {
  const check = async () => {
    const res = await fetch('/api/me');
    if (res.status === 401) { location.href = '/login'; return null; }
    const me = await res.json();
    if (me.user.status === 'active') { location.href = '/'; return null; }
    return me;
  };
  const me = await check();
  if (!me) return;
  document.title = `Waiting · ${mess}`;
  swap(`<div class="auth-form">
    <div class="wait-drop" aria-hidden="true"></div>
    <h2>Almost in, ${esc(me.user.name)}</h2>
    <p class="intro">${esc(me.admin_name ?? 'The admin')} needs to approve your account. This page opens by itself once they do.</p>
    <div class="auth-foot"><button type="button" class="linkish" id="signOut">Sign out</button></div>
  </div>`);
  document.getElementById('signOut').addEventListener('click', async () => {
    await post('logout', {});
    location.href = '/login';
  });
  setInterval(() => { if (!document.hidden) check().catch(() => {}); }, 8000);
}

async function start() {
  const token = new URLSearchParams(location.search).get('token');
  try {
    const info = await fetch('/api/public').then(r => r.json());
    mess = info.mess_name;
    hasAdmin = info.has_admin;
    needsCode = info.needs_code;
    document.getElementById('messName').textContent = mess;
    document.title = `Sign in · ${mess}`;
  } catch { /* the default name still works */ }
  if (location.pathname === '/waiting') waiting();
  else if (location.pathname === '/reset' && token) show('reset', { token });
  else if (location.pathname === '/reset') swap(messagePanel('Link not valid', 'Ask for a new reset link and open it from the email.'));
  else show(hasAdmin ? 'login' : 'setup');
}
start();
