/**
 * BottomNav.js — the four-tab bar from the spec:
 *   Garden Map | Journal | Profile | Settings
 *
 * Icon-heavy with tiny labels. It hides itself automatically while a child is
 * inside an activity so the play area is uncluttered, and reappears on the
 * map/journal/profile/settings scenes.
 */
import { el } from '../core/dom.js';

const TABS = [
  { id: 'garden', label: 'Garden', emoji: '🌻' },
  { id: 'journal', label: 'Journal', emoji: '📔' },
  { id: 'profile', label: 'Profile', emoji: '🧒' },
  { id: 'settings', label: 'Settings', emoji: '⚙️' },
];

export default class BottomNav {
  constructor(ctx, onNavigate) {
    this.ctx = ctx;
    this.onNavigate = onNavigate;
    this.buttons = new Map();
    this.node = el('nav', { class: 'bottom-nav', aria: { label: 'Main navigation' } });

    for (const tab of TABS) {
      const btn = el(
        'button',
        {
          class: 'nav-btn',
          dataset: { tab: tab.id },
          aria: { label: tab.label },
          onClick: () => {
            ctx.audio.tap();
            this.onNavigate(tab.id);
          },
        },
        [el('span', { class: 'nav-emoji', text: tab.emoji }), el('span', { class: 'nav-label', text: tab.label })]
      );
      this.buttons.set(tab.id, btn);
      this.node.append(btn);
    }
  }

  setActive(id) {
    for (const [tabId, btn] of this.buttons) btn.classList.toggle('active', tabId === id);
  }

  show() {
    this.node.classList.remove('hidden');
  }
  hide() {
    this.node.classList.add('hidden');
  }
}
