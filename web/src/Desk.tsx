// The painted desk: four lighting renders stacked, plus invisible clickable areas over each object.
import { useEffect, useRef } from 'react';
import { Lighting } from './lighting';

export type Spot = 'bulb' | 'lava' | 'phone' | 'notepad' | 'timer' | 'lamp';

const W = 1376, H = 768;
// Object bounds in image pixels: [left, top, right, bottom].
const SPOTS: Record<Spot, [number, number, number, number]> = {
  bulb: [625, 70, 750, 245],
  lava: [130, 135, 262, 560],
  phone: [530, 345, 846, 585],      // phone body only, so its label sits at screen center
  notepad: [535, 590, 845, 718],
  timer: [865, 445, 1020, 592],
  lamp: [1020, 335, 1352, 570],
};

interface Props {
  labels: Partial<Record<Spot, string>>;      // hover text; a spot without a label is not clickable
  attention?: Spot | null;                     // glows to say "click me"
  onSpot: (s: Spot) => void;
  onLighting: (l: Lighting) => void;
}

export default function Desk({ labels, attention, onSpot, onLighting }: Props) {
  const bulbOff = useRef<HTMLImageElement>(null);
  const lavaOff = useRef<HTMLImageElement>(null);
  const bothOn = useRef<HTMLImageElement>(null);

  useEffect(() => {
    document.querySelectorAll<HTMLImageElement>('.stage img').forEach(i => { i.decode?.().catch(() => {}); });
    const l = new Lighting({ bulbOff: bulbOff.current!, lavaOff: lavaOff.current!, bothOn: bothOn.current! });
    onLighting(l);
    return () => l.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="stage">
      <img src="/scene/desk-both-off.jpeg" alt="A cluttered shop counter at night: lava lamp, rotary phone, notepad, kitchen timer and a brass oil lamp" />
      <img ref={bulbOff} src="/scene/desk-bulb-off.jpeg" alt="" aria-hidden="true" />
      <img ref={lavaOff} src="/scene/desk-lava-off.jpeg" alt="" aria-hidden="true" />
      <img ref={bothOn} src="/scene/desk-both-on.jpeg" alt="" aria-hidden="true" />
      {(Object.keys(SPOTS) as Spot[]).map(s => {
        const [l, t, r, b] = SPOTS[s];
        const label = labels[s];
        return (
          <button key={s} className={`spot${attention === s ? ' attention' : ''}`} disabled={!label}
            style={{ left: `${(l / W) * 100}%`, top: `${(t / H) * 100}%`, width: `${((r - l) / W) * 100}%`, height: `${((b - t) / H) * 100}%` }}
            onClick={() => onSpot(s)} aria-label={label ?? s}>
            {label && <span className="spot-label">{label}</span>}
          </button>
        );
      })}
    </div>
  );
}
