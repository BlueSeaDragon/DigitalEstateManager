import json
import os
import re

from openai import BadRequestError, OpenAI

# Point the OpenAI SDK to an Apertus API provider or self-hosted endpoint
APERTUS_API_KEY = os.getenv("APERTUS_API_KEY", "your-apertus-api-key")
APERTUS_BASE_URL = os.getenv("APERTUS_BASE_URL", "https://api.apertus.ai/v1")  # Example endpoint URL
# Model tag as named by your host, e.g. "apertus-70b-instruct" or "apertus-8b-instruct"
APERTUS_MODEL = os.getenv("APERTUS_MODEL", "apertus-70b-instruct")

# Resolve relative to this file so it works regardless of the working directory
POLICIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "provider_policies.json")

client = OpenAI(
    api_key=APERTUS_API_KEY,
    base_url=APERTUS_BASE_URL
)


def _parse_json_response(content: str) -> dict:
    """Parse model output as JSON, tolerating markdown fences or surrounding prose."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError(f"Model response did not contain JSON: {content[:200]!r}")
        return json.loads(match.group(0))


def get_cancellation_instructions(provider_name: str, mode: str, contract_details: dict):
    """
    Queries Apertus (8B or 70B parameter model) to evaluate policy rules
    and output formatted legal cancellation steps for Switzerland.
    """
    # Load knowledge base
    with open(POLICIES_PATH, "r", encoding="utf-8") as f:
        policies = json.load(f)

    provider_policy = policies.get(provider_name, {})

    system_prompt = (
        "You are a Swiss Estate Legal & Subscription Cancellation Assistant. "
        "Analyze the provided contract details and policy rules under Swiss Law, "
        "and generate step-by-step instructions and formal letter text in German. "
        "Respond with a single JSON object only, without markdown or extra text."
    )

    user_prompt = f"""
    Provider: {provider_name}
    Cancellation Mode: {mode} (during_life or after_death)
    Policy Rules: {json.dumps(provider_policy, ensure_ascii=False)}
    Contract Metadata: {json.dumps(contract_details, ensure_ascii=False)}

    Return a JSON response with:
    1. notice_period (string)
    2. required_docs (list of strings)
    3. execution_steps (list of strings)
    4. letter_body (formal legal cancellation letter text in German)
    """

    request = dict(
        model=APERTUS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2,
    )

    # Not every OpenAI-compatible host supports JSON mode; fall back to prompt-only JSON
    try:
        response = client.chat.completions.create(**request, response_format={"type": "json_object"})
    except BadRequestError:
        response = client.chat.completions.create(**request)

    return _parse_json_response(response.choices[0].message.content)
