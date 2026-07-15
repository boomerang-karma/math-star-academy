/**
 * SceneManager.js — owns the single #stage element and swaps scenes in/out.
 *
 * A "scene" is any object with `mount(root)` and `unmount()`. Scenes include
 * the garden map, journal, profile, settings, parent dashboard, and — while a
 * child is playing — a live game instance. The manager guarantees the previous
 * scene is torn down before the next mounts, and applies a gentle transition
 * (skipped when the child has reduced-motion on).
 */
import { clear } from './dom.js';

export default class SceneManager {
  constructor(rootEl, bus, settings) {
    this.root = rootEl;
    this.bus = bus;
    this.settings = settings;
    this.current = null;
    this.currentName = null;
  }

  async show(name, scene) {
    // Tear down the outgoing scene.
    if (this.current) {
      try {
        await this.current.unmount?.();
      } catch (err) {
        console.error('[SceneManager] unmount failed', err);
      }
    }

    const reduce = this.settings?.get('reducedMotion');
    if (!reduce) {
      this.root.classList.remove('scene-in');
      // force reflow so the animation re-triggers
      void this.root.offsetWidth;
    }

    clear(this.root);
    this.current = scene;
    this.currentName = name;

    await scene.mount?.(this.root);

    if (!reduce) this.root.classList.add('scene-in');
    this.bus.emit('scene:change', { name });
    this.root.scrollTop = 0;
  }
}
