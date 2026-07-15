/**
 * NarrationService.js — full voice narration via the Web Speech API.
 *
 * The spec asks for "full voice narration for every instruction and
 * celebration." SpeechSynthesis ships in every modern browser and works
 * offline once voices are installed, so no audio recording is needed. We pick
 * the warmest-sounding available voice and speak at a child-friendly pace.
 *
 * If narration is unavailable or disabled, every method is a graceful no-op,
 * so callers can always `narration.say(...)` without guarding.
 */
export default class NarrationService {
  constructor(settings, bus) {
    this.settings = settings;
    this.bus = bus;
    this.synth = window.speechSynthesis || null;
    this.voice = null;
    this._queue = [];
    if (this.synth) {
      this._pickVoice();
      // voices load asynchronously in some browsers
      this.synth.addEventListener?.('voiceschanged', () => this._pickVoice());
    }
    // When the child turns narration off mid-sentence, stop immediately.
    bus.on('settings:changed', ({ key }) => {
      if (key === 'narration' && !settings.get('narration')) this.cancel();
    });
  }

  _pickVoice() {
    if (!this.synth) return;
    const voices = this.synth.getVoices();
    if (!voices.length) return;
    // Prefer a female/warm English voice; fall back to first English, then any.
    const prefer = [/samantha/i, /female/i, /karen/i, /moira/i, /tessa/i, /google uk english female/i, /zira/i];
    this.voice =
      prefer.map((rx) => voices.find((v) => rx.test(v.name))).find(Boolean) ||
      voices.find((v) => /^en/i.test(v.lang)) ||
      voices[0];
  }

  /**
   * Speak a line. Options:
   *   interrupt — cancel anything currently speaking (default true)
   *   rate/pitch — override the gentle defaults
   *   onEnd — callback when finished
   */
  say(text, { interrupt = true, rate = 0.95, pitch = 1.15, onEnd } = {}) {
    if (!this.synth || !this.settings.get('narration') || !text) {
      onEnd?.();
      return;
    }
    if (interrupt) this.cancel();
    const u = new SpeechSynthesisUtterance(text);
    if (this.voice) u.voice = this.voice;
    u.rate = rate;
    u.pitch = pitch;
    u.volume = 1;
    u.onend = () => onEnd?.();
    u.onerror = () => onEnd?.();
    this.synth.speak(u);
    this.bus.emit('narration:speak', { text });
  }

  /** Speak several lines back-to-back with small gaps. */
  sayAll(lines, opts = {}) {
    lines = [].concat(lines).filter(Boolean);
    const next = (i) => {
      if (i >= lines.length) {
        opts.onEnd?.();
        return;
      }
      this.say(lines[i], { ...opts, interrupt: i === 0, onEnd: () => next(i + 1) });
    };
    next(0);
  }

  cancel() {
    this.synth?.cancel();
  }
}
