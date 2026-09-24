"""
LLM-judgment duplicate-capability check.

Same _call_llm-replaced-by-real-client pattern as security_check.py.
Config settled after debugging in security_check.py: temperature=0.1
(not 0.0 — degenerate repetition loops observed at temperature=0),
max_tokens=8192 (headroom for reasoning-model overhead).
"""
from dataclasses import dataclass

from src.llm.nebius_client import get_llm, invoke_json


@dataclass
class DuplicateFinding:
    module_a: str
    module_b: str
    similar: bool
    confidence: str  # "low" | "medium" | "high"
    reasoning: str


DUPLICATE_PROMPT = """You are comparing two Terraform modules to judge
whether they serve a substantially similar purpose — i.e. a team
building a new service might reasonably use either one, or might not
know both exist.

Module A: {module_a}
Description: {desc_a}
Resource types: {resources_a}

Module B: {module_b}
Description: {desc_b}
Resource types: {resources_b}

Respond ONLY with valid JSON, no other text. The "reasoning" field
must be ONE sentence, maximum 20 words:
{{"similar": true|false, "confidence": "low"|"medium"|"high", "reasoning": "one short sentence, max 20 words"}}
"""


def check_duplicate_capability(
    module_a: str, module_b: str, desc_a: str, desc_b: str,
    resources_a: list[str], resources_b: list[str],
) -> DuplicateFinding:
    llm = get_llm(max_tokens=8192, temperature=0.1, frequency_penalty=0.4)
    prompt = DUPLICATE_PROMPT.format(
        module_a=module_a, desc_a=desc_a, resources_a=resources_a,
        module_b=module_b, desc_b=desc_b, resources_b=resources_b,
    )
    result = invoke_json(llm, prompt)

    if "_error" in result:
        # Same fault-tolerance contract as security_check.py: a
        # failed/malformed LLM call must be visibly distinguishable
        # from a genuine "not similar" judgment, not silently
        # defaulted to false.
        return DuplicateFinding(
            module_a=module_a,
            module_b=module_b,
            similar=False,
            confidence="unknown",
            reasoning=f"LLM_CALL_FAILED: {result['_error']}",
        )

    return DuplicateFinding(
        module_a=module_a,
        module_b=module_b,
        similar=result.get("similar", False),
        confidence=result.get("confidence", "low"),
        reasoning=result.get("reasoning", ""),
    )