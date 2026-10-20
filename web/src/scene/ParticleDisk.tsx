import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, BufferAttribute, BufferGeometry, Color, type ShaderMaterial } from 'three';
import { scene } from './sceneState';

const vertex = /* glsl */ `
  attribute float aRadius;
  attribute float aAngle;
  attribute float aSpeed;
  attribute float aSeed;
  uniform float uPhase;
  uniform float uSpin;
  uniform float uTime;
  uniform float uEnergy;
  uniform float uPixelRatio;
  varying float vAlpha;
  void main() {
    float angle = aAngle + uPhase * uSpin * aSpeed / aRadius;
    float r = aRadius + sin(uTime * 1.7 + aSeed * 40.0) * 0.03 + uEnergy * 0.35 * aSeed;
    vec3 pos = vec3(cos(angle) * r, sin(angle) * r, (aSeed - 0.5) * 0.18);
    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mv;
    float twinkle = 0.55 + 0.45 * sin(uTime * (1.5 + aSeed * 3.0) + aSeed * 90.0);
    gl_PointSize = (1.4 + aSeed * 2.2) * uPixelRatio * (6.0 / -mv.z) * (1.0 + uEnergy * 0.8);
    vAlpha = twinkle * smoothstep(3.6, 2.2, aRadius) * smoothstep(1.4, 1.9, aRadius);
  }
`;

const fragment = /* glsl */ `
  uniform vec3 uColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float a = smoothstep(0.5, 0.0, d) * vAlpha;
    gl_FragColor = vec4(uColor * a, a);
  }
`;

/** Tilted accretion disk of particles orbiting the core with differential speed (`spin` < 0 turns it the other way). */
export function ParticleDisk({
  count = 2600,
  tilt = [1.22, 0.18, 0],
  spin = 1,
}: {
  count?: number;
  tilt?: [number, number, number];
  spin?: number;
}) {
  const material = useRef<ShaderMaterial>(null);
  const geometry = useMemo(() => {
    const geo = new BufferGeometry();
    const radius = new Float32Array(count);
    const angle = new Float32Array(count);
    const speed = new Float32Array(count);
    const seed = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      radius[i] = 1.55 + Math.pow(Math.random(), 1.6) * 2.0;
      angle[i] = Math.random() * Math.PI * 2;
      speed[i] = 0.5 + Math.random() * 0.9;
      seed[i] = Math.random();
    }
    geo.setAttribute('position', new BufferAttribute(new Float32Array(count * 3), 3));
    geo.setAttribute('aRadius', new BufferAttribute(radius, 1));
    geo.setAttribute('aAngle', new BufferAttribute(angle, 1));
    geo.setAttribute('aSpeed', new BufferAttribute(speed, 1));
    geo.setAttribute('aSeed', new BufferAttribute(seed, 1));
    return geo;
  }, [count]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  const uniforms = useMemo(
    () => ({
      uPhase: { value: 0 },
      uSpin: { value: 1 },
      uTime: { value: 0 },
      uEnergy: { value: 0 },
      uPixelRatio: { value: 1 },
      uColor: { value: new Color() },
    }),
    [],
  );

  useFrame((state) => {
    const m = material.current;
    if (!m) return;
    m.uniforms.uPhase.value = scene.phase;
    m.uniforms.uSpin.value = spin;
    m.uniforms.uTime.value = state.clock.elapsedTime;
    m.uniforms.uEnergy.value = scene.energy;
    m.uniforms.uPixelRatio.value = state.gl.getPixelRatio();
    (m.uniforms.uColor.value as Color).copy(scene.primary).multiplyScalar(1.2 * scene.glow);
  });

  return (
    <points geometry={geometry} rotation={tilt} frustumCulled={false}>
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
    </points>
  );
}
