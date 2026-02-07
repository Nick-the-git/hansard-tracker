"""Hansard Tracker — Search page."""

import streamlit as st
from app.hansard_client import search_members, get_member_contributions

st.set_page_config(page_title="Search — Hansard Tracker", page_icon="🔍", layout="wide")

st.title("🔍 Search Hansard")
st.markdown("Find what an MP has said about any topic in Parliament.")

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

    topic = st.text_input(
        "Enter a topic or keywords",
        placeholder="e.g. artificial intelligence, housing crisis, NHS waiting times",
    )

    num_results = st.number_input("Number of results", min_value=1, max_value=100, value=10)

    if st.button("Search Hansard", type="primary", use_container_width=True):
        if not topic:
            st.warning("Please enter a topic to search for.")
        else:
            with st.spinner(f"Searching Hansard for {member.name}'s speeches on \"{topic}\"..."):
                try:
                    contributions = get_member_contributions(
                        member_id=member.id,
                        search_term=topic,
                        take=num_results,
                        filter_short=True,
                    )
                except Exception as e:
                    st.error(f"Error searching Hansard: {e}")
                    contributions = []

            st.divider()
            st.markdown(f'### Results for "{topic}"')

            if not contributions:
                st.info(
                    f"No speeches found where **{member.name}** discussed \"{topic}\". "
                    f"Try different keywords or a broader topic."
                )
            else:
                st.caption(f"Showing {len(contributions)} results")

                for i, c in enumerate(contributions, 1):
                    date = c.sitting_date.split("T")[0] if c.sitting_date else "Unknown"
                    text = c.text
                    display_text = text[:600] + "..." if len(text) > 600 else text

                    with st.container():
                        col_rank, col_content = st.columns([0.3, 5])
                        with col_rank:
                            st.markdown(
                                f'<div style="background:#1d70b8; color:white; '
                                f'width:36px; height:36px; border-radius:50%; '
                                f'display:flex; align-items:center; justify-content:center; '
                                f'font-weight:bold; font-size:16px; margin-top:4px;">{i}</div>',
                                unsafe_allow_html=True,
                            )
                        with col_content:
                            st.markdown(f"**{c.debate_title or 'Unknown debate'}**")
                            st.caption(f"{date} · {c.section} · {c.house}")

                        st.markdown(display_text)
                        st.markdown(f"[Read full debate on Hansard →]({c.hansard_url})")
                        st.divider()
