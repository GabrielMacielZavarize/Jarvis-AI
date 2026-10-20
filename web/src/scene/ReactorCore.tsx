import { Billboard } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { type ComponentType, useEffect, useMemo, useRef } from 'react';
import {
  AdditiveBlending,
  Color,
  DoubleSide,
  EdgesGeometry,
  IcosahedronGeometry,
  type Group,
  type LineBasicMaterial,
  type Mesh,
  MeshBasicMaterial,
  type ShaderMaterial,
} from 'three';
import type { SceneStyle, ShellStyle } from '../lib/themes';
import { arcs, circle } from './geometry';
import { scene } from './sceneState';
import { simplexNoise3D } from './shaders/noise';

const plasmaVertex = /* glsl */ `
  uniform float uPhase;
  uniform float uEnergy;
  uniform float uSurge;
  uniform float uFreq;
  uniform float uDetail;
  uniform float uAmp;
  varying vec3 vNormalV;
  varying vec3 vViewDir;
  varying float vNoise;
  ${simplexNoise3D}
  void main() {
    vec3 n = normalize(position);
    float slow = snoise(n * uFreq + vec3(0.0, uPhase * 0.5, uPhase * 0.25));
    float fast = snoise(n * uDetail + vec3(uPhase * 1.3, 0.0, -uPhase));
    float amp = (0.05 + uEnergy * 0.34 + uSurge * 0.14) * uAmp;
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
  uniform float uBands;
  varying vec3 vNormalV;
  varying vec3 vViewDir;
  varying float vNoise;
  void main() {
    float facing = clamp(dot(normalize(vNormalV), normalize(vViewDir)), 0.0, 1.0);
    float rim = pow(1.0 - facing, 2.4);
    float bands = pow(abs(sin(vNoise * uBands - uPhase * 2.2)), 16.0);
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
  uniform float uRays;
  varying vec2 vUv;
  void main() {
    vec2 p = vUv - 0.5;
    float d = length(p) * 2.0;
    float core = smoothstep(0.32, 0.0, d);
    float glow = pow(clamp(1.0 - d, 0.0, 1.0), 2.6);
    // atan(0, 0) is undefined: the very centre gets no ray instead of a NaN pixel.
    float angle = d > 0.001 ? atan(p.y, p.x) : 0.0;
    float rays = uRays > 0.0 ? pow(abs(sin(angle * uRays + uTime * 0.7)), 24.0) * glow * (0.35 + uEnergy) : 0.0;
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

const glowMaterial = (opacity = 0.5) =>
  new MeshBasicMaterial({
    transparent: true,
    opacity,
    side: DoubleSide,
    depthWrite: false,
    blending: AdditiveBlending,
    toneMapped: false,
  });

/** J.A.R.V.I.S.: two wireframe icosahedra turning around the plasma. */
function LatticeShell() {
  const shell = useRef<Group>(null);
  const shellMat = useRef<LineBasicMaterial>(null);
  const innerShellMat = useRef<LineBasicMaterial>(null);
  const shellEdges = useMemo(() => new EdgesGeometry(new IcosahedronGeometry(1.34, 2)), []);
  const innerEdges = useMemo(() => new EdgesGeometry(new IcosahedronGeometry(0.62, 1)), []);
  useEffect(() => () => [shellEdges, innerEdges].forEach((geometry) => geometry.dispose()), [shellEdges, innerEdges]);

  useFrame((_, delta) => {
    const energy = scene.energy;
    if (shellMat.current) {
      shellMat.current.color.copy(scene.primary).multiplyScalar(0.9 * scene.glow);
      shellMat.current.opacity = (0.16 + energy * 0.35) * (1 - scene.network * 0.5);
    }
    if (innerShellMat.current) {
      innerShellMat.current.color.copy(scene.accent).multiplyScalar(scene.glow);
      innerShellMat.current.opacity = 0.18 + energy * 0.4;
    }
    if (shell.current) {
      shell.current.rotation.y += delta * 0.18 * scene.speed;
      shell.current.rotation.x += delta * 0.07 * scene.speed;
    }
  });

  return (
    <group ref={shell}>
      <lineSegments geometry={shellEdges}>
        <lineBasicMaterial ref={shellMat} transparent depthWrite={false} blending={AdditiveBlending} toneMapped={false} />
      </lineSegments>
      <lineSegments geometry={innerEdges} rotation={[0.6, 0.3, 0]}>
        <lineBasicMaterial ref={innerShellMat} transparent depthWrite={false} blending={AdditiveBlending} toneMapped={false} />
      </lineSegments>
    </group>
  );
}

const CELLS = Array.from({ length: 10 }, (_, index) => [index * 36 + 4, 28] as [number, number]);
const COILS = Array.from({ length: 10 }, (_, index) => [index * 36 + 32, 8] as [number, number]);

/** Mark III: the arc reactor of the chest piece, ten cells around the plasma and copper coils. */
function ReactorShell() {
  const cells = useRef<Mesh>(null);
  const coils = useRef<Mesh>(null);
  const g = useMemo(
    () => ({ cells: arcs(1.3, 0.17, CELLS), coils: arcs(1.3, 0.09, COILS), outer: circle(1.5, 0.018), inner: circle(1.08, 0.012) }),
    [],
  );
  const m = useMemo(() => ({ cells: glowMaterial(), coils: glowMaterial(), rims: glowMaterial() }), []);
  useEffect(
    () => () => {
      Object.values(g).forEach((geometry) => geometry.dispose());
      Object.values(m).forEach((material) => material.dispose());
    },
    [g, m],
  );

  useFrame((_, delta) => {
    const energy = scene.energy;
    if (cells.current) cells.current.rotation.z += delta * 0.22 * scene.speed;
    if (coils.current) coils.current.rotation.z = cells.current?.rotation.z ?? 0;
    m.cells.color.copy(scene.primary).multiplyScalar(scene.glow * (0.7 + energy * 0.9));
    m.cells.opacity = (0.28 + energy * 0.4) * (1 - scene.network * 0.5);
    m.coils.color.copy(scene.accent).multiplyScalar(scene.glow * 1.2);
    m.coils.opacity = 0.45 + energy * 0.4;
    m.rims.color.copy(scene.primary).multiplyScalar(scene.glow);
    m.rims.opacity = 0.35 + scene.surge * 0.3;
  });

  return (
    <group position-z={0.02}>
      <mesh ref={cells} geometry={g.cells} material={m.cells} />
      <mesh ref={coils} geometry={g.coils} material={m.coils} />
      <mesh geometry={g.outer} material={m.rims} />
      <mesh geometry={g.inner} material={m.rims} />
    </group>
  );
}

const GYRO_RINGS: { radius: number; tilt: [number, number, number]; axis: 'x' | 'y' | 'z'; speed: number }[] = [
  { radius: 1.3, tilt: [Math.PI / 2, 0, 0], axis: 'z', speed: 0.5 },
  { radius: 1.36, tilt: [0.4, 0.9, 0], axis: 'x', speed: -0.35 },
  { radius: 1.42, tilt: [-0.7, -0.5, 0.3], axis: 'y', speed: 0.28 },
];

/** F.R.I.D.A.Y.: three thin gyroscope rings gliding around a liquid plasma. */
function GyroShell() {
  const rings = useRef<(Group | null)[]>([]);
  const material = useMemo(() => glowMaterial(), []);
  useEffect(() => () => material.dispose(), [material]);

  useFrame((_, delta) => {
    GYRO_RINGS.forEach((ring, index) => {
      const group = rings.current[index];
      if (group) group.rotation[ring.axis] += delta * ring.speed * scene.speed;
    });
    material.color.copy(scene.primary).multiplyScalar(scene.glow * (1 + scene.energy * 0.8));
    material.opacity = (0.4 + scene.energy * 0.4) * (1 - scene.network * 0.5);
  });

  return (
    <group>
      {GYRO_RINGS.map((ring, index) => (
        <group key={ring.radius} rotation={ring.tilt}>
          <group ref={(node) => void (rings.current[index] = node)}>
            <mesh material={material}>
              <torusGeometry args={[ring.radius, 0.007, 6, 200]} />
            </mesh>
            <mesh material={material} position={[ring.radius, 0, 0]}>
              <sphereGeometry args={[0.035, 12, 12]} />
            </mesh>
          </group>
        </group>
      ))}
    </group>
  );
}

/** Stealth: one faint ring, nothing that catches the eye. */
function VeilShell() {
  const g = useMemo(() => circle(1.3, 0.006, 200), []);
  const material = useMemo(() => glowMaterial(0.25), []);
  useEffect(
    () => () => {
      g.dispose();
      material.dispose();
    },
    [g, material],
  );
  useFrame(() => {
    material.color.copy(scene.primary).multiplyScalar(scene.glow);
    material.opacity = 0.2 + scene.energy * 0.3;
  });
  return <mesh geometry={g} material={material} />;
}

const SHELLS: Record<ShellStyle, ComponentType> = {
  lattice: LatticeShell,
  reactor: ReactorShell,
  gyro: GyroShell,
  veil: VeilShell,
};

export function ReactorCore({ style }: { style: SceneStyle }) {
  const group = useRef<Group>(null);
  const plasma = useRef<ShaderMaterial>(null);
  const halo = useRef<ShaderMaterial>(null);
  const heart = useRef<Mesh>(null);
  const heartMat = useRef<ShaderMaterial>(null);
  const Shell = SHELLS[style.shell];

  const plasmaUniforms = useMemo(
    () => ({
      uPhase: { value: 0 },
      uEnergy: { value: 0 },
      uSurge: { value: 0 },
      uFreq: { value: 1.6 },
      uDetail: { value: 4.2 },
      uAmp: { value: 1 },
      uBands: { value: 18 },
      uColor: { value: new Color() },
      uColor2: { value: new Color() },
    }),
    [],
  );
  const heartUniforms = useMemo(
    () => ({ uColor: { value: new Color() }, uEnergy: { value: 0 }, uTime: { value: 0 }, uRays: { value: 6 } }),
    [],
  );
  const haloUniforms = useMemo(() => ({ uColor: { value: new Color() }, uStrength: { value: 0.6 } }), []);

  useEffect(() => {
    plasmaUniforms.uFreq.value = style.plasma.freq;
    plasmaUniforms.uDetail.value = style.plasma.detail;
    plasmaUniforms.uAmp.value = style.plasma.amp;
    plasmaUniforms.uBands.value = style.plasma.bands;
    heartUniforms.uRays.value = style.plasma.rays;
  }, [style, plasmaUniforms, heartUniforms]);

  useFrame((state) => {
    const energy = scene.energy;
    const t = state.clock.elapsedTime;

    if (plasma.current) {
      const u = plasma.current.uniforms;
      u.uPhase.value = scene.phase;
      u.uEnergy.value = energy;
      u.uSurge.value = scene.surge;
      (u.uColor.value as Color).copy(scene.primary).multiplyScalar(scene.glow * (1 - scene.network * 0.65));
      (u.uColor2.value as Color).copy(scene.secondary).multiplyScalar(1 - scene.network * 0.75);
    }
    if (halo.current) {
      (halo.current.uniforms.uColor.value as Color).copy(scene.primary);
      halo.current.uniforms.uStrength.value = (0.32 * scene.glow + energy * 0.55 + scene.surge * 0.3) * (1 - scene.network * 0.4);
    }
    if (heart.current && heartMat.current) {
      const pulse = (1 + Math.sin(t * 2.4) * 0.04 + energy * 0.5) * (1 - scene.network * 0.45);
      heart.current.scale.setScalar(pulse);
      const u = heartMat.current.uniforms;
      (u.uColor.value as Color).copy(scene.primary).multiplyScalar(scene.glow);
      u.uEnergy.value = energy;
      u.uTime.value = t;
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

        <Shell />
      </group>
    </group>
  );
}
