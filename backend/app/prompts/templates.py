"""
Mode & role prompt templates — deliberately data, not code.

The whole "many discussion modes" idea is built as: two orchestration
TOPOLOGIES (parallel rounds / sequential relay) x a swappable role-prompt
template here. So Debate, Expert, Simulation, Co-operative are mostly different
strings in this file, not different Python.

To add or tweak a mode later, edit the templates here — you should rarely need
to touch the orchestrator. `{placeholders}` are filled by the orchestrator at
run time. The actual orchestration that consumes these lands in step 6; this
file just establishes the home for them.
"""

# --- DEBATE (parallel-rounds topology) -------------------------------------

DEBATE_ROUND1 = (
    "Answer the user's question directly and concretely. Be concise: give your "
    "best answer, not an exhaustive report. Use readable Markdown with short "
    "sections or bullets. Keep the answer under 120 words unless the user "
    "explicitly asks for a long report. "
    "You are one of several independent models answering in parallel; you "
    "cannot see the others yet."
)

# {others} = the other models' previous-round answers, formatted by orchestrator.
DEBATE_CRITIQUE = (
    "Here are the other models' answers to the same question:\n\n{others}\n\n"
    "Challenge only the most important weak points. Then defend or revise your "
    "own previous answer. Be direct about where they are wrong and where they "
    "are right. Do not merely summarize. Avoid repeating earlier content. Keep "
    "each debate round under 120 words unless the user explicitly asks for a long "
    "report."
)

# {answers} = all final-round answers, formatted by orchestrator.
DEBATE_SYNTHESIS = (
    "Below are the final answers from several models that debated this "
    "question:\n\n{answers}\n\nProduce ONE combined best answer. Explicitly "
    "note: (1) where they AGREED, (2) where they DISAGREED, and (3) your final "
    "recommendation. Remove duplication and keep only the strongest points. Be "
    "decisive. Keep the synthesis under 220 words unless the user explicitly "
    "asks for a long report."
)

# --- SUPER MIND (parallel answers + one unified response) -------------------

SUPERMIND_INDIVIDUAL = (
    "Answer as one member of a multi-model panel. Be useful but compact. "
    "Prioritize quality over quantity: give the best 2-3 ideas or conclusions, "
    "not an exhaustive list. Keep the answer under 450 words unless the user "
    "explicitly asks for a long report. Use Markdown headings and bullets. "
    "If the prompt includes a URL, do not claim you visited it unless the user "
    "provided its contents; infer carefully from the prompt and say what should "
    "be verified."
)

# {answers} = all individual model answers, formatted by orchestrator.
SUPERMIND_SYNTHESIS = (
    "Below are individual answers from several AI models responding to the same "
    "user request:\n\n{answers}\n\nCreate ONE unified answer for the user. Do "
    "not mention that you are combining model outputs unless it is useful. "
    "Remove duplication and keep only the strongest points. Prefer depth on the "
    "best recommendation over many shallow options. Limit the response to: a "
    "short answer, up to 3 ranked options or conclusions, key risks/unknowns, "
    "and next actions. Keep it under 650 words unless the user explicitly asks "
    "for a long report. Use readable Markdown."
)

# {answers} = individual model answers; {unified} = the unified response.
SUPERMIND_SCRIBE = (
    "You are the scribe for a multi-AI discussion.\n\nUser request:\n{prompt}\n\n"
    "Individual answers:\n{answers}\n\nUnified response:\n{unified}\n\n"
    "Create concise, meeting-ready notes in Markdown with exactly these "
    "sections:\n\n"
    "## Decision Brief\n"
    "## Consensus\n"
    "## Disagreements / Uncertainty\n"
    "## Risks\n"
    "## Open Questions\n"
    "## Next Actions\n\n"
    "Use at most 3 bullets per section. Do not add generic process advice. If a "
    "section has nothing meaningful, write '- None surfaced.' Keep the whole "
    "scribe under 350 words."
)

# --- EXPERT (parallel topology, different role per column) ------------------
# {role} is injected per-provider, e.g. "a senior security engineer".
EXPERT_ROLE = (
    "Answer the user's question strictly from the perspective of {role}. "
    "Bring the concerns, vocabulary, and priorities that role would have."
)

# --- CO-OPERATIVE / RELAY (sequential topology) -----------------------------
# {prior} = everything said so far in the chain.
RELAY_CONTINUE = (
    "The discussion so far:\n\n{prior}\n\nBuild on this. Add what is missing, "
    "correct what is wrong, and push the answer forward. Do not just repeat "
    "what has been said."
)

# Optional human interjection marker (pausable/resumable runs).
HUMAN_INTERJECTION_PREFIX = "[The human interjected with the following steer]: "
