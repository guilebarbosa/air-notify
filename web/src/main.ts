import { mount } from "svelte";

import "@fontsource/lexend/latin-600.css"; // the wordmark's font, Latin only, bundled (no requests to Google Fonts)

import App from "./App.svelte";
import "./app.css";

mount(App, { target: document.getElementById("app")! });

// Phones and tablets: keep the page scrolled by a pixel, so iPhone Safari shows the map behind the
// status bar (it only draws page content there once the page is scrolled; see app.css). The map is
// pinned to the screen, so the scroll itself isn't visible. Re-applied after the page scrolls back
// to the top, e.g. when the status bar is tapped.
if (matchMedia("(pointer: coarse)").matches) {
	const nudge = () => {
		if (window.scrollY < 1) window.scrollTo(0, 1);
	};
	let settle: ReturnType<typeof setTimeout> | undefined;
	addEventListener("load", () => requestAnimationFrame(nudge));
	addEventListener(
		"scroll",
		() => {
			clearTimeout(settle);
			settle = setTimeout(nudge, 250);
		},
		{ passive: true },
	);
}
