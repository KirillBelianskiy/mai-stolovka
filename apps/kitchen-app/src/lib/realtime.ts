const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function createHintTracker() {
  const newest = new Map<string, number>();
  return (message: Record<string, unknown>) => {
    const { type, order_id: id, version } = message;
    if (
      type !== "order.changed" ||
      typeof id !== "string" ||
      !UUID.test(id) ||
      typeof version !== "number" ||
      !Number.isSafeInteger(version) ||
      version < 1 ||
      version > 2_147_483_647
    ) return false;

    const orderId = id.toLowerCase();
    if ((newest.get(orderId) ?? 0) >= version) return false;
    newest.delete(orderId);
    newest.set(orderId, version);
    if (newest.size > 512) {
      const oldest = newest.keys().next();
      if (!oldest.done) newest.delete(oldest.value);
    }
    return true;
  };
}

export function createQueueRefresh(fetchQueue: (quiet: boolean) => Promise<void>) {
  let generation = 0;
  let quiet = true;
  let running: Promise<void> | null = null;
  let stopped = false;

  async function reconcile() {
    try {
      while (!stopped) {
        const observed = generation;
        const quietFetch = quiet;
        quiet = true;
        await fetchQueue(quietFetch);
        if (observed === generation) return;
      }
    } finally {
      running = null;
    }
  }

  return {
    request(quietRequest = false) {
      if (stopped) return Promise.resolve();
      generation += 1;
      quiet &&= quietRequest;
      running ??= Promise.resolve().then(reconcile);
      return running;
    },
    stop() {
      stopped = true;
    },
  };
}

export function startKitchenRealtime({
  token,
  refresh,
  onUnauthorized,
}: {
  token: string;
  refresh: (quiet?: boolean) => void;
  onUnauthorized: (code: number) => void;
}) {
  let stopped = false;
  let socket: WebSocket | undefined;
  let retry: number | undefined;
  let handshake: number | undefined;
  let attempts = 0;
  let fetched = false;

  function reconcile() {
    refresh(fetched);
    fetched = true;
  }

  function reconnect() {
    const base = Math.min(30_000, 1000 * 2 ** Math.min(attempts++, 5));
    retry = window.setTimeout(() => {
      retry = undefined;
      connect();
    }, base * (0.75 + Math.random() * 0.25));
  }

  function connect() {
    if (stopped || socket || retry !== undefined) return;
    const url = new URL("/api/v1/ws/kitchen", window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    let connection: WebSocket;
    try {
      connection = new WebSocket(url);
    } catch {
      reconcile();
      reconnect();
      return;
    }

    socket = connection;
    let subscribed = false;
    const acceptHint = createHintTracker();
    handshake = window.setTimeout(() => {
      if (socket !== connection) return;
      reconcile();
      socket = undefined;
      connection.close();
      reconnect();
    }, 6000);

    connection.onopen = () => {
      if (socket === connection) {
        connection.send(JSON.stringify({ type: "auth", access_token: token }));
      }
    };
    connection.onmessage = (event) => {
      if (socket !== connection || typeof event.data !== "string") return;
      let message: Record<string, unknown>;
      try {
        const parsed: unknown = JSON.parse(event.data);
        if (!parsed || typeof parsed !== "object") return;
        message = parsed as Record<string, unknown>;
      } catch {
        return;
      }
      if (message.type === "ready" && !subscribed) {
        subscribed = true;
        attempts = 0;
        window.clearTimeout(handshake);
        reconcile();
      } else if (subscribed && acceptHint(message)) {
        reconcile();
      }
    };
    connection.onclose = ({ code }) => {
      if (socket !== connection) return;
      socket = undefined;
      window.clearTimeout(handshake);
      if (code === 4401 || code === 4403) {
        stop();
        onUnauthorized(code);
        return;
      }
      reconcile();
      reconnect();
    };
  }

  const onResume = () => {
    // The first snapshot normally follows ready. When disconnected, use REST fallback.
    if (fetched) reconcile();
    if (!socket) {
      window.clearTimeout(retry);
      retry = undefined;
      connect();
    }
  };
  const onVisible = () => {
    if (document.visibilityState === "visible") onResume();
  };
  const poll = window.setInterval(() => {
    if (fetched && document.visibilityState === "visible") reconcile();
  }, 15_000);
  window.addEventListener("focus", onResume);
  window.addEventListener("online", onResume);
  document.addEventListener("visibilitychange", onVisible);

  function stop() {
    if (stopped) return;
    stopped = true;
    window.clearTimeout(retry);
    window.clearTimeout(handshake);
    window.clearInterval(poll);
    window.removeEventListener("focus", onResume);
    window.removeEventListener("online", onResume);
    document.removeEventListener("visibilitychange", onVisible);
    const closing = socket;
    socket = undefined;
    closing?.close();
  }

  connect();
  return stop;
}
