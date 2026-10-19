import { type KeyboardEvent, type PointerEvent, useEffect, useRef, useState } from 'react';
import { areaPath, chartPoints, linePath, nearestIndex } from '../../lib/chart';

interface SparklineProps {
  values: number[];
  domain: [number, number];
  height?: number;
  /** Tooltip text of a point ("15h · 22°"). */
  describe: (index: number) => string;
  /** What the chart shows, for screen readers. */
  label: string;
  /** Labels under the x axis, by point index. */
  ticks?: { index: number; text: string }[];
}

/**
 * One series line with its 10% wash, the last value marked, and a crosshair that snaps to the
 * nearest point under the pointer (or the arrow keys) with a tooltip.
 */
export function Sparkline({ values, domain, height = 64, describe, label, ticks = [] }: SparklineProps) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const element = box.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const points = width > 0 ? chartPoints(values, width, height, domain) : [];
  const last = points[points.length - 1];
  const active = hover !== null && hover < points.length ? hover : null;

  const onPointer = (event: PointerEvent<SVGSVGElement>) => {
    if (points.length === 0) return;
    const rect = event.currentTarget.getBoundingClientRect();
    setHover(nearestIndex(points, event.clientX - rect.left));
  };
  const onKey = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const step = event.key === 'ArrowLeft' ? -1 : 1;
    setHover((index) => Math.min(values.length - 1, Math.max(0, (index ?? values.length - 1) + step)));
  };

  return (
    <div className="spark" ref={box}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={label}
          tabIndex={0}
          onPointerMove={onPointer}
          onPointerLeave={() => setHover(null)}
          onFocus={() => setHover(values.length - 1)}
          onBlur={() => setHover(null)}
          onKeyDown={onKey}
        >
          <line className="spark__base" x1={0} x2={width} y1={height - 0.5} y2={height - 0.5} />
          <path className="spark__area" d={areaPath(points, height)} />
          <path className="spark__line" d={linePath(points)} />
          {active !== null && (
            <>
              <line className="spark__cross" x1={points[active].x} x2={points[active].x} y1={0} y2={height} />
              <circle className="spark__dot" cx={points[active].x} cy={points[active].y} r={4} />
            </>
          )}
          {active === null && last && <circle className="spark__dot" cx={last.x} cy={last.y} r={4} />}
        </svg>
      )}
      {active !== null && points[active] && (
        <div
          className="spark__tip"
          role="status"
          style={{ left: Math.min(Math.max(points[active].x, 40), width - 40), top: Math.max(0, points[active].y - 30) }}
        >
          {describe(active)}
        </div>
      )}
      {ticks.length > 0 && width > 0 && (
        <div className="spark__ticks" aria-hidden>
          {ticks
            .filter((tick) => tick.index < points.length)
            .map((tick) => (
              <span key={tick.index} style={{ left: points[tick.index].x }}>
                {tick.text}
              </span>
            ))}
        </div>
      )}
    </div>
  );
}
