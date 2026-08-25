"""The agent's three tools, each mapped to one required tool category:

  - search_policies         -> document search / retrieval
  - get_account_data        -> structured-data lookup + calculation
  - create_escalation_draft -> the mocked state-changing action (confirmed in app.py)

Access control lives here, not in the prompt: every function takes the session's
authenticated account_id as a hidden first argument supplied by app.py, never by the
model. The model has no parameter through which it could ask for another customer's
data -- there is nothing to prompt-inject its way around.
"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

import business_rules
import data_store
import documents

ORDER_FIELDS = [
    "order_id", "account_id", "carrier", "status", "booked_at",
    "pickup_window_start", "pickup_window_end", "pickup_actual_at",
    "shipment_fee_inr", "carrier_fault", "customer_fault",
    "cancellation_requested_at", "notes",
]
TICKET_FIELDS = [
    "ticket_id", "account_id", "created_at", "status", "subject", "description",
    "channel", "assigned_to", "last_customer_message_at", "historical_resolution",
]


def _jsonable(value):
    """Recursively converts pandas/numpy values into plain JSON-safe Python types."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return None if pd.isna(value) else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if math.isnan(value) else float(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def search_policies(account_id: str, index, query: str):
    """Search policies, SOPs, product docs, and signed customer agreements."""
    results = documents.search(index, query, top_k=4)
    return _jsonable({"query": query, "results": results})


def get_account_data(account_id: str, order_id: str | None = None,
                      ticket_id: str | None = None, severity: str | None = None):
    """Scoped structured-data lookup + deterministic calculations for the logged-in
    account only. An order_id/ticket_id belonging to another account is treated as
    not found -- it is never fetched, let alone returned."""
    account = data_store.get_account(account_id)
    overrides = business_rules.get_overrides(account_id)
    sla_targets = business_rules.get_sla_targets(account, overrides)
    now = data_store.NOW

    response = {
        "account": {
            "account_id": account["account_id"],
            "name": account["account_name"],
            "plan": account["plan"],
            "premium_support": bool(account["premium_support"]),
        },
        "sla_targets": sla_targets,
        "contract_notes": (overrides or {}).get("notes", []),
        # Always included (not just when asked "list my stuff") so a follow-up like
        # "what's the status of ESC-1001" is answerable without a separate tool --
        # the alternative, an escalation_id lookup parameter, failed in practice
        # because the model had no reason to know an escalation tool existed.
        "escalations_on_this_account": data_store.list_escalations_for_account(account_id),
    }

    if order_id:
        order = data_store.get_order(account_id, order_id)
        if order is None:
            response["order_error"] = f"No order {order_id} found on this account."
        else:
            order_view = {k: order[k] for k in ORDER_FIELDS}
            order_view["cancellation"] = business_rules.evaluate_cancellation(order, overrides, now)
            order_view["service_credit"] = business_rules.evaluate_service_credit(order, overrides, now)
            response["order"] = order_view

    if ticket_id:
        ticket = data_store.get_ticket(account_id, ticket_id)
        if ticket is None:
            response["ticket_error"] = f"No ticket {ticket_id} found on this account."
        else:
            ticket_view = {k: ticket[k] for k in TICKET_FIELDS}
            if severity:
                ticket_view["sla"] = business_rules.evaluate_sla_breach(ticket, severity, sla_targets, now)
            response["ticket"] = ticket_view

    if not order_id and not ticket_id:
        response["orders"] = [
            {k: o[k] for k in ["order_id", "carrier", "status", "booked_at"]}
            for o in data_store.list_orders_for_account(account_id)
        ]
        response["tickets"] = [
            {k: t[k] for k in ["ticket_id", "status", "subject", "created_at"]}
            for t in data_store.list_tickets_for_account(account_id)
        ]

    return _jsonable(response)


def create_escalation_draft(account_id: str, category: str, summary: str,
                             order_id: str | None = None, ticket_id: str | None = None):
    """Prepares an escalation but does NOT create it. app.py intercepts this call,
    shows the draft to the user, and only calls data_store.create_escalation_record(...)
    after an explicit Confirm click -- the model cannot make this action happen by
    itself, no matter what it is told or tricked into saying."""
    if order_id and data_store.get_order(account_id, order_id) is None:
        return _jsonable({"error": f"No order {order_id} found on this account; cannot escalate it."})
    if ticket_id and data_store.get_ticket(account_id, ticket_id) is None:
        return _jsonable({"error": f"No ticket {ticket_id} found on this account; cannot escalate it."})

    return _jsonable({
        "status": "awaiting_confirmation",
        "category": category,
        "summary": summary,
        "order_id": order_id,
        "ticket_id": ticket_id,
        "message": "Draft prepared. Waiting for the user to confirm in the interface "
                   "before this is actually created.",
    })
