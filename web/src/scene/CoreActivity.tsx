import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, Color, DoubleSide, type Group, type Mesh, MeshBasicMaterial } from 'three';
import { arcs, circle, dashes } from './geometry';
import { scene } from './sceneState';

const ERROR_COLOR = new Color('#ff4b4b');
const BIT_ANGLES = [0, 1, 2, 3].map((index) => (index * Math.PI) / 2);

const glowMaterial = () =>
  new MeshBasicMaterial({
    transparent: true,
    opacity: 0,
    side: DoubleSide,
    depthWrite: false,
    blending: AdditiveBlending,
    toneMapped: false,
  });

/**
 * VOZ-30: "pensando" (three scanner arcs sweeping around the core and data bits orbiting it) and
 * "executando" (a ticking ring and a gyroscope spinning around the plasma) while a tool runs, plus
 * a shockwave when the tool finishes (red when it failed). Driven by scene.thinking/executing/flash.
 */
export function CoreActivity() {
  const scanner = useRef<Mesh>(null);
  const bits = useRef<Group>(null);
  const ticker = useRef<Mesh>(null);
  const gyro = useRef<Group>(null);
  const gyroA = useRef<Mesh>(null);
  const gyroB = useRef<Mesh>(null);
  const wave = useRef<Mesh>(null);

  const g = useMemo(
    () => ({
      scanner: arcs(1.43, 0.04, [
        [0, 34],
        [120, 34],
        [240, 34],
      ]),
      ticker: dashes(1.43, 0.05, 36, 0.35),
      wave: circle(1.05, 0.035, 160),
    }),
    [],
  );
  const m = useMemo(
    () => ({ scanner: glowMaterial(), bits: glowMaterial(), ticker: glowMaterial(), gyro: glowMaterial(), wave: glowMaterial() }),
    [],
  );
  useEffect(() => () => Object.values(m).forEach((material) => material.dispose()), [m]);

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    const { thinking, executing, flash } = scene;

    if (scanner.current && bits.current) {
      scanner.current.visible = bits.current.visible = thinking > 0.01;
      scanner.current.rotation.z -= delta * (1.6 + thinking * 1.4);
      bits.current.rotation.y += delta * 2.2;
      bits.current.rotation.z = Math.sin(t * 0.7) * 0.5;
      m.scanner.color.copy(scene.primary).multiplyScalar(1.4);
      m.scanner.opacity = thinking * (0.55 + Math.sin(t * 5) * 0.2);
      m.bits.color.copy(scene.accent).multiplyScalar(1.6);
      m.bits.opacity = thinking * 0.9;
    }
    if (ticker.current && gyro.current && gyroA.current && gyroB.current) {
      ticker.current.visible = gyro.current.visible = executing > 0.01;
      ticker.current.rotation.z += delta * 2.8;
      ticker.current.scale.setScalar(1 + Math.max(0, Math.sin(t * 9)) * 0.025 * executing);
      gyroA.current.rotation.x += delta * 3.1;
      gyroA.current.rotation.y += delta * 1.3;
      gyroB.current.rotation.y -= delta * 2.6;
      gyroB.current.rotation.z += delta * 0.9;
      m.ticker.color.copy(scene.accent).multiplyScalar(1.5);
      m.ticker.opacity = executing * 0.75;
      m.gyro.color.copy(scene.primary).multiplyScalar(1.3);
      m.gyro.opacity = executing * 0.6;
    }
    if (wave.current) {
      wave.current.visible = flash > 0;
      wave.current.scale.setScalar(1 + (1 - flash) * 1.7);
      m.wave.color.copy(scene.flashOk ? scene.primary : ERROR_COLOR).multiplyScalar(1.8);
      m.wave.opacity = flash * flash * 0.9;
    }
  });

  return (
    <group>
      <mesh ref={scanner} geometry={g.scanner} material={m.scanner} position-z={0.05} visible={false} />
      <group ref={bits} visible={false}>
        {BIT_ANGLES.map((angle) => (
          <mesh key={angle} material={m.bits} position={[Math.cos(angle) * 1.2, 0, Math.sin(angle) * 1.2]}>
            <boxGeometry args={[0.05, 0.05, 0.05]} />
          </mesh>
        ))}
      </group>
      <mesh ref={ticker} geometry={g.ticker} material={m.ticker} position-z={0.05} visible={false} />
      <group ref={gyro} visible={false}>
        <mesh ref={gyroA} material={m.gyro}>
          <torusGeometry args={[1.18, 0.006, 6, 160]} />
        </mesh>
        <mesh ref={gyroB} material={m.gyro} rotation={[1.2, 0, 0.4]}>
          <torusGeometry args={[1.24, 0.006, 6, 160]} />
        </mesh>
      </group>
      <mesh ref={wave} geometry={g.wave} material={m.wave} position-z={0.06} visible={false} />
    </group>
  );
}
