// Game flow. The desk is always on screen; panels open from the objects on it.
// State lives in the browser; the server is stateless.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import Desk, { type Spot } from './Desk';
import type { Lighting } from './lighting';
import { VoiceConversation } from '@elevenlabs/client';
import { CallPanel, type CallStatus, Granting, IntroPanel, Notepad, Overlay, ResultPanel, Roster, type Rating, type Review, ReviewPanel, WinPanel, WishPanel, type CallLine, type Note } from './panels';
import { bell, getVolume, ring, say, setVolume, sfx, tick, VOICE_VOLUME } from './sound';
import { HeldAudio } from './held';

import type { CallCard, GameConfig, GrantResult, Scorecard } from './types.gen';

/** Text without voice tags like [laughs], for display. */
const spoken = (t: string) => t.replace(/\[[^\]]*\]/g, '').replace(/\s+/g, ' ').trim();
// A line the client is still saying, as far as it's been heard: typed is how many characters of their current reply have
// been heard, counted in the agent's raw text (audio tags and all, which is how the SDK's alignment counts them).
const heardSoFar = (l: CallLine, typed: number) => l.live ? spoken(l.live.raw.slice(0, Math.max(0, typed - l.live.from)).replace(/\[[^\]]*$/, '')) : l.text;
/** Sent when the call clock runs out; the same words as TIME_UP in the server's agents.py. */
const TIME_UP = "(The call is out of time. The broker can't talk anymore.)";

type Panel = 'none' | 'call' | 'notepad' | 'wish' | 'granting' | 'result' | 'review' | 'won';

interface Job {
  client: CallCard;
  log: CallLine[];
  notes: Note[];         // what the client's agent has jotted on the notepad, in the order it was said
  hungUp: boolean;       // the call is over, so the lamp can be rubbed
  draft: string;
  greeted?: boolean;     // the genie has said his line for this client's wish
  deadline?: number;     // when the wish clock runs out (ms); set when the player starts the kitchen timer
  wish?: string;
  grant?: GrantResult;
  review?: Review;       // from the client's callback
}

export default function App() {
  const [cfg, setCfg] = useState<GameConfig | null>(null);
  const [cards, setCards] = useState<CallCard[]>([]);
  const [generated, setGenerated] = useState<CallCard[]>([]);     // new clients, one written each time a client is picked
  const [loadError, setLoadError] = useState('');
  // Nothing is saved: every page load is a fresh game.
  const [ratings, setRatings] = useState<Record<string, Rating>>({});     // each client's latest result
  // Karma is the sum of each client's latest pay, so retrying a client replaces their earlier result,
  // minus what was lost letting the wish clock run out, which can take it below 0.
  const [penalty, setPenalty] = useState(0);
  const [notice, setNotice] = useState('');
  const karmaWith = (r: Record<string, Rating>) => Object.values(r).reduce((sum, x) => sum + x.pay, cfg?.start_karma ?? 0) - penalty;
  const karma = karmaWith(ratings);
  const [job, setJob] = useState<Job | null>(null);
  const [panel, setPanel] = useState<Panel>(() => new URLSearchParams(location.search).has('win') ? 'won' : 'none');
  const [error, setError] = useState('');
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [talking, setTalking] = useState(false);
  const [typed, setTyped] = useState(0);     // see heardSoFar
  const [mic, setMic] = useState<number | undefined>();     // the broker's mic meter, see CallPanel
  // Add &win to the link to open straight on the win screen (for showing it off).
  const showWin = new URLSearchParams(location.search).has('win');
  const [intro, setIntro] = useState(!showWin);     // shown on every page load, before the bulb
  const [lit, setLit] = useState(false);      // the game starts when the player turns on the bulb; off again = only the bulb works
  const [caller, setCaller] = useState<CallCard | null>(null);     // the client on the ringing phone
  const [ringingBack, setRingingBack] = useState(false);     // the current client calling back about their wish
  const lighting = useRef<Lighting | null>(null);
  const usedPhrases = useRef<string[]>([]);     // the genie's stock phrases this session, sent back so he doesn't repeat himself
  const stopRing = useRef<(() => void) | null>(null);

  useEffect(() => {
    Promise.all([api.config(), api.clients()])
      .then(([c, cs]) => { setCfg(c); setCards(cs); })
      .catch(e => setLoadError(String(e)));
  }, []);

  // Generated clients are deleted on the server once untouched for an hour; refresh the ones on this list while the game is open.
  const generatedIds = useRef<string[]>([]);
  generatedIds.current = generated.map(g => g.agent_id);
  useEffect(() => {
    if (!cfg || cfg.voice_fake) return;
    const t = setInterval(() => {
      if (generatedIds.current.length) api.keepAlive({ agent_ids: generatedIds.current }).catch(e => console.warn('Keep-alive failed:', e));
    }, cfg.keep_alive_minutes * 60_000);
    return () => clearInterval(t);
  }, [cfg]);

  // The lava lamp shows karma: dim when broke, full glow at the win line.
  useEffect(() => {
    if (cfg) lighting.current?.setLava(0.2 + 0.8 * Math.min(1, karma / cfg.win_karma));
  }, [karma, cfg]);
  const onLighting = useCallback((l: Lighting) => { lighting.current = l; }, []);

  const addLog = (l: CallLine) => setJob(j => j && { ...j, log: [...j.log, l] });
  // When the broker cuts the client off, the server sends back only what was heard: swap it in for the full line.
  const cutLog = (full: string, heard: string) => setJob(j => {
    const i = j ? j.log.map(l => l.who === 'client' && l.text === full).lastIndexOf(true) : -1;
    if (!j || i < 0) return j;
    const log = [...j.log]; log[i] = { who: 'client', text: heard };
    return { ...j, log };
  });

  // ---------------------------------------------------------------- the call: a live voice session with the client's agent
  // Both calls connect while the phone rings: the phone only rings once the client's first words are ready, and their
  // audio is held (HeldAudio) until the player picks up, so they talk the moment the phone is answered.
  const conv = useRef<VoiceConversation | null>(null);
  const heldAudio = useRef<HeldAudio | null>(null);
  const sdkSilent = useRef(false);      // HeldAudio is what the player hears; the SDK's own copy stays at volume 0
  const pickup = useRef<(() => void) | null>(null);      // what answering the ringing phone does
  const timeUp = useRef<(() => void) | null>(null);      // what happens when the call clock runs out
  const [callEnds, setCallEnds] = useState<number | undefined>();     // when the call clock runs out (ms)
  const [callStatus, setCallStatus] = useState<CallStatus>('over');
  const ringFor = (start: () => void) => { stopRing.current = ring(); setQueued(false); start(); };
  const lineDead = (msg: string) => { stopRing.current?.(); stopRing.current = null; setQueued(false); setCaller(null); setRingingBack(false); setNotice(msg); };

  const startCall = async (c: CallCard) => {
    if (!cfg) return;
    setQueued(true); setError('');
    const player = new HeldAudio(VOICE_VOLUME * getVolume());
    heldAudio.current = player;
    let picked = false, opening = true, rang = false, over = false;
    const early: CallLine[] = [];
    const log = (l: CallLine) => { if (picked) addLog(l); else early.push(l); };
    // The client files a note at the start of the reply that says it, so each note is held until that line has been spoken.
    // What they called to ask for comes with the client's card and goes on the pad once their opening line has been heard.
    let held: Note[] = [{ text: c.ask, ask: true }];
    const showHeld = () => {
      if (!held.length || !picked) return;
      const add = held; held = [];
      setJob(j => j && { ...j, notes: [...j.notes, ...add.filter(n => !j.notes.some(o => o.text === n.text))] });
      setFresh(new Set(add.map(n => n.text)));
    };
    // How far the client's current reply has got: characters written (agent messages) and characters whose audio has
    // arrived. Once all of it has arrived, the SDK going 'listening' means the reply has played to the end; before
    // that, 'listening' can just mean its audio buffer ran dry. Both start again whenever the broker speaks.
    let said = 0, got = 0, mode = 'listening', lastVoice = 0;
    // When each character of the current reply is heard, so the log shows the client's words as they're said.
    let heardAt: number[] = [], align: number[] | undefined;
    const heardCount = () => { const now = performance.now(); return heardAt.filter(t => t <= now).length; };
    player.onHeard = t => heardAt.push(...t);
    // The broker spoke: the client's last reply stays as far as it was heard.
    const freeze = () => {
      const n = heardCount();
      setJob(j => j && { ...j, log: j.log.flatMap(l => !l.live ? [l] : heardSoFar(l, n) ? [{ who: l.who, text: heardSoFar(l, n) }] : []) });
      heardAt = []; setTyped(0);
    };
    const meter = setInterval(() => {
      setTyped(heardCount());
      if (!picked) return;
      const on = !opening && !muted && !!conv.current;
      setMic(on ? Math.min(5, Math.round((conv.current?.getInputVolume() ?? 0) * 25)) + (Date.now() - lastVoice < 400 ? 10 : 0) : -1);
    }, 60);
    // The opening can't be interrupted: the broker's mic opens once it has played in full. Until then the SDK plays it
    // at volume 0 and the player hears it from HeldAudio.
    const openingDone = () => {
      if (!opening || !picked || !said || got < said || player.busy) return;
      opening = false; clearInterval(awake);
      showHeld();
      sdkSilent.current = false;
      conv.current?.setVolume({ volume: VOICE_VOLUME * getVolume() });
      conv.current?.setMicMuted(false);
    };
    player.onTalking = t => { if (picked && opening) setTalking(t); };
    player.onDrained = openingDone;
    // While the phone rings the agent would take the silence as the broker gone quiet and speak again.
    const awake = setInterval(() => conv.current?.sendUserActivity(), 2000);

    // Time's up: the broker finishes what they're saying (if they're talking), the client answers it, and then with the
    // broker muted the client says a last thing and hangs up.
    let closing = false, muted = false, awaitingReply = false, wrapped = false;
    const mute = () => { muted = true; conv.current?.setMicMuted(true); };
    const settle = () => {
      if (!closing || !muted || awaitingReply || mode === 'speaking' || got < said || wrapped) return;
      wrapped = true;
      conv.current?.sendUserMessage(TIME_UP);
    };
    timeUp.current = () => {
      if (opening) { opening = false; clearInterval(awake); }
      closing = true;
      if (Date.now() - lastVoice > 600) mute();      // not talking right now
      settle();
    };

    const callOver = () => {
      if (over) return;
      over = true; clearInterval(awake); clearInterval(meter); setMic(undefined);
      showHeld(); conv.current = null; timeUp.current = null; setCallEnds(undefined);
      player.close(); if (heldAudio.current === player) heldAudio.current = null;
      if (!picked) { lineDead(`${c.name.split(' ')[0]}'s call didn't come through.`); return; }
      setCallStatus('over'); setTalking(false); setJob(j => j && { ...j, hungUp: true });
    };
    pickup.current = () => {
      picked = true; pickup.current = null;
      setJob({ client: c, log: early, notes: [], hungUp: false, draft: '' });
      setFresh(new Set()); setPanel('call'); setCallStatus('live');
      setCallNow(Date.now()); setCallEnds(Date.now() + cfg.call_seconds * 1000);
      player.release();
    };
    try {
      const { signed_url } = await api.signedUrl(c.agent_id);
      conv.current = await VoiceConversation.startSession({
        signedUrl: signed_url,
        clientTools: {
          note: ({ text }: { text: string }) => { held.push({ text }); },
        },
        onAudio: b64 => {
          if (!opening) return;
          player.push(b64, align); align = undefined;
          if (!rang) { rang = true; setQueued(false); ringFor(() => setCaller(c)); }
        },
        onAudioAlignment: a => { got += a.chars.length; if (opening) align = a.char_start_times_ms; },     // comes just before its audio
        onAudioAlignmentPlayback: ({ alignment: a }) => {     // after the opening the SDK plays the audio; this is as a chunk starts
          if (opening) return;
          const now = performance.now();
          heardAt.push(...a.char_start_times_ms.map(ms => now + ms));
        },
        onInterruption: () => { const now = performance.now(); heardAt = heardAt.filter(t => t <= now); },
        onMessage: m => {
          if (m.role === 'user') {
            if (m.message === TIME_UP) return;
            freeze();
            awaitingReply = true; said = 0; got = 0;
            if (closing && !muted) mute();     // the broker has finished what they were saying
            log({ who: 'broker', text: spoken(m.message) });
          } else {
            log({ who: 'client', text: spoken(m.message), live: { raw: m.message, from: said } });
            said += m.message.length; awaitingReply = false;
          }
        },
        onAgentResponseCorrection: x => {
          // The time's-up message lands while the server still thinks the client is talking (its guess at playback runs
          // behind the browser), so it reports a cut that the player never heard.
          if (wrapped) return;
          cutLog(spoken(x.original_agent_response), spoken(x.corrected_agent_response));
        },
        onVadScore: ({ vadScore }) => { if (vadScore > 0.5) lastVoice = Date.now(); },
        onModeChange: m => {
          mode = m.mode;
          if (opening) return;
          setTalking(mode === 'speaking');
          if (mode === 'listening') { showHeld(); settle(); }
        },
        onDisconnect: d => { if (d.reason !== 'user' && picked) sfx('phone-hangup'); callOver(); },
        onError: msg => setError(`The line crackled. ${msg}`),
      });
      conv.current.setMicMuted(true);
      sdkSilent.current = true;
      conv.current.setVolume({ volume: 0 });
    } catch (e) {
      setError(`Couldn't get through. ${e}`);
      callOver();
    }
  };
  // The call clock, from pickup: when it runs out the client wraps up the call.
  const [callNow, setCallNow] = useState(() => Date.now());
  useEffect(() => {
    if (!callEnds) return;
    const t = setInterval(() => setCallNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [callEnds]);
  const callSecondsLeft = callEnds ? Math.max(0, Math.ceil((callEnds - callNow) / 1000)) : undefined;
  useEffect(() => { if (callSecondsLeft === 0) { timeUp.current?.(); timeUp.current = null; } }, [callSecondsLeft]);

  // The callback, once the wish is granted: the client posts their review, says their piece and hangs up.
  // The broker's mic stays muted. All of it is played from HeldAudio, so it keeps playing after the client hangs up.
  const startCallback = async (j: Job) => {
    if (!j.wish || !j.grant) return;
    setError('');
    const first = j.client.name.split(' ')[0];
    const player = new HeldAudio(VOICE_VOLUME * getVolume());
    heldAudio.current = player;
    let verdict: (Scorecard & { review: string }) | null = null;
    let picked = false, rang = false, closed = false, finished = false;
    const early: CallLine[] = [];
    const stamp = (what: string) => console.info(`[callback] ${what} audio=${player.received.toFixed(1)}s t=${(performance.now() / 1000).toFixed(1)}s`);
    player.onTalking = t => { if (picked) { setTalking(t); stamp(t ? 'speaking' : 'listening'); } };
    // Done once the line has closed and everything the client said has played.
    const finish = async () => {
      if (!picked || !closed || player.busy || finished) return;
      finished = true; clearInterval(typing);
      stamp('disconnected');
      sfx('phone-hangup');
      player.close(); if (heldAudio.current === player) heldAudio.current = null;
      setCallStatus('over'); setTalking(false);
      if (!verdict) { setJob(null); setPanel('none'); setNotice(`${first} hung up without leaving a review.`); return; }
      const v = verdict;
      try {
        const s = await api.score({ goal_met: v.goal_met, feeling: v.feeling });
        setJob(x => x && { ...x, review: { text: v.review, stars: s.stars, pay: s.bill.pay, goal_met: v.goal_met, feeling: v.feeling } });
        setPanel('review');
      } catch (e) { setError(`The review got lost. ${e}`); }
    };
    player.onDrained = () => void finish();
    let said = 0, align: number[] | undefined;
    const heardAt: number[] = [];
    player.onHeard = t => heardAt.push(...t);
    const typing = setInterval(() => { const now = performance.now(); setTyped(heardAt.filter(t => t <= now).length); }, 60);
    pickup.current = () => {
      picked = true; pickup.current = null;
      setJob({ ...j, log: early }); setFresh(new Set()); setPanel('call'); setCallStatus('live');
      player.release();
    };
    try {
      const { signed_url } = await api.signedUrl(j.client.agent_id);
      conv.current = await VoiceConversation.startSession({
        signedUrl: signed_url,
        startingWorkflowNodeId: 'callback',
        overrides: { agent: { firstMessage: '' } },     // the opening line is for the morning call only
        dynamicVariables: { wish: j.wish, outcome: j.grant.genie.text,     // and the morning call, so the client argues from what was really said
                            call: j.log.map(l => `${l.who === 'client' ? 'You' : 'Broker'}: ${l.text}`).join('\n') || '(no record)' },
        // The answer steers the client to speak next; the same words as REVIEW_POSTED in the server's agents.py.
        clientTools: { review: (r: Scorecard & { review: string }) => { verdict ??= r; return "Review posted online. The broker still hasn't heard from you: now talk to them out loud and give them your verdict."; } },
        onAudioAlignment: a => { align = a.char_start_times_ms; },     // comes just before its audio
        onAudio: b64 => {
          player.push(b64, align); align = undefined;
          if (!rang) { rang = true; ringFor(() => setRingingBack(true)); }
        },
        onMessage: m => {
          if (m.role === 'user') return;
          const l: CallLine = { who: 'client', text: spoken(m.message), live: { raw: m.message, from: said } };
          said += m.message.length;
          if (picked) addLog(l); else early.push(l);
        },
        onDisconnect: () => {
          closed = true; conv.current = null;
          if (!rang && verdict) { rang = true; ringFor(() => setRingingBack(true)); return; }     // reviewed, said nothing: as before, the review still comes
          if (!rang) { player.close(); setJob(null); lineDead(`${first} hung up without leaving a review.`); return; }
          void finish();
        },
        onError: msg => setError(`The line crackled. ${msg}`),
      });
      conv.current.setMicMuted(true);
      sdkSilent.current = true;
      conv.current.setVolume({ volume: 0 });
    } catch (e) {
      setError(`Couldn't get through. ${e}`);
      conv.current = null; player.close(); lineDead(`${first} couldn't get through.`);
    }
  };
  const hangUp = () => {
    if (conv.current) { sfx('phone-hangup'); void conv.current.endSession(); }
    setPanel('none');
  };

  // ---------------------------------------------------------------- the grant
  // The genie is live: the genie node of the client's agent. He files the grant (the grant tool), then tells the broker
  // what happened and hangs up himself (end_call, whose spoken message is the outcome).
  // In fake mode there's no agent, so the server grants the wish in one call.
  const genie = useRef<VoiceConversation | null>(null);
  const genieAudio = useRef<HeldAudio | null>(null);     // his voice, played from our own queue
  const seal = async (wish: string) => {
    if (!job || !cfg) return;
    setJob({ ...job, draft: wish, wish }); setPanel('granting');
    const l = lighting.current;
    l?.breathe(true);          // the room dims and swells while the genie thinks
    let answered = false;      // the genie's answer is on screen, or the wish has failed
    const show = (g: GrantResult) => { answered = true; l?.breathe(false); setJob(j => j && { ...j, grant: g }); setPanel('result'); };
    const fail = (e: unknown) => { if (answered) return; answered = true; l?.breathe(false); setError(`The lamp sputtered out. ${e}`); setPanel('wish'); };
    const req = { client_id: job.client.agent_id, wish, used_phrases: usedPhrases.current };
    let granted = false, closed = false, finished = false;
    const t0 = performance.now();
    const stamp = (what: string) => console.info(`[genie] ${what} t=${((performance.now() - t0) / 1000).toFixed(1)}s`);     // for scripts/test_browser_call.py
    let player: HeldAudio | null = null;
    // Done once he has hung up and everything he said has played.
    const finish = () => {
      if (!closed || !player || player.busy || finished) return;
      finished = true; stamp('heard in full');
      player.close(); if (genieAudio.current === player) genieAudio.current = null;
    };
    try {
      if (cfg.voice_fake) {
        const g = await api.grant(req);
        usedPhrases.current = [...usedPhrases.current, ...(g.phrases ?? [])];
        show(g); void say(g.genie);
        return;
      }
      const start = await api.genie(req);
      // He plays from our own queue, as the client's callback does: the SDK stops its player the moment he hangs up.
      player = new HeldAudio(VOICE_VOLUME * getVolume());
      genieAudio.current = player; player.onDrained = finish; player.release();
      genie.current = await VoiceConversation.startSession({
        signedUrl: start.signed_url,
        startingWorkflowNodeId: 'genie',
        overrides: { agent: { firstMessage: '' } },     // the client's opening line is for the morning call only
        dynamicVariables: start.variables,
        clientTools: {
          grant: (g: { is_wish: boolean; phrases?: string[] }) => {
            if (!g.is_wish) {     // not a wish he'll touch: his recorded refusal
              show({ refused: true, genie: cfg.genie_refused, phrases: [] }); void say(cfg.genie_refused);
              void genie.current?.endSession();
              return 'Refused.';
            }
            granted = true; stamp('granted');
            usedPhrases.current = [...usedPhrases.current, ...(g.phrases ?? [])];
            // The answer steers him to speak next; the same words as GRANT_NOTED in the server's agents.py.
            return "Noted. The broker hasn't heard anything from you yet: now end_call, with the whole outcome as its message to speak.";
          },
        },
        onMessage: m => {
          if (m.role === 'user') return;
          if (granted && !answered) show({ refused: false, genie: { text: spoken(m.message), audio: null, seconds: 0 }, phrases: [] });
        },
        onAudio: b64 => player?.push(b64),
        onDisconnect: () => { closed = true; genie.current = null; stamp('closed'); fail('The genie left without a word.'); finish(); },
        onError: msg => fail(msg),
      });
      genie.current.setMicMuted(true);
      genie.current.setVolume({ volume: 0 });     // our own player is the one that's heard
    } catch (e) { fail(e); player?.close(); }
  };
  // The wish clock: ticks while running; when it hits zero the bell rings and whatever is written goes to the genie.
  const [now, setNow] = useState(() => Date.now());
  const draftRef = useRef('');
  const clockRunning = !!job?.deadline && !job.wish;
  useEffect(() => {
    if (!clockRunning) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [clockRunning]);
  useEffect(() => clockRunning ? tick() : undefined, [clockRunning]);     // ticks until sealed or out of time
  const secondsLeft = job?.deadline ? Math.max(0, Math.ceil((job.deadline - now) / 1000)) : 0;
  useEffect(() => {
    if (clockRunning && cfg && job && secondsLeft === 0) {
      bell();
      const wish = draftRef.current.trim();
      if (wish) void seal(wish);
      else {     // nothing written: the genie is put out, karma is lost, and the clock can be started again
        void say(cfg.genie_refused);
        setPenalty(p => p + cfg.timeout_penalty);
        setJob({ ...job, deadline: undefined });
        setPanel('none');
        setNotice(`Time's up. You lost ${cfg.timeout_penalty} karma. Start the clock again when you're ready.`);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clockRunning, secondsLeft]);
  const startClock = () => {
    if (!job || !cfg) return;
    draftRef.current = job.draft; setNow(Date.now());
    setJob({ ...job, deadline: Date.now() + cfg.wish_seconds * 1000 });
  };

  // The genie's answer is dismissed: a refused wish goes back to before the wish, a granted one brings the client's callback.
  const afterResult = () => {
    if (!job?.grant) return;
    setPanel('none');
    if (job.grant.refused) { setJob({ ...job, wish: undefined, grant: undefined, deadline: undefined }); return; }
    setQueued(true);
    void startCallback(job);     // the phone rings once the client is ready to talk
  };
  const after = job?.review ? { ...ratings, [job.client.agent_id]: { stars: job.review.stars, pay: job.review.pay } } : ratings;
  const finishJob = () => {
    if (!job?.review || !cfg) return;
    setRatings(after); setJob(null);
    setPanel(karmaWith(after) >= cfg.win_karma ? 'won' : 'none');
  };
  const restart = () => { setRatings({}); setPenalty(0); setJob(null); setPanel('none'); };
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(''), 6000);
    return () => clearTimeout(t);
  }, [notice]);

  // ---------------------------------------------------------------- incoming calls
  // The player picks a client from the notepad; that client calls in a moment later.
  const [queued, setQueued] = useState(false);
  const roster = [...cards, ...generated];
  const pick = (c: CallCard) => {
    setPanel('none');
    void startCall(c);     // the phone rings once the client is ready to talk
    // Write the next client while this one plays, so they're on the list for the next round.
    if (!cfg?.voice_fake) api.generate().then(g => setGenerated(gs => [...gs, g])).catch(e => console.warn('No new client:', e));
  };
  const answer = () => {
    if (!caller && !(ringingBack && job)) return;
    stopRing.current?.(); stopRing.current = null; sfx('phone-pickup');
    setCaller(null); setRingingBack(false);
    pickup.current?.();
  };

  // ---------------------------------------------------------------- desk objects
  const ringing = !!caller || ringingBack;
  const canStartClock = !!job && job.hungUp && !job.deadline;
  const canWish = clockRunning;
  const idle = !job && !queued && !caller;     // no client picked: the light switch still works
  const labels: Partial<Record<Spot, string>> = !lit ? { bulb: 'Turn on the light' } : {
    bulb: idle ? 'Turn off the light' : undefined,
    lava: cfg ? `Karma ${karma} / ${cfg.win_karma}` : undefined,
    phone: ringing ? 'Answer the phone'
      : queued ? 'Wait for the phone to ring'
      : job && callStatus !== 'over' && panel !== 'call' ? `Back to ${job.client.name.split(' ')[0]}` : undefined,
    notepad: job ? 'Case notes' : "Tonight's clients",
    timer: canStartClock && cfg ? `You'll have ${cfg.wish_seconds} seconds to wish. Start the clock`
      : clockRunning ? `${secondsLeft} seconds left`
      : job && !job.hungUp ? 'On a call' : undefined,
    lamp: canWish ? 'Rub the lamp' : undefined,
  };
  const onSpot = (s: Spot) => {
    if (s === 'bulb' && !lit) { sfx('light-switch', 0.25); setLit(true); lighting.current?.setBulb(true); lighting.current?.flicker(); }
    else if (s === 'bulb' && idle) { sfx('light-switch', 0.25); setLit(false); lighting.current?.setBulb(false); }
    if (s === 'phone') {
      if (ringing) answer();
      else if (job && callStatus !== 'over') setPanel('call');
    }
    if (s === 'notepad') setPanel('notepad');
    if (s === 'timer' && canStartClock) startClock();
    if (s === 'lamp' && canWish) {
      if (!job.greeted && cfg) { void say(cfg.genie_rubs[Math.floor(Math.random() * cfg.genie_rubs.length)]); setJob({ ...job, greeted: true }); }
      setPanel('wish');
    }
  };

  return (
    <main className="room">
      <Desk labels={labels} waiting={queued && !ringing ? 'phone' : null} attention={!lit ? 'bulb' : ringing ? 'phone' : canStartClock ? 'timer' : canWish && panel !== 'wish' ? 'lamp' : !job && !queued ? 'notepad' : null} onSpot={onSpot} onLighting={onLighting} />
      <VolumeSlider onChange={v => {
        heldAudio.current?.setVolume(VOICE_VOLUME * v);
        if (!sdkSilent.current) conv.current?.setVolume({ volume: VOICE_VOLUME * v });      // turning it up would play the same voice twice
        genieAudio.current?.setVolume(VOICE_VOLUME * v);
      }} />
      {cfg?.llm_fake && <div className="tag">Fake mode: canned responses</div>}
      {loadError && <Overlay><p className="type error">
        {loadError.includes('access code') ? loadError.replace(/^Error: /, '') : <>Can't reach the server. Is it running?<br />{loadError}</>}
      </p></Overlay>}

      {panel === 'call' && job && (
        <CallPanel client={job.client} log={job.log.map(l => { const text = heardSoFar(l, typed); return { ...l, text, live: text !== l.text ? l.live : undefined }; }).filter(l => l.text)} status={callStatus} talking={talking} notes={job.notes} fresh={fresh} secondsLeft={callSecondsLeft} mic={mic} onHangUp={hangUp} />
      )}
      {panel === 'call' && error && <div className="toast">{error}</div>}
      {panel === 'notepad' && (
        <Overlay onClose={() => setPanel('none')}>
          {job ? <Notepad client={job.client} notes={job.notes} />
            : <Roster cards={roster} ratings={ratings} karma={karma} winKarma={cfg?.win_karma ?? 100} busy={queued || ringing}
                onPick={pick} onRestart={restart} />}
        </Overlay>
      )}
      {panel === 'wish' && job && cfg && (
        <WishPanel client={job.client} notes={job.notes} cfg={cfg} initial={job.draft} secondsLeft={secondsLeft}
          onDraft={d => { draftRef.current = d; }}
          onSeal={w => void seal(w)} onClose={draft => { setJob({ ...job, draft }); setPanel('none'); }} />
      )}
      {panel === 'wish' && error && <div className="toast">{error}</div>}
      {notice && <div className="toast">{notice}</div>}
      {panel === 'granting' && <Granting />}
      {panel === 'result' && job?.grant && job.wish && <ResultPanel wish={job.wish} grant={job.grant} onDone={afterResult} />}
      {panel === 'review' && job?.review && <ReviewPanel client={job.client} review={job.review} karmaBefore={karma} karmaAfter={karmaWith(after)} onDone={finishJob} />}
      {intro && !loadError && <IntroPanel winKarma={cfg?.win_karma ?? 100} timeoutPenalty={cfg?.timeout_penalty ?? 10} onStart={() => setIntro(false)} />}
      {panel === 'won' && <WinPanel karma={showWin && karma < (cfg?.win_karma ?? 100) ? cfg?.win_karma ?? 100 : karma} onRestart={restart} />}
    </main>
  );
}

/** One slider for every sound in the game. */
function VolumeSlider({ onChange }: { onChange: (v: number) => void }) {
  const [v, setV] = useState(getVolume);
  return (
    <label className="volume">
      <span>Volume</span>
      <input type="range" min={0} max={1} step={0.05} value={v} onChange={e => { const x = Number(e.target.value); setV(x); setVolume(x); onChange(x); }} />
    </label>
  );
}
