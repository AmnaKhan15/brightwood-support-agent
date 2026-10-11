import type { Metadata, Viewport } from "next";
import { Instrument_Sans, JetBrains_Mono, Newsreader } from "next/font/google";
import { Chat } from "@/components/chat";
import { Header } from "@/components/header";
import { Inspector } from "@/components/inspector";
import { Providers } from "@/components/providers";
import { Toast } from "@/components/toast";
import "./globals.css";

const serif = Newsreader({ variable: "--font-serif", subsets: ["latin"], weight: ["400", "500"], style: ["normal", "italic"] });
const body = Instrument_Sans({ variable: "--font-body", subsets: ["latin"] });
const mono = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Brightwood Goods",
  description: "A fictional home goods store with a working multi-agent AI support assistant.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${serif.variable} ${body.variable} ${mono.variable} antialiased`} suppressHydrationWarning>
      <body className="min-h-dvh font-sans">
        <Providers>
          <Header />
          <main className="mx-auto w-full max-w-[1400px] px-4 pb-28 pt-8 sm:px-6 lg:px-10">{children}</main>
          <Chat />
          <Inspector />
          <Toast />
        </Providers>
      </body>
    </html>
  );
}
