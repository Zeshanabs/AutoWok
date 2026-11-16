import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    clearMocks: true,
    // The first test of a file pays for module import and jsdom start-up; 5 s is too tight on a loaded CI runner.
    testTimeout: 20000,
  },
});
