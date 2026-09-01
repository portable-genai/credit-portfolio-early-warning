# bigquery.tf : the obligor metrics and servicing dataset this vertical reads (CMEK, read-only).
#
# General Principle map:
#   P-03 (residency): the dataset is created in var.region, validated against allowed_regions, so
#         obligor financials and arrears never leave the deployment's country.
#   P-09 (CMEK explicit): the dataset encrypts under the regional key from kms.tf. CMEK does not
#         cascade, so the BigQuery service-agent key binding is declared there alongside it. A
#         dataset created with no key binding encrypts under Google-managed keys and looks
#         identical in the console, which is why the binding is not left implicit.
#   P-04 (data minimisation): the columns below are exactly the ones the adapter selects. A
#         schema wider than the query is a standing invitation to read more than the decision
#         needs.
#
# This dataset backs PortfolioFeedPort (credit_portfolio_ews.adapters.gcp.portfolio_feed). The
# dataset id is deployment configuration, read from CREDITEWS_METRICS_DATASET; an unconfigured
# dataset makes the adapter RAISE rather than return an empty window, because an empty window
# would read as an obligor with nothing wrong.
#
# The serving identity gets dataViewer and nothing more (iam.tf). This service proposes a grade
# and never applies one, and it does not write here either: there is no ingestion path in this
# repository, and the tables are populated by whatever already spreads the book.

resource "google_bigquery_dataset" "obligor" {
  dataset_id = "obligor_metrics" # matches CREDITEWS_METRICS_DATASET
  project    = var.project_id
  # The EFFECTIVE region, never var.region, which defaults to null. `location` is
  # OPTIONAL on this resource, so a null here does not fail the plan: it silently
  # creates the dataset in the US multi-region and breaks residency with a green gate.
  location    = local.region # P-03
  description = "Obligor financial metrics and servicing history for Doc7 (internal, CMEK)."

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.cmek.id # CMEK does not cascade (P-09)
  }

  # Internal credit data: never world-readable, and never dropped with the stack.
  delete_contents_on_destroy = false

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.bigquery,
  ]
}

# The spread financials the signal rules read. `tenant` is a REQUIRED column rather than a
# convention: every query in the adapter is tenant-scoped, and the isolation refusal reads this
# column to distinguish "not yours" from "does not exist".
resource "google_bigquery_table" "obligor_metrics" {
  dataset_id          = google_bigquery_dataset.obligor.dataset_id
  table_id            = "obligor_metrics"
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "obligor_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant", type = "STRING", mode = "REQUIRED" },
    { name = "metric", type = "STRING", mode = "REQUIRED" },
    { name = "value", type = "NUMERIC", mode = "REQUIRED" },
    { name = "period", type = "STRING", mode = "REQUIRED" },
    { name = "as_of", type = "DATE", mode = "REQUIRED" },
    { name = "unit", type = "STRING", mode = "NULLABLE" },
    # Every figure the engine states carries a citation, and these two columns are where it
    # comes from. A row that cannot say where it came from cannot enter an assessment.
    { name = "source", type = "STRING", mode = "REQUIRED" },
    { name = "source_ref", type = "STRING", mode = "REQUIRED" },
  ])
}

# The servicing record behind the arrears clocks. One row is read per assessment, the most
# recent at or before the reporting date, so the ordering columns are part of the contract.
resource "google_bigquery_table" "obligor_servicing" {
  dataset_id          = google_bigquery_dataset.obligor.dataset_id
  table_id            = "obligor_servicing"
  project             = var.project_id
  deletion_protection = true

  schema = jsonencode([
    { name = "obligor_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant", type = "STRING", mode = "REQUIRED" },
    { name = "currency", type = "STRING", mode = "REQUIRED" },
    # Minor units, integer: the materiality legs compare integers, and a float would make the
    # absolute leg disagree with itself at the boundary.
    { name = "drawn_amount", type = "INTEGER", mode = "REQUIRED" },
    { name = "past_due_amount", type = "INTEGER", mode = "REQUIRED" },
    { name = "days_past_due", type = "INTEGER", mode = "REQUIRED" },
    { name = "as_of", type = "DATE", mode = "REQUIRED" },
    { name = "source_ref", type = "STRING", mode = "REQUIRED" },
  ])
}
