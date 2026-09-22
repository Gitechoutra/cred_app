import { useEffect, useRef, useState } from 'react';

/**
 * Reveal an element the first time it scrolls into view.
 *
 * Uses IntersectionObserver rather than a scroll listener, so the work happens
 * off the main thread and a long page does not fire a callback on every frame
 * of a flick scroll.
 *
 * It reveals **once** and then disconnects. Content that re-animates every time
 * it passes the viewport reads as instability, which is the wrong note on a
 * screen showing someone's money - and an observer left attached to a hundred
 * rows is a leak nobody notices until the tab has been open an hour.
 *
 * `prefers-reduced-motion` short-circuits the whole thing: the element starts
 * visible and no observer is created at all.
 */
export function useReveal(options = {}) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;

    if (prefersReducedMotion()) {
      setVisible(true);
      return undefined;
    }

    // Already on screen at mount - reveal without waiting for a scroll that
    // may never come.
    const rect = node.getBoundingClientRect();
    if (rect.top < window.innerHeight && rect.bottom > 0) {
      setVisible(true);
      return undefined;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        setVisible(true);
        observer.disconnect();
      },
      // A small negative bottom margin means the element is a little way into
      // the viewport before it moves, rather than animating right on the edge
      // where the motion is half off-screen.
      { threshold: 0.05, rootMargin: '0px 0px -40px 0px', ...options },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return { ref, visible };
}

/**
 * Wrapper form, for when a component just needs its children to arrive.
 *
 * `delay` staggers a handful of siblings. Use the `.stagger` class instead for
 * a whole grid - a delay per child there means a prop on every child.
 */
export function Reveal({ children, delay = 0, className = '', as: Tag = 'div' }) {
  const { ref, visible } = useReveal();

  return (
    <Tag
      ref={ref}
      className={`reveal ${visible ? 'is-visible' : ''} ${className}`.trim()}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children}
    </Tag>
  );
}

/** Single source of truth for the motion preference. */
export function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  );
}

/**
 * Pointer-driven parallax, normalised to -1..1 on each axis.
 *
 * Reads the pointer at the window level and writes a transform on the element,
 * rather than tracking hover per layer - one listener, any number of layers,
 * each choosing its own depth.
 *
 * Returns a zero offset under reduced motion, which is why the CSS does not try
 * to neutralise it: an inline transform would win over a stylesheet rule.
 * Skipped entirely on coarse pointers, where there is no cursor to follow and
 * the listener would only cost battery.
 */
export function useParallax({ strength = 12 } = {}) {
  const [offset, setOffset] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const coarse = window.matchMedia?.('(pointer: coarse)').matches;
    if (prefersReducedMotion() || coarse) return undefined;

    let frame = 0;

    const onMove = (event) => {
      // Coalesce to one update per frame. Pointer events fire far faster than
      // the display refreshes, and setting state on each is wasted work.
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const x = (event.clientX / window.innerWidth - 0.5) * 2;
        const y = (event.clientY / window.innerHeight - 0.5) * 2;
        setOffset({ x: x * strength, y: y * strength });
      });
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    return () => {
      window.removeEventListener('pointermove', onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [strength]);

  return offset;
}

/**
 * Count a number up once its element is on screen.
 *
 * Driven by requestAnimationFrame against a timestamp rather than a fixed step,
 * so the duration holds even when the tab is throttled or the display runs at
 * 120Hz. Eased out, because a linear counter looks mechanical.
 *
 * Under reduced motion it renders the final value immediately - the information
 * is the number, not the counting.
 */
export function useCountUp(target, { duration = 1400 } = {}) {
  const { ref, visible } = useReveal();
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!visible) return undefined;

    if (prefersReducedMotion()) {
      setValue(target);
      return undefined;
    }

    let frame = 0;
    let start = 0;

    const tick = (now) => {
      if (!start) start = now;
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - (1 - progress) ** 3;
      setValue(target * eased);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [visible, target, duration]);

  return { ref, value };
}

export default useReveal;
