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

function createSynthesis() {
  return { content: "", provider: "", fallbackProvider: null, fallbackReason: null };
}

function providerModel(health, provider) {
  if (!health) return providerLabels[provider] || "Provider";
  return health[`${provider}_model`] || providerLabels[provider] || "Provider";
}

function ensureRound(rounds, roundNumber) {
  if (rounds[roundNumber]) return rounds;
  return { ...rounds, [roundNumber]: createColumns() };
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [threads, setThreads] = useState([]);
  const [selectedThread, setSelectedThread] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [mode, setMode] = useState("compare");
  const [provider, setProvider] = useState("anthropic");
  const [roundCount, setRoundCount] = useState(3);
  const [speakerOrder, setSpeakerOrder] = useState("anthropic,openai,gemini");
  const [pauseBetween, setPauseBetween] = useState(false);
  const [columns, setColumns] = useState(createColumns);
  const [debateRounds, setDebateRounds] = useState({});
  const [synthesis, setSynthesis] = useState(createSynthesis);
  const [relayTranscript, setRelayTranscript] = useState([]);
  const [runError, setRunError] = useState(null);
  const [awaitingHuman, setAwaitingHuman] = useState(null);
  const [humanSteer, setHumanSteer] = useState("");
  const [activeRun, setActiveRun] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const streamRef = useRef(null);

  const activeProviders = mode === "compare" || mode === "debate" ? providerOrder : [provider];

  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch((e) => setHealthError(String(e)));
    loadThreads();
  }, []);

  useEffect(() => {
    return () => streamRef.current?.close();
  }, []);

  function resetRunState() {
    setColumns(createColumns());
    setDebateRounds({});
    setSynthesis(createSynthesis());
    setRelayTranscript([]);
    setRunError(null);
    setAwaitingHuman(null);
    setHumanSteer("");
  }

  async function loadThreads() {
    const response = await fetch("/api/threads");
    if (response.ok) {
      setThreads(await response.json());
    }
  }

  async function loadThread(threadId) {
    const response = await fetch(`/api/threads/${threadId}`);
    if (!response.ok) return;

    const thread = await response.json();
    setSelectedThread(thread);
    setMode(thread.mode);
    setPrompt("");
    resetRunState();
  }

  function startNewThread() {
    setSelectedThread(null);
    setPrompt("");
    resetRunState();
  }

  function parsedSpeakerOrder() {
    const seen = new Set();
    const values = speakerOrder
      .split(",")
      .map((item) => item.trim())
      .filter((item) => providerOrder.includes(item) && !seen.has(item) && seen.add(item));
    return values.length ? values : providerOrder;
  }

  function startStream(run) {
    setIsStreaming(true);
    streamRef.current?.close();
    streamRef.current = openRunStream(
      run.run_id,
      {
        mode: run.mode,
        provider: run.provider,
        rounds: String(run.rounds || roundCount),
      },
      {
        onRoundStart: (event) => {
          setDebateRounds((current) => ensureRound(current, event.round));
        },
        onDelta: (event) => {
          if (run.mode === "debate") {
            setDebateRounds((current) => {
              const next = ensureRound(current, event.round);
              const column = next[event.round][event.provider];
              return {
                ...next,
                [event.round]: {
                  ...next[event.round],
                  [event.provider]: {
                    ...column,
                    content: column.content + event.delta,
                    fallbackProvider: event.fallback_provider || column.fallbackProvider,
                  },
                },
              };
            });
            return;
          }

          if (run.mode === "relay") {
            setRelayTranscript((current) => {
              const index = current.findIndex(
                (item) => item.speakerIndex === event.round - 1,
              );
              if (index === -1) return current;
              const next = [...current];
              next[index] = {
                ...next[index],
                content: next[index].content + event.delta,
                fallbackProvider: event.fallback_provider || next[index].fallbackProvider,
              };
              return next;
            });
            return;
          }

          setColumns((current) => ({
            ...current,
            [event.provider]: {
              ...current[event.provider],
              content: current[event.provider].content + event.delta,
              fallbackProvider:
                event.fallback_provider || current[event.provider].fallbackProvider,
            },
          }));
        },
        onSynthesisStart: (event) => {
          setSynthesis((current) => ({ ...current, provider: event.provider }));
        },
        onSynthesisDelta: (event) => {
          setSynthesis((current) => ({
            ...current,
            provider: event.provider,
            content: current.content + event.delta,
            fallbackProvider: event.fallback_provider || current.fallbackProvider,
          }));
        },
        onRelaySpeakerStart: (event) => {
          setRelayTranscript((current) => [
            ...current,
            {
              speakerIndex: event.speaker_index,
              provider: event.provider,
              content: "",
              fallbackProvider: null,
              fallbackReason: null,
            },
          ]);
        },
        onFallbackStart: (event) => {
          if (run.mode === "debate" && event.round <= (run.rounds || roundCount)) {
            setDebateRounds((current) => {
              const next = ensureRound(current, event.round);
              const column = next[event.round][event.provider];
              return {
                ...next,
                [event.round]: {
                  ...next[event.round],
                  [event.provider]: {
                    ...column,
                    fallbackProvider: event.fallback_provider,
                    fallbackReason: event.message,
                  },
                },
              };
            });
            return;
          }

          if (run.mode === "debate") {
            setSynthesis((current) => ({
              ...current,
              fallbackProvider: event.fallback_provider,
              fallbackReason: event.message,
            }));
            return;
          }

          if (run.mode === "relay") {
            setRelayTranscript((current) => {
              const index = current.findIndex(
                (item) => item.speakerIndex === event.round - 1,
              );
              if (index === -1) return current;
              const next = [...current];
              next[index] = {
                ...next[index],
                fallbackProvider: event.fallback_provider,
                fallbackReason: event.message,
              };
              return next;
            });
            return;
          }

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
          if (run.mode === "relay") {
            setRelayTranscript((current) => [
              ...current,
              {
                speakerIndex: event.round - 1,
                provider: event.provider,
                content: event.message || "Stream failed.",
                error: true,
              },
            ]);
            return;
          }
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
        onAwaitingHuman: (event) => {
          setAwaitingHuman(event);
        },
        onRunDone: () => {
          setIsStreaming(false);
          setIsLoading(false);
          loadThreads();
          if (run.thread_id) loadThread(run.thread_id);
        },
      },
    );
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || isLoading || isStreaming) return;

    setIsLoading(true);
    setIsStreaming(false);
    resetRunState();

    try {
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: trimmed,
          mode,
          provider,
          rounds: roundCount,
          speaker_order: parsedSpeakerOrder(),
          pause_between: pauseBetween,
          thread_id: selectedThread?.id || null,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Request failed");

      setColumns((current) => {
        const next = { ...current };
        for (const item of data.providers || []) {
          next[item.provider] = { ...next[item.provider], model: item.model };
        }
        return next;
      });
      setActiveRun(data);
      startStream(data);
    } catch (error) {
      setRunError(error.message || String(error));
      setIsLoading(false);
      setIsStreaming(false);
    }
  }

  async function handleContinue(event) {
    event.preventDefault();
    if (!activeRun || !awaitingHuman || isStreaming) return;

    setIsLoading(true);
    try {
      const response = await fetch(`/api/runs/${activeRun.run_id}/continue`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: humanSteer }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Continue failed");
      setAwaitingHuman(null);
      setHumanSteer("");
      startStream(activeRun);
    } catch (error) {
      setRunError(error.message || String(error));
      setIsLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="mx-auto grid min-h-screen w-full max-w-[1500px] gap-6 px-5 py-6 lg:grid-cols-[280px_minmax(0,1fr)] lg:px-8">
        <ThreadSidebar
          threads={threads}
          selectedThreadId={selectedThread?.id}
          onSelect={loadThread}
          onNew={startNewThread}
        />

        <main className="flex min-w-0 flex-col gap-6">
        <header className="flex flex-col gap-3 border-b border-neutral-800 pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">multichat</h1>
            <p className="mt-1 text-sm text-neutral-400">Stage 7: thread persistence and reopen</p>
          </div>

          <div className="rounded-md border border-neutral-800 px-3 py-2 text-sm">
            {healthError && <span className="text-red-400">Backend offline ({healthError})</span>}
            {!healthError && !health && <span className="text-neutral-400">Checking backend...</span>}
            {health && <span className="text-emerald-400">● connected</span>}
          </div>
        </header>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="grid gap-3 md:grid-cols-4">
            <Control label="Mode" htmlFor="mode">
              <select id="mode" value={mode} onChange={(event) => setMode(event.target.value)} disabled={isLoading || isStreaming} className="control">
                <option value="compare">Compare</option>
                <option value="single">Single provider</option>
                <option value="debate">Debate</option>
                <option value="relay">Relay</option>
              </select>
            </Control>

            {mode === "single" && (
              <ProviderSelect provider={provider} setProvider={setProvider} disabled={isLoading || isStreaming} />
            )}

            {mode === "debate" && (
              <Control label="Rounds" htmlFor="rounds">
                <input id="rounds" type="number" min="1" max="5" value={roundCount} onChange={(event) => setRoundCount(Number(event.target.value))} disabled={isLoading || isStreaming} className="control" />
              </Control>
            )}

            {mode === "relay" && (
              <>
                <Control label="Speaker order" htmlFor="speaker-order">
                  <input id="speaker-order" value={speakerOrder} onChange={(event) => setSpeakerOrder(event.target.value)} disabled={isLoading || isStreaming} className="control" />
                </Control>
                <label className="flex items-end gap-2 pb-2 text-sm text-neutral-300">
                  <input type="checkbox" checked={pauseBetween} onChange={(event) => setPauseBetween(event.target.checked)} disabled={isLoading || isStreaming} />
                  Pause between speakers
                </label>
              </>
            )}
          </div>

          <label htmlFor="prompt" className="text-sm font-medium text-neutral-300">Prompt</label>
          {selectedThread && (
            <p className="text-xs text-neutral-500">
              Continuing thread #{selectedThread.id}: {selectedThread.title}
            </p>
          )}
          <textarea
            id="prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Ask the models..."
            className="min-h-32 resize-y rounded-md border border-neutral-800 bg-neutral-900 px-4 py-3 text-base text-neutral-100 outline-none transition focus:border-neutral-500"
          />
          <div className="flex items-center justify-between gap-3">
            {runError ? <p className="text-sm text-red-300">{runError}</p> : <span className="text-sm text-neutral-500">{isStreaming ? "Streaming responses..." : awaitingHuman ? "Awaiting human steer" : "Ready"}</span>}
            <button type="submit" disabled={isLoading || isStreaming || !prompt.trim()} className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-neutral-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-neutral-700 disabled:text-neutral-400">
              {isStreaming ? "Streaming..." : isLoading ? "Starting..." : "Run"}
            </button>
          </div>
        </form>

        {awaitingHuman && (
          <form onSubmit={handleContinue} className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
            <p className="text-sm text-amber-200">Paused before {providerLabels[awaitingHuman.next_provider] || "next speaker"}.</p>
            <div className="mt-3 flex flex-col gap-3 sm:flex-row">
              <input value={humanSteer} onChange={(event) => setHumanSteer(event.target.value)} placeholder="Optional steer for the remaining speakers" className="min-w-0 flex-1 rounded-md border border-amber-500/30 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none" />
              <button type="submit" disabled={isStreaming || isLoading} className="rounded-md bg-amber-300 px-4 py-2 text-sm font-semibold text-neutral-950 disabled:bg-neutral-700 disabled:text-neutral-400">Continue</button>
            </div>
          </form>
        )}

        {mode === "debate" ? (
          <DebateView rounds={debateRounds} synthesis={synthesis} health={health} />
        ) : mode === "relay" ? (
          <RelayView transcript={relayTranscript} />
        ) : (
          <ColumnGrid providers={activeProviders} columns={columns} health={health} isLoading={isLoading} isStreaming={isStreaming} />
        )}
        {selectedThread && <HistoryView thread={selectedThread} />}
        </main>
      </div>
    </div>
  );
}

function ThreadSidebar({ threads, selectedThreadId, onSelect, onNew }) {
  return (
    <aside className="rounded-lg border border-neutral-800 bg-neutral-900/50 p-3 lg:sticky lg:top-6 lg:h-[calc(100vh-48px)] lg:overflow-y-auto">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">
          Threads
        </h2>
        <button
          type="button"
          onClick={onNew}
          className="rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500"
        >
          New
        </button>
      </div>
      <div className="space-y-2">
        {threads.length === 0 && (
          <p className="text-sm text-neutral-500">No threads yet.</p>
        )}
        {threads.map((thread) => (
          <button
            key={thread.id}
            type="button"
            onClick={() => onSelect(thread.id)}
            className={`w-full rounded-md border p-2 text-left text-sm transition ${
              selectedThreadId === thread.id
                ? "border-emerald-500/60 bg-emerald-500/10"
                : "border-neutral-800 bg-neutral-950/40 hover:border-neutral-600"
            }`}
          >
            <span className="block truncate font-medium text-neutral-200">
              {thread.title || `Thread ${thread.id}`}
            </span>
            <span className="mt-1 block truncate text-xs text-neutral-500">
              {thread.mode} · {thread.message_count} messages
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function HistoryView({ thread }) {
  return (
    <section className="space-y-3 border-t border-neutral-800 pt-5">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">
        Thread history
      </h2>
      {thread.messages.map((message) => (
        <article
          key={message.id}
          className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-3"
        >
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
            <span className="font-semibold uppercase text-neutral-300">
              {message.provider
                ? providerLabels[message.provider] || message.provider
                : message.role}
            </span>
            {message.model && <span>{message.model}</span>}
            {message.round !== null && <span>round {message.round}</span>}
          </div>
          <p className="whitespace-pre-wrap text-sm leading-6 text-neutral-100">
            {message.content}
          </p>
        </article>
      ))}
    </section>
  );
}

function Control({ label, htmlFor, children }) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={htmlFor} className="text-sm font-medium text-neutral-300">{label}</label>
      {children}
    </div>
  );
}

function ProviderSelect({ provider, setProvider, disabled }) {
  return (
    <Control label="Provider" htmlFor="provider">
      <select id="provider" value={provider} onChange={(event) => setProvider(event.target.value)} disabled={disabled} className="control">
        <option value="anthropic">Anthropic</option>
        <option value="openai">OpenAI</option>
        <option value="gemini">Gemini</option>
      </select>
    </Control>
  );
}

function ColumnGrid({ providers, columns, health, isLoading, isStreaming }) {
  return (
    <section className="grid min-h-64 grid-cols-1 gap-4 lg:grid-cols-3">
      {providers.map((providerName) => (
        <ProviderCard key={providerName} providerName={providerName} column={columns[providerName]} health={health} isLoading={isLoading} isStreaming={isStreaming} />
      ))}
    </section>
  );
}

function ProviderCard({ providerName, column, health, isLoading, isStreaming }) {
  const hasContent = Boolean(column.content);
  return (
    <article className="min-h-64 rounded-lg border border-neutral-800 bg-neutral-900/60 p-4">
      <div className="mb-3 flex items-center justify-between gap-3 border-b border-neutral-800 pb-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-300">{providerLabels[providerName]}</h2>
        <span className="text-xs text-neutral-500">{column.model || providerModel(health, providerName)}</span>
      </div>
      <FallbackBadge column={column} />
      {column.error && <p className="whitespace-pre-wrap text-sm text-red-300">{column.error}</p>}
      {!column.error && (isLoading || isStreaming) && !hasContent && <p className="text-sm text-neutral-400">Waiting for stream...</p>}
      {!column.error && !isLoading && !isStreaming && !hasContent && <p className="text-sm text-neutral-500">The answer will appear here.</p>}
      {hasContent && <p className="whitespace-pre-wrap text-sm leading-6 text-neutral-100">{column.content}</p>}
    </article>
  );
}

function FallbackBadge({ column }) {
  if (!column.fallbackProvider) return null;
  return (
    <p className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-200" title={column.fallbackReason || undefined}>
      via {providerLabels[column.fallbackProvider]} fallback
    </p>
  );
}

function DebateView({ rounds, synthesis, health }) {
  const roundKeys = Object.keys(rounds).map(Number).sort((a, b) => a - b);
  return (
    <div className="space-y-6">
      {roundKeys.map((round) => (
        <section key={round} className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">Round {round}</h2>
          <ColumnGrid providers={providerOrder} columns={rounds[round]} health={health} isLoading={false} isStreaming={false} />
        </section>
      ))}
      <section className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4">
        <div className="mb-3 flex items-center justify-between border-b border-emerald-500/20 pb-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-emerald-200">Synthesis</h2>
          <span className="text-xs text-emerald-200/70">{providerLabels[synthesis.provider] || synthesis.provider}</span>
        </div>
        <FallbackBadge column={synthesis} />
        {synthesis.content ? <p className="whitespace-pre-wrap text-sm leading-6 text-neutral-100">{synthesis.content}</p> : <p className="text-sm text-neutral-400">Synthesis will appear here.</p>}
      </section>
    </div>
  );
}

function RelayView({ transcript }) {
  return (
    <section className="space-y-3">
      {transcript.length === 0 && <p className="text-sm text-neutral-500">Relay transcript will appear here.</p>}
      {transcript.map((item, index) => (
        <article key={`${item.provider}-${item.speakerIndex}-${index}`} className="rounded-lg border border-neutral-800 bg-neutral-900/60 p-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-300">{providerLabels[item.provider] || item.provider}</h2>
          <FallbackBadge column={item} />
          <p className={`mt-3 whitespace-pre-wrap text-sm leading-6 ${item.error ? "text-red-300" : "text-neutral-100"}`}>{item.content || "Waiting for stream..."}</p>
        </article>
      ))}
    </section>
  );
}
