import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import { AdditiveBlending, Color, type ShaderMaterial } from 'three';
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
  varying vec3 vWorld;

  float gridLine(vec2 p, float size, float width) {
    vec2 coord = p / size;
    vec2 g = abs(fract(coord - 0.5) - 0.5) / fwidth(coord);
    return 1.0 - min(min(g.x, g.y) / width, 1.0);
  }

  void main() {
    float d = length(vWorld.xz);
    float fade = smoothstep(28.0, 2.5, d);
    float minor = gridLine(vWorld.xz, 1.0, 1.0) * 0.22;
    float major = gridLine(vWorld.xz, 5.0, 1.3) * 0.55;
    float wave = mod(uTime * 4.5, 32.0);
    float ring = smoothstep(1.4, 0.0, abs(d - wave)) * (1.0 - wave / 32.0);
    float pad = smoothstep(0.08, 0.0, abs(d - 3.0)) * 0.6 + smoothstep(0.05, 0.0, abs(d - 3.6)) * 0.3;
    float alpha = (minor + major) * fade + ring * 0.55 * fade + pad * (0.5 + uEnergy * 0.6);
    gl_FragColor = vec4(uColor * alpha * (0.65 + uEnergy * 0.9), alpha);
  }
`;

/** Holographic projection table: perspective grid with an expanding scan wave. */
export function GridFloor() {
  const material = useRef<ShaderMaterial>(null);
  const uniforms = useMemo(
    () => ({ uColor: { value: new Color() }, uTime: { value: 0 }, uEnergy: { value: 0 } }),
    [],
  );

  useFrame((state) => {
    const m = material.current;
    if (!m) return;
    m.uniforms.uTime.value = state.clock.elapsedTime;
    m.uniforms.uEnergy.value = scene.energy;
    (m.uniforms.uColor.value as Color).copy(scene.primary).multiplyScalar(0.55 * scene.glow);
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
