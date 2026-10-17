import { Billboard } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import {
  AdditiveBlending,
  Color,
  EdgesGeometry,
  IcosahedronGeometry,
  type Group,
  type LineBasicMaterial,
  type Mesh,
  type ShaderMaterial,
} from 'three';
import { scene } from './sceneState';
import { simplexNoise3D } from './shaders/noise';

const plasmaVertex = /* glsl */ `
  uniform float uPhase;
  uniform float uEnergy;
  uniform float uSurge;
  varying vec3 vNormalV;
  varying vec3 vViewDir;
  varying float vNoise;
  ${simplexNoise3D}
  void main() {
    vec3 n = normalize(position);
    float slow = snoise(n * 1.6 + vec3(0.0, uPhase * 0.5, uPhase * 0.25));
    float fast = snoise(n * 4.2 + vec3(uPhase * 1.3, 0.0, -uPhase));
    float amp = 0.05 + uEnergy * 0.34 + uSurge * 0.14;
    float disp = slow * amp + fast * (0.015 + uEnergy * 0.1);
    vNoise = slow * 0.5 + 0.5;
    vec4 mv = modelViewMatrix * vec4(position + n * disp, 1.0);
    vViewDir = normalize(-mv.xyz);
    vNormalV = normalize(normalMatrix * n);
    gl_Position = projectionMatrix * mv;
  }
`;

const plasmaFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform vec3 uColor2;
  uniform float uEnergy;
  uniform float uPhase;
  varying vec3 vNormalV;
  varying vec3 vViewDir;
  varying float vNoise;
  void main() {
    float facing = clamp(dot(normalize(vNormalV), normalize(vViewDir)), 0.0, 1.0);
    float rim = pow(1.0 - facing, 2.4);
    float bands = pow(abs(sin(vNoise * 18.0 - uPhase * 2.2)), 16.0);
    vec3 col = uColor2 * 0.22;
    col += uColor * rim * (1.3 + uEnergy * 1.15);
    col += uColor * bands * (0.22 + uEnergy * 0.9) * (0.35 + rim);
    col += mix(uColor2, uColor, vNoise) * pow(facing, 4.0) * (0.16 + uEnergy * 0.9);
    float alpha = clamp(0.1 + rim * 0.95 + bands * 0.3, 0.0, 1.0);
    gl_FragColor = vec4(col, alpha);
  }
`;

const heartFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uEnergy;
  uniform float uTime;
  varying vec2 vUv;
  void main() {
    vec2 p = vUv - 0.5;
    float d = length(p) * 2.0;
    float core = smoothstep(0.32, 0.0, d);
    float glow = pow(clamp(1.0 - d, 0.0, 1.0), 2.6);
    float angle = atan(p.y, p.x);
    float rays = pow(abs(sin(angle * 6.0 + uTime * 0.7)), 24.0) * glow * (0.35 + uEnergy);
    vec3 col = mix(uColor, vec3(1.0), core) * (core * 2.6 + glow * 1.3 + rays * 1.5) * (1.0 + uEnergy * 1.6);
    gl_FragColor = vec4(col, clamp(core + glow + rays, 0.0, 1.0));
  }
`;

const haloVertex = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const haloFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uStrength;
  varying vec2 vUv;
  void main() {
    float d = length(vUv - 0.5) * 2.0;
    float glow = pow(clamp(1.0 - d, 0.0, 1.0), 3.2);
    gl_FragColor = vec4(uColor * glow * uStrength, glow);
  }
`;

export function ReactorCore() {
  const group = useRef<Group>(null);
  const shell = useRef<Group>(null);
  const plasma = useRef<ShaderMaterial>(null);
  const halo = useRef<ShaderMaterial>(null);
  const heart = useRef<Mesh>(null);
  const heartMat = useRef<ShaderMaterial>(null);
  const shellMat = useRef<LineBasicMaterial>(null);
  const innerShellMat = useRef<LineBasicMaterial>(null);

  const plasmaUniforms = useMemo(
    () => ({
      uPhase: { value: 0 },
      uEnergy: { value: 0 },
      uSurge: { value: 0 },
      uColor: { value: new Color() },
      uColor2: { value: new Color() },
    }),
    [],
  );
  const heartUniforms = useMemo(
    () => ({ uColor: { value: new Color() }, uEnergy: { value: 0 }, uTime: { value: 0 } }),
    [],
  );
  const haloUniforms = useMemo(() => ({ uColor: { value: new Color() }, uStrength: { value: 0.6 } }), []);
  const shellEdges = useMemo(() => new EdgesGeometry(new IcosahedronGeometry(1.34, 2)), []);
  const innerEdges = useMemo(() => new EdgesGeometry(new IcosahedronGeometry(0.62, 1)), []);

  useFrame((state, delta) => {
    const energy = scene.energy;
    const t = state.clock.elapsedTime;

    if (plasma.current) {
      const u = plasma.current.uniforms;
      u.uPhase.value = scene.phase;
      u.uEnergy.value = energy;
      u.uSurge.value = scene.surge;
      (u.uColor.value as Color).copy(scene.primary).multiplyScalar(scene.glow);
      (u.uColor2.value as Color).copy(scene.secondary);
    }
    if (halo.current) {
      (halo.current.uniforms.uColor.value as Color).copy(scene.primary);
      halo.current.uniforms.uStrength.value = 0.32 * scene.glow + energy * 0.55 + scene.surge * 0.3;
    }
    if (heart.current && heartMat.current) {
      const pulse = 1 + Math.sin(t * 2.4) * 0.04 + energy * 0.5;
      heart.current.scale.setScalar(pulse);
      const u = heartMat.current.uniforms;
      (u.uColor.value as Color).copy(scene.primary).multiplyScalar(scene.glow);
      u.uEnergy.value = energy;
      u.uTime.value = t;
    }
    if (shellMat.current) {
      shellMat.current.color.copy(scene.primary).multiplyScalar(0.9 * scene.glow);
      shellMat.current.opacity = 0.16 + energy * 0.35;
    }
    if (innerShellMat.current) {
      innerShellMat.current.color.copy(scene.accent).multiplyScalar(scene.glow);
      innerShellMat.current.opacity = 0.18 + energy * 0.4;
    }
    if (shell.current) {
      shell.current.rotation.y += delta * 0.18 * scene.speed;
      shell.current.rotation.x += delta * 0.07 * scene.speed;
    }
    if (group.current) {
      group.current.rotation.y = Math.sin(t * 0.21) * 0.25;
      group.current.rotation.x = Math.cos(t * 0.17) * 0.12;
    }
  });

  return (
    <group>
      <Billboard>
        <mesh position-z={-0.6}>
          <planeGeometry args={[7.5, 7.5]} />
          <shaderMaterial
            ref={halo}
            uniforms={haloUniforms}
            vertexShader={haloVertex}
            fragmentShader={haloFragment}
            transparent
            depthWrite={false}
            blending={AdditiveBlending}
            toneMapped={false}
          />
        </mesh>
      </Billboard>

      <group ref={group}>
        <mesh>
          <icosahedronGeometry args={[1, 48]} />
          <shaderMaterial
            ref={plasma}
            uniforms={plasmaUniforms}
            vertexShader={plasmaVertex}
            fragmentShader={plasmaFragment}
            transparent
            depthWrite={false}
            blending={AdditiveBlending}
            toneMapped={false}
          />
        </mesh>

        <Billboard>
          <mesh ref={heart}>
            <planeGeometry args={[1.5, 1.5]} />
            <shaderMaterial
              ref={heartMat}
              uniforms={heartUniforms}
              vertexShader={haloVertex}
              fragmentShader={heartFragment}
              transparent
              depthWrite={false}
              blending={AdditiveBlending}
              toneMapped={false}
            />
          </mesh>
        </Billboard>

        <group ref={shell}>
          <lineSegments geometry={shellEdges}>
            <lineBasicMaterial
              ref={shellMat}
              transparent
              depthWrite={false}
              blending={AdditiveBlending}
              toneMapped={false}
            />
          </lineSegments>
          <lineSegments geometry={innerEdges} rotation={[0.6, 0.3, 0]}>
            <lineBasicMaterial
              ref={innerShellMat}
              transparent
              depthWrite={false}
              blending={AdditiveBlending}
              toneMapped={false}
            />
          </lineSegments>
        </group>
      </group>
    </group>
  );
}

