const BACKEND_ORIGIN = new URL("https://api-test.maistolovka.me");

type ProxyContext = { request: Request };

export async function onRequest({ request }: ProxyContext): Promise<Response> {
  const upstreamUrl = new URL(request.url);
  upstreamUrl.protocol = BACKEND_ORIGIN.protocol;
  upstreamUrl.host = BACKEND_ORIGIN.host;
  return fetch(new Request(upstreamUrl, request));
}
