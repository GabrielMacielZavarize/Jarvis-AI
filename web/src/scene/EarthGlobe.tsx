import { Html } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  CatmullRomCurve3,
  Color,
  type Group,
  type Mesh,
  type MeshBasicMaterial,
  type ShaderMaterial,
  TubeGeometry,
  Vector3,
} from 'three';
import { useHud } from '../lib/hudStore';
import { landDots } from '../lib/landDots';
import type { GeoPoint, NetLink } from '../lib/types';
import { scene } from './sceneState';

/** Globe radius: just outside the plasma core, inside the wireframe shell. */
const R = 1.16;
const DEG = Math.PI / 180;
const Z_AXIS = new Vector3(0, 0, 1);
/** How much the globe grows while it draws a search. */
const FOCUS_ZOOM = 0.55;
const worldEnd = new Vector3();
const worldCentre = new Vector3();
const toCamera = new Vector3();

/** lat/lon (degrees) → point on a sphere where (0, 0) faces the camera (+Z). */
function toVector(lat: number, lon: number, radius = 1) {
  const phi = lat * DEG;
  const lambda = lon * DEG;
  return new Vector3(
    radius * Math.cos(phi) * Math.sin(lambda),
    radius * Math.sin(phi),
    radius * Math.cos(phi) * Math.cos(lambda),
  );
}

const dotVertex = /* glsl */ `
  uniform float uOpacity;
  uniform float uPixelRatio;
  uniform float uSize;
  varying float vAlpha;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vec3 normal = normalize(normalMatrix * normalize(position));
    float facing = dot(normal, normalize(-mv.xyz));
    vAlpha = smoothstep(-0.05, 0.4, facing) * uOpacity;
    gl_PointSize = uSize * uPixelRatio * (9.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const dotFragment = /* glsl */ `
  uniform vec3 uColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float a = smoothstep(0.5, 0.1, d) * vAlpha;
    gl_FragColor = vec4(uColor * a, a);
  }
`;

const arcVertex = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const arcFragment = /* glsl */ `
  uniform vec3 uColor;
  uniform float uHead;
  uniform float uPulse;
  uniform float uFade;
  varying vec2 vUv;
  void main() {
    float x = vUv.x;
    if (x > uHead) discard;
    float drawing = step(uHead, 0.999);
    float head = smoothstep(uHead - 0.22, uHead, x) * drawing;
    float pulse = uPulse < 0.0 ? 0.0 : smoothstep(0.07, 0.0, abs(x - uPulse));
    float alpha = (0.42 + head * 1.4 + pulse * 1.6) * uFade;
    gl_FragColor = vec4(uColor * alpha * 1.5, alpha);
  }
`;

// Fixed colours so connections stay readable whatever the mode tint is.
const KIND_COLORS: Record<NetLink['kind'], Color> = {
  request: new Color('#5ff4ff'),
  link: new Color('#5ff4ff'),
  source: new Color('#ffc15e'),
  model: new Color('#f2fdff'),
};

function linkColor(kind: NetLink['kind'], target: Color) {
  return target.copy(KIND_COLORS[kind]);
}

/** Great-circle arc from home to a host, drawn progressively then pulsing data packets. */
function Arc({ link, home }: { link: NetLink; home: GeoPoint }) {
  const material = useRef<ShaderMaterial>(null);
  const tag = useRef<HTMLDivElement>(null);
  const marker = useRef<Mesh>(null);
  const markerMat = useRef<MeshBasicMaterial>(null);
  const ring = useRef<Mesh>(null);
  const ringMat = useRef<MeshBasicMaterial>(null);

  const { geometry, end, normal } = useMemo(() => {
    const a = toVector(home.lat, home.lon);
    const b = toVector(link.lat, link.lon);
    const angle = a.angleTo(b);
    const altitude = 0.14 + 0.62 * (angle / Math.PI);
    const points: Vector3[] = [];
    for (let i = 0; i <= 48; i++) {
      const t = i / 48;
      const direction = a.clone().lerp(b, t).normalize();
      points.push(direction.multiplyScalar(R * (1 + altitude * Math.sin(Math.PI * t))));
    }
    return {
      geometry: new TubeGeometry(new CatmullRomCurve3(points), 72, 0.011, 6, false),
      end: b.clone().multiplyScalar(R),
      normal: b.clone(),
    };
  }, [home.lat, home.lon, link.lat, link.lon]);
  const uniforms = useMemo(
    () => ({ uColor: { value: new Color() }, uHead: { value: 0 }, uPulse: { value: -1 }, uFade: { value: 1 } }),
    [],
  );

  useEffect(() => () => geometry.dispose(), [geometry]);
  useLayoutEffect(() => {
    ring.current?.quaternion.setFromUnitVectors(Z_AXIS, normal);
  }, [normal]);

  useFrame((state) => {
    const age = (Date.now() - link.createdAt) / 1000;
    const life = link.ttl / 1000;
    const visible = age >= 0;
    const fade = !visible ? 0 : age > life ? Math.max(0, 1 - (age - life) / 1.2) : Math.min(1, age * 4);
    const head = Math.max(0, Math.min(1, age / 0.85));
    const pulse = age > 0.85 ? ((age - 0.85) / 1.25) % 1 : -1;

    const m = material.current;
    if (m) {
      linkColor(link.kind, m.uniforms.uColor.value as Color);
      m.uniforms.uHead.value = head;
      m.uniforms.uPulse.value = pulse;
      m.uniforms.uFade.value = fade;
    }
    const arrived = head >= 1 ? fade : 0;
    if (marker.current && markerMat.current) {
      marker.current.scale.setScalar(arrived);
      linkColor(link.kind, markerMat.current.color).multiplyScalar(2.2);
    }
    // Name of the place and the service at the end of the arc, hidden behind the globe.
    if (tag.current && marker.current) {
      marker.current.getWorldPosition(worldEnd);
      marker.current.parent?.getWorldPosition(worldCentre);
      const facing = toCamera.copy(state.camera.position).sub(worldEnd).normalize().dot(worldEnd.sub(worldCentre).normalize());
      const shown = link.kind !== 'model' && arrived > 0.05 && facing > 0.2;
      tag.current.style.opacity = shown ? String(Math.min(1, arrived) * Math.min(1, (facing - 0.2) * 4)) : '0';
    }
    if (ring.current && ringMat.current) {
      const wave = (age * 1.1) % 1;
      ring.current.scale.setScalar(arrived > 0 ? 1 + wave * 3 : 0.0001);
      ringMat.current.opacity = arrived * (1 - wave) * 0.9;
      linkColor(link.kind, ringMat.current.color).multiplyScalar(1.6);
    }
  });

  return (
    <group>
      <mesh geometry={geometry} renderOrder={3}>
        <shaderMaterial
          ref={material}
          uniforms={uniforms}
          vertexShader={arcVertex}
          fragmentShader={arcFragment}
          transparent
          depthWrite={false}
          blending={AdditiveBlending}
          toneMapped={false}
        />
      </mesh>
      <mesh ref={marker} position={end} scale={0}>
        <sphereGeometry args={[0.02, 10, 10]} />
        <meshBasicMaterial ref={markerMat} toneMapped={false} />
      </mesh>
      <mesh ref={ring} position={end}>
        <ringGeometry args={[0.018, 0.026, 24]} />
        <meshBasicMaterial ref={ringMat} transparent depthWrite={false} blending={AdditiveBlending} toneMapped={false} />
      </mesh>
      <Html position={end} zIndexRange={[2, 0]} style={{ pointerEvents: 'none' }}>
        <div ref={tag} className={`globe-tag globe-tag--${link.kind}`} style={{ opacity: 0 }}>
          <b>{link.label}</b>
          <span>{link.host}</span>
        </div>
      </Html>
    </group>
  );
}

function HomeBeacon({ home }: { home: GeoPoint }) {
  const ring = useRef<Mesh>(null);
  const ringMat = useRef<MeshBasicMaterial>(null);
  const dotMat = useRef<MeshBasicMaterial>(null);
  const position = useMemo(() => toVector(home.lat, home.lon, R), [home.lat, home.lon]);

  useLayoutEffect(() => {
    ring.current?.quaternion.setFromUnitVectors(Z_AXIS, position.clone().normalize());
  }, [position]);

  useFrame((state) => {
    const wave = (state.clock.elapsedTime * 0.7) % 1;
    const visibility = 0.25 + scene.network * 0.75;
    if (ring.current && ringMat.current) {
      ring.current.scale.setScalar(1 + wave * 2.6);
      ringMat.current.opacity = (1 - wave) * visibility;
      ringMat.current.color.copy(scene.accent).multiplyScalar(1.8);
    }
    if (dotMat.current) dotMat.current.color.copy(scene.accent).multiplyScalar(1.5 + scene.network * 1.5);
  });

  return (
    <group>
      <mesh position={position}>
        <sphereGeometry args={[0.024, 12, 12]} />
        <meshBasicMaterial ref={dotMat} toneMapped={false} />
      </mesh>
      <mesh ref={ring} position={position}>
        <ringGeometry args={[0.02, 0.028, 28]} />
        <meshBasicMaterial ref={ringMat} transparent depthWrite={false} blending={AdditiveBlending} toneMapped={false} />
      </mesh>
    </group>
  );
}

/**
 * Dotted holographic Earth inside the reactor. While Jarvis thinks or calls the
 * web, it turns to face the user's city and draws the connections it is making.
 */
export function EarthGlobe() {
  const group = useRef<Group>(null);
  const material = useRef<ShaderMaterial>(null);
  const ocean = useRef<MeshBasicMaterial>(null);
  const links = useHud((s) => s.links);
  const home = useHud((s) => s.home);
  const pruneLinks = useHud((s) => s.pruneLinks);

  const geometry = useMemo(() => {
    const dots = landDots(1.7);
    const positions = new Float32Array((dots.length / 2) * 3);
    for (let i = 0; i < dots.length; i += 2) {
      const lon = dots[i];
      const lat = dots[i + 1];
      const j = (i / 2) * 3;
      positions[j] = R * Math.cos(lat) * Math.sin(lon);
      positions[j + 1] = R * Math.sin(lat);
      positions[j + 2] = R * Math.cos(lat) * Math.cos(lon);
    }
    const geo = new BufferGeometry();
    geo.setAttribute('position', new BufferAttribute(positions, 3));
    return geo;
  }, []);
  const uniforms = useMemo(
    () => ({ uColor: { value: new Color() }, uOpacity: { value: 0.2 }, uPixelRatio: { value: 1 }, uSize: { value: 2.2 } }),
    [],
  );

  useEffect(() => {
    const id = window.setInterval(pruneLinks, 1000);
    return () => window.clearInterval(id);
  }, [pruneLinks]);

  const focus = useMemo(() => new Vector3(), []);

  useFrame((state, delta) => {
    const now = Date.now();
    const activeLinks = useHud.getState().links.filter((link) => now - link.createdAt < link.ttl);
    const active = activeLinks.length > 0;
    const target = active || scene.mode === 'thinking' ? 1 : 0;
    scene.network += (target - scene.network) * (1 - Math.exp(-delta * (target ? 4 : 1.5)));
    // Only real lookups (search, weather, news) take the stage; the model round-trip does not.
    const lookup = activeLinks.some((link) => link.kind !== 'model') ? 1 : 0;
    scene.globeFocus += (lookup - scene.globeFocus) * (1 - Math.exp(-delta * (lookup ? 2.5 : 1.2)));

    const g = group.current;
    if (g) {
      g.scale.setScalar(1 + scene.globeFocus * FOCUS_ZOOM);
      // Idle: slow spin. Active: face the middle of home + destinations so the arcs cross the disc.
      focus.copy(toVector(home.lat, home.lon)).multiplyScalar(1.5);
      for (const link of activeLinks) focus.add(toVector(link.lat, link.lon));
      focus.normalize();
      const homeYaw = -Math.atan2(focus.x, focus.z);
      const homePitch = Math.asin(Math.max(-1, Math.min(1, focus.y))) * 0.85;
      const k = 1 - Math.exp(-delta * 2.2 * scene.network);
      g.rotation.y += delta * 0.07 * (1 - scene.network);
      const diff = Math.atan2(Math.sin(homeYaw - g.rotation.y), Math.cos(homeYaw - g.rotation.y));
      g.rotation.y += diff * k;
      const pitchTarget = scene.network > 0.05 ? homePitch : 0.32;
      g.rotation.x += (pitchTarget - g.rotation.x) * (1 - Math.exp(-delta * 1.5));
    }

    const m = material.current;
    if (m) {
      (m.uniforms.uColor.value as Color).copy(scene.primary).multiplyScalar(1.1 * scene.glow);
      m.uniforms.uOpacity.value = 0.16 + scene.network * 0.95 + scene.energy * 0.15;
      m.uniforms.uSize.value = 2.2 + scene.network * 1.3;
      m.uniforms.uPixelRatio.value = state.gl.getPixelRatio();
    }
    // A dark ocean hides the plasma behind the continents while the globe is busy.
    if (ocean.current) ocean.current.opacity = scene.network * 0.82;
  });

  return (
    <group ref={group} rotation={[0.32, 0, 0]}>
      <mesh renderOrder={1}>
        <sphereGeometry args={[R * 0.985, 48, 48]} />
        <meshBasicMaterial ref={ocean} color="#010a12" transparent opacity={0} depthWrite={false} />
      </mesh>
      <points geometry={geometry} frustumCulled={false} renderOrder={2}>
        <shaderMaterial
          ref={material}
          uniforms={uniforms}
          vertexShader={dotVertex}
          fragmentShader={dotFragment}
          transparent
          depthWrite={false}
          blending={AdditiveBlending}
          toneMapped={false}
        />
      </points>
      <HomeBeacon home={home} />
      {links.map((link) => (
        <Arc key={link.id} link={link} home={home} />
      ))}
    </group>
  );
}
