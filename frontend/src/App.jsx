import { useEffect, useRef, useState } from "react";

import { openRunStream } from "./lib/sse";

const providerOrder = ["anthropic", "openai", "gemini"];

const providerLabels = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  gemini: "Gemini",
  scribe: "Scribe",
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
        usage: null,
      },
    ]),
  );
}

function createSynthesis() {
  return {
    content: "",
    provider: "",
    fallbackProvider: null,
    fallbackReason: null,
    usage: null,
    error: null,
  };
}

function createScribe() {
  return {
    content: "",
    provider: "",
    fallbackProvider: null,
    fallbackReason: null,
    error: null,
  };
}

function providerModel(health, provider) {
  if (!health) return providerLabels[provider] || "Provider";
  return health[`${provider}_model`] || providerLabels[provider] || "Provider";
}

function ensureRound(rounds, roundNumber) {
  if (rounds[roundNumber]) return rounds;
  return { ...rounds, [roundNumber]: createColumns() };
}

function latestUserMessage(thread) {
  if (!thread?.messages?.length) return "";
  const userMessages = thread.messages.filter((message) => message.role === "user");
  return userMessages[userMessages.length - 1]?.content || "";
}

function tokenText(promptTokens, outputTokens) {
  if (promptTokens == null && outputTokens == null) return "tokens unavailable";
  const prompt = promptTokens ?? 0;
  const output = outputTokens ?? 0;
  return `${prompt} in / ${output} out`;
}

function threadTokenTotals(thread) {
  if (!thread?.messages?.length) return null;
  let prompt = 0;
  let output = 0;
  let hasTokens = false;
  for (const message of thread.messages) {
    if (message.prompt_tokens != null) {
      prompt += message.prompt_tokens;
      hasTokens = true;
    }
    if (message.output_tokens != null) {
      output += message.output_tokens;
      hasTokens = true;
    }
  }
  return hasTokens ? { prompt, output } : null;
}

function messageUsage(message) {
  if (message.prompt_tokens == null && message.output_tokens == null) return null;
  return {
    prompt_tokens: message.prompt_tokens,
    output_tokens: message.output_tokens,
  };
}

async function copyText(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Clipboard can be blocked by browser permissions; the UI stays usable.
  }
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
  const [scribe, setScribe] = useState(createScribe);
  const [supermindTab, setSupermindTab] = useState("unified");
  const [relayTranscript, setRelayTranscript] = useState([]);
  const [runError, setRunError] = useState(null);
  const [awaitingHuman, setAwaitingHuman] = useState(null);
  const [humanSteer, setHumanSteer] = useState("");
  const [activeRun, setActiveRun] = useState(null);
  const [lastPrompt, setLastPrompt] = useState("");
  const [rerunningProvider, setRerunningProvider] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const streamRef = useRef(null);

  const activeProviders =
    mode === "compare" || mode === "debate" || mode === "supermind"
      ? providerOrder
      : [provider];

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
    setScribe(createScribe());
    setSupermindTab("unified");
    setRelayTranscript([]);
    setRunError(null);
    setAwaitingHuman(null);
    setHumanSteer("");
    setRerunningProvider(null);
  }

  function hydrateThreadState(thread) {
    const nextColumns = createColumns();
    const nextRounds = {};
    const nextSynthesis = createSynthesis();
    const nextScribe = createScribe();
    const nextRelayTranscript = [];
    const assistantMessages = thread.messages.filter((message) => message.role === "assistant");

    if (thread.mode === "supermind") {
      for (const message of assistantMessages) {
        if (providerOrder.includes(message.provider) && message.round === 1) {
          nextColumns[message.provider] = {
            ...nextColumns[message.provider],
            content: message.content,
            model: message.model || "",
            done: true,
            usage: messageUsage(message),
          };
        } else if (message.provider === "scribe" || message.round === 3) {
          nextScribe.content = message.content;
          nextScribe.provider = message.provider || "scribe";
        } else if (message.round === 2) {
          nextSynthesis.content = message.content;
          nextSynthesis.provider = message.provider || "";
          nextSynthesis.usage = messageUsage(message);
        }
      }

      if (!nextSynthesis.content && assistantMessages.some((message) => message.round === 1)) {
        nextSynthesis.error =
          "Unified response was not saved for this thread. The synthesis provider likely failed during the run.";
      }
    } else if (thread.mode === "compare" || thread.mode === "single") {
      for (const message of assistantMessages) {
        if (!providerOrder.includes(message.provider)) continue;
        nextColumns[message.provider] = {
          ...nextColumns[message.provider],
          content: message.content,
          model: message.model || "",
          done: true,
          usage: messageUsage(message),
        };
      }
    } else if (thread.mode === "debate") {
      const roundCounts = assistantMessages.reduce((counts, message) => {
        if (message.round == null) return counts;
        counts[message.round] = (counts[message.round] || 0) + 1;
        return counts;
      }, {});
      const maxRound = Math.max(0, ...Object.keys(roundCounts).map(Number));

      for (const message of assistantMessages) {
        if (message.round === maxRound && roundCounts[message.round] === 1) {
          nextSynthesis.content = message.content;
          nextSynthesis.provider = message.provider || "";
          nextSynthesis.usage = messageUsage(message);
          continue;
        }

        if (!providerOrder.includes(message.provider)) continue;
        const roundNumber = message.round || 0;
        if (!nextRounds[roundNumber]) nextRounds[roundNumber] = createColumns();
        nextRounds[roundNumber][message.provider] = {
          ...nextRounds[roundNumber][message.provider],
          content: message.content,
          model: message.model || "",
          done: true,
          usage: messageUsage(message),
        };
      }
    } else if (thread.mode === "relay") {
      for (const message of assistantMessages) {
        nextRelayTranscript.push({
          speakerIndex: (message.round || nextRelayTranscript.length + 1) - 1,
          provider: message.provider,
          content: message.content,
          fallbackProvider: null,
          fallbackReason: null,
        });
      }
    }

    setColumns(nextColumns);
    setDebateRounds(nextRounds);
    setSynthesis(nextSynthesis);
    setScribe(nextScribe);
    setSupermindTab("unified");
    setRelayTranscript(nextRelayTranscript);
    setRunError(null);
    setAwaitingHuman(null);
    setHumanSteer("");
    setRerunningProvider(null);
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
    setLastPrompt(latestUserMessage(thread));
    setPrompt("");
    hydrateThreadState(thread);
  }

  function startNewThread() {
    setSelectedThread(null);
    setPrompt("");
    setLastPrompt("");
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

  function startStream(run, options = {}) {
    const targetProvider = options.targetProvider || null;
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
          if (targetProvider && event.provider !== targetProvider) return;

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
        onSynthesisDone: (event) => {
          if (!event.content) return;
          setSynthesis((current) => ({
            ...current,
            provider: event.provider || current.provider,
            content: current.content || event.content,
            error: null,
          }));
        },
        onScribeStart: (event) => {
          setScribe((current) => ({ ...current, provider: event.provider }));
        },
        onScribeDelta: (event) => {
          setScribe((current) => ({
            ...current,
            provider: event.provider,
            content: current.content + event.delta,
            fallbackProvider: event.fallback_provider || current.fallbackProvider,
          }));
        },
        onScribeDone: (event) => {
          if (!event.content) return;
          setScribe((current) => ({
            ...current,
            provider: event.provider || current.provider,
            content: current.content || event.content,
            error: null,
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
          if (targetProvider && event.provider !== targetProvider) return;

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

          if (run.mode === "supermind" && event.round === 2) {
            setSynthesis((current) => ({
              ...current,
              fallbackProvider: event.fallback_provider,
              fallbackReason: event.message,
            }));
            return;
          }

          if (run.mode === "supermind" && event.round === 3) {
            setScribe((current) => ({
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
          if (targetProvider && event.provider !== targetProvider) return;

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

          if (run.mode === "supermind" && event.round === 2) {
            setSynthesis((current) => ({
              ...current,
              provider: event.provider,
              error: event.message || "Synthesis failed.",
            }));
            return;
          }

          if (run.mode === "supermind" && event.round === 3) {
            setScribe((current) => ({
              ...current,
              provider: event.provider,
              error: event.message || "Scribe failed.",
            }));
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
          if (targetProvider && event.provider !== targetProvider) return;

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
          setRerunningProvider(null);
          loadThreads();
          if (!targetProvider && run.thread_id) loadThread(run.thread_id);
        },
      },
    );
  }

  async function createRun({ runPrompt, runMode, runProvider, attachToThread = true }) {
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: runPrompt,
        mode: runMode,
        provider: runProvider,
        rounds: roundCount,
        speaker_order: parsedSpeakerOrder(),
        pause_between: pauseBetween,
        thread_id: attachToThread ? selectedThread?.id || null : null,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Request failed");
    return data;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || isLoading || isStreaming) return;
    await submitPrompt(trimmed);
  }

  async function submitPrompt(trimmed) {
    setIsLoading(true);
    setIsStreaming(false);
    resetRunState();
    setLastPrompt(trimmed);

    try {
      const data = await createRun({
        runPrompt: trimmed,
        runMode: mode,
        runProvider: provider,
      });

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

  async function rerunProvider(providerName) {
    const runPrompt = (prompt.trim() || lastPrompt || latestUserMessage(selectedThread)).trim();
    if (!runPrompt || isLoading || isStreaming) return;

    setRunError(null);
    setIsLoading(true);
    setRerunningProvider(providerName);
    setLastPrompt(runPrompt);
    setColumns((current) => ({
      ...current,
      [providerName]: {
        ...createColumns()[providerName],
        model: current[providerName]?.model || providerModel(health, providerName),
      },
    }));

    try {
      const data = await createRun({
        runPrompt,
        runMode: "single",
        runProvider: providerName,
        attachToThread: false,
      });
      setColumns((current) => ({
        ...current,
        [providerName]: {
          ...current[providerName],
          model:
            data.providers?.find((item) => item.provider === providerName)?.model ||
            data.model ||
            current[providerName]?.model,
        },
      }));
      setActiveRun(data);
      startStream(data, { targetProvider: providerName });
    } catch (error) {
      setRunError(error.message || String(error));
      setIsLoading(false);
      setIsStreaming(false);
      setRerunningProvider(null);
    }
  }

  function editLastPrompt() {
    const value = (lastPrompt || latestUserMessage(selectedThread)).trim();
    if (value) setPrompt(value);
  }

  function rerunLastPrompt() {
    const value = (prompt.trim() || lastPrompt || latestUserMessage(selectedThread)).trim();
    if (value) {
      setPrompt(value);
      submitPrompt(value);
    }
  }

  function handlePromptKeyDown(event) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
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
            <p className="mt-1 text-sm text-neutral-400">Self-hosted AI boardroom</p>
          </div>

          <div className="rounded-md border border-neutral-800 px-3 py-2 text-sm">
            {healthError && <span className="text-red-400">Backend offline ({healthError})</span>}
            {!healthError && !health && <span className="text-neutral-400">Checking backend...</span>}
            {health && <span className="text-emerald-400">● connected</span>}
          </div>
        </header>

        <form id="run-form" onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="grid gap-3 md:grid-cols-4">
            <Control label="Mode" htmlFor="mode">
              <select id="mode" value={mode} onChange={(event) => setMode(event.target.value)} disabled={isLoading || isStreaming} className="control">
                <option value="compare">Compare</option>
                <option value="supermind">Super Mind</option>
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
            onKeyDown={handlePromptKeyDown}
            placeholder="Ask the models..."
            className="min-h-32 resize-y rounded-md border border-neutral-800 bg-neutral-900 px-4 py-3 text-base text-neutral-100 outline-none transition focus:border-neutral-500"
          />
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            {runError ? <p className="text-sm text-red-300">{runError}</p> : <span className="text-sm text-neutral-500">{isStreaming ? "Streaming responses..." : awaitingHuman ? "Awaiting human steer" : "Ready"}</span>}
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={editLastPrompt} disabled={isLoading || isStreaming || !(lastPrompt || latestUserMessage(selectedThread))} className="rounded-md border border-neutral-700 px-3 py-2 text-sm text-neutral-200 transition hover:border-neutral-500 disabled:cursor-not-allowed disabled:text-neutral-600">
                Edit last
              </button>
              <button type="button" onClick={rerunLastPrompt} disabled={isLoading || isStreaming || !(prompt.trim() || lastPrompt || latestUserMessage(selectedThread))} className="rounded-md border border-neutral-700 px-3 py-2 text-sm text-neutral-200 transition hover:border-neutral-500 disabled:cursor-not-allowed disabled:text-neutral-600">
                Rerun
              </button>
              <button type="submit" disabled={isLoading || isStreaming || !prompt.trim()} title="Run" className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-neutral-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-neutral-700 disabled:text-neutral-400">
                {isStreaming ? "Streaming..." : isLoading ? "Starting..." : "Run"}
              </button>
            </div>
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

        {mode === "supermind" ? (
          <SuperMindView
            tab={supermindTab}
            setTab={setSupermindTab}
            columns={columns}
            synthesis={synthesis}
            scribe={scribe}
            health={health}
            isLoading={isLoading}
            isStreaming={isStreaming}
            onCopy={copyText}
          />
        ) : mode === "debate" ? (
          <DebateView rounds={debateRounds} synthesis={synthesis} health={health} onCopy={copyText} />
        ) : mode === "relay" ? (
          <RelayView transcript={relayTranscript} onCopy={copyText} />
        ) : (
          <ColumnGrid
            providers={activeProviders}
            columns={columns}
            health={health}
            isLoading={isLoading}
            isStreaming={isStreaming}
            onCopy={copyText}
            onRerun={rerunProvider}
            rerunningProvider={rerunningProvider}
          />
        )}
        {selectedThread && <HistoryView thread={selectedThread} onCopy={copyText} onEditLast={editLastPrompt} onRerunLast={rerunLastPrompt} />}
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

function HistoryView({ thread, onCopy, onEditLast, onRerunLast }) {
  const totals = threadTokenTotals(thread);
  return (
    <section className="space-y-3 border-t border-neutral-800 pt-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">
            Thread history
          </h2>
          <p className="mt-1 text-xs text-neutral-500">
            {totals ? tokenText(totals.prompt, totals.output) : "tokens unavailable"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={onEditLast} className="rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500">
            Edit last
          </button>
          <button type="button" onClick={onRerunLast} className="rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500">
            Rerun
          </button>
        </div>
      </div>
      {thread.messages.map((message) => (
        <article
          key={message.id}
          className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-3"
        >
          <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
              <span className="font-semibold uppercase text-neutral-300">
                {message.provider
                  ? providerLabels[message.provider] || message.provider
                  : message.role}
              </span>
              {message.model && <span>{message.model}</span>}
              {message.round !== null && <span>round {message.round}</span>}
              <span>{tokenText(message.prompt_tokens, message.output_tokens)}</span>
            </div>
            <button type="button" onClick={() => onCopy(message.content)} disabled={!message.content} className="self-start rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500 disabled:cursor-not-allowed disabled:text-neutral-600">
              Copy
            </button>
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

function ColumnGrid({
  providers,
  columns,
  health,
  isLoading,
  isStreaming,
  onCopy,
  onRerun,
  rerunningProvider,
}) {
  return (
    <section className="grid min-h-64 grid-cols-1 gap-4 lg:grid-cols-3">
      {providers.map((providerName) => (
        <ProviderCard
          key={providerName}
          providerName={providerName}
          column={columns[providerName]}
          health={health}
          isLoading={isLoading}
          isStreaming={isStreaming}
          onCopy={onCopy}
          onRerun={onRerun}
          isRerunning={rerunningProvider === providerName}
        />
      ))}
    </section>
  );
}

function ProviderCard({
  providerName,
  column,
  health,
  isLoading,
  isStreaming,
  onCopy,
  onRerun,
  isRerunning,
}) {
  const hasContent = Boolean(column.content);
  return (
    <article className="min-h-64 rounded-lg border border-neutral-800 bg-neutral-900/60 p-4">
      <div className="mb-3 flex flex-col gap-3 border-b border-neutral-800 pb-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-300">{providerLabels[providerName]}</h2>
          <span className="text-xs text-neutral-500">{column.model || providerModel(health, providerName)}</span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs text-neutral-500">
            {column.usage ? tokenText(column.usage.prompt_tokens, column.usage.output_tokens) : "tokens unavailable"}
          </span>
          <div className="flex gap-2">
            <button type="button" onClick={() => onCopy?.(column.content)} disabled={!hasContent} className="rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500 disabled:cursor-not-allowed disabled:text-neutral-600">
              Copy
            </button>
            {onRerun && (
              <button type="button" onClick={() => onRerun(providerName)} disabled={isLoading || isStreaming} className="rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500 disabled:cursor-not-allowed disabled:text-neutral-600">
                {isRerunning ? "Rerun..." : "Rerun"}
              </button>
            )}
          </div>
        </div>
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

function SuperMindView({
  tab,
  setTab,
  columns,
  synthesis,
  scribe,
  health,
  isLoading,
  isStreaming,
  onCopy,
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-3 rounded-lg border border-violet-500/30 bg-violet-500/10 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-violet-200">
            Super Mind
          </h2>
        </div>
        <div className="grid w-full grid-cols-3 rounded-md border border-violet-500/30 bg-neutral-950/70 p-1 sm:w-auto">
          <button
            type="button"
            onClick={() => setTab("unified")}
            className={`rounded px-3 py-2 text-sm font-medium transition ${
              tab === "unified"
                ? "bg-violet-400 text-neutral-950"
                : "text-violet-100 hover:bg-violet-500/10"
            }`}
          >
            Unified
          </button>
          <button
            type="button"
            onClick={() => setTab("individual")}
            className={`rounded px-3 py-2 text-sm font-medium transition ${
              tab === "individual"
                ? "bg-violet-400 text-neutral-950"
                : "text-violet-100 hover:bg-violet-500/10"
            }`}
          >
            Individual
          </button>
          <button
            type="button"
            onClick={() => setTab("scribe")}
            className={`rounded px-3 py-2 text-sm font-medium transition ${
              tab === "scribe"
                ? "bg-violet-400 text-neutral-950"
                : "text-violet-100 hover:bg-violet-500/10"
            }`}
          >
            Scribe
          </button>
        </div>
      </div>

      {tab === "unified" ? (
        <SynthesisCard
          title="Unified Response"
          emptyText={
            isLoading || isStreaming
              ? "Reading individual responses before writing the unified answer..."
              : "The unified answer will appear here."
          }
          synthesis={synthesis}
          onCopy={onCopy}
        />
      ) : tab === "scribe" ? (
        <SynthesisCard
          title="Scribe Notes"
          emptyText={
            isLoading || isStreaming
              ? "Scribe notes will appear after the unified response."
              : "Scribe notes will appear here."
          }
          synthesis={scribe}
          onCopy={onCopy}
        />
      ) : (
        <ColumnGrid
          providers={providerOrder}
          columns={columns}
          health={health}
          isLoading={isLoading}
          isStreaming={isStreaming}
          onCopy={onCopy}
        />
      )}
    </section>
  );
}

function SynthesisCard({ title = "Synthesis", emptyText, synthesis, onCopy }) {
  return (
    <section className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4">
      <div className="mb-3 flex flex-col gap-3 border-b border-emerald-500/20 pb-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-emerald-200">
            {title}
          </h2>
          <span className="text-xs text-emerald-200/70">
            {providerLabels[synthesis.provider] || synthesis.provider || "Synthesis provider"}
          </span>
        </div>
        <button
          type="button"
          onClick={() => onCopy?.(synthesis.content)}
          disabled={!synthesis.content}
          className="rounded-md border border-emerald-500/30 px-2 py-1 text-xs text-emerald-100 hover:border-emerald-300 disabled:cursor-not-allowed disabled:text-emerald-900"
        >
          Copy
        </button>
      </div>
      <FallbackBadge column={synthesis} />
      {synthesis.error && (
        <p className="whitespace-pre-wrap text-sm text-red-300">{synthesis.error}</p>
      )}
      {!synthesis.error && synthesis.content && (
        <p className="whitespace-pre-wrap text-sm leading-6 text-neutral-100">
          {synthesis.content}
        </p>
      )}
      {!synthesis.error && !synthesis.content && (
        <p className="text-sm text-neutral-400">{emptyText || "Synthesis will appear here."}</p>
      )}
    </section>
  );
}

function DebateView({ rounds, synthesis, health, onCopy }) {
  const roundKeys = Object.keys(rounds).map(Number).sort((a, b) => a - b);
  return (
    <div className="space-y-6">
      {roundKeys.map((round) => (
        <section key={round} className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">Round {round}</h2>
          <ColumnGrid providers={providerOrder} columns={rounds[round]} health={health} isLoading={false} isStreaming={false} onCopy={onCopy} />
        </section>
      ))}
      <SynthesisCard synthesis={synthesis} onCopy={onCopy} />
    </div>
  );
}

function RelayView({ transcript, onCopy }) {
  return (
    <section className="space-y-3">
      {transcript.length === 0 && <p className="text-sm text-neutral-500">Relay transcript will appear here.</p>}
      {transcript.map((item, index) => (
        <article key={`${item.provider}-${item.speakerIndex}-${index}`} className="rounded-lg border border-neutral-800 bg-neutral-900/60 p-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-300">{providerLabels[item.provider] || item.provider}</h2>
            <button type="button" onClick={() => onCopy?.(item.content)} disabled={!item.content} className="rounded-md border border-neutral-700 px-2 py-1 text-xs text-neutral-200 hover:border-neutral-500 disabled:cursor-not-allowed disabled:text-neutral-600">
              Copy
            </button>
          </div>
          <FallbackBadge column={item} />
          <p className={`mt-3 whitespace-pre-wrap text-sm leading-6 ${item.error ? "text-red-300" : "text-neutral-100"}`}>{item.content || "Waiting for stream..."}</p>
        </article>
      ))}
    </section>
  );
}
