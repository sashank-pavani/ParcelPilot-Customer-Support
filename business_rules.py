"""Deterministic business-rule calculations, encoded as plain Python so financial
numbers are exact and reproducible -- the model is never asked to do this arithmetic
itself, only to decide when to call it and how to explain the result in words.

The constants below are transcribed from the supplied policy/contract PDFs (treated
the way a real support tool would treat terms already ingested from a contract
management system, rather than re-parsing a PDF on every request). The original PDF
text is still searchable through the search_policies tool so any answer can be cited
and independently verified against the source.

Simplification, stated up front: response-time targets are expressed by the source
documents in mixed units (minutes, business hours, business days). This app compares
them using plain wall-clock elapsed time rather than modeling a business-hour/weekday
calendar, since the dataset's timestamps all fall within a single day. This is a
deliberate scope cut, not an oversight -- see the architecture note.
"""
import math

import pandas as pd

MANAGER_APPROVAL_THRESHOLD_INR = 1000

# 01_Support_Policy_v3_CURRENT.pdf -- Support Policy v3, CURRENT, effective 2026-05-01
DEFAULT_SLA_BY_PLAN = {
    "Enterprise": {"P1": "30 minutes, 24x7", "P2": "2 hours", "P3": "1 business day"},
    "Growth": {"P1": "2 business hours", "P2": "4 business hours", "P3": "2 business days"},
    "Standard": {"P1": "4 business hours", "P2": "1 business day", "P3": "2 business days"},
}
DEFAULT_SLA_SOURCE = "01_Support_Policy_v3_CURRENT.pdf (Support Policy v3, CURRENT)"

SEVERITY_DEFINITIONS = {
    "P1": "Critical: complete production outage preventing all shipment creation, a "
          "confirmed security incident / suspected credential exposure, or another "
          "event causing immediate material business risk with no workaround.",
    "P2": "High: a major feature is unavailable or materially degraded, but core "
          "operations remain possible or a workaround exists.",
    "P3": "Normal: minor defect, how-to question, configuration request, or an issue "
          "with limited operational impact.",
}

# 03_Cancellation_and_Service_Credit_SOP_v4.pdf -- SOP v4, CURRENT, effective 2026-06-15
DEFAULT_CANCELLATION = {"free_window_minutes": 30, "fee_inr": 250}
DEFAULT_SERVICE_CREDIT = {"threshold_hours": 2, "cap_inr": 500, "pct_of_fee": 0.10}
SOP_SOURCE = "03_Cancellation_and_Service_Credit_SOP_v4.pdf (SOP v4, CURRENT)"

# Signed customer agreements override the defaults above wherever they say so.
CONTRACT_OVERRIDES = {
    "ACCT-001": {  # Northstar Logistics
        "source_file": "05_Northstar_Logistics_Enterprise_Agreement.pdf",
        "sla": {"P1": "15 minutes, 24x7", "P2": "1 hour", "P3": "8 business hours"},
        "cancellation_fee_waiver": True,
        "service_credit": None,  # no override specified -> current SOP applies
        "monthly_credit_cap_inr": 5000,
        "notes": [
            "Monthly aggregate service credits are capped at INR 5,000 under this "
            "agreement; this tool reports a single calculation and does not sum "
            "credits already issued earlier in the month.",
        ],
    },
    "ACCT-002": {  # LumenWorks
        "source_file": "06_LumenWorks_Service_Agreement.pdf",
        "sla": {"P1": "2 business hours", "P2": "4 business hours", "P3": "2 business days"},
        "cancellation_fee_waiver": False,
        "service_credit": {"threshold_hours": 4, "fixed_amount_inr": 300},
        "monthly_credit_cap_inr": None,
        "notes": ["No weekend or after-hours support coverage under this agreement."],
    },
}


def get_overrides(account_id: str):
    return CONTRACT_OVERRIDES.get(account_id)


def get_sla_targets(account: dict, overrides: dict | None) -> dict:
    if overrides and overrides.get("sla"):
        return {"targets": overrides["sla"], "source": overrides["source_file"]}
    plan = account["plan"]
    return {"targets": DEFAULT_SLA_BY_PLAN.get(plan, {}), "source": DEFAULT_SLA_SOURCE}


def _minutes_between(later, earlier):
    if pd.isna(later) or pd.isna(earlier):
        return None
    return (later - earlier).total_seconds() / 60.0


def evaluate_cancellation(order: dict, overrides: dict | None, now) -> dict:
    status = order["status"]

    if status == "DRAFT":
        return {"cancellable": True, "fee_inr": 0,
                "reason": f"Draft shipments may be cancelled free of charge ({SOP_SOURCE} S1)."}

    if status == "BOOKED":
        if overrides and overrides.get("cancellation_fee_waiver"):
            return {"cancellable": True, "fee_inr": 0,
                    "reason": f"{overrides['source_file']} waives the cancellation fee "
                              f"for BOOKED shipments before pickup, regardless of how "
                              f"long ago the shipment was booked."}

        requested_at = order.get("cancellation_requested_at")
        if pd.isna(requested_at):
            reference, basis = now, "As of right now"
        else:
            reference, basis = requested_at, "At the time cancellation was requested"

        elapsed = _minutes_between(reference, order["booked_at"])
        within_window = elapsed <= DEFAULT_CANCELLATION["free_window_minutes"]
        fee = 0 if within_window else DEFAULT_CANCELLATION["fee_inr"]
        return {
            "cancellable": True,
            "fee_inr": fee,
            "reason": f"{basis}, {elapsed:.0f} minutes will have passed since booking, "
                      f"{'within' if within_window else 'past'} the "
                      f"{DEFAULT_CANCELLATION['free_window_minutes']}-minute free window "
                      f"({SOP_SOURCE} S1). No contract waiver applies for this account, so "
                      f"the default fee is INR {fee}.",
        }

    if status == "PICKED_UP":
        return {"cancellable": False, "fee_inr": None,
                "reason": f"This shipment has already been picked up, so cancellation is "
                          f"not permitted -- use the return-to-origin workflow instead "
                          f"({SOP_SOURCE} S1)."}

    return {"cancellable": False, "fee_inr": None,
            "reason": f"Shipment status is {status}; delivered shipments cannot be "
                      f"cancelled ({SOP_SOURCE} S1)."}


def evaluate_service_credit(order: dict, overrides: dict | None, now) -> dict:
    window_end = order["pickup_window_end"]
    pickup_actual = order.get("pickup_actual_at")
    reference_time = pickup_actual if not pd.isna(pickup_actual) else now
    delay_minutes = _minutes_between(reference_time, window_end)
    delay_hours = max(0.0, (delay_minutes or 0.0) / 60.0)

    override = overrides.get("service_credit") if overrides else None
    threshold = override["threshold_hours"] if override else DEFAULT_SERVICE_CREDIT["threshold_hours"]
    source = overrides["source_file"] if override else SOP_SOURCE

    carrier_fault = order.get("carrier_fault")
    customer_fault = order.get("customer_fault")
    fault_unknown = carrier_fault is None or (isinstance(carrier_fault, float) and math.isnan(carrier_fault))

    if fault_unknown:
        return {"eligible": None, "amount_inr": None,
                "reason": f"Carrier-fault status is unknown for this order. Per {SOP_SOURCE} "
                          f"S3, do not promise a credit until fault is confirmed -- this "
                          f"should be escalated for investigation instead."}

    if delay_hours <= threshold:
        return {"eligible": False, "amount_inr": 0,
                "reason": f"Pickup delay is {delay_hours:.1f} hours, at or below the "
                          f"{threshold}-hour threshold ({source}). Not eligible."}

    if not carrier_fault:
        return {"eligible": False, "amount_inr": 0,
                "reason": f"Pickup was {delay_hours:.1f} hours late, but the carrier was "
                          f"not at fault, which {source} requires. Not eligible."}

    if customer_fault:
        return {"eligible": False, "amount_inr": 0,
                "reason": "Order notes indicate a customer-caused issue, which disqualifies "
                          "the delay from a service credit regardless of how late it was."}

    if override:
        amount = override["fixed_amount_inr"]
        reason = (f"Pickup was {delay_hours:.1f} hours late (past the {threshold}-hour "
                  f"threshold), carrier at fault, no customer fault. {overrides['source_file']} "
                  f"sets a fixed INR {amount} credit for this account, replacing the default "
                  f"SOP formula.")
    else:
        amount = min(DEFAULT_SERVICE_CREDIT["cap_inr"],
                     DEFAULT_SERVICE_CREDIT["pct_of_fee"] * order["shipment_fee_inr"])
        reason = (f"Pickup was {delay_hours:.1f} hours late (past the {threshold}-hour "
                  f"default threshold), carrier at fault, no customer fault. Default credit "
                  f"is the lower of INR {DEFAULT_SERVICE_CREDIT['cap_inr']} or "
                  f"{DEFAULT_SERVICE_CREDIT['pct_of_fee'] * 100:.0f}% of the shipment fee "
                  f"({SOP_SOURCE} S2) = INR {amount:.0f}.")

    result = {"eligible": True, "amount_inr": round(amount, 2), "reason": reason,
              "needs_manager_approval": amount > MANAGER_APPROVAL_THRESHOLD_INR}
    if overrides and overrides.get("monthly_credit_cap_inr"):
        result["caveat"] = (f"This account's contract caps monthly aggregate service "
                            f"credits at INR {overrides['monthly_credit_cap_inr']}; this "
                            f"figure is not checked against credits already issued this "
                            f"month.")
    return result


def evaluate_sla_breach(ticket: dict, severity: str, targets: dict, now) -> dict:
    if severity not in ("P1", "P2", "P3"):
        return {"error": f"Unknown severity '{severity}'; must be P1, P2, or P3."}
    elapsed_minutes = _minutes_between(now, ticket["created_at"])
    return {
        "severity": severity,
        "severity_definition": SEVERITY_DEFINITIONS[severity],
        "target": targets["targets"].get(severity, "unknown"),
        "target_source": targets["source"],
        "minutes_since_created": round(elapsed_minutes, 1) if elapsed_minutes is not None else None,
        "note": "This target is expressed in the source document's own units (minutes / "
                "business hours / business days). This figure is plain wall-clock elapsed "
                "minutes, not a business-hour calendar, so treat comparisons against "
                "multi-hour or multi-day targets as approximate.",
    }
