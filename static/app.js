const state = {
  run: null,
  scenarios: [],
  visibleEvents: [],
  animationTimer: null,
  paused: false,
  skipAnimation: false,
  selectedReviewAction: null,
  hunt: null,
  reviews: [],
};

const stageDefinitions = [
  { id: "goal", title: "Goal received", description: "Business objective recorded.", matches: ["run_created", "goal_received"] },
  { id: "terraform", title: "Terraform understood", description: "Proposed change parsed.", matches: ["terraform_parsed"] },
  { id: "plan", title: "Investigation planned", description: "Evidence sources selected.", matches: ["investigation_plan_created", "tool_selected"] },
  { id: "evidence", title: "Evidence collected", description: "Cost, usage and context checked.", prefix: ["tool_", "external_call_", "alternative_evidence_"] },
  { id: "risk", title: "Risks checked", description: "Conflicts and safety verified.", matches: ["conflicts_detected", "verifier_completed", "failure_handled_safely"] },
  { id: "alternatives", title: "Options compared", description: "Safe alternatives compared.", matches: ["alternatives_generated", "recommendation_produced"] },
  { id: "policy", title: "Policy evaluated", description: "Rules allowed or blocked review.", prefix: ["policy_"] },
  { id: "human", title: "Human review / execution", description: "A person authorizes the PR.", matches: ["human_review_received", "additional_evidence_requested", "human_context_added", "workflow_resumed", "preferred_action_modified", "mock_pr_created"] },
];

const toolNames = ["pricing", "utilization", "jira", "git_activity", "dependencies"];
const $ = (id) => document.getElementById(id);
const uiVersion = "judge-v3";
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
  "planning-badge",
  "objective-helper",
  "planning-note",
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

function recommendationLabel(action) {
  return {
    request_evidence: "Request more evidence",
    downsize: "Downsize the instance",
    schedule: "Schedule the workload",
    keep: "Keep the current configuration",
    abstain: "Do not recommend a change",
    blocked: "Do not proceed",
  }[action] || labelFor(action);
}

function policyStatusLabel(status) {
  return {
    needs_human_context: "More human information is required",
    passed: "Allowed with safety conditions",
    blocked: "Blocked by safety policy",
  }[status] || labelFor(status);
}

function policyEngineLabel(engine) {
  return {
    python_fallback: "Deterministic Python fallback",
    python: "Deterministic Python policy",
    conftest: "Conftest policy engine",
  }[engine] || "Not recorded";
}

function planningModeLabel(mode) {
  return {
    gemini_primary: "Gemini-assisted",
    gemini_fallback_model: "Gemini fallback model",
    mock_gemini: "Mock Gemini Planner",
    deterministic_fallback: "Deterministic fallback",
    deterministic_only: "Deterministic only",
  }[mode] || "Not recorded";
}

function runStatusLabel(status) {
  return {
    pending_human_review: "Pending review",
    needs_more_evidence: "Needs evidence",
    pr_created: "PR created",
    failed_safely: "Failed safely",
  }[status] || labelFor(status || "none");
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
    $("api-pill").textContent = `API: ${health.status === "ok" ? "Online" : labelFor(health.status)}`;
    state.scenarios = scenarios.scenarios || [];
    renderScenarioOptions();
    setMessage("ui-message", "API ready. Choose a prepared scenario.", true);
  } catch (error) {
    $("api-pill").textContent = "API: Unavailable";
    setMessage("ui-message", error.message);
  }
  loadReviewQueue();
  renderAll();
}

async function loadReviewQueue() {
  try {
    state.reviews = await api("/api/reviews");
    renderReviewQueue();
  } catch (error) {
    setMessage("cloud-hunt-message", error.message);
  }
}

async function startCloudHunt() {
  try {
    setMessage("cloud-hunt-message", "Scanning fixture inventory...", true);
    state.hunt = await api("/api/cloud/hunts", { method: "POST", body: JSON.stringify({ provider_scope: $("cloud-provider-scope").value, inventory_source: "fixtures" }) });
    await loadReviewQueue();
    renderCloudHunt();
    setMessage("cloud-hunt-message", "Cloud Hunt completed. No cloud resource was changed.", true);
  } catch (error) {
    setMessage("cloud-hunt-message", error.message);
  }
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
    const stageStatusLabel = { pending: "Waiting", active: "Current", complete: "Complete", warning: "Needs attention", blocked: "Blocked" }[stageState];
    append(item, el("span", "stage-number", index + 1), el("strong", null, stage.title), el("p", null, stage.description), el("span", "stage-status", stageStatusLabel));
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
  return finalOutcome(state.run);
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
  $("recommendation-title").textContent = decision ? recommendationLabel(decision.preferred_action) : "Waiting for investigation";
  $("recommendation-reason").textContent = decision ? recommendationReason(decision, preferred) : "The recommendation will appear here after evidence and safety checks complete.";
  $("recommendation-confidence").textContent = percentage(decision?.confidence?.final_confidence);
  $("recommendation-risk").textContent = decision ? riskLevel(decision, preferred) : "--";
  $("recommendation-policy").textContent = decision ? policyStatusLabel(decision.policy_result?.status) : "--";
  $("recommendation-policy-technical").textContent = decision ? `Status: ${decision.policy_result?.status} | Engine ID: ${decision.policy_result?.engine}` : "";
  $("recommendation-savings").textContent = preferred ? `${money(preferred.estimated_monthly_savings)}/month` : "--";
  $("recommendation-next").textContent = nextHumanAction(state.run);
  const alternativesNode = $("important-alternatives");
  clear(alternativesNode);
  const alternatives = (decision?.alternatives || []).filter((item) => item.action !== decision.preferred_action).slice(0, 2);
  alternatives.forEach((item) => {
    const note = el("div", "alternative-note");
    const reason = item.eligible
      ? item.description
      : item.rejection_reasons?.[0] || item.risks?.[0] || "Not eligible under current evidence.";
    append(note, el("strong", null, `${recommendationLabel(item.action)} - ${item.eligible ? "eligible" : "rejected"}`), el("span", null, reason));
    alternativesNode.appendChild(note);
  });
}

function renderPlanningStatus() {
  const mode = state.run?.decision_record?.planning_mode || "deterministic_only";
  $("planning-badge").textContent = `Planning: ${planningModeLabel(mode)}`;
  if (mode === "gemini_primary" || mode === "gemini_fallback_model") {
    $("objective-helper").textContent = "This objective is interpreted by Gemini to help plan the investigation. Every proposed action is validated by deterministic safety rules.";
    $("planning-note").textContent = "Gemini proposed investigation steps. GhostBusters validated each action before execution.";
  } else if (mode === "mock_gemini") {
    $("objective-helper").textContent = "This objective is interpreted by the local mock planner for demonstration. Every proposed action is validated by deterministic safety rules.";
    $("planning-note").textContent = "Mock Gemini proposed investigation steps. GhostBusters validated each action before execution.";
  } else if (mode === "deterministic_fallback") {
    $("objective-helper").textContent = "This objective is recorded as business context. The deterministic planner uses explicit FinOps and safety rules.";
    $("planning-note").textContent = "Gemini was unavailable or disabled. GhostBusters continued using its deterministic planner.";
  } else {
    $("objective-helper").textContent = "This objective is recorded as business context. The deterministic planner uses explicit FinOps and safety rules.";
    $("planning-note").textContent = "Deterministic planning is active; no AI provider handled this run.";
  }
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
  const human = humanDecision(state.run);
  $("human-decision").textContent = human.label;
  $("human-decision-technical").textContent = human.technical;
  document.querySelectorAll("[data-review-action]").forEach((button) => {
    const visible = allowed.includes(button.dataset.reviewAction);
    button.hidden = !visible;
    button.disabled = !visible;
  });
  const humanQuestion = state.run?.decision_record?.human_question;
  $("review-guidance").textContent = humanQuestion
    ? `Agent question: ${humanQuestion}`
    : !state.run
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

function humanDecision(run) {
  const latest = run?.human_reviews?.[run.human_reviews.length - 1];
  if (!latest) {
    return {
      label: run?.status === "pending_human_review" ? "Awaiting a reviewer" : "Not made",
      technical: "No review recorded",
    };
  }
  const reviewer = latest.reviewer || "reviewer";
  const labels = {
    approve: `Approved by ${reviewer}`,
    reject: `Rejected by ${reviewer}`,
    request_evidence: `More evidence requested by ${reviewer}`,
    add_context: `Context added by ${reviewer}`,
    modify: `Recommendation modified by ${reviewer}`,
  };
  return { label: labels[latest.action] || labelFor(latest.action), technical: `Review action: ${latest.action}` };
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

function finalOutcome(run) {
  return {
    pr_created: "Remediation PR created",
    rejected: "Workflow closed. No PR created.",
    needs_more_evidence: "Workflow paused for more evidence.",
    blocked: "Workflow blocked. No PR can be created.",
    failed_safely: "Workflow stopped safely. No PR created.",
    pending_human_review: "Awaiting human authorization. No PR created yet.",
    abstained: "Workflow ended without a remediation recommendation.",
    keep: "Current infrastructure retained. No PR created.",
  }[run?.status] || "Waiting for human input";
}

function renderResult() {
  const node = $("result-view");
  clear(node);
  $("result-title").textContent = finalOutcome(state.run);
  const pr = state.run?.mock_pr;
  if (!pr) {
    node.appendChild(el("p", "muted", state.run ? "No PR has been created." : "Start an investigation to see the final workflow outcome."));
    return;
  }
  const layout = el("div", "result-grid");
  const summary = el("div", "pr-summary");
  [["PR", `#${pr.pr_number}`], ["Action", recommendationLabel(pr.chosen_action)], ["Branch", pr.branch], ["Savings", `${money(pr.monthly_savings)}/month | ${money(pr.annual_savings)}/year`], ["From", pr.current_instance_type], ["To", pr.proposed_instance_type]].forEach(([label, value]) => {
    const item = el("div"); append(item, el("span", null, label), el("strong", null, value)); summary.appendChild(item);
  });
  const diff = el("pre"); diff.textContent = pr.terraform_patch_preview || "Not recorded";
  append(layout, summary, diff); node.appendChild(layout);
}

function renderStatus() {
  const run = state.run;
  $("run-pill").textContent = `Run: ${runStatusLabel(run?.status)}`;
  $("policy-pill").textContent = `Policy: ${policyEngineLabel(run?.decision_record?.policy_result?.engine)}`;
  $("approval-pill").textContent = `Human: ${humanDecision(run).label}`;
  $("technical-run-id").textContent = `Run ID: ${run?.id || "not recorded"}`;
  $("trigger-source").textContent = "Trigger source not recorded";
}

function renderAudit() {
  const node = $("audit-view"); clear(node);
  const events = state.run?.audit_events || [];
  $("audit-count").textContent = `${events.length} events`;
  if (!events.length) return node.appendChild(el("p", "muted", "No audit events yet."));
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
  if (!plan) return node.appendChild(el("p", "muted", "No investigation plan yet."));
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
  if (!evidence.length) return node.appendChild(el("p", "muted", "No evidence collected yet."));
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
  if (!conflicts.length) conflictNode.appendChild(el("p", "muted", "No conflicts detected."));
  conflicts.forEach((item) => conflictNode.appendChild(append(el("article", `info-card ${statusClass(item.severity)}`), dataList([["Claim", item.claim], ["Sources", item.sources], ["Values", item.values], ["Severity", item.severity], ["Explanation", item.explanation]]))));
  if (!missing.length) missingNode.appendChild(el("p", "muted", "No missing evidence."));
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
  if (!calls.length) node.appendChild(el("p", "muted", "No retry was needed."));
  incidents.forEach((item) => node.appendChild(append(el("article", `info-card ${statusClass(item.status)}`), el("h3", null, labelFor(item.tool_name)), dataList([["Attempts", item.external_call.attempts], ["Succeeded", item.external_call.success], ["Retries exhausted", item.external_call.retry_exhausted], ["Failure", item.external_call.failure_category], ["Safe message", item.external_call.safe_message]]), rawDetails("Retry events", item.external_call.events))));
}

function renderHistory() {
  const node = $("history-view"); clear(node);
  const reviews = state.run?.human_reviews || [];
  reviews.forEach((item) => node.appendChild(append(el("article", "info-card"), dataList([["Reviewer", item.reviewer], ["Action", item.action], ["Comment", item.comment], ["Requested sources", item.requested_sources], ["Modified action", item.modified_action], ["Human context", item.human_context], ["Created", item.created_at]]))));
  if (!reviews.length) node.appendChild(el("p", "muted", "No human intervention recorded."));
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
  renderAudit(); renderAIDecisions(); renderPlan(); renderTools(); renderTerraform(); renderEvidence(); renderConflicts(); renderAlternatives(); renderVerifier(); renderPolicy(); renderResilience(); renderHistory(); renderImpact(); renderRuntime();
}

function renderAIDecisions() {
  const node = $("ai-decisions-view"); clear(node);
  const decisions = state.run?.decision_record?.ai_decisions || [];
  if (!decisions.length) return node.appendChild(el("p", "muted", "No AI planning decisions recorded."));
  decisions.forEach((item) => {
    const action = item.proposed_action;
    const card = el("article", `info-card ${item.accepted ? "status-completed" : "status-failed"}`);
    append(card, el("h3", null, `${labelFor(item.purpose)} - ${item.accepted ? "accepted" : "rejected"}`), dataList([
      ["Model", item.model], ["Planning mode", planningModeLabel(item.planning_mode)], ["Action", action?.action], ["Tool", action?.tool_name], ["Reason", action?.reason], ["Question", action?.question_being_answered], ["Expected information", action?.expected_information], ["Validation", item.validation_result], ["Latency", item.latency_ms === null ? null : `${item.latency_ms} ms`], ["Fallback reason", item.fallback_reason], ["Error category", item.error_category],
    ]), rawDetails("Usage metadata", item.usage_metadata || {}));
    node.appendChild(card);
  });
}

function renderAll() {
  renderStatus(); renderPlanningStatus(); renderStages(); renderRecommendation(); renderEvidenceSummary(); renderHumanControls(); renderResult(); renderTechnical();
  renderCloudHunt(); renderReviewQueue();
}

function switchMode(mode) {
  ["simple", "cloud-hunt", "review-queue", "technical"].forEach((item) => {
    const view = item === "simple" ? "simple-view" : `${item}-view`;
    const button = item === "simple" ? "simple-view-button" : `${item}-view-button`;
    $(view).hidden = item !== mode;
    $(button).classList.toggle("active", item === mode);
    $(button).setAttribute("aria-pressed", String(item === mode));
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function switchView(technical) { switchMode(technical ? "technical" : "simple"); }

function renderCloudHunt() {
  const summary = $("cloud-hunt-summary");
  if (!summary) return;
  clear(summary);
  const data = state.hunt?.summary;
  if (!data) return;
  [["Resources scanned", data.total_resources], ["Candidates", data.candidates], ["Protected", data.protected_candidates], ["Human context", data.needs_human_context], ["Monthly waste", money(data.estimated_monthly_waste)], ["Annual waste", money(data.estimated_annual_waste)]].forEach(([label, value]) => {
    const card = el("article", "panel hunt-metric");
    append(card, el("span", null, label), el("strong", null, value));
    summary.appendChild(card);
  });
  $("candidate-count").textContent = `${data.candidates} candidate${data.candidates === 1 ? "" : "s"}`;
  const list = $("candidate-list"); clear(list);
  (state.hunt.candidates || []).forEach((candidate) => {
    const resource = candidate.resource;
    const card = el("article", "candidate-card");
    const supporting = candidate.signals.filter((signal) => signal.supports_ghost_hypothesis).slice(0, 5).map((signal) => signal.description);
    const protective = candidate.signals.filter((signal) => !signal.supports_ghost_hypothesis).map((signal) => signal.description);
    append(card, el("p", "kicker", `${labelFor(resource.provider)} | ${labelFor(resource.normalized_resource_type)}`), el("h3", null, resource.resource_name), dataList([["Environment", resource.environment], ["Monthly cost", money(resource.estimated_monthly_cost)], ["Candidate confidence", percentage(candidate.candidate_score)], ["Review state", candidate.exclusion_reason || "Investigation created"]]), el("strong", "candidate-heading", "Why it was flagged"));
    supporting.forEach((item) => card.appendChild(el("p", "candidate-signal", item)));
    if (protective.length) { card.appendChild(el("strong", "candidate-heading", "Protection")); protective.forEach((item) => card.appendChild(el("p", "candidate-protection", item))); }
    list.appendChild(card);
  });
  if (!state.hunt.candidates.length) list.appendChild(el("p", "muted", "No suspicious candidates met the configured threshold."));
}

async function actOnCloudCase(id, action) {
  try {
    await api(`/api/reviews/${id}/action`, { method: "POST", body: JSON.stringify({ action, reviewer: "demo-reviewer", comment: action === "reject" ? "Demo review decision" : null }) });
    await loadReviewQueue();
  } catch (error) { setMessage("cloud-hunt-message", error.message); }
}

function renderReviewQueue() {
  const node = $("review-queue-list");
  if (!node) return;
  clear(node);
  if (!state.reviews.length) return node.appendChild(el("p", "muted", "No review cases loaded."));
  state.reviews.forEach((item) => {
    const card = el("article", "queue-card");
    append(card, el("p", "kicker", `${labelFor(item.source_type)}${item.provider ? ` | ${labelFor(item.provider)}` : ""}`), el("h3", null, item.resource_name), dataList([["Recommendation", item.recommendation], ["Confidence", percentage(item.confidence)], ["Savings", money(item.estimated_monthly_savings) + "/month"], ["Risk", item.risk_level], ["Required reviewer", labelFor(item.required_reviewer_role)], ["State", labelFor(item.status)]]), el("p", "queue-reason", item.recommendation_reason));
    if (item.source_type === "cloud_hunt" && ["pending", "needs_more_evidence"].includes(item.status)) {
      const actions = el("div", "queue-actions");
      if (item.status === "pending") { const approve = el("button", null, "Approve simulated PR"); approve.addEventListener("click", () => actOnCloudCase(item.id, "approve")); actions.appendChild(approve); }
      const reject = el("button", "danger", "Reject"); reject.addEventListener("click", () => actOnCloudCase(item.id, "reject")); actions.appendChild(reject);
      card.appendChild(actions);
    } else if (item.source_type === "terraform_pr") {
      const open = el("button", "secondary", "Open investigation"); open.addEventListener("click", async () => { state.run = await api(`/api/runs/${item.id}`); startAnimation(true); switchMode("simple"); }); card.appendChild(open);
    }
    node.appendChild(card);
  });
}

function bindEvents() {
  $("start-button").addEventListener("click", startRun);
  $("refresh-button").addEventListener("click", refreshRun);
  $("reset-button").addEventListener("click", resetDemo);
  $("pause-button").addEventListener("click", () => { state.paused = !state.paused; $("pause-button").textContent = state.paused ? "Resume" : "Pause"; });
  $("skip-animation").addEventListener("change", (event) => { state.skipAnimation = event.target.checked; if (state.run && state.skipAnimation) startAnimation(true); });
  $("simple-view-button").addEventListener("click", () => switchView(false));
  $("cloud-hunt-view-button").addEventListener("click", () => switchMode("cloud-hunt"));
  $("review-queue-view-button").addEventListener("click", () => { switchMode("review-queue"); loadReviewQueue(); });
  $("technical-view-button").addEventListener("click", () => switchView(true));
  $("open-technical-button").addEventListener("click", () => switchView(true));
  document.querySelectorAll("[data-review-action]").forEach((button) => button.addEventListener("click", () => selectReviewAction(button.dataset.reviewAction)));
  $("submit-review-button").addEventListener("click", submitSelectedReview);
  $("cancel-review-button").addEventListener("click", closeReviewForm);
  $("start-cloud-hunt-button").addEventListener("click", startCloudHunt);
  $("refresh-review-queue-button").addEventListener("click", loadReviewQueue);
  document.querySelectorAll(".audit-section").forEach((section) => {
    section.addEventListener("toggle", () => {
      if (!section.open) return;
      document.querySelectorAll(".audit-section").forEach((other) => {
        if (other !== section) other.open = false;
      });
    });
  });
}

if (ensureCompatibleDom()) {
  bindEvents();
  loadInitial();
}
