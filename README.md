# GhostBusters

GhostBusters is a safety-focused FinOps agent for Terraform-driven cost-remediation workflows. It parses Terraform plan JSON, gathers project and operational evidence, compares remediation alternatives, verifies safety constraints, evaluates deterministic policy, and requires human review before producing a mock pull-request record.

This is a hackathon prototype. It does **not** apply real infrastructure changes, merge code, or create real GitHub pull requests.

## Cloud Hunt Mode (Milestone 7A)

Cloud Hunt is the second entry path alongside Terraform PR Review:

```text
Cloud Hunt inventory scan -> normalized resources -> deterministic ghost candidates
  -> evidence and protective-signal review -> policy -> human review -> simulated PR
```

“Cloud Hunt Mode currently uses controlled multi-cloud inventory fixtures. It demonstrates provider-independent discovery, investigation, policy, and human review. Real cloud credentials and mutation APIs are intentionally not required for the competition prototype.”

Run one fixture-backed hunt from PowerShell:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_cloud_hunt --provider multi_cloud
.\.venv\Scripts\python.exe -m scripts.run_cloud_hunt --provider aws
```

The provider registry exposes the same read-only adapter contract for AWS, Azure, and Google Cloud. The current adapters load `fixtures/cloud_inventory.json`; they do not call cloud APIs and never mutate resources. Each resource is normalized into `CloudResource`, then deterministic scoring creates `GhostCandidate` records. Low utilization alone is insufficient: age, ownership, activity, dependencies, cost, attachment state, and environment are considered together.

Positive signals include low utilization, old age, missing ownership, completed work, no recent activity, no dependencies, ongoing cost, unattached storage, and idle public IPs. Recent activity, active dependencies, production environment, and other protective signals reduce confidence or block remediation. Production and dependency-protected resources remain visible but cannot be approved for automatic remediation.

Use the dashboard's **Cloud Hunt** mode to start a scan and inspect candidates. **Review Queue** combines Terraform PR and Cloud Hunt cases. Reviewers can approve, reject, request evidence, add context, modify the recommendation, or create a waiver. Waivers suppress the resource until their expiry date and are recorded in the case audit trail. A Cloud Hunt approval creates only a simulated PR record. Unmanaged resources receive an import/Jira/platform-owner proposal and never receive a fabricated Terraform address or patch. Scheduled execution is not enabled automatically; a future scheduler can call the CLI entry point.

Cloud Hunt API endpoints:

```text
GET  /api/cloud/providers
GET  /api/cloud/hunt/fixtures
POST /api/cloud/hunts
GET  /api/cloud/hunts
GET  /api/cloud/hunts/{hunt_id}
GET  /api/reviews
GET  /api/reviews/{review_id}
POST /api/reviews/{review_id}/action
```

Manual scenarios to demonstrate:

- `i-forgotten-test`: strong multi-signal candidate, eligible for simulated review.
- `i-staging-api`: low utilization with an active dependency; visible but protected.
- `gce-idle-test`: suspicious signals plus recent Git activity; requests human context.
- `i-healthy-prod` and `vm-prod-azure`: production resources remain protected.
- `vol-unattached-demo`, `disk-unattached-demo`, and `ip-unused-demo`: unattached or idle resources are candidates, but unmanaged resources do not receive fabricated Terraform patches.

Real AWS/Azure/GCP credentials, mutations, `terraform apply`, authentication, RBAC, and automatic scheduling are intentionally outside this milestone.

## Environment setup

```powershell
cd D:\Nutrex\GhostBusters
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Start local PostgreSQL and Redis with Docker Compose:

```powershell
docker compose up -d
docker compose ps
```

The local Docker PostgreSQL endpoint is `localhost:15432`, mapped to container port `5432`. Redis remains available on `localhost:6379`.

## Optional Gemini planning

Milestone 6 adds an optional reasoning layer around the existing deterministic workflow. Gemini may interpret the objective, propose a registered evidence tool, explain the next question, and request human context. GhostBusters validates every proposal before execution. Gemini never parses Terraform, calculates authoritative pricing or savings, computes confidence, runs verifier checks, enforces policy, approves a recommendation, generates a patch, merges a pull request, changes AWS, or runs `terraform apply`.

The default is deterministic-only mode and does not require internet access or an API key:

```dotenv
AI_ENABLED=false
AI_PROVIDER=gemini
AI_DETERMINISTIC_FALLBACK_ENABLED=true
```

The UI and audit trail record the actual planning mode: `deterministic_only`, `deterministic_fallback`, `gemini_primary`, `gemini_fallback_model`, or `mock_gemini`. Gemini failures, malformed responses, unsafe proposals, unknown tools, and step-limit exhaustion return to the deterministic planner without weakening verifier, policy, or human-review controls.

### Mock Gemini demo

Use the offline provider for a repeatable presentation without a key:

```powershell
$env:AI_ENABLED="true"
$env:AI_PROVIDER="mock"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The UI labels this `Mock Gemini Planner`; it never claims that a real Gemini request was made.

### Real Gemini mode

Install the official `google-genai` package from `requirements.txt`, then set the key only in the local process environment or ignored `.env` file:

```powershell
$env:AI_ENABLED="true"
$env:AI_PROVIDER="gemini"
$env:GEMINI_API_KEY="<local environment value>"
$env:GEMINI_MODEL="gemini-3.5-flash"
$env:GEMINI_FALLBACK_MODEL="gemini-2.5-flash-lite"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The primary model is attempted first. When it is unavailable or permission-ineligible, the configured fallback model is attempted. If both fail, the run records `deterministic_fallback`. API keys are read from the environment, never placed in prompts, audit records, serialized runs, or logs.

### Privacy and free-tier limits

Only the objective, a sanitized Terraform resource summary, registered tool descriptions, evidence summaries, unresolved questions, and deterministic safety constraints are eligible for the AI prompt. Hidden chain-of-thought, credentials, database URLs, Redis URLs, webhook secrets, tokens, unrelated audit history, and confidential provider data are not sent.

Do not send confidential company infrastructure or secrets through a free-tier model. Use only controlled demo data unless the organization has approved the provider and data-handling terms.

### AI troubleshooting and verification

Check the actual mode in the Simple View `Planning` badge or the Technical Audit `AI planning decisions` section. Useful controlled checks are:

```powershell
# Deterministic only
$env:AI_ENABLED="false"

# Mock mode, no key or network
$env:AI_ENABLED="true"
$env:AI_PROVIDER="mock"

# Missing-key fallback
$env:AI_ENABLED="true"
$env:AI_PROVIDER="gemini"
$env:GEMINI_API_KEY=""
```

Destructive and production fixtures always run the deterministic hard precheck and do not spend AI calls on normal optimization planning. Human context can resume the existing deterministic evaluation, but it cannot override production or destructive blocks, active dependencies, or critical verifier failures.

Start the API from the repository directory:

```powershell
python -m uvicorn app.main:app --reload
```

Useful endpoints:

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/api/runs`

## OPA and Conftest policy enforcement

[Open Policy Agent](https://www.openpolicyagent.org/) provides the Rego policy language. [Conftest](https://www.conftest.dev/) runs the Rego package in `policies/ghostbusters.rego` against a sanitized JSON representation of the current recommendation.

The policy input includes the resource environment and Terraform actions, whether the operation is destructive, ownership and dependency status, critical missing evidence, conflicts, critical verifier failures, confidence threshold, expected savings, risk, and reversibility. Raw evidence values, process environment variables, credentials, and subprocess environment details are not passed to Conftest or written to policy audit events.

Policies block:

- Unsafe production remediation
- Unexpected delete or destructive Terraform operations
- Remediation with unknown ownership
- Optimization with active critical dependencies
- Remediation with missing critical evidence
- Remediation with critical verifier failures
- Remediation below the configured confidence threshold

Safe non-production recommendations can proceed to mandatory human review. Safe no-change outcomes such as `keep` remain available.

### Install Conftest on Windows

Using [Scoop](https://scoop.sh/):

```powershell
scoop install conftest
conftest --version
```

Alternatively, download the Windows archive from the official [Conftest releases page](https://github.com/open-policy-agent/conftest/releases), extract `conftest.exe`, and either add its directory to `PATH` or set `CONFTEST_EXECUTABLE` to its full path.

### Configure policy execution

The local-development defaults in `.env.example` are:

```dotenv
CONFTEST_ENABLED=true
CONFTEST_EXECUTABLE=conftest
CONFTEST_POLICY_DIR=policies
CONFTEST_TIMEOUT_SECONDS=5
MINIMUM_POLICY_CONFIDENCE=0.70
```

`CONFTEST_POLICY_DIR` may be absolute or relative to the repository root. Set `CONFTEST_ENABLED=false` to deliberately use the Python fallback during development.

### Policy execution and fallback

The workflow order is:

```text
Terraform parsing
  -> investigation planning
  -> evidence collection
  -> conflict detection
  -> alternative generation
  -> verifier
  -> provisional confidence
  -> OPA/Rego through Conftest
  -> final confidence and status
  -> human review
```

The adapter invokes Conftest with a subprocess argument array, captures output without using `shell=True`, and applies a configured timeout. A Conftest exit code representing policy failures is treated as a policy denial, not an execution error.

If Conftest is disabled, missing, unavailable, times out, returns malformed JSON, or fails to execute, GhostBusters runs the existing deterministic Python policy engine. The returned policy result uses:

```json
{
  "engine": "python_fallback",
  "fallback_reason": "Conftest executable was not found."
}
```

Fallback is fail-safe: Conftest failure never causes the workflow to silently permit an unsafe recommendation. The audit history records policy start, selected engine, completion, allow/deny status, violation codes, and the fallback reason.

## Tests

Run the complete suite without requiring Conftest:

```powershell
python -m pytest -q
```

Run only policy adapter tests:

```powershell
python -m pytest tests\test_conftest_policy.py -q
```

If `conftest` is installed and visible on `PATH`, the optional real-Rego integration test runs automatically. Otherwise, only that integration test is skipped; all mocked subprocess and fallback tests still run.

You can also evaluate a prepared policy-input JSON manually:

```powershell
conftest test .\policy-input.json `
  --policy .\policies `
  --namespace ghostbusters
```

## External-call retries, timeouts, and safe failure

The Investigator executes each read-only evidence provider through the centralized retry wrapper in `core/retry.py`. A retry gives a temporary failure another bounded attempt. Exponential backoff increases the delay between attempts so a struggling provider is not called continuously:

```text
delay = min(initial_delay * multiplier ** retry_number + jitter, maximum_delay)
```

Retries are safe only for idempotent operations. Current evidence reads and Redis `GET`/`SET` operations are treated as idempotent. A future write such as GitHub pull-request creation must explicitly opt out unless it has its own idempotency key.

### Default retry configuration

```dotenv
EXTERNAL_RETRY_ENABLED=true
EXTERNAL_RETRY_MAX_ATTEMPTS=3
EXTERNAL_RETRY_INITIAL_DELAY_SECONDS=0.25
EXTERNAL_RETRY_MULTIPLIER=2
EXTERNAL_RETRY_MAX_DELAY_SECONDS=2
EXTERNAL_RETRY_JITTER_SECONDS=0.10
EXTERNAL_CALL_TIMEOUT_SECONDS=5
```

For deterministic debugging, disable retries while retaining one safe attempt:

```dotenv
EXTERNAL_RETRY_ENABLED=false
```

Set jitter to zero for predictable retry timing:

```dotenv
EXTERNAL_RETRY_JITTER_SECONDS=0
```

### Retried failures

- HTTP 408 and timeouts
- HTTP 429 rate limits
- HTTP 500, 502, 503, and 504
- Connection failures
- Temporary DNS/network failures
- Provider-specific errors explicitly classified as temporary

For HTTP 429, `Retry-After` is used when available and capped by `EXTERNAL_RETRY_MAX_DELAY_SECONDS`. Otherwise, exponential delay is used. Retries stop after the configured maximum attempt count.

### Failures that are not retried

- HTTP 400 invalid requests
- HTTP 401 authentication failures
- HTTP 403 authorization failures
- Genuine HTTP 404 resource absence
- Invalid provider configuration or credentials
- Invalid evidence response schemas
- Terraform validation failures
- Policy denials
- Local deterministic calculation or validation errors

Authentication and authorization failures are recorded as unavailable evidence with a safe category, but tokens, headers, raw request bodies, and raw exception text are not exposed.

### Timeout behavior

Real adapters must apply `EXTERNAL_CALL_TIMEOUT_SECONDS` in their HTTP or SDK client. The central wrapper classifies provider timeout exceptions as temporary and also rejects a synchronous result that returns after the configured deadline. This prototype does not create background worker threads to interrupt synchronous mock functions, avoiding abandoned thread work.

### Unavailable evidence

If all attempts fail, the provider produces an explicit evidence item with:

- `freshness_status: unavailable`
- No fabricated value
- Safe failure category
- Attempt count
- Retryable/exhausted status
- Sanitized final failure type

The existing missing-evidence, alternative-generation, verifier, policy, and confidence logic then lowers confidence and selects `request_evidence`, `abstain`, `keep`, or `blocked`. Missing utilization prevents precise rightsizing, and missing pricing prevents exact savings claims. When Jira is unavailable and Git activity is available, Git is recorded as alternative context without pretending it is Jira data.

### Retry audit events

Workflow audit history records these events in attempt order:

```text
external_call_started
external_call_failed
external_call_retry_scheduled
external_call_succeeded
external_call_exhausted
alternative_evidence_selected
```

Audit metadata is limited to the tool, attempt number, maximum attempts, safe failure category, retry delay, elapsed time, and run ID. Secrets and raw exception messages are excluded.

All current pricing, utilization, Jira, Git activity, and dependency providers remain mocked fixtures. Redis retry behavior is unit-tested, but a live Redis service has not been tested on this machine.

## Persistence

When `DATABASE_URL` is set, workflow snapshots, evidence records, approvals, waivers, and audit events are stored in PostgreSQL. For the local Docker setup, use `postgresql://ghostbusters:ghostbusters@localhost:15432/ghostbusters`. When it is absent, tests and lightweight development can use the in-memory store. Redis provides short-lived GitHub delivery lookup on `localhost:6379`; PostgreSQL idempotency is the durable fallback.

See `PROJECT_STATUS.md` for the current architecture, complete workflow, implemented features, and remaining limitations.

