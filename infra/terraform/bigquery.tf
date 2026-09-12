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
# and never applies one, and it does not write here either: in production the tables are
# populated by whatever already spreads the book. For a DEMO deployment the rows come from
# `scripts/load_demo_book.py`, which runs as an operator and never as the service, and which
# fills tables rather than creating them -- a table missing here is a load that exits before
# its first row.

resource "google_bigquery_dataset" "obligor" {
  dataset_id = "obligor_metrics" # matches CREDITEWS_METRICS_DATASET
  project    = var.project_id
  # The EFFECTIVE region, never var.region, which defaults to null. `location` is
  # OPTIONAL on this resource, so a null here does not fail the plan: it silently
  # creates the dataset in the US multi-region and breaks residency with a green gate.
  location    = local.region # P-03
  description = "Obligor financial metrics and servicing history for credit-portfolio-early-warning (internal, CMEK)."

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

  # The same key the dataset names, declared again here on purpose. The dataset's
  # default_encryption_configuration makes BigQuery stamp that key onto every table it creates in
  # the dataset, so the live table carries an encryption_configuration whether or not this
  # resource declares one. Leaving it undeclared makes the next plan read the server-set block as
  # a REMOVAL, and removing an encryption configuration FORCES REPLACEMENT: the table is destroyed
  # and recreated, and a recreated table holds no rows. CMEK does not cascade in Terraform's model
  # even though it does in BigQuery's, which is why the key is named twice.
  encryption_configuration {
    kms_key_name = google_kms_crypto_key.cmek.id
  }

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

  # The same key the dataset names, declared again here on purpose. The dataset's
  # default_encryption_configuration makes BigQuery stamp that key onto every table it creates in
  # the dataset, so the live table carries an encryption_configuration whether or not this
  # resource declares one. Leaving it undeclared makes the next plan read the server-set block as
  # a REMOVAL, and removing an encryption configuration FORCES REPLACEMENT: the table is destroyed
  # and recreated, and a recreated table holds no rows. CMEK does not cascade in Terraform's model
  # even though it does in BigQuery's, which is why the key is named twice.
  encryption_configuration {
    kms_key_name = google_kms_crypto_key.cmek.id
  }

  schema = jsonencode([
    { name = "obligor_id", type = "STRING", mode = "REQUIRED" },
    { name = "tenant", type = "STRING", mode = "REQUIRED" },
    { name = "currency", type = "STRING", mode = "REQUIRED" },
    # MAJOR units, exact decimal. The domain compares integers and never a currency float, and
    # the conversion to minor units happens at the ADAPTER boundary on both sides
    # (`credit_portfolio_ews.demo_book.minor`, imported by the managed adapter and the local
    # store alike). These columns were declared INTEGER and described as minor units, while the
    # adapter has always multiplied what it reads by a hundred; both could not be true. The
    # adapter is what runs and its own test double answers a decimal major amount, so the schema
    # was the half that was wrong -- and an INTEGER here cannot hold cents at all. Left as it
    # was, the absolute leg of the arrears materiality gate would have run on figures a hundred
    # times too large and classified obligors the laptop calls immaterial. NUMERIC rather than
    # FLOAT64 because money in a float is a rounding argument.
    { name = "drawn_amount", type = "NUMERIC", mode = "REQUIRED" },
    { name = "past_due_amount", type = "NUMERIC", mode = "REQUIRED" },
    { name = "days_past_due", type = "INTEGER", mode = "REQUIRED" },
    { name = "as_of", type = "DATE", mode = "REQUIRED" },
    { name = "source_ref", type = "STRING", mode = "REQUIRED" },
  ])
}

# The manifest the demo loader writes LAST, because it records the load that wrote the others.
# It is deliberately not one of this repository's own tables: `hex_service_kit.demobook` keeps it
# out of `TABLES` and appends it in `load_order()`, and the loader creates nothing, so a manifest
# missing from here is a load that exits on a not-found before writing a single row. A sibling
# repository shipped exactly that and three green gates could not see it, because the guard
# iterated the repository's tables rather than the set the loader writes.
#
# `fictional` is what the overwrite guard reads. A demo loader truncates, which is right for a
# demo book and catastrophic for a real one, so it proceeds only when every table is empty or
# this row says what the dataset holds is fictional.
resource "google_bigquery_table" "book_manifest" {
  dataset_id          = google_bigquery_dataset.obligor.dataset_id
  table_id            = "book_manifest"
  project             = var.project_id
  deletion_protection = true

  # The same key the dataset names, declared again here on purpose. The dataset's
  # default_encryption_configuration makes BigQuery stamp that key onto every table it creates in
  # the dataset, so the live table carries an encryption_configuration whether or not this
  # resource declares one. Leaving it undeclared makes the next plan read the server-set block as
  # a REMOVAL, and removing an encryption configuration FORCES REPLACEMENT: the table is destroyed
  # and recreated, and a recreated table holds no rows. CMEK does not cascade in Terraform's model
  # even though it does in BigQuery's, which is why the key is named twice.
  encryption_configuration {
    kms_key_name = google_kms_crypto_key.cmek.id
  }

  schema = jsonencode([
    { name = "book_version", type = "STRING", mode = "REQUIRED" },
    { name = "as_of_date", type = "DATE", mode = "REQUIRED" },
    { name = "fictional", type = "BOOL", mode = "REQUIRED" },
    { name = "loaded_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "source_commit", type = "STRING", mode = "NULLABLE" },
    { name = "tenant", type = "STRING", mode = "REQUIRED" },
  ])
}
