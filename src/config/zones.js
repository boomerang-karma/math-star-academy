/**
 * zones.js — the garden map, as data.
 *
 * This module is the ONE place that knows the full roster of activities. Each
 * zone couples a place on the map to a game class + display metadata. To add a
 * brand-new activity you:
 *
 *   1. write src/games/YourGame.js (extends BaseGame)
 *   2. import it here and append a zone entry
 *
 * The registry, garden map, journal and parent dashboard all build themselves
 * from this array — nothing else needs editing.
 */
import CountingMeadow from '../games/CountingMeadow.js';
import AdditionOrchard from '../games/AdditionOrchard.js';
import BerrySharingGrove from '../games/BerrySharingGrove.js';
import ShapeGrove from '../games/ShapeGrove.js';
import PatternPond from '../games/PatternPond.js';
import ComparisonHill from '../games/ComparisonHill.js';
import CreativeGreenhouse from '../games/CreativeGreenhouse.js';

export const ZONES = [
  {
    id: 'counting-meadow',
    game: CountingMeadow,
    title: 'Counting Meadow',
    tagline: 'Plant the Perfect Patch',
    skillId: 'counting',
    sticker: 'ladybug-friend',
    emoji: '🐞',
    accent: 'meadow',
    // position on the map (percent of the map area) + landmark art
    map: { x: 18, y: 30, art: '🌼' },
  },
  {
    id: 'addition-orchard',
    game: AdditionOrchard,
    title: 'Addition Orchard',
    tagline: 'Combine the Harvest',
    skillId: 'addition',
    sticker: 'harvest-hero',
    emoji: '🍎',
    accent: 'orchard',
    map: { x: 48, y: 22, art: '🌳' },
  },
  {
    id: 'berry-grove',
    game: BerrySharingGrove,
    title: 'Berry Sharing Grove',
    tagline: 'Sharing Makes the Garden Happy',
    skillId: 'subtraction',
    sticker: 'kind-heart',
    emoji: '🐰',
    accent: 'grove',
    map: { x: 74, y: 32, art: '🫐' },
  },
  {
    id: 'shape-grove',
    game: ShapeGrove,
    title: 'Shape Grove',
    tagline: 'Build Fairy Houses & Paths',
    skillId: 'shapes',
    sticker: 'master-builder',
    emoji: '🔷',
    accent: 'shapes',
    map: { x: 28, y: 58, art: '🏠' },
  },
  {
    id: 'pattern-pond',
    game: PatternPond,
    title: 'Pattern Pond',
    tagline: 'Design the Prettiest Flowerbed',
    skillId: 'patterns',
    sticker: 'pattern-artist',
    emoji: '🦋',
    accent: 'pond',
    map: { x: 60, y: 62, art: '💧' },
  },
  {
    id: 'comparison-hill',
    game: ComparisonHill,
    title: 'Comparison Hill',
    tagline: 'More, Fewer, or Same?',
    skillId: 'comparison',
    sticker: 'sharp-eye',
    emoji: '⚖️',
    accent: 'hill',
    map: { x: 84, y: 60, art: '⛰️' },
  },
  {
    id: 'greenhouse',
    game: CreativeGreenhouse,
    title: 'Creative Greenhouse',
    tagline: 'Free Play & Imagination',
    skillId: 'creative',
    sticker: 'green-thumb',
    emoji: '🌱',
    accent: 'greenhouse',
    map: { x: 48, y: 78, art: '🪴' },
    rounds: 1,
    freeplay: true,
  },
];

export const zoneById = (id) => ZONES.find((z) => z.id === id);
export const zoneBySkill = (skillId) => ZONES.find((z) => z.skillId === skillId);

/** Register every zone's game with a GameRegistry. */
export function registerAllGames(registry) {
  for (const z of ZONES) {
    registry.register(z.id, z.game, {
      skillId: z.skillId,
      title: z.title,
      subtitle: z.tagline,
      sticker: z.sticker,
      emoji: z.emoji,
      accent: z.accent,
      rounds: z.rounds,
      freeplay: z.freeplay,
    });
  }
  return registry;
}
