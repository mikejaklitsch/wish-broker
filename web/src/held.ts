// Plays a voice session's audio from our own queue instead of the SDK's player, so the client can start talking while
// the phone rings and be heard from the first word on pickup. The SDK plays the same audio at volume 0 meanwhile.
// It also keeps playing after the line closes, so a client who hangs up while the phone is still ringing is heard in full.

const RATE = 16000;     // the agents' output format, pcm_16000

export class HeldAudio {
  private ctx = new AudioContext({ sampleRate: RATE });
  private gain = this.ctx.createGain();
  private queue: [Float32Array, number[] | undefined][] = [];
  private at = 0;            // when the next chunk starts, in the context's clock
  private playing = 0;       // chunks scheduled and not finished
  private released = false;
  received = 0;              // seconds of audio received
  /** Called when everything received so far has played. */
  onDrained: () => void = () => {};
  /** Called when the client starts or stops being heard. */
  onTalking: (talking: boolean) => void = () => {};
  /** When each character of a chunk's text will be heard (performance.now() ms), as the chunk is scheduled. */
  onHeard: (times: number[]) => void = () => {};

  constructor(volume: number) {
    this.gain.gain.value = volume;
    this.gain.connect(this.ctx.destination);
  }

  /** A chunk of the session's audio (base64 16-bit PCM), with its characters' start times (ms). Queued until release(). */
  push(b64: string, starts?: number[]) {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const pcm = new Int16Array(bytes.buffer, 0, bytes.length >> 1);
    const f = Float32Array.from(pcm, x => x / 32768);
    this.received += f.length / RATE;
    if (this.released) this.play(f, starts); else this.queue.push([f, starts]);
  }

  /** The player picked up: play what's been held, then everything after it as it comes. */
  release() {
    this.released = true;
    void this.ctx.resume();
    this.at = this.ctx.currentTime;
    for (const [f, starts] of this.queue) this.play(f, starts);
    this.queue = [];
    if (!this.playing) this.onDrained();
  }

  get busy() { return this.playing > 0 || (!this.released && this.queue.length > 0); }

  setVolume(v: number) { this.gain.gain.value = v; }

  close() { void this.ctx.close(); }

  private play(f: Float32Array, starts?: number[]) {
    const buf = this.ctx.createBuffer(1, f.length, RATE);
    buf.copyToChannel(f, 0);
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.gain);
    this.at = Math.max(this.at, this.ctx.currentTime);
    src.start(this.at);
    if (starts) { const at = performance.now() + (this.at - this.ctx.currentTime) * 1000; this.onHeard(starts.map(ms => at + ms)); }
    this.at += buf.duration;
    if (this.playing++ === 0) this.onTalking(true);
    src.onended = () => {
      if (--this.playing) return;
      this.onTalking(false);
      this.onDrained();
    };
  }
}
