import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// Where `npm run dev` sends API calls: a running daemon (e.g. http://raspberrypi.local:8080)
// or `air-notify view` on this machine.
const api = process.env.AIR_NOTIFY_API ?? "http://localhost:8080";

export default defineConfig({
  plugins: [svelte()],
  build: {
    // Served by viewer.py and committed, so deployments only need `git pull`, not Node.
    outDir: "../src/air_notify/static",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": { target: api, changeOrigin: true } },
  },
});
