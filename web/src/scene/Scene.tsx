import { Sparkles } from '@react-three/drei';
import { Canvas, useFrame } from '@react-three/fiber';
import { Bloom, ChromaticAberration, EffectComposer, Noise, Vignette } from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';
import { useMemo, useRef } from 'react';
import { type Group, Vector2 } from 'three';
import { CoreActivity } from './CoreActivity';
import { EarthGlobe } from './EarthGlobe';
import { GridFloor } from './GridFloor';
import { HudRings } from './HudRings';
import { Orbits } from './Orbits';
import { ParticleDisk } from './ParticleDisk';
import { ReactorCore } from './ReactorCore';
import { scene, updateScene } from './sceneState';
import { Spectrum } from './Spectrum';

const FOV = 40;
const HALF_FOV_TAN = Math.tan(((FOV / 2) * Math.PI) / 180);

/** Runs before every other frame callback so components read fresh values. */
function SceneDriver() {
  useFrame((state, delta) => updateScene(state.clock.elapsedTime, Math.min(delta, 0.1)), -1);
  return null;
}

/** Mouse parallax + aspect-aware framing so the rings always fit. */
function CameraRig() {
  useFrame((state, delta) => {
    const { camera, pointer, size } = state;
    const aspect = size.width / size.height;
    const fitHeight = 4.25 / HALF_FOV_TAN;
    const fitWidth = 3.6 / (HALF_FOV_TAN * aspect);
    const distance = Math.max(fitHeight, fitWidth);
    const k = 1 - Math.exp(-delta * 2.2);
    camera.position.x += (pointer.x * 0.8 - camera.position.x) * k;
    camera.position.y += (0.55 + pointer.y * 0.45 - camera.position.y) * k;
    camera.position.z += (distance - camera.position.z) * k;
    camera.lookAt(0, 0, 0);
  });
  return null;
}

function Hologram({ visible }: { visible: boolean }) {
  const group = useRef<Group>(null);
  const progress = useRef(0);

  useFrame((_, delta) => {
    if (!group.current) return;
    progress.current = Math.min(1, progress.current + (visible ? delta / 1.8 : 0));
    const p = progress.current;
    const eased = 1 - Math.pow(1 - p, 4);
    group.current.scale.setScalar(Math.max(0.001, eased * (1 + scene.surge * 0.015)));
    group.current.rotation.z = (1 - eased) * -1.4;
  });

  return (
    <group ref={group} scale={0.001}>
      <ReactorCore />
      <CoreActivity />
      <EarthGlobe />
      <HudRings />
      <Spectrum />
      <Orbits />
      <ParticleDisk />
    </group>
  );
}

export function Scene({ visible }: { visible: boolean }) {
  const aberration = useMemo(() => new Vector2(0.0007, 0.0005), []);

  return (
    <Canvas
      className="scene"
      dpr={[1, 1.75]}
      gl={{ antialias: false, powerPreference: 'high-performance', alpha: false, stencil: false }}
      camera={{ position: [0, 0.6, 14], fov: FOV, near: 0.1, far: 120 }}
    >
      <color attach="background" args={['#010409']} />
      <fog attach="fog" args={['#010409', 12, 34]} />
      <SceneDriver />
      <CameraRig />
      <Hologram visible={visible} />
      <GridFloor />
      <Sparkles count={90} scale={[20, 11, 10]} size={2.2} speed={0.25} opacity={0.45} color="#7fe9ff" noise={0.6} />
      <EffectComposer multisampling={0} enableNormalPass={false}>
        <Bloom mipmapBlur intensity={1.05} luminanceThreshold={0.08} luminanceSmoothing={0.35} radius={0.78} />
        <ChromaticAberration offset={aberration} radialModulation modulationOffset={0.35} blendFunction={BlendFunction.NORMAL} />
        <Noise premultiply blendFunction={BlendFunction.SCREEN} opacity={0.05} />
        <Vignette offset={0.22} darkness={0.82} />
      </EffectComposer>
    </Canvas>
  );
}
