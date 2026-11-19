// Keeps a client from wearing out a pet word ("honestly", "okay"). The model playing them repeats its fillers whatever the
// persona says (measured: prompt wording and temperature barely move it), so the call counts them and tells the client
// as it goes, in a note the broker never hears. Measured on Kim and Danny: "honestly" in about half as many replies.

const MIN = 2;      // replies a phrase has been used in before the client is told
const ANSWERS = new Set(['yes', 'no', 'yeah', 'thanks', 'thank you', 'hi', 'oh', 'um', 'uh']);     // answers and sounds, not habits

const words = (t: string) => t.replace(/\[[^\]]*\]/g, ' ').toLowerCase().replace(/’/g, "'");
// Short stand-alone bits between punctuation: "honestly", "okay", "trust me", "I mean".
const asides = (reply: string) => words(reply).split(/[,.;:!?…]+/).map(s => s.trim().split(/\s+/).filter(Boolean))
  .filter(s => s.length >= 1 && s.length <= 2).map(s => s.join(' ')).filter(a => !ANSWERS.has(a));

/** The note to send the client after their latest reply, or null when nothing more has worn out.
 *  `told` is what they've already been told, kept by the caller for the length of the call. */
export function wornNote(replies: string[], told: Map<string, number>): string | null {
  const known = new Set(replies.flatMap(asides));     // once a phrase has stood alone as an aside, every use of it counts
  const flat = replies.map(r => ` ${words(r).replace(/[,.;:!?…]+/g, ' ').split(/\s+/).filter(Boolean).join(' ')} `);
  const worn = [...known].map(a => [a, flat.filter(t => t.includes(` ${a} `)).length] as const).filter(([, n]) => n >= MIN);
  if (!worn.some(([a, n]) => n > (told.get(a) ?? 0))) return null;
  worn.forEach(([a, n]) => told.set(a, n));
  const said = worn.sort((x, y) => y[1] - x[1]).map(([a, n]) => `"${a}" in ${n}`).join(', ');
  return `(A note for you, not something the broker said. Count of your replies on this call that used a phrase: ${said}. `
    + "You've worn those out. From here on leave them out and put it another way.)";
}
