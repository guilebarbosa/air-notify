import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
	// Where `npm run dev` sends API calls: a running daemon (e.g. http://raspberrypi.local:8080)
	// or `air-notify view` on this machine. Set AIR_NOTIFY_API in the environment or in
	// web/.env.local (git-ignored).
	const env = { ...loadEnv(mode, import.meta.dirname, "AIR_NOTIFY_"), ...process.env };
	const api = env.AIR_NOTIFY_API ?? "http://localhost:8080";

	return {
		plugins: [svelte()],
		build: {
			// Served by viewer.py and committed, so deployments only need `git pull`, not Node.
			outDir: "../src/air_notify/static",
			emptyOutDir: true,
		},
		server: {
			proxy: { "/api": { target: api, changeOrigin: true } },
		},
	};
});
