// Game flow. The desk is always on screen; panels open from the objects on it.
// State lives in the browser; the server is stateless.
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import Desk, { type Spot } from './Desk';
import type { Lighting } from './lighting';
import { CallPanel, Granting, Notepad, Overlay, ResultPanel, Roster, type Rating, ReviewPanel, WinPanel, WishPanel, type CallLine } from './panels';
import { bell, getVolume, ring, say, setVolume, sfx, tick } from './sound';

import type { ClientCard, GameConfig, GrantResult, Line } from './types.gen';

type Panel = 'none' | 'call' | 'notepad' | 'wish' | 'granting' | 'result' | 'review' | 'won';

interface Job {
  client: ClientCard;
  log: CallLine[];
  asked: Set<string>;
  revealed: Record<string, string>;
  ended: boolean;        // talk time ran out; no more calls
  hungUp: boolean;       // has hung up at least once, so the lamp can be rubbed
  draft: string;
  deadline?: number;     // when the wish clock runs out (ms); set when the player starts the kitchen timer
  wish?: string;
  grant?: GrantResult;
}

export default function App() {
  const [cfg, setCfg] = useState<GameConfig | null>(null);
  const [cards, setCards] = useState<ClientCard[]>([]);
  const [loadError, setLoadError] = useState('');
  // Nothing is saved: every page load is a fresh game.
  const [ratings, setRatings] = useState<Record<string, Rating>>({});     // each client's latest result
  // Karma is the sum of each client's latest pay, so retrying a client replaces their earlier result.
  const karmaWith = (r: Record<string, Rating>) => Object.values(r).reduce((sum, x) => sum + x.pay, cfg?.start_karma ?? 0);
  const karma = karmaWith(ratings);
  const [job, setJob] = useState<Job | null>(null);
  const [panel, setPanel] = useState<Panel>('none');
  const [error, setError] = useState('');
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [talking, setTalking] = useState(false);
  const [lit, setLit] = useState(false);      // the game starts when the player turns on the bulb; off again = only the bulb works
  const [caller, setCaller] = useState<ClientCard | null>(null);     // the client on the ringing phone
  const lighting = useRef<Lighting | null>(null);
  const stopRing = useRef<(() => void) | null>(null);

  useEffect(() => {
    Promise.all([api.config(), api.clients()])
      .then(([c, cs]) => { setCfg(c); setCards(cs); })
      .catch(e => setLoadError(String(e)));
  }, []);

  // The lava lamp shows karma: dim when broke, full glow at the win line.
  useEffect(() => {
    if (cfg) lighting.current?.setLava(0.2 + 0.8 * Math.min(1, karma / cfg.win_karma));
  }, [karma, cfg]);
  const onLighting = useCallback((l: Lighting) => { lighting.current = l; }, []);

  const addLog = (l: CallLine) => setJob(j => j && { ...j, log: [...j.log, l] });

  const clientSays = async (line: Line) => {
    addLog({ who: 'client', text: line.text });
    await say(line);
  };
  const questionsLeft = job && cfg ? cfg.questions_per_call - job.asked.size : 0;

  // ---------------------------------------------------------------- the call
  const startCall = async (c: ClientCard) => {
    if (!cfg) return;
    setJob({ client: c, log: [], asked: new Set(), revealed: {}, ended: false, hungUp: false, draft: '' });
    setFresh(new Set()); setError(''); setPanel('call');
    setTalking(true);
    await new Promise(r => setTimeout(r, 600));      // let the handset settle before they speak
    await clientSays(c.opening);
    setTalking(false);
  };
  const ask = async (questionId: string) => {
    if (!job || !cfg || talking || job.asked.size >= cfg.questions_per_call) return;
    const q = job.client.questions.find(x => x.id === questionId)!;
    setTalking(true); setError('');
    setJob(j => j && { ...j, asked: new Set(j.asked).add(questionId), log: [...j.log, { who: 'broker', text: q.text }] });
    try {
      const r = await api.ask({ client_id: job.client.id, question_id: questionId });
      setFresh(new Set(r.revealed.map(f => f.id)));
      setJob(j => j && { ...j, revealed: { ...j.revealed, ...Object.fromEntries(r.revealed.map(f => [f.id, f.value])) } });
      await clientSays(r.answer);
      if (job.asked.size + 1 >= cfg.questions_per_call) {     // last question: bell, goodbye, call over
        bell();
        await clientSays(job.client.goodbye);
        setJob(j => j && { ...j, ended: true, hungUp: true });
      }
    } catch (e) {
      setError(`The line crackled. ${e}`);
    } finally { setTalking(false); }
  };
  const hangUp = () => { sfx('phone-hangup'); setJob(j => j && { ...j, hungUp: true }); setPanel('none'); };

  // ---------------------------------------------------------------- the grant
  const seal = async (wish: string) => {
    if (!job) return;
    setJob({ ...job, draft: wish, wish }); setPanel('granting');
    const l = lighting.current;
    l?.breathe(true);          // the room dims and swells while the genie thinks
    try {
      const g = await api.grant({ client_id: job.client.id, wish });
      setJob(j => j && { ...j, grant: g });
      setPanel('result');
      void say(g.genie);
    } catch (e) {
      setError(`The lamp sputtered out. ${e}`);
      setPanel('wish');
    } finally { l?.breathe(false); }
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
    if (clockRunning && cfg && secondsLeft === 0) {
      bell();
      void seal(draftRef.current.trim());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clockRunning, secondsLeft]);
  const startClock = () => {
    if (!job || !cfg) return;
    draftRef.current = job.draft; setNow(Date.now());
    setJob({ ...job, deadline: Date.now() + cfg.wish_seconds * 1000 });
  };

  const showReview = () => setPanel('review');      // reviews are text only
  const after = job?.grant ? { ...ratings, [job.client.id]: { stars: job.grant.stars, pay: job.grant.bill.pay } } : ratings;
  const finishJob = () => {
    if (!job?.grant || !cfg) return;
    setRatings(after); setJob(null);
    setPanel(karmaWith(after) >= cfg.win_karma ? 'won' : 'none');
  };
  const restart = () => { setRatings({}); setJob(null); setPanel('none'); };

  // ---------------------------------------------------------------- incoming calls
  // The player picks a client from the notepad; that client calls in a moment later.
  const [queued, setQueued] = useState(false);
  const pick = (c: ClientCard) => {
    setPanel('none'); setQueued(true);
    setTimeout(() => { setQueued(false); setCaller(c); stopRing.current = ring(); }, 2000);
  };
  const answer = () => {
    if (!caller) return;
    stopRing.current?.(); stopRing.current = null; sfx('phone-pickup');
    setCaller(null); void startCall(caller);
  };

  // ---------------------------------------------------------------- desk objects
  const ringing = !!caller;
  const canStartClock = !!job && job.hungUp && !job.deadline;
  const canWish = clockRunning;
  const idle = !job && !queued && !caller;     // no client picked: the light switch still works
  const labels: Partial<Record<Spot, string>> = !lit ? { bulb: 'Turn on the light' } : {
    bulb: idle ? 'Turn off the light' : undefined,
    lava: cfg ? `Karma ${karma} / ${cfg.win_karma}` : undefined,
    phone: ringing ? 'Answer the phone'
      : job && !job.deadline && !job.ended ? `Call ${job.client.name.split(' ')[0]} back` : undefined,
    notepad: job ? 'Case notes' : "Tonight's clients",
    timer: canStartClock && cfg ? `You'll have ${cfg.wish_seconds} seconds to wish. Start the clock`
      : clockRunning ? `${secondsLeft} seconds left`
      : job && !job.hungUp ? (job.ended ? 'No questions left' : `${questionsLeft} question${questionsLeft === 1 ? '' : 's'} left`) : undefined,
    lamp: canWish ? 'Rub the lamp' : undefined,
  };
  const onSpot = (s: Spot) => {
    if (s === 'bulb' && !lit) { sfx('light-switch', 0.25); setLit(true); lighting.current?.setBulb(true); lighting.current?.flicker(); }
    else if (s === 'bulb' && idle) { sfx('light-switch', 0.25); setLit(false); lighting.current?.setBulb(false); }
    if (s === 'phone') {
      if (ringing) answer();
      else if (job && !job.deadline && !job.ended) { sfx('phone-pickup'); setPanel('call'); }
    }
    if (s === 'notepad') setPanel('notepad');
    if (s === 'timer' && canStartClock) startClock();
    if (s === 'lamp' && canWish) setPanel('wish');
  };

  return (
    <main className="room">
      <Desk labels={labels} attention={!lit ? 'bulb' : ringing ? 'phone' : canStartClock ? 'timer' : canWish && panel !== 'wish' ? 'lamp' : !job && !queued ? 'notepad' : null} onSpot={onSpot} onLighting={onLighting} />
      <VolumeSlider />
      {cfg?.llm_fake && <div className="tag">Fake mode: canned responses</div>}
      {loadError && <Overlay><p className="type error">
        {loadError.includes('access code') ? loadError.replace(/^Error: /, '') : <>Can't reach the server. Is it running?<br />{loadError}</>}
      </p></Overlay>}

      {panel === 'call' && job && cfg && (
        <CallPanel client={job.client} log={job.log} asked={job.asked} questionsLeft={questionsLeft} totalQuestions={cfg.questions_per_call}
          talking={talking} ended={job.ended} revealed={job.revealed} fresh={fresh}
          onAsk={id => void ask(id)} onHangUp={hangUp} />
      )}
      {panel === 'call' && error && <div className="toast">{error}</div>}
      {panel === 'notepad' && (
        <Overlay onClose={() => setPanel('none')}>
          {job ? <Notepad client={job.client} revealed={job.revealed} />
            : <Roster cards={cards} ratings={ratings} karma={karma} winKarma={cfg?.win_karma ?? 100} busy={queued || ringing}
                onPick={pick} onRestart={restart} />}
        </Overlay>
      )}
      {panel === 'wish' && job && cfg && (
        <WishPanel client={job.client} revealed={job.revealed} cfg={cfg} initial={job.draft} secondsLeft={secondsLeft}
          onDraft={d => { draftRef.current = d; }}
          onSeal={w => void seal(w)} onClose={draft => { setJob({ ...job, draft }); setPanel('none'); }} />
      )}
      {panel === 'wish' && error && <div className="toast">{error}</div>}
      {panel === 'granting' && <Granting />}
      {panel === 'result' && job?.grant && job.wish && <ResultPanel client={job.client} wish={job.wish} grant={job.grant} onDone={showReview} />}
      {panel === 'review' && job?.grant && <ReviewPanel client={job.client} grant={job.grant} karmaBefore={karma} karmaAfter={karmaWith(after)} onDone={finishJob} />}
      {panel === 'won' && <WinPanel karma={karma} onRestart={restart} />}
    </main>
  );
}

/** One slider for every sound in the game. */
function VolumeSlider() {
  const [v, setV] = useState(getVolume);
  return (
    <label className="volume">
      <span>Volume</span>
      <input type="range" min={0} max={1} step={0.05} value={v} onChange={e => { const x = Number(e.target.value); setV(x); setVolume(x); }} />
    </label>
  );
}
