"""Every hard constraint the client set, as an assertion.

Nine corrections were issued on 22 July 2026, and the RESOLVE Demo
Specification v0.4 with amendments v0.4.1 is the signed contract above them.
Each is restated here with the reasoning that came with it, then checked.

This file exists because a constraint recorded only in a report drifts. One
recorded as a test cannot: if a later change breaks a client direction, the
build fails and names which direction it broke.
"""

import ast
import json
import unittest
from pathlib import Path

import ramify
from ramify import engine
from ramify.crypto.canonical import canonicalise_receipt
from ramify.crypto.sign import verify_receipt
from ramify.data import seed
from ramify.policy import actor as actor_policy
from ramify.ratify.precedence import RESTRICTIVENESS

PACKAGE_ROOT = Path(ramify.__file__).resolve().parent
WEB_DIR = PACKAGE_ROOT.parents[1] / "frontend"


class Direction1_NoConsensusVote(unittest.TestCase):
    """The two-of-three consensus rule was invented and must not be a principle.

    A majority rule can mislead: two stale or low-authority sources agreeing
    should not outweigh one authoritative source. Each named check carries its
    own rule, evidence requirement and severity instead.
    """

    def test_each_check_carries_its_own_severity(self):
        checks = seed.policy_pack()["checks"]
        self.assertEqual(len(checks), 7)
        for check in checks:
            with self.subTest(check=check["id"]):
                self.assertIn("severity_on_fail", check)

    def test_one_authoritative_recall_outweighs_every_passing_check(self):
        result = engine.assess("ramify:demo:ppe:harborline-nitrile-gloves-m-b2025-09-K")
        passing = [c for c in result["receipt"]["check_results"] if c["outcome"] == "pass"]
        self.assertGreaterEqual(len(passing), 5)
        self.assertEqual(result["objective_posture"], "block")

    def test_no_counting_or_voting_appears_in_the_evaluator(self):
        source = (PACKAGE_ROOT / "ratify" / "precedence.py").read_text(encoding="utf-8")
        for word in ("majority", "consensus", "vote", "two_of_three"):
            self.assertNotIn(word, source.lower())


class Direction2_TrafficLightIsPresentation(unittest.TestCase):
    """The traffic light is presentation, not the underlying decision model.

    The nomination defined five richer outcomes. Compressing them into three
    colours loses precision that the receipt should preserve — so the posture
    travels in the receipt and the colour is derived at display time.
    """

    def test_five_postures_survive_underneath_three_colours(self):
        self.assertEqual(len(RESTRICTIVENESS), 5)
        self.assertEqual(
            {engine.traffic_light(p)["colour"] for p in RESTRICTIVENESS},
            {"green", "orange", "red"},
        )

    def test_no_colour_or_label_is_ever_sealed_into_a_receipt(self):
        # Checked structurally rather than by searching for words. "Approved
        # vendor list" is a procurement condition and has nothing to do with
        # the traffic light; a substring search would flag it and teach the
        # next reader to ignore this test.
        light_values = set()
        for light in engine.TRAFFIC_LIGHT.values():
            light_values.add(light["colour"])
            light_values.add(light["label"])

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    self.assertNotIn(
                        key, ("traffic_light", "colour", "color", "light"), f"{path}.{key}"
                    )
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")
            elif isinstance(node, str):
                self.assertNotIn(node, light_values, f"light value sealed at {path}")

        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                with self.subTest(subject=subject_ref, actor=actor_ref):
                    walk(engine.assess(subject_ref, actor_ref)["receipt"], "receipt")

    def test_substitution_is_a_relationship_not_a_verdict(self):
        result = engine.assess("ramify:demo:supp:stonefield-zinc-gluc-50-90")
        self.assertNotIn("substitution", RESTRICTIVENESS)
        self.assertIsNotNone(result["substitution"])
        self.assertEqual(result["substitution"]["offered_action"], "compare_alternatives")


class Direction3_DemoPolicyPack(unittest.TestCase):
    """Build against a deliberately simplified pack, never sold as production rules."""

    def test_the_pack_labels_itself_a_demonstration_set(self):
        pack = seed.policy_pack()
        self.assertEqual(pack["status"], "demonstration_only")
        self.assertIn("not RAMIFY OS production rules", pack["notice"])

    def test_the_version_travels_inside_the_signed_payload(self):
        receipt = engine.assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        body = canonicalise_receipt(receipt).decode("utf-8")
        self.assertIn(receipt["policy_version"], body)
        self.assertIn("demonstration_only", body)


class Direction4_ReceiptNeverPassesThroughTheModel(unittest.TestCase):
    """The engine produces the result, the receipt service seals it, and the raw
    receipt goes straight to the interface. The model gets a read-only copy and
    writes a separate explanation labelled as presentation.
    """

    def test_the_decision_path_imports_no_agent_framework(self):
        markers = ("langgraph", "langchain", "pydantic_ai", "crewai", "openai", "ollama")
        packages = ("resolve", "ratify", "policy", "receipt", "action", "data", "crypto")
        modules = [PACKAGE_ROOT / "engine.py"]
        for package in packages:
            modules.extend(sorted((PACKAGE_ROOT / package).rglob("*.py")))

        for path in modules:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.extend(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.append(node.module)
            with self.subTest(module=path.name):
                for name in names:
                    self.assertFalse(name.startswith("ramify.agent"), f"{path.name} → {name}")
                    for marker in markers:
                        self.assertNotIn(marker, name.lower())

    def test_explaining_cannot_alter_the_receipt(self):
        from ramify.agent import explain

        receipt = engine.assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        before = json.dumps(receipt, sort_keys=True)
        explain.explain_receipt(receipt)
        self.assertEqual(json.dumps(receipt, sort_keys=True), before)

    def test_the_model_has_no_tool_that_authors_a_verdict(self):
        from ramify.agent import tools

        self.assertEqual(
            {spec["name"] for spec in tools.TOOL_SPECS},
            {"search_products", "assess_product", "list_products"},
        )


class Direction5_TamperEvidentAndAppendOnly(unittest.TestCase):
    """Not "immutable" — a local JSON file can be edited by anyone. A SHA-256
    payload hash is the minimum bar, and human-review decisions append a linked
    superseding receipt rather than overwriting.
    """

    def test_a_receipt_cannot_be_altered_without_detection(self):
        receipt = engine.assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        self.assertTrue(verify_receipt(receipt)["verified"])
        altered = dict(receipt, actor_decision="block")
        self.assertFalse(verify_receipt(altered)["verified"])

    def test_nothing_claims_a_receipt_is_immutable(self):
        # The embedded seed genuinely is immutable and saying so is correct.
        # What must never appear is the claim applied to a receipt, because a
        # local JSON file can be edited by anyone.
        forbidden = (
            "immutable receipt",
            "receipt is immutable",
            "receipts are immutable",
            "immutable decision",
        )
        for path in list(PACKAGE_ROOT.rglob("*.py")) + list(WEB_DIR.rglob("*")):
            if not path.is_file():
                continue
            body = path.read_text(encoding="utf-8").lower()
            with self.subTest(file=path.name):
                for phrase in forbidden:
                    self.assertNotIn(phrase, body)

    def test_the_interface_explains_the_weaker_claim_it_is_making(self):
        # The About page is written for a customer rather than an engineer, so
        # it makes the point in plain language instead of using the term. What
        # matters is that it says a file *can* be edited and that the edit
        # shows — not that it uses the word "tamper-evident".
        about = (WEB_DIR / "pages" / "about.html").read_text(encoding="utf-8").lower()
        self.assertIn("anyone can edit a file", about)
        self.assertIn("without the change being obvious", about)

    def test_review_appends_and_leaves_the_original_alone(self):
        from fastapi.testclient import TestClient

        from ramify.api.app import app
        from ramify.receipt import store

        client = TestClient(app)
        original = client.post(
            "/api/v0/assess",
            json={"identifier": "ramify:demo:supp:brightway-vitd3-5000-b2024-11-Z"},
        ).json()
        original_hash = original["receipt"]["payload_hash"]

        reviewed = client.post(
            "/api/v0/receipt/review",
            json={"receipt_id": original["receipt_ref"], "outcome": "overridden"},
        ).json()

        self.assertEqual(store.get(original["receipt_ref"])["payload_hash"], original_hash)
        self.assertEqual(reviewed["receipt"]["supersedes_receipt"], original["receipt_ref"])


class Direction6_ActionGateExists(unittest.TestCase):
    """The report ended at the verdict. The missing stage was what the agent is
    permitted to do with the result.
    """

    def test_every_assessment_selects_exactly_one_permitted_action(self):
        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                result = engine.assess(subject_ref, actor_ref)
                with self.subTest(subject=subject_ref, actor=actor_ref):
                    self.assertIn(result["selected_action"], result["permitted_actions"])

    def test_no_action_has_a_real_world_effect(self):
        from ramify.action import gate

        for decision in RESTRICTIVENESS:
            for actor_ref in seed.actor_profiles():
                with self.subTest(decision=decision, actor=actor_ref):
                    self.assertTrue(gate.select(decision, actor_ref, None)["simulated"])


class Direction7_ObjectiveTrustSeparateFromActorPolicy(unittest.TestCase):
    """Product-trust facts stay constant while different actors legitimately
    reach different decisions, because their authority, risk tolerance,
    obligations and permitted actions differ.
    """

    def test_the_objective_posture_never_depends_on_who_is_asking(self):
        for subject_ref in seed.subjects():
            postures = {
                engine.assess(subject_ref, actor_ref)["objective_posture"]
                for actor_ref in seed.actor_profiles()
            }
            with self.subTest(subject=subject_ref):
                self.assertEqual(len(postures), 1)

    def test_an_actor_may_only_narrow(self):
        for subject_ref in seed.subjects():
            for actor_ref in seed.actor_profiles():
                result = engine.assess(subject_ref, actor_ref)
                with self.subTest(subject=subject_ref, actor=actor_ref):
                    self.assertGreaterEqual(
                        RESTRICTIVENESS[result["actor_decision"]],
                        RESTRICTIVENESS[result["objective_posture"]],
                    )

    def test_a_malicious_widening_rule_is_not_accepted(self):
        from unittest.mock import patch

        malicious = {
            "label": "Malicious test profile",
            "narrowing_rules": [
                {
                    "id": "malicious_widen",
                    "when": "always",
                    "narrow_to": "allow",
                    "reason_code": "should_never_apply",
                }
            ],
            "permitted_actions": {"block": ["halt"]},
        }
        with patch("ramify.policy.profiles.profile", return_value=malicious):
            result = actor_policy.apply("block", "malicious", seed.subject(next(iter(seed.subjects()))), {})
        self.assertEqual(result.decision, "block")
        self.assertFalse(result.narrowed)
        self.assertNotIn("should_never_apply", result.reason_codes)

    def test_agents_do_not_confer(self):
        # The client warned against several autonomous agents debating whether
        # a product is trustworthy. Checked by signature rather than by
        # searching for words: `apply` receives one actor and the facts, and has
        # no parameter through which another agent's decision could reach it.
        import inspect

        parameters = set(inspect.signature(actor_policy.apply).parameters)
        self.assertEqual(parameters, {"objective_posture", "actor_ref", "subject", "order"})

        fields = set(actor_policy.ActorDecision.__dataclass_fields__)
        for forbidden in ("other_decisions", "peer_decisions", "votes", "consensus"):
            self.assertNotIn(forbidden, fields)

    def test_one_persona_cannot_change_what_another_sees(self):
        baseline = engine.assess("ramify:demo:supp:apex-mg-glyc-120", "consumer_v1")
        for actor_ref in seed.actor_profiles():
            engine.assess("ramify:demo:supp:apex-mg-glyc-120", actor_ref)
        after = engine.assess("ramify:demo:supp:apex-mg-glyc-120", "consumer_v1")
        self.assertEqual(baseline["objective_posture"], after["objective_posture"])
        self.assertEqual(baseline["actor_decision"], after["actor_decision"])
        self.assertEqual(
            baseline["receipt"]["check_results"], after["receipt"]["check_results"]
        )


class Direction8_NoPaediatricExamples(unittest.TestCase):
    """Unnecessarily high risk for a synthetic demonstration. Supplements,
    cosmetics, sterile gloves and protective equipment carry the same value.
    """

    # Checked against what the demonstration actually shows — product names,
    # brands and claim values — rather than the whole file, which legitimately
    # contains the phrases "no paediatric medicine" and "non-prescription".
    FORBIDDEN = ("paediatric", "pediatric", "infant", "baby", "toddler", "paracetamol", "ibuprofen")

    def test_no_product_is_paediatric(self):
        for ref, record in seed.subjects().items():
            surface = " ".join(
                [record["name"], record["brand"]]
                + [str(c.get("value", "")) for c in record.get("claims", [])]
            ).lower()
            with self.subTest(subject=ref):
                for word in self.FORBIDDEN:
                    self.assertNotIn(word, surface)

    def test_no_product_is_a_prescription_medicine(self):
        for ref, record in seed.subjects().items():
            with self.subTest(subject=ref):
                self.assertIn(record["category"], ("supplement", "protective_equipment"))

    def test_only_the_two_agreed_categories_are_used(self):
        self.assertEqual(set(seed.seed()["categories"]), {"supplement", "protective_equipment"})


class Direction9_HonestyBoundary(unittest.TestCase):
    """The specification's own boundary: the demo is small but not fake. The
    scope of the data is what is small, not the integrity of the operations.
    """

    def test_the_synthetic_notice_travels_with_every_receipt(self):
        receipt = engine.assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        self.assertIn("Synthetic", receipt["notice"])
        self.assertIn("certifies nothing", receipt["notice"])

    def test_every_page_carries_a_visible_disclaimer(self):
        # Static markup rather than something injected at runtime, so a page
        # that fails to reach the API still tells the reader what it is.
        for page in WEB_DIR.glob("pages/*.html"):
            body = page.read_text(encoding="utf-8").lower()
            with self.subTest(page=page.name):
                self.assertIn('class="disclaimer"', body)
                self.assertIn("synthetic", body)
                self.assertIn("not for real purchasing", body)

    def test_signatures_are_real_rather_than_simulated(self):
        source = (PACKAGE_ROOT / "crypto" / "sign.py").read_text(encoding="utf-8")
        self.assertIn("Ed25519", source)
        for word in ("_sim", "simulated", "placeholder", "fake"):
            self.assertNotIn(word, source.lower())


class SpecificationConstraints(unittest.TestCase):
    """From the signed specification rather than the correspondence."""

    def test_no_frontend_framework_or_build_step(self):
        # Section 13 declines frontend frameworks, npm tooling and build
        # pipelines outright.
        project_root = PACKAGE_ROOT.parents[1]
        for artefact in ("package.json", "node_modules", "webpack.config.js", "vite.config.js"):
            with self.subTest(artefact=artefact):
                self.assertFalse((project_root / artefact).exists())

        for asset in WEB_DIR.glob("scripts/*.js"):
            body = asset.read_text(encoding="utf-8")
            with self.subTest(asset=asset.name):
                self.assertNotIn("import ", body.split("\n")[0])
                self.assertNotIn("require(", body)

    def test_the_frontend_makes_no_external_request(self):
        for asset in list(WEB_DIR.glob("scripts/*.js")) + list(WEB_DIR.glob("pages/*.html")):
            body = asset.read_text(encoding="utf-8")
            with self.subTest(asset=asset.name):
                for scheme in ("https://", "http://"):
                    for line in body.split("\n"):
                        if scheme in line and "127.0.0.1" not in line:
                            self.fail(f"{asset.name} references an external host: {line.strip()}")

    def test_five_postures_and_six_precedence_rules(self):
        # Amendment v0.4.1 item 4 corrected the Implementation Contract, which
        # had miscounted them as six postures.
        self.assertEqual(len(RESTRICTIVENESS), 5)
        self.assertEqual(len(seed.policy_pack()["precedence"]["rules"]), 6)

    def test_latencies_are_integer_microseconds(self):
        receipt = engine.assess("ramify:demo:supp:apex-mg-glyc-120")["receipt"]
        for stage, value in receipt["latencies_us"].items():
            with self.subTest(stage=stage):
                self.assertIsInstance(value, int)

    def test_no_float_can_enter_a_canonical_form(self):
        with self.assertRaises(ValueError):
            canonicalise_receipt({"unit_price": 34.95})


if __name__ == "__main__":
    unittest.main()
