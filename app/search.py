"""
Hybrid search: combines Hansard API keyword search with local semantic re-ranking.

Strategy:
1. Use the Hansard API's searchTerm parameter to find contributions that
   keyword-match the topic (high recall, noisy ranking)
2. Embed those results locally and re-rank by semantic similarity to the
   query (better ranking, filters irrelevant noise)

This avoids the failure mode where pure semantic search over ALL speeches
returns garbage because the model can't distinguish "relevant" from
"slightly less irrelevant" when scores cluster around 0.55-0.60.
"""

from __future__ import annotations

from sentence_transformers import SentenceTransformer

from app.hansard_client import get_member_contributions, Contribution
from app.semantic_search import get_model


def hybrid_search(
    member_id: int,
    topic: str,
    num_results: int = 10,
    keyword_pool_size: int = 100,
) -> dict:
    """
    Perform hybrid keyword + semantic search.

    1. Fetch up to keyword_pool_size contributions from Hansard using the
       topic as a keyword search term
    2. Embed the query and all results, then re-rank by cosine similarity
    3. Return the top num_results

    Returns a dict with results and metadata.
    """
    # Step 1: Keyword search via Hansard API
    keyword_results = get_member_contributions(
        member_id=member_id,
        search_term=topic,
        take=keyword_pool_size,
        filter_short=True,
    )

    if not keyword_results:
        return {
            "query": topic,
            "member_id": member_id,
            "keyword_matches": 0,
            "results": [],
        }

    # Step 2: Embed query and all results, compute similarities
    model = get_model()

    query_embedding = model.encode([topic], show_progress_bar=False)
    texts = [c.text for c in keyword_results]
    text_embeddings = model.encode(texts, show_progress_bar=False)

    # Cosine similarity (embeddings are already normalized for this model)
    # similarity = dot product for normalized vectors
    similarities = (text_embeddings @ query_embedding.T).flatten()

    # Step 3: Rank by semantic similarity
    scored_results = list(zip(keyword_results, similarities))
    scored_results.sort(key=lambda x: x[1], reverse=True)

    # Take top N
    top_results = scored_results[:num_results]

    output = []
    for rank, (contribution, sim) in enumerate(top_results, 1):
        output.append({
            "rank": rank,
            "similarity": round(float(sim), 4),
            "contribution_id": contribution.contribution_id,
            "text": contribution.text,
            "debate_title": contribution.debate_title,
            "debate_section_id": contribution.debate_section_id,
            "sitting_date": contribution.sitting_date,
            "house": contribution.house,
            "section": contribution.section,
            "hansard_url": contribution.hansard_url,
            "member_name": contribution.member_name,
        })

    return {
        "query": topic,
        "member_id": member_id,
        "keyword_matches": len(keyword_results),
        "results": output,
    }
