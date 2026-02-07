"""Hansard Tracker — Home page."""

import streamlit as st

st.set_page_config(
    page_title="Hansard Tracker",
    page_icon="🏛️",
    layout="wide",
)

st.title("🏛️ Hansard Tracker")
st.subheader("Track what MPs say in Parliament")

st.markdown(
    "Search Hansard records to find what politicians have said about "
    "any topic, and set up alerts to know when they speak."
)

st.divider()

col1, col2 = st.columns(2)

with col1:
    st.markdown("### 🔍 Search")
    st.markdown(
        "Search by topic to find what any MP or Lord has said in "
        "Parliament. Results link directly to the official Hansard record."
    )
    st.page_link("pages/1_Search.py", label="Search Hansard →", icon="🔍")

with col2:
    st.markdown("### 🔔 Alerts")
    st.markdown(
        "Get notified whenever an MP speaks in Parliament. Set up email alerts "
        "and receive links to the Hansard record so you can read it yourself."
    )
    st.page_link("pages/2_Alerts.py", label="Set up alerts →", icon="🔔")
