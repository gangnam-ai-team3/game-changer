import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "게임체인저",
  description: "글로벌 게임 이벤트 사전 검토",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
