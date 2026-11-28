"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { ART } from "@/components/customer-ui";

const promos = [
  { title: "Обед в Ледоколе", art: "orbit-cover" },
  { title: "Заберите в своё время", art: "ledokol-lunch" },
];

export function PromoCover() {
  const [current, setCurrent] = useState(0);
  const track = useRef<HTMLDivElement>(null);

  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    const viewport = track.current;
    if (!viewport || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    const move = event.key === "ArrowLeft" ? -1 : 1;
    const next = Math.min(promos.length - 1, Math.max(0, current + move));
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    viewport.scrollTo({
      left: next * viewport.clientWidth,
      behavior: reducedMotion ? "instant" : "smooth",
    });
  }

  return (
    <section className="cover-promos" aria-label="Столовая и выдача" data-promo-carousel>
      <div className="cover-promo-track" ref={track} tabIndex={0} onKeyDown={handleKey}
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
    </section>
  );
}
