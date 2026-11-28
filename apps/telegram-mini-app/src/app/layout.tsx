import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "МАИ.Еда",
  description: "Меню столовой МАИ. Выберите блюда и соберите свой обед.",
};

export const viewport: Viewport = { viewportFit: "cover", themeColor: "#0B111D" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
