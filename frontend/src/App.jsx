import { useEffect, useRef, useState } from "react";

import { openRunStream } from "./lib/sse";

const providerLabels = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Gemini",
};

function providerModel(health, provider) {
  if (!health) return providerLabels[provider] || "Provider";
  return health[`${provider}_model`] || providerLabels[provider] || "Provider";
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState("anthropic");
  const [answer, setAnswer] = useState("");
  const [model, setModel] = useState("");
  const [chatError, setChatError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const streamRef = useRef(null);

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
    setAnswer("");
    setModel("");
    setChatError(null);
    streamRef.current?.close();

    try {
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: trimmed, provider }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Request failed");
      }
      setModel(data.model);
      setIsStreaming(true);

      streamRef.current = openRunStream(data.run_id, data.provider, {
        onDelta: (event) => {
          setAnswer((current) => current + event.delta);
        },
        onError: (event) => {
          setChatError(event.message || "Stream failed.");
          setIsStreaming(false);
        },
        onRunDone: () => {
          setIsStreaming(false);
          setIsLoading(false);
        },
      });
    } catch (error) {
      setChatError(error.message || String(error));
      setIsLoading(false);
      setIsStreaming(false);
    }
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 px-5 py-6 sm:px-8">
        <header className="flex flex-col gap-3 border-b border-neutral-850 pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">multichat</h1>
            <p className="mt-1 text-sm text-neutral-400">
              Stage 4: provider streaming check
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
            {health && (
              <span className="text-emerald-400">
                ● connected
              </span>
            )}
          </div>
        </header>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-2 sm:max-w-xs">
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

          <label htmlFor="prompt" className="text-sm font-medium text-neutral-300">
            Prompt
          </label>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder={`Ask ${providerLabels[provider]} one question...`}
            className="min-h-32 resize-y rounded-md border border-neutral-800 bg-neutral-900 px-4 py-3 text-base text-neutral-100 outline-none transition focus:border-neutral-500"
          />
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={isLoading || isStreaming || !prompt.trim()}
              className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-neutral-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-neutral-700 disabled:text-neutral-400"
            >
              {isStreaming
                ? "Streaming..."
                : isLoading
                  ? "Starting..."
                  : `Ask ${providerLabels[provider]}`}
            </button>
          </div>
        </form>

        <section className="grid min-h-64 grid-cols-1 gap-4">
          <article className="rounded-lg border border-neutral-800 bg-neutral-900/60 p-4">
            <div className="mb-3 flex items-center justify-between gap-3 border-b border-neutral-800 pb-3">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-300">
                {providerLabels[provider]}
              </h2>
              <span className="text-xs text-neutral-500">
                {model || providerModel(health, provider)}
              </span>
            </div>

            {chatError && (
              <p className="whitespace-pre-wrap text-sm text-red-300">{chatError}</p>
            )}
            {!chatError && (isLoading || isStreaming) && !answer && (
              <p className="text-sm text-neutral-400">Waiting for stream...</p>
            )}
            {!chatError && !isLoading && !isStreaming && !answer && (
              <p className="text-sm text-neutral-500">The answer will appear here.</p>
            )}
            {answer && (
              <p className="whitespace-pre-wrap text-sm leading-6 text-neutral-100">
                {answer}
              </p>
            )}
          </article>
        </section>
      </main>
    </div>
  );
}
