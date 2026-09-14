import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/assets/",
  build: { outDir: "../src/reviewpoint/assets", emptyOutDir: true },
  test: { environment: "jsdom" },
});
