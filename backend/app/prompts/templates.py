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
    "Answer the user's question directly and completely. Be concrete. "
    "You are one of several independent models answering in parallel; you "
    "cannot see the others yet."
)

# {others} = the other models' previous-round answers, formatted by orchestrator.
DEBATE_CRITIQUE = (
    "Here are the other models' answers to the same question:\n\n{others}\n\n"
    "Challenge their weakest points specifically. Then defend or revise your "
    "own previous answer. Be direct about where they are wrong and where they "
    "are right. Do not merely summarise — argue."
)

# {answers} = all final-round answers, formatted by orchestrator.
DEBATE_SYNTHESIS = (
    "Below are the final answers from several models that debated this "
    "question:\n\n{answers}\n\nProduce ONE combined best answer. Explicitly "
    "note: (1) where they AGREED, (2) where they DISAGREED, and (3) your final "
    "recommendation. Be decisive."
)

# --- SUPER MIND (parallel answers + one unified response) -------------------

# {answers} = all individual model answers, formatted by orchestrator.
SUPERMIND_SYNTHESIS = (
    "Below are individual answers from several AI models responding to the same "
    "user request:\n\n{answers}\n\nCreate ONE unified answer for the user. Do "
    "not mention that you are combining model outputs unless it is useful. "
    "Remove duplication, preserve the strongest ideas, call out important "
    "disagreements or uncertainty, and make the final response practical and "
    "decisive. Use clear structure when it improves readability."
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
