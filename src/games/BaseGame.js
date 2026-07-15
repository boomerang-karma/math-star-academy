/**
 * BaseGame.js — the contract every activity implements.
 *
 * This class carries all the machinery that should be identical across games
 * so individual game files stay tiny and focused purely on their own math &
 * interaction. It provides:
 *
 *   • a short 5-round session loop (the spec's 3–7 min play window)
 *   • the standard shell: top bar, Lumi instruction, play stage, next flow
 *   • zero-frustration scoring: children always finish a round; "mistakes"
 *     only cost sparkle-stars, never block progress
 *   • adaptive difficulty via ProgressService (level up on clean wins, ease
 *     down after repeated struggle)
 *   • celebratory feedback (particles, sound, Lumi dance) on every win
 *
 * A subclass MUST implement:
 *   setupRound()   build the interactive round inside `this.stage`
 *   get instruction() (or set this.instruction) — the spoken prompt
 * and SHOULD implement:
 *   get hint()     — a spoken hint when Lumi is tapped
 *
 * A subclass drives the loop by calling:
 *   this.registerMistake(msg?)   a wrong attempt (gentle, non-blocking)
 *   this.solved(opts?)           the round is complete & correct
 */
import { el, clear } from '../core/dom.js';
import TopBar from '../ui/TopBar.js';
import Modal from '../ui/Modal.js';
import { ROUNDS_PER_SESSION } from '../config/curriculum.js';
import { SKILLS } from '../config/curriculum.js';

export default class BaseGame {
  constructor(ctx, meta) {
    this.ctx = ctx;
    this.meta = meta; // { skillId, title, subtitle, sticker, emoji, accent }
    this.skillId = meta.skillId;
    this.roundIndex = 0;
    this.totalRounds = meta.rounds || ROUNDS_PER_SESSION;
    this.sessionStars = 0;
    this.cleanWins = 0;
    this._disposers = [];
    this._startTime = 0;
    this.locked = false; // true briefly during transitions to block input
  }

  /* ---- Scene lifecycle -------------------------------------------- */
  async mount(root) {
    this._startTime = Date.now();
    this.root = root;
    root.dataset.accent = this.meta.accent || 'green';

    this.topbar = new TopBar(this.ctx, {
      title: this.meta.title,
      onBack: () => this.ctx.app.goHome(),
    });
    this.topbar.setRounds(this.totalRounds, 0);

    this.instructionBar = el('div', { class: 'instruction-bar', aria: { live: 'polite' } });
    this.stage = el('div', { class: 'game-stage' });
    this.footer = el('div', { class: 'game-footer' });

    this.shell = el('div', { class: `game-shell game-${this.skillId}` }, [
      this.topbar.node,
      this.instructionBar,
      this.stage,
      this.footer,
    ]);
    root.append(this.shell);

    this.ctx.nav.hide();
    this.ctx.lumi.dock('game');
    this.ctx.lumi.setHint(() => this._speakHint());

    await this.onStart?.();
    this.nextRound();
  }

  async unmount() {
    this._disposers.forEach((d) => d());
    this._disposers = [];
    this.topbar?.destroy();
    this.ctx.lumi.clearHint();
    this.ctx.progress.addPlayTime(Date.now() - this._startTime);
    await this.onEnd?.();
  }

  /** Register a disposer to run on unmount (drag handlers, timers…). */
  track(disposer) {
    if (typeof disposer === 'function') this._disposers.push(disposer);
    return disposer;
  }

  /* ---- Round loop -------------------------------------------------- */
  nextRound() {
    if (this.roundIndex >= this.totalRounds) return this.finishSession();
    this.locked = false;
    this.mistakes = 0;
    this.hintUsed = false;
    this.level = this.ctx.progress.levelConfig(this.skillId);
    this.levelIndex = this.ctx.progress.levelIndex(this.skillId);
    clear(this.stage);
    clear(this.footer);
    this.topbar.setRounds(this.totalRounds, this.roundIndex);

    this.setupRound();

    // Speak the instruction and mirror it in the instruction bar.
    const text = this.instruction || '';
    this.instructionBar.textContent = text;
    this.ctx.lumi.point(text);
  }

  /** A wrong attempt: soft feedback, costs a star, never blocks the child. */
  registerMistake(message) {
    if (this.locked) return;
    this.mistakes += 1;
    this.ctx.audio.wrong();
    if (navigator.vibrate && !this.ctx.settings.get('reducedMotion')) navigator.vibrate(15);
    this.ctx.lumi.think(message || this._encourage());
    this.shell.classList.remove('shake');
    void this.shell.offsetWidth;
    if (!this.ctx.settings.get('reducedMotion')) this.shell.classList.add('shake');
  }

  /** The round is complete & correct. Handles scoring, reward, celebration. */
  solved({ point, message } = {}) {
    if (this.locked) return;
    this.locked = true;
    const clean = this.mistakes === 0 && !this.hintUsed;
    const stars = clean ? 3 : this.mistakes <= 2 ? 2 : 1;
    this.sessionStars += stars;
    if (clean) this.cleanWins += 1;

    // Record for adaptive difficulty + parent stats (won == clean first try).
    this.ctx.progress.recordRound(this.skillId, { won: clean, stars });
    const sparkles = 2 + stars; // 3–5 sparkles a round
    this.ctx.rewards.addSparkles(sparkles);
    this._maybeStickers();

    // Feedback: particles at the success point + Lumi dance.
    const p = point || this._stageCenter();
    this.ctx.particles.sparkleBurst(p.x, p.y, 20);
    this.ctx.particles.bloom(p.x, p.y, 'var(--accent)');
    this.ctx.audio.win();
    this.ctx.lumi.celebrate(message || this._praise());

    this.roundIndex += 1;
    this.topbar.setRounds(this.totalRounds, this.roundIndex);
    this._showNext();
  }

  _showNext() {
    clear(this.footer);
    const last = this.roundIndex >= this.totalRounds;
    const btn = el(
      'button',
      {
        class: 'btn btn-primary btn-next',
        onClick: () => {
          this.ctx.audio.pop();
          last ? this.finishSession() : this.nextRound();
        },
      },
      last ? 'Finish 🎉' : 'Next →'
    );
    this.footer.append(btn);
    // Auto-advance-friendly: focus the button so Enter works too.
    setTimeout(() => btn.focus(), 400);
  }

  /* ---- Session complete ------------------------------------------- */
  finishSession() {
    const maxStars = this.totalRounds * 3;
    const ratio = this.sessionStars / maxStars;
    const stars3 = ratio > 0.85 ? 3 : ratio > 0.5 ? 2 : 1;

    // Finishing any session earns the "first activity" sticker (idempotent),
    // then the zone's signature sticker, then the streak sticker.
    this.ctx.rewards.awardSticker('first-bloom');
    if (this.meta.sticker) this.ctx.rewards.awardSticker(this.meta.sticker);
    if (this.cleanWins >= 3) this.ctx.rewards.awardSticker('streak-3');

    this.ctx.particles.confetti(70);
    this.ctx.audio.win();

    const body = el('div', { class: 'session-summary' }, [
      el('div', { class: 'summary-stars', text: '⭐'.repeat(stars3) + '☆'.repeat(3 - stars3) }),
      el('p', { class: 'summary-line', text: `You earned ${this.sessionStars} sparkle stars!` }),
      el('p', { class: 'summary-bloom', text: SKILLS[this.skillId].bloom }),
    ]);

    this.ctx.lumi.say(`Wonderful work! ${SKILLS[this.skillId].bloom}`, { pose: 'cheer', hold: 5000 });

    Modal.open({
      title: '🌸 Garden Grew! 🌸',
      body,
      className: 'celebrate-modal',
      dismissible: false,
      actions: [
        { label: 'Play Again', onClick: () => this._replay() },
        { label: 'Back to Garden', primary: true, onClick: () => this.ctx.app.goHome() },
      ],
    });
  }

  _replay() {
    this.roundIndex = 0;
    this.sessionStars = 0;
    this.cleanWins = 0;
    this.nextRound();
  }

  /* ---- Sticker awards keyed to milestones ------------------------- */
  _maybeStickers() {
    const s = this.ctx.progress.skill(this.skillId);
    if (s.streak >= 7) this.ctx.rewards.awardSticker('streak-7');
    if (this.ctx.progress.gardenBloom() >= 0.999) this.ctx.rewards.awardSticker('full-bloom');
  }

  /* ---- Small shared helpers --------------------------------------- */
  _speakHint() {
    this.hintUsed = true;
    this.ctx.lumi.think(this.hint || "Look carefully — you can do it!");
  }

  _stageCenter() {
    const r = this.stage.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  _praise() {
    return this.ctx.pick(['Yay! You did it! 🎉', 'Beautiful work!', 'The garden is so happy!', 'Perfect! ✨', 'You are amazing!', 'Hooray! 🌟']);
  }
  _encourage() {
    return this.ctx.pick(['Ooh, try again!', 'Almost! Give it another go.', "That's okay — try once more!", 'So close! You can do it.']);
  }

  /* subclasses override */
  get instruction() {
    return this._instruction || '';
  }
  set instruction(v) {
    this._instruction = v;
  }
  get hint() {
    return this._hint || '';
  }
  set hint(v) {
    this._hint = v;
  }
}
