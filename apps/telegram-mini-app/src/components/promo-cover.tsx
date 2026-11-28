"use client";

import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { ART } from "@/components/customer-ui";

const promos = [
  { title: "Обед в Ледоколе", art: "orbit-cover" },
  { title: "Заберите в своё время", art: "ledokol-lunch" },
];
const trackPromos = [promos.at(-1)!, ...promos, promos[0]];
const rotationDelay = 6500;

function moveTo(viewport: HTMLDivElement, position: number, behavior: ScrollBehavior) {
  viewport.scrollTo({ left: position * viewport.clientWidth, behavior });
}

export function PromoCover({ active }: { active: boolean }) {
  const [current, setCurrent] = useState(0);
  const [inView, setInView] = useState(false);
  const [canRotate, setCanRotate] = useState(false);
  const [inMotion, setInMotion] = useState(false);
  const [touching, setTouching] = useState(false);
  const track = useRef<HTMLDivElement>(null);
  const position = useRef(1);
  const width = useRef(0);
  const settleTimer = useRef<number | undefined>(undefined);

  useLayoutEffect(() => {
    const viewport = track.current;
    if (!viewport || !active) return;
    function align() {
      if (!viewport?.clientWidth || width.current === viewport.clientWidth) return;
      width.current = viewport.clientWidth;
      moveTo(viewport, position.current, "instant");
    }
    align();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(align) : null;
    observer?.observe(viewport);
    return () => observer?.disconnect();
  }, [active]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setCanRotate(document.visibilityState === "visible" && !media.matches);
    update();
    media.addEventListener("change", update);
    document.addEventListener("visibilitychange", update);
    return () => {
      media.removeEventListener("change", update);
      document.removeEventListener("visibilitychange", update);
      window.clearTimeout(settleTimer.current);
    };
  }, []);

  useEffect(() => {
    const viewport = track.current;
    if (!viewport || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setInView(entry.isIntersecting),
    );
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const viewport = track.current;
    if (!viewport || !active || !inView || !canRotate || inMotion || touching) return;
    const timeout = window.setTimeout(() => moveTo(viewport, position.current + 1, "smooth"), rotationDelay);
    return () => window.clearTimeout(timeout);
  }, [active, canRotate, current, inMotion, inView, touching]);

  function handleScroll(viewport: HTMLDivElement) {
    if (!viewport.clientWidth) return;
    const index = Math.round(viewport.scrollLeft / viewport.clientWidth);
    setCurrent((index + promos.length - 1) % promos.length);
    setInMotion(true);
    window.clearTimeout(settleTimer.current);
    settleTimer.current = window.setTimeout(() => {
      if (index === 0 || index === promos.length + 1) {
        // The copy and its original look identical. Reposition between them without animation.
        position.current = index === 0 ? promos.length : 1;
        moveTo(viewport, position.current, "instant");
      } else {
        position.current = index;
      }
      setInMotion(false);
    }, 120);
  }

  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    if (inMotion) return;
    const step = event.key === "ArrowLeft" ? -1 : 1;
    moveTo(event.currentTarget, position.current + step, canRotate ? "smooth" : "instant");
  }

  return (
    <section className="cover-promos" aria-label="Столовая и выдача" data-promo-carousel>
      <div className="cover-promo-track" ref={track} tabIndex={0} onKeyDown={handleKey}
        onTouchStart={() => setTouching(true)}
        onTouchEnd={() => setTouching(false)} onTouchCancel={() => setTouching(false)}
        onScroll={(event) => handleScroll(event.currentTarget)}>
        {trackPromos.map((promo, index) => (
          <div className="cover-promo-slide" key={index}
            aria-hidden={index !== current + 1}>
            <div className="cover-art"><img src={ART + "/" + promo.art + ".jpg"} alt="" draggable={false} /></div>
            <p className="cover-caption"><strong>{promo.title}</strong></p>
          </div>
        ))}
      </div>
      <div className="cover-promo-controls" aria-hidden="true">
        {promos.map((promo, index) => <span key={promo.art} data-current={current === index} />)}
      </div>
    </section>
  );
}
