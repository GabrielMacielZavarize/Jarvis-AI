import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import { AdditiveBlending, type BufferGeometry, DoubleSide, type Mesh, type MeshBasicMaterial } from 'three';
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
}

function RingLayer({ geometry, spin = 0, opacity = 0.6, tone = 'primary', z = 0, react = 0.4, breathe = 0, offset = 0 }: LayerProps) {
  const mesh = useRef<Mesh>(null);
  const material = useRef<MeshBasicMaterial>(null);

  useFrame(() => {
    if (!mesh.current || !material.current) return;
    mesh.current.rotation.z = offset + scene.phase * spin;
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

export function HudRings() {
  const g = useMemo(
    () => ({
      inner: circle(1.62, 0.012),
      innerDots: dashes(1.52, 0.02, 120, 0.25),
      segments: arcs(1.77, 0.05, [
        [10, 100],
        [130, 100],
        [250, 100],
      ]),
      scale: ticks(180, 1.9, 0.05, 0.008, 15, 0.12),
      dashed: dashes(2.64, 0.014, 90, 0.5),
      accent: arcs(2.76, 0.055, [
        [20, 48],
        [200, 48],
      ]),
      accentThin: arcs(2.84, 0.01, [
        [70, 90],
        [250, 90],
      ]),
      outer: circle(2.98, 0.008, 220),
      brackets: arcs(2.98, 0.06, [
        [-4, 8],
        [86, 8],
        [176, 8],
        [266, 8],
      ]),
      pointers: pointers(3.06, 0.09, [90, 210, 330]),
    }),
    [],
  );

  return (
    <group>
      <RingLayer geometry={g.innerDots} spin={-0.12} opacity={0.5} react={0.8} />
      <RingLayer geometry={g.inner} opacity={0.75} breathe={0.12} react={0.6} />
      <RingLayer geometry={g.segments} spin={0.32} opacity={0.55} z={0.02} />
      <RingLayer geometry={g.scale} spin={-0.05} opacity={0.6} z={-0.02} />
      <RingLayer geometry={g.dashed} spin={0.09} opacity={0.45} react={0.6} />
      <RingLayer geometry={g.accent} spin={-0.42} opacity={0.7} tone="accent" z={0.04} />
      <RingLayer geometry={g.accentThin} spin={0.22} opacity={0.5} tone="accent" offset={1} />
      <RingLayer geometry={g.outer} opacity={0.3} react={0.2} />
      <RingLayer geometry={g.brackets} spin={0.03} opacity={0.8} />
      <RingLayer geometry={g.pointers} spin={-0.03} opacity={0.6} tone="accent" />
    </group>
  );
}
