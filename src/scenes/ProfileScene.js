/**
 * ProfileScene.js — the child's profile & the cosmetic "Sparkle Shop".
 *
 * Shows Lumi with her currently equipped cosmetics, the child's name & totals,
 * and the unlockables from the reward service. Sparkles buy purely cosmetic
 * customizations for Lumi (hats, wings) and the garden (decorations) — there is
 * nothing to lose, only delight to gain.
 */
import { el } from '../core/dom.js';
import { lumi as lumiSVG } from '../../assets/svg.js';
import { UNLOCKABLES } from '../services/RewardService.js';
import Modal from '../ui/Modal.js';

export default class ProfileScene {
  constructor(ctx) {
    this.ctx = ctx;
  }

  mount(root) {
    this.root = root;
    this._render();
    this.ctx.lumi.dock('corner');
  }

  _render() {
    const rewards = this.ctx.rewards;
    const progress = this.ctx.progress;
    const name = this.ctx.settings.get('childName') || 'Little Gardener';

    const avatar = el('div', { class: 'profile-avatar' , html: lumiSVG('cheer')});
    // reflect equipped lumi cosmetics
    (rewards.equipped.lumi || []).forEach((id) => {
      const u = UNLOCKABLES.find((x) => x.id === id);
      if (u) avatar.append(el('span', { class: 'avatar-cosmetic', text: u.emoji }));
    });

    const stats = el('div', { class: 'profile-stats' }, [
      this._stat('✨', rewards.sparkles, 'Sparkles'),
      this._stat('⭐', progress.totalStars(), 'Stars'),
      this._stat('🌸', Math.round(progress.gardenBloom() * 100) + '%', 'Garden Grown'),
      this._stat('⏱️', Math.round(progress.totalPlayTimeMs / 60000) + 'm', 'Played'),
    ]);

    const nameBtn = el('button', { class: 'name-edit', text: `✏️ ${name}`, onClick: () => this._editName() });

    const header = el('div', { class: 'profile-header' }, [avatar, el('div', {}, [nameBtn, stats])]);

    // Shop
    const shop = el('div', { class: 'shop' });
    for (const u of UNLOCKABLES) {
      const owned = rewards.isUnlocked(u.id);
      const equipped = rewards.isEquipped(u.id);
      const afford = rewards.sparkles >= u.cost;
      const card = el('div', { class: 'shop-card' + (owned ? ' owned' : '') + (equipped ? ' equipped' : '') }, [
        el('div', { class: 'shop-emoji', text: u.emoji }),
        el('div', { class: 'shop-name', text: u.name }),
        el('div', { class: 'shop-type', text: u.type === 'lumi' ? 'For Lumi' : 'For Garden' }),
        owned
          ? el('button', { class: 'btn btn-small ' + (equipped ? 'btn-primary' : 'btn-ghost'), text: equipped ? 'Wearing ✓' : 'Wear', onClick: () => this._equip(u.id) })
          : el('button', { class: 'btn btn-small ' + (afford ? 'btn-primary' : 'btn-locked'), text: `✨ ${u.cost}`, disabled: afford ? null : 'true', onClick: () => this._buy(u) }),
      ]);
      shop.append(card);
    }

    this.node && this.node.remove();
    this.node = el('div', { class: 'page profile-page' }, [
      el('div', { class: 'page-header' }, [el('h1', { text: '🧒 My Profile' })]),
      header,
      el('div', { class: 'section-label', text: '✨ Sparkle Shop — unlock magical things!' }),
      shop,
    ]);
    this.root.append(this.node);
  }

  _stat(emoji, value, label) {
    return el('div', { class: 'stat-chip' }, [el('span', { class: 'stat-emoji', text: emoji }), el('b', { text: String(value) }), el('small', { text: label })]);
  }

  _buy(u) {
    if (this.ctx.rewards.unlock(u.id)) {
      this.ctx.audio.win();
      this.ctx.lumi.celebrate(`You unlocked ${u.name}! ${u.emoji}`);
      this._render();
    } else {
      this.ctx.lumi.think(`You need ${u.cost} sparkles for ${u.name}. Keep playing! ✨`);
    }
  }

  _equip(id) {
    this.ctx.rewards.equip(id);
    this.ctx.audio.pop();
    this.ctx.lumi._decorate?.();
    this._render();
  }

  _editName() {
    const input = el('input', { class: 'text-input', type: 'text', maxlength: '16', value: this.ctx.settings.get('childName') || '', placeholder: 'Type a name' });
    Modal.open({
      title: "What's your name?",
      body: input,
      actions: [
        { label: 'Cancel' },
        {
          label: 'Save',
          primary: true,
          onClick: () => {
            this.ctx.settings.set('childName', input.value.trim().slice(0, 16));
            this._render();
          },
        },
      ],
    });
    setTimeout(() => input.focus(), 100);
  }

  unmount() {}
}
