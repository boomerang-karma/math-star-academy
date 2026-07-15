/**
 * curriculum.js — the learning model, kept as data (not code).
 *
 * Each SKILL maps to one activity zone and defines its adaptive-difficulty
 * ladder. Games read `levels[levelIndex]` to size a round. Because difficulty
 * is data, designers can retune the whole game without touching game logic —
 * one of the "tweak in a service" goals.
 *
 * A `level` is an opaque config bag; each game interprets its own fields.
 */
export const SKILLS = {
  counting: {
    id: 'counting',
    name: 'Counting',
    bloom: 'Counting skills in full bloom!',
    levels: [
      { max: 5, tenFrame: false, matchNumeral: false },
      { max: 10, tenFrame: true, matchNumeral: false },
      { max: 15, tenFrame: true, matchNumeral: true },
      { max: 20, tenFrame: true, matchNumeral: true },
    ],
  },
  addition: {
    id: 'addition',
    name: 'Addition',
    bloom: 'Adding it all up beautifully!',
    levels: [
      { max: 5, numberLine: false },
      { max: 10, numberLine: true },
      { max: 15, numberLine: true },
      { max: 20, numberLine: true },
    ],
  },
  subtraction: {
    id: 'subtraction',
    name: 'Sharing',
    bloom: 'So generous — sharing beautifully!',
    levels: [
      { max: 5, animals: 1 },
      { max: 8, animals: 1 },
      { max: 10, animals: 2 },
      { max: 12, animals: 2 },
    ],
  },
  shapes: {
    id: 'shapes',
    name: 'Shapes',
    bloom: 'Building wonderful shapes!',
    levels: [
      { kinds: ['circle', 'square', 'triangle'], slots: 3 },
      { kinds: ['circle', 'square', 'triangle', 'rectangle'], slots: 4 },
      { kinds: ['circle', 'square', 'triangle', 'rectangle', 'star'], slots: 5 },
      { kinds: ['circle', 'square', 'triangle', 'rectangle', 'star', 'hexagon'], slots: 6 },
    ],
  },
  patterns: {
    id: 'patterns',
    name: 'Patterns',
    bloom: 'Making the prettiest patterns!',
    levels: [
      { type: 'AB', length: 4, choices: 2 },
      { type: 'ABC', length: 6, choices: 3 },
      { type: 'AAB', length: 6, choices: 3 },
      { type: 'ABB', length: 8, choices: 4 },
    ],
  },
  comparison: {
    id: 'comparison',
    name: 'Comparing',
    bloom: 'A sharp eye for more and less!',
    levels: [
      { max: 5, gap: 2 },
      { max: 8, gap: 2 },
      { max: 10, gap: 1 },
      { max: 12, gap: 1 },
    ],
  },
  creative: {
    id: 'creative',
    name: 'Creativity',
    bloom: 'A truly magical imagination!',
    levels: [{ freeplay: true }],
  },
};

/** Rounds a child must win at a level before it steps up. */
export const LEVEL_UP_AFTER = 3;
/** Consecutive misses before the game eases difficulty for gentle support. */
export const LEVEL_DOWN_AFTER = 3;
/** Rounds that make up one short (3–7 min) session per the spec. */
export const ROUNDS_PER_SESSION = 5;

/**
 * Age → starting difficulty level (0-based index into a skill's `levels`).
 *
 * The game always adapts up/down from wherever a child is, but starting an
 * older child at Level 1 wastes their time. Choosing an age sets a sensible
 * floor so, e.g., a 7-year-old begins at a genuinely harder level and a
 * 4-year-old starts gently. Skills with a single level (free play) ignore this.
 */
export const AGE_START_LEVEL = {
  4: 0, // Level 1 of 4 — gentlest start
  5: 0,
  6: 1, // Level 2 of 4
  7: 2, // Level 3 of 4 — higher, as expected for a 7-year-old
  8: 3, // Level 4 of 4 — hardest tier
};

/** Ages offered in the picker. */
export const AGES = [4, 5, 6, 7, 8];

/** Map a stored age to its starting level (0 when unset/unknown). */
export const ageToStartLevel = (age) => AGE_START_LEVEL[age] ?? 0;
