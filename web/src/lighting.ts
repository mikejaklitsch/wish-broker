// Lighting engine (ported from assets/lighting-test.html). Four aligned renders are stacked and
// their opacities solved so the result is the bilinear mix for bulb level B and lava level L.
// The loop runs only while something is changing.
import { buzzLevel } from './sound';

export interface Layers { bulbOff: HTMLImageElement; lavaOff: HTMLImageElement; bothOn: HTMLImageElement }

const clamp = (v: number) => Math.max(0, Math.min(1, v));
const rand = (a: number, b: number) => a + Math.random() * (b - a);
type Pattern = [number, number][];   // [power multiplier, duration ms]

// Dips never go below 70% of the bulb's brightness; kept slow, since fast strobing just annoys.
const dropout = (): Pattern => [[rand(0.7, 0.8), rand(80, 180)], [1, rand(140, 380)]];

export class Lighting {
  private bulb = { on: false, bright: 1, shown: 0 };     // dark until the player switches it on
  private lava = { level: 1, shown: 1 };
  private steps: { at: number; mul: number }[] = [];
  private running = false;
  private prev = 0;
  private breath = { on: false, amp: 0, start: 0 };

  constructor(private layers: Layers) { this.draw(); }

  setBulb(on: boolean) { this.bulb.on = on; if (!on) this.steps = []; this.kick(); }
  /** Lava brightness 0..1, eased toward. */
  setLava(level: number) { this.lava.level = clamp(level); this.kick(); }

  flicker() { this.play(Array.from({ length: Math.round(rand(2, 4)) }, dropout).flat()); }
  sputter() {
    const s: Pattern = [];
    for (let i = 0; i < Math.round(rand(6, 9)); i++) {
      if (Math.random() < 0.35) s.push([rand(0.82, 0.9), rand(120, 260)], [1, rand(40, 120)]);
      else s.push(...dropout());
      s.push([1, rand(60, 300)]);
    }
    this.play(s);
  }

  /** Silent, slow dimming of the bulb and lava lamp, out of step with each other, until turned off. */
  breathe(on: boolean) {
    if (on && !this.breath.on) this.breath.start = performance.now();
    this.breath.on = on; this.kick();
  }

  destroy() { this.steps = []; buzzLevel(0); this.running = false; }

  private play(pattern: Pattern) {
    if (!this.bulb.on) return;
    let t = performance.now();
    this.steps = pattern.map(([mul, dur]) => { const s = { at: t, mul }; t += dur; return s; });
    this.steps.push({ at: t, mul: 1 });
    this.kick();
  }

  private kick() {
    if (this.running) return;
    this.running = true; this.prev = performance.now();
    requestAnimationFrame(this.frame);
  }

  private mul(now: number): number {
    while (this.steps.length > 1 && this.steps[1].at <= now) this.steps.shift();
    if (this.steps.length === 1 && this.steps[0].at <= now) { this.steps = []; return 1; }
    return this.steps.length ? this.steps[0].mul : 1;
  }

  private frame = (now: number) => {
    if (!this.running) return;
    const dt = Math.min(50, now - this.prev); this.prev = now;
    const mul = this.mul(now);

    // Breathing: each light fades down and back up, then rests, on its own slow cycle. amp eases the
    // whole effect in and out so starting or stopping never jumps.
    this.breath.amp += ((this.breath.on ? 1 : 0) - this.breath.amp) * (1 - Math.exp(-dt / 600));
    const t = (now - this.breath.start) / 1000;
    const wave = (period: number, phase: number) => Math.max(0, Math.sin(2 * Math.PI * t / period + phase)) ** 2;
    const bulbBreath = 1 - 0.55 * this.breath.amp * wave(4.3, 0);
    const lavaBreath = 1 - 0.6 * this.breath.amp * wave(5.9, -2);

    const bT = (this.bulb.on ? this.bulb.bright : 0) * mul * bulbBreath;
    this.bulb.shown += (bT - this.bulb.shown) * (1 - Math.exp(-dt / (bT > this.bulb.shown ? 25 : 60)));
    const lT = this.lava.level * lavaBreath;
    this.lava.shown += (lT - this.lava.shown) * (1 - Math.exp(-dt / 400));   // lava warms slowly
    this.draw();

    if (!this.steps.length && !this.breath.on && this.breath.amp < 0.002 && Math.abs(bT - this.bulb.shown) < 0.002 && Math.abs(lT - this.lava.shown) < 0.002) {
      this.bulb.shown = bT; this.lava.shown = lT; this.draw(); this.running = false; return;
    }
    requestAnimationFrame(this.frame);
  };

  private draw() {
    const B = this.bulb.shown, L = this.lava.shown;
    buzzLevel(this.breath.amp * B * B);      // buzz only while the genie thinks, following the bulb as it dims
    const a4 = B * L, r4 = 1 - a4;
    const a3 = r4 > 1e-6 ? (B * (1 - L)) / r4 : 0;
    const r34 = (1 - a3) * r4;
    const a2 = r34 > 1e-6 ? ((1 - B) * L) / r34 : 0;
    this.layers.bothOn.style.opacity = clamp(a4).toFixed(3);
    this.layers.lavaOff.style.opacity = clamp(a3).toFixed(3);
    this.layers.bulbOff.style.opacity = clamp(a2).toFixed(3);
  }
}
