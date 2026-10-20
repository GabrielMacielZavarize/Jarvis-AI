import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';
import { AdditiveBlending, Color, type Group, type MeshBasicMaterial } from 'three';
import { scene } from './sceneState';

interface OrbitProps {
  radius: number;
  tilt: [number, number, number];
  spin: number;
  tone?: 'primary' | 'accent';
}

/** A tilted gyroscope ring with a travelling node — gives the flat HUD real depth. */
function Orbit({ radius, tilt, spin, tone = 'primary' }: OrbitProps) {
  const spinner = useRef<Group>(null);
  const ringMat = useRef<MeshBasicMaterial>(null);
  const nodeMat = useRef<MeshBasicMaterial>(null);
  const tailMat = useRef<MeshBasicMaterial>(null);

  useFrame(() => {
    if (spinner.current) spinner.current.rotation.z = scene.phase * spin;
    if (ringMat.current) {
      ringMat.current.color.copy(scene[tone]).multiplyScalar(scene.glow * 0.9);
      ringMat.current.opacity = 0.32 + scene.energy * 0.4;
    }
    if (nodeMat.current) nodeMat.current.color.copy(scene[tone]).multiplyScalar(2.4 * scene.glow + scene.energy * 2);
    if (tailMat.current) tailMat.current.color.copy(scene.primary).lerp(WHITE, 0.5).multiplyScalar(1.4);
  });

  return (
    <group rotation={tilt}>
      <group ref={spinner}>
        <mesh>
          <torusGeometry args={[radius, 0.005, 6, 220]} />
          <meshBasicMaterial ref={ringMat} transparent depthWrite={false} blending={AdditiveBlending} toneMapped={false} />
        </mesh>
        <mesh position={[radius, 0, 0]}>
          <sphereGeometry args={[0.045, 16, 16]} />
          <meshBasicMaterial ref={nodeMat} toneMapped={false} />
        </mesh>
        <mesh position={[-radius, 0, 0]} scale={0.6}>
          <sphereGeometry args={[0.045, 16, 16]} />
          <meshBasicMaterial ref={tailMat} toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
}

const ORBITS: OrbitProps[] = [
  { radius: 2.32, tilt: [1.18, 0.32, 0], spin: 0.55 },
  { radius: 2.02, tilt: [-1.05, -0.48, 0.4], spin: -0.7, tone: 'accent' },
  { radius: 2.5, tilt: [0.2, 1.3, 0.2], spin: 0.35 },
];
const WHITE = new Color('#ffffff');

/** `count` gyroscope orbits (each persona has its own number; Stealth has none). */
export function Orbits({ count = ORBITS.length }: { count?: number }) {
  return (
    <group>
      {ORBITS.slice(0, count).map((orbit) => (
        <Orbit key={orbit.radius} {...orbit} />
      ))}
    </group>
  );
}
