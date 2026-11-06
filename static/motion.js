// Animation helpers. Everything here respects "reduce motion" and only moves
// transform and opacity, which browsers can animate without repainting the page.

export const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

const FLUID = 'cubic-bezier(.22, 1, .36, 1)';
const SPRING = CSS.supports('transition-timing-function', 'linear(0, 1)')
  ? 'linear(0, .012, .05 2.4%, .2 5.6%, .82 15.4%, 1.02 20.5%, 1.09 24.8%, 1.11 28.8%, 1.09 33.5%, 1.01 45%, .99 53%, 1)'
  : FLUID;

const still = () => reduced() || document.hidden;

/** Fades and lifts children in, one after another. */
export function stagger(root, selector = '[data-in]') {
  if (still()) return;
  [...root.querySelectorAll(selector)].slice(0, 14).forEach((el, i) => {
    el.animate(
      [{ opacity: 0, transform: 'translateY(14px) scale(.985)' }, { opacity: 1, transform: 'none' }],
      { duration: 520, delay: i * 42, easing: FLUID, fill: 'backwards' });
  });
}

/** Runs a page change, sliding in the direction the person moved. */
export function pageChange(update, direction = 'none') {
  if (still() || !document.startViewTransition) { update(); return Promise.resolve(); }
  document.documentElement.dataset.dir = direction;
  let ran = false;
  const once = () => { if (!ran) { ran = true; update(); } };
  const change = document.startViewTransition(once);
  change.ready.catch(() => {});     // a newer page change cancelled this one's animation
  // The browser runs `once` on its next frame, which never comes on a page that
  // isn't being drawn, so the update must not depend on it.
  return Promise.race([change.updateCallbackDone,
    new Promise(resolve => { setTimeout(() => { once(); resolve(); }, 300); })]);
}

/** Smoothly runs a number from one value to another. */
export function countTo(el, from, to, format, duration = 750) {
  if (still() || from === to) { el.textContent = format(to); return; }
  const start = performance.now();
  const step = now => {
    if (!el.isConnected) return;
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - (1 - t) ** 4;
    el.textContent = format(from + (to - from) * eased);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/** Notes where every keyed item is, ready for glide(). */
export function capture(root) {
  const map = new Map();
  root.querySelectorAll('[data-k]').forEach(el => map.set(el.dataset.k, { el, rect: el.getBoundingClientRect() }));
  return map;
}

/** After a re-render: moved items glide, new ones grow in, removed ones melt away. */
export function glide(root, before) {
  if (still()) return;
  const seen = new Set();
  root.querySelectorAll('[data-k]').forEach(el => {
    const key = el.dataset.k;
    seen.add(key);
    const old = before.get(key);
    const rect = el.getBoundingClientRect();
    if (!old) {
      el.animate(
        [{ opacity: 0, transform: 'scale(.94)', background: 'var(--flash)' },
          { opacity: 1, transform: 'none', background: 'var(--flash)', offset: .5 },
          { opacity: 1, transform: 'none' }],
        { duration: 760, easing: FLUID });
    } else {
      const dx = old.rect.left - rect.left, dy = old.rect.top - rect.top;
      if ((dx || dy) && Math.abs(dy) < innerHeight) {
        el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }],
          { duration: 460, easing: FLUID });
      }
    }
  });
  for (const [key, { el, rect }] of before) {
    if (seen.has(key) || rect.bottom < 0 || rect.top > innerHeight) continue;
    const ghost = el.cloneNode(true);
    ghost.removeAttribute('data-k');
    ghost.querySelectorAll('[data-k]').forEach(n => n.removeAttribute('data-k'));
    Object.assign(ghost.style, {
      position: 'fixed', left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`,
      height: `${rect.height}px`, margin: 0, zIndex: 40, pointerEvents: 'none',
    });
    document.body.append(ghost);
    ghost.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'scale(.92) translateX(24px)' }],
      { duration: 340, easing: 'ease-in', fill: 'forwards' }).finished.finally(() => ghost.remove());
  }
}

/** A quick squash and rebound, used when a value changes. */
export function pop(el) {
  if (still() || !el) return;
  el.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.22)' }, { transform: 'scale(1)' }],
    { duration: 380, easing: SPRING });
}

/** Moves a sliding highlight onto the active item of a menu. */
export function slideTo(indicator, target, vertical) {
  if (!indicator || !target) return;
  const box = target.getBoundingClientRect();
  const parent = indicator.parentElement.getBoundingClientRect();
  indicator.style.setProperty('--x', `${box.left - parent.left}px`);
  indicator.style.setProperty('--y', `${box.top - parent.top}px`);
  indicator.style.setProperty('--w', `${box.width}px`);
  indicator.style.setProperty('--h', `${box.height}px`);
  indicator.classList.toggle('vertical', vertical);
}

/** Draws an SVG line from start to end. */
export function drawLine(path) {
  if (still() || !path) return;
  const length = path.getTotalLength();
  path.animate([{ strokeDasharray: length, strokeDashoffset: length }, { strokeDasharray: length, strokeDashoffset: 0 }],
    { duration: 1100, easing: FLUID });
}

/** Grows bars from zero. */
export function growBars(root) {
  if (still()) return;
  root.querySelectorAll('[data-bar]').forEach((el, i) => {
    el.animate([{ transform: 'scaleX(0)' }, { transform: 'none' }],
      { duration: 800, delay: i * 35, easing: FLUID, fill: 'backwards' });
  });
}
