"""Loads ParcelPilot's structured data (accounts, orders, tickets) from the supplied
workbook and exposes small, account-scoped helper functions.

All financial and date math in this app happens here or in business_rules.py, never
inside a prompt, so the numbers Streamlit shows are exact and reproducible.
"""
import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
WORKBOOK_PATH = DATA_DIR / "ParcelPilot_Assessment_Data.xlsx"
ESCALATIONS_PATH = DATA_DIR / "escalations.json"

_DATE_COLUMNS_ORDERS = [
    "booked_at", "pickup_window_start", "pickup_window_end",
    "pickup_actual_at", "cancellation_requested_at",
]
_DATE_COLUMNS_TICKETS = ["created_at", "last_customer_message_at"]


def _load_workbook():
    accounts = pd.read_excel(WORKBOOK_PATH, sheet_name="accounts")
    orders = pd.read_excel(WORKBOOK_PATH, sheet_name="orders", parse_dates=_DATE_COLUMNS_ORDERS)
    tickets = pd.read_excel(WORKBOOK_PATH, sheet_name="tickets", parse_dates=_DATE_COLUMNS_TICKETS)
    readme = pd.read_excel(WORKBOOK_PATH, sheet_name="README", header=None)
    return accounts, orders, tickets, readme


ACCOUNTS, ORDERS, TICKETS, _README = _load_workbook()


def _readme_value(label: str) -> str:
    row = _README[_README[0] == label]
    return str(row.iloc[0, 1]) if not row.empty else ""


# Every "current time" question in this assessment is answered relative to the dataset
# snapshot time stated in the workbook's README sheet, not the real wall clock -- this
# keeps answers reproducible no matter when the app is actually run or graded.
_snapshot = _readme_value("Dataset snapshot")
NOW = pd.to_datetime(" ".join(_snapshot.split()[:2]))
CURRENCY = _readme_value("Currency") or "INR"


def list_accounts():
    """The small list of demo accounts, for the 'log in as' selector only."""
    return ACCOUNTS[["account_id", "account_name", "plan"]].to_dict("records")


def get_account(account_id: str):
    row = ACCOUNTS[ACCOUNTS["account_id"] == account_id]
    return row.iloc[0].to_dict() if not row.empty else None


def get_order(account_id: str, order_id: str):
    """Returns the order only if it belongs to account_id. This is the access-control
    boundary: a caller can never fetch another account's order by guessing its ID."""
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
    """Marks the order CANCELLED in memory for this process. The Excel workbook is
    not rewritten -- restarting the app reloads the original snapshot."""
    mask = (ORDERS["order_id"] == order_id) & (ORDERS["account_id"] == account_id)
    if not mask.any():
        return None
    ORDERS.loc[mask, "status"] = "CANCELLED"
    ORDERS.loc[mask, "cancellation_requested_at"] = NOW
    return get_order(account_id, order_id)


def _load_escalations():
    if ESCALATIONS_PATH.exists():
        return json.loads(ESCALATIONS_PATH.read_text())
    return []


def list_escalations_for_account(account_id: str):
    return [e for e in _load_escalations() if e["account_id"] == account_id]


def create_escalation_record(account_id: str, category: str, summary: str,
                              order_id: str | None, ticket_id: str | None):
    """Mocked state-changing action: appends a new escalation to a local JSON file.
    Only ever called after the user clicks Confirm in the UI -- see app.py."""
    escalations = _load_escalations()
    new_id = f"ESC-{1000 + len(escalations) + 1}"
    record = {
        "escalation_id": new_id,
        "account_id": account_id,
        "category": category,
        "summary": summary,
        "order_id": order_id,
        "ticket_id": ticket_id,
        # This mock has no support team actually working the queue, so every
        # escalation sits at "submitted" forever -- stated plainly rather than
        # fabricating a status the system has no way to know.
        "status": "submitted (this demo does not simulate support-team resolution)",
        "created_at": NOW.strftime("%Y-%m-%d %H:%M"),
    }
    escalations.append(record)
    ESCALATIONS_PATH.write_text(json.dumps(escalations, indent=2))
    return record
