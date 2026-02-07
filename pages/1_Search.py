"""Hansard Tracker — Semantic Search page."""

import streamlit as st
from app.hansard_client import search_members, get_member_contributions
from app.semantic_search import index_contributions, semantic_query, get_index_stats

st.set_page_config(page_title="Search — Hansard Tracker", page_icon="🔍", layout="wide")

st.title("🔍 Semantic Search")
st.markdown("Find what an MP has said about a topic using meaning-based search.")

# ─── Step 1: Find the MP ────────────────────────────────────────────────────

st.markdown("### 1. Find the MP")

col_search, col_btn = st.columns([3, 1])
with col_search:
    member_name_input = st.text_input(
        "Start typing a name",
        placeholder="e.g. Keir Starmer",
        label_visibility="collapsed",
    )
with col_btn:
    search_clicked = st.button("Search", type="secondary", use_container_width=True)

# Search members
if search_clicked and member_name_input:
    with st.spinner("Searching Parliament members..."):
        try:
            members = search_members(member_name_input)
            st.session_state["members"] = members
        except Exception as e:
            st.error(f"Error searching members: {e}")
            st.session_state["members"] = []

# Display member results
if "members" in st.session_state and st.session_state["members"]:
    members = st.session_state["members"]

    for m in members:
        col_avatar, col_info, col_select = st.columns([0.5, 4, 1])
        with col_avatar:
            if m.thumbnail_url:
                st.image(m.thumbnail_url, width=48)
        with col_info:
            st.markdown(f"**{m.name}**")
            st.caption(f"{m.party} · {m.constituency} · {m.house}")
        with col_select:
            if st.button("Select", key=f"select_{m.id}", use_container_width=True):
                st.session_state["selected_member"] = m
                st.rerun()

elif "members" in st.session_state:
    st.info("No members found. Try a different name.")


# ─── Step 2: Topic search ───────────────────────────────────────────────────

if "selected_member" in st.session_state:
    member = st.session_state["selected_member"]

    st.divider()
    st.markdown(f"### 2. What has **{member.name}** said about...")

    st.markdown(
        f"<small>Selected: <strong>{member.name}</strong> ({member.party}, {member.constituency})</small>",
        unsafe_allow_html=True,
    )

    topic = st.text_input(
        "Describe the topic in plain language — this is semantic search, not keyword matching",
        placeholder="e.g. cost of living crisis, housing affordability, NHS waiting times",
    )

    col_num, col_fetch = st.columns(2)
    with col_num:
        num_results = st.number_input("Number of results", min_value=1, max_value=50, value=10)
    with col_fetch:
        num_to_fetch = st.selectbox(
            "Speeches to index",
            options=[100, 200, 500],
            index=1,
            format_func=lambda x: f"{x} ({'fast' if x == 100 else 'balanced' if x == 200 else 'thorough'})",
        )

    if st.button("Search Hansard", type="primary", use_container_width=True):
        if not topic:
            st.warning("Please enter a topic to search for.")
        else:
            # Step 1: Fetch from Hansard
            with st.spinner(f"Fetching {member.name}'s speeches from Hansard..."):
                try:
                    contributions = get_member_contributions(
                        member_id=member.id,
                        take=min(num_to_fetch, 500),
                    )
                except Exception as e:
                    st.error(f"Error fetching from Hansard API: {e}")
                    contributions = []

            if contributions:
                # Step 2: Index
                with st.spinner(f"Indexing {len(contributions)} speeches (embedding model runs locally)..."):
                    indexed_count = index_contributions(member.id, contributions)

                # Step 3: Semantic search
                with st.spinner("Performing semantic search..."):
                    results = semantic_query(member.id, topic, top_k=num_results)

                stats = get_index_stats(member.id)

                # ─── Display results ─────────────────────────────────────

                st.divider()

                col_header, col_stats = st.columns([3, 2])
                with col_header:
                    st.markdown(f'### Results for "{topic}"')
                with col_stats:
                    st.caption(
                        f"{stats['indexed_count']} speeches indexed"
                        + (f" ({indexed_count} newly added)" if indexed_count > 0 else "")
                    )

                if not results:
                    st.info("No results found. Try broadening your topic or indexing more speeches.")
                else:
                    for r in results:
                        similarity = r["similarity"]
                        if similarity >= 0.6:
                            badge_color = "green"
                        elif similarity >= 0.4:
                            badge_color = "orange"
                        else:
                            badge_color = "gray"

                        sim_pct = round(similarity * 100)
                        date = r.get("sitting_date", "").split("T")[0] if r.get("sitting_date") else "Unknown"
                        text = r["text"]
                        display_text = text[:600] + "..." if len(text) > 600 else text

                        with st.container():
                            col_title, col_sim = st.columns([5, 1])
                            with col_title:
                                st.markdown(f"**{r.get('debate_title', 'Unknown debate')}**")
                            with col_sim:
                                st.markdown(
                                    f'<span style="background:{badge_color}; color:white; '
                                    f'padding:2px 8px; border-radius:3px; font-size:13px; '
                                    f'font-weight:bold;">{sim_pct}% match</span>',
                                    unsafe_allow_html=True,
                                )

                            st.caption(f"{date} · {r.get('section', '')} · {r.get('house', '')}")
                            st.markdown(display_text)
                            st.markdown(f"[Read full debate on Hansard →]({r.get('hansard_url', '#')})")
                            st.divider()
            else:
                st.warning("No contributions found for this member. They may not have recent Hansard records.")
