"""ParcelPilot customer support chatbot -- Streamlit UI.

Run with: streamlit run app.py
"""
import os #imports os file to interact with the operating system

import streamlit as st
from dotenv import load_dotenv #imports dotenv file to load the environment variables

import agent #imports agents.py file
import data_store #imports data_store.py file

load_dotenv()

st.set_page_config(page_title="ParcelPilot Support", page_icon="📦", layout="centered")

# Defining the password for all the accounts as this is a demo app.
DEMO_PASSWORD = "cust1234"

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }

.block-container { padding-top: 2.25rem; max-width: 760px; }

.pp-header {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    padding-bottom: 1rem;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid #E5E9F0;
}
.pp-header .pp-mark {
    width: 30px; height: 30px;
    border-radius: 7px;
    background: linear-gradient(135deg, #2E5EAA, #1B3E7A);
    display: inline-flex; align-items: center; justify-content: center;
    color: white; font-weight: 700; font-size: 0.95rem;
    flex-shrink: 0;
}
.pp-header .pp-name { font-size: 1.35rem; font-weight: 700; color: #1B2430; }
.pp-header .pp-sep { color: #C6CCD6; font-weight: 400; }
.pp-header .pp-tagline { font-size: 1.0rem; color: #6B7280; font-weight: 500; }

.pp-card {
    background: #FBFCFD;
    border: 1px solid #E5E9F0;
    border-radius: 12px;
    padding: 1.5rem 1.6rem 0.9rem 1.6rem;
    margin-bottom: 1.2rem;
}
.pp-card h3 { margin-top: 0; }
.pp-hint {
    font-size: 0.85rem;
    color: #5B6472;
    background: #F1F5FB;
    border: 1px solid #DCE5F2;
    border-radius: 8px;
    padding: 0.65rem 0.9rem;
    margin-bottom: 1.1rem;
    line-height: 1.5;
}
.pp-hint code {
    background: #E4ECF9; padding: 1px 5px; border-radius: 4px; color: #1B3E7A;
}

.pp-plan-badge {
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    color: #1B3E7A;
    background: #E4ECF9;
    border-radius: 5px;
    padding: 2px 7px;
    margin-left: 6px;
}

[data-testid="stChatMessage"] {
    border-radius: 12px;
    padding: 0.9rem 1.05rem;
    margin-bottom: 0.6rem;
    border: 1px solid #ECEFF3;
}

[data-testid="stExpander"] {
    border: none;
    background: transparent;
}
[data-testid="stExpander"] summary {
    font-size: 0.8rem;
    color: #6B7280;
    font-weight: 500;
}
[data-testid="stExpander"] summary:hover { color: #2E5EAA; }

section[data-testid="stSidebar"] { border-right: 1px solid #E5E9F0; }
section[data-testid="stSidebar"] .block-container { padding-top: 1.75rem; }

footer, #MainMenu { visibility: hidden; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def get_api_key():
    # Checked in this order so a local .env run never touches st.secrets at all --
    # accessing it with no secrets.toml present prints a distracting warning banner.
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"]
    try:
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"]
    except Exception:
        pass
    return st.session_state.get("manual_api_key")


@st.cache_resource(show_spinner="Setting things up...")
def get_document_index(api_key_fingerprint: str):
    return agent.build_document_index()


def init_chat(api_key: str, account_id: str):
    st.session_state.chat = agent.new_chat(api_key)
    st.session_state.account_id = account_id
    st.session_state.messages = []
    st.session_state.pending_action = None


def login_screen():
    _, mid, _ = st.columns([1, 4, 1])
    with mid:
        st.markdown('<div class="pp-card">', unsafe_allow_html=True)
        st.markdown("### Sign in")
        demo_ids = ", ".join(f"<code>{a['account_id']}</code>" for a in data_store.list_accounts())
        st.markdown(
            f'<div class="pp-hint">Demo access for this walkthrough — username: '
            f'{demo_ids} · password: <code>{DEMO_PASSWORD}</code> for every account.</div>',
            unsafe_allow_html=True,
        )
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="ACCT-001")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

        if submitted:
            account = data_store.get_account(username.strip().upper())
            if account is None:
                st.error("We couldn't find that account. Check the username and try again.")
            elif password != DEMO_PASSWORD:
                st.error("That password doesn't match.")
            else:
                st.session_state.authenticated_account = account["account_id"]
                st.rerun()


st.markdown(
    '<div class="pp-header">'
    '<span class="pp-mark">PP</span>'
    '<span class="pp-name">ParcelPilot</span>'
    '<span class="pp-sep">/</span>'
    '<span class="pp-tagline">Support</span>'
    '</div>',
    unsafe_allow_html=True,
)

api_key = get_api_key()

with st.sidebar:
    if not api_key:
        st.warning("No Groq API key configured.")
        manual_key = st.text_input("API key", type="password", label_visibility="collapsed",
              placeholder="Paste a Groq API key to try this")
        if manual_key:
            st.session_state.manual_api_key = manual_key
            api_key = manual_key

    if st.session_state.get("authenticated_account"):
        account = data_store.get_account(st.session_state.authenticated_account)
        st.markdown("**Account**")
        st.markdown(
            f"{account['account_name']}"
            f'<span class="pp-plan-badge">{account["plan"]}</span>',
            unsafe_allow_html=True,
        )
        st.caption(account["account_id"])
        st.write("")
        if st.button("Sign out", use_container_width=True):
            for key in ("authenticated_account", "chat", "messages", "pending_action", "account_id"):
                st.session_state.pop(key, None)
            st.rerun()
        st.divider()

    st.caption(
        "Login is mocked for this walkthrough, but the boundary it protects is real: "
        "every lookup is scoped server-side to the signed-in account, so it can't be "
        "asked to return another customer's data."
    )

if not api_key:
    st.info("Add a Gemini API key in the sidebar to continue.")
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
    with st.chat_message(message["role"], avatar="📦" if message["role"] == "assistant" else None):
        st.markdown(message["content"])

if st.session_state.get("pending_action"):
    pending = st.session_state.pending_action
    kind = pending.get("kind", "escalation")
    with st.chat_message("assistant", avatar="📦"):
        if kind == "cancel_order":
            fee = pending.get("fee_inr")
            fee_text = "₹0" if fee == 0 else (f"₹{fee}" if fee is not None else "—")
            st.warning(
                f"**This cancellation hasn't been applied yet — review before confirming**\n\n"
                f"- Order: `{pending.get('order_id')}`\n"
                f"- Cancellation fee: {fee_text}\n"
                f"- {pending.get('reason') or ''}"
            )
        else:
            st.warning(
                f"**This hasn't been submitted yet — review before confirming**\n\n"
                f"- Category: `{pending['category']}`\n"
                f"- Summary: {pending['summary']}\n"
                f"- Order: {pending.get('order_id') or '—'}\n"
                f"- Ticket: {pending.get('ticket_id') or '—'}"
            )
        col1, col2 = st.columns(2)
        if col1.button("Confirm and submit", type="primary", use_container_width=True):
            if kind == "cancel_order":
                record = data_store.cancel_order(
                    st.session_state.account_id, pending["order_id"],
                )
                st.session_state.pending_action = None
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": (
                        f"Order **{pending['order_id']}** is now **CANCELLED**."
                        if record else
                        f"Could not cancel **{pending['order_id']}** — it was not found on this account."
                    ),
                })
            else:
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
                    "content": f"Escalation **{record['escalation_id']}** has been created "
                               f"and routed to the support team.",
                })
            st.rerun()
        dismiss_label = "Don't cancel" if kind == "cancel_order" else "Cancel"
        if col2.button(dismiss_label, use_container_width=True):
            st.session_state.pending_action = None
            st.session_state.messages.append({
                "role": "assistant", "content": "Understood — that hasn't been submitted.",
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

    with st.chat_message("assistant", avatar="📦"):
        with st.spinner("Looking into it..."):
            reply, tool_log, pending = agent.run_turn(
                st.session_state.chat, st.session_state.account_id, index, user_message,
            )
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})
    if pending:
        st.session_state.pending_action = pending
        st.rerun()
