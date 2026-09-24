"""
Thin wrapper for getting a LangChain-compatible chat model pointed at
Nebius Token Factory's OpenAI-compatible endpoint.
"""
import json
import os
import time

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def get_llm(temperature: float = 0.0, max_tokens: int = 1024, reasoning_effort: str = "low", frequency_penalty: float = 0.4) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=os.environ["NEBIUS_BASE_URL"],
        api_key=os.environ["NEBIUS_API_KEY"],
        model=os.environ["NEBIUS_MODEL"],
        temperature=temperature,
        frequency_penalty=frequency_penalty,
        extra_body={"reasoning_effort": reasoning_effort, "max_tokens": max_tokens},
    )


def invoke_json(llm, prompt: str, max_retries: int = 3) -> dict:
    """
    Calls the LLM expecting a JSON response. Retries on: finish_reason == length,
    empty content, or invalid JSON - all treated as transient failures worth
    retrying, per known DeepSeek reasoning-model operational behavior.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        response = llm.invoke(prompt)
        finish_reason = response.response_metadata.get("finish_reason")
        content = response.content

        if finish_reason == "length" or not content.strip():
            last_error = f"attempt {attempt}: finish_reason={finish_reason}, empty_or_truncated=True"
            time.sleep(0.5)
            continue

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            last_error = f"attempt {attempt}: JSON parse error: {e}, content={content[:200]}"
            time.sleep(0.5)
            continue

    return {"_error": f"failed after {max_retries} attempts: {last_error}"}

def invoke_text(llm, prompt: str, max_retries: int = 3) -> str:
    """Same retry logic as invoke_json, but for plain text responses."""
    for attempt in range(1, max_retries + 1):
        response = llm.invoke(prompt)
        finish_reason = response.response_metadata.get("finish_reason")
        content = response.content
        if finish_reason != "length" and content.strip():
            return content.strip()
        time.sleep(0.5)
    return "[unable to generate a response after retries]"