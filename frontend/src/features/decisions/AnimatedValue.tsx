import { useEffect, useRef, useState } from "react";

export function AnimatedValue({
  value,
  format,
}: {
  value: number;
  format: (value: number) => string;
}) {
  const current = useRef(value);
  const [display, setDisplay] = useState(value);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      current.current = value;
      setDisplay(value);
      return;
    }
    const start = performance.now();
    const from = current.current;
    let frame: number;
    const update = (now: number) => {
      const progress = Math.min(1, (now - start) / 350);
      current.current = from + (value - from) * (1 - (1 - progress) ** 3);
      setDisplay(Math.round(current.current));
      if (progress < 1) frame = requestAnimationFrame(update);
    };
    frame = requestAnimationFrame(update);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <span aria-label={format(value)}>{format(display)}</span>;
}
