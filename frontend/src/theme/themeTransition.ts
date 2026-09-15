import { flushSync } from 'react-dom';

const EASE = 'cubic-bezier(0.22, 1, 0.36, 1)';

function reducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function once(fn: () => void) {
  let done = false;
  return () => {
    if (done) return;
    done = true;
    fn();
  };
}

/** Crossfade the whole page. Do not lerp individual colors: that muddy mid-gray is the ugly flash. */
export function withThemeTransition(apply: () => void) {
  if (reducedMotion()) {
    apply();
    return;
  }

  const startViewTransition = document.startViewTransition?.bind(document);
  if (startViewTransition) {
    startViewTransition(() => {
      flushSync(apply);
    });
    return;
  }

  const app = document.getElementById('root');
  if (!app) {
    apply();
    return;
  }

  const finishIn = once(() => {
    app.style.transition = '';
    app.style.opacity = '';
  });

  const reveal = once(() => {
    flushSync(apply);
    requestAnimationFrame(() => {
      app.style.transition = `opacity 0.38s ${EASE}`;
      app.style.opacity = '1';
      app.addEventListener('transitionend', finishIn, { once: true });
      window.setTimeout(finishIn, 420);
    });
  });

  app.style.transition = `opacity 0.18s ${EASE}`;
  app.style.opacity = '0';
  app.addEventListener('transitionend', reveal, { once: true });
  window.setTimeout(reveal, 200);
}
