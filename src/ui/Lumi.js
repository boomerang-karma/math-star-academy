/**
 * Lumi.js — the mascot component.
 *
 * Lumi is a persistent floating character that narrates instructions, gives
 * hints when tapped, points at things, and celebrates wins with a dance. She
 * pairs a speech bubble with synchronized voice narration so pre-readers get
 * the same message two ways.
 *
 * A single Lumi lives in the app shell; scenes and games talk to her through
 * the shared instance (ctx.lumi).
 */
import { el, fromHTML } from '../core/dom.js';
import { lumi as lumiSVG } from '../../assets/svg.js';

export default class Lumi {
  constructor(ctx) {
    this.ctx = ctx;
    this.pose = 'idle';
    this.node = el('div', { class: 'lumi', aria: { hidden: 'true' } });
    this.avatar = el('button', { class: 'lumi-avatar', title: 'Tap Lumi for a hint', aria: { label: 'Lumi, tap for a hint' } });
    this.avatar.innerHTML = lumiSVG('idle');
    this.bubble = el('div', { class: 'lumi-bubble', aria: { live: 'polite' } });
    this.node.append(this.bubble, this.avatar);
    this._hintProvider = null;
    this._bubbleTimer = null;

    this.avatar.addEventListener('click', () => {
      this.ctx.audio.tap();
      if (this._hintProvider) this._hintProvider();
      else this.say(this._lastLine || "Let's play in the garden!");
    });
  }

  mount(parent) {
    parent.append(this.node);
  }

  setPose(pose) {
    if (pose === this.pose) return;
    this.pose = pose;
    this.avatar.innerHTML = lumiSVG(pose);
    // re-apply equipped cosmetics on top of the fresh SVG
    this._decorate();
  }

  /** Draw equipped hats/wings from the reward service as emoji accents. */
  _decorate() {
    const equipped = this.ctx.rewards.equipped.lumi || [];
    this.avatar.querySelector('.lumi-cosmetic')?.remove();
    if (!equipped.length) return;
    const map = { 'hat-flower': ['🌺', 'hat'], 'hat-star': ['⭐', 'hat'], 'wings-rainbow': ['🌈', 'wing'], 'wings-gold': ['💛', 'wing'] };
    const layer = el('div', { class: 'lumi-cosmetic' });
    equipped.forEach((id) => {
      const [emoji, kind] = map[id] || [];
      if (emoji) layer.append(el('span', { class: `cosmetic ${kind}`, text: emoji }));
    });
    this.avatar.append(layer);
  }

  /**
   * Show a speech bubble and speak it. `pose` optionally changes her posture;
   * `hold` keeps the bubble up (ms) before auto-hiding (0 = keep until next).
   */
  say(text, { pose = 'idle', hold = 4200, narrate = true, onEnd } = {}) {
    clearTimeout(this._bubbleTimer);
    this._lastLine = text;
    this.setPose(pose);
    this.bubble.textContent = text;
    this.bubble.classList.add('show');
    this.node.classList.add('talking');
    if (narrate) this.ctx.narration.say(text, { onEnd });
    else onEnd?.();
    if (hold > 0) {
      this._bubbleTimer = setTimeout(() => this.hideBubble(), hold);
    }
    return this;
  }

  hideBubble() {
    this.bubble.classList.remove('show');
    this.node.classList.remove('talking');
    if (this.pose !== 'idle') this.setPose('idle');
  }

  /** Celebrate: cheer pose, sparkles at her position, happy chime. */
  celebrate(text) {
    this.setPose('cheer');
    this.node.classList.add('dancing');
    const r = this.avatar.getBoundingClientRect();
    this.ctx.particles.sparkleBurst(r.left + r.width / 2, r.top + r.height / 2, 22);
    this.ctx.audio.chime();
    if (text) this.say(text, { pose: 'cheer', hold: 3600 });
    setTimeout(() => this.node.classList.remove('dancing'), 2000);
  }

  point(text) {
    this.say(text, { pose: 'point' });
  }
  think(text) {
    this.say(text, { pose: 'think' });
  }

  /** Register a context-specific hint (games set this on mount). */
  setHint(fn) {
    this._hintProvider = fn;
  }
  clearHint() {
    this._hintProvider = null;
  }

  /** Move Lumi to a docked corner or center-stage for intros. */
  dock(where = 'corner') {
    this.node.dataset.dock = where;
  }
}
