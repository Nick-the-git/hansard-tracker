"""LLM integration using Google Gemini for ranking and filtering speeches."""

from __future__ import annotations

import json
import os
import logging
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


def rank_contributions(
    contributions: list[Contribution],
    topic: str,
    member_name: str,
    max_results: int = 10,
) -> list[dict]:
    """
    Use Gemini to rank contributions by relevance to a topic.

    Sends all contributions to the LLM and asks it to:
    1. Identify which ones are genuinely about the topic
    2. Rank them by relevance
    3. Drop anything irrelevant

    Returns a list of dicts with contribution_id, rank, and explanation.
    """
    if not contributions:
        return []

    client = _get_client()

    # Build the speeches list for the prompt
    speeches_text = ""
    for i, c in enumerate(contributions):
        date = c.sitting_date.split("T")[0] if c.sitting_date else "Unknown"
        # Truncate very long speeches to stay within context limits
        text = c.text[:1000] if len(c.text) > 1000 else c.text
        speeches_text += f"\n--- SPEECH {i} ---\nDate: {date}\nDebate: {c.debate_title}\nText: {text}\n"

    prompt = f"""I have {len(contributions)} parliamentary speeches by {member_name}.
I need you to identify which ones are genuinely relevant to this topic: "{topic}"

Here are the speeches:
{speeches_text}

Instructions:
- Only include speeches that are GENUINELY about or substantially related to "{topic}"
- Do NOT include speeches that merely mention a word in passing or in an unrelated context
- Rank the relevant ones from most relevant to least relevant
- Return at most {max_results} results
- If none are relevant, return an empty list

Return ONLY valid JSON in this exact format, no other text:
{{"results": [
  {{"speech_index": 0, "relevance": "brief explanation of why this is relevant"}},
  {{"speech_index": 3, "relevance": "brief explanation"}}
]}}"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=2000,
        ),
    )

    # Parse the response
    try:
        response_text = response.text.strip()
        # Handle markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0]

        data = json.loads(response_text)
        ranked_indices = data.get("results", [])
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error(f"Failed to parse Gemini response: {e}\nResponse: {response.text}")
        return []

    # Map indices back to contributions
    output = []
    for rank, item in enumerate(ranked_indices, 1):
        idx = item.get("speech_index")
        if idx is None or idx < 0 or idx >= len(contributions):
            continue

        c = contributions[idx]
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
            "relevance": item.get("relevance", ""),
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

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=2000,
        ),
    )

    try:
        response_text = response.text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0]

        data = json.loads(response_text)
        matches = data.get("matches", [])
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error(f"Failed to parse Gemini response: {e}\nResponse: {response.text}")
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
