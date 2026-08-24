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

# Mocked login only -- every account shares one demo password. A real deployment
# would replace this whole block with ParcelPilot's actual customer identity
# provider; nothing downstream needs to change since every tool call is scoped by
# account_id regardless of how that id was established.
DEMO_PASSWORD = "cust1234"


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


def login_screen():
    st.subheader("🔒 Customer Login")
    demo_ids = ", ".join(f"`{a['account_id']}`" for a in data_store.list_accounts())
    st.info(
        f"**Demo login for this assessment** — Username: any of {demo_ids} · "
        f"Password: `{DEMO_PASSWORD}` (same for every account). A real deployment "
        f"would sit behind ParcelPilot's actual customer identity provider instead."
    )
    with st.form("login_form"):
        username = st.text_input("Username (account ID)", placeholder="ACCT-001")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")

    if submitted:
        account = data_store.get_account(username.strip().upper())
        if account is None:
            st.error("Unknown username. Try one of the account IDs shown above.")
        elif password != DEMO_PASSWORD:
            st.error("Incorrect password.")
        else:
            st.session_state.authenticated_account = account["account_id"]
            st.rerun()


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

    if st.session_state.get("authenticated_account"):
        account = data_store.get_account(st.session_state.authenticated_account)
        st.success(f"Logged in as **{account['account_name']}**\n\n"
                   f"({account['account_id']}, {account['plan']})")
        if st.button("Log out"):
            for key in ("authenticated_account", "chat", "messages", "pending_action", "account_id"):
                st.session_state.pop(key, None)
            st.rerun()

    st.divider()
    st.caption(
        "Login is mocked for this demo, but the boundary it protects is real: every "
        "tool call is scoped server-side to the logged-in account_id, so the chatbot "
        "cannot be asked to fetch another customer's data no matter how it's prompted."
    )

if not api_key:
    st.info("Add a Gemini API key in the sidebar to start chatting.")
    st.stop()

agent.configure(api_key)
index = get_document_index(api_key[:12])

if not st.session_state.get("authenticated_account"):
    login_screen()
    st.stop()

account_id = st.session_state.authenticated_account
if "chat" not in st.session_state:
    init_chat(api_key, account_id)

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
