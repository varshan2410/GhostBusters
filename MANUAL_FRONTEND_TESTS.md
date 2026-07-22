# Manual Frontend Tests

## Cloud Hunt Mode

1. Open `http://127.0.0.1:8000/` and select **Cloud Hunt**.
2. Leave **Multi-cloud** selected and click **Start Cloud Hunt**.
3. Confirm the summary reports `10` resources across AWS, Azure, and Google Cloud.
4. Confirm `forgotten-test`, `vm-old-demo`, unattached resources, and `unused-static-ip` appear as possible ghost resources.
5. Confirm `staging-api` is visible with an active-dependency protection signal.
6. Select **Review Queue** and confirm Cloud Hunt cases show provider, confidence, savings, risk, and required reviewer role.
7. Approve the strong managed candidate and confirm the result is a simulated PR record only.
8. Reject a case and confirm no simulated PR is created.
9. Create a waiver through the API and run another hunt; confirm the waived resource is suppressed until expiry.

Equivalent PowerShell checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/cloud/providers
$hunt = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/cloud/hunts -ContentType 'application/json' -Body '{"provider_scope":"multi_cloud","inventory_source":"fixtures"}'
$hunt.summary
Invoke-RestMethod http://127.0.0.1:8000/api/reviews
python -m scripts.run_cloud_hunt --provider multi_cloud
```

The inventory is controlled fixture data. No AWS, Azure, or Google Cloud credentials are required, and no cloud resource is stopped, resized, deleted, or released.

Start the API and open `http://127.0.0.1:8000/`.

```powershell
docker compose up -d
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Version 2 Judge Checklist

1. **1366x768 projector:** verify body text, all eight workflow stages, evidence conclusions, controls, and runtime pills are readable with no horizontal overflow.
2. **Status pills:** verify API, Run, Policy, and Human pills use high-contrast text plus a visible icon/label; technical IDs remain secondary.
3. **Three-layer outcome:** confirm Agent recommendation, Human decision, and Final workflow outcome are distinct and never contradict one another.
4. **Rejected workflow:** reject a reviewable run; confirm the recommendation remains visible, Human decision says rejected, Final workflow outcome says the workflow closed, and no controls remain active.
5. **Pending approval:** run `safe`; confirm Approve, Modify Recommendation, Request Evidence, and Reject are the only actions shown.
6. **Blocked state:** run `destructive` and `production`; confirm Approve and Modify are absent and the panel explains why remediation is unavailable.
7. **Needs-more-evidence:** run `conflicting` or `missing_evidence`; confirm Add Context, Request Evidence, and Reject are shown while Approve and Modify are absent.
8. **Technical Audit:** switch views, confirm all sections start collapsed, and verify opening one accordion closes the previously open accordion.
9. **Score formatting:** confirm confidence appears like `46%`, scores like `0.10`, monthly savings like `$70/month`, and annual savings like `$840/year`.
10. **Safe formatting:** inspect nested evidence, policy, and audit data and confirm `[object Object]` never appears.
11. **Keyboard navigation:** use Tab, Shift+Tab, Enter, and Space to operate view toggles, scenario controls, workflow details, review actions, and audit accordions; confirm focus is always visible.
12. **Page length:** after a completed run, confirm the key Simple View story fits within approximately two to four desktop viewport heights.

## Workflow Checks

- Verify the eight stage names and the Waiting, Current, Complete, Needs attention, and Blocked labels.
- Approve `safe` and confirm the final outcome shows one simulated remediation PR, `$70/month`, `$840/year`, and the Terraform diff.
- Confirm plain-language policy wording is primary while `needs_human_context` and `python_fallback` appear only as secondary technical values.
- Expand Technical Audit data and verify raw events remain in sequence and evidence metadata, retries, policy rules, human history, and runtime architecture are preserved.
- Pause, resume, skip replay, refresh, reset, and verify backend conflict messages remain readable.

## Milestone 6 Planning Checks

Run the API after changing the process environment and refresh the page between modes:

```powershell
# Deterministic only
$env:AI_ENABLED="false"

# Offline mock planner
$env:AI_ENABLED="true"
$env:AI_PROVIDER="mock"

# Real Gemini with local key only
$env:AI_ENABLED="true"
$env:AI_PROVIDER="gemini"
$env:GEMINI_API_KEY="<local environment value>"
```

- Confirm the Planning badge shows `Deterministic only`, `Mock Gemini Planner`, `Gemini-assisted`, `Gemini fallback model`, or `Deterministic fallback` based on the actual run payload.
- In mock mode, confirm the note says Mock Gemini proposed steps and that Technical Audit contains accepted proposals, validated tools, and the final deterministic status.
- In disabled or missing-key mode, confirm the note says GhostBusters continued using its deterministic planner and never claims Gemini handled the run.
- Expand AI planning decisions and verify only concise structured records are shown: model, proposed action, reason, validation, latency, and fallback status. No prompts or hidden reasoning should appear.
- Run destructive and production scenarios with AI enabled and confirm Gemini planning is skipped before normal optimization evidence calls.
- Use the objective helper to confirm AI-enabled and deterministic-only wording accurately describes the current planning mode.
