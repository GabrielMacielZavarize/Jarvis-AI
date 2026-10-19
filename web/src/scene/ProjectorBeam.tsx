import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import { AdditiveBlending, Color, DoubleSide, type ShaderMaterial } from 'three';
import { scene } from './sceneState';

/** Floor level of the projection table (GridFloor). */
const FLOOR = -3.5;
const HEIGHT = 4.2;

const vertex = /* glsl */ `
  varying vec2 vUv;
  varying vec3 vNormalV;
  varying vec3 vViewDir;
  void main() {
    vUv = uv;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vViewDir = normalize(-mv.xyz);
    vNormalV = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * mv;
  }
`;

const fragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uTime;
  uniform float uIntensity;
  varying vec2 vUv;
  varying vec3 vNormalV;
  varying vec3 vViewDir;
  void main() {
    float h = vUv.y;
    float rim = pow(1.0 - abs(dot(normalize(vNormalV), normalize(vViewDir))), 1.6);
    float fall = pow(1.0 - h, 2.4);
    float bands = 0.65 + 0.35 * smoothstep(0.55, 1.0, sin(h * 42.0 - uTime * 3.2));
    float streaks = 0.7 + 0.3 * sin(vUv.x * 6.2831853 * 56.0);
    float alpha = fall * (0.2 + rim * 0.8) * bands * streaks * uIntensity;
    gl_FragColor = vec4(uColor * alpha, alpha);
  }
`;

/** Light rising from the projection pad on the floor up to the hologram, with upward scan bands. */
export function ProjectorBeam({ visible }: { visible: boolean }) {
  const material = useRef<ShaderMaterial>(null);
  const reveal = useRef(0);
  const uniforms = useMemo(
    () => ({ uColor: { value: new Color() }, uTime: { value: 0 }, uIntensity: { value: 0 } }),
    [],
  );

  useFrame((state, delta) => {
    const m = material.current;
    if (!m) return;
    reveal.current = Math.min(1, reveal.current + (visible ? delta / 1.4 : 0));
    m.uniforms.uTime.value = state.clock.elapsedTime;
    m.uniforms.uIntensity.value = reveal.current * (0.22 * scene.glow + scene.energy * 0.35 + scene.surge * 0.15);
    (m.uniforms.uColor.value as Color).copy(scene.primary);
  });

  return (
    <mesh position-y={FLOOR + HEIGHT / 2} renderOrder={-1}>
      <cylinderGeometry args={[2.5, 3.0, HEIGHT, 96, 1, true]} />
      <shaderMaterial
        ref={material}
        uniforms={uniforms}
        vertexShader={vertex}
        fragmentShader={fragment}
        transparent
        side={DoubleSide}
        depthWrite={false}
        blending={AdditiveBlending}
        toneMapped={false}
      />
    </mesh>
  );
}
