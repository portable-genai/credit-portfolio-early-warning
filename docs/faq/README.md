# FAQ index

Answers to the questions different teams ask when evaluating, adopting or reviewing this
repository as a common base for post-origination credit monitoring. Each file is written for a
specific audience; skim the one that matches your role.

| FAQ | For | Answers |
|---|---|---|
| [security-faq.md](security-faq.md) | AppSec / security review | server-side identity, the exposure guard, tenant isolation, secrets, supply chain, the audit chain, what is in and out of scope |
| [portability-faq.md](portability-faq.md) | Architecture / cloud / exit planning | no-lock-in, the three profiles, the sovereign exit, data export |
| [features-faq.md](features-faq.md) | Product / credit / delivery | what the engine does, what is deterministic vs model-written, and the boundary with sibling catalog systems |
| [adoption-faq.md](adoption-faq.md) | Engineering leads forking the repo | rename, upstream fixes, extension points, what stays open |
| [compliance-faq.md](compliance-faq.md) | Compliance / model risk / second line | regulatory posture, maker-checker, residency, retention, model-risk evidence |

**If you read only one thing, read [`../model-card.md`](../model-card.md).** The scoring engine is
a model in the supervisory sense, it ships uncalibrated reference weights, and it has no backtest.
Every page here assumes you know that.

These FAQs deliberately do **not** re-document capabilities owned by sibling systems in the
catalog. Where a concern belongs to another repo (covenant extraction at origination in `credit-memo-drafting`,
model validation in the data-residency validator, the guardrail gateway `agent-guardrail-gateway`, the knowledge base `enterprise-knowledge-base`, the agent registry
`agent-registry`, the eval platform `model-quality-gate`, observability and WORM audit `agent-observability`, the human-review console `human-review-console`),
the FAQ points at it and explains the boundary rather than duplicating it. See
[features-faq.md](features-faq.md) for the full "what this repo owns vs what it integrates" map.

Authority order for anything these pages disagree with: [`SPEC.md`](../../SPEC.md), then
[`ARCHITECTURE.md`](../../ARCHITECTURE.md), then [`COMPLIANCE.md`](../../COMPLIANCE.md), then
[`README.md`](../../README.md). These pages restate; they do not decide.
