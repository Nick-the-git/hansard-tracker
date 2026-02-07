"""Hansard Tracker — Search page."""

import os
import streamlit as st
from app.hansard_client import search_members, get_member_contributions
from app.llm import rank_contributions

st.set_page_config(page_title="Search — Hansard Tracker", page_icon="🔍", layout="wide")

st.title("🔍 Search Hansard")
st.markdown("Find what an MP has said about any topic in Parliament.")

# Check for API key
if not os.getenv("GEMINI_API_KEY"):
    st.warning(
        "**Gemini API key not set.** Get a free key at "
        "[Google AI Studio](https://aistudio.google.com/apikey) "
        "and add it as `GEMINI_API_KEY` in your environment or Streamlit secrets."
    )

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

if search_clicked and member_name_input:
    with st.spinner("Searching Parliament members..."):
        try:
            members = search_members(member_name_input)
            st.session_state["members"] = members
        except Exception as e:
            st.error(f"Error searching members: {e}")
            st.session_state["members"] = []

if "members" in st.session_state and st.session_state["members"]:
    for m in st.session_state["members"]:
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

    topic_context = st.text_area(
        "What do you mean by this? (optional but helps accuracy)",
        placeholder="e.g. I mean social investment as in impact investing, social enterprises, community interest companies — NOT general government spending on public services",
        height=80,
        help="Give the AI more context about what you're looking for. This is especially useful for ambiguous terms.",
    )

    col_num, col_fetch = st.columns(2)
    with col_num:
        num_results = st.number_input("Max results", min_value=1, max_value=20, value=10)
    with col_fetch:
        num_to_scan = st.selectbox(
            "Speeches to scan",
            options=[50, 100, 200, 500],
            index=1,
            format_func=lambda x: f"Last {x} speeches",
            help="How many of their most recent speeches to scan for relevance. Higher = goes further back in time but takes longer.",
        )

    with st.form("search_form"):
        topic = st.text_input(
            "Topic",
            placeholder="e.g. artificial intelligence, housing crisis, NHS waiting times",
        )
        search_submitted = st.form_submit_button("Search Hansard", type="primary", use_container_width=True)

    if search_submitted:
        if not topic:
            st.warning("Please enter a topic to search for.")
        elif not os.getenv("GEMINI_API_KEY"):
            st.error("Please set your GEMINI_API_KEY first.")
        else:
            # Step 1: Fetch recent speeches from Hansard
            with st.spinner(f"Fetching {member.name}'s last {num_to_scan} speeches from Hansard..."):
                try:
                    contributions = get_member_contributions(
                        member_id=member.id,
                        take=num_to_scan,
                        filter_short=True,
                    )
                except Exception as e:
                    st.error(f"Error fetching from Hansard: {e}")
                    contributions = []

            if contributions:
                # Step 2: Send to Gemini for ranking
                gemini_error = False
                with st.spinner(f"AI is reading {len(contributions)} speeches and finding ones about \"{topic}\" (may take up to a minute)..."):
                    try:
                        results = rank_contributions(
                            contributions=contributions,
                            topic=topic,
                            member_name=member.name,
                            max_results=num_results,
                            topic_context=topic_context if topic_context else None,
                        )
                    except Exception as e:
                        st.error(f"Gemini error: {e}")
                        results = []
                        gemini_error = True

                # ─── Display results ─────────────────────────────────────

                if gemini_error:
                    st.warning("The AI couldn't process the speeches. Try again in a minute — this is usually a temporary rate limit.")
                else:
                    st.divider()

                    st.markdown(f'### Results for "{topic}"')
                    st.caption(f"Scanned {len(contributions)} recent speeches, found {len(results)} relevant")

                    if not results:
                        st.info(
                            f"None of **{member.name}**'s last {len(contributions)} speeches "
                            f"were about \"{topic}\". They may not have spoken about this recently."
                        )
                    else:
                        for r in results:
                            rank = r["rank"]
                            date = r.get("sitting_date", "").split("T")[0] if r.get("sitting_date") else "Unknown"
                            text = r["text"]
                            display_text = text[:600] + "..." if len(text) > 600 else text

                            with st.container():
                                col_rank, col_content = st.columns([0.3, 5])
                                with col_rank:
                                    st.markdown(
                                        f'<div style="background:#1d70b8; color:white; '
                                        f'width:36px; height:36px; border-radius:50%; '
                                        f'display:flex; align-items:center; justify-content:center; '
                                        f'font-weight:bold; font-size:16px; margin-top:4px;">{rank}</div>',
                                        unsafe_allow_html=True,
                                    )
                                with col_content:
                                    st.markdown(f"**{r.get('debate_title', 'Unknown debate')}**")
                                    st.caption(f"{date} · {r.get('section', '')} · {r.get('house', '')}")

                                st.markdown(display_text)

                                if r.get("relevance"):
                                    st.caption(f"🤖 *{r['relevance']}*")

                                st.markdown(f"[Read full debate on Hansard →]({r.get('hansard_url', '#')})")
                                st.divider()
            else:
                st.warning("No contributions found for this member.")
