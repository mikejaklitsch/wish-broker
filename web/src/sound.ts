// Sounds: a synthesized phone bell, plus recordings: the bulb buzz loop and the phone
// handset and the light switch (cut from the downloads in assets/source/, levelled to -6 dB). Browsers only allow audio after a
// click inside the page, so the context is created on the first press anywhere.

let ctx: AudioContext | null = null;
let buzz: GainNode | null = null;
let master: GainNode | null = null;

/** Overall volume for every sound in the game. */
export const MASTER_VOLUME = 0.6;
/** Volume of recorded voices (0 to 1). */
export const VOICE_VOLUME = 0.5;

// The player's volume slider (0 to 1) scales everything. Remembered in this browser.
const VOLUME_KEY = 'wish-broker-volume';
let userVolume = (() => {
  try { const v = parseFloat(localStorage.getItem(VOLUME_KEY) ?? ''); return isNaN(v) ? 1 : v; } catch { return 1; }
})();
const voices = new Set<HTMLAudioElement>();     // voice lines playing now, so the slider affects them mid-line
export function getVolume() { return userVolume; }
export function setVolume(v: number) {
  userVolume = v;
  try { localStorage.setItem(VOLUME_KEY, String(v)); } catch { /* not remembered */ }
  if (ctx && master) master.gain.setTargetAtTime(MASTER_VOLUME * v, ctx.currentTime, 0.02);
  for (const a of voices) a.volume = VOICE_VOLUME * v;
}

function audio(): AudioContext | null {
  try {
    if (!ctx) {
      ctx = new AudioContext();
      master = ctx.createGain(); master.gain.value = MASTER_VOLUME * userVolume; master.connect(ctx.destination);
      for (const n of ['phone-pickup', 'phone-hangup', 'light-switch', 'timer-tick'] as const) loadSfx(n);
    }
    if (ctx.state === 'suspended') void ctx.resume();
    return ctx;
  } catch { return null; }
}
document.addEventListener('pointerdown', () => audio(), { once: true });

type Sfx = 'phone-pickup' | 'phone-hangup' | 'light-switch' | 'timer-tick';
const sfxBuffers: Partial<Record<Sfx, Promise<AudioBuffer>>> = {};
function loadSfx(name: Sfx) {
  const c = ctx!;
  return sfxBuffers[name] ??= fetch(`/audio/sfx/${name}.mp3`).then(r => r.arrayBuffer()).then(d => c.decodeAudioData(d));
}

/** Play a recorded one-shot sound at a volume from 0 to 1. */
export function sfx(name: Sfx, volume = 1) {
  const c = audio(); if (!c) return;
  loadSfx(name).then(buf => {
    const s = c.createBufferSource(); s.buffer = buf;
    const g = c.createGain(); g.gain.value = volume;
    s.connect(g).connect(master!); s.start();
  }).catch(() => {});
}

/** The kitchen timer ticking (95 s cut from assets/source/, original level). Returns stop(). */
export function tick(): () => void {
  const c = audio(); if (!c) return () => {};
  let src: AudioBufferSourceNode | null = null, stopped = false;
  loadSfx('timer-tick').then(buf => {
    if (stopped) return;
    // Played at the recording's own level: the gain undoes the master volume (the slider still applies).
    const g = c.createGain(); g.gain.value = 1 / MASTER_VOLUME;
    src = c.createBufferSource(); src.buffer = buf; src.connect(g).connect(master!); src.start();
  }).catch(() => {});
  return () => { stopped = true; try { src?.stop(); } catch { /* already stopped */ } };
}

/** Volume of the bulb buzz at full brightness (0 to 1). */
export const BUZZ_VOLUME = 0.1;

/** Set the bulb buzz to follow the light: 0 is off, 1 is full brightness. Silent until audio is allowed. */
export function buzzLevel(level: number) {
  if (!ctx) return;
  if (!buzz) {
    if (level <= 0) return;           // the loop isn't even loaded until it's first needed
    const c = ctx, b = buzz = c.createGain();
    b.gain.value = 0; b.connect(master!);
    fetch('/audio/sfx/bulb-loop.mp3').then(r => r.arrayBuffer()).then(d => c.decodeAudioData(d)).then(buf => {
      const src = c.createBufferSource(); src.buffer = buf; src.loop = true; src.connect(b); src.start();
    }).catch(() => { /* no buzz, no problem */ });
  }
  buzz.gain.setTargetAtTime(BUZZ_VOLUME * Math.max(0, Math.min(1, level)), ctx.currentTime, 0.03);
}

/** Old mechanical phone bell: a hammer striking twin bells ~20 times a second, 2s on, 4s off. Returns stop(). */
export function ring(): () => void {
  let stopped = false;
  const burst = () => {
    const c = audio(); if (!c || stopped) return;
    const t0 = c.currentTime;
    for (let i = 0; i < 40; i++) {
      const t = t0 + i * 0.05;
      for (const f of [1180, 1710]) {
        const o = c.createOscillator(); o.type = 'triangle'; o.frequency.value = f;
        const g = c.createGain();
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(0.09, t + 0.004);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.12);
        o.connect(g).connect(master!); o.start(t); o.stop(t + 0.13);
      }
    }
  };
  burst();
  const id = setInterval(burst, 6000);
  return () => { stopped = true; clearInterval(id); };
}

/** Timer bell when the last question has been answered. */
export function bell() {
  const c = audio(); if (!c) return;
  const t = c.currentTime;
  for (const [f, v] of [[1870, 0.12], [2810, 0.05], [4100, 0.03]] as const) {
    const o = c.createOscillator(); o.frequency.value = f;
    const g = c.createGain(); g.gain.setValueAtTime(v, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 1.6);
    o.connect(g).connect(master!); o.start(t); o.stop(t + 1.7);
  }
}

/**
 * Say a line: play its recording, or when there is none yet, just wait as long as it would take.
 * Resolves when it's finished.
 */
export function say(line: { audio?: string | null; seconds: number }): Promise<void> {
  const wait = () => new Promise<void>(res => setTimeout(res, line.seconds * 1000));
  if (!line.audio) return wait();
  return new Promise(res => {
    const a = new Audio(line.audio!);
    a.volume = VOICE_VOLUME * userVolume;
    voices.add(a);
    a.onended = () => { voices.delete(a); res(); };
    a.onerror = () => { voices.delete(a); void wait().then(res); };
    a.play().catch(() => { void wait().then(res); });
  });
}
