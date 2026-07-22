const state = {
  run: null,
  scenarios: [],
  visibleEvents: [],
  animationTimer: null,
  paused: false,
  skipAnimation: false,
  selectedReviewAction: null,
};

const stageDefinitions = [
  { id: "goal", title: "Goal received", description: "The business objective is recorded.", matches: ["run_created", "goal_received"] },
  { id: "terraform", title: "Terraform understood", description: "The proposed infrastructure change is parsed.", matches: ["terraform_parsed"] },
  { id: "plan", title: "Investigation planned", description: "Relevant evidence sources are selected.", matches: ["investigation_plan_created", "tool_selected"] },
  { id: "evidence", title: "Evidence collected", description: "Cost, usage and context signals are checked.", prefix: ["tool_", "external_call_", "alternative_evidence_"] },
  { id: "risk", title: "Risks checked", description: "Conflicts, gaps and safety findings are verified.", matches: ["conflicts_detected", "verifier_completed", "failure_handled_safely"] },
  { id: "alternatives", title: "Options compared", description: "Eligible alternatives are compared and ranked.", matches: ["alternatives_generated", "recommendation_produced"] },
  { id: "policy", title: "Policy evaluated", description: "Deterministic safety rules allow or block review.", prefix: ["policy_"] },
  { id: "human", title: "Human review / execution", description: "A person decides whether a remediation PR may be created.", matches: ["human_review_received", "additional_evidence_requested", "human_context_added", "workflow_resumed", "preferred_action_modified", "mock_pr_created"] },
];

const toolNames = ["pricing", "utilization", "jira", "git_activity", "dependencies"];
const $ = (id) => document.getElementById(id);
const uiVersion = "judge-v2";
const requiredElementIds = [
  "api-pill",
  "simple-view",
  "technical-view",
  "stage-list",
  "recommendation-title",
  "important-alternatives",
  "evidence-summary-view",
  "resilience-summary",
  "review-form",
  "result-view",
];

function ensureCompatibleDom() {
  const missing = requiredElementIds.filter((id) => !$(id));
  if (!missing.length) return true;
  const reloadKey = `ghostbusters:ui-reload:${uiVersion}`;
  if (!sessionStorage.getItem(reloadKey)) {
    sessionStorage.setItem(reloadKey, "attempted");
    const url = new URL(window.location.href);
    url.searchParams.set("ui", uiVersion);
    window.location.replace(url.toString());
    return false;
  }
  console.error(`GhostBusters UI could not start because these elements are missing: ${missing.join(", ")}`);
  return false;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function safeObject(value, seen = new WeakSet()) {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map((item) => safeObject(item, seen));
  if (typeof value !== "object") return value;
  if (seen.has(value)) return "[Circular]";
  seen.add(value);
  const output = {};
  Object.entries(value).forEach(([key, item]) => { output[key] = safeObject(item, seen); });
  seen.delete(value);
  return output;
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join(", ") : "None";
  if (typeof value === "object") return JSON.stringify(safeObject(value));
  return String(value);
}

function prettyValue(value) {
  if (value === null || value === undefined) return "Not recorded";
  if (typeof value === "object") return JSON.stringify(safeObject(value), null, 2);
  return formatValue(value);
}

function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = formatValue(content);
  return node;
}

function append(parent, ...children) {
  children.filter(Boolean).forEach((child) => parent.appendChild(child));
  return parent;
}

function dataList(entries) {
  const list = el("dl", "data-list");
  entries.forEach(([label, value]) => {
    const row = el("div");
    append(row, el("dt", null, label), el("dd", null, value));
    list.appendChild(row);
  });
  return list;
}

function rawDetails(label, value) {
  const details = el("details", "raw-details");
  const pre = el("pre");
  pre.textContent = prettyValue(value);
  append(details, el("summary", null, label), pre);
  return details;
}

function labelFor(value) {
  return String(value || "Not recorded").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusClass(value) {
  return `status-${String(value || "unknown").replaceAll(" ", "_").toLowerCase()}`;
}

function money(value) {
  if (value === null || value === undefined) return "Not recorded";
  return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function percentage(value) {
  if (value === null || value === undefined) return "Not recorded";
  return `${Math.round(Number(value) * 100)}%`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || `${response.status} ${response.statusText}`;
    throw new Error(typeof detail === "string" ? detail : prettyValue(detail));
  }
  return payload;
}

function setMessage(id, message, success = false) {
  const node = $(id);
  node.textContent = message || "";
  node.style.color = success ? "var(--green)" : "var(--red)";
}

async function loadInitial() {
  try {
    const [health, scenarios] = await Promise.all([api("/health"), api("/api/scenarios")]);
    $("api-pill").textContent = `API: ${health.status}`;
    state.scenarios = scenarios.scenarios || [];
    renderScenarioOptions();
    setMessage("ui-message", "API ready. Choose a prepared scenario.", true);
  } catch (error) {
    $("api-pill").textContent = "API: unavailable";
    setMessage("ui-message", error.message);
  }
  renderAll();
}

function renderScenarioOptions() {
  const select = $("scenario-select");
  clear(select);
  state.scenarios.forEach((scenario) => {
    const option = el("option", null, scenario);
    option.value = scenario;
    select.appendChild(option);
  });
}

async function startRun() {
  try {
    setMessage("ui-message", "Starting investigation...", true);
    const run = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify({
        goal: $("goal-input").value,
        scenario_name: $("scenario-select").value,
        idempotency_key: `ui-${Date.now()}`,
      }),
    });
    state.run = run;
    localStorage.setItem("ghostbusters:lastRunId", run.id);
    state.skipAnimation = $("skip-animation").checked;
    startAnimation();
    setMessage("ui-message", "Investigation complete. Replaying the recorded audit stages.", true);
  } catch (error) {
    setMessage("ui-message", error.message);
  }
}

async function refreshRun() {
  const runId = state.run?.id || localStorage.getItem("ghostbusters:lastRunId");
  if (!runId) return setMessage("ui-message", "No run is available to refresh.");
  try {
    state.run = await api(`/api/runs/${runId}`);
    startAnimation(true);
    setMessage("ui-message", "Current run refreshed.", true);
  } catch (error) {
    setMessage("ui-message", error.message);
  }
}

async function resetDemo() {
  try {
    await api("/api/reset", { method: "POST", body: "{}" });
    window.clearInterval(state.animationTimer);
    state.run = null;
    state.visibleEvents = [];
    localStorage.removeItem("ghostbusters:lastRunId");
    closeReviewForm();
    renderAll();
    setMessage("ui-message", "Demo reset.", true);
  } catch (error) {
    setMessage("ui-message", error.message);
  }
}

function startAnimation(showAll = false) {
  window.clearInterval(state.animationTimer);
  const events = state.run?.audit_events || [];
  state.visibleEvents = state.skipAnimation || showAll ? [...events] : [];
  renderAll();
  if (state.visibleEvents.length === events.length) return;
  state.animationTimer = window.setInterval(() => {
    if (state.paused) return;
    const next = events[state.visibleEvents.length];
    if (!next) {
      window.clearInterval(state.animationTimer);
      renderAll();
      return;
    }
    state.visibleEvents.push(next);
    renderAll();
  }, 420);
}

function stageForEvent(event) {
  return stageDefinitions.find((stage) =>
    stage.matches?.includes(event.event_type) || stage.prefix?.some((prefix) => event.event_type.startsWith(prefix))
  );
}

function renderStages() {
  const list = $("stage-list");
  clear(list);
  const visible = state.visibleEvents;
  const allEvents = state.run?.audit_events || [];
  let lastCompleted = -1;
  stageDefinitions.forEach((stage, index) => {
    if (visible.some((event) => stageForEvent(event)?.id === stage.id)) lastCompleted = index;
  });
  stageDefinitions.forEach((stage, index) => {
    const events = visible.filter((event) => stageForEvent(event)?.id === stage.id);
    const allStageEvents = allEvents.filter((event) => stageForEvent(event)?.id === stage.id);
    let stageState = "pending";
    if (events.length && events.length === allStageEvents.length) stageState = "complete";
    if (index === lastCompleted && visible.length < allEvents.length) stageState = "active";
    if (stage.id === "human" && state.run?.status === "blocked") stageState = "blocked";
    if (stage.id === "human" && ["needs_more_evidence", "abstained"].includes(state.run?.status)) stageState = "warning";
    const item = el("li", `stage ${stageState}`);
    append(item, el("span", "stage-number", index + 1), el("strong", null, stage.title), el("p", null, stage.description), el("span", "stage-status", stageState));
    if (events.length) {
      const details = el("details");
      const eventList = el("ol", "stage-events");
      events.forEach((event) => eventList.appendChild(el("li", null, event.summary)));
      append(details, el("summary", null, `${events.length} recorded event${events.length === 1 ? "" : "s"}`), eventList);
      item.appendChild(details);
    }
    list.appendChild(item);
  });
  renderCurrentAction(visible[visible.length - 1]);
}

function renderCurrentAction(event) {
  if (!event) {
    $("current-action").textContent = "No run started";
    $("current-reason").textContent = "Start an investigation to see the recorded workflow.";
    $("current-output").textContent = "Waiting";
    $("current-next").textContent = "Choose a prepared scenario";
    return;
  }
  const stage = stageForEvent(event);
  $("current-action").textContent = event.summary || labelFor(event.event_type);
  $("current-reason").textContent = stage?.description || "This action is part of the recorded workflow.";
  $("current-output").textContent = conciseEventResult(event);
  $("current-next").textContent = nextStageText(stage?.id);
}

function conciseEventResult(event) {
  const details = event.details || {};
  if (details.status) return `Status: ${labelFor(details.status)}`;
  if (details.allowed !== undefined) return details.allowed ? "Policy allowed review." : "Policy blocked remediation.";
  if (details.failure_category) return `Failed safely: ${labelFor(details.failure_category)}`;
  return event.summary || "Recorded";
}

function nextStageText(stageId) {
  const index = stageDefinitions.findIndex((stage) => stage.id === stageId);
  if (index >= 0 && index < stageDefinitions.length - 1) return stageDefinitions[index + 1].title;
  return resultLabel(state.run?.status);
}

function evidenceItem(source) {
  return (state.run?.decision_record?.evidence || []).find((item) => item.source === source);
}

function evidenceValue(source) {
  return evidenceItem(source)?.value;
}

function preferredAlternative() {
  const decision = state.run?.decision_record;
  return (decision?.alternatives || []).find((item) => item.action === decision.preferred_action);
}

function evidenceSummary(source, item) {
  if (!item || item.freshness_status === "unavailable" || item.value === null) {
    return { title: labelFor(source), detail: "Evidence unavailable", conclusion: item?.claim || "Source did not return evidence" };
  }
  const value = item.value;
  if (source === "pricing") return { title: "Cost impact", detail: `${money(value.current_monthly_cost)} to ${money(value.proposed_monthly_cost)} monthly`, conclusion: `Potential saving: ${money(Number(value.current_monthly_cost || 0) - Number(value.proposed_monthly_cost || 0))} per month` };
  if (source === "utilization") {
    const headroom = Number(value.peak_cpu_pct) < 60;
    return { title: "Utilization", detail: `Average CPU ${formatValue(value.average_cpu_pct)}%, peak ${formatValue(value.peak_cpu_pct)}%`, conclusion: headroom ? "Rightsizing headroom exists" : "Not enough clearly safe headroom" };
  }
  if (source === "jira") return { title: "Jira", detail: `${formatValue(value.issue_key)} is ${labelFor(value.status)}`, conclusion: String(value.status).toLowerCase() === "completed" ? "Project may appear inactive" : "Project remains active or under review" };
  if (source === "git_activity") return { title: "Git activity", detail: `${formatValue(value.recent_commit_count)} recent commits; last commit ${formatValue(value.days_since_last_commit)} days ago`, conclusion: Number(value.recent_commit_count) > 0 ? "Recent work may contradict project status" : "No recent repository activity recorded" };
  if (source === "dependencies") {
    const dependencies = value.active_downstream_dependencies || value.blocking_services || [];
    return { title: "Dependencies", detail: dependencies.length ? `Active: ${formatValue(dependencies)}` : "No active downstream dependencies", conclusion: dependencies.length ? "Automatic remediation may be unsafe" : "No dependency blocker found" };
  }
  return { title: labelFor(source), detail: item.claim, conclusion: formatValue(value) };
}

function renderEvidenceSummary() {
  const node = $("evidence-summary-view");
  clear(node);
  const evidence = state.run?.decision_record?.evidence || [];
  $("evidence-count").textContent = `${evidence.length} source${evidence.length === 1 ? "" : "s"}`;
  if (!evidence.length) {
    node.appendChild(el("p", "muted", "Evidence summaries appear after investigation."));
  } else {
    evidence.filter((item) => toolNames.includes(item.source)).forEach((item) => {
      const summary = evidenceSummary(item.source, item);
      const signal = el("div", "signal");
      append(signal, el("strong", null, summary.title), el("span", null, summary.detail), el("span", null, `Conclusion: ${summary.conclusion}`));
      node.appendChild(signal);
    });
  }
  const findings = state.run?.decision_record?.verifier_findings || [];
  const passed = findings.filter((item) => item.status === "passed").length;
  const warnings = findings.filter((item) => item.status === "warning").length;
  const failed = findings.filter((item) => item.status === "failed").length;
  const checkSummary = findings.length ? `${findings.length} safety checks completed: ${passed} passed, ${warnings} warnings, ${failed} failed.` : "No safety checks recorded yet.";
  const policy = state.run?.decision_record?.policy_result;
  $("safety-summary").textContent = policy ? `${checkSummary} ${policySummary(policy)}` : checkSummary;
  const calls = (state.run?.decision_record?.tool_executions || []).filter((item) => item.external_call);
  const incidents = calls.filter((item) => !item.external_call.success || item.external_call.attempts > 1);
  $("resilience-summary").textContent = !calls.length
    ? "No external evidence calls recorded yet."
    : incidents.length
      ? `${incidents.length} evidence call${incidents.length === 1 ? " required" : "s required"} retry or safe fallback handling.`
      : "All external evidence calls succeeded on the first attempt.";
}

function recommendationReason(decision, preferred) {
  const highConflicts = (decision?.conflicts || []).filter((item) => item.severity === "high");
  if (highConflicts.length) return `${highConflicts.length} high-risk conflict${highConflicts.length === 1 ? " remains" : "s remain"}: ${highConflicts.map((item) => item.explanation).join(" ")}`;
  if (decision?.missing_evidence?.length) return `Critical evidence is incomplete: ${decision.missing_evidence.map((item) => labelFor(item.source)).join(", ")}.`;
  return preferred?.description || decision?.final_summary || "No recommendation recorded.";
}

function riskLevel(decision, preferred) {
  const severities = [...(decision?.conflicts || []).map((item) => item.severity), ...(decision?.verifier_findings || []).filter((item) => item.status !== "passed").map((item) => item.severity)];
  const order = ["info", "low", "medium", "high", "critical"];
  if (preferred?.risks?.length && !severities.length) return "Medium";
  return labelFor(severities.sort((a, b) => order.indexOf(b) - order.indexOf(a))[0] || "low");
}

function nextHumanAction(run) {
  if (!run) return "Start an investigation";
  if (run.status === "pending_human_review") return "Approve, modify, request evidence, or reject";
  if (run.status === "needs_more_evidence") return "Add business context or request updated evidence";
  if (run.status === "blocked") return "Add context where supported; approval is unavailable";
  if (run.status === "pr_created") return "Review the simulated remediation pull request";
  if (run.status === "rejected") return "Review closed by human rejection";
  return "Review the recorded outcome";
}

function renderRecommendation() {
  const decision = state.run?.decision_record;
  const preferred = preferredAlternative();
  $("recommendation-title").textContent = decision ? labelFor(decision.preferred_action) : "Waiting for investigation";
  $("recommendation-reason").textContent = decision ? recommendationReason(decision, preferred) : "The recommendation will appear here after evidence and safety checks complete.";
  $("recommendation-confidence").textContent = percentage(decision?.confidence?.final_confidence);
  $("recommendation-risk").textContent = decision ? riskLevel(decision, preferred) : "--";
  $("recommendation-policy").textContent = decision ? labelFor(decision.policy_result?.status) : "--";
  $("recommendation-savings").textContent = preferred ? `${money(preferred.estimated_monthly_savings)}/mo` : "--";
  $("recommendation-next").textContent = nextHumanAction(state.run);
  const alternativesNode = $("important-alternatives");
  clear(alternativesNode);
  const alternatives = (decision?.alternatives || []).filter((item) => item.action !== decision.preferred_action).slice(0, 2);
  alternatives.forEach((item) => {
    const note = el("div", "alternative-note");
    const reason = item.eligible
      ? item.description
      : item.rejection_reasons?.[0] || item.risks?.[0] || "Not eligible under current evidence.";
    append(note, el("strong", null, `${labelFor(item.action)} - ${item.eligible ? "eligible" : "rejected"}`), el("span", null, reason));
    alternativesNode.appendChild(note);
  });
}

function allowedReviewActions(status) {
  if (status === "pending_human_review") return ["approve", "modify", "request_evidence", "reject"];
  if (status === "needs_more_evidence") return ["add_context", "request_evidence", "reject"];
  if (status === "abstained") return ["add_context", "request_evidence"];
  if (status === "blocked" || status === "keep" || status === "failed_safely") return ["add_context"];
  return [];
}

function renderHumanControls() {
  const status = state.run?.status;
  const allowed = allowedReviewActions(status);
  document.querySelectorAll("[data-review-action]").forEach((button) => {
    const visible = allowed.includes(button.dataset.reviewAction);
    button.hidden = !visible;
    button.disabled = !visible;
  });
  $("review-guidance").textContent = !state.run
    ? "Start a run to see the actions permitted by its safety state."
    : status === "blocked"
      ? "This run is blocked. Approval and remediation controls are unavailable."
      : status === "needs_more_evidence"
        ? "The recommendation is not ready for approval. Add context or request missing evidence."
        : status === "pending_human_review"
          ? "Policy permits a human to decide whether a remediation PR should be created."
          : allowed.length ? "Human input can refine the recorded decision." : "No further review action is available in this state.";
  if (state.selectedReviewAction && !allowed.includes(state.selectedReviewAction)) closeReviewForm();
}

function selectReviewAction(action) {
  state.selectedReviewAction = action;
  $("review-form").hidden = false;
  $("review-form-title").textContent = labelFor(action);
  $("sources-field").hidden = action !== "request_evidence";
  $("context-field").hidden = action !== "add_context";
  $("modify-field").hidden = action !== "modify";
  $("submit-review-button").textContent = action === "approve" ? "Approve and create PR" : action === "reject" ? "Confirm rejection" : "Submit";
  $("review-form").scrollIntoView({ block: "nearest" });
}

function closeReviewForm() {
  state.selectedReviewAction = null;
  $("review-form").hidden = true;
}

async function submitSelectedReview() {
  const action = state.selectedReviewAction;
  if (!action || !state.run) return;
  const payload = { action, reviewer: $("reviewer-input").value || "judge", comment: $("comment-input").value || null };
  if (action === "request_evidence") payload.requested_sources = $("requested-sources").value.split(",").map((item) => item.trim()).filter(Boolean);
  if (action === "add_context") payload.human_context = $("human-context").value || null;
  if (action === "modify") payload.modified_action = $("modified-action").value || null;
  try {
    state.run = await api(`/api/runs/${state.run.id}/review`, { method: "POST", body: JSON.stringify(payload) });
    closeReviewForm();
    startAnimation(true);
    setMessage("review-message", `${labelFor(action)} accepted by the backend.`, true);
  } catch (error) {
    setMessage("review-message", error.message);
  }
}

function resultLabel(status) {
  return {
    pr_created: "Simulated remediation PR created",
    rejected: "Recommendation rejected",
    needs_more_evidence: "More evidence requested",
    blocked: "Remediation blocked",
    failed_safely: "Run failed safely",
  }[status] || "Waiting for human input";
}

function renderResult() {
  const node = $("result-view");
  clear(node);
  $("result-title").textContent = resultLabel(state.run?.status);
  const pr = state.run?.mock_pr;
  if (!pr) {
    node.appendChild(el("p", "muted", state.run?.status === "rejected" ? "The reviewer rejected this recommendation. No PR was created." : state.run?.status === "blocked" ? "Safety policy prevented approval. No PR was created." : "No simulated remediation pull request has been created."));
    return;
  }
  const layout = el("div", "result-grid");
  const summary = el("div", "pr-summary");
  [["PR", `#${pr.pr_number}`], ["Action", labelFor(pr.chosen_action)], ["Branch", pr.branch], ["Savings", `${money(pr.monthly_savings)}/mo`], ["From", pr.current_instance_type], ["To", pr.proposed_instance_type]].forEach(([label, value]) => {
    const item = el("div"); append(item, el("span", null, label), el("strong", null, value)); summary.appendChild(item);
  });
  const diff = el("pre"); diff.textContent = pr.terraform_patch_preview || "Not recorded";
  append(layout, summary, diff); node.appendChild(layout);
}

function renderStatus() {
  const run = state.run;
  $("run-pill").textContent = `Current run: ${run ? labelFor(run.status) : "none"}`;
  $("policy-pill").textContent = `Policy engine: ${run?.decision_record?.policy_result?.engine || "not recorded"}`;
  $("approval-pill").textContent = `Human approval: ${run ? labelFor(run.status) : "waiting"}`;
  $("technical-run-id").textContent = `Run ID: ${run?.id || "not recorded"}`;
  $("trigger-source").textContent = "Trigger source not recorded";
}

function renderAudit() {
  const node = $("audit-view"); clear(node);
  const events = state.run?.audit_events || [];
  $("audit-count").textContent = `${events.length} events`;
  if (!events.length) return node.appendChild(el("p", "muted", "No audit events recorded."));
  events.forEach((event) => {
    const row = el("div", "audit-row");
    const details = el("details", "raw-details");
    append(details, el("summary", null, "Inspect"), dataList([["Timestamp", event.timestamp], ["Actor", event.actor], ["Event type", event.event_type], ["Interpretation", event.summary], ["Next stage", nextStageText(stageForEvent(event)?.id)]]), rawDetails("Input and output", event.details || {}));
    append(row, el("span", "audit-sequence", event.sequence_number), el("strong", null, labelFor(event.event_type)), el("span", null, event.summary), details);
    node.appendChild(row);
  });
}

function renderPlan() {
  const node = $("plan-view"); clear(node);
  const plan = state.run?.decision_record?.investigation_plan;
  if (!plan) return node.appendChild(el("p", "muted", "Not recorded"));
  append(node, dataList([["Objective", plan.goal], ["Resource", plan.resource_id], ["Selected tools", plan.selected_tools], ["Skipped tools", plan.skipped_tools]]), rawDetails("Planning notes", plan.planning_notes));
  const grid = el("div", "technical-grid");
  (plan.questions || []).forEach((question) => {
    const card = el("article", `info-card ${statusClass(question.status)}`);
    append(card, el("h3", null, question.question), dataList([["Required sources", question.required_evidence_sources], ["Status", question.status], ["Resolution", question.resolution_summary]]));
    grid.appendChild(card);
  });
  node.appendChild(grid);
}

function renderTools() {
  const node = $("tool-panel"); clear(node);
  const plan = state.run?.decision_record?.investigation_plan || {};
  const records = state.run?.decision_record?.tool_executions || [];
  toolNames.forEach((name) => {
    const record = records.find((item) => item.tool_name === name);
    const skipped = (plan.skipped_tools || []).includes(name);
    const card = el("article", `info-card ${statusClass(record?.status || (skipped ? "skipped" : "unknown"))}`);
    append(card, el("h3", null, labelFor(name)), dataList([["Status", record?.status || (skipped ? "skipped" : "Not recorded")], ["Why selected", record?.selected_because], ["Input", record?.input_summary], ["Output", record?.output_summary], ["Error", record?.error], ["Attempts", record?.external_call?.attempts], ["Elapsed", record?.external_call ? `${record.external_call.elapsed_ms} ms` : null]]));
    if (record?.external_call) card.appendChild(rawDetails("External call record", record.external_call));
    node.appendChild(card);
  });
}

function renderTerraform() {
  const node = $("terraform-view"); clear(node);
  const decision = state.run?.decision_record;
  const pricing = evidenceValue("pricing") || {};
  const preferred = preferredAlternative() || {};
  append(node, dataList([["Resource ID", decision?.resource_id], ["Environment", "Not recorded in run response"], ["Terraform actions", "Not recorded in run response"], ["Destructive flag", "Not recorded in run response"], ["Current instance type", state.run?.mock_pr?.current_instance_type], ["Proposed instance type", preferred.proposed_instance_type], ["Current monthly cost", money(pricing.current_monthly_cost)], ["Proposed monthly cost", money(pricing.proposed_monthly_cost)]]));
  if (state.run?.mock_pr?.terraform_patch_preview) { const pre = el("pre"); pre.textContent = state.run.mock_pr.terraform_patch_preview; node.appendChild(pre); }
}

function renderEvidence() {
  const node = $("evidence-view"); clear(node);
  const evidence = state.run?.decision_record?.evidence || [];
  if (!evidence.length) return node.appendChild(el("p", "muted", "Not recorded"));
  evidence.forEach((item) => {
    const card = el("article", `info-card ${statusClass(item.freshness_status)}`);
    append(card, el("h3", null, labelFor(item.source)), dataList([["Claim", item.claim], ["Value", item.value], ["Freshness", item.freshness_status], ["Reliability", item.reliability], ["Resource ID", item.resource_id]]), rawDetails("Metadata", item.metadata || {}));
    node.appendChild(card);
  });
}

function renderConflicts() {
  const conflictNode = $("conflicts-view"); const missingNode = $("missing-view"); clear(conflictNode); clear(missingNode);
  conflictNode.appendChild(el("h3", null, "Conflicts")); missingNode.appendChild(el("h3", null, "Missing evidence"));
  const conflicts = state.run?.decision_record?.conflicts || [];
  const missing = state.run?.decision_record?.missing_evidence || [];
  if (!conflicts.length) conflictNode.appendChild(el("p", "muted", "No conflicts recorded."));
  conflicts.forEach((item) => conflictNode.appendChild(append(el("article", `info-card ${statusClass(item.severity)}`), dataList([["Claim", item.claim], ["Sources", item.sources], ["Values", item.values], ["Severity", item.severity], ["Explanation", item.explanation]]))));
  if (!missing.length) missingNode.appendChild(el("p", "muted", "No missing evidence recorded."));
  missing.forEach((item) => missingNode.appendChild(append(el("article", `info-card ${item.critical ? "status-critical" : "status-warning"}`), dataList([["Source", item.source], ["Claim needed", item.claim_needed], ["Critical", item.critical], ["Impact", item.impact]]))));
}

function renderAlternatives() {
  const node = $("alternatives-view"); clear(node);
  const decision = state.run?.decision_record;
  (decision?.alternatives || []).forEach((item) => {
    const card = el("article", `info-card ${item.action === decision.preferred_action ? "preferred" : ""}`);
    append(card, el("h3", null, `${labelFor(item.action)}${item.action === decision.preferred_action ? " - preferred" : ""}`), dataList([["Description", item.description], ["Eligible", item.eligible], ["Score", Number(item.score).toFixed(2)], ["Monthly cost", money(item.estimated_monthly_cost)], ["Monthly savings", money(item.estimated_monthly_savings)], ["Annual savings", money(item.estimated_annual_savings)], ["Supporting evidence", item.supporting_evidence], ["Risks", item.risks], ["Assumptions", item.assumptions], ["Rejection reasons", item.rejection_reasons]]));
    node.appendChild(card);
  });
  if (!decision?.alternatives?.length) node.appendChild(el("p", "muted", "Not recorded"));
}

function renderVerifier() {
  const node = $("verifier-view"); clear(node);
  const findings = state.run?.decision_record?.verifier_findings || [];
  findings.forEach((item) => node.appendChild(append(el("article", `info-card ${statusClass(item.status)}`), el("h3", null, labelFor(item.check_name)), dataList([["Status", item.status], ["Severity", item.severity], ["Explanation", item.explanation], ["Evidence sources", item.evidence_sources]]))));
  if (!findings.length) node.appendChild(el("p", "muted", "Not recorded"));
}

function policySummary(policy) {
  if (!policy) return "Not recorded";
  if (policy.fallback_reason) return `Deterministic Python fallback used safely: ${policy.fallback_reason}`;
  if (!policy.allowed) return policy.blocking_reasons?.[0] || "Policy blocked remediation.";
  return policy.requires_human_approval ? "Policy allows review only after human approval." : "Policy allowed this outcome.";
}

function renderPolicy() {
  const node = $("policy-view"); clear(node);
  const policy = state.run?.decision_record?.policy_result;
  if (!policy) return node.appendChild(el("p", "muted", "Not recorded"));
  append(node, dataList([["Result", policySummary(policy)], ["Engine", policy.engine], ["Version", policy.policy_version], ["Allowed", policy.allowed], ["Status", policy.status], ["Human approval required", policy.requires_human_approval], ["Blocking reasons", policy.blocking_reasons], ["Warnings", policy.warnings], ["Evaluated rules", policy.evaluated_rules], ["Fallback reason", policy.fallback_reason]]), rawDetails("Structured violations", policy.violations || []));
}

function renderResilience() {
  const node = $("resilience-view"); clear(node);
  const calls = (state.run?.decision_record?.tool_executions || []).filter((item) => item.external_call);
  const incidents = calls.filter((item) => !item.external_call.success || item.external_call.attempts > 1 || item.external_call.retry_exhausted);
  if (calls.length && !incidents.length) node.appendChild(el("p", "muted", "All external evidence calls succeeded on the first attempt."));
  if (!calls.length) node.appendChild(el("p", "muted", "No external evidence call details recorded."));
  incidents.forEach((item) => node.appendChild(append(el("article", `info-card ${statusClass(item.status)}`), el("h3", null, labelFor(item.tool_name)), dataList([["Attempts", item.external_call.attempts], ["Succeeded", item.external_call.success], ["Retries exhausted", item.external_call.retry_exhausted], ["Failure", item.external_call.failure_category], ["Safe message", item.external_call.safe_message]]), rawDetails("Retry events", item.external_call.events))));
}

function renderHistory() {
  const node = $("history-view"); clear(node);
  const reviews = state.run?.human_reviews || [];
  reviews.forEach((item) => node.appendChild(append(el("article", "info-card"), dataList([["Reviewer", item.reviewer], ["Action", item.action], ["Comment", item.comment], ["Requested sources", item.requested_sources], ["Modified action", item.modified_action], ["Human context", item.human_context], ["Created", item.created_at]]))));
  if (!reviews.length) node.appendChild(el("p", "muted", "No human interventions recorded."));
}

function renderImpact() {
  const node = $("impact-view"); clear(node);
  const pricing = evidenceValue("pricing") || {};
  const preferred = preferredAlternative() || {};
  node.appendChild(dataList([["Current monthly cost", money(pricing.current_monthly_cost)], ["Proposed monthly cost", money(pricing.proposed_monthly_cost || preferred.estimated_monthly_cost)], ["Monthly savings", money(preferred.estimated_monthly_savings)], ["Annual savings", money(preferred.estimated_annual_savings)], ["Confidence", percentage(state.run?.decision_record?.confidence?.final_confidence)], ["Risk", preferred.risks], ["Run status", state.run?.status]]));
}

function renderRuntime() {
  const node = $("runtime-view"); clear(node);
  node.appendChild(dataList([["Run ID", state.run?.id], ["Version", state.run?.version], ["Scenario fixture", state.run?.scenario_name], ["Trigger source", "Not recorded in run response"], ["Idempotency key", state.run?.idempotency_key], ["Storage backend", "Not recorded in run response"], ["Webhook dedup backend", "Not recorded in run response"], ["Policy engine", state.run?.decision_record?.policy_result?.engine], ["Retry configuration", "Not recorded in run response"]]));
}

function renderTechnical() {
  renderAudit(); renderPlan(); renderTools(); renderTerraform(); renderEvidence(); renderConflicts(); renderAlternatives(); renderVerifier(); renderPolicy(); renderResilience(); renderHistory(); renderImpact(); renderRuntime();
}

function renderAll() {
  renderStatus(); renderStages(); renderRecommendation(); renderEvidenceSummary(); renderHumanControls(); renderResult(); renderTechnical();
}

function switchView(technical) {
  $("simple-view").hidden = technical;
  $("technical-view").hidden = !technical;
  $("simple-view-button").classList.toggle("active", !technical);
  $("technical-view-button").classList.toggle("active", technical);
  $("simple-view-button").setAttribute("aria-pressed", String(!technical));
  $("technical-view-button").setAttribute("aria-pressed", String(technical));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function bindEvents() {
  $("start-button").addEventListener("click", startRun);
  $("refresh-button").addEventListener("click", refreshRun);
  $("reset-button").addEventListener("click", resetDemo);
  $("pause-button").addEventListener("click", () => { state.paused = !state.paused; $("pause-button").textContent = state.paused ? "Resume" : "Pause"; });
  $("skip-animation").addEventListener("change", (event) => { state.skipAnimation = event.target.checked; if (state.run && state.skipAnimation) startAnimation(true); });
  $("simple-view-button").addEventListener("click", () => switchView(false));
  $("technical-view-button").addEventListener("click", () => switchView(true));
  $("open-technical-button").addEventListener("click", () => switchView(true));
  document.querySelectorAll("[data-review-action]").forEach((button) => button.addEventListener("click", () => selectReviewAction(button.dataset.reviewAction)));
  $("submit-review-button").addEventListener("click", submitSelectedReview);
  $("cancel-review-button").addEventListener("click", closeReviewForm);
}

if (ensureCompatibleDom()) {
  bindEvents();
  loadInitial();
}
