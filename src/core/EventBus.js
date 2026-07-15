/**
 * EventBus.js — a tiny synchronous publish/subscribe bus.
 *
 * Services and scenes never call each other directly; they emit and listen on
 * this bus. That keeps the graph acyclic and lets you swap any service for
 * another that emits the same events. Example events:
 *   'reward:sparkles'  { amount }
 *   'progress:updated' { skillId, stars }
 *   'settings:changed' { key, value }
 *   'scene:change'     { name }
 */
export default class EventBus {
  constructor() {
    this._listeners = new Map();
  }

  on(event, handler) {
    if (!this._listeners.has(event)) this._listeners.set(event, new Set());
    this._listeners.get(event).add(handler);
    return () => this.off(event, handler); // returns an unsubscribe fn
  }

  once(event, handler) {
    const off = this.on(event, (payload) => {
      off();
      handler(payload);
    });
    return off;
  }

  off(event, handler) {
    this._listeners.get(event)?.delete(handler);
  }

  emit(event, payload) {
    this._listeners.get(event)?.forEach((h) => {
      try {
        h(payload);
      } catch (err) {
        console.error(`[EventBus] handler for "${event}" threw`, err);
      }
    });
  }
}
