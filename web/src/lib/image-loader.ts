"use client";

/** next/image asks this for each size it needs. Unsplash resizes and compresses on its own CDN, so the browser
 *  loads photos straight from there instead of through Next's /_next/image optimizer (which, on Vercel, is a
 *  separately metered service). Any other image is used as it is. */
export default function imageLoader({ src, width, quality }: { src: string; width: number; quality?: number }) {
  if (!src.startsWith("https://images.unsplash.com/")) return src;
  const url = new URL(src);
  url.searchParams.set("w", String(width));
  url.searchParams.set("q", String(quality ?? 75));
  url.searchParams.set("auto", "format");
  url.searchParams.set("fit", "crop");
  return url.toString();
}
