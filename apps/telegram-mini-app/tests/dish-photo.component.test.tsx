import { afterEach, expect, test } from "vitest";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { DishPhoto } from "../src/components/dish-photo";

afterEach(cleanup);

test("dishes get a neutral illustration if no working photo is available", () => {
  const item = { name: "Борщ со сметаной", image_url: null as string | null };
  const { container, rerender } = render(<DishPhoto item={item} />);
  expect(container.querySelector("img")?.getAttribute("src")).toBe("/design/mai-eda/plate.svg");
  rerender(
    <DishPhoto item={{ ...item, image_url: "http://localhost/borscht.jpg" }} />,
  );
  const image = container.querySelector("img")!;
  fireEvent.error(image);
  expect(container.querySelector("img")?.getAttribute("src")).toBe("/design/mai-eda/plate.svg");
});

test("changing a failed image URL loads the replacement", () => {
  const item = { name: "Борщ", image_url: "http://localhost/old.jpg" };
  const { container, rerender } = render(<DishPhoto item={item} />);
  fireEvent.error(container.querySelector("img")!);
  rerender(
    <DishPhoto item={{ ...item, image_url: "http://localhost/new.jpg" }} />,
  );
  expect(container.querySelector("img")?.getAttribute("src")).toBe(
    "http://localhost/new.jpg",
  );
});
