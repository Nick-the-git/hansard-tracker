"""Hansard Tracker — Alerts page."""

import streamlit as st
from app.hansard_client import search_members
from app.alerts import create_alert, get_alerts, delete_alert, toggle_alert, check_alerts

st.set_page_config(page_title="Alerts — Hansard Tracker", page_icon="🔔", layout="wide")

st.title("🔔 Alerts")
st.markdown(
    "Get notified whenever an MP speaks in Parliament, with a direct link to the Hansard record."
)

# ─── Create new alert ───────────────────────────────────────────────────────

with st.expander("**Create new alert**", expanded=True):
    st.markdown("#### Find the MP")

    col_search, col_btn = st.columns([3, 1])
    with col_search:
        alert_name_input = st.text_input(
            "Search for an MP",
            placeholder="e.g. Rishi Sunak",
            label_visibility="collapsed",
            key="alert_member_search",
        )
    with col_btn:
        alert_search_clicked = st.button(
            "Search", key="alert_search_btn", type="secondary", use_container_width=True
        )

    if alert_search_clicked and alert_name_input:
        with st.spinner("Searching..."):
            try:
                members = search_members(alert_name_input)
                st.session_state["alert_members"] = members
            except Exception as e:
                st.error(f"Error: {e}")
                st.session_state["alert_members"] = []

    if "alert_members" in st.session_state and st.session_state["alert_members"]:
        for m in st.session_state["alert_members"]:
            col_avatar, col_info, col_select = st.columns([0.5, 4, 1])
            with col_avatar:
                if m.thumbnail_url:
                    st.image(m.thumbnail_url, width=48)
            with col_info:
                st.markdown(f"**{m.name}**")
                st.caption(f"{m.party} · {m.constituency} · {m.house}")
            with col_select:
                if st.button("Select", key=f"alert_select_{m.id}", use_container_width=True):
                    st.session_state["alert_selected_member"] = m
                    st.rerun()

    if "alert_selected_member" in st.session_state:
        member = st.session_state["alert_selected_member"]
        st.success(f"Selected: **{member.name}** ({member.party}, {member.constituency})")

        alert_email = st.text_input(
            "Your email address",
            placeholder="you@example.com",
            help="We'll send notifications here when this MP speaks.",
        )

        if st.button("Create alert", type="primary"):
            if not alert_email:
                st.warning("Please enter an email address.")
            else:
                alert = create_alert(member.id, member.name, alert_email)
                st.success(f"Alert created for **{member.name}**! Notifications will be sent to {alert_email}.")
                # Clear selection state
                del st.session_state["alert_selected_member"]
                if "alert_members" in st.session_state:
                    del st.session_state["alert_members"]
                st.rerun()


# ─── Existing alerts ────────────────────────────────────────────────────────

st.divider()

col_header, col_check = st.columns([4, 1])
with col_header:
    st.markdown("### Your alerts")
with col_check:
    if st.button("Check now", use_container_width=True):
        with st.spinner("Checking for new contributions..."):
            check_alerts()
        st.success("Check complete!")
        st.rerun()

all_alerts = get_alerts()

if not all_alerts:
    st.info("No alerts set up yet. Create one above to get started.")
else:
    for alert in all_alerts:
        is_active = alert.get("active", True)

        with st.container():
            col_info, col_actions = st.columns([4, 2])

            with col_info:
                status_emoji = "🟢" if is_active else "⏸️"
                status_text = "Active" if is_active else "Paused"
                st.markdown(f"{status_emoji} **{alert['member_name']}** — {status_text}")
                st.caption(
                    f"Notifying {alert['email']} · Last checked: {alert['last_checked'][:16]}"
                )

            with col_actions:
                col_toggle, col_delete = st.columns(2)
                with col_toggle:
                    toggle_label = "Pause" if is_active else "Resume"
                    if st.button(toggle_label, key=f"toggle_{alert['id']}", use_container_width=True):
                        toggle_alert(alert["id"])
                        st.rerun()
                with col_delete:
                    if st.button("Delete", key=f"delete_{alert['id']}", type="secondary", use_container_width=True):
                        delete_alert(alert["id"])
                        st.rerun()

            st.divider()
