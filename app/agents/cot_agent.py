"""
COT (Chain-of-Thought) Agent — iterative reasoning with self-reflection.

Inspired by: github.com/BaoBao112233/Plan-Agent-with-Meta-Agent

The COT Agent works by looping through three options until it reaches a
final answer or exhausts its iteration budget:

  Option 1 – Reason      : think + observe one step of the problem.
  Option 2 – Reflection  : critically assess the current reasoning
                            chain and correct any errors or hallucinations.
  Option 3 – Answer      : produce the final answer.

Interaction pattern (stateless, pure-async):
    cot = COTAgent()
    result = await cot.reason_through(task="...", context="...")
    print(result.final_answer)
    print(result.reasoning_trace)   # full step-by-step log
"""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from app.ai_gateway import ai_gateway

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Data containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class COTStep:
    """One iteration in the reasoning loop."""
    iteration: int
    route: str                  # "reason" | "reflection" | "answer"
    thought: Optional[str]
    observation: Optional[str]
    reflection: Optional[str]
    final_answer: Optional[str]
    raw_response: str


@dataclass
class COTResult:
    """Final result returned by COTAgent.reason_through()."""
    final_answer: str
    reasoning_trace: List[COTStep]
    iterations_used: int
    total_time_ms: float
    converged: bool             # True = reached Answer; False = hit max_iterations


# ─────────────────────────────────────────────────────────────────────────────
# Prompt template (adapted from BaoBao112233/Plan-Agent-with-Meta-Agent)
# ─────────────────────────────────────────────────────────────────────────────

COT_SYSTEM_PROMPT = """### COT Agent (Chain-of-Thought)

You are a COT Agent responsible for solving tasks iteratively using a
chain-of-thought approach. Work through one step at a time, reflect on
your progress, and deliver a final answer once you are confident.

**Agent Name:** {name}
**Agent Description:** {description}
**Instructions:** {instructions}

---

### Option 1 – Reasoning and Observation
Use this when you have NOT yet reached the final answer.

<Option>
  <Route>Reason</Route>
  <Thought>Reason about the next step of the task</Thought>
  <Observation>The result or conclusion from that reasoning step</Observation>
</Option>

---

### Option 2 – Reflection and Self-Assessment
Use this AFTER Option 1 to check your reasoning. If errors or
inconsistencies are found, note them so the next Reason step corrects them.

<Option>
  <Route>Reflection</Route>
  <Thought>Reflect on the progress so far</Thought>
  <Reflection>Assess correctness; note any errors, gaps, or hallucinations
  and how to fix them in the next step</Reflection>
</Option>

---

### Option 3 – Final Answer
Use this ONLY when you are confident you have the complete answer.

<Option>
  <Route>Answer</Route>
  <Thought>Final summary thought</Thought>
  <Final-Answer>The complete, correct answer to the original task</Final-Answer>
</Option>

---

### Procedure
1. Use **Option 1** to reason step-by-step through the task.
2. After each reasoning step use **Option 2** to reflect and self-correct.
3. Repeat Options 1 and 2 until you have sufficient information.
4. When confident, use **Option 3** to deliver the final answer.
5. You MUST NOT ask the user for clarification. Solve the task on your own.

NOTE: Respond ONLY with one Option block per turn. No extra text outside \
the <Option> tags.
"""


# ─────────────────────────────────────────────────────────────────────────────
# COT Agent
# ─────────────────────────────────────────────────────────────────────────────

class COTAgent:
    """
    Chain-of-Thought Agent that reasons iteratively before answering.

    Usage
    -----
    result = await cot_agent.reason_through(
        task="Generate an efficient SQL query for: How many trips yesterday?",
        context="Available tables: trip_metrics_daily, trips ...",
        name="SQL Reasoning Agent",
        description="Reasons about the optimal SQL structure",
        instructions=["Prefer aggregated tables", "Add date filters"],
        max_iterations=6,
    )
    print(result.final_answer)
    """

    async def reason_through(
        self,
        task: str,
        context: str = "",
        name: str = "COT Agent",
        description: str = "A chain-of-thought reasoning agent",
        instructions: List[str] = None,
        max_iterations: int = 6,
        temperature: float = 0.3,
    ) -> COTResult:
        """
        Run the Reason → Reflection → Answer loop.

        Parameters
        ----------
        task            : The specific task to reason through.
        context         : Optional background context (metadata, schema, etc.).
        name            : Agent identity shown in the system prompt.
        description     : Agent purpose shown in the system prompt.
        instructions    : Optional ordered list of constraints / guidelines.
        max_iterations  : Hard cap on LLM calls (safety against infinite loops).
        temperature     : LLM temperature (lower = more deterministic reasoning).

        Returns
        -------
        COTResult with `final_answer`, `reasoning_trace`, and telemetry.
        """
        start_time = time.time()
        instructions_str = (
            "\n".join(f"{i+1}. {inst}" for i, inst in enumerate(instructions))
            if instructions else "None — use your best judgment."
        )

        system_prompt = COT_SYSTEM_PROMPT.format(
            name=name,
            description=description,
            instructions=instructions_str,
        )

        # Build initial user prompt
        history: List[str] = []
        initial_turn = (
            f"Task: {task}"
            + (f"\n\nContext:\n{context}" if context else "")
        )
        history.append(f"[User]\n{initial_turn}")

        steps: List[COTStep] = []
        iteration = 0
        converged = False
        final_answer = "No answer reached within iteration limit."

        logger.info(
            f"[COTAgent] Starting reasoning: name={name!r} "
            f"max_iter={max_iterations}"
        )

        while iteration < max_iterations:
            iteration += 1

            # Assemble the full conversation as a single prompt
            full_prompt = "\n\n".join(history)
            full_prompt += "\n\n[Assistant]"

            try:
                ai_result = await ai_gateway.generate(
                    prompt=full_prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=800,
                )
                raw = ai_result.get("text", "").strip()
            except Exception as e:
                logger.error(f"[COTAgent] iter={iteration} LLM call failed: {e}")
                break

            # Parse the XML response
            parsed = _parse_cot_response(raw)
            route = (parsed.get("Route") or "reason").lower()

            step = COTStep(
                iteration=iteration,
                route=route,
                thought=parsed.get("Thought"),
                observation=parsed.get("Observation"),
                reflection=parsed.get("Reflection"),
                final_answer=parsed.get("Final Answer"),
                raw_response=raw,
            )
            steps.append(step)

            logger.debug(
                f"[COTAgent] iter={iteration} route={route} "
                f"thought={str(parsed.get('Thought', ''))[:80]!r}"
            )

            # Feed the assistant response back into history
            history.append(f"[Assistant]\n{raw}")

            if route == "answer":
                final_answer = parsed.get("Final Answer") or raw
                converged = True
                logger.info(
                    f"[COTAgent] Converged at iteration {iteration}: "
                    f"{str(final_answer)[:120]!r}"
                )
                break

            # Add an implicit user "continue" nudge so the LLM knows
            # the conversation is still open
            if route == "reason":
                history.append(
                    "[User]\nContinue. Reflect on your observation above, "
                    "then either reason further or provide the Final Answer."
                )
            elif route == "reflection":
                history.append(
                    "[User]\nGood reflection. Now proceed to the next "
                    "reasoning step or, if you are confident, give the "
                    "Final Answer."
                )

        total_ms = (time.time() - start_time) * 1000

        if not converged:
            # Harvest best available answer from trace
            for step in reversed(steps):
                if step.final_answer:
                    final_answer = step.final_answer
                    break
                if step.observation:
                    final_answer = step.observation
                    break

        result = COTResult(
            final_answer=final_answer,
            reasoning_trace=steps,
            iterations_used=iteration,
            total_time_ms=total_ms,
            converged=converged,
        )

        logger.info(
            f"[COTAgent] Done: converged={converged} "
            f"iterations={iteration}/{max_iterations} "
            f"time={total_ms:.0f}ms"
        )
        return result

    def format_trace_for_context(self, result: COTResult) -> str:
        """
        Convert a COTResult's reasoning trace into a compact text block
        suitable for injection into another agent's context/prompt.
        """
        lines = ["### Chain-of-Thought Reasoning Trace\n"]
        for step in result.reasoning_trace:
            lines.append(f"**Step {step.iteration} [{step.route.upper()}]**")
            if step.thought:
                lines.append(f"- Thought: {step.thought}")
            if step.observation:
                lines.append(f"- Observation: {step.observation}")
            if step.reflection:
                lines.append(f"- Reflection: {step.reflection}")
            if step.final_answer:
                lines.append(f"- Answer: {step.final_answer}")
            lines.append("")
        lines.append(f"**Final Answer:** {result.final_answer}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# XML parser (adapted from BaoBao112233/Plan-Agent-with-Meta-Agent cot/utils.py)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_cot_response(xml_output: str) -> Dict[str, Optional[str]]:
    """
    Extract structured fields from the LLM's XML-tagged Option block.

    Handles messy output: strips code fences, is case-insensitive,
    and tolerates missing tags gracefully.
    """
    data: Dict[str, Optional[str]] = {
        "Route":        None,
        "Thought":      None,
        "Observation":  None,
        "Reflection":   None,
        "Final Answer": None,
    }

    # Strip code fences
    clean = re.sub(r'```[a-zA-Z]*\n?', '', xml_output)
    clean = re.sub(r'```', '', clean)

    # Extract each tag
    patterns = {
        "Route":        r'<Route>\s*(.*?)\s*</Route>',
        "Thought":      r'<Thought>\s*(.*?)\s*</Thought>',
        "Observation":  r'<Observation>\s*(.*?)\s*</Observation>',
        "Reflection":   r'<Reflection>\s*(.*?)\s*</Reflection>',
        "Final Answer": r'<Final-Answer>\s*(.*?)\s*</Final-Answer>',
    }

    for key, pattern in patterns.items():
        m = re.search(pattern, clean, re.DOTALL | re.IGNORECASE)
        if m:
            data[key] = m.group(1).strip()

    # If no Route tag but Final-Answer is present → infer Answer route
    if not data["Route"] and data["Final Answer"]:
        data["Route"] = "Answer"

    # If still no Route but Observation present → infer Reason route
    if not data["Route"] and data["Observation"]:
        data["Route"] = "Reason"

    return data


# Global singleton
cot_agent = COTAgent()
