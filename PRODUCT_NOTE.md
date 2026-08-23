# Product Note

## Additional client problem chosen: Trust & Reliability

I chose Trust & Reliability over Proactive Issue Detection because it's the risk that
turns a single wrong answer into a customer walking away, and the supplied data pack
was clearly built to test exactly this (a deprecated policy sitting next to a current
one, two historical tickets with wrong resolutions, a contract that silently
overrides a default fee). Proactive Issue Detection is valuable but is a second
surface (an ops dashboard) rather than something that makes the required chatbot
itself trustworthy — I'd rather ship one thing that doesn't lie than two things that
might.

How I addressed it, concretely (not just "the prompt says be careful"):

1. **The agent never does financial or date math itself.** Every fee, credit amount,
   and SLA comparison comes back from a Python function with an explicit reason
   string. This is the single biggest source of "confidently incorrect" answers with
   LLM agents, and it's removed by construction rather than by hoping the model gets
   arithmetic right.
2. **Every retrieved document chunk carries a status label** (current / deprecated /
   active signed agreement), and the system prompt states the precedence order
   explicitly. Tested directly: asking about cancellation fees on a Northstar order
   does not surface the deprecated policy's numbers, and does not repeat the wrong
   fee stated in that account's own closed ticket (`TKT-450`).
3. **Historical ticket resolutions are visible but never authoritative.** They're
   returned as plain data (so the agent can reference "a similar issue happened
   before"), but the system prompt tells the model outright that this field may be
   wrong and must not be treated as policy.
4. **When a fact is missing or the situation calls for judgment** (unknown carrier
   fault, an amount needing manager approval, anything outside the three tools'
   coverage), the agent drafts an escalation instead of guessing — and that
   escalation still requires a human click before it's real.

## What I'd build next, in priority order

1. **Internal ops/investigation chatbot.** The data pack (and the actual `notes`
   fields on tickets like the API-key-exposure one) clearly anticipates an internal
   user who can see across accounts, investigate known issues, and act with broader
   authority. This was the natural "second user context" the assessment describes,
   cut here only to keep one submission simple and finishable.
2. **A minimal proactive-issue view**, even just a daily grouped table: tickets by
   product-area keyword, orders with an unresolved carrier-fault flag past the SLA
   window, tickets referencing a known-issue ID. The Beacon Retail known-issue example
   in the data pack (`KI-208`/`KI-211`) is exactly the kind of pattern this would
   surface before a customer has to ask about it.
3. **Real authentication and a real database**, replacing the mocked "log in as" and
   the in-memory workbook, once this needs to run against live ParcelPilot data
   instead of a fixed snapshot.
4. **Monthly service-credit aggregation** against Northstar's INR 5,000 cap — noted as
   a caveat in every relevant answer today, but not actually computed.
5. **A real business-hours/weekday calendar** for SLA math instead of wall-clock time,
   once targets need to be accurate to the hour across weekends and multi-day windows.

## What I intentionally left out

- The internal chatbot and the proactive-detection view (above) — scope, not
  difficulty.
- Business-hour-aware SLA timers (wall-clock time is used instead; flagged directly
  in every SLA-related tool result rather than silently assumed).
- Real authentication (mocked with a sidebar account selector).
- Streaming responses / typing indicators beyond Streamlit's own spinner — a
  cosmetic nice-to-have, not a correctness concern.
- Automated tests beyond `sanity_check.py`'s manual-inspection script — reasonable for
  an assessment-scale project, not what I'd ship to production as-is.

## One metric I'd use to judge whether this is useful

**Confirmed-escalation rate on questions the agent answered directly** — i.e., of the
tickets the agent resolved without escalating, how many later needed a human to step
in and correct or redo the answer. This is the number that would catch the exact
failure mode this assessment is worried about (a confident wrong answer), and it's
more informative than a generic containment/deflection rate, which would look great
even while quietly getting cancellation fees wrong.
