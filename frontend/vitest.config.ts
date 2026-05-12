import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@prosper/ui": path.resolve(__dirname, "../packages/ui/src/index.ts"),
      "@prosper/types": path.resolve(__dirname, "../packages/types/src/index.ts"),
    },
  },
});
