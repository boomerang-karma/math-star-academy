/**
 * AudioService.js — all sound is synthesized live with the Web Audio API.
 *
 * Shipping zero audio files keeps the app tiny and fully offline. We generate:
 *   - gentle, looping background music (a soft pentatonic arpeggio pad)
 *   - short, delightful SFX (pops, chimes, sparkles, a "tada" for wins)
 *
 * The context is created lazily on the first user gesture (browsers block
 * autoplay), and every play respects the music/sfx settings toggles.
 */
const NOTE = { C4: 261.63, D4: 293.66, E4: 329.63, G4: 392.0, A4: 440.0, C5: 523.25, D5: 587.33, E5: 659.25, G5: 783.99, A5: 880.0 };
const PENTATONIC = [NOTE.C4, NOTE.D4, NOTE.E4, NOTE.G4, NOTE.A4, NOTE.C5, NOTE.D5, NOTE.E5];

export default class AudioService {
  constructor(settings) {
    this.settings = settings;
    this.ctx = null;
    this.master = null;
    this.musicGain = null;
    this._musicTimer = null;
    this._musicOn = false;
  }

  /** Must be called from a user gesture the first time. Safe to call again. */
  resume() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.9;
      this.master.connect(this.ctx.destination);
      this.musicGain = this.ctx.createGain();
      this.musicGain.gain.value = 0.0;
      this.musicGain.connect(this.master);
    }
    if (this.ctx.state === 'suspended') this.ctx.resume();
  }

  _env(node, gain, t, attack, decay) {
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay);
    node.connect(g);
    g.connect(this.master);
    return g;
  }

  _tone(freq, { type = 'sine', gain = 0.2, attack = 0.01, decay = 0.25, when = 0, glideTo = null } = {}) {
    if (!this.ctx || !this.settings.get('sfx')) return;
    const t = this.ctx.currentTime + when;
    const osc = this.ctx.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t);
    if (glideTo) osc.frequency.exponentialRampToValueAtTime(glideTo, t + attack + decay);
    this._env(osc, gain, t, attack, decay);
    osc.start(t);
    osc.stop(t + attack + decay + 0.05);
  }

  /* ---- Named sound effects ---------------------------------------- */
  pop() {
    this._tone(660, { type: 'triangle', gain: 0.22, attack: 0.005, decay: 0.12, glideTo: 880 });
  }
  tap() {
    this._tone(520, { type: 'sine', gain: 0.15, attack: 0.004, decay: 0.09 });
  }
  chime() {
    this._tone(NOTE.C5, { type: 'sine', gain: 0.18, decay: 0.4 });
    this._tone(NOTE.E5, { type: 'sine', gain: 0.14, decay: 0.4, when: 0.06 });
    this._tone(NOTE.G5, { type: 'sine', gain: 0.12, decay: 0.5, when: 0.12 });
  }
  sparkle() {
    [NOTE.G5, NOTE.A5, NOTE.E5].forEach((f, i) => this._tone(f * 1.5, { type: 'sine', gain: 0.08, attack: 0.003, decay: 0.18, when: i * 0.05 }));
  }
  wrong() {
    // Never harsh — a soft, low "try again" wobble, not a buzzer.
    this._tone(300, { type: 'sine', gain: 0.16, attack: 0.02, decay: 0.22, glideTo: 240 });
  }
  win() {
    const seq = [NOTE.C5, NOTE.E5, NOTE.G5, NOTE.C5 * 2];
    seq.forEach((f, i) => this._tone(f, { type: 'triangle', gain: 0.2, attack: 0.01, decay: 0.35, when: i * 0.12 }));
    this.sparkle();
  }
  count(n = 0) {
    // rising pitch as you count up
    this._tone(NOTE.C4 * Math.pow(2, (n % 8) / 12), { type: 'sine', gain: 0.16, decay: 0.16 });
  }

  /* ---- Ambient background music ----------------------------------- */
  startMusic() {
    if (!this.ctx || this._musicOn) return;
    if (!this.settings.get('music')) return;
    this._musicOn = true;
    this.musicGain.gain.cancelScheduledValues(this.ctx.currentTime);
    this.musicGain.gain.setTargetAtTime(0.12, this.ctx.currentTime, 1.5);

    let step = 0;
    const beat = 0.5;
    const schedule = () => {
      if (!this._musicOn) return;
      const t = this.ctx.currentTime;
      // soft pad chord every 4 beats
      if (step % 8 === 0) {
        [PENTATONIC[0], PENTATONIC[2], PENTATONIC[4]].forEach((f) => this._pad(f, t, beat * 8));
      }
      // gentle arpeggio melody
      const f = PENTATONIC[(step * 3) % PENTATONIC.length];
      this._arp(f, t);
      step++;
      this._musicTimer = setTimeout(schedule, beat * 1000);
    };
    schedule();
  }

  _pad(freq, t, dur) {
    const osc = this.ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.value = freq;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.05, t + 0.8);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(g);
    g.connect(this.musicGain);
    osc.start(t);
    osc.stop(t + dur + 0.1);
  }

  _arp(freq, t) {
    const osc = this.ctx.createOscillator();
    osc.type = 'triangle';
    osc.frequency.value = freq * 2;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.045, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.4);
    osc.connect(g);
    g.connect(this.musicGain);
    osc.start(t);
    osc.stop(t + 0.45);
  }

  stopMusic() {
    this._musicOn = false;
    clearTimeout(this._musicTimer);
    if (this.musicGain && this.ctx) this.musicGain.gain.setTargetAtTime(0.0001, this.ctx.currentTime, 0.6);
  }

  /** React to a settings toggle. */
  syncMusic() {
    if (this.settings.get('music')) this.startMusic();
    else this.stopMusic();
  }
}
