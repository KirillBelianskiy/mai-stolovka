const BACKEND_ORIGIN = new URL("https://api-test.maistolovka.me");

type ProxyContext = { request: Request };

export async function onRequest({ request }: ProxyContext): Promise<Response> {
  const upstreamUrl = new URL(request.url);
  upstreamUrl.protocol = BACKEND_ORIGIN.protocol;
  upstreamUrl.host = BACKEND_ORIGIN.host;

  // Constructing from the incoming Request preserves credentials, Origin, bodies,
  // and the WebSocket Upgrade handshake while pinning the destination hostname.
  return fetch(new Request(upstreamUrl, request));
}
