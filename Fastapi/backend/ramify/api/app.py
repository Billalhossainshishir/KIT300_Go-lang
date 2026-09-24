"""HTTP surface.

Five primitives under `/api/v0/`, plus the basket, agent editing, receipt
verification, human review and an optional explanation endpoint.

The documented CMD command binds Uvicorn to 127.0.0.1. The core deterministic demo
does not require an external network service. An optional language-model adapter
may talk to a separately running local model service; it is never on the trust
decision path.
"""

import hashlib
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from io import BytesIO
import json
import zipfile
from threading import Lock

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ramify import engine
from ramify.agent import interpreter
from ramify.action import cart
from ramify.api.models import (
    ActionEventRequest,
    AddToCartRequest,
    AlternativesRequest,
    AgentProfileRequest,
    AssessRequest,
    CompareRequest,
    ExplainRequest,
    IdentifyRequest,
    InterpretRequest,
    ReviewRequest,
    SubjectRequest,
    VerifyRequest,
)
from ramify.crypto.canonical import rfc3339_nano
from ramify.crypto import keys
from ramify.crypto.sign import verify_receipt
from ramify.data import seed
from ramify.action import alternatives
from ramify.policy import profiles, vocabulary
from ramify.ratify import verify as ratify_verify
from ramify.ratify import checks as ratify_checks
from ramify.receipt import builder, store
from ramify.resolve import primitives
from ramify.timing import now
from ramify.storage import StoreCorrupt

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = PROJECT_ROOT / "frontend"
PAGE_DIR = FRONTEND / "pages"
SCRIPT_DIR = FRONTEND / "scripts"
STYLE_DIR = FRONTEND / "styles"
IMAGE_DIR = PROJECT_ROOT / "product_images"
VERSION = (PROJECT_ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()

def _build_id() -> str:
    """A short digest of the interface files, shown in the footer.

    Content rather than timestamps: copying the tree must not change it, and
    editing a stylesheet must.
    """
    digest = hashlib.sha256()
    for path in sorted(FRONTEND.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(FRONTEND).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:8]


BUILD_ID = _build_id()
DEMO_TAMPER_LOCK = Lock()

app = FastAPI(
    title="RAMIFY OS Decision Receipt Interface",
    description=(
        "KIT300 prototype. Synthetic data only. Not for real purchasing, "
        "safety, legal or compliance decisions."
    ),
    version=VERSION,
)


@app.exception_handler(StoreCorrupt)
async def local_store_corrupt(request, exc: StoreCorrupt):
    """Turn damaged local demo state into a recoverable, human-readable error."""
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                "RAMIFY could not read its local demo state. "
                "The saved state may be incomplete or damaged. "
                f"Details: {exc}"
            )
        },
    )


@app.exception_handler(keys.SignerKeyError)
async def signer_key_corrupt(request, exc: keys.SignerKeyError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "recovery": "Back up the local RAMIFY data folder, then explicitly reset or rekey the synthetic demo signer.",
        },
    )


@app.middleware("http")
async def no_store(request, call_next):
    """Never let a browser hold on to a page or an asset.

    A cached stylesheet does not announce itself — the page simply looks like
    nothing changed. The milliseconds a cache would save are not worth showing
    a client last week's build.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/healthz")
def healthz() -> dict:
    """What the server can honestly say about its own configuration.

    The interface badge reads this rather than asserting offline operation,
    which a page has no way to know.
    """
    return {
        "status": "ok",
        "data_snapshot": seed.snapshot_id(),
        "version": VERSION,
        "build": BUILD_ID,
        "configured_endpoint": "127.0.0.1:8000",
        "default_launcher_loopback_only": True,  # legacy compatibility field
        "documented_launch_loopback_only": True,
        "core_external_network_calls": False,
        # Legacy fields remain for older UI/tests, but deliberately do not claim
        # the application can introspect Uvicorn's actual bind/network behaviour.
        "bound_to": "not introspected by the application",
        "binds_loopback_only": None,
        "makes_external_network_calls": False,
        "makes_outbound_calls": None,
        "note": (
            "The documented CMD launch command configures Uvicorn for 127.0.0.1:8000 and the core demo "
            "requires no external network service. Optional local-model mode may talk to a "
            "separately running local model service. This endpoint reports configuration, not a network audit."
        ),
    }


@app.get("/api/v0/agent/status")
def api_agent_status() -> dict:
    return interpreter.status()


@app.post("/api/v0/interpret")
def api_interpret(request: InterpretRequest) -> dict:
    try:
        return interpreter.interpret(
            request.request_text, request.actor_ref, request.mode, request.candidate_refs
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v0/identify")
def api_identify(request: IdentifyRequest) -> dict:
    return primitives.identify(request.identifier)


@app.post("/api/v0/resolve")
def api_resolve(request: SubjectRequest) -> dict:
    return primitives.resolve(request.subject_ref)


@app.post("/api/v0/status")
def api_status(request: SubjectRequest) -> dict:
    return primitives.status(request.subject_ref)


@app.post("/api/v0/verify")
def api_verify(request: VerifyRequest) -> dict:
    identify_result = primitives.identify(request.subject_ref)
    status_result = primitives.status(request.subject_ref)
    try:
        return ratify_verify.verify(
            request.subject_ref, request.policy_ref, identify_result, status_result
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v0/assess")
def api_assess(request: AssessRequest) -> dict:
    try:
        return engine.assess(
            request.identifier,
            request.actor_ref,
            request.policy_ref,
            request.quantity,
            context=request.context,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v0/compare")
def api_compare(request: CompareRequest) -> dict:
    """Assess one product for every persona at once.

    Each is evaluated independently against the same objective result, and
    `objective_agreed` asserts that they all saw the same posture.
    """
    results = []
    subject_ref = request.identifier
    product_name = ""
    order: dict = {}
    available_profiles = profiles.all_profiles()
    actor_refs = request.actor_refs or list(available_profiles)
    unknown = [ref for ref in actor_refs if ref not in available_profiles]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown agent profile(s): {', '.join(unknown)}")

    for actor_ref in actor_refs:
        profile = available_profiles[actor_ref]
        outcome = engine.assess(
            request.identifier, actor_ref, None, request.quantity, context="comparison"
        )
        subject_ref = outcome["subject_ref"]
        product_name = outcome["product_name"]
        order = outcome["order"]
        results.append(
            {
                "actor_ref": actor_ref,
                "actor_label": profile["label"],
                "summary": profile["summary"],
                "autonomy": profile["autonomy"],
                "objective_posture": outcome["objective_posture"],
                "decision": outcome["actor_decision"],
                "traffic_light": outcome["traffic_light"],
                "narrowed": outcome["narrowed"],
                "selected_action": outcome["selected_action"],
                "unattended": outcome["unattended"],
                "conditions_evaluated": outcome["conditions_evaluated"],
                "applied_rules": outcome["applied_rules"],
                "receipt_ref": outcome["receipt_ref"],
            }
        )

    postures = {row["objective_posture"] for row in results}
    return {
        "subject_ref": subject_ref,
        "product_name": product_name,
        "order": order,
        # True when every persona saw the same objective posture, which is the
        # architecture holding: the product assessment does not know who is
        # asking. If this ever came back false, stage one would be leaking.
        "objective_agreed": len(postures) <= 1,
        "objective_posture": postures.pop() if len(postures) == 1 else None,
        "personas": results,
    }


@app.post("/api/v0/alternatives")
def api_alternatives(request: AlternativesRequest) -> dict:
    """Something this agent could buy instead.

    Every candidate is put through the whole engine for the same agent, so
    nothing is offered that the agent would also stop on.
    """
    try:
        outcome = engine.assess(
            request.identifier,
            request.actor_ref,
            None,
            request.quantity,
            context="suggestion",
            persist_receipt=False,
        )
        found = alternatives.find(
            outcome["subject_ref"], request.actor_ref, request.quantity, outcome
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"alternatives": found}


@app.post("/api/v0/action")
def api_action(request: ActionEventRequest) -> dict:
    """Record an Action Gate event.

    The receipt is re-read server-side and the action checked against what it
    actually permitted, so a click cannot invent a permission the assessment
    did not grant.
    """
    receipt = store.get(request.receipt_ref)
    if receipt is None:
        raise HTTPException(status_code=404, detail="no such receipt")
    if receipt.get("assessment_context") != "purchase":
        raise HTTPException(
            status_code=409,
            detail="Only an explicit purchase journey may create Action Gate events.",
        )
    authority = verify_receipt(receipt, now=now())
    if not authority.get("purchase_authority_valid"):
        raise HTTPException(
            status_code=409,
            detail="This receipt is not current, intact purchase authority. Run the check again.",
        )

    permitted = list(receipt.get("permitted_actions", []))
    for action in receipt.get("human_authorised_actions", []):
        if action not in permitted:
            permitted.append(action)
    if request.action not in permitted:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The decision was {receipt['actor_decision']}, which permits "
                f"{', '.join(permitted) or 'nothing'}. {request.action} is not among them."
            ),
        )

    event, created = store.record_action_once(
        {
            "event_id": f"ramify:demo:act:{uuid4().hex}",
            "action": request.action,
            "receipt_ref": receipt["receipt_id"],
            "receipt_hash": receipt["payload_hash"],
            "subject_ref": receipt["subject_ref"],
            "product_name": receipt.get("product_name", ""),
            "actor_ref": receipt["actor_ref"],
            "actor_label": receipt["actor_label"],
            "actor_decision": receipt["actor_decision"],
            "recorded_at": rfc3339_nano(now()),
            "simulated": True,
            "notice": "Simulated. Nothing was purchased and no money moved.",
        }
    )
    return {
        "event": event,
        "events_for_receipt": len(store.actions_for(receipt["receipt_id"])),
        "already_recorded": not created,
    }


@app.get("/api/v0/actions")
def api_actions(limit: int = Query(50, ge=1, le=200)) -> dict:
    return {"events": store.actions(limit)}


@app.get("/api/v0/actions/verify")
def api_actions_verify() -> dict:
    return store.verify_action_ledger()


@app.get("/api/v0/vocabulary")
def api_vocabulary() -> dict:
    """The versioned posture mapping and the objective-to-actor transitions."""
    return {
        "mapping_version": vocabulary.MAPPING_VERSION,
        "postures": list(vocabulary.POSTURE_MAPPING.values()),
        "standings": [
            {"standing": k, **v} for k, v in vocabulary.STANDING_MAPPING.items()
        ],
        "transitions": vocabulary.transition_matrix(),
    }


@app.get("/api/v0/cart")
def api_cart() -> dict:
    return cart.contents()


@app.post("/api/v0/cart/add")
def api_cart_add(request: AddToCartRequest) -> dict:
    try:
        line = cart.add(request.receipt_ref)
    except cart.CartRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"line": line, "cart": cart.contents()}


@app.post("/api/v0/requisition/create")
def api_requisition_create(request: AddToCartRequest) -> dict:
    """Create a signed simulated requisition for requisition-style personas.

    Requisition authority is deliberately separate from the consumer basket so
    procurement policy cannot silently turn into an ordinary cart checkout.
    """
    try:
        record = cart.create_requisition(request.receipt_ref)
    except cart.CartRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"requisition": record, "cart": cart.contents()}


@app.delete("/api/v0/cart/line/{line_id}")
def api_cart_remove(line_id: str) -> dict:
    if not cart.remove(line_id):
        raise HTTPException(status_code=404, detail="no such line")
    return cart.contents()


@app.delete("/api/v0/cart")
def api_cart_clear() -> dict:
    cart.clear()
    return cart.contents()


@app.post("/api/v0/cart/checkout")
def api_cart_checkout() -> dict:
    try:
        record = cart.checkout()
    except cart.CartRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"order": record, "cart": cart.contents()}


@app.get("/api/v0/agents")
def api_agents() -> dict:
    return {
        "agents": [
            profiles.as_catalogue_entry(profile) for profile in profiles.all_profiles().values()
        ],
        "autonomy_levels": [
            {"value": value, "label": label} for value, label in profiles.AUTONOMY_LABELS.items()
        ],
        "brands": sorted({record["brand"] for record in seed.subjects().values()}),
        "sellers": [
            {"ref": ref, "name": record["name"]} for ref, record in seed.seed()["sellers"].items()
        ],
    }


@app.put("/api/v0/agents/{ref}")
def api_agent_save(ref: str, request: AgentProfileRequest) -> dict:
    if profiles.profile(ref) is None:
        raise HTTPException(status_code=404, detail="no such agent profile")
    try:
        saved = profiles.save(ref, request.model_dump())
    except profiles.InvalidProfile as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return profiles.as_catalogue_entry(saved)


@app.post("/api/v0/agents")
def api_agent_create(request: AgentProfileRequest) -> dict:
    try:
        created = profiles.create(request.model_dump())
    except profiles.InvalidProfile as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return profiles.as_catalogue_entry(created)


@app.post("/api/v0/agents/preview")
def api_agent_preview(request: AgentProfileRequest) -> dict:
    """Compile an edit without saving, so the editor can show its effect."""
    try:
        return profiles.as_catalogue_entry(profiles.preview(request.model_dump()))
    except profiles.InvalidProfile as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v0/agents/{ref}")
def api_agent_reset(ref: str) -> dict:
    """Undo an edit to a shipped agent, or delete one the customer added."""
    if profiles.profile(ref) is None:
        raise HTTPException(status_code=404, detail="no such agent profile")
    restored = profiles.reset(ref)
    return {
        "restored": profiles.as_catalogue_entry(restored) if restored else None,
        "deleted": restored is None,
    }


@app.get("/api/v0/review/queue")
def api_review_queue() -> dict:
    return {
        "open": store.review_queue(),
        "resolved": store.resolved_reviews(20),
    }


@app.post("/api/v0/receipt/verify")
def api_receipt_verify(receipt: dict) -> dict:
    """Verify a receipt.

    The browser panel and the standalone `ramify-verify` tool call the same
    function, so the two cannot drift apart.
    """
    return verify_receipt(receipt)


@app.post("/api/v0/receipt/review")
def api_receipt_review(request: ReviewRequest) -> dict:
    """Record a person's decision on a held receipt.

    Appends a linked superseding receipt; the original is untouched, so the
    trail shows both what the system decided and what the person then chose.
    """
    original = store.get(request.receipt_id)
    if original is None:
        raise HTTPException(status_code=404, detail="no such receipt")
    if original.get("assessment_context") != "purchase":
        raise HTTPException(
            status_code=409,
            detail="Only a receipt from an active purchase journey can enter human review.",
        )
    if original.get("supersedes_receipt") or original.get("human_review"):
        raise HTTPException(
            status_code=409,
            detail=(
                "A human-review successor is terminal and cannot be reviewed again to mint "
                "fresh transaction authority. Run a new product assessment if a new decision is required."
            ),
        )
    if original.get("actor_decision") not in store.AWAITING_REVIEW:
        raise HTTPException(
            status_code=409,
            detail="This decision does not require human review.",
        )
    if store.has_successor(original["receipt_id"]):
        raise HTTPException(
            status_code=409,
            detail="This review has already been answered. The original receipt remains unchanged.",
        )
    original_report = verify_receipt(original, now=now())
    if not original_report.get("purchase_authority_valid"):
        raise HTTPException(
            status_code=409,
            detail="This review request is no longer current and intact. Run the product check again.",
        )

    superseding = dict(original)
    for field in ("payload_hash", "signature"):
        superseding.pop(field, None)

    superseding["receipt_id"] = builder.new_receipt_id()
    superseding["supersedes_receipt"] = original["receipt_id"]
    reviewed_time = now()
    reviewed_at = rfc3339_nano(reviewed_time)
    superseding["timestamp"] = reviewed_at
    superseding["expires_at"] = rfc3339_nano(
        reviewed_time + timedelta(seconds=builder.RECEIPT_TTL_SECONDS)
    )
    outcome_label = (
        "Declined — leave the item unchanged"
        if request.outcome == "confirmed"
        else "Approved once for this simulated transaction"
    )
    posture_presentation = vocabulary.POSTURE_MAPPING.get(
        original.get("objective_posture"), {}
    )
    human_meaning = posture_presentation.get(
        "user_facing", original.get("objective_posture", "unknown")
    )
    human_explanation = posture_presentation.get("meaning", "")
    human_review = {
        "outcome": request.outcome,
        "outcome_label": outcome_label,
        "reviewer_name": request.reviewer_name,
        "reviewer_role": request.reviewer_role,
        "note": request.reviewer_note,
        "reviewed_at": reviewed_at,
        "reviewed_decision": original["actor_decision"],
        "decision_scope": "this simulated transaction only",
        "reviewer_attestation": (
            "The named reviewer made this simulated decision. This field is a "
            "recorded acknowledgement, not a personal cryptographic signature."
        ),
    }
    superseding["human_review"] = human_review
    if request.outcome == "confirmed":
        superseding["selected_action"] = "halt"
        superseding["human_authorised_actions"] = []
        consequence = "No basket line or requisition is created, and nothing proceeds."
    else:
        # A person may authorise one simulated transaction after a held or
        # incomplete case. Preserve the actor's transaction style: a procurement
        # persona must remain a requisition workflow rather than silently turning
        # into a consumer basket purchase after human review. The successor is
        # separate authority; it never rewrites the machine decision.
        profile = profiles.profile(original["actor_ref"]) or {}
        transaction_action = (
            "create_mock_requisition"
            if profile.get("purchase_style") == "requisition"
            else "add_to_mock_cart"
        )
        superseding["selected_action"] = (
            "human_authorised_requisition"
            if transaction_action == "create_mock_requisition"
            else "human_authorised_purchase"
        )
        superseding["human_authorised_actions"] = [transaction_action]
        consequence = (
            "This successor receipt may create one simulated purchase requisition. "
            "The objective posture and original agent decision remain unchanged."
            if transaction_action == "create_mock_requisition"
            else "This successor receipt may admit one simulated basket line. The "
            "objective posture and original agent decision remain unchanged."
        )

    # This plain-language block is part of the signed successor receipt. It is
    # not a second source of truth: every sentence is derived from fields that
    # are also present in machine-readable form.
    superseding["human_receipt"] = {
        "receipt_type": "human_decision_summary",
        "headline": outcome_label,
        "reviewer": {
            "name": request.reviewer_name,
            "role": request.reviewer_role,
        },
        "what_ramify_found": (
            f"Objective posture {original['objective_posture']} — {human_meaning}. "
            f"{human_explanation}"
        ),
        "what_the_agent_did": (
            f"{original['actor_label']} returned {original['actor_decision']} and "
            "handed the decision to a person."
        ),
        "what_the_person_decided": outcome_label,
        "why_it_stopped": original.get("primary_reason", "No primary reason recorded."),
        "important_findings": list(original.get("reason_codes", [])),
        "consequence": consequence,
        "scope": "this simulated transaction only",
        "original_receipt": {
            "receipt_id": original["receipt_id"],
            "payload_hash": original["payload_hash"],
            "unchanged": True,
        },
        "reviewed_at": reviewed_at,
        "notice": (
            "Plain-language summary of the signed machine record. Synthetic "
            "demonstration only; no real purchase or approval occurred."
        ),
    }

    from ramify.crypto.sign import seal

    sealed = seal(superseding)
    try:
        store.append_successor(original["receipt_id"], sealed)
    except store.SuccessorExists as exc:
        raise HTTPException(
            status_code=409,
            detail="This review was answered by another request. Refresh Needs me to see it.",
        ) from exc
    except store.InvalidSuccessorTarget as exc:
        raise HTTPException(
            status_code=409,
            detail="Only the original machine review receipt may receive a human successor.",
        ) from exc
    event = store.record_action(
        {
            "event_id": f"ramify:demo:act:{uuid4().hex}",
            "action": "human_review_" + request.outcome,
            "receipt_ref": sealed["receipt_id"],
            "receipt_hash": sealed["payload_hash"],
            "supersedes_receipt": original["receipt_id"],
            "subject_ref": original["subject_ref"],
            "product_name": original.get("product_name", ""),
            "actor_ref": original["actor_ref"],
            "actor_label": original["actor_label"],
            "actor_decision": original["actor_decision"],
            "recorded_at": reviewed_at,
            "reviewer_name": request.reviewer_name,
            "reviewer_role": request.reviewer_role,
            "simulated": True,
            "notice": "Human review appended. The original receipt was not changed.",
        }
    )
    return {
        "receipt_ref": sealed["receipt_id"],
        "supersedes": original["receipt_id"],
        "receipt": sealed,
        "event": event,
    }


@app.get("/api/v0/receipts")
def api_receipts(limit: int = Query(40, ge=1, le=200)) -> dict:
    all_rows = store.all_receipts()
    answered = {r["supersedes_receipt"] for r in all_rows if r.get("supersedes_receipt")}
    return {
        "receipts": all_rows[-limit:][::-1],
        "total": len(all_rows),
        "superseded": sorted(answered),
    }


@app.get("/api/v0/proof-pack")
def api_proof_pack() -> StreamingResponse:
    """Generate the five-scenario Quick Proof Pack with an explicit manifest."""
    examples = [
        ("01_APPROVED_Apex", "ramify:demo:supp:apex-mg-glyc-120", "consumer_v1"),
        ("02_EXPIRED_Evidence", "ramify:demo:supp:greenline-ashw-ksm66-90", "consumer_v1"),
        ("03_SELLER_RISK", "ramify:demo:ppe:covelane-n95-resp-b2026-01-B", "consumer_v1"),
        ("04_RECALL_Block", "ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K", "consumer_v1"),
        ("05_SUBSTITUTION", "ramify:demo:supp:stonefield-zinc-gluc-50-90", "consumer_v1"),
    ]
    from ramify.crypto import keys as crypto_keys

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        receipts = []
        receipt_entries = []
        for label, subject_ref, actor_ref in examples:
            outcome = engine.assess(
                subject_ref, actor_ref, None, 1, context="proof_pack", persist_receipt=False
            )
            receipt = outcome["receipt"]
            receipts.append(receipt)
            filename = f"receipts/{label}_{receipt['receipt_id'].replace(':', '-')}.json"
            raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
            zf.writestr(filename, raw)
            receipt_entries.append({
                "filename": filename,
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "receipt_id": receipt["receipt_id"],
            })

        # The first receipt creation may install the machine-local signer on a
        # fresh demo. Capture public keys only after those receipts are sealed,
        # otherwise the pack could contain the unrelated embedded signer key.
        public_keys = crypto_keys.public_keys()
        signer_hex = public_keys.get("ramify:demo:signer:receipt", "")
        signer_fingerprint = (
            "sha256:" + hashlib.sha256(bytes.fromhex(signer_hex)).hexdigest()
            if signer_hex else None
        )

        manifest = {
            "schema": "ramify-proof-pack-manifest-v1",
            "pack_type": "quick",
            "app_version": VERSION,
            "data_snapshot": seed.snapshot_id(),
            "dataset_digest": seed.dataset_digest(),
            "policy_ref": seed.policy_pack()["policy_ref"],
            "policy_digest": seed.policy_digest(),
            "verifier_version": "portable-verify-v2",
            "signer_key_fingerprint": signer_fingerprint,
            "expected_receipts": receipt_entries,
            "verification_scope": "Historical sealed-record integrity against included public demonstration keys; not current purchase authority or evidence revalidation.",
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        zf.writestr(
            "README.txt",
            "RAMIFY OS Quick Proof Pack\n"
            f"Version: {VERSION}\n"
            f"Data snapshot: {seed.snapshot_id()}\n\n"
            "Synthetic demonstration evidence only. These receipts do not certify a real product, seller, regulator or laboratory.\n"
            "The manifest declares the expected files, build/data/policy identity, verifier version and signer-key fingerprint.\n"
            f"Example receipt: {receipt_entries[0]['filename']}\n"
            "Portable verification: python -m pip install cryptography ; python verify_receipts.py\n"
            "Successful verification establishes historical sealed-record integrity, not current purchase authority.\n",
        )
        zf.writestr(
            "receipt_index.json",
            json.dumps([{
                "receipt_id": r["receipt_id"], "subject_ref": r["subject_ref"],
                "product_name": r.get("product_name"), "objective_posture": r.get("objective_posture"),
                "actor_decision": r.get("actor_decision"), "payload_hash": r.get("payload_hash"),
            } for r in receipts], indent=2, sort_keys=True) + "\n",
        )
        zf.writestr("verify_receipts.py", (PROJECT_ROOT / "scripts" / "portable_verify.py").read_text(encoding="utf-8"))
        zf.writestr("requirements.txt", "cryptography>=42\n")
        zf.writestr("trust/public_keys.json", json.dumps(public_keys, indent=2, sort_keys=True) + "\n")
        zf.writestr("policy/policy_pack_demo_v1.json", json.dumps(seed.policy_pack(), indent=2, sort_keys=True) + "\n")
        zf.writestr("evidence/evidence_signatures.json", json.dumps(seed.evidence_signatures(), indent=2, sort_keys=True) + "\n")
        for evidence_ref, signature_meta in seed.evidence_signatures().items():
            storage_path = signature_meta.get("storage_path")
            if storage_path:
                source = seed.DATA_DIR / storage_path
                if source.is_file():
                    zf.writestr(f"evidence/artefacts/{source.name}", source.read_bytes())
    buffer.seek(0)
    return StreamingResponse(
        buffer, media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="RAMIFY-Quick-Proof-Pack.zip"'},
    )


@app.get("/api/v0/receipt/{receipt_id:path}")
def api_receipt(receipt_id: str) -> dict:
    receipt = store.get(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="no such receipt")
    return receipt


@app.get("/api/v0/demo/coverage")
def api_demo_coverage() -> dict:
    scenarios = seed.scenarios()
    return {
        "scenario_count": len(scenarios),
        "product_count": len(seed.subjects()),
        "seller_count": len(seed.seed()["sellers"]),
        "evidence_count": len(seed.seed()["evidence"]),
        "actor_count": len(profiles.all_profiles()),
        "scenarios": [
            {
                "id": row["id"],
                "note": row["note"],
                "expected_objective": row["expected_objective"],
                "expected_decision": row["expected_decision"],
            }
            for row in scenarios
        ],
        "notice": "Coverage is asserted by the automated test suite against the synthetic dataset.",
    }


@app.get("/api/v0/ledger/verify")
def api_ledger_verify() -> dict:
    receipts = store.all_receipts()
    results = [verify_receipt(receipt) for receipt in receipts]

    def integrity_ok(report: dict) -> bool:
        return bool(report.get("integrity_verified"))

    intact = sum(1 for result in results if integrity_ok(result))
    fresh = sum(1 for result in results if result.get("fresh", True))
    return {
        "total": len(receipts),
        "valid": intact,
        "invalid": len(receipts) - intact,
        "all_valid": intact == len(receipts),
        "intact": intact,
        "fresh": fresh,
        "past_purchase_authority_window": len(receipts) - fresh,
        "results": results[-20:],
        "note": (
            "Ledger health separates cryptographic integrity from the one-hour purchase-authority validity window. "
            "An old receipt can remain unchanged and verifiable as history after it stops being current purchase authority."
        ),
    }


@app.get("/api/v0/catalogue")
def api_catalogue() -> dict:
    """Everything the interface needs to draw itself."""
    products = []
    for ref, record in seed.subjects().items():
        seller = seed.seller(record["seller_ref"])
        products.append(
            {
                "subject_ref": ref,
                "name": record["name"],
                "brand": record["brand"],
                "category": record["category"],
                "seller_ref": record["seller_ref"],
                "seller_name": seller["name"] if seller else "",
                "batch_ref": record.get("batch_ref"),
                "price_cents": seed.price_cents(ref),
            }
        )
    return {
        "products": sorted(products, key=lambda p: p["name"]),
        "actor_profiles": [
            profiles.as_catalogue_entry(profile) for profile in profiles.all_profiles().values()
        ],
        "policy": {
            "policy_ref": seed.policy_pack()["policy_ref"],
            "policy_version": seed.policy_pack()["policy_version"],
            "status": seed.policy_pack()["status"],
            "notice": seed.policy_pack()["notice"],
        },
        "scenarios": [
            {
                "id": scenario["id"],
                "subject_ref": scenario["subject_ref"],
                "actor_ref": scenario["actor"],
                "note": scenario["note"],
                "expected_objective": scenario["expected_objective"],
                "expected_decision": scenario["expected_decision"],
            }
            for scenario in seed.scenarios()
        ],
        "data_snapshot": seed.snapshot_id(),
        "build": BUILD_ID,
        "snapshot_date": seed.seed()["meta"]["snapshot_date"],
        "notice": seed.seed()["meta"]["notice"],
    }


@app.get("/api/v0/subject/{subject_ref:path}")
def api_subject(subject_ref: str) -> dict:
    """The raw record, so a viewer can check the inputs against the verdict."""
    record = seed.subject(subject_ref)
    if record is None:
        raise HTTPException(status_code=404, detail="no such subject")
    evidence_refs = list(
        dict.fromkeys(
            ref
            for claim in record.get("claims", [])
            for ref in claim.get("evidence_refs", [])
        )
    )
    return {
        "subject": record,
        "status": seed.status_for(subject_ref),
        "evidence": [evidence for ref in evidence_refs if (evidence := seed.evidence(ref)) is not None],
    }


@app.post("/api/v0/explain")
def api_explain(request: ExplainRequest) -> JSONResponse:
    """Plain-English explanation of a finished receipt.

    The model gets a read-only copy and returns prose, labelled presentation so
    nothing downstream mistakes it for the decision. With no model configured
    this falls back to a deterministic summary.
    """
    from ramify.agent import explain

    integrity = verify_receipt(request.receipt, now=now())
    if not integrity.get("hash_valid") or not integrity.get("signature_valid"):
        raise HTTPException(
            status_code=422,
            detail="RAMIFY will only explain a receipt whose hash and signature are intact.",
        )
    result = explain.explain_receipt(request.receipt)
    return JSONResponse(
        {
            "authoritative_summary": result.get("authoritative_summary", result["text"]),
            "explanation": result["text"],
            "source": result["source"],
            "model_text_accepted": bool(result.get("model_text_accepted")),
            "presentation_only": True,
            "authoritative": False,
        }
    )



@app.post("/api/v0/demo/evidence-tamper")
def api_demo_evidence_tamper(request: SubjectRequest) -> dict:
    """Prove evidence tamper detection using an isolated in-memory byte copy."""
    records = [
        seed.evidence(ref)
        for ref, raw in seed.seed().get("evidence", {}).items()
        if raw.get("subject_ref") == request.subject_ref
    ]
    records = [record for record in records if record and record.get("storage_path")]
    if not records:
        raise HTTPException(status_code=404, detail="No evidence artefact is available for this subject.")
    record = records[0]
    artefact_path = (seed.DATA_DIR / record["storage_path"]).resolve()
    try:
        artefact_path.relative_to(seed.DATA_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Evidence path is outside the synthetic data directory.") from exc
    if not artefact_path.is_file():
        raise HTTPException(status_code=404, detail="Evidence artefact is missing.")

    original = artefact_path.read_bytes()
    tampered = original + b"\nRAMIFY SYNTHETIC IN-MEMORY TAMPER DEMO.\n"
    clean_finding = ratify_checks.evaluate_evidence_integrity_bytes(record, original, request.subject_ref)
    tampered_finding = ratify_checks.evaluate_evidence_integrity_bytes(record, tampered, request.subject_ref)
    outcome = engine.assess(
        request.subject_ref,
        "consumer_v1",
        quantity=1,
        context="guided_demo",
        persist_receipt=False,
        evidence_overrides={record["ref"]: tampered},
    )
    evidence_check = next(
        (item for item in outcome.get("receipt", {}).get("check_results", []) if item.get("check_id") == "evidence_freshness"),
        {},
    )
    return {
        "subject_ref": request.subject_ref,
        "evidence_ref": record.get("ref"),
        "clean_integrity": clean_finding,
        "tampered_integrity": tampered_finding,
        "ratify_outcome": evidence_check.get("outcome"),
        "objective_posture": outcome.get("objective_posture"),
        "reason_codes": outcome.get("reason_codes", []),
        "shared_artefact_modified": False,
        "artefact_restored": True,
        "note": "Synthetic isolated demonstration; the shared evidence artefact was never modified.",
    }


@app.post("/api/v0/demo/cart/reset")
def api_demo_cart_reset() -> dict:
    """Clear the dedicated David-demo cart without touching the normal basket."""
    cart.clear(cart_name=cart.DEMO_CART_NAME)
    return {"cleared": True, "simulated": True, "normal_cart_untouched": True}


@app.post("/api/v0/demo/checkout-proof")
def api_demo_checkout_proof() -> dict:
    """Exercise real cart authority checks in a dedicated demonstration cart."""
    cart.clear(cart_name=cart.DEMO_CART_NAME)
    assessment = engine.assess(
        "ramify:demo:supp:apex-mg-glyc-120",
        "consumer_v1",
        quantity=1,
        context="purchase",
    )
    verification = verify_receipt(assessment["receipt"], now=now())
    line = cart.add(
        assessment["receipt_ref"],
        cart_name=cart.DEMO_CART_NAME,
        record_action=False,
    )
    order = cart.checkout(cart_name=cart.DEMO_CART_NAME)
    return {
        "assessment": assessment,
        "verification": verification,
        "line": line,
        "order": order,
        "normal_cart_untouched": True,
        "note": "Dedicated demonstration cart; the normal consumer basket is not cleared or modified.",
    }


@app.get("/api/v0/demo/absent-status")
def api_demo_absent_status() -> dict:
    """Dedicated proof that truly absent status is represented as unknown."""
    finding = ratify_checks.check_standing({})
    return {
        "input": "no status record supplied",
        "standing": "unknown",
        "check": finding.as_dict(),
        "reason_codes": finding.reason_codes,
    }


@app.get("/api/v0/proof-pack/extended")
def api_extended_proof_pack() -> FileResponse:
    pack = PROJECT_ROOT / "RAMIFY-Extended-Proof-Pack.zip"
    if not pack.is_file():
        raise HTTPException(status_code=404, detail="Extended Proof Pack is not present in this build.")
    return FileResponse(pack, media_type="application/zip", filename=pack.name)

# Separate documents rather than a single-page application. The specification
# declines frontend frameworks, npm and build pipelines outright.
PAGES = {
    "": "console.html",
    "shop": "console.html",
    "demo": "demo.html",
    "david-demo": "david-demo.html",
    "tour": "tour.html",
    "cart": "cart.html",
    "agents": "agents.html",
    "review": "review.html",
    "activity": "activity.html",
    "human-receipt": "human-receipt.html",
    "technical": "technical.html",
    "proof-pack": "proof-pack.html",
    "about": "about.html",
    "help": "help.html",
}

ASSET_DIRS = {
    ".js": (SCRIPT_DIR, "application/javascript"),
    ".css": (STYLE_DIR, "text/css"),
    ".png": (IMAGE_DIR, "image/png"),
}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(PAGE_DIR / PAGES[""])


@app.get("/{name}")
def page_or_asset(name: str) -> FileResponse:
    if name in PAGES:
        return FileResponse(PAGE_DIR / PAGES[name])

    directory, media_type = ASSET_DIRS.get(Path(name).suffix, (None, None))
    if directory is None:
        raise HTTPException(status_code=404, detail="not found")

    # Resolve before comparing parents, so ".." cannot walk out of the tree.
    asset = (directory / name).resolve()
    if asset.is_file() and asset.parent == directory.resolve():
        return FileResponse(asset, media_type=media_type)

    raise HTTPException(status_code=404, detail="not found")
