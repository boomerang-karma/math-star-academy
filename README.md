# 🧚 Lumi's Math Garden

A magical, graphical math-learning app for children **ages 4–8**, built to the
_Lumi's Math Garden_ specification. Children play in an enchanted garden that
literally grows as they learn — counting critters, combining fruit, sharing
berries, building shapes, extending patterns, comparing groups, and free-playing
in a greenhouse — guided by **Lumi**, a glowing pixie mascot.

It is a **zero-build, offline-first web app**: no framework, no bundler, no
network. Open it and it runs. Every graphic is inline SVG, every sound is
synthesized live, and narration uses the browser's speech engine.

---

## Quick start

```bash
cd MathGame
python3 serve.py 4173        # any static server works; this one sets correct MIME types
# open http://localhost:4173
```

> ES modules must be served over http(s), not opened as `file://`.
> `serve.py` also disables caching so edits show up immediately.

No dependencies. No `npm install`. Works fully offline once loaded (a service
worker precaches the shell).

---

## Why this architecture

The brief asked for something **"highly interactive and modular… that can be
tweaked in separate services or advanced games into separate files."** So the
app is built around two extension points:

1. **Services** — every cross-cutting concern (audio, narration, storage,
   progress, rewards, particles, settings) is an isolated class behind a small
   interface. Swap any one without touching the rest.
2. **Games** — every activity is a self-contained file extending `BaseGame` and
   registered in one place. Adding a game is _one new file + one array entry_.

Nothing talks to anything else directly: services communicate via an
`EventBus`, and everyone receives the same shared `ctx` object.

---

## Project layout

```
MathGame/
├── index.html               # shell: mounts #app, links the 4 stylesheets
├── serve.py                 # zero-dependency dev server (correct MIME + no-store)
├── sw.js                    # offline service worker (network-first, cache fallback)
├── manifest.webmanifest     # installable PWA metadata
├── assets/
│   └── svg.js               # ALL artwork: Lumi, critters, fruit, animals, shapes…
├── styles/
│   ├── base.css             # design tokens, reset, layout, shared animations
│   ├── themes.css           # per-zone accents, day/night sky, high-contrast
│   ├── components.css       # buttons, Lumi, nav, modals, map, journal, profile…
│   └── games.css            # each activity's board
└── src/
    ├── main.js              # entry point
    ├── config/
    │   ├── curriculum.js    # the LEARNING MODEL as data (skills + difficulty ladders)
    │   └── zones.js         # the GARDEN MAP as data (couples zones ↔ games)  ← add games here
    ├── core/
    │   ├── App.js           # composition root: builds services + ctx, owns navigation
    │   ├── EventBus.js      # pub/sub
    │   ├── SceneManager.js  # swaps scenes in/out of #stage
    │   ├── GameRegistry.js  # plug-in registry (validates the BaseGame contract)
    │   ├── dom.js           # el(), shuffle(), randInt()… tiny helpers
    │   └── drag.js          # unified pointer drag-and-drop (touch + mouse)
    ├── services/
    │   ├── StorageService.js      # namespaced localStorage (all data stays on-device)
    │   ├── SettingsService.js     # accessibility toggles + parent PIN
    │   ├── AudioService.js        # WebAudio-synthesized music & SFX (no files)
    │   ├── NarrationService.js    # Web Speech API voice narration
    │   ├── ProgressService.js     # mastery tracking + adaptive difficulty
    │   ├── RewardService.js       # sparkles, stickers, unlockables
    │   └── ParticleService.js     # canvas sparkles / confetti / blooms
    ├── ui/
    │   ├── Lumi.js          # the mascot (poses, speech bubble, hints, celebrations)
    │   ├── TopBar.js        # in-game header (back, sparkles, round pips)
    │   ├── BottomNav.js     # Garden | Journal | Profile | Settings
    │   └── Modal.js         # accessible dialog
    ├── scenes/
    │   ├── GardenMapScene.js       # home: tappable zones that bloom with progress
    │   ├── JournalScene.js         # sticker album + progress bars
    │   ├── ProfileScene.js         # stats + Sparkle Shop (cosmetics)
    │   ├── SettingsScene.js        # accessibility + parent-area entry
    │   └── ParentDashboardScene.js # PIN-gated reports in garden metaphors
    └── games/
        ├── BaseGame.js             # the contract every activity implements
        ├── CountingMeadow.js       # 1. counting / one-to-one / ten-frames
        ├── AdditionOrchard.js      # 2. addition (drag fruit → pot, number line)
        ├── BerrySharingGrove.js    # 3. subtraction, framed as sharing
        ├── ShapeGrove.js           # 4. build scenes + sort shapes
        ├── PatternPond.js          # 5. extend AB / ABC / AAB / ABB patterns
        ├── ComparisonHill.js       # 6. more / fewer / same
        └── CreativeGreenhouse.js   # 7. open-ended free play + "math compliments"
```

---

## How to add a **new game** (a "separate file")

1. **Create** `src/games/StarCounting.js`:

   ```js
   import BaseGame from './BaseGame.js';
   import { el, randInt } from '../core/dom.js';

   export default class StarCounting extends BaseGame {
     setupRound() {
       this.target = randInt(2, this.level.max);      // `this.level` = adaptive difficulty config
       this.instruction = `Tap ${this.target} stars!`; // spoken + shown automatically
       this.hint = 'Count them one by one.';

       let tapped = 0;
       for (let i = 0; i < this.target; i++) {
         const star = el('button', { class: 'critter', text: '⭐' });
         star.onclick = () => {
           if (++tapped === this.target) this.solved();  // win → sparkles, particles, Lumi dance
           else this.ctx.audio.count(tapped);
         };
         this.stage.append(star);
       }
     }
   }
   ```

   `BaseGame` gives you the session loop, scoring, adaptive difficulty, the top
   bar, celebration, and hint plumbing for free. You implement `setupRound()`
   and call `this.solved()` when the round is won (or `this.registerMistake()`
   for a gentle wrong attempt).

2. **Register** it in `src/config/zones.js` — add one entry to `ZONES`:

   ```js
   import StarCounting from '../games/StarCounting.js';
   // …
   {
     id: 'star-meadow', game: StarCounting,
     title: 'Star Meadow', tagline: 'Count the Stars',
     skillId: 'counting', sticker: 'ladybug-friend',
     emoji: '⭐', accent: 'meadow', map: { x: 34, y: 44, art: '🌟' },
   }
   ```

The garden map, journal, and parent dashboard all rebuild themselves from
`ZONES` — nothing else needs editing.

_(If your game teaches a brand-new skill, also add that skill's difficulty
ladder to `src/config/curriculum.js` under `SKILLS`.)_

---

## How to **swap a service**

Services are created in one place — `App._build()` — and passed to everyone via
`ctx`. To replace, say, narration with a recorded-audio implementation, write a
class with the same `say()/cancel()` methods and change one line:

```js
const narration = new MyRecordedNarration(settings, bus);  // was NarrationService
```

Because callers only depend on the method shape (and emit/listen on the
`EventBus`), nothing else changes.

### The shared `ctx`

Every scene and game receives:

```
ctx = { app, bus, storage, settings, audio, narration,
        progress, rewards, particles, registry,
        lumi, nav, pick, randInt, shuffle, clamp }
```

---

## Spec coverage

| Requirement | Where |
|---|---|
| 7 garden zones + bloom-on-progress map | `GardenMapScene`, `zones.js`, `ProgressService.gardenBloom()` |
| Concrete manipulatives before symbols | every game uses SVG objects; numerals revealed after |
| Drag / tap / arrange, big touch targets | `core/drag.js` + generous CSS hit areas |
| Lumi: demonstrates, encourages, celebrates | `ui/Lumi.js` |
| Voice narration for every instruction & win | `NarrationService` (Web Speech API) |
| Music + SFX (pops, chimes, sparkles) | `AudioService` (WebAudio synthesis) |
| Particle effects (sparkles, pollen, confetti) | `ParticleService` |
| Sparkles, stickers, unlockables, quests | `RewardService`, `JournalScene`, `ProfileScene` |
| Adaptive difficulty (level up / gentle ease) | `ProgressService` + `curriculum.js` |
| Parent dashboard, PIN-protected, garden metaphors | `SettingsScene` gate + `ParentDashboardScene` |
| Accessibility: reduced-motion, high-contrast, large-text | `SettingsService` → `<html data-*>` → CSS |
| Offline-first, COPPA-friendly, no ads, on-device only | `sw.js`, `StorageService`, zero network calls |

---

## Design tokens

All colors, radii, shadows and type live as CSS custom properties at the top of
`styles/base.css`. Re-skin the whole app by editing that block. Per-zone accent
palettes live in `styles/themes.css` (`[data-accent="…"]`).

---

## Notes & known trade-offs

- **Narration** depends on the OS having a speech voice installed; if none is
  available it degrades silently (bubbles still show the text).
- **Audio** unlocks on the first tap (browsers block autoplay) — that's what the
  splash "Enter the Garden" button is for.
- The service worker is **network-first** so updates ship immediately while
  online, and falls back to cache when offline. For a locked production build,
  switch it to cache-first and bump `CACHE` on each release.
