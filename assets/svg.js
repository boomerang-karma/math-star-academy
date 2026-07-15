/**
 * svg.js — Inline SVG art library for Lumi's Math Garden.
 *
 * Everything the game draws lives here as small pure functions that return
 * SVG markup strings. Keeping art inline (no external files) makes the whole
 * app offline-first and COPPA-safe: nothing is ever fetched from a network.
 *
 * Each object family (flowers, fruit, animals, shapes…) is a factory keyed by
 * variant so games can ask for e.g. `manipulative('ladybug')` without caring
 * how it is drawn. Add a new critter by adding one entry here.
 */

/* ------------------------------------------------------------------ *
 * Lumi — the glowing pixie mascot. Pose changes her arms/expression.  *
 * ------------------------------------------------------------------ */
export function lumi(pose = 'idle') {
  const eyes =
    pose === 'cheer'
      ? '<path d="M40 46 q4 -6 8 0" stroke="#5b3b8c" stroke-width="2.4" fill="none" stroke-linecap="round"/><path d="M56 46 q4 -6 8 0" stroke="#5b3b8c" stroke-width="2.4" fill="none" stroke-linecap="round"/>'
      : '<circle cx="44" cy="47" r="4.2" fill="#4a2f73"/><circle cx="60" cy="47" r="4.2" fill="#4a2f73"/><circle cx="45.4" cy="45.6" r="1.4" fill="#fff"/><circle cx="61.4" cy="45.6" r="1.4" fill="#fff"/>';
  const mouth =
    pose === 'think'
      ? '<circle cx="52" cy="57" r="2.6" fill="#c65b8a"/>'
      : '<path d="M46 55 q6 8 12 0" stroke="#c65b8a" stroke-width="2.6" fill="none" stroke-linecap="round"/>';
  const leftArm =
    pose === 'point'
      ? '<path d="M30 66 q-16 -4 -24 -14" stroke="#ffd9b0" stroke-width="6" fill="none" stroke-linecap="round"/>'
      : pose === 'cheer'
        ? '<path d="M30 62 q-12 -14 -14 -26" stroke="#ffd9b0" stroke-width="6" fill="none" stroke-linecap="round"/>'
        : '<path d="M32 66 q-10 4 -12 14" stroke="#ffd9b0" stroke-width="6" fill="none" stroke-linecap="round"/>';
  const rightArm =
    pose === 'cheer'
      ? '<path d="M72 62 q12 -14 14 -26" stroke="#ffd9b0" stroke-width="6" fill="none" stroke-linecap="round"/>'
      : '<path d="M70 66 q10 4 12 14" stroke="#ffd9b0" stroke-width="6" fill="none" stroke-linecap="round"/>';

  return `
  <svg class="lumi-svg" viewBox="0 0 104 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <defs>
      <radialGradient id="lumiGlow" cx="50%" cy="45%" r="55%">
        <stop offset="0%" stop-color="#fff6d8" stop-opacity="0.95"/>
        <stop offset="55%" stop-color="#ffd6f2" stop-opacity="0.45"/>
        <stop offset="100%" stop-color="#e0aaff" stop-opacity="0"/>
      </radialGradient>
      <linearGradient id="lumiWing" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#bde0fe" stop-opacity="0.9"/>
        <stop offset="100%" stop-color="#e0aaff" stop-opacity="0.55"/>
      </linearGradient>
      <linearGradient id="lumiHair" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#ffb3d9"/>
        <stop offset="100%" stop-color="#c77dff"/>
      </linearGradient>
    </defs>
    <circle cx="52" cy="58" r="52" fill="url(#lumiGlow)"/>
    <!-- wings -->
    <g class="lumi-wings">
      <ellipse cx="30" cy="60" rx="20" ry="30" fill="url(#lumiWing)" transform="rotate(-18 30 60)"/>
      <ellipse cx="74" cy="60" rx="20" ry="30" fill="url(#lumiWing)" transform="rotate(18 74 60)"/>
    </g>
    <!-- body / apron -->
    <path d="M40 70 q12 18 24 0 l-2 22 q-10 8 -20 0 z" fill="#8ac926"/>
    <path d="M45 72 h14 l-2 18 h-10 z" fill="#a7e34f"/>
    ${leftArm}
    ${rightArm}
    <!-- head -->
    <circle cx="52" cy="48" r="22" fill="#ffe3c4"/>
    <!-- hair -->
    <path d="M30 44 q-2 -24 22 -26 q24 2 22 26 q-8 -12 -22 -12 q-14 0 -22 12z" fill="url(#lumiHair)"/>
    <circle cx="34" cy="34" r="4" fill="#ff8fab"/>
    <circle cx="70" cy="34" r="4" fill="#ffd166"/>
    <circle cx="52" cy="24" r="4.5" fill="#ff8fab"/>
    <!-- face -->
    ${eyes}
    ${mouth}
    <circle cx="38" cy="53" r="3.4" fill="#ffb3c6" opacity="0.7"/>
    <circle cx="66" cy="53" r="3.4" fill="#ffb3c6" opacity="0.7"/>
    <!-- sparkles -->
    <path class="lumi-spark" d="M86 30 l2 5 l5 2 l-5 2 l-2 5 l-2 -5 l-5 -2 l5 -2 z" fill="#fff4b8"/>
    <path class="lumi-spark" d="M14 44 l1.5 4 l4 1.5 l-4 1.5 l-1.5 4 l-1.5 -4 l-4 -1.5 l4 -1.5 z" fill="#fff4b8"/>
  </svg>`;
}

/* ------------------------------------------------------------------ *
 * Manipulatives — the little countable objects children drag & tap.   *
 * ------------------------------------------------------------------ */
const MANIPULATIVES = {
  ladybug: () => `
    <ellipse cx="32" cy="34" rx="22" ry="18" fill="#e63946"/>
    <path d="M32 16 v36" stroke="#3a0d0d" stroke-width="2.5"/>
    <path d="M32 16 a22 18 0 0 0 -22 18 a22 18 0 0 0 22 18 z" fill="#e63946"/>
    <circle cx="20" cy="28" r="3.4" fill="#2b0a0a"/><circle cx="24" cy="40" r="3" fill="#2b0a0a"/>
    <circle cx="44" cy="28" r="3.4" fill="#2b0a0a"/><circle cx="40" cy="40" r="3" fill="#2b0a0a"/>
    <circle cx="32" cy="14" r="9" fill="#2b0a0a"/>
    <circle cx="28" cy="12" r="2" fill="#fff"/><circle cx="36" cy="12" r="2" fill="#fff"/>`,
  seed: () => `
    <ellipse cx="32" cy="34" rx="13" ry="20" fill="#c98a4b"/>
    <path d="M32 16 q9 18 0 36 q-9 -18 0 -36z" fill="#e6b877"/>
    <path d="M32 20 v28" stroke="#8a5a2b" stroke-width="1.6"/>`,
  flower: (c = '#ff8fab') => `
    <g>
      ${[0, 72, 144, 216, 288].map((a) => `<ellipse cx="32" cy="16" rx="8" ry="13" fill="${c}" transform="rotate(${a} 32 34)"/>`).join('')}
      <circle cx="32" cy="34" r="9" fill="#ffd166"/>
    </g>`,
  butterfly: (c = '#b28dff') => `
    <path d="M32 34 q-20 -22 -26 -2 q-4 16 24 6z" fill="${c}"/>
    <path d="M32 34 q20 -22 26 -2 q4 16 -24 6z" fill="${c}"/>
    <path d="M32 34 q-16 20 -20 4 q0 -12 20 -4z" fill="${c}" opacity="0.85"/>
    <path d="M32 34 q16 20 20 4 q0 -12 -20 -4z" fill="${c}" opacity="0.85"/>
    <ellipse cx="32" cy="34" rx="3.6" ry="14" fill="#5b3b8c"/>
    <path d="M30 20 q-4 -8 -8 -8 M34 20 q4 -8 8 -8" stroke="#5b3b8c" stroke-width="1.6" fill="none"/>`,
  leaf: () => `
    <path d="M14 50 Q32 4 54 18 Q48 52 14 50z" fill="#52b788"/>
    <path d="M18 46 Q34 24 48 22" stroke="#2d6a4f" stroke-width="2" fill="none"/>`,
  acorn: () => `
    <ellipse cx="32" cy="40" rx="15" ry="17" fill="#b5651d"/>
    <path d="M16 30 a16 9 0 0 1 32 0 z" fill="#7a4419"/>
    <rect x="30" y="12" width="4" height="10" rx="2" fill="#7a4419"/>`,
  mushroom: () => `
    <rect x="26" y="34" width="12" height="20" rx="6" fill="#ffe8d6"/>
    <path d="M12 36 a20 16 0 0 1 40 0 z" fill="#ef476f"/>
    <circle cx="24" cy="28" r="3" fill="#fff"/><circle cx="40" cy="30" r="2.4" fill="#fff"/><circle cx="32" cy="22" r="2.4" fill="#fff"/>`,
};

/* ------------------------------------------------------------------ *
 * Fruit — for the Addition Orchard.                                   *
 * ------------------------------------------------------------------ */
const FRUIT = {
  apple: () => `<circle cx="32" cy="36" r="18" fill="#ef476f"/><path d="M32 20 q2 -8 10 -8" stroke="#6a4a2b" stroke-width="3" fill="none" stroke-linecap="round"/><ellipse cx="42" cy="14" rx="6" ry="3.5" fill="#52b788" transform="rotate(-20 42 14)"/><ellipse cx="26" cy="30" rx="5" ry="7" fill="#fff" opacity="0.35"/>`,
  orange: () => `<circle cx="32" cy="36" r="18" fill="#ff9f1c"/><circle cx="32" cy="18" r="3" fill="#52b788"/><ellipse cx="26" cy="30" rx="4" ry="6" fill="#fff" opacity="0.3"/>`,
  pear: () => `<path d="M32 12 q6 8 6 14 q10 6 8 18 q-2 12 -14 12 q-12 0 -14 -12 q-2 -12 8 -18 q0 -6 6 -14z" fill="#c5d86d"/><path d="M32 12 q1 -4 4 -5" stroke="#6a4a2b" stroke-width="2.6" fill="none" stroke-linecap="round"/>`,
  plum: () => `<circle cx="32" cy="36" r="17" fill="#9d4edd"/><path d="M32 20 v20" stroke="#6a2fb0" stroke-width="1.6"/><ellipse cx="26" cy="30" rx="4" ry="6" fill="#fff" opacity="0.25"/>`,
  peach: () => `<circle cx="32" cy="37" r="17" fill="#ffb3a7"/><path d="M32 22 v16" stroke="#e07a5f" stroke-width="1.6"/><ellipse cx="38" cy="16" rx="6" ry="3" fill="#52b788" transform="rotate(20 38 16)"/>`,
};

/* Glowing berries for the Sharing Grove. */
export function berry(c = '#c1121f') {
  return `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <circle cx="32" cy="36" r="16" fill="${c}"/>
    <circle cx="32" cy="36" r="16" fill="#fff" opacity="0.12"/>
    <ellipse cx="26" cy="30" rx="4" ry="6" fill="#fff" opacity="0.5"/>
    <path d="M32 20 q-2 -8 -10 -9 M32 20 q2 -8 10 -9" stroke="#2d6a4f" stroke-width="2.4" fill="none" stroke-linecap="round"/>
  </svg>`;
}

/* ------------------------------------------------------------------ *
 * Animals — the friendly berry-sharing friends.                       *
 * ------------------------------------------------------------------ */
const ANIMALS = {
  bunny: () => `
    <ellipse cx="40" cy="58" rx="26" ry="22" fill="#f4f1de"/>
    <ellipse cx="30" cy="26" rx="7" ry="20" fill="#f4f1de"/><ellipse cx="30" cy="26" rx="3" ry="14" fill="#ffb3c6"/>
    <ellipse cx="50" cy="26" rx="7" ry="20" fill="#f4f1de"/><ellipse cx="50" cy="26" rx="3" ry="14" fill="#ffb3c6"/>
    <circle cx="32" cy="54" r="3.4" fill="#3a3a3a"/><circle cx="48" cy="54" r="3.4" fill="#3a3a3a"/>
    <path d="M40 60 v4 M40 64 q-4 3 -8 1 M40 64 q4 3 8 1" stroke="#c98aa6" stroke-width="2" fill="none" stroke-linecap="round"/>
    <ellipse cx="40" cy="60" rx="3" ry="2.4" fill="#ff8fab"/>`,
  squirrel: () => `
    <path d="M62 60 q22 -6 12 -30 q-8 -16 -18 4 q10 6 6 26z" fill="#bc6c25"/>
    <ellipse cx="40" cy="58" rx="24" ry="20" fill="#dda15e"/>
    <ellipse cx="40" cy="70" rx="14" ry="10" fill="#faedcd"/>
    <circle cx="30" cy="30" r="8" fill="#dda15e"/><circle cx="50" cy="30" r="8" fill="#dda15e"/>
    <circle cx="33" cy="54" r="3.2" fill="#3a2a1a"/><circle cx="47" cy="54" r="3.2" fill="#3a2a1a"/>
    <circle cx="40" cy="60" r="3" fill="#3a2a1a"/>`,
  bird: () => `
    <ellipse cx="40" cy="54" rx="24" ry="20" fill="#48cae4"/>
    <circle cx="40" cy="34" r="15" fill="#48cae4"/>
    <path d="M55 36 l14 -4 l-12 10z" fill="#ffb703"/>
    <circle cx="36" cy="32" r="3.4" fill="#03252e"/><circle cx="37" cy="31" r="1.2" fill="#fff"/>
    <path d="M20 56 q-14 2 -16 12 q16 -2 20 -6z" fill="#0096c7"/>
    <path d="M28 74 l4 8 M40 76 l0 8 M52 74 l-4 8" stroke="#ffb703" stroke-width="3" stroke-linecap="round"/>`,
  hedgehog: () => `
    <path d="M14 58 q0 -26 32 -26 q26 0 30 24 z" fill="#8d6e63"/>
    ${Array.from({ length: 9 }).map((_, i) => `<path d="M${16 + i * 6} 40 l3 -14 l3 14z" fill="#5d4037"/>`).join('')}
    <ellipse cx="58" cy="56" rx="18" ry="12" fill="#d7ccc8"/>
    <circle cx="70" cy="52" r="3.4" fill="#3a2a1a"/>
    <circle cx="74" cy="56" r="3" fill="#3a2a1a"/>`,
};

/* ------------------------------------------------------------------ *
 * Geometric shapes — Shape Grove. Returned as bare <svg> tiles.       *
 * ------------------------------------------------------------------ */
export function shape(kind, color = '#ff8fab', opts = {}) {
  const stroke = opts.outline ? `fill="none" stroke="${color}" stroke-width="4" stroke-dasharray="7 6"` : `fill="${color}"`;
  const body = {
    circle: `<circle cx="40" cy="40" r="30" ${stroke}/>`,
    square: `<rect x="12" y="12" width="56" height="56" rx="6" ${stroke}/>`,
    triangle: `<path d="M40 8 L72 68 L8 68 Z" ${stroke}/>`,
    rectangle: `<rect x="6" y="20" width="68" height="40" rx="6" ${stroke}/>`,
    oval: `<ellipse cx="40" cy="40" rx="34" ry="24" ${stroke}/>`,
    star: `<path d="M40 6 L49 30 L75 30 L54 46 L62 72 L40 56 L18 72 L26 46 L5 30 L31 30 Z" ${stroke}/>`,
    heart: `<path d="M40 68 C4 44 14 14 40 30 C66 14 76 44 40 68 Z" ${stroke}/>`,
    hexagon: `<path d="M22 12 H58 L74 40 L58 68 H22 L6 40 Z" ${stroke}/>`,
  }[kind] || `<circle cx="40" cy="40" r="30" ${stroke}/>`;
  return `<svg viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${body}</svg>`;
}

/* ------------------------------------------------------------------ *
 * Scenery used to decorate the garden map & win screens.              *
 * ------------------------------------------------------------------ */
export const scenery = {
  tree: (scale = 1) => `<svg viewBox="0 0 120 140" style="transform:scale(${scale})" aria-hidden="true">
    <rect x="52" y="86" width="16" height="46" rx="6" fill="#8a5a2b"/>
    <circle cx="60" cy="60" r="42" fill="#52b788"/>
    <circle cx="34" cy="72" r="26" fill="#40916c"/>
    <circle cx="86" cy="72" r="26" fill="#40916c"/>
    <circle cx="60" cy="44" r="30" fill="#74c69d"/>
  </svg>`,
  cloud: () => `<svg viewBox="0 0 160 80" aria-hidden="true"><g fill="#ffffff" opacity="0.9"><circle cx="50" cy="46" r="26"/><circle cx="86" cy="38" r="32"/><circle cx="120" cy="48" r="24"/><rect x="46" y="46" width="80" height="26" rx="13"/></g></svg>`,
  sun: () => `<svg viewBox="0 0 120 120" aria-hidden="true"><g stroke="#ffd166" stroke-width="6" stroke-linecap="round">${Array.from({ length: 12 }).map((_, i) => { const a = (i * 30 * Math.PI) / 180; return `<line x1="${60 + Math.cos(a) * 40}" y1="${60 + Math.sin(a) * 40}" x2="${60 + Math.cos(a) * 54}" y2="${60 + Math.sin(a) * 54}"/>`; }).join('')}</g><circle cx="60" cy="60" r="34" fill="#ffd84d"/></svg>`,
  sparkle: (c = '#fff4b8') => `<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M20 2 L24 16 L38 20 L24 24 L20 38 L16 24 L2 20 L16 16 Z" fill="${c}"/></svg>`,
  basket: () => `<svg viewBox="0 0 160 120" aria-hidden="true"><path d="M20 44 h120 l-14 66 a10 10 0 0 1 -10 8 H44 a10 10 0 0 1 -10 -8 z" fill="#c68b59"/><path d="M20 44 h120 l-14 66 a10 10 0 0 1 -10 8 H44 a10 10 0 0 1 -10 -8 z" fill="url(#weave)"/><defs><pattern id="weave" width="16" height="16" patternUnits="userSpaceOnUse"><path d="M0 8 h16 M8 0 v16" stroke="#a56a3a" stroke-width="3"/></pattern></defs><path d="M18 44 q62 -40 124 0" fill="none" stroke="#a56a3a" stroke-width="10" stroke-linecap="round"/><rect x="12" y="40" width="136" height="14" rx="7" fill="#a56a3a"/></svg>`,
  pot: () => `<svg viewBox="0 0 140 130" aria-hidden="true"><path d="M28 54 h84 l-10 60 a8 8 0 0 1 -8 6 H46 a8 8 0 0 1 -8 -6 z" fill="#b56576"/><ellipse cx="70" cy="54" rx="46" ry="12" fill="#6d597a"/><ellipse cx="70" cy="52" rx="38" ry="8" fill="#355070"/></svg>`,
};

/* ------------------------------------------------------------------ *
 * Public factories. Each wraps the raw <path> art in a sized <svg>.   *
 * ------------------------------------------------------------------ */
function wrap(inner, vb = '0 0 64 64') {
  return `<svg viewBox="${vb}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">${inner}</svg>`;
}
export function manipulative(kind, color) {
  const fn = MANIPULATIVES[kind] || MANIPULATIVES.flower;
  return wrap(fn(color));
}
export function fruit(kind) {
  const fn = FRUIT[kind] || FRUIT.apple;
  return wrap(fn());
}
export function animal(kind) {
  const fn = ANIMALS[kind] || ANIMALS.bunny;
  return wrap(fn(), '0 0 80 90');
}

export const MANIPULATIVE_KINDS = Object.keys(MANIPULATIVES);
export const FRUIT_KINDS = Object.keys(FRUIT);
export const ANIMAL_KINDS = Object.keys(ANIMALS);
export const SHAPE_KINDS = ['circle', 'square', 'triangle', 'rectangle', 'oval', 'star', 'heart', 'hexagon'];
