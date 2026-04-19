import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  const appTitle = process.env.NEXT_PUBLIC_APP_TITLE ?? "Product Foundry";
  const accentColor = process.env.NEXT_PUBLIC_ACCENT_COLOR ?? "#c9972a";
  const logoPath = process.env.NEXT_PUBLIC_LOGO_PATH ?? "/favicon.svg";
  return {
    name: appTitle,
    short_name: appTitle.split(" ").pop() ?? appTitle,
    description: "AI product engineering command center.",
    start_url: "/",
    display: "standalone",
    background_color: "#0f1623",
    theme_color: accentColor,
    icons: [
      {
        src: logoPath,
        sizes: "any",
        type: "image/png",
      },
      {
        src: "/favicon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "maskable",
      },
    ],
  };
}
