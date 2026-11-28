"use client";

import { useState } from "react";
import { imageUrl, type MenuItem } from "@/lib/menu";
import { ART } from "@/components/customer-ui";

const uuid = "[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}";
const uploadedPhoto = new RegExp("^/api/v1/menu/photos/" + uuid + "/(?:menu|detail)/" + uuid + "$");

export function DishPhoto({ item, detail = false, eager = false }: {
  item: Pick<MenuItem, "image_url" | "menu_image_url" | "detail_image_url">;
  detail?: boolean;
  eager?: boolean;
}) {
  const [failed, setFailed] = useState<string[]>([]);
  const photo = [
    detail ? item.detail_image_url : null,
    item.menu_image_url,
  ].find((url) => url && uploadedPhoto.test(url) && !failed.includes(url))
    ?? imageUrl(item.image_url);
  const source = photo && !failed.includes(photo) ? photo : undefined;

  return (
    <span className="dish-photo" data-product-photo={Boolean(source)}>
      <img
        src={source ?? ART + "/plate.svg"}
        alt=""
        loading={eager ? "eager" : "lazy"}
        referrerPolicy="no-referrer"
        onError={() => { if (source) setFailed((previous) => [...previous, source]); }}
      />
    </span>
  );
}
