/**
 * CountingMeadow.js — "Plant the Perfect Patch"
 *
 * Teaches: counting 1–20, one-to-one correspondence, matching quantity→numeral,
 * ten-frame grouping. Children tap scattered critters to hop them into a basket
 * while a big number counts up with a pop on each. Later levels show a target
 * numeral and a ten-frame, asking for an exact amount (with a Check button and
 * the ability to send critters back out).
 */
import BaseGame from './BaseGame.js';
import { el, fromHTML, randInt, shuffle, pick } from '../core/dom.js';
import { manipulative, scenery, MANIPULATIVE_KINDS } from '../../assets/svg.js';

export default class CountingMeadow extends BaseGame {
  setupRound() {
    const lvl = this.level;
    this.target = randInt(2, lvl.max);
    this.critter = pick(['ladybug', 'flower', 'seed', 'mushroom', 'acorn']);
    this.collected = [];
    this.exactMode = !!lvl.matchNumeral; // must place EXACTLY target
    this.useTenFrame = !!lvl.tenFrame;

    const scatterCount = this.exactMode ? Math.min(lvl.max + 2, this.target + randInt(1, 3)) : this.target;

    this.instruction = this.exactMode
      ? `Put exactly ${this.target} ${this.critter}s in the basket!`
      : `Tap every ${this.critter} to count them into the basket!`;
    this.hint = this.exactMode
      ? `Tap critters into the basket until you count to ${this.target}. Tap one in the basket to take it back.`
      : `Tap each ${this.critter}. Count with me: one, two, three…`;

    // ---- layout ----
    this.meadow = el('div', { class: 'meadow' });
    this.counter = el('div', { class: 'count-display', text: this.exactMode ? `0 / ${this.target}` : '0' });

    const basketArt = fromHTML(scenery.basket());
    this.basket = el('div', { class: 'basket' }, [basketArt]);
    this.tenFrame = el('div', { class: 'ten-frame' });
    if (this.useTenFrame) {
      for (let i = 0; i < 10; i++) this.tenFrame.append(el('div', { class: 'tf-cell' }));
      this.basket.append(this.tenFrame);
    } else {
      this.dropPile = el('div', { class: 'basket-pile' });
      this.basket.append(this.dropPile);
    }

    // A big target numeral card for match-numeral rounds.
    const bottom = el('div', { class: 'counting-bottom' });
    if (this.exactMode) {
      bottom.append(el('div', { class: 'target-card', html: `<span>Goal</span><b>${this.target}</b>` }));
    }
    bottom.append(this.basket);
    if (this.exactMode) {
      this.checkBtn = el('button', { class: 'btn btn-primary', text: 'Check ✓', onClick: () => this._check() });
      bottom.append(this.checkBtn);
    }

    // ---- scatter critters ----
    const positions = this._scatterPositions(scatterCount);
    for (let i = 0; i < scatterCount; i++) {
      const critterEl = el('button', {
        class: 'critter pop-in',
        style: { left: positions[i].x + '%', top: positions[i].y + '%', animationDelay: i * 60 + 'ms' },
        aria: { label: this.critter },
        html: manipulative(this.critter, pick(['#ff8fab', '#ffd166', '#c77dff', '#8ac926'])),
      });
      critterEl.addEventListener('click', () => this._collect(critterEl));
      this.meadow.append(critterEl);
    }

    this.stage.append(this.counter, this.meadow, bottom);
  }

  _scatterPositions(n) {
    // Spread critters on a loose grid with jitter so they never overlap much.
    const cols = Math.ceil(Math.sqrt(n * 1.6));
    const rows = Math.ceil(n / cols);
    const cells = shuffle(Array.from({ length: cols * rows }, (_, i) => i)).slice(0, n);
    return cells.map((idx) => {
      const cx = (idx % cols) / cols;
      const cy = Math.floor(idx / cols) / rows;
      return { x: 8 + cx * 82 + Math.random() * 8, y: 6 + cy * 74 + Math.random() * 10 };
    });
  }

  _collect(critterEl) {
    if (this.locked || critterEl.classList.contains('collected')) return;
    critterEl.classList.add('collected');
    this.collected.push(critterEl);
    const n = this.collected.length;
    this.ctx.audio.count(n);

    // Fly the critter to the next basket slot.
    const slot = this.useTenFrame ? this.tenFrame.children[Math.min(n - 1, 9)] : this.dropPile;
    this._flyTo(critterEl, slot, n);

    if (this.exactMode) {
      this.counter.textContent = `${n} / ${this.target}`;
    } else {
      this.counter.textContent = String(n);
      this.counter.classList.remove('bump');
      void this.counter.offsetWidth;
      this.counter.classList.add('bump');
      if (n === this.target) setTimeout(() => this._succeed(), 450);
    }
  }

  _flyTo(critterEl, slot, n) {
    const from = critterEl.getBoundingClientRect();
    const clone = fromHTML(critterEl.querySelector('svg').outerHTML);
    clone.classList.add('fly-clone');
    clone.style.left = from.left + 'px';
    clone.style.top = from.top + 'px';
    clone.style.width = from.width + 'px';
    document.body.append(clone);
    critterEl.style.visibility = 'hidden';
    requestAnimationFrame(() => {
      const to = slot.getBoundingClientRect();
      clone.style.transform = `translate(${to.left - from.left + (this.useTenFrame ? 4 : (n % 5) * 6)}px, ${to.top - from.top + 4}px) scale(.7)`;
      clone.style.opacity = '0.95';
    });
    setTimeout(() => {
      clone.remove();
      const mini = fromHTML(critterEl.querySelector('svg').outerHTML);
      mini.classList.add('basket-item');
      if (this.useTenFrame) {
        slot.innerHTML = '';
        slot.append(mini);
        slot.classList.add('filled');
      } else {
        mini.style.setProperty('--i', String(n));
        this.dropPile.append(mini);
      }
      this.ctx.audio.pop();
      // Allow taking one back in exact mode.
      if (this.exactMode) {
        mini.classList.add('removable');
        mini.addEventListener('click', () => this._removeOne(critterEl, mini, slot));
      }
    }, 380);
  }

  _removeOne(critterEl, mini, slot) {
    if (this.locked) return;
    const idx = this.collected.indexOf(critterEl);
    if (idx >= 0) this.collected.splice(idx, 1);
    critterEl.style.visibility = 'visible';
    critterEl.classList.remove('collected');
    mini.remove();
    if (this.useTenFrame) slot.classList.remove('filled');
    this.ctx.audio.tap();
    // Re-number ten-frame fills so gaps close.
    if (this.useTenFrame) this._reflowTenFrame();
    this.counter.textContent = `${this.collected.length} / ${this.target}`;
  }

  _reflowTenFrame() {
    [...this.tenFrame.children].forEach((c) => {
      c.innerHTML = '';
      c.classList.remove('filled');
    });
    this.collected.forEach((critterEl, i) => {
      const cell = this.tenFrame.children[Math.min(i, 9)];
      const mini = fromHTML(critterEl.querySelector('svg').outerHTML);
      mini.classList.add('basket-item', 'removable');
      mini.addEventListener('click', () => this._removeOne(critterEl, mini, cell));
      cell.append(mini);
      cell.classList.add('filled');
    });
  }

  _check() {
    if (this.collected.length === this.target) this._succeed();
    else {
      const diff = this.target - this.collected.length;
      this.registerMistake(diff > 0 ? `Almost! Add ${diff} more.` : `Ooh, that's too many. Take ${-diff} out.`);
    }
  }

  _succeed() {
    // Soil patch bursts into bloom.
    const r = this.basket.getBoundingClientRect();
    this.ctx.particles.bloom(r.left + r.width / 2, r.top, '#ff8fab');
    this.solved({ point: { x: r.left + r.width / 2, y: r.top }, message: `${this.target}! You counted perfectly! 🌸` });
  }
}
