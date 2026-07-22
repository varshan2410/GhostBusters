# Manual Frontend Tests

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
