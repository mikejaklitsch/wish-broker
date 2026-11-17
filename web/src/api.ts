// Typed calls to the Python server. Shapes come from types.gen.ts, generated from schemas.py.
import type { AskRequest, AskResponse, ClientCard, GameConfig, GrantRequest, GrantResult } from './types.gen';

// The hosted game needs the access code from its link (?code=...). It's remembered for later visits.
const CODE_KEY = 'wish-broker-code';
function accessCode(): string {
  const fromLink = new URLSearchParams(location.search).get('code');
  try {
    if (fromLink) localStorage.setItem(CODE_KEY, fromLink);
    return fromLink ?? localStorage.getItem(CODE_KEY) ?? '';
  } catch { return fromLink ?? ''; }
}

async function call<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-Access-Code': accessCode() };
  if (body) headers['Content-Type'] = 'application/json';
  const r = await fetch(`/api${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401) throw new Error('This game needs the full link, including its access code.');
  if (!r.ok) throw new Error(`${path} failed (${r.status}): ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  config: () => call<GameConfig>('GET', '/config'),
  clients: () => call<ClientCard[]>('GET', '/clients'),
  ask: (req: AskRequest) => call<AskResponse>('POST', '/ask', req),
  grant: (req: GrantRequest) => call<GrantResult>('POST', '/grant', req),
};
