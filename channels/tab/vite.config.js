import { defineConfig } from "vite";
export default defineConfig({
  build: {
    rollupOptions: {
      input: { host: "index.html", sandbox: "sandbox.html" },
    },
  },
});
