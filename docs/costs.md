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
