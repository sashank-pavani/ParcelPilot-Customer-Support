# ParcelPilot Support Chatbot

A customer-facing AI support chatbot for ParcelPilot, built for the CalQuity AI
Engineer assessment. One Python app (Streamlit UI + a small Gemini tool-calling
agent) answers customer questions about shipments, cancellations, service credits,
and support SLAs, grounded in the supplied policy PDFs and structured account data.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how it's built and
[`PRODUCT_NOTE.md`](PRODUCT_NOTE.md) for product decisions and what's next.

## What it does

- Answers natural-language questions using **only** the supplied data pack (policies,
  SOPs, product docs, signed customer agreements, and the accounts/orders/tickets
  workbook), and knows which sources outrank which when they conflict.
- Scopes every customer to their **own account only** — enforced in code, not just in
  the prompt.
- Uses **three tools**: document search, structured-data lookup + calculation, and a
  mocked "create escalation" action that **always requires a confirmation click**
  before it actually happens.
- Shows which tool ran, with what arguments, under each reply.

## 1. Setup

Requires Python 3.11+.

```bash
python -m venv venv
venv\Scripts\activate          # on Windows
# source venv/bin/activate     # on macOS/Linux
pip install -r requirements.txt
```

Get a free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey),
then create a file named `.env` in this folder (copy `.env.example`) containing:

```
GEMINI_API_KEY=your-actual-key-here
```

(If you skip this, the app will ask for a key in the sidebar instead — handy for a
one-off local test, but `.env` is the normal way to run it.)

The app defaults to `gemini-3.5-flash-lite`, chosen after testing a few Gemini models
against this free-tier key: it supports function calling and had the most generous
free rate limit of the ones tried. If your key hits a different model's free-tier
limits, override it without touching code by setting `GEMINI_MODEL` in `.env`. A
short burst of rate-limit errors is also retried automatically (see `agent.py`).

## 2. Run it locally

```bash
streamlit run app.py
```

This opens the chat UI at `http://localhost:8501`. Log in with any account ID as the
username (e.g. `ACCT-001`) and the demo password `cust1234` (shown on the login
screen itself). Use the sidebar's **Log out** button to switch accounts.

Optional — sanity-check the deterministic business logic (fees/credits/SLAs) without
any API key or network access:

```bash
python sanity_check.py
```

## 3. Try it

Log in as **ACCT-001** (Northstar Logistics) and ask:

> Can I cancel ORD-1001 without a cancellation fee? Explain why.

Log out, log back in as **ACCT-002** (LumenWorks), and ask:

> A pickup on order ORD-2002 is late because of carrier fault. Am I owed a service credit?

Ask either account to escalate something (e.g. *"escalate this to support"*) and
notice the app pauses for a **Confirm** click before anything is actually created —
try clicking **Cancel** too. Also try asking one account about another account's
order ID — it should come back "not found," not real data.

## 4. Deploy it (Streamlit Community Cloud — free, easiest option)

1. Push this folder to a **public** GitHub repo (the `.env` file and
   `data/escalations.json` are already git-ignored, so your key won't be committed).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, click
   **New app**, and point it at this repo's `app.py`.
3. In the app's **Settings → Secrets**, add:
   ```
   GEMINI_API_KEY = "your-actual-key-here"
   ```
4. Deploy. You'll get a public URL like `https://your-app.streamlit.app` — that's the
   link to submit.

## Project layout

```
app.py              Streamlit chat UI
agent.py             Gemini tool-calling loop + system prompt + tool schema
tools.py             The 3 tools the agent can call (thin wrappers with access control)
business_rules.py    Deterministic fee/credit/SLA calculations (plain Python, no LLM)
documents.py          PDF chunking + embedding search over the policy/contract docs
data_store.py        Loads the workbook; account-scoped data access; escalation log
sanity_check.py       Offline check of business_rules against the real dataset
data/                 The supplied data pack (PDFs + workbook) + generated escalations.json
ARCHITECTURE.md       Architecture note (required submission doc)
PRODUCT_NOTE.md       Product note (required submission doc)
```

## AI tool usage

Built with Claude Code (Anthropic) as a pair-programming assistant: reading and
summarizing the supplied PDFs/workbook, drafting the module structure, and writing
the business-rule logic, which was then verified against the dataset with
`sanity_check.py` before being wired up to the live Gemini agent.
