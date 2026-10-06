<script lang="ts" module>
	/** Space (in pixels) to keep clear of overlays when zooming to the day's points. */
	export interface Padding {
		topLeft: [number, number];
		bottomRight: [number, number];
	}
</script>

<script lang="ts">
	// The map, filling the window. Three effects below, each re-run by Svelte when what it reads changes:
	//   1. create the Leaflet map once,
	//   2. put the base map (tiles) underneath,
	//   3. draw the day's zones, path and points on top, redrawn whenever they change.
	import L from "leaflet";
	import "leaflet/dist/leaflet.css";

	import { pointColor, zoneColor } from "./lib/colors";
	import { clock } from "./lib/format";
	import type { MapTiles, Point, Zone } from "./lib/types";

	interface Props {
		tiles: MapTiles | null; // from /api/map; nothing is drawn underneath until it arrives
		points: Point[]; // the selected day's reports, oldest first
		zones: Zone[];
		maxAccuracy: number; // metres; less accurate reports aren't drawn (the alerts ignore them too)
		padding: Padding; // the floating panel (desktop) or footer (mobile) covers part of the map
	}

	let { tiles, points, zones, maxAccuracy, padding }: Props = $props();

	const MIN_DISTANCE_M = 100; // a report this close to the last dot drawn doesn't get its own dot
	const LATEST_COLOR = "#dc2626"; // red: the latest dot

	/**
	 * The reports worth a dot: accurate enough, and thinned out so a long stay doesn't pile up
	 * dozens of dots. A report within MIN_DISTANCE_M of the last dot is skipped, except the
	 * newest, which replaces that dot, so the map always shows where he was last seen.
	 */
	function dotsFor(reports: Point[]): Point[] {
		// Less accurate reports can be hundreds of metres off (often a passing phone's own position
		// on the next street) and made the path zigzag.
		const accurate = reports.filter((p) => p.acc <= maxAccuracy);
		const dots: Point[] = [];
		accurate.forEach((p, i) => {
			const last = dots[dots.length - 1];
			const near = last !== undefined && L.latLng(p.lat, p.lon).distanceTo([last.lat, last.lon]) < MIN_DISTANCE_M;
			if (!near) dots.push(p);
			else if (i === accurate.length - 1) dots[dots.length - 1] = p; // the newest replaces the nearby dot
		});
		return dots;
	}

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

	// 1. Create the map once, zoomed out on the whole world until a day is shown. The zoom buttons
	//    and attribution go top right, away from the panel (left) and the mobile footer (bottom).
	$effect(() => {
		const m = L.map(container, { zoomControl: false, attributionControl: false }).setView([20, 0], 2);
		L.control.zoom({ position: "topright" }).addTo(m);
		L.control.attribution({ position: "topright" }).addTo(m);
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

		// Zones: the real geofence area (radius_m), each in its own colour; hover for the name.
		zones.forEach((z, i) => {
			const color = zoneColor(i);
			L.circle([z.lat, z.lon], { radius: z.radius_m, color, weight: 1, fillOpacity: 0.2 })
				.bindTooltip(text(z.name))
				.addTo(layer!);
		});

		const dots = dotsFor(points);

		// The path: a line through the dots in time order.
		const path = dots.map((p): L.LatLngTuple => [p.lat, p.lon]);
		if (path.length > 1) L.polyline(path, { color: "#1e40af", weight: 2, opacity: 0.4 }).addTo(layer);

		// Colour by order: the first dot is light blue, the last dark blue, and each one in between
		// a step darker, so older and newer dots are easy to tell apart.
		dots.forEach((p, i) => {
			const isLast = i === dots.length - 1;
			const color = pointColor(dots.length > 1 ? i / (dots.length - 1) : 1);
			// Accuracy: the area the report could really be anywhere in (±acc metres). Each is
			// only 8% opaque, so where several overlap they add up to a darker patch.
			// (`layer!`: TypeScript can't tell `layer` is still set inside this callback.)
			L.circle([p.lat, p.lon], { radius: p.acc, stroke: false, fillColor: color, fillOpacity: 0.08 }).addTo(layer!);
			// The dot itself, in its colour. The latest is red and a bit bigger, so where he was
			// last seen stands out.
			const dot = L.circleMarker([p.lat, p.lon], {
				radius: isLast ? 8 : 5,
				weight: isLast ? 2 : 1,
				color: "#fff",
				fillColor: isLast ? LATEST_COLOR : color,
				fillOpacity: 1,
			})
				.bindPopup(text(`${clock(p.t)} · ±${p.acc} m`))
				.addTo(layer!);
			if (isLast) dot.bringToFront(); // never hidden under an older dot
		});

		// Zoom to fit the day's dots, clear of the panel/footer, but not closer than street level (17).
		if (path.length) {
			map.fitBounds(path, { paddingTopLeft: padding.topLeft, paddingBottomRight: padding.bottomRight, maxZoom: 17 });
		}
	});
</script>

<div bind:this={container}></div>

<style>
	div {
		position: absolute;
		inset: 0; /* the whole window; the panel and footer float on top */
	}
</style>
