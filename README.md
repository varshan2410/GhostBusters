# GhostBusters

GhostBusters is a safety-focused FinOps agent for Terraform-driven cost-remediation workflows. It parses Terraform plan JSON, gathers project and operational evidence, compares remediation alternatives, verifies safety constraints, evaluates deterministic policy, and requires human review before producing a mock pull-request record.

This is a hackathon prototype. It does **not** apply real infrastructure changes, merge code, or create real GitHub pull requests.

## Environment setup

```powershell
cd D:\Nutrex\GhostBusters
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

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

## Persistence

When `DATABASE_URL` is set, workflow snapshots, evidence records, approvals, waivers, and audit events are stored in PostgreSQL. When it is absent, tests and lightweight development can use the in-memory store. Redis provides short-lived GitHub delivery lookup; PostgreSQL idempotency is the durable fallback.

See `PROJECT_STATUS.md` for the current architecture, complete workflow, implemented features, and remaining limitations.

