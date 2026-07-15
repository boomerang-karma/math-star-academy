/**
 * StorageService.js — namespaced, JSON-safe wrapper around localStorage.
 *
 * All persistence flows through here so that "where does saved data live" is a
 * single, swappable decision. To move to IndexedDB or a native store later,
 * reimplement these four methods; nothing else in the app touches storage.
 *
 * Everything stays on-device (COPPA requirement — no data leaves without
 * explicit parent action, which this app never takes).
 */
const NS = 'lumi:';

export default class StorageService {
  constructor() {
    this.available = this._probe();
    this._memory = new Map(); // fallback if localStorage is blocked (private mode)
  }

  _probe() {
    try {
      const k = NS + '__probe__';
      localStorage.setItem(k, '1');
      localStorage.removeItem(k);
      return true;
    } catch {
      console.warn('[Storage] localStorage unavailable — using in-memory fallback');
      return false;
    }
  }

  get(key, fallback = null) {
    try {
      const raw = this.available ? localStorage.getItem(NS + key) : this._memory.get(key);
      return raw == null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  }

  set(key, value) {
    const raw = JSON.stringify(value);
    if (this.available) localStorage.setItem(NS + key, raw);
    else this._memory.set(key, raw);
    return value;
  }

  remove(key) {
    if (this.available) localStorage.removeItem(NS + key);
    else this._memory.delete(key);
  }

  /** Wipe every Lumi key — used by the parent dashboard "reset" control. */
  clearAll() {
    if (this.available) {
      Object.keys(localStorage)
        .filter((k) => k.startsWith(NS))
        .forEach((k) => localStorage.removeItem(k));
    }
    this._memory.clear();
  }
}
