/**
 * SettingsService.js — accessibility + parental configuration.
 *
 * Holds the small set of toggles the spec calls for (reduced motion, high
 * contrast, large text, narration/music/sfx on-off) plus the parent PIN gate.
 * Applies visual settings to <html> as data-* attributes so CSS can react
 * without any per-component wiring.
 */
const DEFAULTS = {
  reducedMotion: false,
  highContrast: false,
  largeText: false,
  narration: true,
  music: true,
  sfx: true,
  childName: '',
  age: null, // 4–8; sets starting difficulty. null = youngest/gentlest.
  parentPin: '', // empty until a parent sets one
};

export default class SettingsService {
  constructor(storage, bus) {
    this.storage = storage;
    this.bus = bus;
    this._data = { ...DEFAULTS, ...(storage.get('settings') || {}) };
    // Respect the OS reduced-motion preference on first run.
    if (storage.get('settings') === null && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      this._data.reducedMotion = true;
    }
    this.apply();
  }

  get(key) {
    return this._data[key];
  }

  set(key, value) {
    this._data[key] = value;
    this.storage.set('settings', this._data);
    this.apply();
    this.bus.emit('settings:changed', { key, value });
  }

  all() {
    return { ...this._data };
  }

  /** Reflect visual settings onto the document root for CSS to consume. */
  apply() {
    const r = document.documentElement;
    r.dataset.reducedMotion = String(this._data.reducedMotion);
    r.dataset.highContrast = String(this._data.highContrast);
    r.dataset.largeText = String(this._data.largeText);
  }

  /* ---- Parent PIN gate -------------------------------------------- */
  hasPin() {
    return Boolean(this._data.parentPin);
  }

  setPin(pin) {
    this.set('parentPin', String(pin));
  }

  checkPin(pin) {
    return this.hasPin() && String(pin) === this._data.parentPin;
  }
}
