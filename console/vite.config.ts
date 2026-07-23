import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  preview: { port: 4173 },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.indexOf("node_modules") === -1) return;
          if (id.indexOf("@xyflow") !== -1 || id.indexOf("@dagrejs") !== -1) return "graph";
          if (id.indexOf("framer-motion") !== -1) return "motion";
          if (id.indexOf("@radix-ui") !== -1) return "radix";
          if (id.indexOf("react") !== -1 || id.indexOf("zustand") !== -1) return "react";
        },
      },
    },
  },
});
