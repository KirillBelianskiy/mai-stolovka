"use client";

import { useState } from "react";
import { Utensils } from "lucide-react";
import { imageUrl, type MenuItem } from "@/lib/menu";

export function DishPhoto({
  item,
}: {
  item: Pick<MenuItem, "name" | "image_url">;
}) {
  const source = imageUrl(item.image_url);
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const available = source && source !== failedSource;

  return (
    <span className="dish-photo">
      {available ? (
        <img
          src={source}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailedSource(source)}
        />
      ) : (
        <span
          className="photo-unavailable"
          role="img"
          aria-label={`Фото блюда «${item.name}» недоступно`}
        >
          <Utensils size={28} aria-hidden="true" />
          <small>Фото пока нет</small>
        </span>
      )}
    </span>
  );
}
