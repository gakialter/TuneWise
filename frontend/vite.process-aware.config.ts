import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const processAwareRoot = fileURLToPath(new URL("./process-aware", import.meta.url));
const processAwareOutput = fileURLToPath(
  new URL("../src/tunewise/process_aware_demo_static", import.meta.url),
);

export default defineConfig({
  base: "/process-aware-demo/",
  root: processAwareRoot,
  plugins: [react()],
  build: {
    outDir: processAwareOutput,
    emptyOutDir: true,
  },
});
