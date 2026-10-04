<script lang="ts">
	import L from "leaflet";
	import "leaflet/dist/leaflet.css";

	import { clock } from "./lib/format";
	import type { MapTiles, Point, Zone } from "./lib/types";

	interface Props {
		tiles: MapTiles | null; // from /api/map; nothing is drawn underneath until it arrives
		points: Point[];
		zones: Zone[];
	}

	let { tiles, points, zones }: Props = $props();

	let container: HTMLDivElement;
	let map = $state.raw<L.Map>();
	let layer = $state.raw<L.LayerGroup>();

	// Leaflet treats tooltip/popup strings as HTML; DOM nodes keep text from ever being parsed as markup.
	function text(value: string): HTMLElement {
		const span = document.createElement("span");
		span.textContent = value;
		return span;
	}

	$effect(() => {
		const m = L.map(container).setView([20, 0], 2);
		map = m;
		layer = L.layerGroup().addTo(m);
		return () => m.remove();
	});

	$effect(() => {
		if (!map || !tiles) return;
		const base = L.tileLayer(tiles.url, { maxZoom: tiles.maxZoom, attribution: tiles.attribution }).addTo(map);
		return () => {
			base.remove();
		};
	});

	$effect(() => {
		if (!map || !layer) return;
		layer.clearLayers();

		for (const z of zones) {
			L.circle([z.lat, z.lon], { radius: z.radius_m, color: "#2e7d32", weight: 1, fillOpacity: 0.1 })
				.bindTooltip(text(z.name))
				.addTo(layer);
		}

		const path = points.map((p): L.LatLngTuple => [p.lat, p.lon]);
		if (path.length > 1) L.polyline(path, { color: "#1565c0", weight: 2, opacity: 0.6 }).addTo(layer);

		points.forEach((p, i) => {
			const last = i === points.length - 1;
			L.circle([p.lat, p.lon], { radius: p.acc, stroke: false, fillOpacity: 0.08 }).addTo(layer!);
			L.circleMarker([p.lat, p.lon], {
				radius: last ? 7 : 5,
				weight: 1,
				color: "#fff",
				fillColor: last ? "#c62828" : "#1565c0",
				fillOpacity: 1,
			})
				.bindPopup(text(`${clock(p.t)} · ±${p.acc} m`))
				.addTo(layer!);
		});

		if (path.length) map.fitBounds(path, { padding: [30, 30], maxZoom: 17 });
	});
</script>

<div bind:this={container}></div>

<style>
	div {
		height: 100%;
	}
</style>
