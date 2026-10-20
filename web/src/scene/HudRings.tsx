import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, type BufferGeometry, DoubleSide, type Mesh, type MeshBasicMaterial } from 'three';
import type { RingStyle } from '../lib/themes';
import { arcs, circle, dashes, pointers, ticks } from './geometry';
import { scene } from './sceneState';

type Tone = 'primary' | 'accent' | 'secondary';

interface LayerProps {
  geometry: BufferGeometry;
  /** Radians per unit of scene phase. */
  spin?: number;
  opacity?: number;
  tone?: Tone;
  z?: number;
  /** How much the layer brightens with voice energy. */
  react?: number;
  /** How much the layer scales with the user's microphone level. */
  breathe?: number;
  offset?: number;
  /** Radians per ratchet step: the layer ticks round like a targeting reticle instead of gliding. */
  snap?: number;
}

function RingLayer({ geometry, spin = 0, opacity = 0.6, tone = 'primary', z = 0, react = 0.4, breathe = 0, offset = 0, snap = 0 }: LayerProps) {
  const mesh = useRef<Mesh>(null);
  const material = useRef<MeshBasicMaterial>(null);

  useFrame(() => {
    if (!mesh.current || !material.current) return;
    const turn = scene.phase * spin;
    mesh.current.rotation.z = offset + (snap > 0 ? Math.round(turn / snap) * snap : turn);
    const scale = 1 + scene.user * breathe + scene.surge * 0.025;
    mesh.current.scale.setScalar(scale);
    material.current.color.copy(scene[tone]).multiplyScalar(scene.glow * (1 + scene.energy * react * 1.6));
    // The rings step back while the globe grows for a search.
    const recede = 1 - scene.globeFocus * 0.6;
    material.current.opacity = Math.min(1, opacity * (0.75 + scene.energy * react) + scene.surge * 0.2) * recede;
  });

  return (
    <mesh ref={mesh} geometry={geometry} position-z={z}>
      <meshBasicMaterial
        ref={material}
        transparent
        side={DoubleSide}
        depthWrite={false}
        blending={AdditiveBlending}
        toneMapped={false}
      />
    </mesh>
  );
}

type Layer = LayerProps & { key: string };

const DEG = Math.PI / 180;

/** Each persona's rings, from the inside out (the spectrum sits at 2.12-2.56). */
const RING_SETS: Record<RingStyle, () => Layer[]> = {
  classic: () => [
    { key: 'innerDots', geometry: dashes(1.52, 0.02, 120, 0.25), spin: -0.12, opacity: 0.5, react: 0.8 },
    { key: 'inner', geometry: circle(1.62, 0.012), opacity: 0.75, breathe: 0.12, react: 0.6 },
    { key: 'segments', geometry: arcs(1.77, 0.05, [[10, 100], [130, 100], [250, 100]]), spin: 0.32, opacity: 0.55, z: 0.02 },
    { key: 'scale', geometry: ticks(180, 1.9, 0.05, 0.008, 15, 0.12), spin: -0.05, opacity: 0.6, z: -0.02 },
    { key: 'dashed', geometry: dashes(2.64, 0.014, 90, 0.5), spin: 0.09, opacity: 0.45, react: 0.6 },
    { key: 'accent', geometry: arcs(2.76, 0.055, [[20, 48], [200, 48]]), spin: -0.42, opacity: 0.7, tone: 'accent', z: 0.04 },
    { key: 'accentThin', geometry: arcs(2.84, 0.01, [[70, 90], [250, 90]]), spin: 0.22, opacity: 0.5, tone: 'accent', offset: 1 },
    { key: 'outer', geometry: circle(2.98, 0.008, 220), opacity: 0.3, react: 0.2 },
    { key: 'brackets', geometry: arcs(2.98, 0.06, [[-4, 8], [86, 8], [176, 8], [266, 8]]), spin: 0.03, opacity: 0.8 },
    { key: 'pointers', geometry: pointers(3.06, 0.09, [90, 210, 330]), spin: -0.03, opacity: 0.6, tone: 'accent' },
  ],
  // Mark III: a targeting reticle. Heavy segments, a crosshair, lock-on brackets that ratchet round.
  tactical: () => [
    { key: 'inner', geometry: circle(1.6, 0.01), opacity: 0.7, breathe: 0.1, react: 0.6 },
    { key: 'plates', geometry: arcs(1.8, 0.1, [[5, 50], [65, 50], [125, 50], [185, 50], [245, 50], [305, 50]]), spin: 0.2, opacity: 0.45, z: 0.02, snap: 6 * DEG },
    { key: 'crosshair', geometry: ticks(4, 1.95, 0.08, 0.016, 1, 0.12), opacity: 0.8, tone: 'accent' },
    { key: 'scale', geometry: ticks(72, 2.62, 0.05, 0.01, 6, 0.14), spin: -0.04, opacity: 0.55, z: -0.02 },
    { key: 'lock', geometry: arcs(2.82, 0.07, [[-14, 28], [76, 28], [166, 28], [256, 28]]), spin: 0.5, opacity: 0.85, tone: 'accent', snap: 15 * DEG },
    { key: 'track', geometry: arcs(2.9, 0.012, [[30, 120], [210, 120]]), spin: -0.25, opacity: 0.5 },
    { key: 'outer', geometry: dashes(3.02, 0.016, 48, 0.62), spin: 0.06, opacity: 0.4, react: 0.3 },
    { key: 'pointers', geometry: pointers(3.1, 0.12, [0, 90, 180, 270]), opacity: 0.75, tone: 'accent' },
  ],
  // F.R.I.D.A.Y.: long gentle arcs and dotted circles, nothing sharp.
  soft: () => [
    { key: 'dots', geometry: dashes(1.56, 0.034, 72, 0.16), spin: -0.08, opacity: 0.6, react: 0.9 },
    { key: 'inner', geometry: circle(1.68, 0.008), opacity: 0.6, breathe: 0.16, react: 0.6 },
    { key: 'arcs', geometry: arcs(1.84, 0.028, [[0, 150], [180, 150]]), spin: 0.16, opacity: 0.55, z: 0.02 },
    { key: 'dotted', geometry: dashes(2.68, 0.022, 160, 0.18), spin: -0.05, opacity: 0.5, react: 0.6 },
    { key: 'accent', geometry: arcs(2.82, 0.03, [[40, 80], [220, 80]]), spin: 0.24, opacity: 0.65, tone: 'accent', z: 0.04 },
    { key: 'outer', geometry: circle(2.98, 0.006, 220), opacity: 0.3, react: 0.2 },
    { key: 'beads', geometry: dashes(3.1, 0.04, 12, 0.1), spin: -0.07, opacity: 0.7, tone: 'accent' },
  ],
  // Stealth: three hairlines.
  minimal: () => [
    { key: 'inner', geometry: circle(1.62, 0.006), opacity: 0.45, breathe: 0.08, react: 0.4 },
    { key: 'dashed', geometry: dashes(2.64, 0.008, 60, 0.4), spin: 0.04, opacity: 0.3, react: 0.3 },
    { key: 'marks', geometry: arcs(2.8, 0.02, [[80, 20], [260, 20]]), spin: -0.1, opacity: 0.45, tone: 'accent' },
    { key: 'outer', geometry: circle(2.98, 0.005, 220), opacity: 0.2, react: 0.1 },
  ],
};

export function HudRings({ style }: { style: RingStyle }) {
  const layers = useMemo(() => RING_SETS[style](), [style]);
  useEffect(() => () => layers.forEach((layer) => layer.geometry.dispose()), [layers]);

  return (
    <group>
      {layers.map(({ key, ...layer }) => (
        <RingLayer key={`${style}-${key}`} {...layer} />
      ))}
    </group>
  );
}
