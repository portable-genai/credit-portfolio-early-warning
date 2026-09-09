# The shipped obligor book

Everything in these files is **fictional**. Every party announces itself as `(FICTIONAL)`, every
address is an `.example` domain, and the one national identifier present is a synthetic
checksum-valid literal whose only job is to prove that redaction happened.

One file per managed BigQuery table, newline-delimited JSON, each row's keys in that table's
column order. The same files feed four readers, which is the point of them being files:

| Reader | How it reads them |
|---|---|
| the offline profiles | `adapters/local/portfolio_feed.py`, through DuckDB, over the same schema and the same SQL the warehouse answers |
| the deployment | `scripts/load_demo_book.py`, into `obligor_metrics` in the project's dataset |
| the demo and the eval | `adapters/local/_fixtures.py`, which builds its metric windows and arrears snapshots from these rows rather than declaring a second set |
| the tests | `tests/contract/test_demo_book.py`, which holds these columns against `infra/terraform/bigquery.tf` |

## Units

`drawn_amount` and `past_due_amount` are **major** units, decimal: 7800000.0 is SGD 7,800,000.00.
Both adapters convert to minor units at the boundary through `demo_book.minor`, so the domain
only ever compares integers. This is written down because the Terraform used to say the opposite
and the two stores would have disagreed by a factor of a hundred on the leg that decides whether
arrears are material at all.

## The foreign obligor

`obl-omega-999` belongs to `other-bank` and exists so the cross-tenant refusal has something to
refuse. The loader does not fold it into the deployment's tenant; see `CROSS_TENANT` in
`demo_book.py`. Delete its rows and the 403 path still passes offline while doing nothing at all
on the warehouse it exists to police.

## The as-of date

The book is written against `2026-06-30`, and every window and snapshot is measured from that
date rather than from today's. The managed adapter takes `as_of` as a parameter for the same
reason: a fictional warehouse pinned to a clock empties itself as it ages, and the demo goes
quiet with nothing red anywhere.
