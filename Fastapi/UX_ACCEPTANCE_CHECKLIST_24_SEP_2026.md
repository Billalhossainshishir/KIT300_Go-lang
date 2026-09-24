# RAMIFY OS UX acceptance checklist

Build target: v11.0.7 UX hardening patch

## Implemented code checks
- [x] Button hover/focus labels remain readable.
- [x] Large visual hero retained on Shop; ordinary pages use compact page heads.
- [x] Decorative result scan removed so ALLOW/APPROVE has no stray animated line.
- [x] Basket and Human Review action controls wrap instead of covering text.
- [x] Receipt summary shows receipt integrity, evidence validity, permitted action and purchase-authority state separately.
- [x] Human receipt summary separates integrity, machine result, human outcome and transaction authority.
- [x] Product images are forced to `object-fit: contain`.
- [x] Persona colours remain separate from green/amber/red trust colours.
- [x] Main Shop journey remains Product/Request -> RAMIFY -> Agent -> Receipt -> Checkout.
- [x] Needs me and Activity remain primary navigation; Human receipts now has a direct navigation entry.
- [x] First-run popup wording shortened and kept non-technical.
- [x] Guided Demo remains deterministic and does not itself create purchase authority.
- [x] Scenario Lab, Presentation Mode, sound toggle and AI-mode toggle are not reintroduced.
- [x] Choosing/editing a different product clears stale result, evidence, alternatives and verification output without deleting historical receipts.
- [x] Responsive/focus hardening added for smaller widths and keyboard users.

## Manual acceptance on the presentation laptop
Run these before client handover:
- [ ] 1440px desktop: no overlaps/clipping.
- [ ] 1024px window: no overlaps/clipping.
- [ ] 768px window: action buttons wrap and remain readable.
- [ ] Keyboard-only: Tab through top navigation, Shop controls, receipt tabs and action buttons; focus is always visible.
- [ ] Shop -> select product -> change product: old result/receipt panels disappear before the next assessment.
- [ ] Blocked authentic receipt: UI shows authentic receipt separately from purchase permission.
- [ ] Expired authentic receipt: integrity remains distinguishable from expired/non-current authority.
- [ ] Human receipt: original machine result and successor authority are understandable without opening JSON.

## External usability check (not yet claimed as completed)
Use 5-8 people if time permits. Record: Task | Understood without help? | Issue | Fix.
Suggested tasks: choose product, understand result, find Needs me, identify whether checkout is permitted, verify a receipt, find Human receipts.
