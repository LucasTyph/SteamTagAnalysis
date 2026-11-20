import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// VITE_BASE controls where the site is served from:
//   GitHub Pages project site → "/<repo-name>/"
//   own domain root           → "/"
//   own domain subfolder      → "/steam/"
// Always fetch data via import.meta.env.BASE_URL so moving hosts is one setting.
//
// VITE_SITE_URL is the site's public address (e.g. https://example.com/steam/). Link
// previews need absolute URLs, so it fills %SITE_URL% in index.html; without it
// (local builds) the preview tags fall back to relative URLs.
const siteUrl = (process.env.VITE_SITE_URL ?? "").replace(/\/?$/, "/").replace(/^\/$/, "");

const siteMeta: Plugin = {
  name: "site-meta",
  transformIndexHtml: (html) => html.replaceAll("%SITE_URL%", siteUrl),
};

export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react(), siteMeta],
});
