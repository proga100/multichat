import { useEffect, useRef, useState } from "react";

import { openRunStream } from "./lib/sse";

const providerOrder = ["anthropic", "openai", "gemini"];

const providerLabels = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Gemini",
};

function createColumns() {
  return Object.fromEntries(
    providerOrder.map((provider) => [
      provider,
      {
        content: "",
        error: null,
        done: false,
        model: "",
        fallbackProvider: null,
        fallbackReason: null,
      },
    ]),
  );
}

function providerModel(health, provider) {
  if (!health) return providerLabels[provider] || "Provider";
  return health[`${provider}_model`] || providerLabels[provider] || "Provider";
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState("compare");
  const [provider, setProvider] = useState("anthropic");
  const [columns, setColumns] = useState(createColumns);
  const [runError, setRunError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const streamRef = useRef(null);

  const activeProviders = mode === "compare" ? providerOrder : [provider];

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setHealthError(String(e)));
  }, []);

  useEffect(() => {
    return () => streamRef.current?.close();
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || isLoading || isStreaming) return;

    setIsLoading(true);
    setIsStreaming(false);
    setColumns(createColumns());
    setRunError(null);
    streamRef.current?.close();

    try {
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: trimmed, mode, provider }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Request failed");
      }

      setColumns((current) => {
        const next = { ...current };
        for (const item of data.providers || []) {
          next[item.provider] = {
            ...next[item.provider],
            model: item.model,
          };
        }
        return next;
      });
      setIsStreaming(true);

      streamRef.current = openRunStream(
        data.run_id,
        { mode: data.mode, provider: data.provider },
        {
          onDelta: (event) => {
            setColumns((current) => ({
              ...current,
              [event.provider]: {
                ...current[event.provider],
                content: current[event.provider].content + event.delta,
                fallbackProvider:
                  event.fallback_provider ||
                  current[event.provider].fallbackProvider,
              },
            }));
          },
          onFallbackStart: (event) => {
            setColumns((current) => ({
              ...current,
              [event.provider]: {
                ...current[event.provider],
                fallbackProvider: event.fallback_provider,
                fallbackReason: event.message,
              },
            }));
          },
          onError: (event) => {
            setColumns((current) => ({
              ...current,
              [event.provider]: {
                ...current[event.provider],
                error: event.message || "Stream failed.",
                done: true,
              },
            }));
          },
          onProviderDone: (event) => {
            setColumns((current) => ({
              ...current,
              [event.provider]: {
                ...current[event.provider],
                done: true,
              },
            }));
          },
          onRunDone: () => {
            setIsStreaming(false);
            setIsLoading(false);
          },
        },
      );
    } catch (error) {
      setRunError(error.message || String(error));
      setIsLoading(false);
      setIsStreaming(false);
    }
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-6 px-5 py-6 sm:px-8">
        <header className="flex flex-col gap-3 border-b border-neutral-800 pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">multichat</h1>
            <p className="mt-1 text-sm text-neutral-400">
              Stage 5: compare mode
            </p>
          </div>

          <div className="rounded-md border border-neutral-800 px-3 py-2 text-sm">
            {healthError && (
              <span className="text-red-400">
                Backend offline ({healthError})
              </span>
            )}
            {!healthError && !health && (
              <span className="text-neutral-400">Checking backend...</span>
            )}
            {health && <span className="text-emerald-400">● connected</span>}
          </div>
        </header>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,220px)_minmax(0,220px)]">
            <div className="flex flex-col gap-2">
              <label htmlFor="mode" className="text-sm font-medium text-neutral-300">
                Mode
              </label>
              <select
                id="mode"
                value={mode}
                onChange={(event) => setMode(event.target.value)}
                disabled={isLoading || isStreaming}
                className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 outline-none transition focus:border-neutral-500 disabled:cursor-not-allowed disabled:text-neutral-500"
              >
                <option value="compare">Compare</option>
                <option value="single">Single provider</option>
              </select>
            </div>

            {mode === "single" && (
              <div className="flex flex-col gap-2">
                <label htmlFor="provider" className="text-sm font-medium text-neutral-300">
                  Provider
                </label>
                <select
                  id="provider"
                  value={provider}
                  onChange={(event) => setProvider(event.target.value)}
                  disabled={isLoading || isStreaming}
                  className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 outline-none transition focus:border-neutral-500 disabled:cursor-not-allowed disabled:text-neutral-500"
                >
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini</option>
                </select>
              </div>
            )}
          </div>

          <label htmlFor="prompt" className="text-sm font-medium text-neutral-300">
            Prompt
          </label>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={
              mode === "compare"
                ? "Ask all three providers one question..."
                : `Ask ${providerLabels[provider]} one question...`
            }
            className="min-h-32 resize-y rounded-md border border-neutral-800 bg-neutral-900 px-4 py-3 text-base text-neutral-100 outline-none transition focus:border-neutral-500"
          />
          <div className="flex items-center justify-between gap-3">
            {runError ? (
              <p className="text-sm text-red-300">{runError}</p>
            ) : (
              <span className="text-sm text-neutral-500">
                {isStreaming ? "Streaming responses..." : "Ready"}
              </span>
            )}
            <button
              type="submit"
              disabled={isLoading || isStreaming || !prompt.trim()}
              className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-neutral-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-neutral-700 disabled:text-neutral-400"
            >
              {isStreaming
                ? "Streaming..."
                : isLoading
                  ? "Starting..."
                  : mode === "compare"
                    ? "Compare"
                    : `Ask ${providerLabels[provider]}`}
            </button>
          </div>
        </form>

        <section className="grid min-h-64 grid-cols-1 gap-4 lg:grid-cols-3">
          {activeProviders.map((providerName) => {
            const column = columns[providerName];
            const hasContent = Boolean(column.content);
            return (
              <article
                key={providerName}
                className="min-h-64 rounded-lg border border-neutral-800 bg-neutral-900/60 p-4"
              >
                <div className="mb-3 flex items-center justify-between gap-3 border-b border-neutral-800 pb-3">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-300">
                    {providerLabels[providerName]}
                  </h2>
                  <span className="text-xs text-neutral-500">
                    {column.model || providerModel(health, providerName)}
                  </span>
                </div>

                {column.fallbackProvider && (
                  <p
                    className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-200"
                    title={column.fallbackReason || undefined}
                  >
                    via {providerLabels[column.fallbackProvider]} fallback
                  </p>
                )}

                {column.error && (
                  <p className="whitespace-pre-wrap text-sm text-red-300">
                    {column.error}
                  </p>
                )}
                {!column.error && (isLoading || isStreaming) && !hasContent && (
                  <p className="text-sm text-neutral-400">Waiting for stream...</p>
                )}
                {!column.error && !isLoading && !isStreaming && !hasContent && (
                  <p className="text-sm text-neutral-500">
                    The answer will appear here.
                  </p>
                )}
                {hasContent && (
                  <p className="whitespace-pre-wrap text-sm leading-6 text-neutral-100">
                    {column.content}
                  </p>
                )}
              </article>
            );
          })}
        </section>
      </main>
    </div>
  );
}
