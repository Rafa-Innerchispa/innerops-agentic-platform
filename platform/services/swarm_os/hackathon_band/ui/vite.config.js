import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5190,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8200",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8200",
        ws: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 5190,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8200",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8200",
        ws: true,
      },
    },
  },
});
