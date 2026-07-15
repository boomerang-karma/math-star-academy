/**
 * App.js — the composition root.
 *
 * Instantiates every service, assembles the shared `ctx` (the only object games
 * and scenes receive), wires cross-cutting reactions (sticker toasts, level-up
 * cheers), and owns top-level navigation. Because every dependency is created
 * here and passed down through `ctx`, any service can be swapped for another
 * implementation by editing this one file.
 */
import EventBus from './EventBus.js';
import SceneManager from './SceneManager.js';
import GameRegistry from './GameRegistry.js';
import { el, pick, randInt, shuffle, clamp } from './dom.js';

import StorageService from '../services/StorageService.js';
import SettingsService from '../services/SettingsService.js';
import AudioService from '../services/AudioService.js';
import NarrationService from '../services/NarrationService.js';
import ProgressService from '../services/ProgressService.js';
import RewardService from '../services/RewardService.js';
import ParticleService from '../services/ParticleService.js';

import Lumi from '../ui/Lumi.js';
import BottomNav from '../ui/BottomNav.js';
import Modal from '../ui/Modal.js';

import GardenMapScene from '../scenes/GardenMapScene.js';
import JournalScene from '../scenes/JournalScene.js';
import ProfileScene from '../scenes/ProfileScene.js';
import SettingsScene from '../scenes/SettingsScene.js';
import ParentDashboardScene from '../scenes/ParentDashboardScene.js';

import { registerAllGames } from '../config/zones.js';

export default class App {
  constructor(mountEl) {
    this.rootEl = mountEl;
    this._build();
  }

  _build() {
    const bus = new EventBus();
    const storage = new StorageService();
    const settings = new SettingsService(storage, bus);
    const audio = new AudioService(settings);
    const narration = new NarrationService(settings, bus);
    const progress = new ProgressService(storage, bus, settings);
    const rewards = new RewardService(storage, bus);

    // ---- DOM shell ----
    this.rootEl.innerHTML = '';
    this.stageEl = el('main', { id: 'stage', class: 'stage' });
    this.particleCanvas = el('canvas', { id: 'fx', class: 'fx-canvas' });
    const particles = new ParticleService(this.particleCanvas, settings);

    // Shared context handed to every scene & game.
    this.ctx = {
      app: this,
      bus,
      storage,
      settings,
      audio,
      narration,
      progress,
      rewards,
      particles,
      registry: new GameRegistry(),
      pick,
      randInt,
      shuffle,
      clamp,
    };

    const lumi = new Lumi(this.ctx);
    const nav = new BottomNav(this.ctx, (tab) => this.goToTab(tab));
    this.ctx.lumi = lumi;
    this.ctx.nav = nav;

    this.scenes = new SceneManager(this.stageEl, bus, settings);

    registerAllGames(this.ctx.registry);

    this.rootEl.append(this.particleCanvas, this.stageEl, lumi.node, nav.node);

    this._wireReactions();
    this._resumeAudioOnFirstGesture();
    this._showSplash();
  }

  /* ---- Cross-cutting reactions ------------------------------------ */
  _wireReactions() {
    const { bus, lumi, audio } = this.ctx;

    bus.on('reward:sticker', ({ sticker }) => this._stickerToast(sticker));
    bus.on('reward:unlock', ({ unlockable }) => this._toast(`🎁 Unlocked ${unlockable.name}!`));

    bus.on('progress:levelup', ({ skillId }) => {
      audio.sparkle();
      lumi.say('Wow, you leveled up! A tougher, more fun challenge! 🌟', { pose: 'cheer', hold: 3500 });
    });

    bus.on('scene:change', ({ name }) => {
      if (['garden', 'journal', 'profile', 'settings'].includes(name)) this.ctx.nav.show();
      this.ctx.nav.setActive(name === 'parent' ? 'settings' : name);
    });
  }

  _stickerToast(sticker) {
    this.ctx.audio.chime();
    this.ctx.particles.confetti(28);
    const body = el('div', { class: 'sticker-reveal' }, [
      el('div', { class: 'reveal-emoji pop-in', text: sticker.emoji }),
      el('div', { class: 'reveal-name', text: sticker.name }),
      el('div', { class: 'reveal-sub', text: 'New sticker for your journal!' }),
    ]);
    Modal.open({ title: '⭐ New Sticker! ⭐', body, className: 'sticker-modal', actions: [{ label: 'Yay!', primary: true }] });
  }

  _toast(text) {
    const t = el('div', { class: 'toast', text });
    this.rootEl.append(t);
    requestAnimationFrame(() => t.classList.add('show'));
    setTimeout(() => {
      t.classList.remove('show');
      setTimeout(() => t.remove(), 300);
    }, 2400);
  }

  /* ---- Audio unlock ----------------------------------------------- */
  _resumeAudioOnFirstGesture() {
    const unlock = () => {
      this.ctx.audio.resume();
      if (this.ctx.settings.get('music')) this.ctx.audio.startMusic();
    };
    window.addEventListener('pointerdown', unlock, { once: true });
    window.addEventListener('keydown', unlock, { once: true });
  }

  _showSplash() {
    const splash = el('div', { class: 'splash' }, [
      el('div', { class: 'splash-lumi', html: this.ctx.lumi.avatar.innerHTML }),
      el('h1', { class: 'splash-title', text: "Lumi's Math Garden" }),
      el('p', { class: 'splash-sub', text: 'A magical place to play with numbers 🌷' }),
      el('button', {
        class: 'btn btn-primary btn-enter',
        text: 'Enter the Garden 🌸',
        onClick: () => {
          this.ctx.audio.resume();
          if (this.ctx.settings.get('music')) this.ctx.audio.startMusic();
          this.ctx.narration.say("Welcome to Lumi's Math Garden! Let's play!");
          splash.classList.add('leaving');
          setTimeout(() => {
            splash.remove();
            this.goToTab('garden');
          }, 500);
        },
      }),
    ]);
    this.ctx.nav.hide();
    this.rootEl.append(splash);
  }

  /* ---- Navigation -------------------------------------------------- */
  goToTab(tab) {
    this.ctx.lumi.dock('corner');
    const map = {
      garden: () => new GardenMapScene(this.ctx),
      journal: () => new JournalScene(this.ctx),
      profile: () => new ProfileScene(this.ctx),
      settings: () => new SettingsScene(this.ctx),
    };
    const make = map[tab] || map.garden;
    this.scenes.show(tab, make());
  }

  goHome() {
    this.goToTab('garden');
  }

  openZone(id) {
    const game = this.ctx.registry.create(id, this.ctx);
    this.scenes.show(id, game);
  }

  openParentDashboard() {
    this.scenes.show('parent', new ParentDashboardScene(this.ctx));
  }
}
