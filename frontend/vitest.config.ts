import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Same "@/..." alias as tsconfig.json, so tests import modules the way the app does.
export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  // tsconfig keeps jsx "preserve" for Next; tests that render a component need the automatic runtime
  oxc: { jsx: { runtime: "automatic" } },
  test: { include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
});
