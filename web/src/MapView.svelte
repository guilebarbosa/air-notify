<script lang="ts">
	// The map. Three effects below, each re-run by Svelte when what it reads changes:
	//   1. create the Leaflet map once,
	//   2. put the base map (tiles) underneath,
	//   3. draw the day's zones, path and points on top, redrawn whenever they change.
	import L from "leaflet";
	import "leaflet/dist/leaflet.css";

	import { clock } from "./lib/format";
	import type { MapTiles, Point, Zone } from "./lib/types";

	interface Props {
		tiles: MapTiles | null; // from /api/map; nothing is drawn underneath until it arrives
		points: Point[]; // the selected day's reports, oldest first
		zones: Zone[];
	}

	let { tiles, points, zones }: Props = $props();

	let container: HTMLDivElement; // the <div> below; Leaflet draws into it
	// $state.raw: effects re-run when these are assigned, but Svelte doesn't wrap the
	// Leaflet objects in its reactive proxies (Leaflet needs the real objects).
	let map = $state.raw<L.Map>();
	let layer = $state.raw<L.LayerGroup>(); // everything we draw on top of the base map

	// Leaflet treats tooltip/popup strings as HTML; DOM nodes keep text from ever being parsed as markup.
	function text(value: string): HTMLElement {
		const span = document.createElement("span");
		span.textContent = value;
		return span;
	}

	// 1. Create the map once, zoomed out on the whole world until a day is shown.
	$effect(() => {
		const m = L.map(container).setView([20, 0], 2);
		map = m;
		layer = L.layerGroup().addTo(m);
		return () => m.remove(); // cleanup when the component goes away
	});

	// 2. The base map: tile images from the provider /api/map names (OpenStreetMap, CARTO, ...).
	//    If `tiles` ever changes, the old tile layer is removed before the new one is added.
	$effect(() => {
		if (!map || !tiles) return;
		const base = L.tileLayer(tiles.url, { maxZoom: tiles.maxZoom, attribution: tiles.attribution }).addTo(map);
		return () => {
			base.remove();
		};
	});

	// 3. The overlays, redrawn from scratch whenever `points` or `zones` change (e.g. picking
	//    another day). Leaflet draws in the order layers are added, so later ones sit on top:
	//    zones, then the path, then each point's accuracy circle and dot.
	//
	//    Note the two kinds of circle: L.circle has a radius in METRES (it grows and shrinks
	//    with zoom, like a real area on the ground); L.circleMarker has a radius in PIXELS
	//    (a dot that stays the same size at any zoom).
	$effect(() => {
		if (!map || !layer) return;
		layer.clearLayers();

		// Zones: the real geofence area (radius_m), outlined in green; hover for the name.
		for (const z of zones) {
			L.circle([z.lat, z.lon], { radius: z.radius_m, color: "#7d2e32", weight: 1, fillOpacity: 0.2 })
				.bindTooltip(text(z.name))
				.addTo(layer);
		}

		// The path: a line through the points in time order.
		const path = points.map((p): L.LatLngTuple => [p.lat, p.lon]);
		if (path.length > 1) L.polyline(path, { color: "#1565c0", weight: 2, opacity: 0.6 }).addTo(layer);

		points.forEach((p, i) => {
			const isLast = i === points.length - 1;
			const previous = i > 0 ? points[i - 1] : null;
			// only display points that are not too close to the previous one
			const minDistance = 100;
			const isNearPrevious = previous ? L.latLng(p.lat, p.lon).distanceTo([previous.lat, previous.lon]) < minDistance : false;

			if (isNearPrevious) return;

			// Accuracy: the area the report could really be anywhere in (±acc metres). Each is
			// only 8% opaque, so where many reports pile up (hours at home or at Kita) they add
			// up to a darker blue patch, which is what looks like a heatmap.
			// (`layer!`: TypeScript can't tell `layer` is still set inside this callback.)
			L.circle([p.lat, p.lon], { radius: p.acc, stroke: false, fillOpacity: 0.08 }).addTo(layer!);
			// The dot itself: blue, except the day's latest report, which is bigger and red.
			L.circleMarker([p.lat, p.lon], {
				radius: isLast ? 7 : 5,
				weight: 1,
				color: "#fff",
				fillColor: isLast ? "#c62828" : "#1565c0",
				fillOpacity: 1,
			})
				.bindPopup(text(`${clock(p.t)} · ±${p.acc} m`))
				.addTo(layer!);
		});

		// Zoom to fit the day's points, but not closer than street level (17).
		if (path.length) map.fitBounds(path, { padding: [30, 30], maxZoom: 17 });
	});
</script>

<div bind:this={container}></div>

<style>
	div {
		height: 100%; /* Leaflet needs a sized container; App's <main> gives it the full height */
	}
</style>
