/**
 * GardenMapScene.js — the home screen "garden map".
 *
 * An illustrated garden with a tappable landmark for each zone. Landmarks bloom
 * as the child masters that skill (more flowers, brighter, a level ribbon), and
 * the whole garden grows lusher with overall progress — the spec's primary
 * reward loop. Equipped garden decorations from the reward shop appear here too.
 */
import { el, fromHTML } from '../core/dom.js';
import { ZONES } from '../config/zones.js';
import { scenery } from '../../assets/svg.js';
import { UNLOCKABLES } from '../services/RewardService.js';

export default class GardenMapScene {
  constructor(ctx) {
    this.ctx = ctx;
  }

  mount(root) {
    const bloom = this.ctx.progress.gardenBloom();
    const timeOfDay = this._timeOfDay();

    this.node = el('div', { class: 'garden-map', dataset: { tod: timeOfDay } });
    this.node.style.setProperty('--bloom', bloom.toFixed(2));

    // Sky & scenery
    const sky = el('div', { class: 'map-sky' }, [
      fromHTML(scenery.sun()),
      el('div', { class: 'cloud cloud-1', html: scenery.cloud() }),
      el('div', { class: 'cloud cloud-2', html: scenery.cloud() }),
    ]);
    const ground = el('div', { class: 'map-ground' });

    // Greeting banner
    const name = this.ctx.settings.get('childName');
    const banner = el('div', { class: 'map-banner' }, [
      el('h1', { class: 'map-title', text: "Lumi's Math Garden" }),
      el('p', { class: 'map-sub', text: name ? `Welcome back, ${name}! 🌸` : 'Tap a place to play! 🌸' }),
    ]);

    // Decorative blooms whose count scales with overall progress.
    const decor = el('div', { class: 'map-decor' });
    const flowerCount = Math.round(4 + bloom * 26);
    for (let i = 0; i < flowerCount; i++) {
      decor.append(
        el('span', {
          class: 'map-flower',
          text: this.ctx.pick(['🌷', '🌸', '🌼', '🌻', '🌹', '💐']),
          style: { left: 4 + Math.random() * 92 + '%', bottom: Math.random() * 26 + '%', fontSize: 18 + Math.random() * 18 + 'px', animationDelay: Math.random() * 3 + 's' },
        })
      );
    }

    // Equipped garden decorations from the shop.
    const equippedGarden = this.ctx.rewards.equipped.garden || [];
    const decoLayer = el('div', { class: 'map-unlocks' });
    equippedGarden.forEach((id, i) => {
      const u = UNLOCKABLES.find((x) => x.id === id);
      if (u) decoLayer.append(el('span', { class: 'map-unlock', text: u.emoji, style: { left: 10 + i * 22 + '%' } }));
    });

    // Zone landmarks
    const zonesLayer = el('div', { class: 'map-zones' });
    for (const z of ZONES) {
      zonesLayer.append(this._zoneNode(z));
    }

    this.node.append(sky, ground, decor, decoLayer, zonesLayer, banner);
    root.append(this.node);

    // Lumi greets from her corner.
    this.ctx.lumi.dock('corner');
    const greet = name ? `Hello ${name}! Where shall we play today?` : 'Welcome to the Math Garden! Tap a place to play.';
    setTimeout(() => this.ctx.lumi.say(greet, { hold: 5000 }), 300);
  }

  _zoneNode(z) {
    const skillBloom = this.ctx.progress.skillBloom(z.skillId);
    const level = this.ctx.progress.levelIndex(z.skillId);
    const maxLevel = this.ctx.progress.maxLevel(z.skillId);
    const stars = this.ctx.progress.skill(z.skillId).stars;

    const node = el('button', {
      class: 'map-zone',
      dataset: { accent: z.accent, id: z.id },
      style: { left: z.map.x + '%', top: z.map.y + '%' },
      aria: { label: `${z.title}. ${z.tagline}` },
    });
    node.style.setProperty('--zbloom', skillBloom.toFixed(2));

    const halo = el('div', { class: 'zone-halo' });
    const art = el('div', { class: 'zone-art', text: z.map.art });
    const badge = el('div', { class: 'zone-badge', text: z.emoji });
    const label = el('div', { class: 'zone-label', text: z.title });
    const ribbon = z.freeplay
      ? el('div', { class: 'zone-ribbon freeplay', text: 'Free Play' })
      : el('div', { class: 'zone-ribbon' }, [el('span', { class: 'lvl', text: `Lv ${level + 1}/${maxLevel + 1}` }), el('span', { class: 'zone-stars', text: stars ? `⭐${stars}` : '' })]);

    // little blooming flowers around a mastered zone
    const petals = el('div', { class: 'zone-petals' });
    const p = Math.round(skillBloom * 6);
    for (let i = 0; i < p; i++) {
      const a = (i / Math.max(1, p)) * Math.PI * 2;
      petals.append(el('span', { class: 'zone-petal', text: '🌸', style: { left: 50 + Math.cos(a) * 42 + '%', top: 50 + Math.sin(a) * 42 + '%' } }));
    }

    node.append(halo, petals, art, badge, label, ribbon);
    node.addEventListener('click', () => {
      this.ctx.audio.pop();
      const r = node.getBoundingClientRect();
      this.ctx.particles.sparkleBurst(r.left + r.width / 2, r.top + r.height / 2, 12);
      this.ctx.app.openZone(z.id);
    });
    return node;
  }

  _timeOfDay() {
    const h = new Date().getHours();
    if (h < 7) return 'dawn';
    if (h < 17) return 'day';
    if (h < 20) return 'dusk';
    return 'night';
  }

  unmount() {
    this.ctx.lumi.hideBubble();
  }
}
