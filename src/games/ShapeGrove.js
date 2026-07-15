/**
 * ShapeGrove.js — "Build Fairy Houses & Paths" + shape sorting.
 *
 * Teaches: 2D shape identification, sorting/classifying, spatial composition.
 * Two round types alternate for variety:
 *   • BUILD — drag shapes onto the dashed outline slots of a fairy scene
 *     (house, tree, flower path) until the picture is whole.
 *   • SORT — drag scattered shapes into the matching flower-bed bin.
 */
import BaseGame from './BaseGame.js';
import { el, fromHTML, shuffle, pick, randInt } from '../core/dom.js';
import { makeDraggable } from '../core/drag.js';
import { shape, SHAPE_KINDS } from '../../assets/svg.js';

const SCENES = [
  {
    name: 'Fairy House',
    parts: [
      { shape: 'triangle', x: 50, y: 24, size: 30 },
      { shape: 'square', x: 50, y: 55, size: 26 },
      { shape: 'circle', x: 50, y: 58, size: 10 },
      { shape: 'star', x: 80, y: 20, size: 13 },
      { shape: 'hexagon', x: 22, y: 74, size: 15 },
      { shape: 'rectangle', x: 76, y: 78, size: 20 },
    ],
  },
  {
    name: 'Sunny Tree',
    parts: [
      { shape: 'circle', x: 48, y: 32, size: 34 },
      { shape: 'triangle', x: 24, y: 74, size: 18 },
      { shape: 'square', x: 48, y: 66, size: 12 },
      { shape: 'star', x: 16, y: 20, size: 12 },
      { shape: 'circle', x: 82, y: 22, size: 16 },
      { shape: 'hexagon', x: 78, y: 76, size: 15 },
    ],
  },
  {
    name: 'Flower Path',
    parts: [
      { shape: 'square', x: 28, y: 72, size: 15 },
      { shape: 'circle', x: 50, y: 32, size: 18 },
      { shape: 'triangle', x: 70, y: 68, size: 18 },
      { shape: 'square', x: 50, y: 78, size: 15 },
      { shape: 'star', x: 50, y: 14, size: 13 },
      { shape: 'rectangle', x: 76, y: 30, size: 18 },
    ],
  },
];

const PALETTE_COLORS = ['#ff8fab', '#ffd166', '#8ac926', '#48cae4', '#c77dff', '#ff6b6b', '#f4a261', '#4cc9f0'];

export default class ShapeGrove extends BaseGame {
  setupRound() {
    this.mode = this.roundIndex % 2 === 1 ? 'sort' : 'build';
    this.mode === 'sort' ? this._setupSort() : this._setupBuild();
  }

  /* ---------------- BUILD ---------------- */
  _setupBuild() {
    const kinds = this.level.kinds;
    const scene = pick(SCENES);
    const slotsWanted = Math.min(this.level.slots, scene.parts.length);
    // Take parts, remapping any shape not in this level's kind set.
    const parts = scene.parts.slice(0, slotsWanted).map((p) => ({
      ...p,
      shape: kinds.includes(p.shape) ? p.shape : pick(kinds),
    }));
    this.remaining = parts.length;

    this.instruction = `Build the ${scene.name}! Drag each shape onto its outline.`;
    this.hint = `Match each shape to the dashed outline of the same shape.`;

    this.canvas = el('div', { class: 'build-canvas' });
    this.slots = parts.map((p, i) => {
      const slot = el('div', {
        class: 'shape-slot',
        dataset: { shape: p.shape, filled: 'false' },
        style: { left: p.x + '%', top: p.y + '%', width: p.size + '%' },
        html: shape(p.shape, '#8a7a9b', { outline: true }),
      });
      this.canvas.append(slot);
      return slot;
    });

    // Palette: the needed shapes (shuffled) + a distractor at higher levels.
    const need = shuffle(parts.map((p) => p.shape));
    const paletteKinds = [...need];
    if (this.levelIndex >= 2) {
      const distractor = kinds.find((k) => !need.includes(k));
      if (distractor) paletteKinds.push(distractor);
    }
    this.palette = el('div', { class: 'shape-palette' });
    shuffle(paletteKinds).forEach((k, i) => this.palette.append(this._paletteShape(k, i)));

    this.stage.append(this.canvas, this.palette);
  }

  _paletteShape(kind, i) {
    const color = PALETTE_COLORS[i % PALETTE_COLORS.length];
    const node = el('button', {
      class: 'palette-shape pop-in',
      dataset: { shape: kind },
      style: { animationDelay: i * 60 + 'ms' },
      aria: { label: kind },
      html: shape(kind, color),
    });
    this.track(
      makeDraggable(node, {
        disabled: () => this.locked,
        onPickup: () => this.ctx.audio.tap(),
        dropZones: () => this.slots.filter((s) => s.dataset.filled === 'false').map((el) => ({ el, pad: 16 })),
        onDrop: (n, zone) => this._tryPlace(node, zone.el, color),
      })
    );
    // tap fallback: place on the first empty matching slot
    node.addEventListener('click', () => {
      const target = this.slots.find((s) => s.dataset.filled === 'false' && s.dataset.shape === kind);
      if (target) this._tryPlace(node, target, color);
      else this.registerMistake("Hmm, where does this shape go?");
    });
    return node;
  }

  _tryPlace(node, slot, color) {
    if (slot.dataset.filled === 'true') return false;
    if (slot.dataset.shape !== node.dataset.shape) {
      this.registerMistake("That shape doesn't fit here — try another spot!");
      return false;
    }
    slot.dataset.filled = 'true';
    slot.innerHTML = shape(node.dataset.shape, color);
    slot.classList.add('slot-filled');
    node.classList.add('used');
    node.style.pointerEvents = 'none';
    this.ctx.audio.pop();
    const r = slot.getBoundingClientRect();
    this.ctx.particles.sparkleBurst(r.left + r.width / 2, r.top + r.height / 2, 8);
    if (--this.remaining === 0) {
      this.canvas.classList.add('scene-complete');
      setTimeout(() => this.solved({ message: 'You built it! Beautiful! 🏠✨' }), 500);
    }
    return true;
  }

  /* ---------------- SORT ---------------- */
  _setupSort() {
    const kinds = this.level.kinds.slice(0, Math.min(4, this.level.kinds.length));
    this.instruction = `Sort the shapes into the right flower beds!`;
    this.hint = `Drag each shape to the bin with the same shape picture.`;

    // Bins
    this.bins = el('div', { class: 'sort-bins' });
    this.binByKind = {};
    kinds.forEach((k, i) => {
      const bin = el('div', {
        class: 'sort-bin',
        dataset: { shape: k },
        html: `<div class="bin-icon">${shape(k, PALETTE_COLORS[i % PALETTE_COLORS.length], { outline: true })}</div>`,
      });
      bin.append(el('div', { class: 'bin-tray' }));
      this.binByKind[k] = bin;
      this.bins.append(bin);
    });

    // Scattered shapes — a few of each kind.
    const perKind = randInt(2, 3);
    const items = [];
    kinds.forEach((k) => {
      for (let i = 0; i < perKind; i++) items.push(k);
    });
    this.toSort = items.length;
    this.tray = el('div', { class: 'sort-tray' });
    shuffle(items).forEach((k, i) => {
      const color = PALETTE_COLORS[SHAPE_KINDS.indexOf(k) % PALETTE_COLORS.length];
      const s = el('button', {
        class: 'sort-shape pop-in',
        dataset: { shape: k },
        style: { animationDelay: i * 50 + 'ms' },
        aria: { label: k },
        html: shape(k, color),
      });
      this.track(
        makeDraggable(s, {
          disabled: () => this.locked,
          onPickup: () => this.ctx.audio.tap(),
          dropZones: () => Object.values(this.binByKind).map((el) => ({ el, pad: 20 })),
          onDrop: (n, zone) => this._trySort(s, zone.el),
        })
      );
      s.addEventListener('click', () => this._trySort(s, this.binByKind[k]));
      this.tray.append(s);
    });

    this.stage.append(this.bins, this.tray);
  }

  _trySort(node, bin) {
    if (bin.dataset.shape !== node.dataset.shape) {
      this.registerMistake('Not that bed — look at the shape!');
      return false;
    }
    const mini = fromHTML(node.querySelector('svg').outerHTML);
    mini.classList.add('binned');
    bin.querySelector('.bin-tray').append(mini);
    node.remove();
    this.ctx.audio.pop();
    bin.classList.add('bin-bounce');
    setTimeout(() => bin.classList.remove('bin-bounce'), 300);
    if (--this.toSort === 0) setTimeout(() => this.solved({ message: 'All sorted! Wonderful! 🌷' }), 400);
    return true;
  }
}
