import { useFrame } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, Color, type InstancedMesh, Object3D, PlaneGeometry } from 'three';
import { BANDS, levels } from '../lib/audio';
import type { SceneStyle } from '../lib/themes';
import { scene } from './sceneState';

const RADIUS = 2.12;

/**
 * Radial audio spectrum: reads as a dashed ring when silent, blooms when Jarvis speaks. Bars by
 * default; with `dots` each band is a bead riding outwards (F.R.I.D.A.Y.).
 */
export function Spectrum({ style }: { style: SceneStyle['spectrum'] }) {
  const { bars, width, length: maxLength, dots } = style;
  const mesh = useRef<InstancedMesh>(null);
  const dummy = useMemo(() => new Object3D(), []);
  const tint = useMemo(() => new Color(), []);
  const geometry = useMemo(() => {
    const plane = new PlaneGeometry(width, dots ? width : 1);
    if (!dots) plane.translate(0, 0.5, 0);
    return plane;
  }, [width, dots]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  const bandOf = useMemo(
    () =>
      Array.from({ length: bars }, (_, i) => {
        const half = bars / 2;
        const t = i < half ? i / half : (bars - 1 - i) / half;
        return Math.min(BANDS - 1, Math.floor(t * BANDS));
      }),
    [bars],
  );

  useLayoutEffect(() => {
    if (!mesh.current) return;
    for (let i = 0; i < bars; i++) mesh.current.setColorAt(i, tint.set('#ffffff'));
  }, [tint, bars]);

  useFrame((state) => {
    const instanced = mesh.current;
    if (!instanced) return;
    const t = state.clock.elapsedTime;
    for (let i = 0; i < bars; i++) {
      const band = bandOf[i];
      const voice = Math.max(levels.agentBands[band], levels.userBands[band] * 0.9);
      const idle = 0.035 + 0.025 * (0.5 + 0.5 * Math.sin(scene.phase * 2.6 + i * 0.32));
      const value = Math.min(maxLength, idle + voice * maxLength * 1.8);
      const angle = (i / bars) * Math.PI * 2 + Math.PI / 2;
      const radius = dots ? RADIUS + value * 0.9 : RADIUS;
      dummy.position.set(Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
      dummy.rotation.set(0, 0, angle - Math.PI / 2);
      dummy.scale.set(1, dots ? 1 : value, 1);
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
    <instancedMesh key={bars} ref={mesh} args={[geometry, undefined, bars]} frustumCulled={false}>
      <meshBasicMaterial transparent opacity={0.9} depthWrite={false} blending={AdditiveBlending} toneMapped={false} />
    </instancedMesh>
  );
}

const WHITE_CYAN = new Color('#d8fdff');
