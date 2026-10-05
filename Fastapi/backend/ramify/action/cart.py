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
BASKET_ACTIONS = (
    "add_to_mock_cart",
    "purchase_autonomously",
)
_CART_LOCK = RLock()


class CartRefused(Exception):
    """Raised when a line or checkout cannot proceed safely."""


def _cart_path() -> Path:
    from ramify.crypto import keys

    directory = keys.local_data_store()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / CART_NAME


def _read() -> dict:
    cart = read_json(_cart_path(), lambda: {"lines": [], "orders": [], "requisitions": []})
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


def _write(cart: dict) -> None:
    write_json_atomic(_cart_path(), cart)


def _assert_receipt_authority(receipt: dict) -> None:
    """Require an intact, fresh receipt from an explicit purchase journey."""
    if receipt.get("assessment_context") != "purchase":
        raise CartRefused(
            "This receipt came from an exploratory/demo check, not an active purchase journey."
        )

    report = verify_receipt(receipt, now=now())
    if not report.get("time_window_valid"):
        failed = [c["name"] for c in report.get("checks", []) if not c.get("passed")]
        detail = ", ".join(failed) or "integrity/freshness check"
        raise CartRefused(
            f"This receipt is no longer valid purchase authority ({detail}). Run the check again."
        )
    _assert_trusted_snapshot_unchanged(receipt)


def _objective_facts(receipt: dict) -> dict:
    """The parts of a decision that describe the product, not the agent."""
    return {
        "objective_posture": receipt.get("objective_posture"),
        "standing": (receipt.get("status_result") or {}).get("standing"),
        "unit_price_cents": (receipt.get("order") or {}).get("unit_price_cents"),
        "checks": {
            check.get("check_id"): (check.get("outcome"), sorted(check.get("reason_codes", [])))
            for check in receipt.get("check_results", [])
        },
    }


def _assert_trusted_snapshot_unchanged(receipt: dict) -> None:
    """Refuse authority sealed against product facts that have since changed.

    A receipt's signature proves what was true when it was sealed. If the
    trusted local data moved on afterwards (a recall, revoked evidence, a new
    price), the receipt is authentic but stale, and checking out on it would
    act on facts that no longer hold (David, 1 Oct, item 3).

    The sealed dataset digest is the fast path: unchanged data means unchanged
    facts. When it differs, the product is reassessed against the current
    local data and refused only if its own facts changed, so an edit to an
    unrelated product does not void every basket. No network call is made.
    """
    if receipt.get("dataset_digest") == seed.dataset_digest():
        return
    from ramify import engine

    try:
        current = engine.assess(
            receipt["subject_ref"],
            actor_ref=receipt.get("actor_ref", "consumer_v1"),
            quantity=int((receipt.get("order") or {}).get("quantity") or 1),
            context="purchase",
            persist_receipt=False,
        )["receipt"]
    except Exception as exc:
        raise CartRefused(
            "The product could not be reassessed against the current trusted data. Run the check again."
        ) from exc
    if _objective_facts(current) != _objective_facts(receipt):
        raise CartRefused(
            "The trusted product data has changed since this decision was sealed "
            f"(now {current.get('objective_posture')}, "
            f"standing {(current.get('status_result') or {}).get('standing')}). "
            "Run the check again."
        )


def _authorised_unattended(receipt: dict) -> bool:
    """Whether the signed decision itself selected an unattended purchase."""
    return receipt.get("selected_action") == "purchase_autonomously"


def _assert_permits_basket_action(receipt: dict) -> None:
    """Require a receipt whose decision actually permits a basket purchase.

    Admission and checkout both need this. Checkout used to verify only that
    the receipt was authentic and unexpired, which says nothing about posture,
    so a line referencing a blocked or requisition-only decision could be
    written into the basket file and sealed into an order.
    """
    permitted = set(receipt.get("permitted_actions", []))
    permitted.update(receipt.get("human_authorised_actions", []))
    if not permitted.intersection(BASKET_ACTIONS):
        raise CartRefused(
            f"The decision was {receipt.get('actor_decision', 'unknown')}, which permits "
            f"{', '.join(sorted(permitted)) or 'nothing'}. Nothing can be added to the basket on that. Requisition-only authority must use the requisition path."
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


def _reference_already_consumed(cart: dict, receipt_id: str) -> bool:
    """Whether a receipt has already been spent on a sealed order or requisition.

    The current basket lines are deliberately not consulted: at checkout they
    are the lines being validated, so counting them would reject every order.
    """
    if any(
        line.get("receipt_ref") == receipt_id
        for order in cart.get("orders", [])
        for line in order.get("lines", [])
    ):
        return True
    return any(req.get("receipt_ref") == receipt_id for req in cart.get("requisitions", []))


def receipt_consumed(receipt_id: str) -> bool:
    """Whether a receipt has already been spent on a sealed order or requisition."""
    with _CART_LOCK:
        return _reference_already_consumed(_read(), receipt_id)


def contents() -> dict:
    with _CART_LOCK:
        cart = _read()
        lines = list(cart["lines"])
        return {
            "lines": lines,
            "line_count": len(lines),
            "item_count": sum(int(line.get("quantity", 0)) for line in lines),
            "total_cents": sum(int(line.get("line_total_cents", 0)) for line in lines),
            "orders": cart.get("orders", [])[-10:][::-1],
            "requisitions": cart.get("requisitions", [])[-10:][::-1],
        }


def add(receipt_id: str) -> dict:
    """Add one transaction line on the authority of one signed receipt."""
    receipt = store.get(receipt_id)
    if receipt is None:
        raise CartRefused("That receipt is not in the ledger.")

    _assert_receipt_authority(receipt)
    _assert_permits_basket_action(receipt)

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
        cart = _read()
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
            "unattended": _authorised_unattended(receipt),
            "human_authorised": bool(receipt.get("human_authorised_actions")),
            "human_review_outcome": (receipt.get("human_review") or {}).get("outcome"),
            "supersedes_receipt": receipt.get("supersedes_receipt"),
            "added_at": rfc3339_nano(now()),
        }
        cart["lines"].append(line)
        _write(cart)

    actual_action = (
        "purchase_autonomously"
        if receipt.get("selected_action") == "purchase_autonomously"
        else "add_to_mock_cart"
    )
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


def create_requisition(receipt_id: str) -> dict:
    """Create a signed simulated requisition without putting it in the consumer basket."""
    receipt = store.get(receipt_id)
    if receipt is None:
        raise CartRefused("That receipt is not in the ledger.")
    _assert_receipt_authority(receipt)

    permitted = set(receipt.get("permitted_actions", []))
    permitted.update(receipt.get("human_authorised_actions", []))
    if "create_mock_requisition" not in permitted:
        raise CartRefused("This receipt does not authorise a purchase requisition.")

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
        cart = _read()
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
        _write(cart)

    _record_transaction_action(receipt, "create_mock_requisition")
    return sealed


def remove(line_id: str) -> bool:
    with _CART_LOCK:
        cart = _read()
        before = len(cart["lines"])
        cart["lines"] = [line for line in cart["lines"] if line.get("line_id") != line_id]
        if len(cart["lines"]) == before:
            return False
        _write(cart)
        return True


def clear() -> None:
    with _CART_LOCK:
        cart = _read()
        cart["lines"] = []
        _write(cart)


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
    # The autonomy statement in a signed order comes from this flag, so it must
    # be the receipt's authorised action, not an editable basket value (David,
    # 1 Oct, item 4).
    if bool(line.get("unattended", False)) != _authorised_unattended(receipt):
        raise CartRefused("A basket line autonomy state no longer matches its signed receipt.")
    if bool(line.get("human_authorised", False)) != bool(receipt.get("human_authorised_actions")):
        raise CartRefused("A basket line human-authorisation state no longer matches its signed receipt.")
    if line.get("supersedes_receipt") != receipt.get("supersedes_receipt"):
        raise CartRefused("A basket line successor linkage no longer matches its signed receipt.")


def _validate_lines_before_checkout(cart: dict, lines: list[dict]) -> None:
    """Recheck every authority immediately before sealing the order.

    Checked per line and across the set. Per-line checks alone cannot see a
    receipt used twice, so two copies of one signed line each passed and the
    order came out for twice the signed quantity.
    """
    seen: set[str] = set()
    for line in lines:
        receipt_ref = line.get("receipt_ref", "")
        receipt = store.get(receipt_ref)
        if receipt is None:
            raise CartRefused("A basket line no longer has its decision receipt.")
        if receipt.get("payload_hash") != line.get("payload_hash"):
            raise CartRefused("A basket line no longer matches the receipt that admitted it.")
        _assert_receipt_authority(receipt)
        _assert_permits_basket_action(receipt)
        _assert_line_matches_receipt(line, receipt)

        if receipt_ref in seen:
            raise CartRefused(
                "One decision receipt authorises one basket line. The basket names "
                "the same receipt more than once. Run the check again for a new transaction."
            )
        seen.add(receipt_ref)

        if _reference_already_consumed(cart, receipt_ref):
            raise CartRefused(
                "This receipt has already been used for an order or requisition. "
                "Run the check again for a new transaction."
            )


def checkout() -> dict:
    """Seal an order record over a freshly revalidated basket, then empty it."""
    with _CART_LOCK:
        cart = _read()
        lines = list(cart["lines"])
        if not lines:
            raise CartRefused("The basket is empty.")

        _validate_lines_before_checkout(cart, lines)

        issued_at = now()
        human_count = sum(1 for line in lines if line.get("human_authorised"))
        # Counted from the signed receipts, not the basket file, so the signed
        # summary cannot claim autonomy the decision did not grant.
        unattended_count = sum(
            1 for line in lines if _authorised_unattended(store.get(line["receipt_ref"]) or {})
        )
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
        _write(cart)
        return sealed
