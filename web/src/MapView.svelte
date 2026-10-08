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
	//   3. draw the day's zones, path and points on top, redrawn whenever they change, and
	//      zoom in on the latest point.
	// The map buttons (zoom, "Last location", "Whole day") are our own, in the app's style.
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
		focusLatest: boolean; // start zoomed in on the latest dot (today) rather than on the whole day
		buttonsBottom: number; // pixels the map buttons stay above (the mobile footer; 0 on desktop)
	}

	let { tiles, points, zones, maxAccuracy, padding, focusLatest, buttonsBottom }: Props = $props();

	const MIN_DISTANCE_M = 100; // a report this close to the last dot drawn doesn't get its own dot
	const LATEST_COLOR = "#b93636"; // brick (brand red): the latest dot
	const LATEST_ZOOM = 16; // a few streets around the latest dot
	const DAY_MAX_ZOOM = 17; // "Whole day": never closer than street level, even for a day spent in one place

	// The map buttons look like the date buttons (Flowbite's "alternative" style): white with a
	// light border, the brand green on hover. Stacked in groups, with a line between buttons.
	const GROUP = "flex flex-col divide-y divide-gray-200 overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xs";
	const BUTTON =
		"flex size-10 items-center justify-center text-gray-900 enabled:hover:bg-gray-100 enabled:hover:text-primary-700 " +
		"disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary-500";
	// Icons (24×24, stroked like the date arrows).
	const PLUS = "M12 5v14M5 12h14";
	const MINUS = "M5 12h14";
	const PIN = "M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11Zm0-8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z";
	const FRAME = "M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"; // four corners: the whole day

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

	/** The first zone a point is inside, if any. */
	function zoneAt(p: Point): Zone | undefined {
		return zones.find((z) =>
			"outline" in z
				? insideOutline(p, z.outline)
				: L.latLng(p.lat, p.lon).distanceTo([z.lat, z.lon]) <= z.radius_m,
		);
	}

	/**
	 * Ray casting, like the server's check: follow a line from the point due east and count the
	 * edges it crosses; an odd count means inside. Plain lat/lon is fine for in-or-out (squashing
	 * the map sideways doesn't move a point across an edge).
	 */
	function insideOutline(p: Point, corners: [number, number][]): boolean {
		let inside = false;
		corners.forEach(([lat1, lon1], i) => {
			const [lat2, lon2] = corners[(i + 1) % corners.length]; // the last corner joins the first
			if (lat1 > p.lat !== lat2 > p.lat && lon1 + ((p.lat - lat1) * (lon2 - lon1)) / (lat2 - lat1) > p.lon) {
				inside = !inside;
			}
		});
		return inside;
	}

	let container: HTMLDivElement; // the <div> below; Leaflet draws into it
	// $state.raw: effects re-run when these are assigned, but Svelte doesn't wrap the
	// Leaflet objects in its reactive proxies (Leaflet needs the real objects).
	let map = $state.raw<L.Map>();
	let layer = $state.raw<L.LayerGroup>(); // everything we draw on top of the base map
	let path = $state.raw<L.LatLngTuple[]>([]); // the day's dots in time order, for the buttons
	let zoom = $state({ level: 2, min: 0, max: Infinity }); // to grey out + / − at the limits

	/** Zoom to fit these points in the part of the map the panel/footer don't cover. */
	function fit(points: L.LatLngTuple[], maxZoom: number) {
		// On phones the map reaches up behind the status bar (--bleed-top, app.css): keep clear of that too.
		const bleed = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--bleed-top")) || 0;
		const [left, top] = padding.topLeft;
		map?.fitBounds(points, { paddingTopLeft: [left, top + bleed], paddingBottomRight: padding.bottomRight, maxZoom });
	}

	// Leaflet treats tooltip/popup strings as HTML; DOM nodes keep text from ever being parsed as markup.
	function text(value: string): HTMLElement {
		const span = document.createElement("span");
		span.textContent = value;
		return span;
	}

	// 1. Create the map once, zoomed out on the whole world until a day is shown. Only the
	//    attribution is a Leaflet control, bottom right under our buttons.
	$effect(() => {
		const m = L.map(container, { zoomControl: false, attributionControl: false }).setView([20, 0], 2);
		L.control.attribution({ position: "bottomright" }).addTo(m);
		// The zoom limits change when the tiles arrive (they set the deepest zoom).
		const sync = () => (zoom = { level: m.getZoom(), min: m.getMinZoom(), max: m.getMaxZoom() });
		m.on("zoomend zoomlevelschange", sync);
		sync();
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

		// Zones: the real geofence area (a circle or a custom outline), each in its own colour;
		// hover for the name.
		zones.forEach((z, i) => {
			const style = { color: zoneColor(i), weight: 1, fillOpacity: 0.2 };
			const shape =
				"outline" in z
					? L.polygon(z.outline, style)
					: L.circle([z.lat, z.lon], { radius: z.radius_m, ...style });
			shape.bindTooltip(text(z.name)).addTo(layer!);
		});

		const dots = dotsFor(points);

		// The path: a line through the dots in time order.
		const line = dots.map((p): L.LatLngTuple => [p.lat, p.lon]);
		if (line.length > 1) L.polyline(line, { color: "#1e40af", weight: 2, opacity: 0.4 }).addTo(layer);

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
			if (isLast) {
				dot.bringToFront(); // never hidden under an older dot
				// Always-visible label above it: the zone it's in, or the report time outside every zone.
				dot.bindTooltip(text(zoneAt(p)?.name ?? clock(p.t)), {
					permanent: true,
					direction: "top",
					offset: [0, -10], // clear of the dot (radius 8 + border 2)
					className: "latest-label",
				});
			}
		});

		// Today: start on the latest dot, centred in the part of the map the panel/footer don't
		// cover. A past day: show all of it.
		// (`line`, not `path`: reading `path` here would re-run this effect each time it's set.)
		path = line;
		if (line.length) {
			if (focusLatest) fit([line[line.length - 1]], LATEST_ZOOM);
			else fit(line, DAY_MAX_ZOOM);
		}
	});

	function showLatest() {
		if (path.length) fit([path[path.length - 1]], LATEST_ZOOM);
	}

	function showWholeDay() {
		if (path.length) fit(path, DAY_MAX_ZOOM);
	}
</script>

{#snippet icon(d: string)}
	<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
		<path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" {d} />
	</svg>
{/snippet}

<div class="map" style:--buttons-bottom="{buttonsBottom}px">
	<div class="leaflet" bind:this={container}></div>

	<div class="buttons flex flex-col gap-2">
		<div class={GROUP}>
			<button type="button" class={BUTTON} title="Zoom in" disabled={zoom.level >= zoom.max} onclick={() => map?.zoomIn()}>
				{@render icon(PLUS)}
			</button>
			<button type="button" class={BUTTON} title="Zoom out" disabled={zoom.level <= zoom.min} onclick={() => map?.zoomOut()}>
				{@render icon(MINUS)}
			</button>
		</div>
		<div class={GROUP}>
			<button type="button" class={BUTTON} title="Last location" disabled={!path.length} onclick={showLatest}>
				{@render icon(PIN)}
			</button>
			<button type="button" class={BUTTON} title="Whole day" disabled={!path.length} onclick={showWholeDay}>
				{@render icon(FRAME)}
			</button>
		</div>
	</div>
</div>

<style>
	.map,
	.leaflet {
		position: absolute;
		inset: 0; /* the whole window; the panel and footer float on top */
	}

	.leaflet {
		top: calc(-1 * var(--bleed-top, 0px)); /* phones: also behind the status bar (app.css) */
	}

	/* Bottom right, above the attribution. Clear of the mobile footer (--buttons-bottom) and, with
	   viewport-fit=cover, of the iPhone's home bar and notch (the safe-area insets). */
	.buttons {
		position: absolute;
		z-index: 1050; /* over Leaflet's layers and controls (up to 1000), under the panel/footer (1100) */
		right: calc(env(safe-area-inset-right) + 0.75rem);
		bottom: calc(max(var(--buttons-bottom), env(safe-area-inset-bottom)) + 1.75rem);
	}

	/* Leaflet creates these elements itself, hence :global. */
	.leaflet :global(.leaflet-bottom) {
		bottom: max(var(--buttons-bottom), env(safe-area-inset-bottom));
	}

	.leaflet :global(.leaflet-right) {
		right: env(safe-area-inset-right);
	}

	.leaflet :global(.latest-label) {
		font: 600 13px system-ui;
	}
</style>
