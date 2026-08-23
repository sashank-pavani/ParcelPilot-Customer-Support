"""ParcelPilot customer support chatbot -- Streamlit UI.

Run with: streamlit run app.py
"""
import os

import streamlit as st
from dotenv import load_dotenv

import agent
import data_store

load_dotenv()

st.set_page_config(page_title="ParcelPilot Support", page_icon="📦", layout="centered")


def get_api_key():
    # Checked in this order so a local .env run never touches st.secrets at all --
    # accessing it with no secrets.toml present prints a distracting warning banner.
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return st.session_state.get("manual_api_key")


@st.cache_resource(show_spinner="Indexing policy documents...")
def get_document_index(api_key_fingerprint: str):
    return agent.build_document_index()


def init_chat(api_key: str, account_id: str):
    st.session_state.chat = agent.new_chat(api_key)
    st.session_state.account_id = account_id
    st.session_state.messages = []
    st.session_state.pending_action = None


st.title("📦 ParcelPilot Support")
st.caption("AI Agent Assessment demo — customer-facing support chatbot")

api_key = get_api_key()

with st.sidebar:
    st.header("Session")

    if not api_key:
        st.warning("No Gemini API key found in secrets or .env.")
        manual_key = st.text_input("Enter a Gemini API key to try the demo", type="password")
        if manual_key:
            st.session_state.manual_api_key = manual_key
            api_key = manual_key

    accounts = data_store.list_accounts()
    option_labels = {
        f"{a['account_name']} ({a['account_id']}, {a['plan']})": a["account_id"]
        for a in accounts
    }
    chosen_label = st.selectbox("Logged in as (mocked auth)", list(option_labels.keys()))
    chosen_account = option_labels[chosen_label]

    if st.button("Start / restart conversation", type="primary", disabled=not api_key):
        agent.configure(api_key)
        init_chat(api_key, chosen_account)
        st.rerun()

    if st.session_state.get("account_id") and st.session_state.account_id != chosen_account:
        st.info("Account changed — click 'Start / restart conversation' to log in as "
                "the new account. The chatbot never re-scopes an existing conversation "
                "to a different account on its own.")

    st.divider()
    st.caption(
        "This selector mocks authentication. In production the account would come "
        "from a real login session, never from user-typed input — and every tool "
        "call is scoped server-side to that account, so the chatbot cannot be asked "
        "to fetch another customer's data."
    )

if not api_key:
    st.info("Add a Gemini API key in the sidebar to start chatting.")
    st.stop()

agent.configure(api_key)
index = get_document_index(api_key[:12])

if "chat" not in st.session_state:
    init_chat(api_key, chosen_account)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message.get("tool_log"):
            with st.expander("🔧 Tools used"):
                for call in message["tool_log"]:
                    st.code(f"{call['name']}({call['args']})", language="text")
        st.markdown(message["content"])

if st.session_state.get("pending_action"):
    pending = st.session_state.pending_action
    with st.chat_message("assistant"):
        st.warning(
            f"**Escalation ready to create — not yet created**\n\n"
            f"- Category: `{pending['category']}`\n"
            f"- Summary: {pending['summary']}\n"
            f"- Order: {pending.get('order_id') or '—'}\n"
            f"- Ticket: {pending.get('ticket_id') or '—'}"
        )
        col1, col2 = st.columns(2)
        if col1.button("✅ Confirm and create escalation", type="primary"):
            record = data_store.create_escalation_record(
                account_id=st.session_state.account_id,
                category=pending["category"],
                summary=pending["summary"],
                order_id=pending.get("order_id"),
                ticket_id=pending.get("ticket_id"),
            )
            st.session_state.pending_action = None
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"✅ Escalation **{record['escalation_id']}** created and "
                           f"routed to the support team.",
            })
            st.rerun()
        if col2.button("Cancel"):
            st.session_state.pending_action = None
            st.session_state.messages.append({
                "role": "assistant", "content": "Okay — I have not created that escalation.",
            })
            st.rerun()

user_message = st.chat_input(
    "Ask about your shipments, policies, or account...",
    disabled=bool(st.session_state.get("pending_action")),
)
if user_message:
    st.session_state.messages.append({"role": "user", "content": user_message})
    with st.chat_message("user"):
        st.markdown(user_message)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            reply, tool_log, pending = agent.run_turn(
                st.session_state.chat, st.session_state.account_id, index, user_message,
            )
        if tool_log:
            with st.expander("🔧 Tools used"):
                for call in tool_log:
                    st.code(f"{call['name']}({call['args']})", language="text")
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply, "tool_log": tool_log})
    if pending:
        st.session_state.pending_action = pending
        st.rerun()
