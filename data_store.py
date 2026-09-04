"""Loads ParcelPilot's structured data (accounts, orders, tickets) from Supabase.

All financial and date math in this app happens here or in business_rules.py, never
inside a prompt, so the numbers Streamlit shows are exact and reproducible.
"""
import os
import json
from pathlib import Path

import pandas as pd
from supabase import create_client

DATA_DIR = Path(__file__).parent / "data"
ESCALATIONS_PATH = DATA_DIR / "escalations.json"

_DATE_COLUMNS_ORDERS = [
    "booked_at", "pickup_window_start", "pickup_window_end",
    "pickup_actual_at", "cancellation_requested_at",
]
_DATE_COLUMNS_TICKETS = ["created_at", "last_customer_message_at"]

_supabase = None


def _get_client():
    global _supabase
    if _supabase is None:
        _supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _supabase


def _parse_dates(records: list, date_cols: list) -> list:
    for r in records:
        for col in date_cols:
            if col in r and r[col]:
                r[col] = pd.to_datetime(r[col])
            elif col in r:
                r[col] = pd.NaT
    return records


def _load_data():
    client = _get_client()
    accounts = pd.DataFrame(client.table("accounts").select("*").execute().data)
    orders_raw = client.table("orders").select("*").execute().data
    _parse_dates(orders_raw, _DATE_COLUMNS_ORDERS)
    orders = pd.DataFrame(orders_raw)
    tickets_raw = client.table("tickets").select("*").execute().data
    _parse_dates(tickets_raw, _DATE_COLUMNS_TICKETS)
    tickets = pd.DataFrame(tickets_raw)
    return accounts, orders, tickets


ACCOUNTS, ORDERS, TICKETS = _load_data()

# Keep NOW tied to the dataset snapshot for reproducibility
_WORKBOOK = DATA_DIR / "ParcelPilot_Assessment_Data.xlsx"
_readme = pd.read_excel(_WORKBOOK, sheet_name="README", header=None)
_snapshot = str(_readme[_readme[0] == "Dataset snapshot"].iloc[0, 1])
NOW = pd.to_datetime(" ".join(_snapshot.split()[:2]))
CURRENCY = "INR"


def list_accounts():
    return ACCOUNTS[["account_id", "account_name", "plan"]].to_dict("records")


def get_account(account_id: str):
    row = ACCOUNTS[ACCOUNTS["account_id"] == account_id]
    return row.iloc[0].to_dict() if not row.empty else None


def get_order(account_id: str, order_id: str):
    row = ORDERS[(ORDERS["order_id"] == order_id) & (ORDERS["account_id"] == account_id)]
    return row.iloc[0].to_dict() if not row.empty else None


def get_ticket(account_id: str, ticket_id: str):
    row = TICKETS[(TICKETS["ticket_id"] == ticket_id) & (TICKETS["account_id"] == account_id)]
    return row.iloc[0].to_dict() if not row.empty else None


def list_orders_for_account(account_id: str):
    return ORDERS[ORDERS["account_id"] == account_id].to_dict("records")


def list_tickets_for_account(account_id: str):
    return TICKETS[TICKETS["account_id"] == account_id].to_dict("records")


def cancel_order(account_id: str, order_id: str):
    """Marks the order CANCELLED in Supabase and in the in-memory dataframe."""
    mask = (ORDERS["order_id"] == order_id) & (ORDERS["account_id"] == account_id)
    if not mask.any():
        return None
    ORDERS.loc[mask, "status"] = "CANCELLED"
    ORDERS.loc[mask, "cancellation_requested_at"] = NOW
    _get_client().table("orders").update({
        "status": "CANCELLED",
        "cancellation_requested_at": NOW.isoformat(),
    }).eq("order_id", order_id).eq("account_id", account_id).execute()
    return get_order(account_id, order_id)


def list_escalations_for_account(account_id: str):
    try:
        result = _get_client().table("escalations").select("*").eq("account_id", account_id).execute()
        return result.data
    except Exception:
        return []


def create_escalation_record(account_id: str, category: str, summary: str,
                              order_id: str | None, ticket_id: str | None):
    """Creates escalation in Supabase. Only called after user clicks Confirm."""
    existing = list_escalations_for_account(account_id)
    new_id = f"ESC-{1000 + len(existing) + 1}"
    record = {
        "escalation_id": new_id,
        "account_id": account_id,
        "category": category,
        "summary": summary,
        "order_id": order_id,
        "ticket_id": ticket_id,
        "status": "submitted (this demo does not simulate support-team resolution)",
        "created_at": NOW.isoformat(),
    }
    _get_client().table("escalations").insert(record).execute()
    return record
