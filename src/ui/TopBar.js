/**
 * TopBar.js — the slim header shown inside activities.
 *
 * Holds a big friendly Back arrow (returns to the garden map), the live Magic
 * Sparkles counter, and a per-round progress pip row. Kept text-light with
 * large targets per the UX guidelines.
 */
import { el } from '../core/dom.js';
import { scenery } from '../../assets/svg.js';

export default class TopBar {
  constructor(ctx, { title = '', onBack } = {}) {
    this.ctx = ctx;
    this.sparkleCount = el('span', { class: 'sparkle-count', text: String(ctx.rewards.sparkles) });
    this.pips = el('div', { class: 'round-pips' });

    this.backBtn = el(
      'button',
      { class: 'btn-round btn-back', aria: { label: 'Back to the garden' }, onClick: () => { ctx.audio.tap(); onBack?.(); } },
      '←'
    );

    const sparkle = el('div', { class: 'sparkle-badge', html: scenery.sparkle() });
    sparkle.append(this.sparkleCount);

    this.node = el('header', { class: 'topbar' }, [
      this.backBtn,
      el('h2', { class: 'topbar-title', text: title }),
      sparkle,
    ]);

    this._off = ctx.bus.on('reward:sparkles', ({ total }) => this._bump(total));
  }

  _bump(total) {
    this.sparkleCount.textContent = String(total);
    this.sparkleCount.parentElement.classList.remove('pulse');
    void this.sparkleCount.offsetWidth;
    this.sparkleCount.parentElement.classList.add('pulse');
  }

  /** Render N pips, filling `done` of them. */
  setRounds(total, done) {
    this.pips.innerHTML = '';
    for (let i = 0; i < total; i++) {
      this.pips.append(el('span', { class: 'pip' + (i < done ? ' filled' : '') }));
    }
    if (!this.pips.parentElement) this.node.append(this.pips);
  }

  setTitle(t) {
    this.node.querySelector('.topbar-title').textContent = t;
  }

  destroy() {
    this._off?.();
  }
}
