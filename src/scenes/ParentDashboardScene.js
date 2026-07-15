/**
 * ParentDashboardScene.js — the PIN-protected grown-up view.
 *
 * Visual, jargon-free reports told in garden metaphors (per the spec): time
 * spent, per-skill mastery & accuracy, skills "in full bloom", plus offline
 * activity ideas and an on-device data reset. No data ever leaves the device.
 */
import { el } from '../core/dom.js';
import { ZONES } from '../config/zones.js';
import { SKILLS } from '../config/curriculum.js';
import Modal from '../ui/Modal.js';

const OFFLINE_IDEAS = [
  '🍎 Count apples together while grocery shopping.',
  '🔺 Hunt for circles, squares & triangles around the house.',
  '🐞 Line up toys and count them one-by-one.',
  '🧩 Make a repeating pattern with spoons and forks.',
  '➕ Share snacks: "If we have 5 and eat 2, how many are left?"',
  '📏 Compare shoes — whose is longer? Whose is shorter?',
];

export default class ParentDashboardScene {
  constructor(ctx) {
    this.ctx = ctx;
  }

  mount(root) {
    const p = this.ctx.progress;
    const minutes = Math.round(p.totalPlayTimeMs / 60000);
    const mastered = ZONES.filter((z) => !z.freeplay && p.skillBloom(z.skillId) >= 0.999).length;

    const header = el('div', { class: 'page-header parent-header' }, [
      el('button', { class: 'btn-round btn-back', text: '←', aria: { label: 'Back' }, onClick: () => this.ctx.app.goToTab('settings') }),
      el('h1', { text: '🌱 Parent Dashboard' }),
    ]);

    const summary = el('div', { class: 'parent-summary' }, [
      this._bigStat('⏱️', `${minutes} min`, 'Total play time'),
      this._bigStat('🌸', `${mastered}/${ZONES.length - 1}`, 'Skills in full bloom'),
      this._bigStat('✨', p.totalStars(), 'Sparkle stars earned'),
    ]);

    // Per-skill report with accuracy + bloom bars.
    const report = el('div', { class: 'parent-report' });
    for (const z of ZONES) {
      if (z.freeplay) continue;
      const skill = p.skill(z.skillId);
      const bloom = p.skillBloom(z.skillId);
      const acc = p.accuracy(z.skillId);
      const level = p.levelIndex(z.skillId) + 1;
      const maxLevel = p.maxLevel(z.skillId) + 1;
      report.append(
        el('div', { class: 'report-row' }, [
          el('div', { class: 'report-emoji', text: z.emoji }),
          el('div', { class: 'report-main' }, [
            el('div', { class: 'report-title' }, [el('b', { text: SKILLS[z.skillId].name }), el('span', { class: 'report-level', text: `Level ${level} of ${maxLevel}` })]),
            el('div', { class: 'report-bar' }, [el('div', { class: 'report-fill', style: { width: Math.round(bloom * 100) + '%' } })]),
            el('div', { class: 'report-meta', text: skill.played ? `${acc}% accuracy · ${skill.played} rounds · best streak ${skill.bestStreak}` : 'Not started yet' }),
          ]),
          el('div', { class: 'report-status', text: bloom >= 0.999 ? '🌸' : bloom > 0.5 ? '🌿' : skill.played ? '🌱' : '🌰' }),
        ])
      );
    }

    // Offline suggestions
    const ideas = el('ul', { class: 'offline-ideas' });
    OFFLINE_IDEAS.forEach((t) => ideas.append(el('li', { text: t })));

    const resetBtn = el('button', { class: 'btn btn-danger', text: 'Reset all progress', onClick: () => this._confirmReset() });
    const pinBtn = el('button', { class: 'btn btn-ghost', text: 'Change PIN', onClick: () => this._changePin() });

    this.node = el('div', { class: 'page parent-page' }, [
      header,
      summary,
      el('div', { class: 'section-label', text: '🌼 How each skill is growing' }),
      report,
      el('div', { class: 'section-label', text: '🏡 Try these away from the screen' }),
      ideas,
      el('div', { class: 'section-label', text: 'Manage' }),
      el('div', { class: 'parent-manage' }, [pinBtn, resetBtn]),
      el('p', { class: 'coppa-note', text: '🛡️ COPPA-friendly: no ads, no tracking, no accounts. All data is stored only on this device.' }),
    ]);
    root.append(this.node);
    this.ctx.lumi.dock('hidden');
  }

  _bigStat(emoji, value, label) {
    return el('div', { class: 'big-stat' }, [el('div', { class: 'bs-emoji', text: emoji }), el('div', { class: 'bs-value', text: String(value) }), el('div', { class: 'bs-label', text: label })]);
  }

  _confirmReset() {
    Modal.open({
      title: 'Reset all progress?',
      body: 'This clears stickers, sparkles and every skill. This cannot be undone.',
      actions: [
        { label: 'Keep my garden' },
        {
          label: 'Reset everything',
          primary: true,
          onClick: () => {
            this.ctx.progress.reset();
            this.ctx.rewards.reset();
            this.ctx.app.goHome();
          },
        },
      ],
    });
  }

  _changePin() {
    const input = el('input', { class: 'pin-input', type: 'tel', inputmode: 'numeric', maxlength: '4', placeholder: '••••' });
    Modal.open({
      title: 'Set a new 4-digit PIN',
      body: input,
      actions: [
        { label: 'Cancel' },
        {
          label: 'Save',
          primary: true,
          // false keeps the dialog open on invalid input; true auto-closes it.
          onClick: () => {
            if (/^\d{4}$/.test(input.value)) {
              this.ctx.settings.setPin(input.value);
              return true;
            }
            input.value = '';
            input.placeholder = '4 digits!';
            return false;
          },
        },
      ],
    });
    setTimeout(() => input.focus(), 100);
  }

  unmount() {
    this.ctx.lumi.dock('corner');
  }
}
