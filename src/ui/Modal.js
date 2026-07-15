/**
 * Modal.js — a generic, accessible overlay dialog.
 *
 * Used for the parent-PIN gate, the round-complete celebration, unlock
 * confirmations, and sticker reveals. Traps focus lightly, closes on backdrop
 * tap (when dismissible) and on Escape, and always restores focus afterwards.
 */
import { el } from '../core/dom.js';

export default class Modal {
  /**
   * @param {object} opts
   *   title, body (Node|string), actions [{label, primary, onClick, keep}],
   *   dismissible (backdrop/Esc closes), className, onClose
   */
  static open(opts = {}) {
    return new Modal(opts);
  }

  constructor({ title, body, actions = [], dismissible = true, className = '', onClose } = {}) {
    this._onClose = onClose;
    this._prevFocus = document.activeElement;

    const card = el('div', { class: `modal-card ${className}`, role: 'dialog', aria: { modal: 'true', label: title || 'Dialog' } });
    if (title) card.append(el('h2', { class: 'modal-title', text: title }));
    if (body) {
      const b = el('div', { class: 'modal-body' });
      b.append(body.nodeType ? body : el('p', { text: String(body) }));
      card.append(b);
    }
    if (actions.length) {
      const bar = el('div', { class: 'modal-actions' });
      for (const a of actions) {
        const btn = el('button', {
          class: 'btn ' + (a.primary ? 'btn-primary' : 'btn-ghost'),
          text: a.label,
          onClick: () => {
            const r = a.onClick?.();
            if (!a.keep && r !== false) this.close();
          },
        });
        bar.append(btn);
      }
      card.append(bar);
    }

    this.backdrop = el('div', { class: 'modal-backdrop' }, [card]);
    this.card = card;
    if (dismissible) {
      this.backdrop.addEventListener('pointerdown', (e) => {
        if (e.target === this.backdrop) this.close();
      });
    }
    this._onKey = (e) => {
      if (e.key === 'Escape' && dismissible) this.close();
    };
    document.addEventListener('keydown', this._onKey);

    document.body.append(this.backdrop);
    requestAnimationFrame(() => this.backdrop.classList.add('show'));
    card.querySelector('button, input, [tabindex]')?.focus();
  }

  close() {
    document.removeEventListener('keydown', this._onKey);
    this.backdrop.classList.remove('show');
    setTimeout(() => {
      this.backdrop.remove();
      this._prevFocus?.focus?.();
      this._onClose?.();
    }, 220);
  }
}
