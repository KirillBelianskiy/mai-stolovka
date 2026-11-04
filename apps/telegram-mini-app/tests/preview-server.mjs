// Isolated static-export preview with synthetic API fixtures. Never used by the application.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../out");
const categories = ["Супы", "Горячее", "Напитки"].map((name, index) => ({
  id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  name,
  sort_order: index,
}));
const names = [
  "Суп-пюре из тыквы",
  "Куриный суп с лапшой",
  "Борщ со сметаной",
  "Куриная котлета с пюре",
  "Гречка с овощами",
  "Паста с курицей",
  "Рис с овощами",
  "Компот из сухофруктов",
];
const items = Array.from({ length: 28 }, (_, index) => ({
  id: `10000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
  category_id: categories[index < 3 ? 0 : index > 25 ? 2 : 1].id,
  name: names[index % names.length] + (index >= 8 ? ` · ${index + 1}` : ""),
  description:
    index % 3 === 0
      ? "Нежный вкус, сезонные овощи и немного хорошего настроения."
      : "Классический обед в столовой МАИ.",
  price: [14500, 12000, 13550, 24000, 9500, 21500, 8500, 4500][index % 8],
  is_available: true,
  image_url: null,
}));
const mime = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".ico": "image/x-icon",
};
const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  // Optional same-origin proxy for a disposable User Service, never the deployed API.
  if (process.env.MAI_USER_TEST_URL && url.pathname.startsWith("/api/v1/users/")) {
    try {
      const target = new URL(process.env.MAI_USER_TEST_URL);
      if (!["localhost", "127.0.0.1"].includes(target.hostname)) throw new Error("Local only");
      const headers = {};
      for (const name of ["authorization", "cookie", "origin", "content-type"]) {
        if (request.headers[name]) headers[name] = request.headers[name];
      }
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const result = await fetch(new URL(url.pathname.replace("/api/v1/users", "") + url.search, target), {
        method: request.method,
        headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : Buffer.concat(chunks),
        redirect: "error",
        signal: AbortSignal.timeout(10000),
      });
      response.writeHead(result.status, {
        "Content-Type": result.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store",
        "Set-Cookie": result.headers.getSetCookie(),
      });
      response.end(Buffer.from(await result.arrayBuffer()));
    } catch { response.writeHead(502).end("Disposable User Service unavailable"); }
    return;
  }
  const scenario = new URL(
    request.headers.referer ?? "http://127.0.0.1",
  ).searchParams.get("scenario");
  function json(body, status = 200) {
    response.writeHead(status, {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    });
    response.end(JSON.stringify(body));
  }
  if (url.pathname.startsWith("/api/")) {
    if (scenario === "slow")
      await new Promise((resolve) => setTimeout(resolve, 2200));
    if (scenario === "error") return json({ detail: "Synthetic outage" }, 503);
    if (url.pathname === "/api/v1/menu/categories") return json(categories);
    if (url.pathname === "/api/v1/menu/items") {
      const all =
        scenario === "empty"
          ? []
          : items.filter(
              (item) =>
                !url.searchParams.has("category_id") ||
                item.category_id === url.searchParams.get("category_id"),
            );
      const offset = Number(url.searchParams.get("offset") ?? 0),
        limit = Number(url.searchParams.get("limit") ?? 24);
      return json({
        items: all.slice(offset, offset + limit),
        total: all.length,
        limit,
        offset,
      });
    }
    const found = items.find(
      (item) => `/api/v1/menu/items/${item.id}` === url.pathname,
    );
    if (found && scenario !== "unavailable") return json(found);
    return json({ detail: "Not found" }, 404);
  }
  let path;
  try {
    path = resolve(root, "." + decodeURIComponent(url.pathname));
  } catch {
    response.writeHead(400).end();
    return;
  }
  if (path !== root && !path.startsWith(root + "/")) {
    response.writeHead(403).end();
    return;
  }
  if (!extname(path)) path = join(path, "index.html");
  try {
    const data = await readFile(path);
    response.writeHead(200, {
      "Content-Type": mime[extname(path)] ?? "application/octet-stream",
      "Cache-Control": "no-store",
    });
    response.end(data);
  } catch {
    response.writeHead(404).end("Not found");
  }
});
server.listen(Number(process.env.MAI_PREVIEW_PORT ?? 8765), "127.0.0.1", () =>
  console.log("Synthetic Mini App preview: http://127.0.0.1:8765"),
);
