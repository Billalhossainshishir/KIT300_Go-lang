"""Receipt-backed simulated basket and checkout.

Every basket line carries the signed receipt that admitted it. The server
re-reads and verifies that receipt instead of trusting browser state. Local JSON
state is updated atomically and protected by an in-process lock so concurrent
requests cannot silently overwrite each other.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from threading import RLock

from ramify.crypto.canonical import rfc3339_nano
from ramify.crypto.sign import seal, verify_receipt
from ramify.data import seed
from ramify.receipt import store
from ramify.storage import read_json, write_json_atomic
from ramify.timing import now

CART_NAME = "cart.json"
DEMO_CART_NAME = "david_demo_cart.json"
BASKET_ACTIONS = (
    "add_to_mock_cart",
    "purchase_autonomously",
)
_CART_LOCK = RLock()


class CartRefused(Exception):
    """Raised when a line or checkout cannot proceed safely."""


def _cart_path(cart_name: str = CART_NAME) -> Path:
    from ramify.crypto import keys

    directory = keys.local_data_store()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / cart_name


def _read(cart_name: str = CART_NAME) -> dict:
    cart = read_json(_cart_path(cart_name), lambda: {"lines": [], "orders": [], "requisitions": []})
    if not isinstance(cart, dict):
        raise CartRefused("The local basket store is not a JSON object.")
    if (
        not isinstance(cart.get("lines", []), list)
        or not isinstance(cart.get("orders", []), list)
        or not isinstance(cart.get("requisitions", []), list)
    ):
        raise CartRefused("The local transaction store has an unexpected structure.")
    cart.setdefault("lines", [])
    cart.setdefault("orders", [])
    cart.setdefault("requisitions", [])
    return cart


def _write(cart: dict, cart_name: str = CART_NAME) -> None:
    write_json_atomic(_cart_path(cart_name), cart)


def _permitted_transaction_actions(receipt: dict) -> set[str]:
    permitted = set(receipt.get("permitted_actions", []))
    permitted.update(receipt.get("human_authorised_actions", []))
    return permitted


def _assert_receipt_authority(
    receipt: dict, *, required_any: tuple[str, ...] | set[str] | None = None
) -> None:
    """Require intact, current and action-appropriate one-time authority."""
    if receipt.get("assessment_context") != "purchase":
        raise CartRefused(
            "This receipt came from an exploratory/demo check, not an active purchase journey."
        )

    report = verify_receipt(receipt, now=now())
    if not report.get("purchase_authority_valid"):
        failed = [c["name"] for c in report.get("checks", []) if not c.get("passed")]
        detail = ", ".join(failed) or "integrity/validity check"
        raise CartRefused(
            f"This receipt is no longer valid purchase authority ({detail}). Run the check again."
        )

    receipt_id = receipt.get("receipt_id", "")
    if receipt_id and store.has_successor(receipt_id):
        raise CartRefused(
            "This receipt has been superseded by a later decision and is no longer transaction authority."
        )

    if required_any:
        permitted = _permitted_transaction_actions(receipt)
        required = set(required_any)
        if not permitted.intersection(required):
            raise CartRefused(
                f"The signed decision was {receipt.get('actor_decision', 'unknown')} and permits "
                f"{', '.join(sorted(permitted)) or 'no transaction action'}, not the requested transaction path."
            )


def _receipt_already_used(cart: dict, receipt_id: str) -> bool:
    if any(line.get("receipt_ref") == receipt_id for line in cart.get("lines", [])):
        return True
    if any(
        line.get("receipt_ref") == receipt_id
        for order in cart.get("orders", [])
        for line in order.get("lines", [])
    ):
        return True
    return any(req.get("receipt_ref") == receipt_id for req in cart.get("requisitions", []))


def _receipt_consumed(cart: dict, receipt_id: str) -> bool:
    """Whether one-time authority has already produced a completed transaction."""
    if any(
        line.get("receipt_ref") == receipt_id
        for order in cart.get("orders", [])
        for line in order.get("lines", [])
    ):
        return True
    return any(
        req.get("receipt_ref") == receipt_id
        or any(line.get("receipt_ref") == receipt_id for line in req.get("lines", []))
        for req in cart.get("requisitions", [])
    )


def contents(cart_name: str = CART_NAME) -> dict:
    with _CART_LOCK:
        cart = _read(cart_name)
        lines = list(cart["lines"])
        return {
            "lines": lines,
            "line_count": len(lines),
            "item_count": sum(int(line.get("quantity", 0)) for line in lines),
            "total_cents": sum(int(line.get("line_total_cents", 0)) for line in lines),
            "orders": cart.get("orders", [])[-10:][::-1],
            "requisitions": cart.get("requisitions", [])[-10:][::-1],
        }


def add(receipt_id: str, *, cart_name: str = CART_NAME, record_action: bool = True) -> dict:
    """Add one transaction line on the authority of one signed receipt."""
    receipt = store.get(receipt_id)
    if receipt is None:
        raise CartRefused("That receipt is not in the ledger.")

    _assert_receipt_authority(receipt, required_any=BASKET_ACTIONS)

    order = receipt.get("order")
    if not isinstance(order, dict) or any(
        order.get(field) is None
        for field in ("quantity", "unit_price_cents", "line_total_cents")
    ):
        raise CartRefused(
            "This receipt carries no complete signed price/quantity values, so it cannot enter the basket."
        )
    try:
        quantity = int(order["quantity"])
        unit_price = int(order["unit_price_cents"])
        line_total = int(order["line_total_cents"])
    except (TypeError, ValueError) as exc:
        raise CartRefused("The signed order values are not valid integers.") from exc
    if quantity < 1 or unit_price < 0 or line_total != unit_price * quantity:
        raise CartRefused("The signed order values are internally inconsistent.")

    subject = seed.subject(receipt["subject_ref"]) or {}

    with _CART_LOCK:
        cart = _read(cart_name)
        if _receipt_already_used(cart, receipt["receipt_id"]):
            raise CartRefused(
                "This receipt has already been used for a basket/order line. "
                "Run the check again for a new transaction."
            )

        line = {
            "line_id": uuid.uuid4().hex[:12],
            "subject_ref": receipt["subject_ref"],
            "product_name": receipt.get("product_name", ""),
            "brand": subject.get("brand", ""),
            "quantity": quantity,
            "unit_price_cents": unit_price,
            "line_total_cents": line_total,
            "receipt_ref": receipt["receipt_id"],
            "payload_hash": receipt["payload_hash"],
            "actor_ref": receipt["actor_ref"],
            "actor_label": receipt["actor_label"],
            "objective_posture": receipt["objective_posture"],
            "actor_decision": receipt["actor_decision"],
            "unattended": receipt.get("selected_action") == "purchase_autonomously",
            "human_authorised": bool(receipt.get("human_authorised_actions")),
            "human_review_outcome": (receipt.get("human_review") or {}).get("outcome"),
            "supersedes_receipt": receipt.get("supersedes_receipt"),
            "added_at": rfc3339_nano(now()),
        }
        cart["lines"].append(line)
        _write(cart, cart_name)

    actual_action = (
        "purchase_autonomously"
        if receipt.get("selected_action") == "purchase_autonomously"
        else "add_to_mock_cart"
    )
    if record_action:
        _record_transaction_action(receipt, actual_action)
    return line


def _record_transaction_action(receipt: dict, action: str) -> None:
    """Record the real staged action once, even if Step 4 was skipped."""
    store.record_action_once(
        {
            "event_id": f"ramify:demo:act:{uuid.uuid4().hex}",
            "action": action,
            "receipt_ref": receipt["receipt_id"],
            "receipt_hash": receipt["payload_hash"],
            "subject_ref": receipt["subject_ref"],
            "product_name": receipt.get("product_name", ""),
            "actor_ref": receipt["actor_ref"],
            "actor_label": receipt["actor_label"],
            "actor_decision": receipt["actor_decision"],
            "recorded_at": rfc3339_nano(now()),
            "simulated": True,
            "notice": "Simulated transaction step recorded. No money or inventory moved.",
        }
    )


def create_requisition(receipt_id: str, *, cart_name: str = CART_NAME, record_action: bool = True) -> dict:
    """Create a signed simulated requisition without putting it in the consumer basket."""
    receipt = store.get(receipt_id)
    if receipt is None:
        raise CartRefused("That receipt is not in the ledger.")
    _assert_receipt_authority(receipt, required_any={"create_mock_requisition"})

    order = receipt.get("order")
    if not isinstance(order, dict) or any(
        order.get(field) is None for field in ("quantity", "unit_price_cents", "line_total_cents")
    ):
        raise CartRefused("This receipt carries no complete signed price/quantity values.")
    try:
        quantity = int(order["quantity"])
        unit_price = int(order["unit_price_cents"])
        line_total = int(order["line_total_cents"])
    except (TypeError, ValueError) as exc:
        raise CartRefused("The signed order values are not valid integers.") from exc
    if quantity < 1 or unit_price < 0 or line_total != unit_price * quantity:
        raise CartRefused("The signed order values are internally inconsistent.")

    with _CART_LOCK:
        cart = _read(cart_name)
        if _receipt_already_used(cart, receipt["receipt_id"]):
            raise CartRefused(
                "This receipt has already been used for a basket, order or requisition. "
                "Run the check again for a new transaction."
            )
        issued_at = now()
        record = {
            "schema_version": "0.4",
            "record_type": "requisition_record",
            "requisition_id": f"ramify:demo:req:{uuid.uuid4().hex}",
            "data_snapshot": seed.snapshot_id(),
            "subject_ref": receipt["subject_ref"],
            "product_name": receipt.get("product_name", ""),
            "quantity": quantity,
            "unit_price_cents": unit_price,
            "line_total_cents": line_total,
            "currency": "AUD",
            "actor_ref": receipt["actor_ref"],
            "actor_label": receipt["actor_label"],
            "objective_posture": receipt["objective_posture"],
            "actor_decision": receipt["actor_decision"],
            "receipt_ref": receipt["receipt_id"],
            "receipt_hash": receipt["payload_hash"],
            "lines": [
                {
                    "subject_ref": receipt["subject_ref"],
                    "product_name": receipt.get("product_name", ""),
                    "quantity": quantity,
                    "line_total_cents": line_total,
                    "receipt_ref": receipt["receipt_id"],
                    "receipt_hash": receipt["payload_hash"],
                    "actor_ref": receipt["actor_ref"],
                    "objective_posture": receipt["objective_posture"],
                    "actor_decision": receipt["actor_decision"],
                    "human_authorised": bool(receipt.get("human_authorised_actions")),
                    "supersedes_receipt": receipt.get("supersedes_receipt"),
                }
            ],
            "timestamp": rfc3339_nano(issued_at),
            "customer_summary": {
                "headline": "RAMIFY recorded a simulated purchase requisition.",
                "authority": "The requisition is linked to the signed product decision that permitted it.",
                "what_did_not_happen": "No purchase, payment, approval workflow or inventory movement occurred.",
            },
            "notice": "Synthetic local demonstration requisition only. No external procurement system was contacted.",
        }
        sealed = seal(record)
        cart["requisitions"] = cart.get("requisitions", []) + [sealed]
        _write(cart, cart_name)

    if record_action:
        _record_transaction_action(receipt, "create_mock_requisition")
    return sealed


def remove(line_id: str, *, cart_name: str = CART_NAME) -> bool:
    with _CART_LOCK:
        cart = _read(cart_name)
        before = len(cart["lines"])
        cart["lines"] = [line for line in cart["lines"] if line.get("line_id") != line_id]
        if len(cart["lines"]) == before:
            return False
        _write(cart, cart_name)
        return True


def clear(*, cart_name: str = CART_NAME) -> None:
    with _CART_LOCK:
        cart = _read(cart_name)
        cart["lines"] = []
        _write(cart, cart_name)


def _assert_line_matches_receipt(line: dict, receipt: dict) -> None:
    """Reject local basket edits that are not authorised by the sealed receipt."""
    signed_order = receipt.get("order") or {}
    expected = {
        "subject_ref": receipt.get("subject_ref"),
        "product_name": receipt.get("product_name", ""),
        "quantity": signed_order.get("quantity"),
        "unit_price_cents": signed_order.get("unit_price_cents"),
        "line_total_cents": signed_order.get("line_total_cents"),
        "actor_ref": receipt.get("actor_ref"),
        "objective_posture": receipt.get("objective_posture"),
        "actor_decision": receipt.get("actor_decision"),
    }
    for field, value in expected.items():
        if line.get(field) != value:
            raise CartRefused(f"A basket line {field} no longer matches its signed receipt.")
    if bool(line.get("human_authorised", False)) != bool(receipt.get("human_authorised_actions")):
        raise CartRefused("A basket line human-authorisation state no longer matches its signed receipt.")
    if line.get("supersedes_receipt") != receipt.get("supersedes_receipt"):
        raise CartRefused("A basket line successor linkage no longer matches its signed receipt.")


def _validate_lines_before_checkout(lines: list[dict], cart_state: dict) -> None:
    """Recheck every authority immediately before sealing the order.

    The complete transaction is validated as one unit: every line must still
    permit a consumer-basket action, one receipt may appear only once, and no
    receipt may already have been consumed by an earlier order/requisition.
    """
    seen: set[str] = set()
    for line in lines:
        receipt_ref = line.get("receipt_ref", "")
        if not receipt_ref:
            raise CartRefused("A basket line has no receipt reference.")
        if receipt_ref in seen:
            raise CartRefused(
                "The same one-time receipt authority appears more than once in this basket."
            )
        seen.add(receipt_ref)

        if _receipt_consumed(cart_state, receipt_ref):
            raise CartRefused(
                "A basket line refers to receipt authority that has already been consumed."
            )

        receipt = store.get(receipt_ref)
        if receipt is None:
            raise CartRefused("A basket line no longer has its decision receipt.")
        if receipt.get("payload_hash") != line.get("payload_hash"):
            raise CartRefused("A basket line no longer matches the receipt that admitted it.")
        _assert_receipt_authority(receipt, required_any=BASKET_ACTIONS)
        _assert_line_matches_receipt(line, receipt)


def checkout(*, cart_name: str = CART_NAME) -> dict:
    """Seal an order record over a freshly revalidated basket, then empty it."""
    with _CART_LOCK:
        cart = _read(cart_name)
        lines = list(cart["lines"])
        if not lines:
            raise CartRefused("The basket is empty.")

        _validate_lines_before_checkout(lines, cart)

        issued_at = now()
        human_count = sum(1 for line in lines if line.get("human_authorised"))
        unattended_count = sum(1 for line in lines if line.get("unattended"))
        normal_count = len(lines) - human_count - unattended_count
        customer_summary = {
            "headline": "RAMIFY checked every item before this simulated order was recorded.",
            "what_was_checked": (
                f"{len(lines)} basket line(s), each linked to a sealed product decision receipt."
            ),
            "how_the_order_was_authorised": (
                f"{human_count} line(s) were authorised by a person; "
                f"{unattended_count} line(s) were permitted for autonomous purchase; "
                f"{normal_count} line(s) followed the agent's normal purchase policy."
            ),
            "what_did_not_happen": "No real payment, inventory movement or shipment occurred.",
            "audit_message": (
                "The machine decision, any human follow-on decision and this order record "
                "remain separate, linked and independently verifiable."
            ),
        }

        record = {
            "schema_version": "0.4",
            "record_type": "order_record",
            "order_id": f"ramify:demo:order:{uuid.uuid4().hex}",
            "data_snapshot": seed.snapshot_id(),
            "line_count": len(lines),
            "item_count": sum(line["quantity"] for line in lines),
            "total_cents": sum(line["line_total_cents"] for line in lines),
            "currency": "AUD",
            "lines": [
                {
                    "subject_ref": line["subject_ref"],
                    "product_name": line["product_name"],
                    "quantity": line["quantity"],
                    "line_total_cents": line["line_total_cents"],
                    "receipt_ref": line["receipt_ref"],
                    "receipt_hash": line["payload_hash"],
                    "actor_ref": line["actor_ref"],
                    "objective_posture": line["objective_posture"],
                    "actor_decision": line["actor_decision"],
                    "human_authorised": line.get("human_authorised", False),
                    "supersedes_receipt": line.get("supersedes_receipt"),
                }
                for line in lines
            ],
            "timestamp": rfc3339_nano(issued_at),
            "customer_summary": customer_summary,
            "notice": (
                "Simulated order. No purchase was made, no money moved and no inventory "
                "was touched. Every line names the decision receipt that admitted it."
            ),
        }

        sealed = seal(record)
        cart["orders"] = cart.get("orders", []) + [sealed]
        cart["lines"] = []
        _write(cart, cart_name)
        return sealed
