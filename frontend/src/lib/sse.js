export function openRunStream(runId, handlers) {
  const source = new EventSource(`/api/runs/${runId}/stream`);

  source.addEventListener("delta", (event) => {
    handlers.onDelta?.(JSON.parse(event.data));
  });

  source.addEventListener("provider_done", (event) => {
    handlers.onProviderDone?.(JSON.parse(event.data));
  });

  source.addEventListener("error", (event) => {
    if (event.data) {
      handlers.onError?.(JSON.parse(event.data));
    } else {
      handlers.onError?.({ message: "Stream connection failed." });
    }
  });

  source.addEventListener("run_done", () => {
    handlers.onRunDone?.();
    source.close();
  });

  return source;
}
