import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import { AdditiveBlending, Color, type ShaderMaterial } from 'three';
import type { SceneStyle } from '../lib/themes';
import { scene } from './sceneState';

const vertex = /* glsl */ `
  varying vec3 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const fragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uTime;
  uniform float uEnergy;
  uniform float uSweep;
  uniform float uSweepOn;
  uniform float uMinor;
  uniform float uMajor;
  varying vec3 vWorld;

  const float TAU = 6.2831853;

  float gridLine(vec2 p, float size, float width) {
    vec2 coord = p / size;
    vec2 g = abs(fract(coord - 0.5) - 0.5) / fwidth(coord);
    return 1.0 - min(min(g.x, g.y) / width, 1.0);
  }

  void main() {
    float d = length(vWorld.xz);
    float fade = smoothstep(28.0, 2.5, d);
    float minor = gridLine(vWorld.xz, uMinor, 1.0) * 0.22;
    float major = gridLine(vWorld.xz, uMajor, 1.3) * 0.55;
    float wave = mod(uTime * 4.5, 32.0);
    // The wave fades in as it leaves the pad: born at full strength it lit a disc right under the
    // core that the bloom turned into a flash every few seconds.
    float ring = smoothstep(1.4, 0.0, abs(d - wave)) * (1.0 - wave / 32.0) * smoothstep(2.0, 4.5, wave);
    float pad = smoothstep(0.08, 0.0, abs(d - 3.0)) * 0.6 + smoothstep(0.05, 0.0, abs(d - 3.6)) * 0.3;
    // Radar sweep: a beam turning around the pad that lights the grid and leaves a fading wake.
    // atan(0, 0) is undefined: one NaN pixel at the centre would be smeared black by the bloom.
    float angle = d > 0.001 ? atan(vWorld.z, vWorld.x) : 0.0;
    float behind = mod(uSweep - angle, TAU);
    float wake = smoothstep(1.3, 0.0, behind) * smoothstep(3.0, 3.8, d) * fade * uSweepOn;
    float beam = smoothstep(0.035, 0.0, behind) * smoothstep(3.0, 3.8, d) * fade * uSweepOn;
    float alpha = (minor + major) * fade + ring * 0.55 * fade + pad * (0.5 + uEnergy * 0.6);
    alpha += (minor * 2.2 + major * 1.2 + 0.035) * wake + beam * 0.5;
    gl_FragColor = vec4(uColor * alpha * (0.65 + uEnergy * 0.9), alpha);
  }
`;

/** Holographic projection table: perspective grid with an expanding scan wave and a radar sweep. */
export function GridFloor({ style }: { style: SceneStyle['floor'] }) {
  const material = useRef<ShaderMaterial>(null);
  const uniforms = useMemo(
    () => ({
      uColor: { value: new Color() },
      uTime: { value: 0 },
      uEnergy: { value: 0 },
      uSweep: { value: 0 },
      uSweepOn: { value: 1 },
      uMinor: { value: 1 },
      uMajor: { value: 5 },
    }),
    [],
  );

  useFrame((state) => {
    const m = material.current;
    if (!m) return;
    m.uniforms.uTime.value = state.clock.elapsedTime;
    m.uniforms.uEnergy.value = scene.energy;
    // Speed-scaled phase: the sweep is lazy in standby and fast while processing.
    m.uniforms.uSweep.value = scene.phase * 0.9;
    m.uniforms.uSweepOn.value = style.sweep ? 1 : 0;
    m.uniforms.uMinor.value = style.minor;
    m.uniforms.uMajor.value = style.major;
    (m.uniforms.uColor.value as Color).copy(scene.primary).multiplyScalar(0.55 * scene.glow * style.glow);
  });

  return (
    <mesh rotation-x={-Math.PI / 2} position-y={-3.5}>
      <planeGeometry args={[90, 90]} />
      <shaderMaterial
        ref={material}
        uniforms={uniforms}
        vertexShader={vertex}
        fragmentShader={fragment}
        transparent
        depthWrite={false}
        blending={AdditiveBlending}
        toneMapped={false}
      />
    </mesh>
  );
}
