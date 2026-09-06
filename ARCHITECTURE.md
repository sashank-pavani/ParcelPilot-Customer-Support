# Architecture Note

## How the app is structured

The app is a single Python/Streamlit application. When a customer logs in, we know their `account_id` for the rest of the session. Every tool call the AI makes passes that `account_id` through — it's set by the app, not by the AI — so there's no way for the model to access another customer's data even if asked.

---

## The three tools

The AI can call exactly three tools:

**1. `search_policies` — document search**
Searches across 6 policy PDFs using sentence-transformers embeddings and cosine similarity. Each chunk returned includes the source filename and whether it's current, deprecated, or a signed agreement — so the model knows which source to trust when documents conflict.

**2. `get_account_data` — structured data lookup**
Pulls the logged-in customer's orders, tickets, and escalations from Supabase. Also runs deterministic calculations — cancellation fee, service credit eligibility, SLA breach check — and returns the results directly. The AI never does this math itself; it just reads the output and explains it.

**3. `create_escalation_draft` / `cancel_order_draft` — state-changing actions**
These tools only prepare a draft. They don't actually do anything until the customer clicks Confirm in the UI. This is enforced by code structure — the record is only written to Supabase from a button click handler, never from inside the tool itself.

---

## The tool-calling loop

Each time a customer sends a message:

1. We package the system prompt + last 6 messages + new message → send to Groq
2. Groq may respond with one or more tool calls instead of a text reply
3. We run the tool(s) in Python and send the results back to Groq
4. Repeat up to 6 rounds until Groq replies with plain text
5. Save both the user message and the reply to Supabase

The loop is manual (not using any auto-function-calling SDK feature) so we can:
- Show the user which tool ran and with what arguments
- Gate the escalation/cancel tools behind a Confirm button

---

## AI model

We started with Gemini Flash for chat. It worked initially but the free-tier rate limit ran out quickly — the model makes multiple API calls per user message (one per tool round), which burns through the quota fast.

We switched to Groq's `llama-3.3-70b-versatile`. Groq has a more generous free tier and their API is OpenAI-compatible, so the switch only required changing the client. The tool schema format is identical.

---

## PDF search

We tried Gemini's embedding API first but the API key type we had (OAuth token, not an API key) wasn't supported for embeddings. Instead of spending time debugging auth, we switched to `sentence-transformers` with the `all-MiniLM-L6-v2` model. It runs directly on the server — no API key, no rate limits.

At startup, the app:
1. Reads each PDF with `pypdf`
2. Splits text into chunks (~150+ chars)
3. Embeds each chunk as a vector
4. Stores everything in memory

At query time, we embed the user's question, compute cosine similarity against all chunks, and return the top 4 matches to the AI.

Six short documents with a few dozen chunks total — a real vector database would be overkill here. Numpy is enough.

---

## Data storage

Everything started in an Excel workbook. We migrated it to Supabase so the data is real and persistent:

| Table | What's in it |
|---|---|
| `accounts` | 4 demo customer accounts |
| `orders` | 6 shipment records |
| `tickets` | 7 support tickets |
| `escalations` | Created when customers confirm an escalation |
| `conversation_history` | Last messages per session (for context on refresh) |

Cancellations and escalations write back to Supabase immediately — they survive app restarts and redeployments.

---

## Business rules

Cancellation fees, service credits, and SLA breach checks are all calculated in `business_rules.py` — plain Python with hardcoded constants from the policy PDFs. The AI is never asked to compute these; it only reads the result and explains it.

Why hardcode instead of re-parsing PDFs? Because asking an LLM to extract a rupee amount from a contract PDF on every request is a reliability risk. The numbers are small and stable — encoding them directly is safer.

The two signed customer agreements (Northstar Logistics and LumenWorks) have custom terms that override the defaults. These overrides are also in `business_rules.py` as a simple Python dict.

---

## Access control

`account_id` is set at login by the app and passed as a hidden argument to every tool. The model has no parameter it could use to request a different account's data. Even if the model tried to ask for `ACCT-002`'s orders while logged in as `ACCT-001`, the query would filter on `account_id = 'ACCT-001'` and return nothing.

---

## Things we deliberately didn't build

- **Business-hour calendar for SLA checks** — the dataset timestamps all fall within one day, so wall-clock time was accurate enough. Noted explicitly in the tool response.
- **Vector database** — six documents don't need one. In-memory numpy is simpler and faster to understand.
- **Auto-function-calling** — manual loop gives us visibility and confirmation gating.
- **Roles beyond "customer"** — a customer-facing bot has one role. Roles become useful when you add an internal ops chatbot for support agents.
