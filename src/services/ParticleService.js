/**
 * ParticleService.js — a full-screen canvas particle layer.
 *
 * Sits above everything (pointer-events: none) and paints the sparkle, pollen,
 * confetti and bloom bursts that make success feel magical. One shared rAF loop
 * drives all particles; when none are alive the loop parks itself to save
 * battery. Honours the reduced-motion setting by drastically thinning output.
 */
export default class ParticleService {
  constructor(canvas, settings) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.settings = settings;
    this.particles = [];
    this._raf = null;
    this._last = 0;
    this._resize = this._resize.bind(this);
    window.addEventListener('resize', this._resize);
    this._resize();
    // A gentle, ever-present drift of pollen motes in the background.
    this._ambientTimer = setInterval(() => this._ambient(), 900);
  }

  _resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = window.innerWidth * dpr;
    this.canvas.height = window.innerHeight * dpr;
    this.canvas.style.width = window.innerWidth + 'px';
    this.canvas.style.height = window.innerHeight + 'px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  _reduced() {
    return this.settings?.get('reducedMotion');
  }

  _ambient() {
    if (this._reduced() || document.hidden) return;
    const w = window.innerWidth;
    this._spawn(1, {
      x: Math.random() * w,
      y: window.innerHeight + 10,
      vy: -0.25 - Math.random() * 0.35,
      vx: (Math.random() - 0.5) * 0.2,
      size: 2 + Math.random() * 3,
      life: 6000,
      color: 'rgba(255,244,184,0.7)',
      shape: 'dot',
      gravity: 0,
      fade: true,
    });
  }

  _spawn(n, opts) {
    for (let i = 0; i < n; i++) this.particles.push({ born: performance.now(), ...opts });
    this._ensureLoop();
  }

  /* ---- Public burst helpers --------------------------------------- */

  /** A shower of star sparkles at a screen point. */
  sparkleBurst(x, y, count = 18, palette = ['#fff4b8', '#ffd166', '#ffb3d9', '#a0e7e5']) {
    if (this._reduced()) count = Math.min(count, 6);
    for (let i = 0; i < count; i++) {
      const a = Math.random() * Math.PI * 2;
      const speed = 1 + Math.random() * 4;
      this._spawn(1, {
        x, y,
        vx: Math.cos(a) * speed,
        vy: Math.sin(a) * speed - 1,
        size: 3 + Math.random() * 5,
        life: 900 + Math.random() * 700,
        color: palette[Math.floor(Math.random() * palette.length)],
        shape: Math.random() < 0.5 ? 'star' : 'dot',
        gravity: 0.05,
        spin: (Math.random() - 0.5) * 0.3,
        rot: Math.random() * Math.PI,
        fade: true,
      });
    }
  }

  /** Petals/confetti raining from the top — used on big wins. */
  confetti(count = 60, palette = ['#ff8fab', '#ffd166', '#8ac926', '#48cae4', '#c77dff', '#ff6b6b']) {
    if (this._reduced()) count = Math.min(count, 14);
    const w = window.innerWidth;
    for (let i = 0; i < count; i++) {
      this._spawn(1, {
        x: Math.random() * w,
        y: -20 - Math.random() * 200,
        vx: (Math.random() - 0.5) * 1.5,
        vy: 1.5 + Math.random() * 2.5,
        size: 6 + Math.random() * 7,
        life: 3200,
        color: palette[Math.floor(Math.random() * palette.length)],
        shape: Math.random() < 0.6 ? 'petal' : 'rect',
        gravity: 0.02,
        spin: (Math.random() - 0.5) * 0.4,
        rot: Math.random() * Math.PI,
        sway: Math.random() * Math.PI * 2,
        fade: false,
      });
    }
  }

  /** A ring of blooming dots expanding from a point. */
  bloom(x, y, color = '#ff8fab') {
    if (this._reduced()) return this.sparkleBurst(x, y, 6);
    const n = 12;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      this._spawn(1, {
        x, y,
        vx: Math.cos(a) * 2.5,
        vy: Math.sin(a) * 2.5,
        size: 6,
        grow: 0.15,
        life: 700,
        color,
        shape: 'dot',
        gravity: 0,
        fade: true,
      });
    }
  }

  /* ---- Loop -------------------------------------------------------- */
  _ensureLoop() {
    if (this._raf == null) {
      this._last = performance.now();
      this._raf = requestAnimationFrame((t) => this._tick(t));
    }
  }

  _tick(now) {
    const dt = Math.min(50, now - this._last);
    this._last = now;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    const alive = [];
    for (const p of this.particles) {
      const age = now - p.born;
      if (age > p.life) continue;
      p.vy += (p.gravity || 0) * (dt / 16);
      if (p.sway != null) {
        p.sway += 0.05;
        p.x += Math.sin(p.sway) * 0.6;
      }
      p.x += p.vx * (dt / 16);
      p.y += p.vy * (dt / 16);
      if (p.grow) p.size += p.grow;
      if (p.spin) p.rot += p.spin;
      const k = age / p.life;
      const alphaBase = p.fade ? 1 - k : k < 0.85 ? 1 : 1 - (k - 0.85) / 0.15;
      ctx.globalAlpha = Math.max(0, alphaBase);
      ctx.fillStyle = p.color;
      this._draw(ctx, p);
      alive.push(p);
    }
    ctx.globalAlpha = 1;
    this.particles = alive;
    if (alive.length) this._raf = requestAnimationFrame((t) => this._tick(t));
    else {
      this._raf = null;
      ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    }
  }

  _draw(ctx, p) {
    ctx.save();
    ctx.translate(p.x, p.y);
    if (p.rot) ctx.rotate(p.rot);
    const s = p.size;
    switch (p.shape) {
      case 'star':
        this._star(ctx, s);
        break;
      case 'rect':
        ctx.fillRect(-s / 2, -s / 3, s, s / 1.6);
        break;
      case 'petal':
        ctx.beginPath();
        ctx.ellipse(0, 0, s / 2, s, 0, 0, Math.PI * 2);
        ctx.fill();
        break;
      default:
        ctx.beginPath();
        ctx.arc(0, 0, s / 2, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.restore();
  }

  _star(ctx, s) {
    ctx.beginPath();
    for (let i = 0; i < 5; i++) {
      const a = (i * 4 * Math.PI) / 5 - Math.PI / 2;
      const x = Math.cos(a) * s * 0.6;
      const y = Math.sin(a) * s * 0.6;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.closePath();
    ctx.fill();
  }

  destroy() {
    clearInterval(this._ambientTimer);
    window.removeEventListener('resize', this._resize);
    if (this._raf) cancelAnimationFrame(this._raf);
  }
}
