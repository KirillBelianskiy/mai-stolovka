"use client";

import { useState } from "react";
import { imageUrl, type MenuItem } from "@/lib/menu";
import { ART } from "@/components/customer-ui";

export function DishPhoto({ item, eager = false }: {
  item: Pick<MenuItem, "image_url">;
  eager?: boolean;
}) {
  const source = imageUrl(item.image_url);
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const photo = source && source !== failedSource ? source : undefined;

  return (
    <span className="dish-photo" data-product-photo={Boolean(photo)}>
      <img
        src={photo ?? ART + "/plate.svg"}
        alt=""
        loading={eager ? "eager" : "lazy"}
        referrerPolicy="no-referrer"
        onError={() => { if (photo) setFailedSource(photo); }}
      />
    </span>
  );
}
