# Architecture Note

## Overview

A single Python/Streamlit app implements a customer-facing support chatbot for
ParcelPilot. One authenticated customer account is "logged in" per session through a
mocked login form (see Access control below). The agent is a small manual
tool-calling loop around Google Gemini, with exactly **three tools**, one per
required category:

| Tool | Category | What it does |
|---|---|---|
| `search_policies` | Document search / retrieval | Embedding search over the six supplied PDFs (policies, SOPs, product docs, signed agreements) |
| `get_account_data` | Structured-data lookup + calculation | Scoped lookup of the logged-in account's orders/tickets, plus deterministic cancellation-fee, service-credit, and SLA calculations |
| `create_escalation_draft` | State-changing action (mocked) | Drafts an escalation; only actually recorded after an explicit user confirmation click in the UI |

Model: `gemini-3.5-flash-lite`, picked empirically -- a couple of newer Gemini models
supported function calling but had very restrictive free-tier quotas (as low as 20
requests/day), which isn't workable for a demo a reviewer will actually click through.
`gemini-3.5-flash-lite` had the most headroom of the models tried. `agent.py` also
retries once or twice with backoff on a 429, since a short tool-heavy exchange can
otherwise trip even a generous free-tier limit.

## Agent design

The tool loop (`agent.py`) is deliberately **manual**, not the SDK's automatic
function-calling mode, for two reasons:

1. **Visibility** — the assessment asks the interface to show which tool is being
   used. A manual loop lets the UI log each `(tool name, arguments)` pair as it
   happens and render it in an expander under the reply.
2. **Confirmation gating** — automatic function calling would execute
   `create_escalation_draft`'s underlying action the instant the model calls it.
   Instead, the tool function only ever returns a *draft* (`status:
   "awaiting_confirmation"`); the record is written to disk exclusively from a
   Streamlit button handler, never from inside the model's tool-call path. This
   means confirmation is enforced by code structure, not by asking the model nicely
   in the prompt — even a hostile or confused model response cannot create an
   escalation by itself.

The loop: send the user message → if the model responds with a function call, run the
corresponding Python function and feed the result back → repeat (capped at 6 rounds)
until the model returns plain text. This is intentionally simple: a `while`-style loop
around one `send_message` call, no orchestration framework.

## Tool design

Each tool returns small, explicit JSON (via a `_jsonable()` normalizer that converts
pandas/numpy types), so the model always reasons over concrete values rather than
prose it has to re-derive. The guiding principle, stated directly in the system
prompt: **the model decides *when* to call a tool and how to explain the result in
words; it is never asked to compute a fee, a credit amount, or an elapsed time itself.**
All arithmetic and date math lives in `business_rules.py`, is plain Python, and is
covered by an offline sanity check (`sanity_check.py`) that prints every order's and
ticket's computed outcome for manual verification against the source PDFs — useful
both for debugging and for confirming the logic before ever spending an API call.

## Document and structured-data handling

- **Documents** (`documents.py`): each PDF is text-extracted with `pypdf`, split into
  paragraph-sized chunks (~150+ chars, merging short headings into the following
  paragraph), and embedded with Gemini's `gemini-embedding-001` model. Retrieval is
  cosine similarity over an in-memory list — no vector database, since the corpus is
  six one-page documents (a few dozen chunks total). Every chunk carries its source
  filename and a hand-set status label (`CURRENT`, `DEPRECATED`, or `ACTIVE signed
  agreement (...)`), so the model can see authority and freshness directly in the tool
  result instead of inferring it from filenames.
- **Structured data** (`data_store.py`): the supplied workbook (accounts, orders,
  tickets) is loaded once with pandas. Every read function takes `account_id` as a
  parameter supplied by the app layer (from the authenticated session), not by the
  model — `get_order`/`get_ticket` filter on `account_id` *before* returning anything,
  so a request for another account's order ID simply returns "not found," never a
  cross-account leak. This is the access-control boundary the assessment asks for,
  and it lives in the data layer, not in prompt instructions.
- **Mocked authentication, account context, and roles**: the app opens on a real login
  form (`app.py`) — username is an account ID, password is a fixed demo value shown
  on screen — rather than a picker, so the login step is a genuine gate the model has
  no visibility into, not just a UI convenience. Once authenticated, `account_id` is
  held server-side in the session and threaded into every tool call the same way
  described above. Roles were deliberately not modeled beyond this: a customer-facing
  bot has exactly one role ("this account's customer"), so a role hierarchy would be
  invented complexity with nothing in the data to justify it. Roles become meaningful
  the moment an *internal* ops chatbot is added (support agent vs. team lead vs.
  admin, each scoped to different accounts/actions) — see the Product Note.

## Source reliability and conflict handling

This is the "Trust and Reliability" problem the assessment calls out, addressed with
three concrete mechanisms rather than a generic policy statement:

1. **Contract terms are modeled as structured config, not re-parsed from PDF text at
   query time.** `business_rules.py` hardcodes the two signed agreements' override
   terms (Northstar's cancellation waiver and custom SLA; LumenWorks' fixed
   service-credit amount) as a small Python dict, the way a real support tool would
   treat data already ingested from a contract-management system. This was a
   deliberate trade-off: asking an LLM to re-extract dates and rupee amounts from
   free text on every request, for numbers that drive a financial calculation, is a
   reliability risk this assessment's own SOP explicitly warns against ("do not
   promise a credit when ... unknown"). The source PDF remains fully searchable
   through `search_policies` for citation and independent verification — the config
   is a cache of an already-read contract, not a hidden source of truth.
2. **Precedence is explicit and enforced in the prompt + tool metadata, not
   discovered by the model.** The system prompt states the order (signed agreement >
   current policy > current product docs; deprecated docs and ticket
   `historical_resolution` fields are context only) and every retrieved chunk carries
   its status label so the model doesn't have to guess it from surrounding text.
   Verified in testing: asking about the deprecated policy's SLA numbers, or repeating
   the wrong guidance baked into `TKT-450`/`TKT-451`'s `historical_resolution` fields,
   does not make the agent adopt them as current.
3. **The model is not allowed to do the arithmetic.** Every fee, credit amount, and
   SLA-breach determination comes back from `get_account_data` as a ready-made value
   with a `reason` string citing the exact source and figures used. This removes the
   most common way a "confidently incorrect" answer happens with LLM agents — silent
   arithmetic mistakes — for the numbers customers actually care about (money and
   time).

## Major technical trade-offs

- **Wall-clock time, not a business-hour calendar.** SLA targets are expressed in
  mixed units (minutes / business hours / business days). Modeling a real
  business-hour, weekend-aware calendar was cut as disproportionate to this
  assessment's scope; elapsed time is plain wall-clock minutes, with an explicit note
  returned alongside multi-hour/day targets so the model doesn't overstate precision.
  All dataset timestamps fall within a single day, so this doesn't affect any of the
  supplied records.
- **"Now" is the dataset snapshot time**, read from the workbook's README sheet at
  load time (not hardcoded), per the assessment's own instruction to treat it as the
  reference time for all time-based questions.
- **No vector database, no framework (LangChain/etc.).** At six documents and a
  handful of structured tables, an in-memory numpy similarity search and pandas
  filtering are simpler to read, debug, and explain than adding infrastructure that
  would only start paying off at a much larger corpus size.
- **Parallel tool calls, answered together.** Gemini sometimes requests two tools in
  one turn (e.g. `get_account_data` and `search_policies` together). Early testing
  showed that answering only the first and dropping the second left the model stuck
  restating the same call with an empty final answer — the API expects a
  `function_response` for every `function_call` it made, in the same message. The
  loop now executes every call from a turn and returns all of their results together
  before the model continues.
- **One chatbot, customer-facing.** The assessment allows building only one; an
  internal ops/investigation chatbot and a proactive issue-detection view were scoped
  out of this submission (see the Product Note for what that would look like).
- **No standalone API layer.** `tools.py` already has the shape of one -- three
  functions with explicit, typed inputs/outputs and access control enforced before
  any data leaves the function -- but it's called in-process from Streamlit rather
  than exposed over HTTP. Wrapping it in FastAPI would be a small, mechanical change
  (each tool becomes one endpoint) and is the natural next step if this needed to
  serve more than one UI.
