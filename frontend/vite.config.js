import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
const require = createRequire(import.meta.url);
const swagger = dirname(require.resolve("swagger-ui-dist/package.json"));
function offlineDocs() {
  return {
    name: "offline-api-docs",
    generateBundle() {
      const files = {
        "swagger-ui-bundle.js": join(swagger, "swagger-ui-bundle.js"),
        "swagger-ui.css": join(swagger, "swagger-ui.css"),
        "LICENSE.txt": join(swagger, "LICENSE"),
        "NOTICE.txt": join(swagger, "NOTICE"),
        "swagger-ui-bundle.js.LICENSE.txt": join(
          swagger,
          "swagger-ui-bundle.js.LICENSE.txt",
        ),
        "index.html": new URL("./docs/index.html", import.meta.url),
        "initializer.js": new URL("./docs/initializer.js", import.meta.url),
      };
      for (const [name, path] of Object.entries(files)) {
        this.addWatchFile(path instanceof URL ? path.pathname : path);
        const source = readFileSync(path, "utf8")
          .replace(/\/\/# sourceMappingURL=.*$/gm, "")
          .replace(/\/\*# sourceMappingURL=.*?\*\//g, "");
        this.emitFile({ type: "asset", fileName: `swagger/${name}`, source });
      }
    },
  };
}
export default defineConfig({
  plugins: [react(), tailwindcss(), offlineDocs()],
  base: "/assets/",
  build: { outDir: "../src/reviewpoint/assets", emptyOutDir: true },
  test: { environment: "jsdom" },
});
