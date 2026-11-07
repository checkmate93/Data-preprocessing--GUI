"""LLM wrapper: Anthropic or OpenAI, chosen by environment variables.

    ANTHROPIC_API_KEY or OPENAI_API_KEY      the key (the first one found decides the provider)
    DATAPREP_LLM_PROVIDER=anthropic|openai   optional, forces the provider
    DATAPREP_LLM_MODEL                       optional, default claude-sonnet-5-5 / gpt-4o
    DATAPREP_LLM_BASE_URL                    optional, e.g. an Azure/compatible gateway

The app passes its own base URL on purpose: a shell may already export ANTHROPIC_BASE_URL for
another tool, and the SDK would silently pick it up.
"""

import asyncio
import logging
import os

import yaml

logger = logging.getLogger(__name__)

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o"}
DEFAULT_BASE_URLS = {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com/v1"}


def llm_config():
    """Output: {"provider", "model"} or None when no key is configured."""
    provider = os.environ.get("DATAPREP_LLM_PROVIDER", "").strip().lower()
    if not provider:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            return None
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"Unknown DATAPREP_LLM_PROVIDER: {provider}")
    if not os.environ.get(f"{provider.upper()}_API_KEY"):
        return None
    return {"provider": provider, "model": os.environ.get("DATAPREP_LLM_MODEL") or DEFAULT_MODELS[provider]}


def chat(messages, system=None, max_tokens=2500):
    """Input: messages [{"role": "user"|"assistant", "content": str}], optional system prompt.
    Output: {"text", "input_tokens", "output_tokens", "model"}.
    Failures propagate so the Node retry mechanism can run again.
    """
    config = llm_config()
    if config is None:
        raise RuntimeError("Δεν έχει ρυθμιστεί LLM: όρισε ANTHROPIC_API_KEY ή OPENAI_API_KEY στον server.")
    provider, model = config["provider"], config["model"]
    base_url = os.environ.get("DATAPREP_LLM_BASE_URL") or DEFAULT_BASE_URLS[provider]
    logger.info("LLM %s/%s: %s messages, %s chars", provider, model, len(messages), sum(len(m["content"]) for m in messages))

    if provider == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], base_url=base_url)
        kwargs = {}
        if system:  # the system prompt is identical across the agent's steps: cache it
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        response = client.messages.create(model=model, max_tokens=max_tokens, messages=messages, **kwargs)
        text = "".join(block.text for block in response.content if block.type == "text")
        u = response.usage
        cached = (getattr(u, "cache_read_input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        usage = (u.input_tokens + cached, u.output_tokens)
    else:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=base_url)
        full = ([{"role": "system", "content": system}] if system else []) + messages
        response = client.chat.completions.create(model=model, messages=full, max_tokens=max_tokens)
        text = response.choices[0].message.content or ""
        usage = (response.usage.prompt_tokens, response.usage.completion_tokens)

    logger.info("LLM response %s chars, tokens in=%s out=%s", len(text), *usage)
    return {"text": text, "input_tokens": usage[0], "output_tokens": usage[1], "model": model}


def call_llm(prompt, response_schema=None):
    """Single prompt in, text (or a YAML mapping when response_schema is given) out. Used by the v1 advisor."""
    user_prompt = prompt
    if response_schema is not None:
        schema_text = yaml.safe_dump(response_schema, sort_keys=False)
        user_prompt = (
            f"{prompt}\n\nReturn one YAML mapping and nothing else. Use exactly these keys:\n"
            f"{schema_text}\nWrap the mapping in ```yaml fences."
        )
    text = chat([{"role": "user", "content": user_prompt}])["text"]
    if response_schema is None:
        return text
    parsed = parse_yaml_block(text)
    missing = [key for key in response_schema if key not in parsed]
    if missing:
        raise ValueError(f"LLM response is missing keys: {missing}")
    return parsed


async def call_llm_async(prompt, response_schema=None):
    """Async wrapper. Runs the sync client off the event loop."""
    return await asyncio.to_thread(call_llm, prompt, response_schema)


def parse_yaml_block(text):
    """The ```yaml fenced mapping in an LLM reply (or the whole reply when there is no fence)."""
    if not text or not str(text).strip():
        raise ValueError("LLM returned an empty response")
    body = str(text)
    if "```yaml" in body:
        body = body.split("```yaml", 1)[1].split("```", 1)[0]
    elif "```" in body:
        body = body.split("```", 1)[1].split("```", 1)[0]
    parsed = yaml.safe_load(body.strip())
    if not isinstance(parsed, dict):
        raise ValueError("Expected a YAML mapping from the LLM")
    return parsed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("config:", llm_config())
    assert parse_yaml_block("x\n```yaml\naction: answer\ntext: |\n  γεια\n```") == {"action": "answer", "text": "γεια"}
    if llm_config():
        print(chat([{"role": "user", "content": "Πες «γεια» με μία λέξη."}]))
