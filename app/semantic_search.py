"""Semantic search over Hansard contributions using embeddings + ChromaDB."""

from __future__ import annotations

import os
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer

from app.hansard_client import Contribution


# all-MiniLM-L6-v2: 80MB, fast, decent quality
# all-mpnet-base-v2: 420MB, slower, significantly better quality
# For Streamlit Cloud (1GB RAM), MiniLM is the safer choice.
MODEL_NAME = "all-MiniLM-L6-v2"

# Singleton instances
_model: Optional[SentenceTransformer] = None
_chroma_client: Optional[chromadb.PersistentClient] = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        # Use a path that works both locally and on Streamlit Cloud
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chromadb")
        os.makedirs(data_dir, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=data_dir)
    return _chroma_client


def _collection_name(member_id: int) -> str:
    """Each member gets their own collection for easy management."""
    return f"member_{member_id}"


def index_contributions(member_id: int, contributions: list[Contribution]) -> int:
    """
    Embed and store contributions in ChromaDB.
    Returns the number of new contributions indexed.
    """
    if not contributions:
        return 0

    client = get_chroma_client()
    collection = client.get_or_create_collection(
        name=_collection_name(member_id),
        metadata={"hnsw:space": "cosine"},
    )

    # Filter out already-indexed contributions
    existing_ids = set(collection.get()["ids"])
    new_contributions = [c for c in contributions if c.contribution_id not in existing_ids]

    if not new_contributions:
        return 0

    model = get_model()

    # Prepare data for ChromaDB
    ids = [c.contribution_id for c in new_contributions]
    texts = [c.text for c in new_contributions]
    metadatas = [
        {
            "member_id": c.member_id,
            "member_name": c.member_name,
            "debate_title": c.debate_title,
            "debate_section_id": c.debate_section_id,
            "sitting_date": c.sitting_date,
            "house": c.house,
            "section": c.section,
            "hansard_url": c.hansard_url,
            "text_preview": c.text[:500],
        }
        for c in new_contributions
    ]

    # Generate embeddings
    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    # Upsert into ChromaDB (handles batching internally)
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )

    return len(new_contributions)


def semantic_query(member_id: int, query: str, top_k: int = 10) -> list[dict]:
    """
    Perform semantic search over a member's indexed contributions.
    Returns a list of results with text, metadata, and relevance rank.
    """
    client = get_chroma_client()

    try:
        collection = client.get_collection(name=_collection_name(member_id))
    except Exception:
        return []

    if collection.count() == 0:
        return []

    model = get_model()
    query_embedding = model.encode([query], show_progress_bar=False).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"] or not results["ids"][0]:
        return []

    output = []
    for i, doc_id in enumerate(results["ids"][0]):
        distance = results["distances"][0][i]
        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # Convert to similarity: 1 - (distance / 2)
        similarity = 1 - (distance / 2)

        output.append({
            "contribution_id": doc_id,
            "text": results["documents"][0][i],
            "similarity": round(similarity, 4),
            "rank": i + 1,
            **results["metadatas"][0][i],
        })

    return output


def get_index_stats(member_id: int) -> dict:
    """Get stats about a member's indexed contributions."""
    client = get_chroma_client()
    try:
        collection = client.get_collection(name=_collection_name(member_id))
        return {
            "member_id": member_id,
            "indexed_count": collection.count(),
            "collection_name": _collection_name(member_id),
        }
    except Exception:
        return {
            "member_id": member_id,
            "indexed_count": 0,
            "collection_name": _collection_name(member_id),
        }


def delete_member_index(member_id: int) -> bool:
    """Delete all indexed data for a member."""
    client = get_chroma_client()
    try:
        client.delete_collection(name=_collection_name(member_id))
        return True
    except Exception:
        return False
