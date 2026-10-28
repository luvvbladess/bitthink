import { useLayoutEffect, useState } from 'react';

/** iOS can both shrink AND pan the visual viewport without a layout resize. */
export function useVisualViewport() {
  const read = () => ({
    height: Math.round(window.visualViewport?.height || window.innerHeight),
    offsetTop: Math.max(0, Math.round(window.visualViewport?.offsetTop || 0)),
  });
  const [bounds, setBounds] = useState(read);
  useLayoutEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const next = read();
      setBounds(previous => previous.height === next.height && previous.offsetTop === next.offsetTop ? previous : next);
    };
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(update); };
    const viewport = window.visualViewport;
    update();
    window.addEventListener('resize', schedule);
    window.addEventListener('orientationchange', schedule);
    viewport?.addEventListener('resize', schedule);
    viewport?.addEventListener('scroll', schedule, { passive: true });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', schedule);
      window.removeEventListener('orientationchange', schedule);
      viewport?.removeEventListener('resize', schedule);
      viewport?.removeEventListener('scroll', schedule);
    };
  }, []);
  return bounds;
}

export function useVisualViewportHeight() {
  return useVisualViewport().height;
}
