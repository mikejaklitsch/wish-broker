// The overlays that open from desk objects. Each is a plain component driven by props; no game logic here.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { ClientCard, GameConfig, GrantResult } from './types.gen';

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
  cards: ClientCard[]; ratings: Record<string, Rating>; karma: number; winKarma: number; busy: boolean;
  onPick: (c: ClientCard) => void; onRestart: () => void;
}) {
  const allDone = cards.length > 0 && cards.every(c => c.id in ratings);
  return (
    <div className="pad">
      <p className="hand pad-title">Tonight's clients</p>
      <p className="hand muted">{busy ? 'The phone will ring any second.' : allDone ? `That's everyone. Karma: ${karma} of ${winKarma}. Pick anyone to try again.` : 'Pick who calls next.'}</p>
      <ul className="roster">
        {cards.map(c => {
          const r = ratings[c.id];
          return (
            <li key={c.id}>
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
export function Notepad({ client, revealed, fresh }: { client: ClientCard | null; revealed: Record<string, string>; fresh?: Set<string> }) {
  if (!client) return <div className="pad"><p className="hand">No client on the line.</p></div>;
  return (
    <div className="pad">
      <p className="hand pad-title">{client.name}</p>
      <ul className="facts">
        {client.facts.filter(f => f.requires.every(r => r in revealed)).map(f => {
          const v = revealed[f.id];
          return (
            <li key={f.id} className={`${v ? 'known' : 'unknown'}${fresh?.has(f.id) ? ' fresh' : ''}`}>
              <span className="box" aria-hidden="true">{v ? '✓' : '?'}</span>
              <span className="hand q">{f.label}</span>
              {v && <span className="hand a">{v}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------- the call: scripted questions
export interface CallLine { who: 'broker' | 'client'; text: string }

export function CallPanel({ client, log, asked, questionsLeft, totalQuestions, talking, ended, revealed, fresh, onAsk, onHangUp }: {
  client: ClientCard; log: CallLine[]; asked: Set<string>; questionsLeft: number; totalQuestions: number;
  talking: boolean; ended: boolean; revealed: Record<string, string>; fresh: Set<string>;
  onAsk: (questionId: string) => void; onHangUp: () => void;
}) {
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' }); }, [log]);
  const first = client.name.split(' ')[0];
  return (
    <Overlay wide>
      <div className="split">
        <div className="call">
          <div className="call-head type">
            <span>On the line: {client.name}</span>
            <span className={`clock${questionsLeft <= 1 ? ' low' : ''}`}>{questionsLeft} of {totalQuestions} questions left</span>
          </div>
          <div className="call-log" ref={logRef}>
            {log.map((l, i) => (
              <p key={i} className={`line ${l.who}`}><b>{l.who === 'client' ? first : 'You'}:</b> {l.text}</p>
            ))}
          </div>
          {!ended && (
            <div className="questions">
              {client.questions.filter(q => q.requires.every(r => r in revealed)).map(q => (
                <button key={q.id} className={`question${q.requires.some(r => fresh.has(r)) && !asked.has(q.id) ? ' unlocked' : ''}`}
                  disabled={talking || asked.has(q.id)} onClick={() => onAsk(q.id)}>
                  {q.text}
                </button>
              ))}
            </div>
          )}
          <button className="hangup" disabled={talking && !ended} onClick={onHangUp}>{ended ? 'Put the phone down' : 'Hang up'}</button>
        </div>
        <Notepad client={client} revealed={revealed} fresh={fresh} />
      </div>
    </Overlay>
  );
}

// ---------------------------------------------------------------- the wish contract
export function WishPanel({ client, revealed, cfg, initial, secondsLeft, onDraft, onSeal, onClose }: {
  client: ClientCard; revealed: Record<string, string>; cfg: GameConfig; initial: string; secondsLeft: number;
  onDraft: (draft: string) => void; onSeal: (wish: string) => void; onClose: (draft: string) => void;
}) {
  const [wish, setWishState] = useState(initial);
  const setWish = (w: string) => { setWishState(w); onDraft(w); };
  const words = (wish.match(/\S+/g) ?? []).length;
  return (
    <Overlay wide onClose={() => onClose(wish)}>
      <div className="split">
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
        <Notepad client={client} revealed={revealed} />
      </div>
    </Overlay>
  );
}

// ---------------------------------------------------------------- genie's answer
export function ResultPanel({ client, wish, grant, onDone }: { client: ClientCard; wish: string; grant: GrantResult; onDone: () => void }) {
  return (
    <Overlay>
      <div className="contract">
        <p className="type small muted">"{wish}"</p>
        <p className="genie">{grant.genie.text}</p>
        <button className="primary" onClick={onDone}>Read the review</button>
      </div>
    </Overlay>
  );
}

// ---------------------------------------------------------------- the review
export function ReviewPanel({ client, grant, karmaBefore, karmaAfter, onDone }: {
  client: ClientCard; grant: GrantResult; karmaBefore: number; karmaAfter: number; onDone: () => void;
}) {
  const b = grant.bill;
  return (
    <Overlay>
      <div className="review">
        <div className="stars" aria-label={`${grant.stars} out of 5 stars`}>{'★'.repeat(grant.stars)}<span>{'★'.repeat(5 - grant.stars)}</span></div>
        <p className="review-text">{grant.review.text}</p>
        <p className="review-by">{client.name}</p>
        {grant.scorecard && (
          <ul className="score type small">
            <li>Got what {client.name.split(' ')[0]} was after: {grant.scorecard.goal_met}</li>
            <li>How {client.name.split(' ')[0]} feels about the rest: {grant.scorecard.feeling}</li>
            <li>{grant.scorecard.note}</li>
          </ul>
        )}
        <table className="ledger type small">
          <tbody>
            <tr><td>Paid ({grant.stars}★)</td><td>+{b.pay}</td></tr>
            {karmaBefore + b.pay > karmaAfter && <tr><td>Replaces your last try</td><td>−{karmaBefore + b.pay - karmaAfter}</td></tr>}
            <tr className="total"><td>Karma</td><td>{karmaBefore} → {karmaAfter}</td></tr>
          </tbody>
        </table>
        <button className="primary" onClick={onDone}>Hang up</button>
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
      <div className="contract">
        <h2 className="type">{karma} karma.</h2>
        <p className="genie">Fine. The lamp owes you a wish of your own. Word it carefully.</p>
        <button className="primary" onClick={onRestart}>Start over</button>
      </div>
    </Overlay>
  );
}
