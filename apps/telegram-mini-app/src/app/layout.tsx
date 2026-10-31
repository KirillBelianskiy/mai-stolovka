import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = { title: "Обед в МАИ", description: "МАИ Еда — каркас приложения" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="ru"><body><Providers>{children}</Providers></body></html>;
}
