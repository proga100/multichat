import { useEffect, useState } from "react";

export default function App() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState(null);
  const [chatError, setChatError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setHealthError(String(e)));
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || isLoading) return;

    setIsLoading(true);
    setAnswer(null);
    setChatError(null);

    try {
      const response = await fetch("/api/chat/once", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: trimmed }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Request failed");
      }
      setAnswer(data);
    } catch (error) {
      setChatError(error.message || String(error));
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 px-5 py-6 sm:px-8">
        <header className="flex flex-col gap-3 border-b border-neutral-850 pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">multichat</h1>
            <p className="mt-1 text-sm text-neutral-400">
              Stage 2: Claude non-streaming check
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
                ● connected · {health.anthropic_model}
              </span>
            )}
          </div>
        </header>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <label htmlFor="prompt" className="text-sm font-medium text-neutral-300">
            Prompt
          </label>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Ask Claude one question..."
            className="min-h-32 resize-y rounded-md border border-neutral-800 bg-neutral-900 px-4 py-3 text-base text-neutral-100 outline-none transition focus:border-neutral-500"
          />
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={isLoading || !prompt.trim()}
              className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-neutral-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-neutral-700 disabled:text-neutral-400"
            >
              {isLoading ? "Thinking..." : "Ask Claude"}
            </button>
          </div>
        </form>

        <section className="grid min-h-64 grid-cols-1 gap-4">
          <article className="rounded-lg border border-neutral-800 bg-neutral-900/60 p-4">
            <div className="mb-3 flex items-center justify-between gap-3 border-b border-neutral-800 pb-3">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-300">
                Anthropic
              </h2>
              <span className="text-xs text-neutral-500">
                {answer?.model || health?.anthropic_model || "Claude"}
              </span>
            </div>

            {chatError && (
              <p className="whitespace-pre-wrap text-sm text-red-300">{chatError}</p>
            )}
            {!chatError && isLoading && (
              <p className="text-sm text-neutral-400">Waiting for full response...</p>
            )}
            {!chatError && !isLoading && !answer && (
              <p className="text-sm text-neutral-500">The answer will appear here.</p>
            )}
            {answer && (
              <p className="whitespace-pre-wrap text-sm leading-6 text-neutral-100">
                {answer.content}
              </p>
            )}
          </article>
        </section>
      </main>
    </div>
  );
}
