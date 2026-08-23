"""A small, manual function-calling loop around Gemini.

Kept manual rather than using the SDK's automatic-function-calling mode for two
reasons: (1) the interface needs to show which tool ran and with what arguments, and
(2) the escalation tool must pause for a human "Confirm" click instead of executing
itself the moment the model calls it.
"""
import os

import google.generativeai as genai

import documents
import tools

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
MAX_TOOL_ROUNDS = 6

TOOL_SCHEMA = [{
    "function_declarations": [
        {
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
        {
            "name": "get_account_data",
            "description": (
                "Look up the logged-in customer's own account, orders, and tickets, "
                "and get deterministic calculations: cancellation fee, service-credit "
                "eligibility and amount, and SLA target vs. elapsed time. Only ever "
                "returns data for the current account. Pass severity ('P1', 'P2', or "
                "'P3') once you have classified a ticket's severity, to check it "
                "against the SLA target."
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
        {
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
    ],
}]

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

For failed-pickup or cancellation questions, call get_account_data with the relevant \
order_id and use the returned cancellation/service_credit fields directly rather than \
computing amounts yourself. For ticket severity or SLA questions, first classify the \
severity (P1/P2/P3) using the definitions surfaced by search_policies, then call \
get_account_data again with that severity to get the exact target and elapsed time.

If a response-time target already appears breached, say so plainly instead of \
softening it. If the request needs human judgment, an exception to policy, or an \
action you cannot perform, or if key facts are missing or contradictory, prepare an \
escalation with create_escalation_draft and explain why -- do not guess or promise an \
outcome you are not sure of. An escalation only takes effect once the user confirms \
it in the interface.

Be concise and specific. When you state a policy fact, name the source document and \
whether it is current, deprecated, or a signed agreement."""


def configure(api_key: str):
    genai.configure(api_key=api_key)


def new_chat(api_key: str):
    configure(api_key)
    model = genai.GenerativeModel(
        model_name=MODEL_NAME, system_instruction=SYSTEM_PROMPT, tools=TOOL_SCHEMA,
    )
    return model.start_chat(history=[])


def build_document_index():
    return documents.build_index()


def _function_call(response):
    for part in response.candidates[0].content.parts:
        if getattr(part, "function_call", None) and part.function_call.name:
            return part.function_call
    return None


def _response_text(response):
    texts = [part.text for part in response.candidates[0].content.parts if getattr(part, "text", None)]
    return "\n".join(texts).strip()


def run_turn(chat, account_id: str, index, user_message: str):
    """Runs one user turn to completion, executing tool calls along the way.

    Returns (final_text, tool_log, pending_action). pending_action is set when the
    model wants to create an escalation and is waiting on the user to confirm it.
    """
    tool_log = []
    pending_action = None
    response = chat.send_message(user_message)

    for _ in range(MAX_TOOL_ROUNDS):
        call = _function_call(response)
        if call is None:
            break

        name = call.name
        args = dict(call.args)
        tool_log.append({"name": name, "args": args})

        if name == "search_policies":
            result = tools.search_policies(account_id, index, **args)
        elif name == "get_account_data":
            result = tools.get_account_data(account_id, **args)
        elif name == "create_escalation_draft":
            result = tools.create_escalation_draft(account_id, **args)
            if "error" not in result:
                pending_action = {"account_id": account_id, **args}
        else:
            result = {"error": f"Unknown tool {name}"}

        response = chat.send_message(genai.protos.Content(parts=[genai.protos.Part(
            function_response=genai.protos.FunctionResponse(name=name, response={"result": result})
        )]))

    return _response_text(response), tool_log, pending_action
