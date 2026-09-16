# ParcelPilot Support Chatbot

A customer support chatbot built for the CalQuity AI Engineer assessment. Customers can log in, ask about their orders and policies, get cancellation fees calculated, escalate issues, and cancel orders — all through a chat interface.

Live demo: [parcelpilot-customer-support.streamlit.app](https://parcelpilot-customer-support.streamlit.app/)

---

## What it does

- Answers questions about shipments, cancellations, service credits, and SLAs
- Searches across 6 policy PDFs to give grounded, cited answers
- Looks up real account data (orders, tickets) scoped to the logged-in customer only
- Calculates fees and credits using Python logic — never asks the AI to do the math
- Lets customers create escalations or cancel orders, but only after they click Confirm
- Detects stuck shipments (carrier didn't show up) and flags them automatically
- Stores conversation history and escalations in Supabase (persists across sessions)

---

## Tech stack

| Layer | What we use | Why |
|---|---|---|
| UI | Streamlit | Fast to build, easy to deploy |
| Chat AI | Groq (openai/gpt-oss-20b) | Fast, free tier, OpenAI-compatible |
| PDF search | sentence-transformers (all-MiniLM-L6-v2) | Local model, no API key needed |
| Database | Supabase (PostgreSQL) | Free, persistent, easy Python client |
| Business logic | Plain Python | - |

---

## Why Groq instead of Gemini?

I started with Gemini for chat. It worked initially but I hit the free-tier rate limit quickly — the model makes multiple API calls per user message (one per tool call), so the limit runs out faster than expected.

Groq has a more generous free tier and their API is OpenAI-compatible, so the switch was straightforward. I kept the same tool-calling structure, just changed the client.

For PDF embeddings, I originally tried Gemini's embedding API but faced the same Rate limit error. Rather than fight the issue, I switched to `sentence-transformers` which runs locally — no key needed, no rate limits.

---

## Setup (local)

Requires Python 3.11.

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

Create a `.env` file:

```
GROQ_API_KEY=your-groq-key-here
SUPABASE_URL=your-supabase-url
SUPABASE_KEY=your-supabase-anon-key
```

Get a free Groq key at [console.groq.com](https://console.groq.com).

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. Log in with any account ID (`ACCT-001`, `ACCT-002`, etc.) and password `cust1234`.

---

## Deploy (Streamlit Cloud)

1. Push to a public GitHub repo
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app → point to `app.py`
3. Add secrets in Settings → Secrets:
   ```
   GROQ_API_KEY = "your-key"
   SUPABASE_URL = "your-url"
   SUPABASE_KEY = "your-anon-key"
   ```
4. Deploy

---

## Project layout

```
app.py               Streamlit UI — login, chat, confirm buttons
agent.py             Groq tool-calling loop, system prompt, tool schema
tools.py             Three tools the agent can call (with access control)
business_rules.py    Fee, credit, SLA calculations — pure Python, no AI
documents.py         PDF chunking + embedding search via sentence-transformers
data_store.py        Supabase queries for accounts, orders, tickets, escalations
db.py                Conversation history (save/load from Supabase)
data/                Policy PDFs + Excel workbook (source data)
.streamlit/          Theme config (colors, fonts)
```

---

## Demo accounts

| Account | Name | Plan |
|---|---|---|
| ACCT-001 | Northstar Logistics | Enterprise |
| ACCT-002 | LumenWorks | Growth |
| ACCT-003 | BlueRidge Co | Standard |
| ACCT-004 | Zenith Parts | Standard |

Password for all: `cust1234`
