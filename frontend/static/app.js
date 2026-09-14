const state = {
  user: null,
  catalog: null,
  dashboard: null,
  configuration: null,
  appointments: [],
  reservedBlocks: [],
  calendarLoaded: false,
  waitlistEntries: [],
  auditEvents: [],
  recommendations: [],
  route: "home",
  settingsSection: "people",
  scheduleStep: 1,
  maxScheduleStep: 1,
  intakeConfirmationRequired: false,
  pendingCandidate: null,
  rescheduleAppointmentId: null,
  statusAppointmentId: null,
  selectedRescheduleRecommendation: null,
  vacancyRecoverySourceAppointmentId: null,
  vacancyRecoveryChain: null,
  vacancyRecoveryCandidates: [],
  selectedVacancyOffer: null,
  contactWaitlistId: null,
  calibrationProcedureCode: null,
  releaseReservedBlockId: null,
  doctorStatusTarget: null,
  providerStatusTarget: null,
  providerDeletionTarget: null,
  userStatusTarget: null,
  calendarMode: "month",
  calendarMonthOffset: 0,
  simulationFile: null,
  simulationPreview: null,
  simulationRun: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const VIEW_META = {
  home: { title: "Home", subtitle: "Your next actions and practice status.", roles: ["administrator", "scheduler", "clinician", "auditor"] },
  operations: { title: "Today", subtitle: "Run the patient day in the order events actually happen.", roles: ["administrator", "scheduler", "clinician"] },
  scheduler: { title: "Schedule patient", subtitle: "Find a feasible doctor, room, and time in three clear steps.", roles: ["administrator", "scheduler", "clinician"] },
  waitlist: { title: "ASAP waitlist", subtitle: "Work earlier-opening requests without disturbing locked visits.", roles: ["administrator", "scheduler", "clinician"] },
  calendar: { title: "Calendar", subtitle: "Review future appointments across the rolling one-year horizon.", roles: ["administrator", "scheduler", "clinician"] },
  analytics: { title: "Reports", subtitle: "Review descriptive local operational patterns.", roles: ["administrator", "scheduler", "clinician"] },
  simulation: { title: "Simulation", subtitle: "Replay de-identified demand without changing the live calendar.", roles: ["administrator", "scheduler", "clinician"] },
  configuration: { title: "Settings", subtitle: "Maintain governed scheduling resources and policy.", roles: ["administrator"] },
  audit: { title: "Audit log", subtitle: "Review append-only controlled activity.", roles: ["administrator", "auditor"] },
};

const HELP = {
  home: {
    purpose: "Use Home to see what needs attention now and start the correct workflow.",
    tasks: ["Open today’s patient flow", "Schedule a patient or walk-in", "Review role-specific work"],
    safety: "Home is an overview. Complete controlled changes in their dedicated workflow.",
    access: "Every signed-in role receives a workspace appropriate to its permissions.",
  },
  operations: {
    purpose: "Use Today to check patients in, record seating, and close visits with their real outcome.",
    tasks: ["Review the operating day", "Record arrival and seating", "Record completion, cancellation, or no-show"],
    safety: "Do not pre-record workflow events or force a walk-in into an infeasible opening.",
    access: "Schedulers, clinicians, and administrators.",
  },
  scheduler: {
    purpose: "Use Schedule patient to find and lock one feasible appointment.",
    tasks: ["Find or add a patient", "Select clinician-approved treatment", "Compare feasible openings; add patient limits only when needed"],
    safety: "A search never moves an existing visit. Reserved-block overrides require an authorized role, an exact option, and a recorded reason.",
    access: "Schedulers, clinicians, and administrators.",
  },
  waitlist: {
    purpose: "Use the ASAP waitlist to manage patients who consented to an earlier opening.",
    tasks: ["Add a waitlist request", "Record contact attempts", "Find a compatible opening"],
    safety: "Never weaken a hard constraint or move another patient merely to create capacity.",
    access: "Schedulers, clinicians, and administrators.",
  },
  calendar: {
    purpose: "Use Calendar to inspect confirmed visits by month or across the annual horizon.",
    tasks: ["Review appointment density", "See reserved doctor/procedure capacity", "Open a day or start protected rescheduling"],
    safety: "A lightly booked day is not necessarily feasible; only a scheduling search confirms availability.",
    access: "Schedulers, clinicians, and administrators.",
  },
  analytics: {
    purpose: "Use Reports to review local utilization, attendance, wait, duration, and production patterns.",
    tasks: ["Choose a comparable date range", "Review operational metrics", "Identify questions for governed review"],
    safety: "Reports are descriptive and must not diagnose, deny care, or override safety policy.",
    access: "Schedulers, clinicians, and administrators according to practice policy.",
  },
  simulation: {
    purpose: "Use Simulation to test de-identified appointment demand against current practice capacity.",
    tasks: ["Upload a CSV or XLSX file", "Review validated rows and policy substitutions", "Run and download a hypothetical schedule"],
    safety: "A simulation never creates or changes a live appointment. Direct identifiers, free-text clinical content, formulas, and reserved-capacity overrides are rejected.",
    access: "Schedulers, clinicians, and administrators. Preview and completion are recorded without uploaded row content in the audit log.",
  },
  configuration: {
    purpose: "Use Settings to maintain the inputs that determine feasibility and staff access.",
    tasks: ["Maintain people and access", "Create or release doctor procedure blocks", "Manage supporting availability, resources, and approved procedure rules"],
    safety: "Never change policy merely to clear an error or manufacture an opening. Existing confirmed visits remain fixed.",
    access: "Administrators; clinical policy and duration changes also require authorized clinical approval.",
  },
  audit: {
    purpose: "Use Audit log to verify who performed a controlled action, when, and with what outcome.",
    tasks: ["Filter recent events", "Review actors and outcomes", "Escalate missing or unexplained activity"],
    safety: "Do not copy patient-linked information to external systems outside the approved incident process.",
    access: "Administrators and auditors. This page is read-only.",
  },
};

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
  });
  if (response.status === 401) {
    showLogin();
    throw new Error("Your session expired. Sign in again.");
  }
  if (!response.ok) {
    let message = "The request could not be completed.";
    try {
      const body = await response.json();
      const fieldLabels = {
        patient_name: "Patient name",
        medical_record_number: "Patient record number (MRN)",
        procedure_code: "Procedure",
        date_from: "Earliest acceptable date",
        date_to: "Latest acceptable date",
        time_from: "Earliest daily time",
        time_to: "Latest daily time",
        reason: "Reason",
      };
      message = Array.isArray(body.detail) ? body.detail.map((item) => {
        const field = item.loc?.[item.loc.length - 1];
        return fieldLabels[field] ? `${fieldLabels[field]}: ${item.msg}` : item.msg;
      }).join("; ") : body.detail || message;
    } catch (_) {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function isoDate(value) {
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: practiceTimeZone(), year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function addDays(value, count) {
  const date = new Date(value);
  date.setDate(date.getDate() + count);
  return date;
}

function money(cents) {
  return new Intl.NumberFormat([], { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format((cents || 0) / 100);
}

function practiceTimeZone() {
  return state.catalog?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function practiceLocalToIso(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value || "");
  if (!match) throw new Error("Enter a complete local date and time.");
  const desired = match.slice(1).map(Number);
  const desiredUtc = Date.UTC(desired[0], desired[1] - 1, desired[2], desired[3], desired[4]);
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: practiceTimeZone(), hourCycle: "h23", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const zonedUtcValue = (instant) => {
    const parts = Object.fromEntries(formatter.formatToParts(instant).map((part) => [part.type, part.value]));
    return Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute), Number(parts.second));
  };
  let candidate = new Date(desiredUtc);
  candidate = new Date(desiredUtc - (zonedUtcValue(candidate) - candidate.getTime()));
  candidate = new Date(candidate.getTime() + desiredUtc - zonedUtcValue(candidate));
  if (zonedUtcValue(candidate) !== desiredUtc) {
    throw new Error("That local time does not exist in the practice timezone because of a clock change.");
  }
  return candidate.toISOString();
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat([], { timeZone: practiceTimeZone(), weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function formatDate(value) {
  return new Intl.DateTimeFormat([], { timeZone: practiceTimeZone(), weekday: "short", month: "short", day: "numeric" }).format(new Date(value));
}

function formatTime(value) {
  return new Intl.DateTimeFormat([], { timeZone: practiceTimeZone(), hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function minutesBetween(start, end) {
  return Math.round((new Date(end) - new Date(start)) / 60000);
}

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = value ?? "";
  return element.innerHTML;
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast visible${error ? " error" : ""}`;
  clearTimeout(toast.timeout);
  toast.timeout = setTimeout(() => { element.className = "toast"; }, 5500);
}

function success(title, detail) {
  $("#activity-title").textContent = title;
  $("#activity-detail").textContent = detail;
  $("#activity-banner").hidden = false;
  toast(title);
}

function loading(element, value) {
  if (!element) return;
  element.classList.toggle("loading", value);
  element.disabled = value;
}

function closeEditor(form) {
  const details = form.closest("details");
  if (details) details.open = false;
}

function showLogin() {
  $("#app-view").hidden = true;
  $("#login-view").hidden = false;
  $("#login-password").value = "";
}

function showApp() {
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  const name = state.user.display_name;
  $("#user-name").textContent = name;
  $("#user-role").textContent = state.user.role;
  $("#user-initials").textContent = name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("");
  $$('[data-roles]').forEach((element) => {
    const roles = element.dataset.roles.split(",");
    element.hidden = !roles.includes(state.user.role);
  });
}

function routeParts() {
  return location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
}

function navigate(route) {
  const target = `#/${route}`;
  if (location.hash === target) applyRoute();
  else location.hash = target;
}

async function applyRoute() {
  if (!state.user) return;
  const parts = routeParts();
  let view = parts[0] || "home";
  if (!VIEW_META[view] || !VIEW_META[view].roles.includes(state.user.role)) view = "home";
  state.route = view;
  state.settingsSection = view === "configuration" ? (parts[1] || "people") : state.settingsSection;

  $$(".view").forEach((section) => { section.hidden = section.id !== `${view}-view`; });
  $$(".nav-item").forEach((button) => {
    const buttonView = button.dataset.route.split("/")[0];
    button.classList.toggle("active", buttonView === view);
  });
  const meta = VIEW_META[view];
  $("#view-title").textContent = meta.title;
  $("#view-subtitle").textContent = meta.subtitle;
  document.title = `${meta.title} · Siligent`;
  $("#activity-banner").hidden = true;

  if (view === "home") await loadHome();
  if (view === "operations") await loadOperations();
  if (view === "waitlist") await loadWaitlist();
  if (view === "calendar") await loadCalendar();
  if (view === "analytics") await loadAnalytics();
  if (view === "configuration") {
    setSettingsSection(state.settingsSection, false);
    await loadConfiguration();
  }
  if (view === "audit") await loadAudit();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openHelp() {
  const content = HELP[state.route];
  $("#help-title").textContent = `About ${VIEW_META[state.route].title}`;
  $("#help-purpose").textContent = content.purpose;
  $("#help-tasks").innerHTML = content.tasks.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  $("#help-safety").textContent = content.safety;
  $("#help-access").textContent = content.access;
  $("#help-dialog").showModal();
}

function phaseChips(phases) {
  return phases.map((phase) => `<span class="phase-chip"><b>${escapeHtml(phase.role)}</b> · ${escapeHtml(phase.duration_minutes)} min ${escapeHtml(phase.name)}</span>`).join("");
}

function phaseStrip(phases) {
  return `<div class="phase-strip">${phases.map((phase) => {
    const minutes = phase.duration_minutes ?? minutesBetween(phase.starts_at, phase.ends_at);
    const width = Math.min(12, Math.max(1, Math.round(minutes / 15)));
    return `<div class="phase-segment ${escapeHtml(phase.role)} phase-width-${width}"><b>${escapeHtml(phase.role)}</b><span>${escapeHtml(minutes)}m${phase.provider_name ? ` · ${escapeHtml(phase.provider_name)}` : ""}</span></div>`;
  }).join("")}</div>`;
}

function populateProcedurePreview() {
  if (!state.catalog) return;
  const procedure = state.catalog.procedures.find((item) => item.code === $("#procedure").value);
  $("#procedure-preview").innerHTML = procedure ? phaseChips(procedure.phases) : "";
}

async function bootstrap() {
  const now = new Date();
  $("#today-label").textContent = new Intl.DateTimeFormat([], { weekday: "long", month: "long", day: "numeric", year: "numeric" }).format(now);
  setDateDefaults(now);
  try {
    const session = await api("/api/auth/session");
    state.user = session.user;
    showApp();
    await loadApplication();
  } catch (_) {
    showLogin();
  }
}

function setDateDefaults(now = new Date()) {
  const min = isoDate(now);
  const max = isoDate(addDays(now, 365));
  ["#date-from", "#date-to", "#waitlist-from", "#waitlist-to", "#reschedule-from", "#reschedule-to", "#operations-date", "#shift-date", "#reserved-block-repeat-until"].forEach((id) => {
    $(id).min = min;
    $(id).max = max;
  });
  $("#analytics-from").min = isoDate(addDays(now, -366));
  $("#analytics-from").max = max;
  $("#analytics-to").min = isoDate(addDays(now, -366));
  $("#analytics-to").max = max;
  $("#date-from").value = min;
  $("#date-to").value = isoDate(addDays(now, 30));
  $("#waitlist-from").value = min;
  $("#waitlist-to").value = isoDate(addDays(now, 90));
  $("#reschedule-from").value = isoDate(addDays(now, 1));
  $("#reschedule-to").value = isoDate(addDays(now, 30));
  $("#operations-date").value = min;
  $("#analytics-from").value = isoDate(addDays(now, -30));
  $("#analytics-to").value = min;
  $("#shift-date").value = min;
  const localParts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: practiceTimeZone(), hourCycle: "h23", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(now).map((part) => [part.type, part.value]));
  const localMinimum = `${localParts.year}-${localParts.month}-${localParts.day}T${localParts.hour}:${localParts.minute}`;
  ["#reserved-block-start", "#reserved-block-end", "#reserved-block-release-at"].forEach((id) => {
    $(id).min = localMinimum;
  });
}

function resetWaitlistDates(now = new Date()) {
  $("#waitlist-from").value = isoDate(now);
  $("#waitlist-to").value = isoDate(addDays(now, 90));
  $("#waitlist-time-from").value = "08:00";
  $("#waitlist-time-to").value = "17:00";
}

async function loadApplication() {
  state.catalog = await api("/api/catalog");
  const now = new Date();
  $("#today-label").textContent = new Intl.DateTimeFormat([], { timeZone: practiceTimeZone(), weekday: "long", month: "long", day: "numeric", year: "numeric" }).format(now);
  setDateDefaults(now);
  const options = state.catalog.procedures.map((procedure) => {
    const minutes = procedure.phases.reduce((sum, item) => sum + item.duration_minutes, 0) || procedure.duration_minutes + procedure.preparation_minutes + procedure.cleanup_minutes;
    return `<option value="${escapeHtml(procedure.code)}">${escapeHtml(procedure.name)} · ${minutes} min · ${escapeHtml(money(procedure.production_cents))}</option>`;
  }).join("");
  $("#procedure").innerHTML = options;
  $("#waitlist-procedure").innerHTML = options;
  const doctors = '<option value="">Best available</option>' + state.catalog.doctors.map((doctor) => `<option value="${escapeHtml(doctor.id)}">${escapeHtml(doctor.name)}</option>`).join("");
  $("#preferred-doctor").innerHTML = doctors;
  populateProcedurePreview();
  if (!location.hash) navigate("home");
  else await applyRoute();
}

async function loadDashboard() {
  state.dashboard = await api("/api/dashboard");
  return state.dashboard;
}

function renderAppointmentList(container, appointments, actions = false) {
  if (!appointments.length) {
    container.innerHTML = '<div class="empty-state compact"><p>No appointments in this range.</p></div>';
    return;
  }
  container.innerHTML = `<div class="appointment-table-head" aria-hidden="true"><span>Patient name</span><span>Procedure</span><span>Start</span><span>End</span><span>Doctor / room</span><span>Status</span><span>Actions</span></div>` + appointments.map((item) => {
    const canRecover = actions && item.status === "cancelled" && item.room_name && !item.checked_in_at && !item.seated_at && new Date(item.starts_at) > new Date() && ["administrator", "scheduler"].includes(state.user.role);
    const outcomeData = `data-id="${escapeHtml(item.id)}" data-seated="${item.seated_at ? "true" : "false"}" data-can-no-show="${!item.checked_in_at && new Date(item.starts_at) <= new Date() ? "true" : "false"}"`;
    const actionMarkup = actions && item.status === "confirmed"
      ? `<span class="row-actions appointment-actions" data-label="Actions"><button class="link-button reschedule-trigger" data-id="${escapeHtml(item.id)}" type="button">Reschedule</button><button class="link-button status-trigger" ${outcomeData} type="button">Outcome</button></span>`
      : canRecover
        ? `<span class="appointment-actions" data-label="Actions"><button class="link-button recovery-trigger" data-id="${escapeHtml(item.id)}" type="button">${item.vacancy_recovery_status === "active" ? "Resume recovery" : item.vacancy_recovery_status === "stopped" ? "View recovery" : "Recover opening"}</button></span>`
        : '<span class="appointment-actions" data-label="Actions">—</span>';
    return `<article class="appointment-row">
    <span class="appointment-patient" data-label="Patient name"><strong>${escapeHtml(item.patient_name)}</strong></span>
    <span class="appointment-procedure" data-label="Procedure"><strong>${escapeHtml(item.procedure_name)}</strong></span>
    <span class="appointment-start" data-label="Start"><strong>${escapeHtml(formatTime(item.starts_at))}</strong><small>${escapeHtml(formatDate(item.starts_at))}</small></span>
    <span class="appointment-end" data-label="End"><strong>${escapeHtml(formatTime(item.ends_at))}</strong></span>
    <span class="appointment-provider" data-label="Doctor / room"><strong>${escapeHtml(item.doctor_name)}</strong><small>${escapeHtml(item.room_name || "Room pending")}</small></span>
    <span class="appointment-status" data-label="Status"><span class="badge">${escapeHtml(item.status)}</span></span>
    ${actionMarkup}
  </article>`;
  }).join("");
  container.querySelectorAll(".reschedule-trigger").forEach((button) => button.addEventListener("click", () => openReschedule(button.dataset.id)));
  container.querySelectorAll(".status-trigger").forEach((button) => button.addEventListener("click", () => openStatus(button)));
  container.querySelectorAll(".recovery-trigger").forEach((button) => button.addEventListener("click", () => resumeVacancyRecovery(button.dataset.id)));
}

async function loadHome() {
  const role = state.user.role;
  $("#home-greeting").textContent = `Welcome, ${state.user.display_name.split(/\s+/)[0]}`;
  const actionsByRole = {
    scheduler: [["Schedule patient", "scheduler"], ["Schedule walk-in", "scheduler?walkin=1"], ["Work waitlist", "waitlist"]],
    clinician: [["Open Today", "operations"], ["Schedule patient", "scheduler"], ["Review reports", "analytics"]],
    administrator: [["Open Today", "operations"], ["Schedule patient", "scheduler"], ["Review settings", "configuration/people"]],
    auditor: [["Review audit log", "audit"]],
  };
  $("#home-quick-actions").innerHTML = actionsByRole[role].map(([label, route]) => `<button class="button" type="button" data-home-route="${escapeHtml(route)}">${escapeHtml(label)}</button>`).join("");
  $$("[data-home-route]").forEach((button) => button.addEventListener("click", () => {
    const [route, query] = button.dataset.homeRoute.split("?");
    if (query === "walkin=1") prepareWalkIn();
    navigate(route);
  }));

  if (role === "auditor") {
    await loadAudit(false);
    $("#home-guidance").textContent = "Review controlled activity and investigate unexpected events.";
    $("#home-metrics").innerHTML = [
      ["Recent events", state.auditEvents.length],
      ["Failed outcomes", state.auditEvents.filter((item) => item.outcome !== "success").length],
    ].map(([label, value]) => `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
    $("#home-upcoming").innerHTML = '<div class="empty-state compact"><p>Patient appointments are not shown in the auditor workspace.</p></div>';
    $("#role-panel-title").textContent = "Audit priorities";
    renderRoleTasks([
      ["Review recent controlled changes", "Filter the audit log by category and outcome.", "audit"],
      ["Investigate unexpected actors", "Escalate missing or unexplained events through the approved process.", "audit"],
    ]);
    return;
  }

  const data = await loadDashboard();
  $("#home-guidance").textContent = role === "administrator" ? "Review the day, then resolve staffing or configuration work." : "Start with the patients and requests that need attention now.";
  const metrics = [
    ["Visits today", data.metrics.today, "confirmed and in progress"],
    ["Upcoming visits", data.metrics.upcoming, "across the rolling schedule"],
    ["ASAP waitlist", data.metrics.waitlist, "patients ready to move"],
    ["Daily production", money(data.metrics.production_cents), "scheduled credit"],
  ];
  $("#home-metrics").innerHTML = metrics.map(([label, value, detail], index) => `<article class="metric-card${index === 2 && Number(value) ? " attention" : ""}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`).join("");
  renderAppointmentList($("#home-upcoming"), data.upcoming.slice(0, 6), true);

  if (role === "administrator") {
    $("#role-panel-title").textContent = "Administrative priorities";
    renderRoleTasks([
      ["Review daily coverage", "Confirm shifts, leave, and closures before scheduling.", "configuration/availability"],
      ["Maintain unique access", "Create or review practice accounts.", "configuration/people"],
      ["Review controlled activity", "Inspect configuration and rescheduling events.", "audit"],
    ]);
  } else if (role === "clinician") {
    $("#role-panel-title").textContent = "Clinical priorities";
    renderRoleTasks([
      ["Review today’s handoffs", "See when the dentist and supporting staff are needed.", "operations"],
      ["Review procedure trends", "Use local descriptive evidence for governed discussion.", "analytics"],
    ]);
  } else {
    $("#role-panel-title").textContent = "Scheduling priorities";
    renderRoleTasks([
      ["Schedule a new patient", "Find a feasible opening in three steps.", "scheduler"],
      ["Work the ASAP queue", `${data.metrics.waitlist} request(s) currently active.`, "waitlist"],
      ["Run today’s schedule", "Check patients in and record outcomes.", "operations"],
    ]);
  }
}

function renderRoleTasks(tasks) {
  $("#role-action-list").innerHTML = tasks.map(([title, detail, route]) => `<article class="task-item"><span><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></span><button class="link-button" type="button" data-task-route="${escapeHtml(route)}">Open</button></article>`).join("");
  $$("[data-task-route]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.taskRoute)));
}

function validateStep(step) {
  const section = $(`[data-schedule-step="${step}"]`);
  const invalid = [...section.querySelectorAll("input,select,textarea")].find((field) => !field.checkValidity());
  if (invalid) {
    invalid.reportValidity();
    invalid.focus();
    return false;
  }
  return true;
}

function setScheduleStep(step, force = false) {
  const bounded = Math.min(3, Math.max(1, Number(step)));
  if (!force && bounded > state.maxScheduleStep) return;
  state.scheduleStep = bounded;
  state.maxScheduleStep = Math.max(state.maxScheduleStep, bounded);
  $$('[data-schedule-step]').forEach((section) => { section.hidden = Number(section.dataset.scheduleStep) !== bounded; });
  $$(".workflow-step").forEach((button) => {
    const number = Number(button.dataset.stepTarget);
    button.classList.toggle("active", number === bounded);
    button.classList.toggle("complete", number < bounded);
    button.disabled = number > state.maxScheduleStep;
    button.setAttribute("aria-current", number === bounded ? "step" : "false");
  });
  $(".workflow-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetSchedule() {
  $("#schedule-form").reset();
  setDateDefaults(new Date());
  $("#time-from").value = "08:00";
  $("#time-to").value = "17:00";
  $("#patient-search").value = "";
  $("#patient-search-results").innerHTML = "";
  $("#intake-summary").hidden = true;
  $("#recommendations").className = "empty-state";
  $("#recommendations").innerHTML = '<div class="empty-mark">⌕</div><h3>Search has not run</h3><p>Go back and find feasible openings.</p>';
  state.recommendations = [];
  state.pendingCandidate = null;
  state.intakeConfirmationRequired = false;
  state.maxScheduleStep = 1;
  $("#patient-always-available").checked = true;
  updatePatientAvailabilityControls();
  populateProcedurePreview();
  setScheduleStep(1, true);
}

function prepareWalkIn() {
  resetSchedule();
  $("#walk-in").checked = true;
  $("#date-from").value = isoDate(new Date());
  $("#date-to").value = isoDate(new Date());
}

function updatePatientAvailabilityControls() {
  const custom = !$("#patient-always-available").checked;
  $("#custom-patient-availability").hidden = !custom;
  ["#date-from", "#date-to", "#time-from", "#time-to"].forEach((id) => {
    $(id).required = custom;
  });
}

async function searchPatients() {
  const query = $("#patient-search").value.trim();
  const container = $("#patient-search-results");
  if (query.length < 2) {
    container.innerHTML = '<p class="field-guidance">Enter at least 2 characters.</p>';
    return;
  }
  const button = $("#patient-search-button");
  loading(button, true);
  try {
    const data = await api("/api/patients/search", {
      method: "POST",
      body: JSON.stringify({ query, limit: 10 }),
    });
    if (!data.patients.length) {
      container.innerHTML = '<p class="field-guidance">No matching patient. Enter the new patient details below.</p>';
      return;
    }
    container.innerHTML = data.patients.map((patient) => `<button class="patient-result" type="button" data-name="${escapeHtml(patient.display_name)}" data-mrn="${escapeHtml(patient.medical_record_number)}"><span><strong>${escapeHtml(patient.display_name)}</strong><small>MRN ${escapeHtml(patient.medical_record_number)}</small></span><small>${patient.last_appointment_at ? `Last visit ${escapeHtml(formatDateTime(patient.last_appointment_at))}` : "No prior visit"}</small></button>`).join("");
    container.querySelectorAll(".patient-result").forEach((result) => result.addEventListener("click", () => {
      $("#patient-name").value = result.dataset.name;
      $("#patient-mrn").value = result.dataset.mrn;
      container.innerHTML = `<p class="field-guidance"><strong>${escapeHtml(result.dataset.name)}</strong> selected.</p>`;
      $("#patient-name").focus();
    }));
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

async function searchRecommendations(event) {
  event.preventDefault();
  if (!validateStep(2)) return;
  const button = $("#recommend-button");
  loading(button, true);
  try {
    const data = await api("/api/recommendations", {
      method: "POST",
      body: JSON.stringify({
        patient_name: $("#patient-name").value.trim(),
        medical_record_number: $("#patient-mrn").value.trim(),
        procedure_code: $("#procedure").value,
        condition: $("#condition").value,
        patient_always_available: $("#patient-always-available").checked,
        date_from: $("#date-from").value,
        date_to: $("#date-to").value,
        time_from: $("#time-from").value,
        time_to: $("#time-to").value,
        preferred_doctor_id: $("#preferred-doctor").value || null,
        difficulty: $("#difficulty").value,
        waitlist_consent: $("#waitlist-consent").checked,
        walk_in: $("#walk-in").checked,
        allow_reserved_block_override: $("#reserved-block-override-search").checked,
      }),
    });
    state.intakeConfirmationRequired = data.intake.requires_staff_confirmation;
    state.recommendations = data.candidates;
    const risk = data.intake.attendance_risk;
    $("#intake-summary").hidden = false;
    $("#intake-summary").innerHTML = `<strong>${escapeHtml(data.intake.priority.replaceAll("_", " "))} priority</strong> · ${escapeHtml(data.intake.tags.join(", ") || "no condition tags")} · local source ${escapeHtml(data.intake.source)} · attendance risk ${escapeHtml(Math.round(risk.probability * 100))}% (${escapeHtml(risk.basis)})`;
    renderRecommendations(data.candidates);
    state.maxScheduleStep = 3;
    setScheduleStep(3, true);
    if (!data.candidates.length && $("#waitlist-consent").checked) success("Added to ASAP waitlist", "No feasible opening was found, so the consented request remains available for cancellation recovery.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function renderRecommendations(candidates) {
  const container = $("#recommendations");
  if (!candidates.length) {
    container.className = "empty-state";
    container.innerHTML = '<div class="empty-mark">0</div><h3>No feasible opening</h3><p>All hard constraints were preserved. Review doctor procedure blocks and resource coverage, try a custom patient window, or use the ASAP waitlist.</p>';
    return;
  }
  container.className = "recommendations";
  container.innerHTML = candidates.map((candidate, index) => {
    const start = new Date(candidate.starts_at);
    const dateParts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: practiceTimeZone(), month: "short", day: "numeric", weekday: "short" }).formatToParts(start).map((part) => [part.type, part.value]));
    const equipment = (candidate.equipment || []).map((item) => `unit ${item.unit_number}`).join(", ");
    const override = candidate.requires_reserved_block_override ? '<span class="badge override-badge">Authorized override required</span>' : "";
    return `<article class="recommendation-card${index === 0 ? " best" : ""}${candidate.requires_reserved_block_override ? " override-candidate" : ""}"><div class="recommendation-top"><div class="date-tile"><span>${escapeHtml(dateParts.month)}</span><strong>${escapeHtml(dateParts.day)}</strong><span>${escapeHtml(dateParts.weekday)}</span></div><div class="slot-copy"><strong>${escapeHtml(formatTime(candidate.starts_at))}–${escapeHtml(formatTime(candidate.ends_at))} · ${escapeHtml(candidate.doctor_name)}</strong><span>${escapeHtml(candidate.room_name)}${equipment ? ` · equipment ${escapeHtml(equipment)}` : ""}</span>${override}<small>${index === 0 ? "Best match · " : ""}${escapeHtml(candidate.explanation.join(" · "))}</small></div><button class="button primary review-slot" data-id="${escapeHtml(candidate.id)}" type="button">Review</button></div>${phaseStrip(candidate.phases)}</article>`;
  }).join("");
  container.querySelectorAll(".review-slot").forEach((button) => button.addEventListener("click", () => openConfirmation(button.dataset.id)));
}

function openConfirmation(candidateId) {
  const candidate = state.recommendations.find((item) => item.id === candidateId);
  if (!candidate) return;
  state.pendingCandidate = candidate;
  const procedureName = $("#procedure").selectedOptions[0]?.textContent.split(" · ")[0] || $("#procedure").value;
  const items = [
    ["Patient", $("#patient-name").value],
    ["Procedure", procedureName],
    ["Doctor", candidate.doctor_name],
    ["Date and time", `${formatDateTime(candidate.starts_at)}–${formatTime(candidate.ends_at)}`],
    ["Room", candidate.room_name],
    ["Clinical plan", candidate.phases.map((phase) => `${phase.role} ${phase.duration_minutes ?? minutesBetween(phase.starts_at, phase.ends_at)}m`).join(" · ")],
  ];
  $("#confirm-summary").innerHTML = items.map(([label, value]) => `<div class="review-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
  $("#confirm-intake-row").hidden = !state.intakeConfirmationRequired;
  $("#intake-confirmation").checked = false;
  $("#reserved-block-override-review").hidden = !candidate.requires_reserved_block_override;
  $("#reserved-block-override-reason").required = candidate.requires_reserved_block_override;
  $("#reserved-block-override-reason").value = "";
  $("#reserved-block-override-acknowledgement").checked = false;
  $("#confirm-dialog").showModal();
}

async function confirmSlot(event) {
  event.preventDefault();
  const button = $("#confirm-slot-button");
  if (state.intakeConfirmationRequired && !$("#intake-confirmation").checked) {
    toast("Review and accept the locally normalized scheduling tags first.", true);
    return;
  }
  if (state.pendingCandidate.requires_reserved_block_override && !$("#reserved-block-override-acknowledgement").checked) {
    toast("Explicitly acknowledge the exact reserved-block override first.", true);
    return;
  }
  loading(button, true);
  try {
    await api("/api/appointments", { method: "POST", body: JSON.stringify({
      recommendation_id: state.pendingCandidate.id,
      staff_confirms_intake: $("#intake-confirmation").checked,
      reserved_block_override_acknowledged: $("#reserved-block-override-acknowledgement").checked,
      reserved_block_override_reason: $("#reserved-block-override-reason").value || null,
    }) });
    $("#confirm-dialog").close();
    $("#recommendations").className = "empty-state";
    $("#recommendations").innerHTML = '<div class="empty-mark">✓</div><h3>Confirmed and locked</h3><p>The doctor, room, supporting resources, and phases are reserved.</p>';
    $("#intake-summary").hidden = true;
    success("Appointment confirmed and locked", "Use protected rescheduling and explicit authorization for any later change.");
    state.dashboard = null;
    state.appointments = [];
    state.calendarLoaded = false;
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

async function loadOperations() {
  const day = $("#operations-date").value;
  const data = await api(`/api/operations?day=${encodeURIComponent(day)}`);
  const active = data.appointments.filter((item) => item.status === "confirmed");
  const production = data.providers.reduce((sum, item) => sum + Number(item.production_cents), 0);
  const doctorMinutes = data.providers.filter((item) => item.role === "doctor").reduce((sum, item) => sum + Number(item.booked_minutes), 0);
  $("#operations-summary").innerHTML = [
    ["Visits", active.length, "confirmed today"],
    ["Rooms in plan", new Set(active.map((item) => item.room_name)).size, "active operatories"],
    ["Dentist minutes", doctorMinutes, "scheduled clinical time"],
    ["Production", money(production), "scheduled credit"],
  ].map(([label, value, detail]) => `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`).join("");
  const timeline = $("#operations-appointments");
  timeline.innerHTML = data.appointments.map((item) => {
    const recoverable = item.status === "cancelled" && item.room_name && !item.checked_in_at && !item.seated_at && new Date(item.starts_at) > new Date() && ["administrator", "scheduler"].includes(state.user.role);
    const scheduledToday = isoDate(item.starts_at) === isoDate(new Date());
    const flowAction = scheduledToday
      ? !item.checked_in_at ? `<button class="button secondary flow-trigger" data-id="${escapeHtml(item.id)}" data-action="check_in" type="button">Check in</button>` : !item.seated_at ? `<button class="button secondary flow-trigger" data-id="${escapeHtml(item.id)}" data-action="seat" type="button">Mark as seated</button>` : '<span class="badge">Seated</span>'
      : '<span class="badge">Not today</span>';
    const outcomeData = `data-id="${escapeHtml(item.id)}" data-seated="${item.seated_at ? "true" : "false"}" data-can-no-show="${!item.checked_in_at && new Date(item.starts_at) <= new Date() ? "true" : "false"}"`;
    const flow = item.status === "confirmed" ? `<div class="row-actions">${flowAction}<button class="link-button status-trigger" ${outcomeData} type="button">Record outcome</button></div>` : recoverable ? `<div class="row-actions"><button class="link-button recovery-trigger" data-id="${escapeHtml(item.id)}" type="button">${item.vacancy_recovery_status === "active" ? "Resume recovery" : item.vacancy_recovery_status === "stopped" ? "View recovery" : "Recover opening"}</button></div>` : "";
    return `<article class="timeline-card"><div class="timeline-head"><div><strong>${escapeHtml(item.patient_name)}</strong><span>${escapeHtml(item.procedure_name)} · Start ${escapeHtml(formatTime(item.starts_at))} · End ${escapeHtml(formatTime(item.ends_at))}</span><span>${escapeHtml(item.doctor_name)} · ${escapeHtml(item.room_name)}${item.arrival_type === "walk_in" ? " · walk-in" : ""}</span></div><span class="badge">${escapeHtml(item.status)}</span>${flow}</div>${phaseStrip(item.phases)}</article>`;
  }).join("") || '<div class="empty-state compact"><p>No visits planned for this day.</p></div>';
  timeline.querySelectorAll(".flow-trigger").forEach((button) => button.addEventListener("click", () => advanceFlow(button)));
  timeline.querySelectorAll(".status-trigger").forEach((button) => button.addEventListener("click", () => openStatus(button)));
  timeline.querySelectorAll(".recovery-trigger").forEach((button) => button.addEventListener("click", () => resumeVacancyRecovery(button.dataset.id)));
  $("#provider-board").innerHTML = data.providers.map((item) => {
    const percent = item.target_cents ? Math.min(100, Math.round(item.production_cents / item.target_cents * 100)) : 0;
    return `<article class="provider-card"><header><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.role)}</small></header><progress class="progress" max="100" value="${escapeHtml(percent)}" aria-label="${escapeHtml(percent)} percent of production target"></progress><div class="provider-stats"><span>${escapeHtml(item.booked_minutes)} min booked</span><span>${escapeHtml(money(item.production_cents))}</span></div></article>`;
  }).join("");
}

async function advanceFlow(button) {
  loading(button, true);
  try {
    await api(`/api/appointments/${button.dataset.id}/flow`, { method: "POST", body: JSON.stringify({ action: button.dataset.action }) });
    success(button.dataset.action === "check_in" ? "Patient checked in" : "Patient marked as seated", "Today’s timeline and audit history were updated.");
    await loadOperations();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

async function loadWaitlist() {
  const data = await api("/api/waitlist");
  state.waitlistEntries = data.entries;
  renderWaitlist();
}

function renderWaitlist() {
  const query = $("#waitlist-filter").value.trim().toLowerCase();
  const priority = $("#waitlist-priority-filter").value;
  const entries = state.waitlistEntries.filter((item) => {
    const searchable = `${item.patient_name} ${item.medical_record_number} ${item.procedure_name}`.toLowerCase();
    return (!query || searchable.includes(query)) && (!priority || item.priority === priority);
  });
  const container = $("#waitlist-entries");
  container.innerHTML = entries.map((item) => `<article class="waitlist-card"><span><strong>${escapeHtml(item.patient_name)} · ${escapeHtml(item.procedure_name)}</strong><small>MRN ${escapeHtml(item.medical_record_number)} · ${escapeHtml(item.priority)} · ${escapeHtml(item.earliest_date)} through ${escapeHtml(item.latest_date)} · ${escapeHtml(item.contact_attempts)} contact(s)${item.last_contact_outcome ? ` · last ${escapeHtml(item.last_contact_outcome.replaceAll("_", " "))}` : ""}</small></span><div class="row-actions"><button class="button quiet waitlist-contact" data-id="${escapeHtml(item.id)}" type="button">Record contact</button><button class="button secondary waitlist-match" data-id="${escapeHtml(item.id)}" type="button">Find opening</button></div></article>`).join("") || '<div class="empty-state"><div class="empty-mark">✓</div><h3>No matching requests</h3><p>Change the filters or add a new waitlist request.</p></div>';
  container.querySelectorAll(".waitlist-match").forEach((button) => button.addEventListener("click", () => findWaitlistMatches(button)));
  container.querySelectorAll(".waitlist-contact").forEach((button) => button.addEventListener("click", () => openWaitlistContact(button.dataset.id)));
}

async function addWaitlist(event) {
  event.preventDefault();
  const button = event.submitter;
  loading(button, true);
  try {
    await api("/api/waitlist", { method: "POST", body: JSON.stringify({
      patient_name: $("#waitlist-name").value,
      medical_record_number: $("#waitlist-mrn").value,
      procedure_code: $("#waitlist-procedure").value,
      earliest_date: $("#waitlist-from").value,
      latest_date: $("#waitlist-to").value,
      time_from: $("#waitlist-time-from").value,
      time_to: $("#waitlist-time-to").value,
      priority: $("#waitlist-priority").value,
      notes: "",
    }) });
    $("#waitlist-add-dialog").close();
    event.target.reset();
    resetWaitlistDates();
    success("Waitlist request added", "The patient remains active until scheduled, declined, or otherwise resolved.");
    await loadWaitlist();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function openWaitlistContact(id) {
  const entry = state.waitlistEntries.find((item) => item.id === id);
  if (!entry) return;
  state.contactWaitlistId = id;
  $("#waitlist-contact-summary").textContent = `${entry.patient_name} · ${entry.procedure_name} · ${entry.priority} priority`;
  $("#contact-channel").value = "phone";
  $("#contact-outcome").value = "left_message";
  $("#contact-incentive").value = "";
  $("#waitlist-contact-dialog").showModal();
}

async function recordWaitlistContact(event) {
  event.preventDefault();
  const button = event.submitter;
  loading(button, true);
  try {
    await api(`/api/waitlist/${state.contactWaitlistId}/contacts`, { method: "POST", body: JSON.stringify({ channel: $("#contact-channel").value, outcome: $("#contact-outcome").value, incentive_offered: $("#contact-incentive").value }) });
    $("#waitlist-contact-dialog").close();
    success("Contact attempt recorded", "The waitlist status and append-only audit history were updated.");
    await loadWaitlist();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

async function findWaitlistMatches(button) {
  loading(button, true);
  try {
    const entry = state.waitlistEntries.find((item) => item.id === button.dataset.id);
    const data = await api(`/api/waitlist/${button.dataset.id}/matches`, { method: "POST" });
    if (entry) {
      $("#patient-name").value = entry.patient_name;
      $("#patient-mrn").value = entry.medical_record_number;
      $("#procedure").value = entry.procedure_code;
      populateProcedurePreview();
    }
    state.recommendations = data.candidates;
    state.intakeConfirmationRequired = false;
    $("#intake-summary").hidden = false;
    $("#intake-summary").innerHTML = "<strong>Waitlist match</strong> · the existing request has already been reviewed";
    renderRecommendations(data.candidates);
    state.maxScheduleStep = 3;
    setScheduleStep(3, true);
    navigate("scheduler");
    if (!data.candidates.length) toast("No current match; the patient remains active on the waitlist.", true);
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

async function loadCalendar(force = false) {
  if (!state.calendarLoaded || force) {
    const start = new Date();
    const end = addDays(start, 364);
    const [appointments, blocks] = await Promise.all([
      api(`/api/appointments?date_from=${isoDate(start)}&date_to=${isoDate(end)}`),
      api(`/api/reserved-blocks?date_from=${isoDate(start)}&date_to=${isoDate(end)}`),
    ]);
    state.appointments = appointments.appointments;
    state.reservedBlocks = blocks.blocks;
    state.calendarLoaded = true;
  }
  renderCalendar();
}

function appointmentCounts() {
  const counts = new Map();
  state.appointments.filter((item) => item.status === "confirmed").forEach((item) => {
    const key = isoDate(item.starts_at);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return counts;
}

function reservedBlockCounts() {
  const counts = new Map();
  state.reservedBlocks.filter((item) => item.status === "active").forEach((item) => {
    const key = isoDate(item.starts_at);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return counts;
}

function dayLevel(count) {
  return count >= 6 ? "high" : count >= 3 ? "medium" : count ? "low" : "";
}

function monthCells(month, counts, blockCounts, detailed = false) {
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const offset = (month.getDay() + 6) % 7;
  const cells = Array.from({ length: offset }, () => '<button class="day-cell outside" type="button" tabindex="-1"></button>');
  const today = isoDate(new Date());
  for (let day = 1; day <= days; day += 1) {
    const key = new Date(Date.UTC(month.getFullYear(), month.getMonth(), day)).toISOString().slice(0, 10);
    const count = counts.get(key) || 0;
    const reserved = blockCounts.get(key) || 0;
    cells.push(`<button class="day-cell ${dayLevel(count)} ${reserved ? "has-reserved-block" : ""} ${key === today ? "today" : ""}" data-date="${key}" type="button"><span>${day}</span>${detailed ? `<span class="day-count">${count ? `${count} visit${count === 1 ? "" : "s"}` : "No visits"}${reserved ? `<b>${reserved} reserved</b>` : ""}</span>` : reserved ? '<span class="reserved-dot" aria-label="Reserved capacity"></span>' : ""}</button>`);
  }
  return cells.join("");
}

function renderCalendar() {
  const counts = appointmentCounts();
  const blockCounts = reservedBlockCounts();
  const [practiceYear, practiceMonth] = isoDate(new Date()).split("-").map(Number);
  const first = new Date(practiceYear, practiceMonth - 1, 1);
  const container = $("#calendar-grid");
  $("#month-controls").hidden = state.calendarMode !== "month";
  $$("[data-calendar-mode]").forEach((button) => button.classList.toggle("active", button.dataset.calendarMode === state.calendarMode));
  if (state.calendarMode === "month") {
    const month = new Date(first.getFullYear(), first.getMonth() + state.calendarMonthOffset, 1);
    $("#calendar-month-label").textContent = month.toLocaleString([], { month: "long", year: "numeric" });
    $("#previous-month").disabled = state.calendarMonthOffset === 0;
    $("#next-month").disabled = state.calendarMonthOffset === 11;
    container.innerHTML = `<div class="month-view"><div class="month-grid">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day) => `<span class="weekday">${day}</span>`).join("")}${monthCells(month, counts, blockCounts, true)}</div></div>`;
  } else {
    const months = [];
    for (let index = 0; index < 12; index += 1) {
      const month = new Date(first.getFullYear(), first.getMonth() + index, 1);
      months.push(`<article class="month-card"><h3>${escapeHtml(month.toLocaleString([], { month: "long", year: "numeric" }))}</h3><div class="month-grid">${["M", "T", "W", "T", "F", "S", "S"].map((day) => `<span class="weekday">${day}</span>`).join("")}${monthCells(month, counts, blockCounts, false)}</div></article>`);
    }
    container.innerHTML = `<div class="year-calendar">${months.join("")}</div>`;
  }
  container.querySelectorAll(".day-cell:not(.outside)").forEach((button) => button.addEventListener("click", () => showDay(button.dataset.date)));
}

function showDay(day) {
  const items = state.appointments.filter((item) => isoDate(item.starts_at) === day);
  const blocks = state.reservedBlocks.filter((item) => isoDate(item.starts_at) === day);
  $("#day-detail").hidden = false;
  $("#day-detail-label").textContent = new Intl.DateTimeFormat([], { timeZone: "UTC", weekday: "long", month: "long", day: "numeric", year: "numeric" }).format(new Date(`${day}T12:00:00Z`));
  $("#day-reserved-blocks").innerHTML = blocks.length ? `<div class="subsection-label">Reserved capacity</div>${blocks.map((item) => `<article class="reserved-block-summary"><span><strong>${escapeHtml(formatTime(item.starts_at))}–${escapeHtml(formatTime(item.ends_at))} · ${escapeHtml(item.doctor_name)}</strong><small>${escapeHtml(item.procedure_name)}${item.room_name ? ` · ${escapeHtml(item.room_name)}` : ""}${item.equipment_name ? ` · ${escapeHtml(item.equipment_name)} unit ${escapeHtml(item.equipment_unit_number)}` : ""}</small></span><span class="badge">${escapeHtml(item.status)}</span></article>`).join("")}` : "";
  renderAppointmentList($("#day-appointments"), items, true);
  $("#day-detail").scrollIntoView({ behavior: "smooth" });
}

async function loadAnalytics() {
  const data = await api(`/api/analytics?date_from=${encodeURIComponent($("#analytics-from").value)}&date_to=${encodeURIComponent($("#analytics-to").value)}`);
  const summary = data.summary;
  $("#analytics-summary").innerHTML = [
    ["Chair utilization", `${summary.chair_utilization_percent}%`, "occupied configured capacity"],
    ["No-show rate", `${summary.no_show_rate_percent}%`, "resolved visits"],
    ["Average patient wait", `${summary.average_wait_minutes} min`, "check-in to seating"],
    ["Production", money(summary.production_cents), "selected date range"],
  ].map(([label, value, detail]) => `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`).join("");
  $("#analytics-providers").innerHTML = data.providers.map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.role)} · ${escapeHtml(item.booked_minutes)} booked minutes · ${escapeHtml(money(item.production_cents))} production</small></span><span class="badge">${escapeHtml(money(item.revenue_per_booked_hour_cents))}/h</span></article>`).join("");
  $("#analytics-procedures").innerHTML = data.procedures.map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.visits)} visits · ${escapeHtml(item.no_shows)} no-shows · ${escapeHtml(item.average_actual_minutes)}m observed chair time</small></span></article>`).join("");
}

function simulationUploadBody() {
  if (!state.simulationFile) throw new Error("Choose a CSV or XLSX file first.");
  const body = new FormData();
  body.append("file", state.simulationFile);
  return body;
}

function setSimulationBusy(value) {
  $("#simulation-file").disabled = value;
  $("#simulation-preview-button").disabled = value;
  $("#simulation-clear-button").disabled = value;
}

function renderSimulationPreview(data) {
  state.simulationPreview = data;
  $("#simulation-preview-empty").hidden = true;
  $("#simulation-preview-content").hidden = false;
  $("#simulation-results-panel").hidden = true;
  const summary = data.summary;
  $("#simulation-preview-summary").innerHTML = [
    ["Rows", summary.row_count],
    ["File", data.file_format.toUpperCase()],
    ["Date range", `${summary.date_from} to ${summary.date_to}`],
    ["Policy substitutions", summary.duration_policy_adjustments + summary.production_policy_adjustments],
  ].map(([label, value]) => `<span><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></span>`).join("");
  $("#simulation-policy-note").textContent = `${summary.policy_note} Showing ${data.preview_rows.length} of ${summary.row_count} validated rows.`;
  $("#simulation-preview-table").innerHTML = `<table><thead><tr><th>Patient ref</th><th>Procedure</th><th>Complexity</th><th>Priority</th><th>Availability</th><th>Preferred dentist</th></tr></thead><tbody>${data.preview_rows.map((row) => `<tr><td>${escapeHtml(row.patient_ref)}</td><td>${escapeHtml(row.procedure_code)}</td><td>${escapeHtml(row.difficulty)}</td><td>${escapeHtml(row.priority)}</td><td>${row.availability_assumption === "any_opening" ? "Any opening" : `${escapeHtml(row.availability_start_date)}–${escapeHtml(row.availability_end_date)}<small>${escapeHtml(row.daily_start_time)}–${escapeHtml(row.daily_end_time)}</small>`}</td><td>${escapeHtml(row.preferred_doctor_code || "Best available")}</td></tr>`).join("")}</tbody></table>`;
}

async function previewSimulation(event) {
  event.preventDefault();
  const selected = $("#simulation-file").files[0];
  if (!selected) { toast("Choose a CSV or XLSX file first.", true); return; }
  state.simulationFile = selected;
  state.simulationRun = null;
  const button = $("#simulation-preview-button");
  loading(button, true);
  setSimulationBusy(true);
  try {
    const data = await api("/api/simulations/preview", { method: "POST", body: simulationUploadBody() });
    renderSimulationPreview(data);
    success("Simulation file validated", `${data.summary.row_count} de-identified request(s) are ready for review.`);
  } catch (error) {
    state.simulationPreview = null;
    $("#simulation-preview-empty").hidden = false;
    $("#simulation-preview-content").hidden = true;
    $("#simulation-results-panel").hidden = true;
    toast(error.message, true);
  } finally {
    loading(button, false);
    setSimulationBusy(false);
  }
}

function renderSimulationResults(data) {
  state.simulationRun = data;
  const report = data.report;
  $("#simulation-results-panel").hidden = false;
  $("#simulation-result-metrics").innerHTML = [
    ["Scheduled", `${report.scheduled} of ${report.row_count}`, `${report.schedule_rate_percent}% placement rate`],
    ["Feasible production", money(report.scheduled_production_cents), "hypothetical gross production—not revenue"],
    ["Booking lead", `${report.mean_booking_lead_days} days`, `95th percentile ${report.p95_booking_lead_days} days · ${report.mean_availability_delay_days} days after first acceptable time`],
    ["Unscheduled value", money(report.unscheduled_production_cents), `${report.unscheduled} request(s)`],
  ].map(([label, value, detail]) => `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`).join("");
  const valid = report.invariant_failures.length === 0 && report.locked_appointments_moved === 0 && report.live_calendar_changed === false;
  $("#simulation-invariant-status").className = `simulation-invariant ${valid ? "valid" : "invalid"}`;
  $("#simulation-invariant-status").innerHTML = valid
    ? `<strong>Safety checks passed</strong><span>${escapeHtml(report.confirmed_and_locked_in_simulation)} hypothetical appointments locked, zero locked visits moved, and no live-calendar writes.</span>`
    : `<strong>Safety check failed</strong><span>${escapeHtml(report.invariant_failures.join("; ") || "Review the simulation report.")}</span>`;
  $("#simulation-results-table").innerHTML = `<table><thead><tr><th>Patient ref</th><th>Procedure</th><th>Start / lead</th><th>End</th><th>Doctor / room</th><th>Result</th><th>Production</th></tr></thead><tbody>${data.results.map((row) => `<tr><td>${escapeHtml(row.patient_ref)}</td><td>${escapeHtml(row.procedure_name)}<small>${escapeHtml(row.difficulty)}</small></td><td>${row.starts_at ? `${escapeHtml(formatDateTime(row.starts_at))}<small>${escapeHtml(row.booking_lead_days)} days from request</small>` : "—"}</td><td>${row.ends_at ? escapeHtml(formatTime(row.ends_at)) : "—"}</td><td>${row.doctor_name ? `${escapeHtml(row.doctor_name)}<small>${escapeHtml(row.room_name)}</small>` : "—"}</td><td><span class="badge">${escapeHtml(row.result)}</span>${row.blocking_reason ? `<small>${escapeHtml(row.blocking_reason)}</small>` : ""}</td><td>${escapeHtml(money(row.result === "scheduled" ? row.production_cents : 0))}</td></tr>`).join("")}</tbody></table>`;
  $("#simulation-results-panel").scrollIntoView({ behavior: "smooth" });
}

async function runSimulation() {
  if (!state.simulationPreview) { toast("Validate the upload before running it.", true); return; }
  const button = $("#simulation-run-button");
  loading(button, true);
  setSimulationBusy(true);
  try {
    const data = await api("/api/simulations/run", { method: "POST", body: simulationUploadBody() });
    renderSimulationResults(data);
    success("Simulation complete", `${data.report.scheduled} of ${data.report.row_count} requests were placed without changing the live calendar.`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
    setSimulationBusy(false);
  }
}

function safeCsvCell(value) {
  let text = value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@]/.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function downloadLocalFile(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadSimulationResults() {
  if (!state.simulationRun) return;
  const columns = ["request_id", "patient_ref", "request_received_at", "procedure_code", "procedure_name", "difficulty", "priority", "result", "doctor_name", "room_name", "starts_at", "ends_at", "scheduled_minutes", "booking_lead_days", "availability_delay_days", "production_cents", "locked", "blocking_reason"];
  const csv = [columns.join(","), ...state.simulationRun.results.map((row) => columns.map((column) => safeCsvCell(row[column])).join(","))].join("\r\n") + "\r\n";
  downloadLocalFile("simulation-results.csv", csv, "text/csv;charset=utf-8");
}

function downloadSimulationReport() {
  if (!state.simulationRun) return;
  downloadLocalFile("simulation-report.json", `${JSON.stringify(state.simulationRun.report, null, 2)}\n`, "application/json");
}

function clearSimulation() {
  state.simulationFile = null;
  state.simulationPreview = null;
  state.simulationRun = null;
  $("#simulation-upload-form").reset();
  $("#simulation-preview-empty").hidden = false;
  $("#simulation-preview-content").hidden = true;
  $("#simulation-results-panel").hidden = true;
}

function setSettingsSection(section, updateHash = true) {
  const allowed = ["people", "availability", "resources", "clinical", "calibration"];
  const target = allowed.includes(section) ? section : "people";
  state.settingsSection = target;
  $$("[data-settings-section]").forEach((panel) => { panel.hidden = panel.dataset.settingsSection !== target; });
  $$("[data-settings-route]").forEach((button) => button.classList.toggle("active", button.dataset.settingsRoute === target));
  if (updateHash) navigate(`configuration/${target}`);
}

async function loadConfiguration() {
  const [data, reserved] = await Promise.all([
    api("/api/configuration"),
    api("/api/reserved-blocks"),
  ]);
  state.configuration = data;
  state.reservedBlocks = reserved.blocks;
  const doctors = data.providers.filter((item) => item.role === "doctor");
  $("#configuration-doctors").innerHTML = doctors.map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.staff_code)} · ${escapeHtml(item.specialty || "Dentist")} · max ${escapeHtml(item.max_active_rooms)} active rooms</small></span><span class="row-actions"><span class="badge">${item.active && item.doctor_active ? "active" : "inactive"}</span><button class="button quiet doctor-status-trigger" data-id="${escapeHtml(item.doctor_id)}" type="button">${item.active && item.doctor_active ? "Deactivate" : "Reactivate"}</button><button class="button quiet provider-delete-trigger" data-id="${escapeHtml(item.id)}" type="button">Delete permanently</button></span></article>`).join("") || '<div class="empty-state compact"><p>No dentists configured.</p></div>';
  $("#configuration-providers").innerHTML = data.providers.filter((item) => item.role !== "doctor").map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.staff_code)} · ${escapeHtml(item.role)}</small></span><span class="row-actions"><span class="badge">${item.active ? "active" : "inactive"}</span><button class="button quiet provider-status-trigger" data-id="${escapeHtml(item.id)}" type="button">${item.active ? "Deactivate" : "Reactivate"}</button><button class="button quiet provider-delete-trigger" data-id="${escapeHtml(item.id)}" type="button">Delete permanently</button></span></article>`).join("") || '<div class="empty-state compact"><p>No support providers configured.</p></div>';
  $("#configuration-rooms").innerHTML = data.rooms.map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.code)} · ${escapeHtml(item.category)} · ${escapeHtml(item.turnover_minutes)}m turnover</small></span><span class="badge">${item.active ? "active" : "inactive"}</span></article>`).join("");
  $("#configuration-leave").innerHTML = data.unavailability.map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(formatDateTime(item.starts_at))}–${escapeHtml(formatDateTime(item.ends_at))} · ${escapeHtml(item.reason_code.replaceAll("_", " "))}</small></span></article>`).join("") || '<div class="empty-state compact"><p>No upcoming leave recorded.</p></div>';
  $("#configuration-users").innerHTML = data.users.map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.role === "clinician" ? "Dentist / doctor" : item.role)}${item.linked_dentist_name ? ` · linked to ${escapeHtml(item.linked_dentist_name)}` : ""}</small></span><span class="row-actions"><span class="badge">${item.active ? "active" : "inactive"}</span>${item.id === state.user?.id ? "" : `<button class="button quiet user-status-trigger" data-id="${escapeHtml(item.id)}" type="button">${item.active ? "Deactivate" : "Reactivate"}</button>`}</span></article>`).join("");
  $("#doctor-procedure-options").innerHTML = data.procedures.filter((item) => item.active).map((item) => `<label class="check-field"><input class="doctor-procedure-code" type="checkbox" value="${escapeHtml(item.code)}"><span>${escapeHtml(item.name)}</span></label>`).join("");
  const providerOptions = data.providers.filter((item) => item.active).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.display_name)} · ${escapeHtml(item.role)}</option>`).join("");
  $("#leave-provider").innerHTML = providerOptions;
  $("#shift-provider").innerHTML = providerOptions;
  $("#shift-cover-for").innerHTML = '<option value="">Not coverage</option>' + providerOptions;
  $("#capacity-doctor").innerHTML = doctors.map((item) => `<option value="${escapeHtml(item.doctor_id)}" data-capacity="${escapeHtml(item.max_active_rooms)}">${escapeHtml(item.display_name)}</option>`).join("");
  $("#preference-provider").innerHTML = doctors.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.display_name)}</option>`).join("");
  const procedureOptions = data.procedures.map((item) => `<option value="${escapeHtml(item.code)}">${escapeHtml(item.name)}</option>`).join("");
  $("#preference-procedure").innerHTML = procedureOptions;
  $("#policy-procedure").innerHTML = procedureOptions;
  $("#requirement-procedure").innerHTML = procedureOptions;
  $("#configuration-shifts").innerHTML = data.shifts.map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.shift_date)} · ${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.status)}${item.local_start ? ` · ${escapeHtml(item.local_start)}–${escapeHtml(item.local_end)}` : ""}${item.covering_for_name ? ` · for ${escapeHtml(item.covering_for_name)}` : ""}</small></span></article>`).join("") || '<div class="empty-state compact"><p>No rota overrides.</p></div>';
  $("#configuration-equipment").innerHTML = data.equipment.map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.code)} · ${escapeHtml(item.quantity)} units</small></span></article>`).join("") || '<div class="empty-state compact"><p>No equipment configured.</p></div>';
  $("#requirement-equipment").innerHTML = data.equipment.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} · ${escapeHtml(item.quantity)} available</option>`).join("");
  $("#reserved-block-doctor").innerHTML = doctors.map((item) => `<option value="${escapeHtml(item.doctor_id)}">${escapeHtml(item.display_name)}</option>`).join("");
  $("#reserved-block-procedure").innerHTML = procedureOptions;
  $("#reserved-block-room").innerHTML = '<option value="">No room reserved</option>' + data.rooms.filter((item) => item.active).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("");
  $("#reserved-block-equipment").innerHTML = '<option value="">No equipment reserved</option>' + data.equipment.filter((item) => item.active).flatMap((item) => Array.from({ length: item.quantity }, (_, index) => `<option value="${escapeHtml(item.id)}:${index + 1}">${escapeHtml(item.name)} · unit ${index + 1}</option>`)).join("");
  $("#new-user-provider").innerHTML = '<option value="">No linked dentist</option>' + doctors.filter((item) => item.active && item.doctor_active).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.display_name)}</option>`).join("");
  updateUserProviderVisibility();
  $("#configuration-doctors").querySelectorAll(".doctor-status-trigger").forEach((button) => button.addEventListener("click", () => openDoctorStatus(button.dataset.id)));
  $("#configuration-providers").querySelectorAll(".provider-status-trigger").forEach((button) => button.addEventListener("click", () => openProviderStatus(button.dataset.id)));
  $$(".provider-delete-trigger").forEach((button) => button.addEventListener("click", () => openProviderDeletion(button.dataset.id)));
  $("#configuration-users").querySelectorAll(".user-status-trigger").forEach((button) => button.addEventListener("click", () => openUserStatus(button.dataset.id)));
  renderReservedBlocks();
  $("#configuration-closures").innerHTML = data.closures.map((item) => `<article class="resource-item"><span><strong>${escapeHtml(item.reason_code.replaceAll("_", " "))}</strong><small>${escapeHtml(formatDateTime(item.starts_at))}–${escapeHtml(formatDateTime(item.ends_at))}</small></span></article>`).join("") || '<div class="empty-state compact"><p>No upcoming closures.</p></div>';
  renderProcedurePolicy();
  updateCapacityValue();
  updatePreferenceValue();
  updateEquipmentRequirementValue();
  await loadCalibration();
}

function renderReservedBlocks() {
  const container = $("#configuration-reserved-blocks");
  const blocks = state.reservedBlocks.filter((item) => item.status === "active");
  container.innerHTML = blocks.map((item) => `<article class="resource-item reserved-block-item"><span><strong>${escapeHtml(formatDateTime(item.starts_at))}–${escapeHtml(formatTime(item.ends_at))}</strong><small>${escapeHtml(item.doctor_name)} · ${escapeHtml(item.procedure_name)}${item.room_name ? ` · ${escapeHtml(item.room_name)}` : ""}${item.equipment_name ? ` · ${escapeHtml(item.equipment_name)} unit ${escapeHtml(item.equipment_unit_number)}` : ""}${item.release_at ? ` · releases ${escapeHtml(formatDateTime(item.release_at))}` : ""}</small></span><button class="button quiet reserved-block-release" data-id="${escapeHtml(item.id)}" type="button">Release</button></article>`).join("") || '<div class="empty-state compact"><p>No active doctor procedure blocks.</p></div>';
  container.querySelectorAll(".reserved-block-release").forEach((button) => button.addEventListener("click", () => openReservedBlockRelease(button.dataset.id)));
}

async function createReservedBlock(event) {
  event.preventDefault();
  const button = event.submitter;
  const equipment = $("#reserved-block-equipment").value.split(":");
  loading(button, true);
  try {
    const result = await api("/api/configuration/reserved-blocks", { method: "POST", body: JSON.stringify({
      doctor_id: $("#reserved-block-doctor").value,
      procedure_code: $("#reserved-block-procedure").value,
      starts_at: practiceLocalToIso($("#reserved-block-start").value),
      ends_at: practiceLocalToIso($("#reserved-block-end").value),
      room_id: $("#reserved-block-room").value || null,
      equipment_id: equipment.length === 2 ? equipment[0] : null,
      equipment_unit_number: equipment.length === 2 ? Number(equipment[1]) : null,
      release_at: $("#reserved-block-release-at").value ? practiceLocalToIso($("#reserved-block-release-at").value) : null,
      repeat_weekly_until: $("#reserved-block-repeat-until").value || null,
      reason: $("#reserved-block-reason").value,
    }) });
    success(`${result.count} doctor procedure block${result.count === 1 ? "" : "s"} created`, "Only the matching doctor and procedure may use this protected time unless an exact override is authorized.");
    event.target.reset();
    closeEditor(event.target);
    state.calendarLoaded = false;
    await loadConfiguration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function openReservedBlockRelease(id) {
  const block = state.reservedBlocks.find((item) => item.id === id);
  if (!block) return;
  state.releaseReservedBlockId = id;
  $("#reserved-block-release-summary").textContent = `${formatDateTime(block.starts_at)}–${formatTime(block.ends_at)} · ${block.doctor_name} · ${block.procedure_name}`;
  $("#reserved-block-release-reason").value = "";
  $("#reserved-block-release-dialog").showModal();
}

async function releaseReservedBlock(event) {
  event.preventDefault();
  const button = event.submitter;
  loading(button, true);
  try {
    await api(`/api/configuration/reserved-blocks/${state.releaseReservedBlockId}/release`, { method: "POST", body: JSON.stringify({ reason: $("#reserved-block-release-reason").value }) });
    $("#reserved-block-release-dialog").close();
    success("Reserved block released", "Future searches may use the capacity; the block and release remain in audit history.");
    state.calendarLoaded = false;
    await loadConfiguration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function updateCapacityValue() {
  $("#capacity-value").value = $("#capacity-doctor").selectedOptions[0]?.dataset.capacity || 3;
}

function updatePreferenceValue() {
  const match = state.configuration?.preferences.find((item) => item.provider_id === $("#preference-provider").value && item.procedure_code === $("#preference-procedure").value);
  $("#preference-value").value = match?.preference ?? 0;
}

function updateEquipmentRequirementValue() {
  const match = state.configuration?.equipment_requirements.find((item) => item.equipment_id === $("#requirement-equipment").value && item.procedure_code === $("#requirement-procedure").value);
  $("#requirement-quantity").value = match?.quantity ?? 0;
}

async function runSettingsMutation(event, request, title, detail) {
  event.preventDefault();
  const button = event.submitter;
  loading(button, true);
  try {
    await request();
    success(title, detail);
    event.target.reset();
    closeEditor(event.target);
    await loadConfiguration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function addProvider(event) { return runSettingsMutation(event, () => api("/api/configuration/providers", { method: "POST", body: JSON.stringify({ staff_code: $("#provider-code").value, display_name: $("#provider-name").value, role: $("#provider-role").value }) }), "Provider added", "The provider is available to future scheduling searches according to configured hours."); }
function addDoctor(event) {
  const procedureCodes = $$(".doctor-procedure-code:checked").map((input) => input.value);
  if (!procedureCodes.length) {
    event.preventDefault();
    toast("Select at least one clinician-approved procedure.", true);
    return null;
  }
  return runSettingsMutation(event, () => api("/api/configuration/doctors", { method: "POST", body: JSON.stringify({
    staff_code: $("#doctor-code").value,
    display_name: $("#doctor-name").value,
    specialty: $("#doctor-specialty").value,
    max_active_rooms: Number($("#doctor-capacity").value),
    procedure_codes: procedureCodes,
  }) }), "Dentist added", "The dentist is active with approved qualifications and default weekday hours. Review availability before scheduling.");
}

function updateDoctorStatusApproval() {
  const target = state.doctorStatusTarget;
  if (!target) return;
  const futureApproved = target.nextActive || !target.impact.future_appointment_count || $("#doctor-future-acknowledgement").checked;
  const blocksApproved = target.nextActive || !target.impact.active_block_count || $("#doctor-release-blocks").checked;
  $("#apply-doctor-status-button").disabled = !(futureApproved && blocksApproved);
}

async function openDoctorStatus(doctorId) {
  const provider = state.configuration.providers.find((item) => item.doctor_id === doctorId);
  if (!provider) return;
  try {
    const impact = await api(`/api/configuration/doctors/${doctorId}/impact`);
    const nextActive = !(provider.active && provider.doctor_active);
    state.doctorStatusTarget = { doctorId, provider, impact, nextActive };
    $("#doctor-status-title").textContent = `${nextActive ? "Reactivate" : "Deactivate"} dentist`;
    $("#doctor-status-summary").textContent = `${provider.display_name} · ${provider.staff_code}`;
    $("#doctor-status-impact").innerHTML = nextActive
      ? "<strong>Reactivation effect</strong><span>The dentist returns to future scheduling searches. Prior blocks are not recreated and linked accounts remain inactive until separately reactivated.</span>"
      : `<strong>Impact review</strong><span>${escapeHtml(impact.future_appointment_count)} future locked appointment(s) remain unchanged · ${escapeHtml(impact.active_block_count)} protected block(s) require release · ${escapeHtml(impact.active_linked_account_count)} linked active account(s) will be disabled.</span>`;
    $("#doctor-future-ack-row").hidden = nextActive || !impact.future_appointment_count;
    $("#doctor-release-blocks-row").hidden = nextActive || !impact.active_block_count;
    $("#doctor-future-acknowledgement").checked = false;
    $("#doctor-release-blocks").checked = false;
    $("#doctor-status-reason").value = "";
    const button = $("#apply-doctor-status-button");
    button.textContent = `${nextActive ? "Reactivate" : "Deactivate"} dentist`;
    button.className = `button ${nextActive ? "primary" : "danger"}`;
    updateDoctorStatusApproval();
    $("#doctor-status-dialog").showModal();
  } catch (error) {
    toast(error.message, true);
  }
}

async function applyDoctorStatus(event) {
  event.preventDefault();
  const target = state.doctorStatusTarget;
  if (!target) return;
  const button = event.submitter;
  loading(button, true);
  try {
    await api(`/api/configuration/doctors/${target.doctorId}/status`, { method: "PUT", body: JSON.stringify({
      active: target.nextActive,
      reason: $("#doctor-status-reason").value,
      acknowledge_future_appointments: $("#doctor-future-acknowledgement").checked,
      release_active_blocks: $("#doctor-release-blocks").checked,
    }) });
    $("#doctor-status-dialog").close();
    success(`Dentist ${target.nextActive ? "reactivated" : "deactivated"}`, target.nextActive ? "The dentist can appear in future searches. Linked accounts must be reactivated separately." : "New searches exclude the dentist. Existing appointments remain locked and unchanged.");
    state.calendarLoaded = false;
    await loadConfiguration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function updateProviderStatusApproval() {
  const target = state.providerStatusTarget;
  if (!target) return;
  $("#apply-provider-status-button").disabled = !(
    target.nextActive || !target.impact.blocking.appointment_phase_count || $("#provider-future-acknowledgement").checked
  );
}

async function openProviderStatus(providerId) {
  const provider = state.configuration.providers.find((item) => item.id === providerId);
  if (!provider) return;
  try {
    const impact = await api(`/api/configuration/providers/${providerId}/deletion-impact`);
    const nextActive = !provider.active;
    state.providerStatusTarget = { providerId, provider, impact, nextActive };
    $("#provider-status-title").textContent = `${nextActive ? "Reactivate" : "Deactivate"} provider`;
    $("#provider-status-summary").textContent = `${provider.display_name} · ${provider.role}`;
    $("#provider-status-impact").innerHTML = nextActive
      ? "<strong>Reactivation effect</strong><span>The provider returns to future scheduling searches.</span>"
      : `<strong>Impact review</strong><span>${escapeHtml(impact.blocking.appointment_phase_count)} appointment phase record(s) are retained. Existing future appointments never move.</span>`;
    $("#provider-future-ack-row").hidden = nextActive || !impact.blocking.appointment_phase_count;
    $("#provider-future-acknowledgement").checked = false;
    $("#provider-status-reason").value = "";
    const button = $("#apply-provider-status-button");
    button.textContent = `${nextActive ? "Reactivate" : "Deactivate"} provider`;
    button.className = `button ${nextActive ? "primary" : "danger"}`;
    updateProviderStatusApproval();
    $("#provider-status-dialog").showModal();
  } catch (error) {
    toast(error.message, true);
  }
}

async function applyProviderStatus(event) {
  event.preventDefault();
  const target = state.providerStatusTarget;
  if (!target) return;
  const button = event.submitter;
  loading(button, true);
  try {
    await api(`/api/configuration/providers/${target.providerId}/status`, { method: "PUT", body: JSON.stringify({
      active: target.nextActive,
      reason: $("#provider-status-reason").value,
      acknowledge_future_appointments: $("#provider-future-acknowledgement").checked,
    }) });
    $("#provider-status-dialog").close();
    success(`Provider ${target.nextActive ? "reactivated" : "deactivated"}`, target.nextActive ? "The provider can appear in future searches." : "Existing appointments remain locked and unchanged.");
    state.calendarLoaded = false;
    await loadConfiguration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

async function openProviderDeletion(providerId) {
  const provider = state.configuration.providers.find((item) => item.id === providerId);
  if (!provider) return;
  try {
    const impact = await api(`/api/configuration/providers/${providerId}/deletion-impact`);
    state.providerDeletionTarget = { providerId, provider, impact };
    $("#provider-delete-summary").textContent = `${provider.display_name} · ${provider.role}`;
    const blockers = Object.entries(impact.blocking).filter(([, count]) => count).map(([key, count]) => `${count} ${key.replaceAll("_", " ")}`);
    $("#provider-delete-impact").innerHTML = impact.blocking_total
      ? `<strong>Deletion blocked</strong><span>${escapeHtml(blockers.join(" · "))}. Preserve this record as inactive.</span>`
      : `<strong>Eligible after deactivation</strong><span>${escapeHtml(impact.setup_total)} related setup record(s) will be permanently deleted with this staff record.</span>`;
    $("#provider-delete-reason").value = "";
    $("#provider-delete-confirmation").checked = false;
    updateProviderDeletionApproval();
    $("#provider-delete-dialog").showModal();
  } catch (error) {
    toast(error.message, true);
  }
}

function updateProviderDeletionApproval() {
  const target = state.providerDeletionTarget;
  if (!target) return;
  $("#apply-provider-delete-button").disabled = Boolean(
    target.impact.blocking_total || target.impact.active || target.impact.doctor_active || !$("#provider-delete-confirmation").checked
  );
}

async function applyProviderDeletion(event) {
  event.preventDefault();
  const target = state.providerDeletionTarget;
  if (!target) return;
  if (!$("#provider-delete-confirmation").checked) {
    toast("Confirm permanent deletion before continuing.", true);
    return;
  }
  const button = event.submitter;
  loading(button, true);
  try {
    await api(`/api/configuration/providers/${target.providerId}`, { method: "DELETE", body: JSON.stringify({
      reason: $("#provider-delete-reason").value,
      confirm_permanent_delete: true,
    }) });
    $("#provider-delete-dialog").close();
    success("Staff record permanently deleted", "Eligible related configuration was removed. Audit history remains append-only.");
    state.calendarLoaded = false;
    await loadConfiguration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function updateUserProviderVisibility() {
  const isDentist = $("#new-user-role").value === "clinician";
  $("#new-user-dentist-row").hidden = !isDentist;
  if (!isDentist) $("#new-user-provider").value = "";
}

function openUserStatus(userId) {
  const account = state.configuration.users.find((item) => item.id === userId);
  if (!account) return;
  const nextActive = !account.active;
  state.userStatusTarget = { userId, account, nextActive };
  $("#user-status-title").textContent = `${nextActive ? "Reactivate" : "Deactivate"} account`;
  $("#user-status-summary").textContent = `${account.display_name} · ${account.role === "clinician" ? "Dentist / doctor" : account.role}`;
  $("#user-status-reason").value = "";
  const button = $("#apply-user-status-button");
  button.textContent = `${nextActive ? "Reactivate" : "Deactivate"} account`;
  button.className = `button ${nextActive ? "primary" : "danger"}`;
  $("#user-status-dialog").showModal();
}

async function applyUserStatus(event) {
  event.preventDefault();
  const target = state.userStatusTarget;
  if (!target) return;
  const button = event.submitter;
  loading(button, true);
  try {
    await api(`/api/configuration/users/${target.userId}/status`, { method: "PUT", body: JSON.stringify({ active: target.nextActive, reason: $("#user-status-reason").value }) });
    $("#user-status-dialog").close();
    success(`Account ${target.nextActive ? "reactivated" : "deactivated"}`, target.nextActive ? "The user can sign in again." : "Active sessions were revoked and audit history was preserved.");
    await loadConfiguration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function addRoom(event) { return runSettingsMutation(event, () => api("/api/configuration/rooms", { method: "POST", body: JSON.stringify({ code: $("#room-code").value, name: $("#room-name").value, category: $("#room-category").value, turnover_minutes: 10 }) }), "Operatory added", "Future searches can use this room where procedure policy permits."); }
function addLeave(event) { return runSettingsMutation(event, () => api("/api/configuration/unavailability", { method: "POST", body: JSON.stringify({ provider_id: $("#leave-provider").value, starts_at: practiceLocalToIso($("#leave-start").value), ends_at: practiceLocalToIso($("#leave-end").value), reason_code: $("#leave-reason").value }) }), "Provider time blocked", "Future searches will respect this dated unavailability."); }
function addUser(event) { return runSettingsMutation(event, () => api("/api/configuration/users", { method: "POST", body: JSON.stringify({ username: $("#new-username").value, display_name: $("#new-user-name").value, role: $("#new-user-role").value, password: $("#new-user-password").value, provider_id: $("#new-user-role").value === "clinician" ? ($("#new-user-provider").value || null) : null }) }), "Unique account created", "The user can sign in with the assigned role and temporary password."); }

function renderProcedurePolicy() {
  const code = $("#policy-procedure").value || state.configuration.procedures[0]?.code;
  if (!code) return;
  const procedure = state.configuration.procedures.find((item) => item.code === code);
  const phases = state.configuration.phases.filter((item) => item.procedure_code === code);
  $("#policy-name").value = procedure.name;
  $("#policy-production").value = procedure.production_cents;
  $("#phase-editor").innerHTML = phases.map(phaseRow).join("");
  bindPhaseRemove();
}

function phaseRow(phase = { code: "new-phase", name: "New phase", role: "assistant", standard_minutes: 10, complex_minutes: 15 }) {
  return `<div class="phase-editor-row"><input class="phase-code" minlength="1" maxlength="80" value="${escapeHtml(phase.code)}" aria-label="Phase code" required><input class="phase-name" minlength="2" maxlength="160" value="${escapeHtml(phase.name)}" aria-label="Phase name" required><select class="phase-role" aria-label="Required role">${["doctor", "hygienist", "assistant", "room"].map((role) => `<option value="${role}" ${phase.role === role ? "selected" : ""}>${role}</option>`).join("")}</select><input class="phase-standard" type="number" min="5" max="480" step="5" value="${escapeHtml(phase.standard_minutes)}" aria-label="Standard minutes" required><input class="phase-complex" type="number" min="5" max="600" step="5" value="${escapeHtml(phase.complex_minutes)}" aria-label="Complex minutes" required><button class="icon-button remove-phase" type="button" aria-label="Remove phase">×</button></div>`;
}

function bindPhaseRemove() {
  $$("#phase-editor .remove-phase").forEach((button) => button.addEventListener("click", () => button.closest(".phase-editor-row").remove()));
}

function saveCapacity(event) { return runSettingsMutation(event, () => api(`/api/configuration/doctors/${$("#capacity-doctor").value}/capacity`, { method: "PUT", body: JSON.stringify({ max_active_rooms: Number($("#capacity-value").value) }) }), "Supervision limit saved", "Future searches will respect the approved active-room limit."); }
function savePreference(event) { return runSettingsMutation(event, () => api("/api/configuration/preferences", { method: "PUT", body: JSON.stringify({ provider_id: $("#preference-provider").value, procedure_code: $("#preference-procedure").value, preference: Number($("#preference-value").value) }) }), "Procedure preference saved", "This ranking preference cannot bypass feasibility constraints."); }
function saveShift(event) {
  const status = $("#shift-status").value;
  return runSettingsMutation(event, () => api("/api/configuration/shifts", { method: "PUT", body: JSON.stringify({ provider_id: $("#shift-provider").value, shift_date: $("#shift-date").value, status, local_start: status === "off" ? null : $("#shift-start").value, local_end: status === "off" ? null : $("#shift-end").value, covering_for_provider_id: status === "cover" ? $("#shift-cover-for").value : null, notes: "" }) }), "Daily override saved", "Future searches will use the dated rota override.");
}

async function saveProcedurePolicy(event) {
  event.preventDefault();
  const button = event.submitter;
  const phases = $$("#phase-editor .phase-editor-row").map((row) => ({
    code: row.querySelector(".phase-code").value,
    name: row.querySelector(".phase-name").value,
    role: row.querySelector(".phase-role").value,
    standard_minutes: Number(row.querySelector(".phase-standard").value),
    complex_minutes: Number(row.querySelector(".phase-complex").value),
  }));
  if (!phases.length) { toast("Add at least one phase.", true); return; }
  loading(button, true);
  try {
    await api(`/api/configuration/procedures/${encodeURIComponent($("#policy-procedure").value)}`, { method: "PUT", body: JSON.stringify({ name: $("#policy-name").value, production_cents: Number($("#policy-production").value), phases }) });
    success("Procedure policy saved", "The approved policy affects future searches only; existing locked visits remain unchanged.");
    state.catalog = await api("/api/catalog");
    closeEditor(event.target);
    await loadConfiguration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function saveEquipment(event) { return runSettingsMutation(event, () => api("/api/configuration/equipment", { method: "POST", body: JSON.stringify({ code: $("#equipment-code").value, name: $("#equipment-name").value, quantity: Number($("#equipment-quantity").value) }) }), "Equipment capacity saved", "Future searches will respect the configured number of units."); }
function saveEquipmentRequirement(event) { return runSettingsMutation(event, () => api("/api/configuration/equipment-requirements", { method: "PUT", body: JSON.stringify({ procedure_code: $("#requirement-procedure").value, equipment_id: $("#requirement-equipment").value, quantity: Number($("#requirement-quantity").value) }) }), "Procedure requirement saved", "Future searches will reserve the required equipment units."); }
function saveClosure(event) { return runSettingsMutation(event, () => api("/api/configuration/closures", { method: "POST", body: JSON.stringify({ starts_at: practiceLocalToIso($("#closure-start").value), ends_at: practiceLocalToIso($("#closure-end").value), reason_code: $("#closure-reason").value }) }), "Practice closure saved", "Future searches will avoid the closed interval."); }

function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') { cell += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) { row.push(cell.trim()); cell = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell.trim());
      if (row.some((value) => value !== "")) rows.push(row);
      row = []; cell = "";
    } else cell += char;
  }
  row.push(cell.trim());
  if (row.some((value) => value !== "")) rows.push(row);
  if (rows.length < 2) throw new Error("CSV needs a header and at least one row.");
  const headers = rows[0].map((value) => value.toLowerCase());
  const prohibited = ["patient_name", "mrn", "date_of_birth", "phone", "address"];
  if (headers.some((header) => prohibited.includes(header))) throw new Error("Patient identifiers are prohibited in calibration imports.");
  const required = ["procedure_code", "service_date", "scheduled_minutes", "actual_minutes", "outcome"];
  if (required.some((header) => !headers.includes(header))) throw new Error(`Required columns: ${required.join(", ")}`);
  return rows.slice(1).map((values) => {
    const item = Object.fromEntries(headers.map((header, index) => [header, values[index] || ""]));
    return { procedure_code: item.procedure_code, doctor_staff_code: item.doctor_staff_code || null, service_date: item.service_date, scheduled_minutes: Number(item.scheduled_minutes), actual_minutes: item.actual_minutes ? Number(item.actual_minutes) : null, outcome: item.outcome };
  });
}

async function importCalibration(event) {
  event.preventDefault();
  const button = event.submitter;
  loading(button, true);
  try {
    const rows = parseCsv(await $("#calibration-file").files[0].text());
    const result = await api("/api/calibration/import", { method: "POST", body: JSON.stringify({ source_name: $("#calibration-source").value, rows }) });
    success("De-identified history imported", result.recommendations_ready ? `${result.recommendations_ready} recommendation(s) await approval.` : "Reference defaults remain active while evidence accumulates.");
    event.target.reset();
    closeEditor(event.target);
    await loadCalibration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

async function loadCalibration() {
  const data = await api("/api/calibration");
  $("#calibration-results").innerHTML = `<article class="resource-item"><span><strong>Ready out of the box</strong><small>Versioned reference defaults are active. Local history is optional and can only propose future changes after ${escapeHtml(data.minimum_sample_size)} usable samples.</small></span><span class="badge">No data required</span></article>` + data.procedures.map((item) => {
    const ready = item.calibration_status === "recommendation_ready";
    const approved = item.calibration_status === "approved";
    const detail = ready || approved ? `${escapeHtml(item.observed_sample_size)} samples · active ${escapeHtml(item.active_standard_minutes)}m/${escapeHtml(item.active_complex_minutes)}m · proposed ${escapeHtml(item.standard_minutes)}m/${escapeHtml(item.complex_minutes)}m · ${approved ? "approved" : "awaiting approval"}` : item.calibration_status === "collecting" ? `${escapeHtml(item.observed_sample_size)} optional samples · ${escapeHtml(item.samples_needed)} more before a recommendation` : "Reference defaults active";
    return `<article class="resource-item"><span><strong>${escapeHtml(item.name)}</strong><small>${detail}</small></span>${ready ? `<button class="button secondary calibration-apply" data-code="${escapeHtml(item.procedure_code)}" data-name="${escapeHtml(item.name)}" type="button">Review recommendation</button>` : `<span class="badge">${approved ? "Approved" : item.calibration_status === "collecting" ? "Collecting" : "Default"}</span>`}</article>`;
  }).join("");
  $$(".calibration-apply").forEach((button) => button.addEventListener("click", () => openCalibrationApproval(button)));
}

function openCalibrationApproval(button) {
  state.calibrationProcedureCode = button.dataset.code;
  $("#calibration-approval-summary").textContent = `Review and approve the staged recommendation for ${button.dataset.name}.`;
  $("#calibration-approval-reason").value = "";
  $("#calibration-approval-dialog").showModal();
}

async function applyCalibration(event) {
  event.preventDefault();
  const button = event.submitter;
  loading(button, true);
  try {
    await api(`/api/calibration/${encodeURIComponent(state.calibrationProcedureCode)}/apply`, { method: "POST", body: JSON.stringify({ approval_reason: $("#calibration-approval-reason").value }) });
    $("#calibration-approval-dialog").close();
    success("Duration recommendation applied", "The versioned change affects future scheduling only.");
    await loadCalibration();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

async function loadAudit(render = true) {
  const data = await api("/api/audit");
  state.auditEvents = data.events;
  if (!render) return;
  const categories = [...new Set(data.events.map((item) => item.event_type.split(".")[0]))].sort();
  const outcomes = [...new Set(data.events.map((item) => item.outcome))].sort();
  $("#audit-category").innerHTML = '<option value="">All categories</option>' + categories.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item.replaceAll("_", " "))}</option>`).join("");
  $("#audit-outcome").innerHTML = '<option value="">All outcomes</option>' + outcomes.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
  renderAudit();
}

function renderAudit() {
  const query = $("#audit-filter").value.trim().toLowerCase();
  const category = $("#audit-category").value;
  const outcome = $("#audit-outcome").value;
  const events = state.auditEvents.filter((item) => {
    const searchable = `${item.event_type} ${item.actor_name} ${item.entity_type} ${item.outcome}`.toLowerCase();
    return (!query || searchable.includes(query)) && (!category || item.event_type.startsWith(`${category}.`)) && (!outcome || item.outcome === outcome);
  });
  $("#audit-list").innerHTML = events.map((item) => `<article class="audit-row"><time>${escapeHtml(formatDateTime(item.occurred_at))}</time><strong>${escapeHtml(item.event_type.replaceAll(".", " · ").replaceAll("_", " "))}</strong><small>${escapeHtml(item.actor_name)} · ${escapeHtml(item.entity_type)}</small><span class="outcome">${escapeHtml(item.outcome)}</span></article>`).join("") || '<div class="empty-state"><p>No events match these filters.</p></div>';
}

function openReschedule(id) {
  state.rescheduleAppointmentId = id;
  state.selectedRescheduleRecommendation = null;
  $("#reschedule-options").innerHTML = "";
  $("#reschedule-reason").value = "";
  $("#reschedule-approval").checked = false;
  $("#apply-reschedule-button").disabled = true;
  $("#reschedule-dialog").showModal();
}

async function findRescheduleOptions() {
  const button = $("#find-reschedule-button");
  loading(button, true);
  try {
    const data = await api(`/api/appointments/${state.rescheduleAppointmentId}/reschedule-options`, { method: "POST", body: JSON.stringify({ date_from: $("#reschedule-from").value, date_to: $("#reschedule-to").value, time_from: $("#reschedule-time-from").value, time_to: $("#reschedule-time-to").value, preferred_doctor_id: null }) });
    const container = $("#reschedule-options");
    container.innerHTML = data.candidates.map((candidate) => `<button type="button" class="option-button" data-id="${escapeHtml(candidate.id)}"><span><strong>${escapeHtml(formatDateTime(candidate.starts_at))}</strong><br><small>${escapeHtml(candidate.doctor_name)} · ${escapeHtml(candidate.room_name)}</small></span><span>${escapeHtml(formatTime(candidate.ends_at))}</span></button>`).join("") || '<div class="empty-state compact"><p>No valid replacement found.</p></div>';
    container.querySelectorAll(".option-button").forEach((option) => option.addEventListener("click", () => {
      container.querySelectorAll(".option-button").forEach((item) => item.classList.remove("selected"));
      option.classList.add("selected");
      state.selectedRescheduleRecommendation = option.dataset.id;
      updateRescheduleApproval();
    }));
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function updateRescheduleApproval() {
  $("#apply-reschedule-button").disabled = !(state.selectedRescheduleRecommendation && $("#reschedule-approval").checked && $("#reschedule-reason").value.trim().length >= 10);
}

async function applyReschedule(event) {
  event.preventDefault();
  const button = $("#apply-reschedule-button");
  loading(button, true);
  try {
    await api(`/api/appointments/${state.rescheduleAppointmentId}/reschedule`, { method: "POST", body: JSON.stringify({ recommendation_id: state.selectedRescheduleRecommendation, reason: $("#reschedule-reason").value }) });
    $("#reschedule-dialog").close();
    success("Authorized replacement recorded", "The old slot was released and the exact approved replacement was locked in one transaction.");
    state.appointments = [];
    state.calendarLoaded = false;
    await Promise.all([state.route === "operations" ? loadOperations() : Promise.resolve(), state.route === "calendar" ? loadCalendar(true) : Promise.resolve()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function openStatus(button) {
  state.statusAppointmentId = button.dataset.id;
  const completed = $('#status-value option[value="completed"]');
  const noShow = $('#status-value option[value="no_show"]');
  completed.disabled = button.dataset.seated !== "true";
  noShow.disabled = button.dataset.canNoShow !== "true";
  $("#status-value").value = !completed.disabled ? "completed" : !noShow.disabled ? "no_show" : "cancelled";
  $("#status-reason").value = "";
  $("#status-dialog").showModal();
}

async function applyStatus(event) {
  event.preventDefault();
  const button = $("#apply-status-button");
  loading(button, true);
  try {
    const data = await api(`/api/appointments/${state.statusAppointmentId}/status`, { method: "POST", body: JSON.stringify({ status: $("#status-value").value, reason: $("#status-reason").value }) });
    $("#status-dialog").close();
    success("Appointment outcome recorded", data.vacancy_recovery_eligible ? "The future opening can now be recovered one approved move at a time." : data.waitlist_matches ? `${data.waitlist_matches} waitlist patient(s) may match the released opening.` : "Capacity, analytics, and audit history were updated.");
    state.appointments = [];
    state.calendarLoaded = false;
    if (state.route === "operations") await loadOperations();
    if (state.route === "calendar") await loadCalendar(true);
    if (data.vacancy_recovery_eligible) openVacancyRecovery(data);
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function openVacancyRecovery(statusResult) {
  state.vacancyRecoverySourceAppointmentId = statusResult.appointment_id;
  state.vacancyRecoveryChain = null;
  state.vacancyRecoveryCandidates = [];
  state.selectedVacancyOffer = null;
  const slot = statusResult.released_slot;
  $("#vacancy-recovery-start-summary").textContent = slot
    ? `${formatDateTime(slot.starts_at)}–${formatTime(slot.ends_at)} is now open.`
    : "The cancelled future slot is now open.";
  $("#vacancy-recovery-start").hidden = false;
  $("#vacancy-recovery-workspace").hidden = true;
  resetVacancyApproval();
  $("#vacancy-recovery-dialog").showModal();
}

async function resumeVacancyRecovery(appointmentId) {
  try {
    const data = await api(`/api/appointments/${appointmentId}/vacancy-recovery`, { method: "POST" });
    state.vacancyRecoverySourceAppointmentId = appointmentId;
    state.vacancyRecoveryChain = data.chain;
    state.vacancyRecoveryCandidates = [];
    resetVacancyApproval();
    $("#vacancy-recovery-start").hidden = true;
    $("#vacancy-recovery-workspace").hidden = false;
    renderVacancyChain();
    renderVacancyCandidates();
    $("#vacancy-recovery-dialog").showModal();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderVacancyChain() {
  const chain = state.vacancyRecoveryChain;
  if (!chain) return;
  const vacancy = chain.current_vacancy;
  $("#vacancy-current-slot").innerHTML = `<strong>${escapeHtml(formatDateTime(vacancy.starts_at))}–${escapeHtml(formatTime(vacancy.ends_at))}</strong><small>${escapeHtml(vacancy.doctor_name)} · ${escapeHtml(vacancy.room_name || "No room")}</small>`;
  $("#vacancy-step-count").textContent = `${chain.step_count} approved move${chain.step_count === 1 ? "" : "s"}`;
  $("#vacancy-recovery-history").innerHTML = chain.steps.map((step) => `<article class="recovery-step"><span class="step-number">${escapeHtml(step.sequence)}</span><span><strong>${escapeHtml(step.patient_name)} · ${escapeHtml(step.procedure_name)}</strong><small>Moved into ${escapeHtml(formatDateTime(step.filled_starts_at))}; released ${escapeHtml(formatDateTime(step.released_starts_at))} · permission: ${escapeHtml(step.permission_method.replaceAll("_", " "))}</small></span></article>`).join("") || '<p class="muted-copy">No appointments have been moved. The cancelled slot is the current vacancy.</p>';
  const active = chain.status === "active";
  $("#find-vacancy-candidates").disabled = !active;
  $("#vacancy-stop-button").disabled = !active;
}

function resetVacancyApproval() {
  state.selectedVacancyOffer = null;
  $("#vacancy-approval").hidden = true;
  $("#vacancy-permission-confirmed").checked = false;
  $("#vacancy-exact-acknowledged").checked = false;
  $("#vacancy-move-reason").value = "";
  $("#apply-vacancy-move").disabled = true;
}

async function beginVacancyRecovery() {
  const button = $("#start-vacancy-recovery");
  loading(button, true);
  try {
    const data = await api(`/api/appointments/${state.vacancyRecoverySourceAppointmentId}/vacancy-recovery`, { method: "POST" });
    state.vacancyRecoveryChain = data.chain;
    $("#vacancy-recovery-start").hidden = true;
    $("#vacancy-recovery-workspace").hidden = false;
    renderVacancyChain();
    await findVacancyCandidates();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
  }
}

function renderVacancyCandidates() {
  const container = $("#vacancy-candidates");
  container.innerHTML = state.vacancyRecoveryCandidates.map((candidate) => `<button type="button" class="option-button vacancy-option" data-offer-id="${escapeHtml(candidate.offer_id)}"><span><strong>${escapeHtml(candidate.patient_name)} · ${escapeHtml(candidate.procedure_name)}</strong><small>Current: ${escapeHtml(formatDateTime(candidate.current_starts_at))}–${escapeHtml(formatTime(candidate.current_ends_at))}<br>Move to: ${escapeHtml(formatDateTime(candidate.proposed_starts_at))}–${escapeHtml(formatTime(candidate.proposed_ends_at))} · ${escapeHtml(candidate.doctor_name)} · ${escapeHtml(candidate.room_name)}</small></span><span class="candidate-flags"><span class="badge">${escapeHtml(Math.round(candidate.advancement_minutes / 60))}h earlier</span>${candidate.earlier_slot_opt_in ? '<span class="badge consented">ASAP opted in</span>' : '<span class="badge permission-needed">Permission needed</span>'}</span></button>`).join("") || '<div class="empty-state compact"><p>No later confirmed appointment can safely use this exact vacancy. You can finish without changing anything else.</p></div>';
  container.querySelectorAll(".vacancy-option").forEach((button) => button.addEventListener("click", () => selectVacancyOffer(button.dataset.offerId)));
}

async function findVacancyCandidates() {
  const button = $("#find-vacancy-candidates");
  loading(button, true);
  resetVacancyApproval();
  try {
    const data = await api(`/api/vacancy-recovery/${state.vacancyRecoveryChain.id}/candidates`, { method: "POST" });
    state.vacancyRecoveryChain = data.chain;
    state.vacancyRecoveryCandidates = data.candidates;
    renderVacancyChain();
    renderVacancyCandidates();
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
    renderVacancyChain();
  }
}

function selectVacancyOffer(offerId) {
  const candidate = state.vacancyRecoveryCandidates.find((item) => item.offer_id === offerId);
  if (!candidate) return;
  state.selectedVacancyOffer = candidate;
  $$(".vacancy-option").forEach((item) => item.classList.toggle("selected", item.dataset.offerId === offerId));
  $("#vacancy-approval-summary").innerHTML = `<strong>Authorize ${escapeHtml(candidate.patient_name)} only</strong><span>${escapeHtml(formatDateTime(candidate.current_starts_at))} → ${escapeHtml(formatDateTime(candidate.proposed_starts_at))}</span>`;
  $("#vacancy-approval").hidden = false;
  $("#vacancy-approval").scrollIntoView({ behavior: "smooth", block: "nearest" });
  updateVacancyApproval();
}

function updateVacancyApproval() {
  $("#apply-vacancy-move").disabled = !(
    state.selectedVacancyOffer
    && $("#vacancy-permission-confirmed").checked
    && $("#vacancy-exact-acknowledged").checked
    && $("#vacancy-move-reason").value.trim().length >= 10
  );
}

async function applyVacancyMove(event) {
  event.preventDefault();
  const button = $("#apply-vacancy-move");
  loading(button, true);
  try {
    const data = await api(`/api/vacancy-recovery/${state.vacancyRecoveryChain.id}/move`, {
      method: "POST",
      body: JSON.stringify({
        offer_id: state.selectedVacancyOffer.offer_id,
        permission_method: $("#vacancy-permission-method").value,
        patient_permission_confirmed: $("#vacancy-permission-confirmed").checked,
        exact_move_acknowledged: $("#vacancy-exact-acknowledged").checked,
        reason: $("#vacancy-move-reason").value,
      }),
    });
    state.vacancyRecoveryChain = data.chain;
    state.vacancyRecoveryCandidates = [];
    resetVacancyApproval();
    renderVacancyChain();
    renderVacancyCandidates();
    state.appointments = [];
    state.calendarLoaded = false;
    success("One approved appointment moved", "Only that patient changed. Its former slot is now the vacancy; choose Find eligible later visits to continue.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
    updateVacancyApproval();
  }
}

async function stopVacancyRecovery(reason = "Staff finished this focused vacancy recovery review") {
  if (!state.vacancyRecoveryChain || state.vacancyRecoveryChain.status !== "active") {
    $("#vacancy-recovery-dialog").close();
    return;
  }
  const button = $("#vacancy-stop-button");
  loading(button, true);
  try {
    const data = await api(`/api/vacancy-recovery/${state.vacancyRecoveryChain.id}/stop`, { method: "POST", body: JSON.stringify({ reason }) });
    state.vacancyRecoveryChain = data.chain;
    $("#vacancy-recovery-dialog").close();
    success("Vacancy recovery finished", `${data.chain.step_count} approved move${data.chain.step_count === 1 ? "" : "s"} recorded. No other appointments changed.`);
    if (state.route === "operations") await loadOperations();
    if (state.route === "calendar") await loadCalendar(true);
  } catch (error) {
    toast(error.message, true);
  } finally {
    loading(button, false);
    renderVacancyChain();
  }
}

function bindEvents() {
  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("#login-error").textContent = "";
    try {
      const data = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username: $("#login-username").value, password: $("#login-password").value }) });
      state.user = data.user;
      showApp();
      await loadApplication();
    } catch (error) {
      $("#login-error").textContent = error.message;
    }
  });
  $("#logout-button").addEventListener("click", async () => { try { await api("/api/auth/logout", { method: "POST" }); } catch (_) {} showLogin(); });
  window.addEventListener("hashchange", () => applyRoute().catch((error) => toast(error.message, true)));
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.route)));
  $$('[data-route-target]').forEach((button) => button.addEventListener("click", () => navigate(button.dataset.routeTarget)));
  $("#page-help-button").addEventListener("click", openHelp);
  $$('[data-dialog-close]').forEach((button) => button.addEventListener("click", () => $(`#${button.dataset.dialogClose}`).close()));
  $("#dismiss-activity").addEventListener("click", () => { $("#activity-banner").hidden = true; });

  $("#patient-search-button").addEventListener("click", searchPatients);
  $("#patient-search").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); searchPatients(); } });
  $("#procedure").addEventListener("change", populateProcedurePreview);
  $("#patient-always-available").addEventListener("change", updatePatientAvailabilityControls);
  $$("[data-next-step]").forEach((button) => button.addEventListener("click", () => { if (validateStep(state.scheduleStep)) { state.maxScheduleStep = Math.max(state.maxScheduleStep, Number(button.dataset.nextStep)); setScheduleStep(button.dataset.nextStep, true); } }));
  $$("[data-previous-step]").forEach((button) => button.addEventListener("click", () => setScheduleStep(button.dataset.previousStep, true)));
  $$("[data-step-target]").forEach((button) => button.addEventListener("click", () => setScheduleStep(button.dataset.stepTarget)));
  $("#schedule-form").addEventListener("submit", searchRecommendations);
  $("#new-schedule-request").addEventListener("click", resetSchedule);
  $("#confirm-form").addEventListener("submit", confirmSlot);

  $("#operations-date").addEventListener("change", () => loadOperations().catch((error) => toast(error.message, true)));
  $("#quick-walkin").addEventListener("click", () => { prepareWalkIn(); navigate("scheduler"); $("#patient-search").focus(); });

  $("#open-waitlist-dialog").addEventListener("click", () => $("#waitlist-add-dialog").showModal());
  $("#waitlist-form").addEventListener("submit", addWaitlist);
  $("#waitlist-filter").addEventListener("input", renderWaitlist);
  $("#waitlist-priority-filter").addEventListener("change", renderWaitlist);
  $("#waitlist-contact-form").addEventListener("submit", recordWaitlistContact);

  $$("[data-calendar-mode]").forEach((button) => button.addEventListener("click", () => { state.calendarMode = button.dataset.calendarMode; renderCalendar(); }));
  $("#previous-month").addEventListener("click", () => { state.calendarMonthOffset = Math.max(0, state.calendarMonthOffset - 1); renderCalendar(); });
  $("#next-month").addEventListener("click", () => { state.calendarMonthOffset = Math.min(11, state.calendarMonthOffset + 1); renderCalendar(); });
  $("#close-day-detail").addEventListener("click", () => { $("#day-detail").hidden = true; });

  $("#analytics-from").addEventListener("change", () => loadAnalytics().catch((error) => toast(error.message, true)));
  $("#analytics-to").addEventListener("change", () => loadAnalytics().catch((error) => toast(error.message, true)));

  $("#simulation-upload-form").addEventListener("submit", previewSimulation);
  $("#simulation-file").addEventListener("change", () => {
    state.simulationFile = $("#simulation-file").files[0] || null;
    state.simulationPreview = null;
    state.simulationRun = null;
    $("#simulation-preview-empty").hidden = false;
    $("#simulation-preview-content").hidden = true;
    $("#simulation-results-panel").hidden = true;
  });
  $("#simulation-run-button").addEventListener("click", runSimulation);
  $("#simulation-clear-button").addEventListener("click", clearSimulation);
  $("#simulation-download-results").addEventListener("click", downloadSimulationResults);
  $("#simulation-download-report").addEventListener("click", downloadSimulationReport);

  $$("[data-settings-route]").forEach((button) => button.addEventListener("click", () => setSettingsSection(button.dataset.settingsRoute)));
  $("#doctor-form").addEventListener("submit", addDoctor);
  $("#provider-form").addEventListener("submit", addProvider);
  $("#room-form").addEventListener("submit", addRoom);
  $("#leave-form").addEventListener("submit", addLeave);
  $("#reserved-block-form").addEventListener("submit", createReservedBlock);
  $("#reserved-block-release-form").addEventListener("submit", releaseReservedBlock);
  $("#user-form").addEventListener("submit", addUser);
  $("#new-user-role").addEventListener("change", updateUserProviderVisibility);
  $("#doctor-status-form").addEventListener("submit", applyDoctorStatus);
  $("#doctor-future-acknowledgement").addEventListener("change", updateDoctorStatusApproval);
  $("#doctor-release-blocks").addEventListener("change", updateDoctorStatusApproval);
  $("#user-status-form").addEventListener("submit", applyUserStatus);
  $("#provider-status-form").addEventListener("submit", applyProviderStatus);
  $("#provider-future-acknowledgement").addEventListener("change", updateProviderStatusApproval);
  $("#provider-delete-form").addEventListener("submit", applyProviderDeletion);
  $("#provider-delete-confirmation").addEventListener("change", updateProviderDeletionApproval);
  $("#capacity-form").addEventListener("submit", saveCapacity);
  $("#capacity-doctor").addEventListener("change", updateCapacityValue);
  $("#preference-form").addEventListener("submit", savePreference);
  $("#preference-provider").addEventListener("change", updatePreferenceValue);
  $("#preference-procedure").addEventListener("change", updatePreferenceValue);
  $("#shift-form").addEventListener("submit", saveShift);
  $("#policy-procedure").addEventListener("change", renderProcedurePolicy);
  $("#procedure-policy-form").addEventListener("submit", saveProcedurePolicy);
  $("#add-phase").addEventListener("click", () => { $("#phase-editor").insertAdjacentHTML("beforeend", phaseRow()); bindPhaseRemove(); });
  $("#equipment-form").addEventListener("submit", saveEquipment);
  $("#equipment-requirement-form").addEventListener("submit", saveEquipmentRequirement);
  $("#requirement-procedure").addEventListener("change", updateEquipmentRequirementValue);
  $("#requirement-equipment").addEventListener("change", updateEquipmentRequirementValue);
  $("#closure-form").addEventListener("submit", saveClosure);
  $("#calibration-form").addEventListener("submit", importCalibration);
  $("#calibration-approval-form").addEventListener("submit", applyCalibration);

  $("#audit-filter").addEventListener("input", renderAudit);
  $("#audit-category").addEventListener("change", renderAudit);
  $("#audit-outcome").addEventListener("change", renderAudit);

  $("#find-reschedule-button").addEventListener("click", findRescheduleOptions);
  $("#reschedule-approval").addEventListener("change", updateRescheduleApproval);
  $("#reschedule-reason").addEventListener("input", updateRescheduleApproval);
  $("#reschedule-form").addEventListener("submit", applyReschedule);
  $("#status-form").addEventListener("submit", applyStatus);
  $("#start-vacancy-recovery").addEventListener("click", beginVacancyRecovery);
  $("#find-vacancy-candidates").addEventListener("click", findVacancyCandidates);
  $("#vacancy-permission-confirmed").addEventListener("change", updateVacancyApproval);
  $("#vacancy-exact-acknowledged").addEventListener("change", updateVacancyApproval);
  $("#vacancy-move-reason").addEventListener("input", updateVacancyApproval);
  $("#vacancy-approval").addEventListener("submit", applyVacancyMove);
  $("#vacancy-stop-button").addEventListener("click", () => stopVacancyRecovery());
  $("#close-vacancy-recovery").addEventListener("click", () => stopVacancyRecovery());
  $("#vacancy-recovery-dialog").addEventListener("cancel", (event) => {
    if (state.vacancyRecoveryChain?.status === "active") {
      event.preventDefault();
      stopVacancyRecovery();
    }
  });
}

bindEvents();
bootstrap();
