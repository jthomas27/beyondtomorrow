# Publishing and email recovery

Apply PostgreSQL migration `0002_delivery_and_email_jobs.sql` before deploying
the worker. It adds tables without modifying articles or the existing corpus.

## Durable requests

The worker reads IMAP with `BODY.PEEK[]`, commits each request to PostgreSQL,
then marks the message read. Duplicate raw requests share a SHA-256 job ID.
An atomic claim and renewable lease prevent concurrent processing. Expired
running jobs become eligible for recovery after ten minutes. A lease-renewal
failure cancels processing. Failed/partial jobs require an explicit retry:

```sh
.venv/bin/python scripts/retry_email_job.py
.venv/bin/python scripts/retry_email_job.py --retry JOB_ID
```

Completed jobs discard their raw email; failed/partial jobs retain it for retry.
Treat these database records as private mailbox data and include them in normal
backup/access controls. Retry never clears prior delivery receipts.

Commands require an allowlisted From address and an aligned DMARC pass in the
first Authentication-Results header from the receiving Hostinger server. This
assumes Hostinger prepends its own result and rejects/removes forged headers
claiming its authentication identity. Forwarded messages that fail DMARC are
rejected; send commands directly from the approved account. Receiver hostnames
are restricted to the observed regional Hostinger SMTP ingress format.

## Publications and delivery

Ghost creation uses a durable receipt keyed by email job ID or source filename.
A replay returns the saved Ghost post ID and URL. An existing matching slug is
never deleted or automatically overwritten. Workflow delivery uses the tool's
stored receipt rather than trusting the publisher model's claimed URL.

LinkedIn receipts are keyed by article URL and profile. Newsletter receipts are
per article and recipient hash. Legacy local success logs are read only during
transition. New successes are persisted in PostgreSQL. Missing database access
blocks new deliveries rather than silently losing deduplication.

Resend requests use stable idempotency keys and preserve their original payload
for uncertain retries. The provider keeps keys for 24 hours; the worker stops
automatic retries after 23 hours for an ambiguous send. Ghost/LinkedIn do not
offer this same guarantee: an interrupted create remains `sending` and requires
operator reconciliation before another create. This intentionally favours
preventing duplicates over speculative retries.

Newsletter selection requires one active newsletter, or `GHOST_NEWSLETTER_ID`
when several are active. Only explicitly subscribed, unsuppressed free members
are included. Unsubscribe links use Ghost member/newsletter identifiers. Partial
delivery reports an error and retries only unfinished recipients.

CLI exit codes: `0` complete, `1` failed, `2` published with unfinished stages.
Keep the known Ghost URL when indexing or a later delivery fails.

## Theme maintenance

See [theme/README.md](../theme/README.md). Edit source CSS/JavaScript/templates,
build the injection artifacts, deploy once and retain the private rollback copy.
