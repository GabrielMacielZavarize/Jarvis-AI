import { useEffect, useRef } from 'react';
import { landDots } from '../../lib/landDots';

const DEG = Math.PI / 180;

interface HoloGlobeProps {
  latitude: number;
  longitude: number;
  size?: number;
}

/** Orthographic dotted globe that spins to the target coordinates and pings it. */
export function HoloGlobe({ latitude, longitude, size = 128 }: HoloGlobeProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef({ lon: (longitude + 140) * DEG, lat: 0 });

  useEffect(() => {
    const dots = landDots(2.4);
    const el = canvas.current;
    const ctx = el?.getContext('2d');
    if (!el || !ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    el.width = size * dpr;
    el.height = size * dpr;
    ctx.scale(dpr, dpr);

    const styles = getComputedStyle(el);
    const rgb = styles.getPropertyValue('--c-primary-rgb').trim().split(/\s+/).join(',') || '95,244,255';
    const accent = styles.getPropertyValue('--c-accent-rgb').trim().split(/\s+/).join(',') || '255,182,72';
    const targetLon = longitude * DEG;
    const targetLat = latitude * DEG * 0.75;
    const r = size / 2 - 6;
    const cx = size / 2;
    const cy = size / 2;
    let frame = 0;
    let settled = 0;

    const project = (lon: number, lat: number) => {
      const { lon: lon0, lat: lat0 } = view.current;
      const cosLat = Math.cos(lat);
      const dLon = lon - lon0;
      const depth = Math.sin(lat0) * Math.sin(lat) + Math.cos(lat0) * cosLat * Math.cos(dLon);
      const x = cosLat * Math.sin(dLon);
      const y = Math.cos(lat0) * Math.sin(lat) - Math.sin(lat0) * cosLat * Math.cos(dLon);
      return { x: cx + x * r, y: cy - y * r, depth };
    };

    const draw = (time: number) => {
      const v = view.current;
      let delta = targetLon - v.lon;
      delta = Math.atan2(Math.sin(delta), Math.cos(delta));
      v.lon += delta * 0.045;
      v.lat += (targetLat - v.lat) * 0.045;
      if (Math.abs(delta) < 0.002) settled += 1;

      ctx.clearRect(0, 0, size, size);
      const halo = ctx.createRadialGradient(cx, cy, r * 0.6, cx, cy, r * 1.08);
      halo.addColorStop(0, `rgba(${rgb},0.02)`);
      halo.addColorStop(1, `rgba(${rgb},0.22)`);
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = `rgba(${rgb},0.55)`;
      ctx.lineWidth = 1;
      ctx.stroke();

      // Graticule: meridians every 30°.
      ctx.strokeStyle = `rgba(${rgb},0.12)`;
      for (let m = -180; m < 180; m += 30) {
        ctx.beginPath();
        let started = false;
        for (let lat = -90; lat <= 90; lat += 6) {
          const p = project(m * DEG, lat * DEG);
          if (p.depth < 0) {
            started = false;
            continue;
          }
          if (started) ctx.lineTo(p.x, p.y);
          else ctx.moveTo(p.x, p.y);
          started = true;
        }
        ctx.stroke();
      }

      for (let i = 0; i < dots.length; i += 2) {
        const p = project(dots[i], dots[i + 1]);
        if (p.depth <= 0) continue;
        ctx.fillStyle = `rgba(${rgb},${0.25 + p.depth * 0.75})`;
        ctx.fillRect(p.x - 0.7, p.y - 0.7, 1.4, 1.4);
      }

      const target = project(targetLon, latitude * DEG);
      if (target.depth > 0) {
        const pulse = (time / 1400) % 1;
        ctx.strokeStyle = `rgba(${accent},${1 - pulse})`;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.arc(target.x, target.y, 3 + pulse * 12, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = `rgb(${accent})`;
        ctx.shadowColor = `rgb(${accent})`;
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(target.x, target.y, 2.6, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = `rgba(${accent},0.5)`;
        ctx.beginPath();
        ctx.moveTo(target.x, target.y);
        ctx.lineTo(size - 4, target.y < cy ? 10 : size - 10);
        ctx.stroke();
      }

      // Keep a gentle drift once the target is reached.
      if (settled > 90) view.current.lon += 0.0006;
      frame = requestAnimationFrame(draw);
    };

    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [latitude, longitude, size]);

  return <canvas ref={canvas} className="globe" style={{ width: size, height: size }} aria-hidden />;
}
