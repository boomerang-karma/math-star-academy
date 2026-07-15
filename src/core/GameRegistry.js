/**
 * GameRegistry.js — the plug-in system for activities.
 *
 * This is the heart of the "add an advanced game in a separate file" goal.
 * A game is just a module that default-exports a class extending BaseGame and
 * a small metadata object. To add a game you:
 *
 *   1. create src/games/MyGame.js
 *   2. import it in src/config/zones.js and give it a zone entry
 *
 * Nothing else in the engine needs to change. The registry validates that a
 * game satisfies the BaseGame contract before it is allowed in, so a broken
 * plug-in fails loudly at registration instead of mysteriously at runtime.
 */
export default class GameRegistry {
  constructor() {
    this._games = new Map(); // id -> { id, GameClass, meta }
  }

  /**
   * @param {string} id           unique id, e.g. 'counting-meadow'
   * @param {class}  GameClass     class extending BaseGame
   * @param {object} meta          { title, skillId, ... } display metadata
   */
  register(id, GameClass, meta = {}) {
    if (this._games.has(id)) throw new Error(`[GameRegistry] duplicate game id "${id}"`);
    for (const method of ['mount', 'unmount']) {
      if (typeof GameClass.prototype[method] !== 'function') {
        throw new Error(`[GameRegistry] game "${id}" is missing required method ${method}()`);
      }
    }
    this._games.set(id, { id, GameClass, meta });
    return this;
  }

  has(id) {
    return this._games.has(id);
  }

  get(id) {
    return this._games.get(id);
  }

  list() {
    return [...this._games.values()];
  }

  /** Instantiate a game with the shared service context. */
  create(id, ctx) {
    const entry = this._games.get(id);
    if (!entry) throw new Error(`[GameRegistry] unknown game "${id}"`);
    return new entry.GameClass(ctx, entry.meta);
  }
}
