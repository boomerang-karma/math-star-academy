/**
 * BerrySharingGrove.js — subtraction, framed as kindness.
 *
 * Teaches: subtraction / decomposing numbers, "take away", remainder. A glowing
 * pile of berries sits in the grove; friendly animals ask for an exact amount.
 * The child drags berries into each animal's basket. When everyone is happy the
 * leftover berries glow and the take-away equation is revealed — "sharing makes
 * the garden happy", never "you lost some".
 */
import BaseGame from './BaseGame.js';
import { el, fromHTML, randInt, shuffle, pick } from '../core/dom.js';
import { makeDraggable } from '../core/drag.js';
import { berry, animal, ANIMAL_KINDS } from '../../assets/svg.js';

const NAMES = { bunny: 'Bella Bunny', squirrel: 'Sammy Squirrel', bird: 'Bibi Bird', hedgehog: 'Hattie Hedgehog' };

export default class BerrySharingGrove extends BaseGame {
  setupRound() {
    const lvl = this.level;
    this.total = randInt(Math.max(3, lvl.max - 3), lvl.max);
    const animalCount = lvl.animals || 1;

    // Decide each animal's request so the sum never exceeds the pile.
    this.requests = [];
    let remaining = this.total;
    const kinds = shuffle(ANIMAL_KINDS).slice(0, animalCount);
    kinds.forEach((kind, i) => {
      const last = i === animalCount - 1;
      const maxNeed = remaining - (animalCount - 1 - i); // leave ≥1 for each other animal
      const need = last ? randInt(1, Math.max(1, remaining - 1)) : randInt(1, Math.max(1, maxNeed - 1));
      remaining -= need;
      this.requests.push({ kind, need, got: 0 });
    });
    this.leftover = remaining;

    const totalNeed = this.requests.reduce((n, r) => n + r.need, 0);
    this.instruction =
      animalCount === 1
        ? `${NAMES[this.requests[0].kind]} would love ${this.requests[0].need} berries. Share them!`
        : `Share the berries so each friend gets exactly what they asked for!`;
    this.hint = `Drag berries to each basket. ${this.total} berries, give ${totalNeed} away.`;

    // ---- animals row ----
    const friends = el('div', { class: 'friends' });
    this.requests.forEach((req) => {
      req.basket = el('div', { class: 'animal-basket', aria: { label: `${req.kind} basket` } });
      req.countEl = el('div', { class: 'ab-count', text: `0/${req.need}` });
      req.basket.append(req.countEl);
      const bubble = el('div', { class: 'animal-bubble', text: `${req.need} please! 🫐` });
      const av = el('div', { class: 'animal-avatar', html: animal(req.kind) });
      req.card = el('div', { class: 'friend' }, [bubble, av, req.basket]);
      friends.append(req.card);
    });

    // ---- berry pile ----
    this.pile = el('div', { class: 'berry-pile' });
    this.berries = [];
    for (let i = 0; i < this.total; i++) {
      const c = pick(['#c1121f', '#7b2cbf', '#3a86ff', '#e5383b']);
      const b = el('button', { class: 'berry pop-in', style: { animationDelay: i * 40 + 'ms' }, aria: { label: 'berry' }, html: berry(c) });
      this._makeBerryInteractive(b);
      this.berries.push(b);
      this.pile.append(b);
    }

    this.stage.append(friends, el('div', { class: 'pile-label', text: `${this.total} juicy berries` }), this.pile);
  }

  _openBaskets() {
    return this.requests.filter((r) => r.got < r.need).map((r) => ({ el: r.basket, pad: 30, req: r }));
  }

  _makeBerryInteractive(b) {
    this.track(
      makeDraggable(b, {
        disabled: () => this.locked,
        dropZones: () => this._openBaskets(),
        onPickup: () => this.ctx.audio.tap(),
        onDrop: (node, zone) => {
          if (zone.req) {
            this._give(b, zone.req);
            return true;
          }
          return false;
        },
      })
    );
    b.addEventListener('click', () => {
      const open = this.requests.find((r) => r.got < r.need);
      if (open) this._give(b, open);
    });
  }

  _give(b, req) {
    if (this.locked || b.classList.contains('given') || req.got >= req.need) return;
    b.classList.add('given');
    req.got += 1;
    req.countEl.textContent = `${req.got}/${req.need}`;

    const from = b.getBoundingClientRect();
    const clone = fromHTML(b.querySelector('svg').outerHTML);
    clone.classList.add('fly-clone');
    Object.assign(clone.style, { left: from.left + 'px', top: from.top + 'px', width: from.width + 'px' });
    document.body.append(clone);
    b.style.visibility = 'hidden';
    const to = req.basket.getBoundingClientRect();
    requestAnimationFrame(() => {
      clone.style.transform = `translate(${to.left + to.width / 2 - from.left - from.width / 2}px, ${to.top - from.top}px) scale(.6)`;
    });
    setTimeout(() => {
      clone.remove();
      const mini = fromHTML(b.querySelector('svg').outerHTML);
      mini.classList.add('basket-berry');
      req.basket.append(mini);
      this.ctx.audio.pop();
      if (req.got === req.need) {
        req.card.classList.add('happy');
        this.ctx.audio.chime();
        this.ctx.lumi.say(`${NAMES[req.kind]} says thank you! 💕`, { pose: 'cheer', hold: 2000 });
        if (this.requests.every((r) => r.got >= r.need)) setTimeout(() => this._finishShare(), 700);
      }
    }, 330);
  }

  _finishShare() {
    // Highlight the berries left in the pile.
    const left = this.berries.filter((b) => !b.classList.contains('given'));
    left.forEach((b) => b.classList.add('leftover-glow'));
    const totalNeed = this.total - this.leftover;

    const eq = el('div', { class: 'equation share-eq' }, [
      el('b', { text: String(this.total) }),
      el('span', { text: '−' }),
      el('b', { text: String(totalNeed) }),
      el('span', { text: '=' }),
      el('b', { class: 'eq-sum solved', text: String(this.leftover) }),
    ]);
    this.stage.append(eq);
    const berriesWord = this.leftover === 1 ? 'berry' : 'berries';
    const msg = this.leftover === 0 ? `You shared them all! So kind! 💖` : `${this.leftover} ${berriesWord} left for you! Sharing is caring! 🐰`;
    const r = this.pile.getBoundingClientRect();
    this.solved({ point: { x: r.left + r.width / 2, y: r.top + 20 }, message: msg });
  }
}
