"""Minimal stdlib CLI: review one obligor, list the book, or verify the audit chain."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from hex_service_kit.logging import configure_logging

from ..config import build_container, build_review_service

#: Service name on every log line, matching what the API and the tracer report.
_SERVICE_NAME = "credit-portfolio-early-warning"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="credit_portfolio_ews")
    sub = parser.add_subparsers(dest="command", required=True)

    review_cmd = sub.add_parser("review", help="Review one obligor and propose a grade.")
    review_cmd.add_argument("obligor_id")
    review_cmd.add_argument("--test-period", default="", help="Empty means the latest reported.")
    review_cmd.add_argument("--as-of", default="", help="ISO date. Empty means today.")
    review_cmd.add_argument("--actor", default="cli-user@bank.example")
    review_cmd.add_argument("--tenant", default="", help="Tenant partition asserted to Hrz7.")

    list_cmd = sub.add_parser("obligors", help="List the obligors this tenant's registry holds.")
    list_cmd.add_argument("--tenant", default="")

    args = parser.parse_args(argv)
    container = build_container()
    # Idempotent: a process that is both an API app and a CLI entry point configures once.
    configure_logging(container.settings.profile, service=_SERVICE_NAME)
    tenant = args.tenant or container.settings.tenant
    service = build_review_service(container)

    if args.command == "obligors":
        for record in service.obligors(tenant):
            print(f"{record.obligor_id}  {record.current_grade.value:<16} {record.name}")
        return 0

    if args.command == "review":
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
        review = service.review(
            args.obligor_id,
            tenant=tenant,
            actor=args.actor,
            as_of=as_of,
            test_period=args.test_period,
        )
        assessment = review.assessment
        proposal = assessment.proposal
        print(
            f"{assessment.obligor_id} {assessment.test_period}: "
            f"{proposal.current_grade.value} -> {proposal.proposed_grade.value} "
            f"({proposal.movement.value}, {proposal.notches} notches)"
        )
        print(
            f"  composite {assessment.composite_score} (band {proposal.band_grade.value}), "
            f"floors {', '.join(proposal.applied_floors) or 'none'}"
        )
        print(f"  requires_human_review: {assessment.requires_human_review}")
        print(f"  grade_applied: {review.grade_applied}")
        if assessment.requires_human_review:
            # Rule R8 on the CLI path too: the same proposal, the same router. A surface that
            # only printed the flag would be a second place an escalation can stop.
            print(f"  routed to human review: {review.review_ref}")
            print(f"  approvals required: {review.required_approvals}")
        return 0

    return 2  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
