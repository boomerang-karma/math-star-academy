/**
 * SettingsScene.js — child-safe settings + the door to the parent area.
 *
 * The toggles here are the accessibility & audio options from the spec
 * (reduced motion, high contrast, large text, narration/music/sfx). The parent
 * dashboard is gated behind a PIN entered on this screen, keeping reports and
 * data controls away from little fingers.
 */
import { el } from '../core/dom.js';
import Modal from '../ui/Modal.js';
import { AGES, ageToStartLevel } from '../config/curriculum.js';

export default class SettingsScene {
  constructor(ctx) {
    this.ctx = ctx;
  }

  mount(root) {
    const s = this.ctx.settings;

    const toggles = [
      { key: 'narration', label: '🗣️ Voice narration', desc: 'Lumi reads everything aloud' },
      { key: 'music', label: '🎵 Background music', desc: 'Gentle garden melody' },
      { key: 'sfx', label: '🔔 Sound effects', desc: 'Pops, chimes & sparkles' },
      { key: 'reducedMotion', label: '🍃 Reduced motion', desc: 'Calmer, fewer animations' },
      { key: 'highContrast', label: '🔲 High contrast', desc: 'Bolder colors & outlines' },
      { key: 'largeText', label: '🔠 Large text', desc: 'Bigger words everywhere' },
    ];

    const list = el('div', { class: 'settings-list' });
    for (const t of toggles) {
      list.append(this._toggle(t));
    }

    const parentBtn = el('button', { class: 'btn btn-parent', text: '🔒 Parent Dashboard', onClick: () => this._enterParent() });

    this.node = el('div', { class: 'page settings-page' }, [
      el('div', { class: 'page-header' }, [el('h1', { text: '⚙️ Settings' })]),
      el('div', { class: 'section-label', text: '🎂 How old is the gardener?' }),
      this._agePicker(),
      el('div', { class: 'section-label', text: 'Sound & motion' }),
      list,
      el('div', { class: 'section-label', text: 'Grown-ups' }),
      parentBtn,
      el('p', { class: 'coppa-note', text: '🛡️ Kid-safe & ad-free. Everything stays on this device.' }),
    ]);
    root.append(this.node);
    this.ctx.lumi.dock('corner');
  }

  /** Age chips 4–8 that set the starting difficulty. */
  _agePicker() {
    const current = this.ctx.settings.get('age');
    const row = el('div', { class: 'age-picker' });
    const hint = el('p', { class: 'age-hint', text: this._ageHint(current) });

    AGES.forEach((age) => {
      const chip = el('button', {
        class: 'age-chip' + (age === current ? ' selected' : ''),
        text: String(age),
        aria: { label: `${age} years old`, pressed: String(age === current) },
        onClick: () => {
          this.ctx.audio.pop();
          this.ctx.settings.set('age', age); // → ProgressService bumps every skill's level
          row.querySelectorAll('.age-chip').forEach((c) => {
            const on = c.textContent === String(age);
            c.classList.toggle('selected', on);
            c.setAttribute('aria-pressed', String(on));
          });
          hint.textContent = this._ageHint(age);
          const lvl = ageToStartLevel(age) + 1;
          this.ctx.lumi.celebrate(`Great! Starting at Level ${lvl} — let's grow! 🌱`);
        },
      });
      row.append(chip);
    });

    return el('div', {}, [row, hint]);
  }

  _ageHint(age) {
    if (!age) return 'Pick an age to set the starting level. Older gardeners begin at a higher level.';
    const lvl = ageToStartLevel(age) + 1;
    return `Age ${age}: activities start at Level ${lvl} of 4 and keep adapting as you play.`;
  }

  _toggle({ key, label, desc }) {
    const on = this.ctx.settings.get(key);
    const sw = el('button', {
      class: 'switch' + (on ? ' on' : ''),
      role: 'switch',
      aria: { checked: String(on), label },
    }, [el('span', { class: 'knob' })]);
    sw.addEventListener('click', () => {
      const v = !this.ctx.settings.get(key);
      this.ctx.settings.set(key, v);
      sw.classList.toggle('on', v);
      sw.setAttribute('aria-checked', String(v));
      this.ctx.audio.resume();
      this.ctx.audio.tap();
      if (key === 'music') this.ctx.audio.syncMusic();
      if (key === 'narration' && v) this.ctx.narration.say('Voice narration is on!');
    });
    return el('div', { class: 'setting-item' }, [el('div', { class: 'setting-text' }, [el('div', { class: 'setting-label', text: label }), el('div', { class: 'setting-desc', text: desc })]), sw]);
  }

  _enterParent() {
    const s = this.ctx.settings;
    // First time: let the parent create a PIN. Otherwise: verify it.
    if (!s.hasPin()) {
      this._pinDialog('Create a 4-digit Parent PIN', (pin) => {
        if (/^\d{4}$/.test(pin)) {
          s.setPin(pin);
          this.ctx.app.openParentDashboard();
          return true;
        }
        return false;
      });
    } else {
      this._pinDialog('Enter Parent PIN', (pin) => {
        if (s.checkPin(pin)) {
          this.ctx.app.openParentDashboard();
          return true;
        }
        return false;
      });
    }
  }

  _pinDialog(title, onSubmit) {
    const input = el('input', { class: 'pin-input', type: 'tel', inputmode: 'numeric', maxlength: '4', pattern: '\\d*', placeholder: '••••' });
    const err = el('div', { class: 'pin-err' });
    Modal.open({
      title,
      body: el('div', {}, [input, err]),
      actions: [
        { label: 'Cancel' },
        {
          label: 'OK',
          primary: true,
          // Return false to keep the dialog open on a bad PIN; a correct PIN
          // returns true so the Modal auto-closes and the dashboard shows.
          onClick: () => {
            if (onSubmit(input.value)) return true;
            err.textContent = 'Hmm, try again.';
            input.value = '';
            input.focus();
            return false;
          },
        },
      ],
    });
    setTimeout(() => input.focus(), 100);
  }

  unmount() {}
}
