import type { Metadata, Viewport } from "next";
import { Instrument_Serif, JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google";
import { Chat } from "@/components/chat";
import { Header } from "@/components/header";
import { Inspector } from "@/components/inspector";
import { SmoothScroll } from "@/components/motion";
import { Providers } from "@/components/providers";
import { Toast } from "@/components/toast";
import { VoiceGreeting } from "@/components/voice-greeting";
import "lenis/dist/lenis.css";
import "./globals.css";

const serif = Instrument_Serif({ variable: "--font-serif", subsets: ["latin"], weight: "400", style: ["normal", "italic"] });
const body = Plus_Jakarta_Sans({ variable: "--font-body", subsets: ["latin"], weight: ["400", "500", "600", "700", "800"] });
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
          <SmoothScroll />
          <Header />
          <main className="mx-auto w-full max-w-[1400px] px-4 pb-28 pt-8 sm:px-6 lg:px-10">{children}</main>
          <Chat />
          <VoiceGreeting />
          <Inspector />
          <Toast />
        </Providers>
      </body>
    </html>
  );
}
