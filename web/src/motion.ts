// anime.js motion helpers. Centralizing here keeps easing/duration consistent
// and lets us swap timelines in one place if the aesthetic changes.

import anime from "animejs";

export const easing = {
  out: "cubicBezier(0.22, 1, 0.36, 1)",
  inOut: "cubicBezier(0.65, 0, 0.35, 1)",
  spring: "spring(1, 80, 10, 0)",
};

export function revealUp(
  targets: anime.AnimeParams["targets"],
  opts: anime.AnimeParams = {},
): anime.AnimeInstance {
  return anime({
    targets,
    translateY: [16, 0],
    opacity: [0, 1],
    duration: 520,
    easing: easing.out,
    delay: anime.stagger(40),
    ...opts,
  });
}

export function staggerIn(
  targets: anime.AnimeParams["targets"],
  opts: anime.AnimeParams = {},
): anime.AnimeInstance {
  return anime({
    targets,
    translateX: [-24, 0],
    opacity: [0, 1],
    duration: 460,
    easing: easing.out,
    delay: anime.stagger(30),
    ...opts,
  });
}

export function modalIn(backdrop: Element, modal: Element): void {
  anime({
    targets: backdrop,
    opacity: [0, 1],
    duration: 200,
    easing: easing.out,
  });
  anime({
    targets: modal,
    scale: [0.92, 1],
    opacity: [0, 1],
    duration: 340,
    easing: easing.out,
  });
}

export function modalOut(
  backdrop: Element,
  modal: Element,
  onDone: () => void,
): void {
  anime({
    targets: modal,
    scale: [1, 0.94],
    opacity: [1, 0],
    duration: 180,
    easing: easing.inOut,
  });
  anime({
    targets: backdrop,
    opacity: [1, 0],
    duration: 220,
    easing: easing.inOut,
    complete: onDone,
  });
}

export function toastIn(el: Element): void {
  anime({
    targets: el,
    translateX: [40, 0],
    opacity: [0, 1],
    duration: 320,
    easing: easing.out,
  });
}

export function toastOut(el: Element, onDone: () => void): void {
  anime({
    targets: el,
    translateX: [0, 40],
    opacity: [1, 0],
    duration: 260,
    easing: easing.inOut,
    complete: onDone,
  });
}

export function pulseGlow(_target: Element): void {
  // Intentionally a no-op in the tailadmin theme — no neon glow.
}

export function scanlineSweep(_el: Element): void {
  // No-op: no scanline in the admin theme.
}

export function progressTo(fill: Element, pct: number): void {
  anime({
    targets: fill,
    width: `${Math.max(0, Math.min(100, pct))}%`,
    duration: 320,
    easing: easing.out,
  });
}

export function numberTo(el: Element, from: number, to: number): void {
  const obj = { n: from };
  anime({
    targets: obj,
    n: to,
    duration: 420,
    round: 1,
    easing: easing.out,
    update: () => {
      (el as HTMLElement).textContent = String(obj.n);
    },
  });
}
