# Cost tracking

The Dashboard's **Costs** tab shows the current UTC calendar month's AWS spending, daily totals, and service breakdown. Amounts use AWS's **UnblendedCost** basis and show whether AWS considers them estimated; they cover the billing data visible to the configured credentials across the account. They are provisional billing figures, not a final invoice.

Set these in your normal environment file, then update dependencies and restart through the application's usual workflow:

```dotenv
AWS_COSTS_ENABLED=true
# Optional named AWS CLI/SDK profile; otherwise use the standard AWS credential chain.
AWS_COSTS_PROFILE=default
```

The identity needs `ce:GetCostAndUsage`, and Cost Explorer must be enabled for the account. Existing `aws login` profiles are supported through the required `boto3[crt]` dependency; the Bedrock bearer token alone does not authorize billing requests. Credentials remain server-side.

Cost Explorer charges **$0.01 per paginated request**. Successful reports are cached for 24 hours; failures retry after at least 30 minutes, capped at three attempts per UTC day. Dashboard polling every 15 seconds reuses that cache. Each actual provider request is logged through the existing observability layer. Missing access and failed refreshes display explicitly, and previous reports remain visibly stale rather than becoming zero.

Private snapshots use the existing atomic JSON writer and cross-process lock in `.runtime/costs/<APP_ENV>`, surviving app restarts. `COSTS_CACHE_PATH` optionally selects an absolute private local directory. Separate devices or checkouts have separate caches and may each issue billing queries; network filesystems and non-POSIX locking are not supported. Cache age plus AWS's own reporting delay can put the display roughly 48 hours behind usage.

[AWS cost API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html) · [API pricing and reporting delay](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-what-is.html) · [AWS login support](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html)

## Pinecone Standard: observed usage estimates

The Pinecone provider uses the [documented Prometheus monitoring interface](https://docs.pinecone.io/guides/production/monitoring), available on Standard, without CSV imports or an Enterprise upgrade. It observes counters going forward; it cannot retrieve historical invoices or usage before monitoring began.

Put these settings in the selected environment file, such as `.env.production`, and restart through the normal launcher:

1. Set `PINECONE_COSTS_ENABLED=true`.
2. Set `PINECONE_PROJECT_ID` to the ID from your Pinecone project's settings/list, and set the existing server-side `PINECONE_API_KEY` for that project.

Pricing settings are not required. The [bundled catalog](../services/costs/pinecone_pricing.py) is the application's authoritative reference for [Pinecone Standard cloud/region rates](https://www.pinecone.io/pricing/), checked on **2026-11-05**, in USD per million units. It uses the region-specific Standard table, rather than Enterprise rates or the pricing page's general summary range.

This versioned reference is part of the application; collection does not scrape prices at runtime. Unpublished regions retain observed quantities with an explicit missing-price notice and no dollar total. The dashboard warns when a reference is more than 30 days old.

Advanced overrides remain optional: `PINECONE_COSTS_RATES_JSON` replaces the complete rate map, for example `{"aws/us-east-1":{"read_usd_per_million":"16","write_usd_per_million":"4"}}`. Rates must be finite and nonnegative. `PINECONE_COSTS_PRICE_DATE` defaults to the fixed bundled reference date, and `PINECONE_COSTS_PRICE_SOURCE` defaults to the public pricing page; an explicitly supplied date must be valid and nonfuture. The date is reference metadata, not independent verification of custom rates, which the dashboard identifies as user-supplied. Each interval retains its original pricing stamp, so changing overrides never reprices older observations.

Complete unfilled `REPLACE_WITH_...` price templates, including their date and minimum placeholders, use the bundled defaults. Partially filled or malformed real overrides fail visibly instead of silently falling back.

The project ID is still required. Pinecone's [project API keys cannot access project settings](https://docs.pinecone.io/admin/projects/understanding-projects), and the documented [index metadata](https://docs.pinecone.io/reference/api/2025-10/control-plane/describe_index) does not include a project ID. The application does not guess it from hostnames or request another credential; a missing or placeholder `PINECONE_PROJECT_ID` displays a specific configuration message before any monitoring request.

One app-owned collector checks the durable snapshot every five minutes; dashboard polling every 15 seconds reads only that snapshot. The collector uses authenticated read-only discovery and metric requests, with provider HTTPS target validation, bounded responses and deadlines, and no redirects. It does not issue vector searches, mutations, embedding requests or model calls. Shutdown waits for an active bounded collection before releasing its worker.

The first sample establishes a private baseline, not zero spending. Subsequent observed nonnegative read/write deltas use the stamped configured prices. Reset/new/disappearing series and collection gaps are reported as limitations. Intervals spanning a UTC day/month boundary are excluded, because the exact timing of their usage is unknown; no prorating or historical backfill is performed. The current-month view never substitutes a previous month's report. Adjacent fully observed ranges are combined only within one UTC day with equal pricing and coverage, preserving exact sums and bounds.

Storage is a current byte quantity; storage charges are excluded because a single quantity does not establish billed storage over time. Backups, egress, inference, Assistant and dedicated read-node charges are also outside the estimate. Unsupported capacity modes remain explicitly excluded. This is a partial observed usage estimate, not a complete monthly bill.

The [Standard monthly minimum](https://docs.pinecone.io/guides/cost/understand-cost#minimum-usage) defaults to the separately displayed USD 50 commitment; `PINECONE_COSTS_MONTHLY_MINIMUM_USD` can describe your applicable commitment. It is never added to partial observed usage or treated as an exact invoice.

Missing or invalid environment settings produce a disabled/not-configured view and no remote requests. Live metrics verification requires the configured project ID and API key; it is not claimed when either is absent. Private baseline state remains in the same environment-scoped local snapshot directory as AWS and is excluded from API responses. Running another machine/checkout creates independent coverage rather than shared account history.
