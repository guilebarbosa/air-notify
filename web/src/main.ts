import { mount } from "svelte";

import "@fontsource/lexend/latin-600.css"; // the wordmark's font, Latin only, bundled (no requests to Google Fonts)

import App from "./App.svelte";
import "./app.css";

mount(App, { target: document.getElementById("app")! });
