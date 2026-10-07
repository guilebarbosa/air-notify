<script lang="ts">
	// The airNotify lockup (mark + wordmark), inline so the wordmark uses the bundled Lexend font.
	// From the designer's airnotify-lockup.svg, with its viewBox trimmed to the ink (2-unit margin).
	interface Props {
		class?: string; // size it with a height class, e.g. "h-10 w-auto"
	}

	let { class: className = "" }: Props = $props();

	// Unique per instance: the desktop panel and the mobile footer each have a logo, and a
	// gradient defined inside a hidden copy wouldn't render for the visible one.
	const uid = $props.id();
	const gradient = `logo-gradient-${uid}`;
</script>

<svg class={className} viewBox="2 2 603.44 129" role="img" aria-label="airNotify" xmlns="http://www.w3.org/2000/svg">
	<svg x="0" y="0" width="300.53" height="133" viewBox="-7.53 13.5 300.53 133">
		<defs>
			<linearGradient id={gradient} gradientUnits="userSpaceOnUse" x1="23.98" y1="0" x2="267" y2="0">
				<stop offset="0" stop-color="#FF9C4C" />
				<stop offset="1" stop-color="#B93636" />
			</linearGradient>
		</defs>
		<path
			d="M23.98 114.99L42.77 44.13A19 19 0 0 1 79.50 44.13L98.52 115.87A19 19 0 0 0 135.25 115.87L154.27 44.13A19 19 0 0 1 191.00 44.13L210.02 115.87A19 19 0 0 0 246.75 115.87L267.00 39.50"
			fill="none"
			stroke="url(#{gradient})"
			stroke-width="25"
			stroke-linecap="round"
			stroke-linejoin="round"
		/>
		<circle cx="23.98" cy="114.99" r="21" fill="#FFFFFF" stroke="#FF9C4C" stroke-width="13.02" />
		<circle cx="267" cy="39.5" r="22" fill="#B93636" />
	</svg>
	<text x="314.53" y="95.76" font-family="Lexend, sans-serif" font-weight="600" font-size="66.5" letter-spacing="-1.5" fill="#050505">
		airNotify
	</text>
</svg>
