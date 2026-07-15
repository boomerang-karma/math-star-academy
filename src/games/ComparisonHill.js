/**
 * ComparisonHill.js — comparing quantities (more / fewer / same).
 *
 * Teaches: comparing groups, the language of more/less/equal. Two bushes bear
 * different numbers of berries; Lumi asks which has MORE (or FEWER), and the
 * child taps a whole bush — a big, forgiving target. When the groups are equal
 * the answer is the "Same!" button, teaching equality too. On answer both
 * counts are revealed so the comparison is concrete.
 */
import BaseGame from './BaseGame.js';
import { el, randInt, pick } from '../core/dom.js';
import { berry } from '../../assets/svg.js';

export default class ComparisonHill extends BaseGame {
  setupRound() {
    const { max, gap } = this.level;
    const equal = Math.random() < 0.22;
    let a = randInt(1, max);
    let b;
    if (equal) b = a;
    else {
      do {
        b = randInt(1, max);
      } while (Math.abs(a - b) < gap || a === b);
    }
    this.a = a;
    this.b = b;
    this.ask = pick(['more', 'fewer']);

    // Determine the correct answer id: 'A' | 'B' | 'same'
    if (a === b) this.answer = 'same';
    else if (this.ask === 'more') this.answer = a > b ? 'A' : 'B';
    else this.answer = a < b ? 'A' : 'B';

    this.instruction = `Which bush has ${this.ask.toUpperCase()} berries? Tap it! (or “Same”)`;
    this.hint = this.ask === 'more' ? `More means the bigger bunch. Count each one!` : `Fewer means the smaller bunch. Count each one!`;

    this.cardA = this._bush(a, 'A', '#c1121f');
    this.cardB = this._bush(b, 'B', '#7b2cbf');
    const versus = el('div', { class: 'versus', text: 'vs' });
    const row = el('div', { class: 'compare-row' }, [this.cardA, versus, this.cardB]);

    this.sameBtn = el('button', { class: 'btn btn-same', text: '🟰 Same!', onClick: () => this._choose('same', this.sameBtn) });

    this.stage.append(row, this.sameBtn);
  }

  _bush(n, id, color) {
    const grid = el('div', { class: 'bush-berries' });
    for (let i = 0; i < n; i++) grid.append(el('span', { class: 'mini-berry pop-in', style: { animationDelay: i * 40 + 'ms' }, html: berry(color) }));
    const numeral = el('div', { class: 'bush-numeral', text: '?' });
    const card = el('button', { class: 'bush-card', dataset: { id }, aria: { label: `bush ${id}` } }, [grid, numeral]);
    card.addEventListener('click', () => this._choose(id, card));
    return card;
  }

  _choose(choice, node) {
    if (this.locked) return;
    // Always reveal the two counts so the comparison is visible.
    this.cardA.querySelector('.bush-numeral').textContent = String(this.a);
    this.cardB.querySelector('.bush-numeral').textContent = String(this.b);

    if (choice === this.answer) {
      node.classList.add('correct');
      if (this.answer !== 'same') node.classList.add('winner');
      const r = node.getBoundingClientRect();
      this.solved({ point: { x: r.left + r.width / 2, y: r.top + 20 }, message: this._why() });
    } else {
      node.classList.add('nudge');
      setTimeout(() => node.classList.remove('nudge'), 400);
      // hide numerals again so they can re-count
      setTimeout(() => {
        this.cardA.querySelector('.bush-numeral').textContent = '?';
        this.cardB.querySelector('.bush-numeral').textContent = '?';
      }, 900);
      this.registerMistake('Count again carefully — you can do it!');
    }
  }

  _why() {
    if (this.answer === 'same') return `Both have ${this.a}! They are the same! 🟰`;
    const hi = Math.max(this.a, this.b),
      lo = Math.min(this.a, this.b);
    return this.ask === 'more' ? `${hi} is more than ${lo}! 🎉` : `${lo} is fewer than ${hi}! 🎉`;
  }
}
