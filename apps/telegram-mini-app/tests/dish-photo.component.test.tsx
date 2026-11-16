import { afterEach, expect, test } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DishPhoto } from "../src/components/dish-photo";

afterEach(cleanup);

test("missing and failed images leave an explained placeholder", () => {
  const item = { name: "Борщ", image_url: null as string | null };
  const { container, rerender } = render(<DishPhoto item={item} />);
  expect(
    screen.getByRole("img", { name: "Фото блюда «Борщ» недоступно" }),
  ).toBeTruthy();
  rerender(
    <DishPhoto item={{ ...item, image_url: "http://localhost/borscht.jpg" }} />,
  );
  const image = container.querySelector("img")!;
  fireEvent.error(image);
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByText("Фото пока нет")).toBeTruthy();
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
  expect(screen.queryByText("Фото пока нет")).toBeNull();
});
