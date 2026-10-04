<script lang="ts">
	import Button from "flowbite-svelte/Button.svelte"; // same per-component import as the date picker

	import { clock } from "./lib/format";
	import type { Status } from "./lib/types";

	interface Props {
		status: Status | null;
		message: string | null; // overrides the summary, e.g. a check result or an error
		checking: boolean;
		oncheck: () => void;
	}

	let { status, message, checking, oncheck }: Props = $props();

	const summary = $derived.by(() => {
		if (!status?.available) return "";
		const parts: string[] = [];
		if (status.stopped) parts.push(`Stopped: ${status.stopped}`);
		if (status.last_check) parts.push(`Last check ${clock(status.last_check)}`);
		if (status.latest_report) parts.push(`latest report ${clock(status.latest_report)}`);
		return parts.join(" · ");
	});
</script>

{#if status?.available}
	<div class="check">
		<Button size="sm" onclick={oncheck} disabled={checking}>{checking ? "Checking…" : "Check now"}</Button>
	</div>
{/if}
<p>{message ?? summary}</p>

<style>
	.check {
		margin: 0 0.75rem;
	}

	p {
		margin: 0.75rem;
		color: #666;
		font-size: 12px;
	}
</style>
