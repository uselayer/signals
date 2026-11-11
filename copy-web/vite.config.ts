import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Built into the engine's static folder: /copy serves index.html, its files load from /static/copy/.
export default defineConfig({
  plugins: [react()],
  base: "/static/copy/",
  build: { outDir: "../signals/static/copy", emptyOutDir: true, sourcemap: false },
});
