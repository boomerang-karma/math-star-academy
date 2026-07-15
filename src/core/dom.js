/**
 * dom.js — a 40-line DOM micro-helper.
 *
 * We deliberately avoid a UI framework: the app is small, must run with no
 * build step, and children's activities are mostly imperative (spawn 7
 * ladybugs, animate them, tear them down). `el()` covers 95% of needs.
 */

/** Create an element. `spec` may set className, text, html, attrs, dataset,
 *  style, events (on*), and children. */
export function el(tag, spec = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(spec)) {
    if (v == null) continue;
    if (k === 'class' || k === 'className') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'aria' && typeof v === 'object') for (const [a, av] of Object.entries(v)) node.setAttribute(`aria-${a}`, av);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

/** Build a node from an HTML string (used for our inline SVG art). */
export function fromHTML(html) {
  const t = el('div', { html });
  return t.firstElementChild;
}

/** querySelector shorthand scoped to a root (defaults to document). */
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Remove all children of a node. */
export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/** Promise that resolves after `ms`, honouring reduced-motion (caller decides). */
export const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** Clamp helper used all over the games. */
export const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));

/** Fisher–Yates shuffle (returns a new array). */
export function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/** Random integer in [lo, hi] inclusive. */
export const randInt = (lo, hi) => lo + Math.floor(Math.random() * (hi - lo + 1));

/** Pick a random element. */
export const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
