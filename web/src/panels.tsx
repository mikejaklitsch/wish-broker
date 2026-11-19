// The overlays that open from desk objects. Each is a plain component driven by props; no game logic here.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { CallCard, GameConfig, GrantResult, Scorecard } from './types.gen';

export function Overlay({ children, onClose, wide }: { children: ReactNode; onClose?: () => void; wide?: boolean }) {
  useEffect(() => {
    if (!onClose) return;
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className="overlay" onPointerDown={e => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div className={`overlay-body${wide ? ' wide' : ''}`}>{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------- notepad: tonight's clients
export interface Rating { stars: number; pay: number }

export function Roster({ cards, ratings, karma, winKarma, busy, onPick, onRestart }: {
  cards: CallCard[]; ratings: Record<string, Rating>; karma: number; winKarma: number; busy: boolean;
  onPick: (c: CallCard) => void; onRestart: () => void;
}) {
  const done = (c: CallCard) => c.agent_id in ratings;
  const allDone = cards.length > 0 && cards.every(done);
  const ordered = [...cards.filter(c => !done(c)), ...cards.filter(done)];     // finished clients sink to the bottom
  return (
    <div className="pad">
      <p className="hand pad-title">Tonight's clients</p>
      <p className="hand muted">{busy ? 'The phone will ring any second.' : allDone ? `That's everyone. Karma: ${karma} of ${winKarma}. Pick anyone to try again.` : 'Pick who calls next.'}</p>
      <ul className="roster">
        {ordered.map(c => {
          const r = ratings[c.agent_id];
          return (
            <li key={c.agent_id}>
              <button className="hand" disabled={busy} onClick={() => onPick(c)} title={r ? 'Try again; the new result replaces this one' : undefined}>
                <span className="r-name">{c.name}</span>
                <span className="r-job">{c.profession}</span>
                {r && <span className="r-stars" aria-label={`${r.stars} out of 5 stars`}>{'★'.repeat(r.stars)}<span>{'★'.repeat(5 - r.stars)}</span> +{r.pay}</span>}
              </button>
            </li>
          );
        })}
      </ul>
      <button className="link" onClick={onRestart}>Start over</button>
    </div>
  );
}

// ---------------------------------------------------------------- notepad: case file
/** Something the client told the broker, jotted down by their agent's note tool. ask: what they called to ask for. */
export interface Note { text: string; ask?: boolean }

/** What the client has said so far, one line per note in the order it came up, with what they asked for kept at the top.
 *  Nothing marks which lines matter to the wish: that's for the broker to judge. */
export function Notepad({ client, notes, fresh }: { client: CallCard | null; notes: Note[]; fresh?: Set<string> }) {
  if (!client) return <div className="pad"><p className="hand">No client on the line.</p></div>;
  const ask = notes.find(n => n.ask);
  return (
    <div className="pad">
      <p className="hand pad-title">{client.name}</p>
      {ask && <p className={`hand ask${fresh?.has(ask.text) ? ' fresh' : ''}`}><span className="muted">Asked for:</span> {ask.text}</p>}
      <ul className="facts">
        {notes.filter(n => n !== ask).map(n => (
          <li key={n.text} className={`known${fresh?.has(n.text) ? ' fresh' : ''}`}>
            <span className="hand" aria-hidden="true">•</span>
            <span className="hand a">{n.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------- the call: live, with the client's agent
export interface CallLine {
  who: 'broker' | 'client'; text: string;
  live?: { raw: string; from: number };     // still being spoken: shown as far as it's been heard (see App's typed)
}
export type CallStatus = 'connecting' | 'live' | 'over';

export function CallPanel({ client, log, status, talking, notes, fresh, secondsLeft, mic, onHangUp }: {
  client: CallCard; log: CallLine[]; status: CallStatus; talking: boolean; notes: Note[]; fresh: Set<string>;
  secondsLeft?: number;     // the call clock; the callback has none
  mic?: number;             // the broker's mic: -1 off, else bars 0..5, plus 10 while the call hears a voice
  onHangUp: () => void;
}) {
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' }); }, [log]);
  const first = client.name.split(' ')[0];
  const state = status === 'connecting' ? 'Connecting…' : status === 'over' ? 'Call ended' : talking ? `${first} is talking` : 'Listening…';
  return (
    <Overlay wide>
      <div className="split">
        <div className="call">
          <div className="call-head type">
            <span>On the line: {client.name}</span>
            <span className={`clock${secondsLeft !== undefined && secondsLeft <= 15 ? ' low' : ''}`}>
              {state}
              {secondsLeft !== undefined && status === 'live' && (secondsLeft > 0
                ? ` · ${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, '0')}` : " · Time's up")}
            </span>
          </div>
          <div className="call-log" ref={logRef}>
            {log.map((l, i) => (
              <p key={i} className={`line ${l.who}${l.live ? ' live' : ''}`}><b>{l.who === 'client' ? first : 'You'}:</b> {l.text}</p>
            ))}
          </div>
          {mic !== undefined && status === 'live' && <MicMeter mic={mic} />}
          <button className="hangup" onClick={onHangUp}>{status === 'over' ? 'Put the phone down' : 'Hang up'}</button>
        </div>
        <Notepad client={client} notes={notes} fresh={fresh} />
      </div>
    </Overlay>
  );
}

function MicMeter({ mic }: { mic: number }) {
  const off = mic < 0, heard = mic >= 10, bars = off ? 0 : mic % 10;
  return (
    <div className={`mic${off ? ' off' : ''}${heard ? ' heard' : ''}`}>
      <span className="bars">{[1, 2, 3, 4, 5].map(b => <i key={b} className={b <= bars ? 'on' : ''} />)}</span>
      {off ? 'Your mic is off' : heard ? 'Hearing you' : 'Your mic'}
    </div>
  );
}

// ---------------------------------------------------------------- the wish contract
export function WishPanel({ client, notes, cfg, initial, secondsLeft, onDraft, onSeal, onClose }: {
  client: CallCard; notes: Note[]; cfg: GameConfig; initial: string; secondsLeft: number;
  onDraft: (draft: string) => void; onSeal: (wish: string) => void; onClose: (draft: string) => void;
}) {
  const [wish, setWishState] = useState(initial);
  const setWish = (w: string) => { setWishState(w); onDraft(w); };
  const words = (wish.match(/\S+/g) ?? []).length;
  return (
    <Overlay wide onClose={() => onClose(wish)}>
      <div className="split wish-split">
        <img className="genie-portrait" src="/scene/genie.jpg" alt="The genie, rising from his lamp" />
        <div className="contract">
          <h2 className="type">Wish contract</h2>
          <p className="type small">On behalf of {client.name}.</p>
          <textarea className="type" value={wish} onChange={e => setWish(e.target.value)} placeholder="I wish…" autoFocus rows={7} />
          <div className="meter type small">
            <span>{words} words</span>
            <span className={`clock${secondsLeft <= 15 ? ' low' : ''}`}>{secondsLeft}s left</span>
          </div>
          <div className="row">
            <button className="primary" disabled={!words} onClick={() => onSeal(wish.trim())}>Seal the wish</button>
            <button className="link" onClick={() => onClose(wish)}>Not yet</button>
          </div>
        </div>
        <Notepad client={client} notes={notes} />
      </div>
    </Overlay>
  );
}

// ---------------------------------------------------------------- genie's answer
export function ResultPanel({ wish, grant, onDone }: { wish: string; grant: GrantResult; onDone: () => void }) {
  return (
    <Overlay wide>
      <div className="split genie-split">
        <img className="genie-portrait" src="/scene/genie.jpg" alt="The genie, rising from his lamp" />
        <div className="contract centered">
          <p className="type small muted">"{wish}"</p>
          <p className="genie">{grant.genie.text}</p>
          <button className="primary" onClick={onDone}>{grant.refused ? 'Try again' : 'Done'}</button>
        </div>
      </div>
    </Overlay>
  );
}

// ---------------------------------------------------------------- the review
// The close button, by stars: the broker shrugging it off.
const SHRUG: Record<number, string> = {
  1: "They'll be back.", 2: "Can't win 'em all", 3: 'Close enough', 4: "I'll take it", 5: 'Another happy customer',
};

/** The client's review, posted on their callback, with the stars and pay the server worked out from it. */
export interface Review extends Scorecard { text: string; stars: number; pay: number }

export function ReviewPanel({ client, review, karmaBefore, karmaAfter, onDone }: {
  client: CallCard; review: Review; karmaBefore: number; karmaAfter: number; onDone: () => void;
}) {
  const first = client.name.split(' ')[0];
  return (
    <Overlay>
      <div className="review">
        <div className="stars" aria-label={`${review.stars} out of 5 stars`}>{'★'.repeat(review.stars)}<span>{'★'.repeat(5 - review.stars)}</span></div>
        <p className="review-text">{review.text}</p>
        <p className="review-by">{client.name}</p>
        <ul className="score type small">
          <li>Got what {first} was after: {review.goal_met}</li>
          <li>How {first} feels about the rest: {review.feeling}</li>
        </ul>
        <table className="ledger type small">
          <tbody>
            <tr><td>Paid ({review.stars}★)</td><td>+{review.pay}</td></tr>
            {karmaBefore + review.pay > karmaAfter && <tr><td>Replaces your last try</td><td>−{karmaBefore + review.pay - karmaAfter}</td></tr>}
            <tr className="total"><td>Karma</td><td>{karmaBefore} → {karmaAfter}</td></tr>
          </tbody>
        </table>
        <button className="primary" onClick={onDone}>{SHRUG[review.stars]}</button>
      </div>
    </Overlay>
  );
}

export function Granting() {
  // A light scrim only, so the room's dimming and swelling stays visible behind the words.
  return <div className="overlay thinking"><p className="genie">The lamp grows warm…</p></div>;
}

export function WinPanel({ karma, onRestart }: { karma: number; onRestart: () => void }) {
  return (
    <Overlay>
      <div className="contract centered">
        <h2 className="type">You earned {karma} Karma!</h2>
        <p className="genie">Congratulations! You've earned a wish of your own, surely this won't go wrong...</p>
        <button className="primary" onClick={onRestart}>Start over</button>
      </div>
    </Overlay>
  );
}

/** The first thing the player sees: who they are and how the job works. */
export function IntroPanel({ winKarma, timeoutPenalty, onStart }: { winKarma: number; timeoutPenalty: number; onStart: () => void }) {
  return (
    <Overlay>
      <div className="intro">
        <h1>Wish Broker</h1>
        <p>You're a professional wish maker. People call you when they have a wish to spend but no idea how to do it right. Your job is to find out what they really want and make sure the genie can't twist your words.</p>
        <p>Happy clients leave good reviews and good reviews pay in karma. The genie isn't patient, so failing to make a wish in time will lose you {timeoutPenalty} karma. Collect {winKarma} karma to earn a wish of your own and win the game!</p>
        <button className="primary" onClick={onStart}>Open for business</button>
      </div>
    </Overlay>
  );
}
