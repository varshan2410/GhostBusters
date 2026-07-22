# Manual Frontend Tests

Run the API, then open `http://127.0.0.1:8000/`.

```powershell
docker compose up -d
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Judge View Checklist

1. **Simple View safe scenario:** confirm Simple View is selected by default, run `safe`, and verify the full story is understandable from grouped stages, recommendation, evidence, human decision, and result.
2. **Simple View conflicting scenario:** run `conflicting`; confirm the recommendation asks for evidence or context, high-risk conflicts are summarized, and approval is unavailable.
3. **Simple View blocked scenario:** run `destructive`, then `production`; confirm each shows a blocked result and never offers approval.
4. **Technical Audit toggle:** switch between Simple View and Technical Audit; confirm the simple content is replaced, not placed beside or underneath it.
5. **Grouped audit stages:** replay a run and confirm all raw events remain in sequence inside the eight grouped stages and the complete technical audit trail.
6. **Evidence summaries:** confirm utilization, Jira, Git activity, dependencies, and pricing use plain-language values and conclusions.
7. **Human actions by state:** verify `pending_human_review` offers Approve, Modify, Request Evidence, and Reject; `needs_more_evidence` offers Add Context, Request Evidence, and Reject; blocked runs never offer approval.
8. **Safe object rendering:** expand evidence and audit details and confirm no value appears as `[object Object]`.
9. **Scores and percentages:** confirm confidence uses a whole percentage and technical alternative scores use two decimals such as `0.10`.
10. **1366x768 projector test:** confirm there is no horizontal overflow, the eight stages are readable, and the human controls do not float over other content.
11. **Webhook versus demo explanation:** confirm the start panel says demo runs use prepared PR fixtures and production starts from supported GitHub pull-request webhook actions, not every Git push.
12. **Objective accuracy:** confirm the objective is described as an input to explicit deterministic FinOps and safety rules, not a chatbot or unrestricted planner.

## Action Checks

- Approve a `safe` run and verify one simulated remediation PR and Terraform diff appear.
- Submit duplicate approval and confirm the UI displays the backend conflict or unchanged PR without creating another PR.
- Request missing evidence, add context, modify an eligible recommendation, and reject a reviewable run.
- Pause, resume, skip replay, refresh the current run, and reset the demo.
- Open every Technical Audit section and verify plan questions, tools, raw evidence, conflicts, alternatives, verifier findings, policy, resilience, human history, business impact, and runtime fields remain available.
