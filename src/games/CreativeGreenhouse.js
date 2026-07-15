/**
 * CreativeGreenhouse.js — open-ended free play.
 *
 * No right answers here. The child stamps flowers, shapes, butterflies and
 * trees onto a canvas, drags them around, and arranges their own scene. When
 * they show Lumi, she auto-counts the creation and pays "math compliments"
 * ("You made 5 flowers — and a lovely repeating pattern!"), turning free play
 * into gentle, unpressured math talk.
 *
 * It reuses BaseGame's shell but runs a single, unscored "round" the child ends
 * on their own terms.
 */
import BaseGame from './BaseGame.js';
import { el, fromHTML, pick, clamp } from '../core/dom.js';
import { manipulative, shape, scenery } from '../../assets/svg.js';

const TOOLS = [
  { id: 'flower-pink', label: '🌸', make: () => manipulative('flower', '#ff8fab'), group: 'flower' },
  { id: 'flower-yellow', label: '🌼', make: () => manipulative('flower', '#ffd166'), group: 'flower' },
  { id: 'flower-blue', label: '💠', make: () => manipulative('flower', '#4cc9f0'), group: 'flower' },
  { id: 'flower-purple', label: '🪻', make: () => manipulative('flower', '#c77dff'), group: 'flower' },
  { id: 'butterfly', label: '🦋', make: () => manipulative('butterfly', '#c77dff'), group: 'bug' },
  { id: 'ladybug', label: '🐞', make: () => manipulative('ladybug'), group: 'bug' },
  { id: 'mushroom', label: '🍄', make: () => manipulative('mushroom'), group: 'plant' },
  { id: 'leaf', label: '🍃', make: () => manipulative('leaf'), group: 'plant' },
  { id: 'star', label: '⭐', make: () => shape('star', '#ffd166'), group: 'shape' },
  { id: 'heart', label: '💗', make: () => shape('heart', '#ff8fab'), group: 'shape' },
  { id: 'tree', label: '🌳', make: () => scenery.tree(), group: 'big', big: true },
  { id: 'sun', label: '☀️', make: () => scenery.sun(), group: 'big', big: true },
];

export default class CreativeGreenhouse extends BaseGame {
  onStart() {
    this.totalRounds = 1; // single free-play session
  }

  setupRound() {
    this.instruction = `Make your own magical garden! Tap a plant, then tap to place it. 🌱`;
    this.hint = `Pick something from the tray, then tap the garden to plant it. Drag things to move them!`;
    this.placed = [];
    this.selected = TOOLS[0];
    this.eraser = false;

    // ---- canvas ----
    this.canvas = el('div', { class: 'greenhouse-canvas' });
    this.canvas.addEventListener('pointerdown', (e) => this._canvasTap(e));
    this.hud = el('div', { class: 'greenhouse-hud', text: '0 things planted' });

    // ---- tool tray ----
    this.tray = el('div', { class: 'greenhouse-tray' });
    TOOLS.forEach((t, i) => {
      const btn = el('button', { class: 'tool' + (i === 0 ? ' selected' : ''), dataset: { id: t.id }, aria: { label: t.id }, html: t.make() });
      btn.addEventListener('click', () => this._selectTool(t, btn));
      this.tray.append(btn);
    });
    this.eraserBtn = el('button', { class: 'tool tool-eraser', title: 'Eraser', text: '🧹' });
    this.eraserBtn.addEventListener('click', () => this._toggleEraser());
    this.clearBtn = el('button', { class: 'tool tool-clear', title: 'Clear all', text: '🗑️' });
    this.clearBtn.addEventListener('click', () => this._clearAll());
    this.tray.append(this.eraserBtn, this.clearBtn);

    // ---- show-lumi button ----
    const done = el('button', { class: 'btn btn-primary btn-show-lumi', text: 'Show Lumi my garden! 🌟', onClick: () => this._showLumi() });

    this.stage.append(el('div', { class: 'greenhouse-wrap' }, [this.hud, this.canvas]), this.tray, done);
  }

  _selectTool(t, btn) {
    this.selected = t;
    this.eraser = false;
    this.eraserBtn.classList.remove('active');
    this.tray.querySelectorAll('.tool').forEach((b) => b.classList.remove('selected'));
    btn.classList.add('selected');
    this.ctx.audio.tap();
  }

  _toggleEraser() {
    this.eraser = !this.eraser;
    this.eraserBtn.classList.toggle('active', this.eraser);
    this.canvas.classList.toggle('erasing', this.eraser);
    this.ctx.audio.tap();
  }

  _clearAll() {
    this.placed.forEach((p) => p.el.remove());
    this.placed = [];
    this._updateHud();
    this.ctx.audio.pop();
  }

  _canvasTap(e) {
    // Ignore taps that land on an existing item (those are handled per-item).
    if (e.target.closest('.planted')) return;
    if (this.eraser) return;
    const rect = this.canvas.getBoundingClientRect();
    const x = clamp(e.clientX - rect.left, 16, rect.width - 16);
    const y = clamp(e.clientY - rect.top, 16, rect.height - 16);
    this._place(this.selected, x, y);
  }

  _place(tool, x, y) {
    const rot = (Math.random() - 0.5) * 16;
    const node = el('div', {
      class: 'planted pop-in' + (tool.big ? ' big' : ''),
      dataset: { id: tool.id, group: tool.group },
      style: { left: x + 'px', top: y + 'px', transform: `translate(-50%,-50%) rotate(${rot}deg)` },
      html: tool.make(),
    });
    this._makeMovable(node);
    this.canvas.append(node);
    this.placed.push({ tool, x, y, el: node });
    this.ctx.audio.count(this.placed.length);
    const r = node.getBoundingClientRect();
    this.ctx.particles.sparkleBurst(r.left + r.width / 2, r.top + r.height / 2, 5);
    this._updateHud();
  }

  /** Free reposition (no snap-back) + eraser removal. */
  _makeMovable(node) {
    let moving = false,
      sx = 0,
      sy = 0,
      ox = 0,
      oy = 0,
      dragged = false,
      pid = null;
    const rect = () => this.canvas.getBoundingClientRect();
    node.addEventListener('pointerdown', (e) => {
      if (this.eraser) {
        this._remove(node);
        e.stopPropagation();
        return;
      }
      moving = true;
      dragged = false;
      pid = e.pointerId;
      node.setPointerCapture(pid);
      sx = e.clientX;
      sy = e.clientY;
      ox = parseFloat(node.style.left);
      oy = parseFloat(node.style.top);
      node.classList.add('lifting');
      e.stopPropagation();
    });
    node.addEventListener('pointermove', (e) => {
      if (!moving || e.pointerId !== pid) return;
      const r = rect();
      if (Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) > 4) dragged = true;
      node.style.left = clamp(ox + (e.clientX - sx), 16, r.width - 16) + 'px';
      node.style.top = clamp(oy + (e.clientY - sy), 16, r.height - 16) + 'px';
    });
    const end = (e) => {
      if (!moving) return;
      moving = false;
      node.classList.remove('lifting');
    };
    node.addEventListener('pointerup', end);
    node.addEventListener('pointercancel', end);
  }

  _remove(node) {
    node.classList.add('poof');
    this.placed = this.placed.filter((p) => p.el !== node);
    this.ctx.audio.pop();
    setTimeout(() => node.remove(), 200);
    this._updateHud();
  }

  _updateHud() {
    const n = this.placed.length;
    this.hud.textContent = n === 0 ? 'Plant something lovely!' : `${n} thing${n === 1 ? '' : 's'} planted`;
  }

  /** Lumi counts the creation and gives cheerful math compliments. */
  _showLumi() {
    const n = this.placed.length;
    if (n === 0) {
      this.ctx.lumi.think('Plant a few things first, then show me! 🌷');
      return;
    }
    // Tally by tool and by group.
    const byGroup = {};
    const byTool = {};
    this.placed.forEach((p) => {
      byGroup[p.tool.group] = (byGroup[p.tool.group] || 0) + 1;
      byTool[p.tool.id] = (byTool[p.tool.id] || 0) + 1;
    });
    const flowers = byGroup.flower || 0;
    const topTool = Object.entries(byTool).sort((a, b) => b[1] - a[1])[0];

    const compliments = [`Wow! You planted ${n} things! Let's count: ${n}!`];
    if (flowers >= 2) compliments.push(`I see ${flowers} beautiful flowers! 🌸`);
    if (topTool && topTool[1] >= 3) compliments.push(`You made a lovely bunch of ${topTool[1]}!`);
    if (Object.keys(byGroup).length >= 3) compliments.push(`So many different kinds — what an imagination!`);
    if (this._looksLikePattern()) compliments.push(`Ooh, I think you made a repeating pattern! 🦋`);

    this.ctx.rewards.awardSticker('green-thumb');
    this.ctx.lumi.sayAll ? null : null;
    this.ctx.narration.sayAll(compliments);
    this.ctx.lumi.celebrate(compliments[0]);
    this.instructionBar.textContent = compliments.join('  ');

    // End the free-play session on a high note.
    this.solved({ message: 'Your garden is magical! 🌈' });
  }

  /** Heuristic: are items roughly in a row with alternating groups? */
  _looksLikePattern() {
    if (this.placed.length < 4) return false;
    const sorted = [...this.placed].sort((a, b) => parseFloat(a.el.style.left) - parseFloat(b.el.style.left));
    const ys = sorted.map((p) => parseFloat(p.el.style.top));
    const avg = ys.reduce((a, b) => a + b, 0) / ys.length;
    const inRow = ys.every((y) => Math.abs(y - avg) < 70);
    if (!inRow) return false;
    let alternating = true;
    for (let i = 2; i < sorted.length; i++) {
      if (sorted[i].tool.id !== sorted[i - 2].tool.id) alternating = false;
    }
    return alternating;
  }
}
