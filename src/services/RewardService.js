/**
 * RewardService.js — Magic Sparkles, the sticker journal, and unlockables.
 *
 * The spec's motivation system: children earn Sparkles (a soft currency),
 * collect themed stickers into a journal, and unlock cosmetic customizations
 * for Lumi and the garden. All cosmetic, all positive — there is no way to
 * "lose" anything.
 */
export const STICKERS = [
  { id: 'first-bloom', emoji: '🌸', name: 'First Bloom', hint: 'Finish your first activity' },
  { id: 'ladybug-friend', emoji: '🐞', name: 'Ladybug Friend', hint: 'Count in the Meadow' },
  { id: 'harvest-hero', emoji: '🍎', name: 'Harvest Hero', hint: 'Add in the Orchard' },
  { id: 'kind-heart', emoji: '🐰', name: 'Kind Heart', hint: 'Share in the Grove' },
  { id: 'master-builder', emoji: '🏠', name: 'Master Builder', hint: 'Build in Shape Grove' },
  { id: 'pattern-artist', emoji: '🦋', name: 'Pattern Artist', hint: 'Design at the Pond' },
  { id: 'sharp-eye', emoji: '👀', name: 'Sharp Eye', hint: 'Compare on the Hill' },
  { id: 'green-thumb', emoji: '🌱', name: 'Green Thumb', hint: 'Create in the Greenhouse' },
  { id: 'streak-3', emoji: '⭐', name: 'Triple Star', hint: 'Win 3 in a row' },
  { id: 'streak-7', emoji: '🌟', name: 'Lucky Seven', hint: 'Win 7 in a row' },
  { id: 'hundred-sparkles', emoji: '✨', name: 'Sparkle Collector', hint: 'Earn 100 Sparkles' },
  { id: 'full-bloom', emoji: '🌈', name: 'Full Bloom', hint: 'Grow every part of the garden' },
];

export const UNLOCKABLES = [
  { id: 'hat-flower', type: 'lumi', name: 'Flower Crown', emoji: '🌺', cost: 20 },
  { id: 'hat-star', type: 'lumi', name: 'Star Tiara', emoji: '⭐', cost: 40 },
  { id: 'wings-rainbow', type: 'lumi', name: 'Rainbow Wings', emoji: '🌈', cost: 60 },
  { id: 'wings-gold', type: 'lumi', name: 'Golden Wings', emoji: '💛', cost: 80 },
  { id: 'deco-fountain', type: 'garden', name: 'Sparkle Fountain', emoji: '⛲', cost: 30 },
  { id: 'deco-rainbow', type: 'garden', name: 'Garden Rainbow', emoji: '🌈', cost: 50 },
  { id: 'deco-lanterns', type: 'garden', name: 'Fairy Lanterns', emoji: '🏮', cost: 70 },
  { id: 'deco-pond', type: 'garden', name: 'Wishing Pond', emoji: '💧', cost: 90 },
];

export default class RewardService {
  constructor(storage, bus) {
    this.storage = storage;
    this.bus = bus;
    this.sparkles = storage.get('sparkles') ?? 0;
    this.stickers = new Set(storage.get('stickers') || []);
    this.unlocked = new Set(storage.get('unlocked') || []);
    this.equipped = storage.get('equipped') || { lumi: [], garden: [] };
  }

  _save() {
    this.storage.set('sparkles', this.sparkles);
    this.storage.set('stickers', [...this.stickers]);
    this.storage.set('unlocked', [...this.unlocked]);
    this.storage.set('equipped', this.equipped);
  }

  addSparkles(n) {
    this.sparkles += n;
    this._save();
    this.bus.emit('reward:sparkles', { amount: n, total: this.sparkles });
    if (this.sparkles >= 100) this.awardSticker('hundred-sparkles');
    return this.sparkles;
  }

  awardSticker(id) {
    if (!STICKERS.some((s) => s.id === id) || this.stickers.has(id)) return false;
    this.stickers.add(id);
    this._save();
    const sticker = STICKERS.find((s) => s.id === id);
    this.bus.emit('reward:sticker', { sticker });
    return true;
  }

  hasSticker(id) {
    return this.stickers.has(id);
  }

  canAfford(id) {
    const u = UNLOCKABLES.find((x) => x.id === id);
    return u && !this.unlocked.has(id) && this.sparkles >= u.cost;
  }

  unlock(id) {
    const u = UNLOCKABLES.find((x) => x.id === id);
    if (!u || this.unlocked.has(id) || this.sparkles < u.cost) return false;
    this.sparkles -= u.cost;
    this.unlocked.add(id);
    // auto-equip the newly unlocked cosmetic
    this.equip(id);
    this._save();
    this.bus.emit('reward:unlock', { unlockable: u });
    return true;
  }

  isUnlocked(id) {
    return this.unlocked.has(id);
  }

  equip(id) {
    const u = UNLOCKABLES.find((x) => x.id === id);
    if (!u || !this.unlocked.has(id)) return;
    // one item per slot family for lumi cosmetics of the same category
    const bucket = this.equipped[u.type];
    const idx = bucket.indexOf(id);
    if (idx >= 0) bucket.splice(idx, 1); // toggle off
    else bucket.push(id);
    this._save();
    this.bus.emit('reward:equip', { equipped: this.equipped });
  }

  isEquipped(id) {
    return Object.values(this.equipped).some((arr) => arr.includes(id));
  }

  reset() {
    this.sparkles = 0;
    this.stickers = new Set();
    this.unlocked = new Set();
    this.equipped = { lumi: [], garden: [] };
    this._save();
  }
}
