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

// The public address, for absolute links in share previews. Vercel provides its production domain at build time.
const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? (process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : "http://localhost:3000");
const DESCRIPTION = "Calm home goods with smart AI support: a team of AI agents tracks orders, handles returns and refunds in seconds, and hands big decisions to real people.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE),
  title: { default: "Brightwood · Calm things, smart support", template: "%s · Brightwood" },
  description: DESCRIPTION,
  applicationName: "Brightwood",
  keywords: ["AI customer support", "multi-agent", "LangGraph", "Gemini", "home goods"],
  openGraph: { type: "website", siteName: "Brightwood", title: "Brightwood · Calm things, smart support", description: DESCRIPTION, url: "/", locale: "en_US" },
  twitter: { card: "summary_large_image", title: "Brightwood · Calm things, smart support", description: DESCRIPTION },
};

export const viewport: Viewport = {
  width: "device-width", initialScale: 1, viewportFit: "cover",
  themeColor: [{ media: "(prefers-color-scheme: light)", color: "#f5efe6" }, { media: "(prefers-color-scheme: dark)", color: "#161514" }],
};

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
