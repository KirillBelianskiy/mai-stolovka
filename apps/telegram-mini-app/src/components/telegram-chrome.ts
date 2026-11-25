"use client";

import { on, postEventFp, supports, type SafeAreaInsets } from "@tma.js/sdk-react";
import { useEffect, useEffectEvent, useState } from "react";

export function useTelegramChrome(canGoBack: boolean, onBack: () => void) {
  const [version, setVersion] = useState<string | null>(null);
  const dispatchBack = useEffectEvent(onBack);

  useEffect(() => {
    // Read only the presentation version. The auth provider owns signed launch data.
    const url = new URL(window.location.href);
    const launchVersion = new URLSearchParams(url.hash.slice(1)).get("tgWebAppVersion")
      ?? url.searchParams.get("tgWebAppVersion");
    if (!launchVersion || !/^\d+(\.\d+){1,2}$/.test(launchVersion)) return;
    setVersion(launchVersion);
    postEventFp("web_app_ready");
    if (!supports("web_app_request_safe_area", launchVersion)) return;

    const root = document.documentElement;
    const setInsets = (name: string, insets: SafeAreaInsets) => {
      for (const edge of ["top", "right", "bottom", "left"] as const) {
        root.style.setProperty("--telegram-" + name + "-" + edge, Math.max(0, insets[edge]) + "px");
      }
    };
    const removeSafe = on("safe_area_changed", (insets) => setInsets("safe", insets));
    const removeContent = on("content_safe_area_changed", (insets) => setInsets("content", insets));
    postEventFp("web_app_request_safe_area");
    postEventFp("web_app_request_content_safe_area");
    return () => {
      removeSafe();
      removeContent();
      for (const name of ["safe", "content"]) {
        for (const edge of ["top", "right", "bottom", "left"]) {
          root.style.removeProperty("--telegram-" + name + "-" + edge);
        }
      }
    };
  }, []);

  useEffect(() => {
    if (!version || !supports("web_app_setup_back_button", version)) return;
    postEventFp("web_app_setup_back_button", { is_visible: canGoBack });
    if (canGoBack) return on("back_button_pressed", () => dispatchBack());
  }, [canGoBack, version]);
}
