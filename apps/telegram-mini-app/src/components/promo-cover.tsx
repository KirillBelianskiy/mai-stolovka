"use client";

import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ART } from "@/components/customer-ui";

const promos = [
  { title: "Обед в Ледоколе", art: "orbit-cover" },
  { title: "Заберите в своё время", art: "ledokol-lunch" },
];
const rotationDelay = 6500;

function scrollToPromo(viewport: HTMLDivElement, index: number, reducedMotion: boolean) {
  viewport.scrollTo({
    left: index * viewport.clientWidth,
    behavior: reducedMotion ? "instant" : "smooth",
  });
}

export function PromoCover({ active }: { active: boolean }) {
  const [current, setCurrent] = useState(0);
  const [paused, setPaused] = useState(false);
  const [focused, setFocused] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [inView, setInView] = useState(false);
  const [documentVisible, setDocumentVisible] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(true);
  const track = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateMotion = () => setReducedMotion(motion.matches);
    const updateVisibility = () => setDocumentVisible(document.visibilityState === "visible");
    updateMotion();
    updateVisibility();
    motion.addEventListener("change", updateMotion);
    document.addEventListener("visibilitychange", updateVisibility);
    return () => {
      motion.removeEventListener("change", updateMotion);
      document.removeEventListener("visibilitychange", updateVisibility);
    };
  }, []);

  useEffect(() => {
    const viewport = track.current;
    if (!viewport || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setInView(entry.intersectionRatio >= 0.5),
      { threshold: 0.5 },
    );
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const viewport = track.current;
    if (!viewport || !active || !inView || !documentVisible || reducedMotion ||
      paused || focused || hovered || dragging) return;
    const timeout = window.setTimeout(() => {
      scrollToPromo(viewport, (current + 1) % promos.length, false);
    }, rotationDelay);
    return () => window.clearTimeout(timeout);
  }, [active, current, documentVisible, dragging, focused, hovered, inView, paused, reducedMotion]);

  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const move = event.key === "ArrowLeft" ? -1 : 1;
    const next = Math.min(promos.length - 1, Math.max(0, current + move));
    scrollToPromo(event.currentTarget, next, reducedMotion);
  }

  const playbackLabel = paused ? "Включить автопрокрутку" : "Приостановить автопрокрутку";
  return (
    <section className="cover-promos" aria-label="Столовая и выдача" data-promo-carousel
      onPointerEnter={(event) => { if (event.pointerType === "mouse") setHovered(true); }}
      onPointerLeave={(event) => { if (event.pointerType === "mouse") setHovered(false); }}>
      <div className="cover-promo-track" ref={track} tabIndex={0} onKeyDown={handleKey}
        onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        onPointerDown={(event) => { if (event.pointerType !== "mouse") setDragging(true); }}
        onPointerUp={() => setDragging(false)} onPointerCancel={() => setDragging(false)}
        onScroll={(event) => {
          const viewport = event.currentTarget;
          if (viewport.clientWidth) {
            setCurrent(Math.min(promos.length - 1, Math.max(0, Math.round(viewport.scrollLeft / viewport.clientWidth))));
          }
        }}>
        {promos.map((promo, index) => (
          <div className="cover-promo-slide" key={promo.art} aria-hidden={current !== index}>
            <div className="cover-art">
              <img src={ART + "/" + promo.art + ".jpg"} alt="" draggable={false} />
            </div>
            <p className="cover-caption"><strong>{promo.title}</strong></p>
          </div>
        ))}
      </div>
      <div className="cover-promo-controls" aria-hidden="true">
        {promos.map((promo, index) => <span key={promo.art} data-current={current === index} />)}
      </div>
      {!reducedMotion && (
        <button type="button" className="round-button cover-promo-toggle" aria-label={playbackLabel}
          title={playbackLabel} onClick={() => setPaused(!paused)}>
          {paused ? <Play aria-hidden="true" /> : <Pause aria-hidden="true" />}
        </button>
      )}
    </section>
  );
}
