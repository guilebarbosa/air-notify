<script lang="ts">
	import { onMount } from "svelte";

	import CheckNow from "./CheckNow.svelte";
	import DayPicker from "./DayPicker.svelte";
	import { checkNow, getDay, getDays, getMap, getStatus } from "./lib/api";
	import type { Day, DayData, MapTiles, Status } from "./lib/types";
	import MapView from "./MapView.svelte";

	let days = $state<Day[]>([]);
	let selected = $state<string | null>(null);
	let day = $state<DayData | null>(null);
	let status = $state<Status | null>(null);
	let message = $state<string | null>(null);
	let checking = $state(false);
	let tiles = $state<MapTiles | null>(null);

	const showError = (error: unknown) => {
		console.error(error);
		message = `Error: ${error instanceof Error ? error.message : String(error)}`;
	};

	async function select(date: string) {
		selected = date;
		day = await getDay(date);
	}

	async function loadDays() {
		days = await getDays();
		// Keep the selected day if it's still recorded; otherwise show the newest.
		const keep = days.find((d) => d.date === selected)?.date ?? days[0]?.date;
		if (keep) await select(keep);
	}

	async function loadStatus() {
		status = await getStatus();
	}

	async function check() {
		checking = true;
		message = null;
		try {
			const result = await checkNow();
			await Promise.all([loadStatus(), loadDays()]);
			if (result.status !== "ok") message = result.detail;
		} catch (error) {
			showError(error);
		} finally {
			checking = false;
		}
	}

	async function loadMap() {
		tiles = await getMap();
		if (tiles.warning) message = tiles.warning;
	}

	onMount(() => {
		Promise.all([loadMap(), loadStatus(), loadDays()]).catch(showError);
	});
</script>

<nav>
	<h1>AirNotify</h1>
	<DayPicker {days} {selected} onselect={(date) => select(date).catch(showError)} />
	<CheckNow {status} {message} {checking} oncheck={check} />
</nav>
<main>
	<MapView {tiles} points={day?.points ?? []} zones={day?.zones ?? []} />
</main>

<style>
	nav {
		width: 21rem; /* fits the inline calendar */
		overflow-y: auto;
		border-right: 1px solid #ddd;
	}

	h1 {
		font-size: 3rem;
		margin: 0.75rem;
		font-weight: 900;
	}

	main {
		flex: 1;
		min-height: 0;
	}

	@media (max-width: 40rem) {
		nav {
			width: auto;
			height: 40%;
			border-right: 0;
			border-bottom: 1px solid #ddd;
		}
	}
</style>
