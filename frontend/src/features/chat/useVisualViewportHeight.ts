import { useEffect, useState } from 'react';

/** The usable area can shrink for a software keyboard without a layout resize. */
export function useVisualViewportHeight() {
  const read = () => Math.round(window.visualViewport?.height || window.innerHeight);
  const [height, setHeight] = useState(read);
  useEffect(() => {
    const update = () => setHeight(read());
    const viewport = window.visualViewport;
    window.addEventListener('resize', update);
    viewport?.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
      viewport?.removeEventListener('resize', update);
    };
  }, []);
  return height;
}
