import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// VITE_BASE controls where the site is served from:
//   GitHub Pages project site → "/<repo-name>/"
//   own domain root           → "/"
//   own domain subfolder      → "/steam/"
// Always fetch data via import.meta.env.BASE_URL so moving hosts is one setting.
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
});
