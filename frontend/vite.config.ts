import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/tunewise/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
  },
});
