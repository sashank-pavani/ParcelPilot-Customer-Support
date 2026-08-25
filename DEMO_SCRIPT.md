# Demo Video Script (~5 minutes)

Not a submission requirement to keep — this is just a script to read from while you
screen-record. Delete it (or leave it, it doesn't hurt) before submitting the repo.

Record your screen with the Streamlit app open (`streamlit run app.py`) plus this
script in a second window/monitor to read from. Free tools: Windows's built-in
**Xbox Game Bar** (`Win+G` → Record), OBS Studio, or Loom.

---

## 1. Architecture (about 90 seconds)

*Say, while showing `ARCHITECTURE.md` or just talking over a blank screen:*

> "This is a customer-facing support chatbot for ParcelPilot, a logistics platform.
> It's a single Python app: a Streamlit chat UI on top of a small tool-calling agent
> built on Google Gemini.
>
> The agent has exactly three tools, one per category the assessment asked for:
> `search_policies` does document retrieval over the six supplied PDFs — policies,
> SOPs, product docs, and two signed customer agreements — using embedding-based
> similarity search. `get_account_data` is the structured-data tool: it looks up the
> logged-in customer's own orders and tickets from the supplied workbook, and returns
> deterministic calculations — cancellation fees, service-credit eligibility, SLA
> targets — computed in plain Python, not by the LLM. And `create_escalation_draft` is
> the state-changing action, mocked as a local JSON file, which never actually fires
> until the user clicks Confirm in the UI.
>
> The most important design decision: the model never does financial or date math
> itself. Every dollar amount and every elapsed-time comparison comes back from a
> tested Python function with an explicit reason string, so the model's job is
> deciding *when* to call a tool and *how to explain* the result — not computing it."

## 2. Live demo (about 2.5 minutes)

*Switch to the running app.*

1. **Contract override.** Log in with username **ACCT-001**, password **cust1234**
   (both shown right on the login screen — this is Northstar Logistics). Ask:
   > "Can I cancel ORD-1001 without a cancellation fee? Explain why."

   Point out the answer cites the *signed agreement* overriding the *default SOP*,
   and expand "View reasoning steps" to show `get_account_data` and `search_policies` ran.

2. **Contract-specific numbers, not the default.** Click **Log out** in the sidebar,
   log back in as **ACCT-002** (LumenWorks), same password. Ask:
   > "A pickup on ORD-2001 is 3 hours late because of carrier fault — do I get a
   > service credit?"

   The answer should say **no** — LumenWorks's contract sets a 4-hour threshold, not
   the default 2-hour one. This is one of the assessment's own example questions,
   answered against real account data instead of a hardcoded response.

3. **Trust & reliability.** Still as LumenWorks, ask:
   > "Was the old guidance on ticket TKT-451 — that the Growth plan only supports
   > 3,000 rows — actually correct?"

   The agent should say no: the real limit is 5,000 rows; 3,000 is just a workaround
   for a known bug. This shows the agent refusing to repeat a wrong historical answer.

4. **Access control.** Still logged in as LumenWorks, ask for **ORD-1001** (which
   belongs to Northstar). It should come back "not found" — not real data. Mention
   this is enforced in the data layer (`data_store.py`), not just prompted for.

5. **Confirmation-gated action.** Ask something like:
   > "This is a full outage for us, please escalate immediately."

   Show the **"not yet created"** warning with Confirm/Cancel buttons. Click
   **Confirm**, and point out the resulting escalation ID. Optionally show
   `data/escalations.json` on disk.

## 3. Key decisions, briefly (about 60 seconds)

> "A few decisions worth calling out. First, I treat the signed contracts as
> structured config rather than re-parsing the PDF on every request — for numbers
> that drive money, I didn't want to trust an LLM's PDF extraction, though the
> original PDF is still searchable for citation. Second, all response-time math uses
> plain wall-clock time rather than a full business-hours calendar — a deliberate
> scope cut, called out directly in the architecture note. And third, the escalation
> tool is architecturally incapable of firing without a human click — that's not a
> prompt instruction, it's how the code is structured, which matters a lot for a
> support tool that's allowed to take real actions."

*(End here, or add a sentence on what you'd build next from the Product Note.)*
