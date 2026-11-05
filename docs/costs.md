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

Put these settings in the selected environment file, such as `.env.production`, and restart through the normal launcher after installing the updated requirements:

1. Set `PINECONE_COSTS_ENABLED=true`.
2. Set `PINECONE_PROJECT_ID` to the ID from your Pinecone project's settings/list, and set the existing server-side `PINECONE_API_KEY` for that project.
3. Optionally set `PINECONE_COSTS_RATES_JSON` with the verified read/write prices per million units for every observed cloud/region, plus `PINECONE_COSTS_PRICE_DATE=YYYY-MM-DD` and `PINECONE_COSTS_PRICE_SOURCE=https://www.pinecone.io/pricing/`.

The rate-map structure is:

```text
PINECONE_COSTS_RATES_JSON={"aws/us-east-1":{"read_usd_per_million":"COPY_VERIFIED_RATE","write_usd_per_million":"COPY_VERIFIED_RATE"}}
```

Replace both placeholders using the current [applicable Pinecone prices](https://www.pinecone.io/pricing/); they are deliberately not example numeric prices. Add entries for other cloud/region combinations as needed. Prices must be finite and nonnegative, the verification date cannot be in the future, and the dashboard warns when prices are more than 30 days old. Without configured rates, observed quantities remain available and dollar estimates stay unavailable.

One app-owned collector checks the durable snapshot every five minutes; dashboard polling every 15 seconds reads only that snapshot. The collector uses authenticated read-only discovery and metric requests, with provider HTTPS target validation, bounded responses and deadlines, and no redirects. It does not issue vector searches, mutations, embedding requests or model calls. Shutdown waits for an active bounded collection before releasing its worker.

The first sample establishes a private baseline, not zero spending. Subsequent observed nonnegative read/write deltas use the stamped configured prices. Reset/new/disappearing series and collection gaps are reported as limitations. Intervals spanning a UTC day/month boundary are excluded, because the exact timing of their usage is unknown; no prorating or historical backfill is performed. The current-month view never substitutes a previous month's report. Adjacent fully observed ranges are combined only within one UTC day with equal pricing and coverage, preserving exact sums and bounds.

Storage is a current byte quantity; storage charges are excluded because a single quantity does not establish billed storage over time. Backups, egress, inference, Assistant and dedicated read-node charges are also outside the estimate. Unsupported capacity modes remain explicitly excluded. This is a partial observed usage estimate, not a complete monthly bill.

The [Standard monthly minimum](https://docs.pinecone.io/guides/cost/understand-cost#minimum-usage) defaults to the separately displayed USD 50 commitment; `PINECONE_COSTS_MONTHLY_MINIMUM_USD` can describe your applicable commitment. It is never added to partial observed usage or treated as an exact invoice.

Missing or invalid environment settings produce a disabled/not-configured view and no remote requests. Live metrics verification requires the configured project ID and API key; it is not claimed when either is absent. Private baseline state remains in the same environment-scoped local snapshot directory as AWS and is excluded from API responses. Running another machine/checkout creates independent coverage rather than shared account history.
