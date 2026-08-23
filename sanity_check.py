"""Quick, offline sanity check for the deterministic business-rule calculations --
no API key or network access needed.

Run: python sanity_check.py

Prints the cancellation/service-credit outcome for every order, and the SLA target for
every ticket at each severity, so the logic can be eyeballed against the source PDFs
before wiring it up to the LLM.
"""
import data_store
import business_rules as rules

print(f"Reference 'now' (dataset snapshot): {data_store.NOW}\n")

print("=== Orders ===")
for order in data_store.ORDERS.to_dict("records"):
    overrides = rules.get_overrides(order["account_id"])
    cancellation = rules.evaluate_cancellation(order, overrides, data_store.NOW)
    credit = rules.evaluate_service_credit(order, overrides, data_store.NOW)
    print(f"{order['order_id']} ({order['account_id']}, {order['status']})")
    print(f"  cancellation   : {cancellation}")
    print(f"  service_credit : {credit}\n")

print("=== Tickets ===")
for ticket in data_store.TICKETS.to_dict("records"):
    account = data_store.get_account(ticket["account_id"])
    overrides = rules.get_overrides(ticket["account_id"])
    targets = rules.get_sla_targets(account, overrides)
    print(f"{ticket['ticket_id']} ({ticket['account_id']}): {ticket['subject']}")
    for severity in ("P1", "P2", "P3"):
        result = rules.evaluate_sla_breach(ticket, severity, targets, data_store.NOW)
        print(f"  {severity}: target={result['target']!r} elapsed_min={result['minutes_since_created']}")
    print()
