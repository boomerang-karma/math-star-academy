/**
 * ProgressService.js — mastery tracking + adaptive difficulty state.
 *
 * Stores, per skill: current level, stars earned, rounds won/played, a rolling
 * streak, and lifetime accuracy. This is the single source of truth the parent
 * dashboard reads and the garden's bloom level is derived from.
 *
 * Adaptive difficulty lives here (not in the games) so every activity levels
 * up and eases off with the same, gentle, child-friendly rules.
 */
import { SKILLS, LEVEL_UP_AFTER, LEVEL_DOWN_AFTER, ageToStartLevel } from '../config/curriculum.js';

function blankSkill() {
  return {
    level: 0,
    stars: 0,
    played: 0,
    won: 0,
    winsAtLevel: 0,
    missStreak: 0,
    bestStreak: 0,
    streak: 0,
    lastPlayed: null,
  };
}

export default class ProgressService {
  constructor(storage, bus, settings) {
    this.storage = storage;
    this.bus = bus;
    this.settings = settings;
    const saved = storage.get('progress') || {};
    this.data = {};
    for (const id of Object.keys(SKILLS)) this.data[id] = { ...blankSkill(), ...(saved[id] || {}) };
    this.totalPlayTimeMs = storage.get('playtime') || 0;

    // Apply the age-based starting level, and re-apply whenever a grown-up
    // changes the child's age in Settings.
    this.applyAgeFloor();
    bus.on('settings:changed', ({ key }) => {
      if (key === 'age') this.applyAgeFloor(true);
    });
  }

  /**
   * Raise each skill to at least the level implied by the child's age.
   * @param {boolean} announce  emit an event so the UI can react/celebrate.
   */
  applyAgeFloor(announce = false) {
    const floor = ageToStartLevel(this.settings?.get('age'));
    if (!floor) return;
    let bumped = false;
    for (const id of Object.keys(SKILLS)) {
      if (SKILLS[id].levels.length <= 1) continue; // skip free-play skills
      const s = this.skill(id);
      const target = Math.min(floor, this.maxLevel(id));
      if (s.level < target) {
        s.level = target;
        s.winsAtLevel = 0;
        s.missStreak = 0;
        bumped = true;
      }
    }
    if (bumped) this._save();
    if (announce) this.bus.emit('progress:agechanged', { floor, bumped });
  }

  _save() {
    this.storage.set('progress', this.data);
  }

  skill(id) {
    return this.data[id] || (this.data[id] = blankSkill());
  }

  /** Current adaptive level config for a skill. */
  levelConfig(id) {
    const s = this.skill(id);
    const levels = SKILLS[id].levels;
    return levels[Math.min(s.level, levels.length - 1)];
  }

  levelIndex(id) {
    return this.skill(id).level;
  }

  maxLevel(id) {
    return SKILLS[id].levels.length - 1;
  }

  /** Record the result of one round and run the adaptive-difficulty rules. */
  recordRound(id, { won, stars = 0 }) {
    const s = this.skill(id);
    s.played += 1;
    s.lastPlayed = Date.now();
    if (won) {
      s.won += 1;
      s.stars += stars;
      s.streak += 1;
      s.bestStreak = Math.max(s.bestStreak, s.streak);
      s.missStreak = 0;
      s.winsAtLevel += 1;
      if (s.winsAtLevel >= LEVEL_UP_AFTER && s.level < this.maxLevel(id)) {
        s.level += 1;
        s.winsAtLevel = 0;
        this.bus.emit('progress:levelup', { skillId: id, level: s.level });
      }
    } else {
      s.streak = 0;
      s.missStreak += 1;
      s.winsAtLevel = Math.max(0, s.winsAtLevel - 1);
      if (s.missStreak >= LEVEL_DOWN_AFTER && s.level > 0) {
        s.level -= 1;
        s.missStreak = 0;
        this.bus.emit('progress:leveldown', { skillId: id, level: s.level });
      }
    }
    this._save();
    this.bus.emit('progress:updated', { skillId: id, skill: { ...s } });
    return s;
  }

  addPlayTime(ms) {
    this.totalPlayTimeMs += ms;
    this.storage.set('playtime', this.totalPlayTimeMs);
  }

  accuracy(id) {
    const s = this.skill(id);
    return s.played ? Math.round((s.won / s.played) * 100) : 0;
  }

  totalStars() {
    return Object.values(this.data).reduce((n, s) => n + s.stars, 0);
  }

  /** 0..1 overall mastery — drives how lush the garden map looks. */
  gardenBloom() {
    const ids = Object.keys(SKILLS);
    const perSkill = ids.map((id) => (this.skill(id).level + (this.skill(id).winsAtLevel / LEVEL_UP_AFTER)) / (this.maxLevel(id) + 1));
    return perSkill.reduce((a, b) => a + b, 0) / ids.length;
  }

  /** Per-skill bloom 0..1 for the map zones. */
  skillBloom(id) {
    const s = this.skill(id);
    return Math.min(1, (s.level + s.winsAtLevel / LEVEL_UP_AFTER) / (this.maxLevel(id) + 1));
  }

  reset() {
    for (const id of Object.keys(SKILLS)) this.data[id] = blankSkill();
    this.totalPlayTimeMs = 0;
    this.storage.set('playtime', 0);
    this.applyAgeFloor(); // keep the age-based starting level after a reset
    this._save();
    this.bus.emit('progress:reset');
  }
}
