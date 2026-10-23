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

export default useReveal;
