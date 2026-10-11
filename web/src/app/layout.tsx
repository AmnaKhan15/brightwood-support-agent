import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Manrope, Sora } from "next/font/google";
import { Chat } from "@/components/chat";
import { Header } from "@/components/header";
import { Inspector } from "@/components/inspector";
import { Providers } from "@/components/providers";
import { Toast } from "@/components/toast";
import "./globals.css";

const sora = Sora({ variable: "--font-sora", subsets: ["latin"], weight: ["600", "700"] });
const manrope = Manrope({ variable: "--font-manrope", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Brightwood Goods",
  description: "A fictional home goods store with a working multi-agent AI support assistant.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sora.variable} ${manrope.variable} ${mono.variable} antialiased`} suppressHydrationWarning>
      <body className="min-h-dvh font-sans">
        <Providers>
          <Header />
          <main className="mx-auto w-full max-w-6xl px-4 pb-28 pt-8">{children}</main>
          <Chat />
          <Inspector />
          <Toast />
        </Providers>
      </body>
    </html>
  );
}
