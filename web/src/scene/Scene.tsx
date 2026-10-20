import { Sparkles } from '@react-three/drei';
import { Canvas, useFrame } from '@react-three/fiber';
import { Bloom, ChromaticAberration, EffectComposer, Noise, Vignette } from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { type Group, Vector2 } from 'three';
import { CoreActivity } from './CoreActivity';
import { useHud } from '../lib/hudStore';
import { currentSceneProfile } from '../lib/lan';
import { usePrefs } from '../lib/prefs';
import { type SceneStyle, type ThemeId, themeInfo } from '../lib/themes';
import { type AutoState, autoStep, fixedLevel, LEVEL_LABELS, QUALITY_PROFILES, startAuto } from '../lib/quality';
import type { SceneLevel } from '../lib/types';
import { EarthGlobe } from './EarthGlobe';
import { GridFloor } from './GridFloor';
import { HudRings } from './HudRings';
import { Orbits } from './Orbits';
import { ParticleDisk } from './ParticleDisk';
import { ProjectorBeam } from './ProjectorBeam';
import { ReactorCore } from './ReactorCore';
import { scene, updateScene } from './sceneState';
import { Spectrum } from './Spectrum';

const FOV = 40;
const SPARKLE_SCALE: [number, number, number] = [20, 11, 10];
const HALF_FOV_TAN = Math.tan(((FOV / 2) * Math.PI) / 180);

/** Runs before every other frame callback so components read fresh values. */
function SceneDriver() {
  useFrame((state, delta) => updateScene(state.clock.elapsedTime, Math.min(delta, 0.1)), -1);
  return null;
}

/** Seconds of frames averaged before the automatic quality decides. */
const FPS_WINDOW_S = 4;

/** Measures the frame rate and reports it; in automatic mode it also moves the quality. */
function FrameMonitor({ level, onWindow }: { level: SceneLevel; onWindow: (fps: number) => void }) {
  const sample = useRef({ frames: 0, time: 0 });
  // Right after a level change the new shaders compile: that window says nothing about the speed.
  useEffect(() => {
    sample.current = { frames: 0, time: -FPS_WINDOW_S };
  }, [level]);
  useFrame((_, delta) => {
    // A hidden tab or a long hitch is not the scene's speed: drop that window.
    if (delta > 0.5) {
      sample.current = { frames: 0, time: 0 };
      return;
    }
    if (sample.current.time < 0) {
      sample.current.time = Math.min(0, sample.current.time + delta);
      return;
    }
    const w = sample.current;
    w.frames += 1;
    w.time += delta;
    if (w.time >= FPS_WINDOW_S) {
      onWindow(w.frames / w.time);
      sample.current = { frames: 0, time: 0 };
    }
  });
  return null;
}

/** Mouse parallax + aspect-aware framing so the rings always fit. */
function CameraRig() {
  useFrame((state, delta) => {
    const { camera, pointer, size } = state;
    const aspect = size.width / size.height;
    const fitHeight = 4.25 / HALF_FOV_TAN;
    const fitWidth = 3.6 / (HALF_FOV_TAN * aspect);
    // Cinema mode (no panels): the core comes a little closer.
    const distance = Math.max(fitHeight, fitWidth) * (useHud.getState().cinema ? 0.84 : 1);
    const k = 1 - Math.exp(-delta * 2.2);
    camera.position.x += (pointer.x * 0.8 - camera.position.x) * k;
    camera.position.y += (0.55 + pointer.y * 0.45 - camera.position.y) * k;
    camera.position.z += (distance - camera.position.z) * k;
    camera.lookAt(0, 0, 0);
  });
  return null;
}

function Hologram({ visible, particles, theme, style }: { visible: boolean; particles: number; theme: ThemeId; style: SceneStyle }) {
  const group = useRef<Group>(null);
  const progress = useRef(0);
  // A new protocol re-materialises the hologram (the same spin-in as the boot) while its parts swap.
  const shown = useRef(theme);
  if (shown.current !== theme) {
    shown.current = theme;
    progress.current = 0.25;
  }

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
      <ReactorCore style={style} />
      <CoreActivity />
      <EarthGlobe />
      <HudRings style={style.rings} />
      <Spectrum style={style.spectrum} />
      <Orbits count={style.orbits} />
      <ParticleDisk count={Math.round(particles * style.disk.count)} tilt={style.disk.tilt} spin={style.disk.spin} />
    </group>
  );
}

/**
 * Memoised: the HUD re-renders on every transcript chunk, and re-rendering the whole 3D tree that
 * often cost frames, which made the automatic quality step down (a blank frame) mid-conversation.
 */
export const Scene = memo(function Scene({ visible }: { visible: boolean }) {
  const aberration = useMemo(() => new Vector2(0.0007, 0.0005), []);
  // LAN-26: a phone starts on the lighter scene; the quality in Ajustes can change it.
  const { lite } = useMemo(currentSceneProfile, []);
  const { quality, theme } = usePrefs();
  const style = themeInfo(theme).scene;
  const [auto, setAuto] = useState<AutoState>(() => startAuto(lite));
  const level = quality === 'auto' ? auto.level : fixedLevel(quality, lite);
  const profile = QUALITY_PROFILES[level];
  const sparkles = Math.round(profile.sparkles * style.sparkle.count);

  useEffect(() => {
    if (quality === 'auto') setAuto(startAuto(lite));
  }, [quality, lite]);

  // The automatic quality says when it changes, so a one-off change of look has an explanation.
  const announced = useRef(level);
  useEffect(() => {
    if (quality !== 'auto' || announced.current === level) return;
    const fps = useHud.getState().sceneQuality.fps;
    useHud.getState().addLog('info', `Qualidade da cena: ${LEVEL_LABELS[level]}${fps ? ` (${fps} fps)` : ''}`);
    announced.current = level;
  }, [level, quality]);

  const onWindow = (fps: number) => {
    useHud.getState().setSceneQuality(level, Math.round(fps));
    if (quality === 'auto') setAuto((state) => autoStep(state, fps));
  };

  return (
    <Canvas
      className="scene"
      dpr={profile.dpr}
      gl={{ antialias: false, powerPreference: lite ? 'default' : 'high-performance', alpha: false, stencil: false }}
      camera={{ position: [0, 0.6, 14], fov: FOV, near: 0.1, far: 120 }}
    >
      <color attach="background" args={['#010409']} />
      <fog attach="fog" args={['#010409', 12, 34]} />
      <SceneDriver />
      <FrameMonitor level={level} onWindow={onWindow} />
      <CameraRig />
      <Hologram visible={visible} particles={profile.particles} theme={theme} style={style} />
      <GridFloor style={style.floor} />
      {profile.beam && style.beam && <ProjectorBeam visible={visible} />}
      {sparkles > 0 && (
        <Sparkles count={sparkles} scale={SPARKLE_SCALE} size={2.2} speed={0.25} opacity={0.45} color={style.sparkle.color} noise={0.6} />
      )}
      {profile.postprocessing === 'full' ? (
        <EffectComposer multisampling={0} enableNormalPass={false}>
          <Bloom mipmapBlur intensity={1.05 * style.bloom} luminanceThreshold={0.08} luminanceSmoothing={0.35} radius={0.78} />
          <ChromaticAberration offset={aberration} radialModulation modulationOffset={0.35} blendFunction={BlendFunction.NORMAL} />
          <Noise premultiply blendFunction={BlendFunction.SCREEN} opacity={0.05} />
          <Vignette offset={0.22} darkness={0.82} />
        </EffectComposer>
      ) : (
        <EffectComposer multisampling={0} enableNormalPass={false} resolutionScale={profile.postprocessing === 'lite' ? 0.5 : 1}>
          <Bloom intensity={1.1 * style.bloom} luminanceThreshold={0.1} luminanceSmoothing={0.35} />
        </EffectComposer>
      )}
    </Canvas>
  );
});
