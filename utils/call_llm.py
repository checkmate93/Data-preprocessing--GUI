import asyncio
import logging
import os

import yaml

# Learn more about calling the LLM: https://the-pocket.github.io/PocketFlow/utility_function/llm.html
logger = logging.getLogger(__name__)


def call_llm(prompt, response_schema=None):
    """Call the chat model.

    Input: prompt (str), response_schema (dict, optional)
    Output: response text (str), or a dict when response_schema is set
    Necessity: SchemaAdvisorNode uses this to propose a cleaning_config.
    Failures propagate so the Node retry mechanism can run again.
    """
    logger.info("LLM prompt (%s chars)", len(prompt))
    from openai import OpenAI

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "your-api-key"))
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    user_prompt = prompt
    if response_schema is not None:
        schema_text = yaml.safe_dump(response_schema, sort_keys=False)
        user_prompt = (
            f"{prompt}\n\n"
            "Return one YAML mapping and nothing else. "
            "Use exactly these keys:\n"
            f"{schema_text}\n"
            "Wrap the mapping in ```yaml fences."
        )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = response.choices[0].message.content
    logger.info("LLM response (%s chars)", len(text or ""))
    if response_schema is None:
        return text

    parsed = _parse_yaml_mapping(text)
    missing = [key for key in response_schema if key not in parsed]
    if missing:
        raise ValueError(f"LLM response is missing keys: {missing}")
    return parsed


async def call_llm_async(prompt, response_schema=None):
    """Async wrapper for FastAPI nodes. Runs the sync client off the event loop."""
    return await asyncio.to_thread(call_llm, prompt, response_schema)


def _parse_yaml_mapping(text):
    if not text or not str(text).strip():
        raise ValueError("LLM returned an empty response")
    body = str(text)
    if "```" in body:
        fence = "```yaml" if "```yaml" in body else "```"
        body = body.split(fence, 1)[1].split("```", 1)[0]
    parsed = yaml.safe_load(body.strip())
    if not isinstance(parsed, dict):
        raise ValueError("Expected a YAML mapping from the LLM")
    return parsed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(call_llm("In one sentence, what is a train/test split?"))
