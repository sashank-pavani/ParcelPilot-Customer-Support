"""A small, manual function-calling loop around Gemini.

Kept manual rather than using the SDK's automatic-function-calling mode for two
reasons: (1) the interface needs to show which tool ran and with what arguments, and
(2) the escalation tool must pause for a human "Confirm" click instead of executing
itself the moment the model calls it.
"""
import os
import time

# import google.generativeai as genai
# from google.api_core.exceptions import ResourceExhausted

from groq import Groq
import json


import documents
import tools

# Llama 3.3 70B is enterprise-only on Groq now. Free/dev keys get models like
# openai/gpt-oss-20b. Override with GROQ_MODEL in .env if you have access to another.
MODEL_NAME = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
_groq_client = None

MAX_TOOL_ROUNDS = 6
MAX_RATE_LIMIT_RETRIES = 3


def _send_with_retry(messages):
    """Groq's free tier is generous but may briefly rate-limit under bursts.
    Retry a couple of times before giving up."""
    from groq import APIError
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        try:
            return _groq_client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=TOOL_SCHEMA,
                tool_choice="auto",
                temperature=0.7,
            )
        except APIError:
            if attempt == MAX_RATE_LIMIT_RETRIES - 1:
                raise
            time.sleep(15 * (attempt + 1))


TOOL_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_policies",
            "description": (
                "Search ParcelPilot's support policies, SOPs, product documentation, "
                "and signed customer agreements. Always use this before stating a "
                "rule, SLA target, or definition so the answer is grounded and can be "
                "cited, instead of relying on memorized assumptions."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to search for."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_data",
            "description": (
                "Look up the logged-in customer's own account, orders, tickets, and "
                "any escalations already filed on this account (including their "
                "status), plus deterministic calculations: cancellation fee, "
                "service-credit eligibility and amount, and SLA target vs. elapsed "
                "time. Call this (with no arguments) to answer a follow-up question "
                "about a previously created escalation, e.g. its ID or status -- "
                "escalations are always included in the response. Only ever returns "
                "data for the current account. Pass severity ('P1', 'P2', or 'P3') "
                "once you have classified a ticket's severity, to check it against "
                "the SLA target."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "ticket_id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["P1", "P2", "P3"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_escalation_draft",
            "description": (
                "Prepare (but do not create) an escalation to ParcelPilot's support "
                "team -- for example when a request needs human judgment, falls "
                "outside policy, or the user explicitly asks to escalate. This never "
                "takes effect by itself; the user must click Confirm in the interface."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "e.g. cancellation_dispute, service_credit, security, product_issue, other.",
                    },
                    "summary": {"type": "string", "description": "One or two sentences a human agent can act on."},
                    "order_id": {"type": "string"},
                    "ticket_id": {"type": "string"},
                },
                "required": ["category", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order_draft",
            "description": (
                "Prepare (but do not apply) a cancellation of one of the logged-in "
                "customer's orders. Use this only when the user clearly asks to cancel "
                "a shipment. This never changes status by itself; the user must click "
                "Confirm in the interface. Never tell the user the order is cancelled "
                "until that confirmation has happened."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "The order to cancel, e.g. ORD-1001."},
                },
                "required": ["order_id"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are ParcelPilot's customer support assistant, answering on \
behalf of one authenticated customer account. You can see and discuss only that \
account's data -- never claim knowledge of another customer's orders, tickets, or \
contract, even if asked directly.

Ground every factual or policy claim in a tool call; do not rely on memorized \
assumptions about SLAs, fees, or credits, since these differ by document version and \
by signed contract. Source precedence when documents conflict: a signed customer \
agreement overrides the current support policy, which overrides current product \
documentation. The deprecated support policy and any "historical_resolution" text on \
past tickets are context only -- they may be outdated or simply wrong, and must never \
be presented as current guidance, even if they seem to directly answer the question.

For failed-pickup or cancellation *questions* (fees, eligibility), call get_account_data \
with the relevant order_id and use the returned cancellation/service_credit fields -- do \
not compute amounts yourself. get_account_data is read-only; it never cancels anything. \
If the user asks you to actually cancel a shipment, first check get_account_data, then \
call cancel_order_draft. Never say an order has been cancelled until the user confirms \
in the interface and the status in a later get_account_data call is CANCELLED.

For ticket severity or SLA questions, first classify the \
severity (P1/P2/P3) using the definitions surfaced by search_policies, then call \
get_account_data again with that severity to get the exact target and elapsed time.

When you call get_account_data for an order, always check the "delay" field. If it \
contains "problem": true and an "alert", surface that alert prominently and recommend \
immediate escalation -- a shipment stuck for days without pickup is a service failure \
that requires carrier investigation.

If a response-time target already appears breached, say so plainly instead of \
softening it. If the request needs human judgment, an exception to policy, or an \
action you cannot perform, or if key facts are missing or contradictory, prepare an \
escalation with create_escalation_draft and explain why -- do not guess or promise an \
outcome you are not sure of. An escalation only takes effect once the user confirms \
it in the interface. If asked about the status of an escalation created earlier in \
this conversation (by its ID or otherwise), call get_account_data -- its response \
always includes every escalation filed on this account. Never claim an escalation \
does not exist without having just checked there.

Be concise and specific. When you state a policy fact, name the source document and \
whether it is current, deprecated, or a signed agreement."""


# def configure(api_key: str):
#     genai.configure(api_key=api_key)


# def new_chat(api_key: str):
#     configure(api_key)
#     model = genai.GenerativeModel(
#         model_name=MODEL_NAME, system_instruction=SYSTEM_PROMPT, tools=TOOL_SCHEMA,
#     )
#     return model.start_chat(history=[])

def configure(api_key: str):
    global _groq_client
    _groq_client = Groq(api_key=api_key)


def new_chat(api_key: str):
    configure(api_key)
    return {"messages": [{"role": "system", "content": SYSTEM_PROMPT}]}


def build_document_index():
    return documents.build_index()





def run_turn(chat, account_id: str, index, user_message: str):
    """Runs one user turn to completion, executing tool calls along the way.

    Returns (final_text, tool_log, pending_action). pending_action is set when the
    model wants to create an escalation and is waiting on the user to confirm it.
    """
    tool_log = []
    pending_action = None
    
    # Build message list for Groq (includes chat history)
    messages = chat["messages"].copy()
    messages.append({"role": "user", "content": user_message})
    
    # First call to Groq
    response = _send_with_retry(messages)

    for _ in range(MAX_TOOL_ROUNDS):
        # Check if Groq returned any tool calls
        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            break

        # Add assistant's response to message history
        messages.append({
            "role": "assistant",
            "content": response.choices[0].message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ],
        })

        # Execute each tool and collect results
        tool_results = []
        for call in tool_calls:
            name = call.function.name
            # Groq returns arguments as a JSON string, need to parse it
            args = json.loads(call.function.arguments)
            tool_log.append({"name": name, "args": args})

            if name == "search_policies":
                result = tools.search_policies(account_id, index, **args)
            elif name == "get_account_data":
                result = tools.get_account_data(account_id, **args)
            elif name == "create_escalation_draft":
                result = tools.create_escalation_draft(account_id, **args)
                if "error" not in result:
                    pending_action = {"kind": "escalation", "account_id": account_id, **args}
            elif name == "cancel_order_draft":
                result = tools.cancel_order_draft(account_id, **args)
                if "error" not in result:
                    pending_action = {
                        "kind": "cancel_order",
                        "account_id": account_id,
                        "order_id": result["order_id"],
                        "fee_inr": result.get("fee_inr"),
                        "reason": result.get("reason"),
                    }
            else:
                result = {"error": f"Unknown tool {name}"}

            tool_results.append({
                "tool_call_id": call.id,
                "role": "tool",
                "content": json.dumps(result),
            })

        # Add tool results to message history
        messages.extend(tool_results)

        # Call Groq again with the tool results
        response = _send_with_retry(messages)

    # Save the updated message history back to chat
    chat["messages"] = messages

    # Extract final text from Groq's response
    final_text = response.choices[0].message.content or ""
    return final_text, tool_log, pending_action