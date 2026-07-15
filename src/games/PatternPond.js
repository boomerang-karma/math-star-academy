/**
 * PatternPond.js — "Design the Most Beautiful Flowerbed"
 *
 * Teaches: recognising & extending repeating patterns (AB, ABC, AAB, ABB).
 * A row shows a pattern repeated twice with the final unit missing; the child
 * drags the correct flowers/leaves/butterflies into the empty spots to continue
 * it. Completing the row makes every flower bloom in sequence and butterflies
 * fly in formation.
 */
import BaseGame from './BaseGame.js';
import { el, fromHTML, shuffle, pick } from '../core/dom.js';
import { makeDraggable } from '../core/drag.js';
import { manipulative } from '../../assets/svg.js';

// Distinct visual tokens a pattern can be built from.
const TOKENS = [
  { id: 'flower-pink', render: () => manipulative('flower', '#ff8fab') },
  { id: 'flower-yellow', render: () => manipulative('flower', '#ffd166') },
  { id: 'butterfly', render: () => manipulative('butterfly', '#c77dff') },
  { id: 'leaf', render: () => manipulative('leaf') },
  { id: 'flower-blue', render: () => manipulative('flower', '#4cc9f0') },
  { id: 'ladybug', render: () => manipulative('ladybug') },
];

const UNITS = { AB: [0, 1], ABC: [0, 1, 2], AAB: [0, 0, 1], ABB: [0, 1, 1] };

export default class PatternPond extends BaseGame {
  setupRound() {
    const type = this.level.type;
    const unit = UNITS[type];
    const choices = this.level.choices;
    this.tokens = shuffle(TOKENS).slice(0, choices);

    // Three repeats; the last unit is blank for the child to complete.
    const repeats = 3;
    this.seq = [];
    for (let r = 0; r < repeats; r++) for (const u of unit) this.seq.push(this.tokens[u]);
    this.blankFrom = unit.length * (repeats - 1);
    this.activeIndex = this.blankFrom;

    this.instruction = `Finish the flowerbed pattern! What comes next?`;
    this.hint = `Look at how it repeats: ${type.split('').join(', ')}. Drag the matching one into the glowing spot.`;

    // ---- pattern row ----
    this.row = el('div', { class: 'pattern-row' });
    this.slots = this.seq.map((tok, i) => {
      const filled = i < this.blankFrom;
      const slot = el('div', {
        class: 'pattern-slot' + (filled ? ' filled' : ''),
        dataset: { index: i },
        html: filled ? `<span class="tok">${tok.render()}</span>` : '',
      });
      this.row.append(slot);
      return slot;
    });
    this._highlightActive();

    // ---- token palette ----
    this.paletteEl = el('div', { class: 'pattern-palette' });
    this.tokens.forEach((tok, i) => {
      const btn = el('button', {
        class: 'palette-token pop-in',
        dataset: { id: tok.id },
        style: { animationDelay: i * 70 + 'ms' },
        aria: { label: tok.id },
        html: tok.render(),
      });
      this.track(
        makeDraggable(btn, {
          disabled: () => this.locked,
          onPickup: () => this.ctx.audio.tap(),
          dropZones: () => [{ el: this.slots[this.activeIndex], pad: 22 }],
          onDrop: () => this._tryPlace(tok),
        })
      );
      btn.addEventListener('click', () => this._tryPlace(tok));
      this.paletteEl.append(btn);
    });

    this.stage.append(el('div', { class: 'pond-frame' }, [this.row]), this.paletteEl);
  }

  _highlightActive() {
    this.slots.forEach((s, i) => s.classList.toggle('active', i === this.activeIndex));
  }

  _tryPlace(tok) {
    if (this.locked || this.activeIndex >= this.seq.length) return;
    const expected = this.seq[this.activeIndex];
    if (tok.id !== expected.id) {
      this.registerMistake('Look at the pattern again — which one repeats?');
      return;
    }
    const slot = this.slots[this.activeIndex];
    slot.innerHTML = `<span class="tok pop-in">${tok.render()}</span>`;
    slot.classList.add('filled', 'just-placed');
    this.ctx.audio.pop();
    this.activeIndex += 1;
    if (this.activeIndex >= this.seq.length) {
      this._bloomRow();
    } else {
      this._highlightActive();
    }
  }

  _bloomRow() {
    // Each flower blooms in sequence, then butterflies fly across.
    this.slots.forEach((s, i) => {
      setTimeout(() => {
        s.classList.add('bloom');
        const r = s.getBoundingClientRect();
        this.ctx.particles.sparkleBurst(r.left + r.width / 2, r.top + r.height / 2, 6);
        this.ctx.audio.count(i);
      }, i * 110);
    });
    const total = this.slots.length * 110 + 300;
    setTimeout(() => {
      this._flyButterflies();
      this.solved({ message: 'What a beautiful pattern! 🦋' });
    }, total);
  }

  _flyButterflies() {
    if (this.ctx.settings.get('reducedMotion')) return;
    const rect = this.row.getBoundingClientRect();
    for (let i = 0; i < 5; i++) {
      const b = fromHTML(manipulative('butterfly', pick(['#c77dff', '#ff8fab', '#4cc9f0'])));
      b.classList.add('flyby-butterfly');
      b.style.left = rect.left + 'px';
      b.style.top = rect.top + rect.height / 2 + 'px';
      b.style.setProperty('--dx', rect.width + 80 + 'px');
      b.style.setProperty('--dy', -60 - i * 20 + 'px');
      b.style.animationDelay = i * 120 + 'ms';
      document.body.append(b);
      setTimeout(() => b.remove(), 2000);
    }
  }
}
