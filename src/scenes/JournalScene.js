/**
 * JournalScene.js — the sticker & progress journal.
 *
 * A keepsake book: every sticker the child has collected (with gentle hints for
 * ones still to earn), their Magic Sparkle total, and a per-zone "bloom" bar
 * described in the garden metaphors the spec asks for.
 */
import { el, fromHTML } from '../core/dom.js';
import { STICKERS } from '../services/RewardService.js';
import { ZONES } from '../config/zones.js';
import { scenery } from '../../assets/svg.js';

export default class JournalScene {
  constructor(ctx) {
    this.ctx = ctx;
  }

  mount(root) {
    const rewards = this.ctx.rewards;
    const earned = STICKERS.filter((s) => rewards.hasSticker(s.id)).length;

    const header = el('div', { class: 'page-header' }, [
      el('h1', { text: '📔 My Garden Journal' }),
      el('div', { class: 'sparkle-total', html: `${scenery.sparkle()}<b>${rewards.sparkles}</b> Magic Sparkles` }),
    ]);

    // Sticker grid
    const stickerGrid = el('div', { class: 'sticker-grid' });
    for (const s of STICKERS) {
      const has = rewards.hasSticker(s.id);
      stickerGrid.append(
        el('div', { class: 'sticker-card' + (has ? ' earned' : ' locked'), title: has ? s.name : s.hint }, [
          el('div', { class: 'sticker-emoji', text: has ? s.emoji : '❓' }),
          el('div', { class: 'sticker-name', text: has ? s.name : '???' }),
          el('div', { class: 'sticker-hint', text: has ? 'Collected!' : s.hint }),
        ])
      );
    }

    // Progress bars per zone
    const progressList = el('div', { class: 'progress-list' });
    for (const z of ZONES) {
      if (z.freeplay) continue;
      const bloom = this.ctx.progress.skillBloom(z.skillId);
      const acc = this.ctx.progress.accuracy(z.skillId);
      const row = el('div', { class: 'progress-row', dataset: { accent: z.accent } }, [
        el('div', { class: 'pr-emoji', text: z.emoji }),
        el('div', { class: 'pr-body' }, [
          el('div', { class: 'pr-title', text: z.title }),
          el('div', { class: 'pr-bar' }, [el('div', { class: 'pr-fill', style: { width: Math.round(bloom * 100) + '%' } })]),
        ]),
        el('div', { class: 'pr-pct', text: bloom >= 0.999 ? '🌸 Full bloom!' : Math.round(bloom * 100) + '%' }),
      ]);
      progressList.append(row);
    }

    this.node = el('div', { class: 'page journal-page' }, [
      header,
      el('div', { class: 'section-label', text: `Stickers  (${earned}/${STICKERS.length})` }),
      stickerGrid,
      el('div', { class: 'section-label', text: 'How my garden is growing' }),
      progressList,
    ]);
    root.append(this.node);
    this.ctx.lumi.dock('corner');
  }

  unmount() {}
}
