/**
 * AdditionOrchard.js — "Combine the Harvest"
 *
 * Teaches: addition as combining (composing numbers), sums 1–20. Two trees
 * bear fruit; the child drags (or taps) every fruit into the central magic pot.
 * The running total grows with each fruit, an equation builds underneath, and
 * on later levels Lumi hops along a number line to the sum.
 */
import BaseGame from './BaseGame.js';
import { el, fromHTML, randInt, pick } from '../core/dom.js';
import { makeDraggable } from '../core/drag.js';
import { fruit, scenery, FRUIT_KINDS } from '../../assets/svg.js';

export default class AdditionOrchard extends BaseGame {
  setupRound() {
    const max = this.level.max;
    this.a = randInt(1, Math.max(1, max - 1));
    this.b = randInt(1, Math.max(1, max - this.a));
    this.sum = this.a + this.b;
    this.count = 0;
    this.fruitKind = pick(FRUIT_KINDS);

    this.instruction = `Drop all the fruit into the magic pot to add them up!`;
    this.hint = `First tree has ${this.a}, second has ${this.b}. Move them all into the pot and count!`;

    // ---- pot (drop target) ----
    this.pot = el('div', { class: 'magic-pot', html: scenery.pot() });
    this.potFill = el('div', { class: 'pot-fill' });
    this.pot.append(this.potFill);
    this.potCount = el('div', { class: 'pot-count', text: '0' });
    this.pot.append(this.potCount);

    // ---- two trees ----
    this.leftTree = this._buildTree(this.a, 'left');
    this.rightTree = this._buildTree(this.b, 'right');

    // ---- equation ----
    this.eq = el('div', { class: 'equation' }, [
      el('b', { text: String(this.a) }),
      el('span', { text: '+' }),
      el('b', { text: String(this.b) }),
      el('span', { text: '=' }),
      el('b', { class: 'eq-sum', text: '?' }),
    ]);

    const orchard = el('div', { class: 'orchard' }, [this.leftTree, this.pot, this.rightTree]);
    this.stage.append(orchard, this.eq);

    if (this.level.numberLine) {
      this.numberLine = this._buildNumberLine(this.level.max);
      this.stage.append(this.numberLine);
    }
  }

  _buildTree(n, side) {
    const canopy = el('div', { class: 'tree-canopy', html: scenery.tree() });
    const fruits = el('div', { class: 'tree-fruits' });
    for (let i = 0; i < n; i++) {
      const f = el('button', {
        class: 'fruit pop-in',
        style: { animationDelay: i * 70 + 'ms' },
        aria: { label: this.fruitKind },
        html: fruit(this.fruitKind),
      });
      this._makeFruitInteractive(f);
      fruits.append(f);
    }
    return el('div', { class: `tree tree-${side}` }, [canopy, fruits]);
  }

  _makeFruitInteractive(f) {
    const drop = () => this._deposit(f);
    // Drag into the pot…
    this.track(
      makeDraggable(f, {
        data: {},
        disabled: () => this.locked,
        dropZones: () => [{ el: this.pot, pad: 36 }],
        onPickup: () => this.ctx.audio.tap(),
        onDrop: (node, zone) => {
          if (zone.el === this.pot) {
            drop();
            return true;
          }
          return false;
        },
      })
    );
    // …or simply tap it (accessible fallback).
    f.addEventListener('click', (e) => {
      if (f.classList.contains('picked')) return;
      drop();
    });
  }

  _deposit(f) {
    if (this.locked || f.classList.contains('picked')) return;
    f.classList.add('picked');
    this.count += 1;
    const n = this.count;

    // animate a flying clone into the pot
    const from = f.getBoundingClientRect();
    const clone = fromHTML(f.querySelector('svg').outerHTML);
    clone.classList.add('fly-clone');
    Object.assign(clone.style, { left: from.left + 'px', top: from.top + 'px', width: from.width + 'px' });
    document.body.append(clone);
    f.style.visibility = 'hidden';
    const to = this.pot.getBoundingClientRect();
    requestAnimationFrame(() => {
      clone.style.transform = `translate(${to.left + to.width / 2 - from.left - from.width / 2}px, ${to.top + 10 - from.top}px) scale(.55)`;
      clone.style.opacity = '0.5';
    });
    setTimeout(() => {
      clone.remove();
      this.potCount.textContent = String(n);
      this.potCount.classList.remove('bump');
      void this.potCount.offsetWidth;
      this.potCount.classList.add('bump');
      this.potFill.style.height = Math.min(100, (n / this.sum) * 70 + 12) + '%';
      this.ctx.audio.count(n);
      if (this.numberLine) this._hopTo(n);
      if (n === this.sum) setTimeout(() => this._reveal(), 400);
    }, 340);
  }

  _buildNumberLine(max) {
    const line = el('div', { class: 'number-line' });
    this.marks = [];
    for (let i = 0; i <= max; i++) {
      const m = el('div', { class: 'nl-mark' }, [el('span', { class: 'nl-dot' }), el('small', { text: String(i) })]);
      this.marks.push(m);
      line.append(m);
    }
    this.hopper = el('div', { class: 'nl-hopper', text: '🧚' });
    line.append(this.hopper);
    requestAnimationFrame(() => this._hopTo(0));
    return line;
  }

  _hopTo(n) {
    if (!this.marks?.[n]) return;
    const mark = this.marks[n];
    const lineRect = this.numberLine.getBoundingClientRect();
    const mr = mark.getBoundingClientRect();
    this.hopper.style.left = mr.left - lineRect.left + mr.width / 2 - 14 + 'px';
    this.hopper.classList.remove('hop');
    void this.hopper.offsetWidth;
    this.hopper.classList.add('hop');
  }

  _reveal() {
    this.eq.querySelector('.eq-sum').textContent = String(this.sum);
    this.eq.classList.add('solved');
    const r = this.pot.getBoundingClientRect();
    this.solved({ point: { x: r.left + r.width / 2, y: r.top }, message: `${this.a} plus ${this.b} equals ${this.sum}! 🍎` });
  }
}
