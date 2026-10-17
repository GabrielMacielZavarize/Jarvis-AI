import { useFrame } from '@react-three/fiber';
import { useLayoutEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, Color, type InstancedMesh, Object3D, PlaneGeometry } from 'three';
import { BANDS, levels } from '../lib/audio';
import { scene } from './sceneState';

const BARS = 120;
const RADIUS = 2.12;
const MAX_LENGTH = 0.44;

/** Radial audio spectrum: reads as a dashed ring when silent, blooms when Jarvis speaks. */
export function Spectrum() {
  const mesh = useRef<InstancedMesh>(null);
  const dummy = useMemo(() => new Object3D(), []);
  const tint = useMemo(() => new Color(), []);
  const geometry = useMemo(() => {
    const plane = new PlaneGeometry(0.022, 1);
    plane.translate(0, 0.5, 0);
    return plane;
  }, []);
  const bandOf = useMemo(
    () =>
      Array.from({ length: BARS }, (_, i) => {
        const half = BARS / 2;
        const t = i < half ? i / half : (BARS - 1 - i) / half;
        return Math.min(BANDS - 1, Math.floor(t * BANDS));
      }),
    [],
  );

  useLayoutEffect(() => {
    if (!mesh.current) return;
    for (let i = 0; i < BARS; i++) mesh.current.setColorAt(i, tint.set('#ffffff'));
  }, [tint]);

  useFrame((state) => {
    const instanced = mesh.current;
    if (!instanced) return;
    const t = state.clock.elapsedTime;
    for (let i = 0; i < BARS; i++) {
      const band = bandOf[i];
      const voice = Math.max(levels.agentBands[band], levels.userBands[band] * 0.9);
      const idle = 0.035 + 0.025 * (0.5 + 0.5 * Math.sin(scene.phase * 2.6 + i * 0.32));
      const value = idle + voice * MAX_LENGTH * 1.8;
      const angle = (i / BARS) * Math.PI * 2 + Math.PI / 2;
      dummy.position.set(Math.cos(angle) * RADIUS, Math.sin(angle) * RADIUS, 0);
      dummy.rotation.set(0, 0, angle - Math.PI / 2);
      dummy.scale.set(1, Math.min(MAX_LENGTH, value), 1);
      dummy.updateMatrix();
      instanced.setMatrixAt(i, dummy.matrix);

      const userDominant = levels.userBands[band] > levels.agentBands[band];
      tint
        .copy(userDominant ? WHITE_CYAN : scene.primary)
        .multiplyScalar(scene.glow * (0.55 + voice * 2.6) + Math.sin(t * 3 + i) * 0.04);
      instanced.setColorAt(i, tint);
    }
    instanced.instanceMatrix.needsUpdate = true;
    if (instanced.instanceColor) instanced.instanceColor.needsUpdate = true;
  });

  return (
    <instancedMesh ref={mesh} args={[geometry, undefined, BARS]} frustumCulled={false}>
      <meshBasicMaterial transparent opacity={0.9} depthWrite={false} blending={AdditiveBlending} toneMapped={false} />
    </instancedMesh>
  );
}

const WHITE_CYAN = new Color('#d8fdff');
