"""LLM integration using Google Gemini for ranking and filtering speeches."""

from __future__ import annotations

import json
import os
import logging
import time
from typing import Optional

from google import genai
from google.genai import types

from app.hansard_client import Contribution


logger = logging.getLogger(__name__)


def _get_client() -> genai.Client:
    """Get a Gemini client using the API key from environment."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY not set. Get a free key at https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=api_key)


def _call_gemini(client: genai.Client, prompt: str, max_retries: int = 2) -> str:
    """Call Gemini with automatic retry on rate limit (429) errors."""
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2000,
                ),
            )
            return response.text
        except Exception as e:
            if "429" in str(e) and attempt < max_retries:
                wait = 20 * (attempt + 1)  # 20s, then 40s
                logger.warning(f"Gemini rate limited, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                raise
    return ""  # Should not reach here


# Max speeches per Gemini call — keeps prompts within token limits
_BATCH_SIZE = 80


def _build_rank_prompt(
    speeches_text: str,
    num_speeches: int,
    topic: str,
    member_name: str,
    max_results: int,
) -> str:
    """Build the ranking prompt."""
    return f"""I have {num_speeches} parliamentary speeches by {member_name}.
I need you to identify which ones are genuinely relevant to this topic: "{topic}"

Here are the speeches:
{speeches_text}

Instructions:
- Only include speeches that are GENUINELY and DIRECTLY about "{topic}"
- Do NOT include speeches that merely mention a related word in passing or in an unrelated context
- A speech about general government spending is NOT about "{topic}" unless it specifically discusses "{topic}"
- Rank the relevant ones from most relevant to least relevant
- Return at most {max_results} results
- If none are relevant, return an empty list

Return ONLY valid JSON in this exact format, no other text:
{{"results": [
  {{"speech_index": 0, "relevance": "brief explanation of why this is relevant"}},
  {{"speech_index": 3, "relevance": "brief explanation"}}
]}}"""


def _parse_rank_response(raw: str) -> list[dict]:
    """Parse a ranking response from Gemini."""
    try:
        response_text = raw.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0]
        data = json.loads(response_text)
        return data.get("results", [])
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error(f"Failed to parse Gemini response: {e}\nResponse: {raw}")
        return []


def rank_contributions(
    contributions: list[Contribution],
    topic: str,
    member_name: str,
    max_results: int = 10,
) -> list[dict]:
    """
    Use Gemini to rank contributions by relevance to a topic.

    For large sets of contributions, processes in batches to stay within
    token limits, then returns the top results across all batches.
    """
    if not contributions:
        return []

    client = _get_client()

    # Split into batches
    batches = []
    for start in range(0, len(contributions), _BATCH_SIZE):
        batches.append(contributions[start : start + _BATCH_SIZE])

    # Process each batch — collect all candidates with their original index
    all_candidates = []

    for batch_idx, batch in enumerate(batches):
        offset = batch_idx * _BATCH_SIZE

        speeches_text = ""
        for i, c in enumerate(batch):
            date = c.sitting_date.split("T")[0] if c.sitting_date else "Unknown"
            text = c.text[:1000] if len(c.text) > 1000 else c.text
            speeches_text += f"\n--- SPEECH {i} ---\nDate: {date}\nDebate: {c.debate_title}\nText: {text}\n"

        prompt = _build_rank_prompt(speeches_text, len(batch), topic, member_name, max_results)
        raw = _call_gemini(client, prompt)
        results = _parse_rank_response(raw)

        for item in results:
            idx = item.get("speech_index")
            if idx is not None and 0 <= idx < len(batch):
                all_candidates.append({
                    "original_index": offset + idx,
                    "relevance": item.get("relevance", ""),
                })

    # Map back to contributions and assign final ranks
    output = []
    for rank, candidate in enumerate(all_candidates[:max_results], 1):
        c = contributions[candidate["original_index"]]
        output.append({
            "rank": rank,
            "contribution_id": c.contribution_id,
            "text": c.text,
            "debate_title": c.debate_title,
            "debate_section_id": c.debate_section_id,
            "sitting_date": c.sitting_date,
            "house": c.house,
            "section": c.section,
            "hansard_url": c.hansard_url,
            "member_name": c.member_name,
            "relevance": candidate["relevance"],
        })

    return output


def filter_contributions_by_topics(
    contributions: list[Contribution],
    topics: list[str],
    member_name: str,
) -> list[dict]:
    """
    Use Gemini to check if any contributions are relevant to a list of topics.
    Used by the alerts system to filter new speeches.

    Returns a list of dicts with contribution info and matched topics.
    """
    if not contributions or not topics:
        return []

    client = _get_client()

    speeches_text = ""
    for i, c in enumerate(contributions):
        date = c.sitting_date.split("T")[0] if c.sitting_date else "Unknown"
        text = c.text[:1000] if len(c.text) > 1000 else c.text
        speeches_text += f"\n--- SPEECH {i} ---\nDate: {date}\nDebate: {c.debate_title}\nText: {text}\n"

    topics_str = ", ".join(f'"{t}"' for t in topics)

    prompt = f"""I have {len(contributions)} recent parliamentary speeches by {member_name}.
Check if any of them are genuinely relevant to these topics: {topics_str}

Here are the speeches:
{speeches_text}

Instructions:
- Only include speeches that are GENUINELY about one or more of the listed topics
- Do NOT include speeches that merely mention a word in passing
- For each relevant speech, say which topic(s) it matches

Return ONLY valid JSON in this exact format, no other text:
{{"matches": [
  {{"speech_index": 0, "topics": ["topic1"], "reason": "brief explanation"}},
  {{"speech_index": 3, "topics": ["topic1", "topic2"], "reason": "brief explanation"}}
]}}

If none are relevant, return: {{"matches": []}}"""

    raw = _call_gemini(client, prompt)

    try:
        response_text = raw.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0]

        data = json.loads(response_text)
        matches = data.get("matches", [])
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error(f"Failed to parse Gemini response: {e}\nResponse: {raw}")
        return []

    output = []
    for item in matches:
        idx = item.get("speech_index")
        if idx is None or idx < 0 or idx >= len(contributions):
            continue

        c = contributions[idx]
        output.append({
            "contribution_id": c.contribution_id,
            "text": c.text,
            "debate_title": c.debate_title,
            "sitting_date": c.sitting_date,
            "house": c.house,
            "section": c.section,
            "hansard_url": c.hansard_url,
            "member_name": c.member_name,
            "matched_topics": item.get("topics", []),
            "reason": item.get("reason", ""),
        })

    return output
