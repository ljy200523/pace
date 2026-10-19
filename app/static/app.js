const API = "/api/v1";
const $ = (selector) => document.querySelector(selector);
const localDate = (date = new Date()) => {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
};
const dateAtLocalNoon = (iso) => new Date(`${iso}T12:00:00`);
const state = { studentId: localStorage.getItem("daywellStudentId"), studentName: localStorage.getItem("daywellStudentName") || "", selectedDay: localDate(), weekStart: null, events: [], entries: [], mood: null, insights: null, restCandidates: [], googleConnected: false };
let editingEventId = null;

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API}${path}`, { ...options, headers });
  const payload = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}
function setMessage(element, message, error = false) { element.textContent = message; element.classList.toggle("error", error); }
let toastTimer;
function notify(message, kind = "success") {
  const region = $("#toast-region");
  const toast = document.createElement("div");
  toast.className = `toast toast-${kind}`;
  toast.innerHTML = `<span class="toast-icon" aria-hidden="true">${kind === "error" ? "!" : "✳"}</span><span class="toast-copy"></span><button class="toast-close" type="button" aria-label="Dismiss message">×</button>`;
  toast.querySelector(".toast-copy").textContent = message;
  region.replaceChildren(toast);
  toast.querySelector(".toast-close").addEventListener("click", () => toast.remove());
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.remove(), 4800);
}
function confirmAction({ title, message, confirmLabel = "Continue", danger = false }) {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  const button = $("#confirm-action"); button.innerHTML = `${confirmLabel} <span>↗</span>`;
  button.classList.toggle("danger-button", danger);
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }));
}
function mondayOf(iso) { const day = dateAtLocalNoon(iso); day.setDate(day.getDate() - ((day.getDay() + 6) % 7)); return day; }
function fmtTime(iso) { return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
function sameDay(a, b) { return localDate(new Date(a)) === localDate(new Date(b)); }
function dateLabel(iso, options = { weekday: "short", month: "short", day: "numeric" }) { return dateAtLocalNoon(iso).toLocaleDateString([], options); }

async function ensureStudent() {
  try { const account = await api("/auth/me"); state.studentId = String(account.student_id); state.studentName = account.display_name; localStorage.setItem("daywellStudentId", state.studentId); localStorage.setItem("daywellStudentName", state.studentName); localStorage.setItem("daywellOnboarded", "1"); return true; }
  catch { state.studentId = null; $("#student-dialog").showModal(); return false; }
}
function setIdentity(name) {
  state.studentName = name;
  $("#profile-name").textContent = `${name}’s space`;
  $(".avatar").textContent = name.slice(0, 1).toUpperCase();
  $("#greeting").innerHTML = `A softer way to <em>stay on track.</em>`;
  $(".subheading").textContent = `School is a lot, ${name}. Let’s make space for you in it.`;
}
function setToday() {
  const now = new Date();
  $("#today-label").textContent = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  if (state.studentName) setIdentity(state.studentName);
}
function renderInsights() {
  const report = state.insights;
  if (!report) return;
  const score = report.risk.score;
  $("#risk-score").textContent = score == null ? "—" : score;
  $("#risk-meter").style.setProperty("--risk-progress", (score || 0) + "%");
  $("#risk-meter").dataset.level = score == null ? "none" : score < 30 ? "low" : score < 60 ? "moderate" : "elevated";
  $("#risk-label").textContent = score == null ? "Check in to estimate burnout risk" : report.risk.classification + " burnout risk";
  $("#risk-note").textContent = report.risk.note;
  $("#risk-data-note").textContent = report.risk.partial_data ? "Some recent sleep or mood/energy data is missing; the score uses available components." : report.risk.days_with_recent_checkins + " recent check-in day(s) included.";
  const names = { workload: "Next 7 days", sleep: "Sleep · 3 days", mood_energy: "Mood & energy" };
  const container = $("#risk-components"); container.replaceChildren();
  Object.entries(report.risk.components).forEach(([key, part]) => {
    const item = document.createElement("div"); item.className = "risk-component";
    const detail = key === "workload" ? part.effort_points + " effort points" : key === "sleep" ? (part.average_hours == null ? "Log sleep to include it" : part.average_hours + "h average") : "Recent check-ins";
    item.innerHTML = "<span></span><div><strong></strong><small></small></div><b></b>";
    item.querySelector("strong").textContent = names[key]; item.querySelector("small").textContent = detail;
    item.querySelector("b").textContent = part.score == null ? "No data" : Math.round(part.score) + " / 100";
    item.querySelector("span").style.setProperty("--component-fill", (part.score || 0) + "%"); container.append(item);
  });
  const weekContainer = $("#forecast-weeks"); weekContainer.replaceChildren();
  report.weeks.forEach((week) => {
    const card = document.createElement("article"); card.className = "forecast-week forecast-" + week.classification.toLowerCase().replaceAll(" ", "-");
    card.innerHTML = "<div class=\"forecast-week-top\"><span>WEEK " + week.week + "</span><b></b></div><strong></strong><small></small><div class=\"forecast-bar\"><i></i></div>";
    card.querySelector(".forecast-week-top b").textContent = dateLabel(week.start, { month: "short", day: "numeric" }) + " – " + dateLabel(week.end, { month: "short", day: "numeric" });
    card.querySelector("strong").textContent = week.classification;
    card.querySelector("small").textContent = week.effort_points + " effort points · " + week.event_count + " events";
    card.querySelector(".forecast-bar i").style.width = Math.min(100, week.effort_points / 60 * 100) + "%"; weekContainer.append(card);
  });
  const button = $("#rest-schedule-button"); button.disabled = !state.googleConnected || !state.restCandidates.length;
  $("#rest-preview-copy").textContent = state.restCandidates.length
    ? state.restCandidates.length + " possible two-hour block(s) found for the next 7 days. Nothing is added until you choose Schedule."
    : state.googleConnected ? "No qualifying open gaps found in the next 7 days." : "Connect Google Calendar to preview open gaps and add protected rest blocks.";
}
function renderWeek() {
  const monday = mondayOf(state.selectedDay);
  state.weekStart = localDate(monday);
  const wrap = $("#week-strip"); wrap.replaceChildren();
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday); d.setDate(d.getDate() + i); const key = localDate(d);
    const chip = document.createElement("button"); chip.className = `day-chip${key === state.selectedDay ? " selected" : ""}${key === localDate() ? " today" : ""}${state.events.some((e) => sameDay(e.starts_at, key)) ? " has-events" : ""}`;
    chip.innerHTML = `<span>${d.toLocaleDateString([], { weekday: "short" })}</span><strong>${d.getDate()}</strong><i></i>`;
    chip.setAttribute("aria-label", dateLabel(key)); chip.addEventListener("click", () => { state.selectedDay = key; renderWeek(); renderSchedule(); }); wrap.append(chip);
  }
}
function renderSchedule() {
  const list = $("#schedule-list"); list.replaceChildren();
  const events = state.events.filter((event) => sameDay(event.starts_at, state.selectedDay)).sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at));
  if (!events.length) {
    const empty = document.createElement("div"); empty.className = "empty-state";
    empty.innerHTML = `<span>✳</span><strong>${state.selectedDay === localDate() ? "Your day still has room for you." : "Nothing on this day yet."}</strong><p>${dateLabel(state.selectedDay)} · You can keep it that way, or add what’s on your mind.</p><button class="outline-button" id="empty-add-event">＋ Add an event</button>`;
    list.append(empty); $("#empty-add-event").addEventListener("click", () => $("#event-dialog").showModal()); return;
  }
  events.forEach((event) => {
    const row = document.createElement("div"); row.className = "event-row";
    const hours = Math.max(0, (new Date(event.ends_at) - new Date(event.starts_at)) / 3600000);
    row.innerHTML = `<div class="event-time">${fmtTime(event.starts_at)}</div><div class="event-marker"></div><div class="event-info"><strong></strong><small></small></div><div class="event-duration">${hours < 1 ? `${Math.round(hours * 60)} min` : `${hours.toFixed(hours % 1 ? 1 : 0)} hr`}</div><div class="event-actions"><button class="edit-event">Edit</button><button class="delete-event">Delete</button></div>`;
    row.querySelector("strong").textContent = event.title; row.querySelector("small").textContent = event.category;
    row.querySelector(".edit-event").addEventListener("click", () => editEvent(event));
    row.querySelector(".delete-event").addEventListener("click", () => deleteEvent(event)); list.append(row);
  });
}
function renderSummary() {
  const today = localDate(); const monday = mondayOf(today); const byDay = Array(7).fill(0); let count = 0; let hours = 0;
  state.events.forEach((event) => {
    const start = new Date(event.starts_at), end = new Date(event.ends_at); const h = Math.max(0, (end - start) / 3600000);
    if (start >= monday && start < new Date(monday.getTime() + 7 * 86400000)) { byDay[(start.getDay() + 6) % 7] += h; count++; hours += h; }
  });
  $("#week-hours").textContent = hours.toFixed(hours % 1 ? 1 : 0); $("#event-count").textContent = `${count} ${count === 1 ? "EVENT" : "EVENTS"} THIS WEEK`;
  const bars = $("#mini-bars"); bars.replaceChildren(); const max = Math.max(...byDay, 1);
  byDay.forEach((value, index) => { const bar = document.createElement("div"); const d = new Date(monday); d.setDate(d.getDate() + index); bar.className = `mini-bar${value ? " has-events" : ""}${localDate(d) === today ? " today" : ""}`; bar.style.height = `${Math.max(3, value / max * 26)}px`; bar.dataset.tip = `${d.toLocaleDateString([], { weekday: "short" })}: ${value.toFixed(value % 1 ? 1 : 0)}h`; bars.append(bar); });
  const active = state.entries.slice(0, 7).filter((e) => e.entry_date >= localDate(new Date(Date.now() - 6 * 86400000)));
  $("#checkin-days").textContent = active.length; const dots = $("#week-dots"); dots.replaceChildren();
  for (let i = 0; i < 7; i++) { const d = new Date(); d.setDate(d.getDate() - (6 - i)); const dot = document.createElement("i"); dot.className = `week-dot${state.entries.some((e) => e.entry_date === localDate(d)) ? " filled" : ""}`; dot.title = dateLabel(localDate(d)); dots.append(dot); }
  const latest = state.entries[0];
  if (latest) { const labels = ["A gentler day might help", "Taking it one step at a time", "Finding your footing", "A little more like you", "Feeling good today"];
    $("#mood-copy").textContent = latest.mood ? labels[latest.mood - 1] : "Thanks for checking in"; $("#mood-face").textContent = ["☹", "◔", "😐", "☺", "✿"][Math.max(0, (latest.mood || 3) - 1)];
    $("#mood-detail").textContent = latest.entry_date === today ? "You showed up for yourself today." : `Last check-in · ${dateLabel(latest.entry_date, { month: "short", day: "numeric" })}`;
    $("#sleep-copy").textContent = latest.sleep_hours != null ? `${latest.sleep_hours} hours of sleep logged` : "Your care counts, too";
  }
}
async function loadDashboard() {
  if (!state.studentId) { renderWeek(); renderSchedule(); renderSummary(); return; }
  try {
    const google = await loadGoogleStatus();
    if (google?.connected) {
      try { await api("/google/sync", { method: "POST", body: "{}" }); }
      catch (syncError) { console.error("Google Calendar sync failed", syncError); $("#google-status").textContent = `Connected: ${google.google_email || "Google Calendar"} · sync needs attention`; }
    }
    const [events, entries, insights] = await Promise.all([
      api(`/students/${state.studentId}/calendar/events?start=${encodeURIComponent(`${localDate(mondayOf(localDate()))}T00:00:00`)}&end=${encodeURIComponent(`${localDate(addDays(mondayOf(localDate()), 7))}T00:00:00`)}`),
      api(`/students/${state.studentId}/wellbeing?limit=30`),
      api(`/students/${state.studentId}/calendar/insights`),
    ]);
    state.events = events; state.entries = entries; state.insights = insights; state.googleConnected = !!google?.connected;
    state.restCandidates = google?.connected ? (await api(`/students/${state.studentId}/calendar/rest-blocks/preview`)).blocks : [];
    renderWeek(); renderSchedule(); renderSummary(); renderInsights();
    const todayEntry = entries.find((entry) => entry.entry_date === localDate());
    if (todayEntry) { selectMood(todayEntry.mood); $("#sleep-hours").value = todayEntry.sleep_hours ?? ""; $("#stress-level").value = todayEntry.stress ?? ""; $("#energy-level").value = todayEntry.energy ?? ""; $("#checkin-note").value = todayEntry.notes ?? ""; }
  } catch (error) { console.error(error); }
}
function renderNutritionHistory(items) {
  const list = $("#nutrition-history"); list.replaceChildren();
  if (!items.length) { const empty = document.createElement("p"); empty.className = "nutrition-empty"; empty.textContent = "Your meal suggestions will appear here."; list.append(empty); return; }
  items.forEach((item) => {
    const row = document.createElement("article"); row.className = "nutrition-history-item";
    const title = document.createElement("strong"); title.textContent = item.detected_food;
    const tag = document.createElement("span"); tag.className = "nutrition-tag"; tag.textContent = item.quality_tag;
    const tip = document.createElement("p"); tip.textContent = item.feedback_tip;
    const when = document.createElement("small"); when.textContent = new Date(item.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    row.append(title, tag, tip, when); list.append(row);
  });
}
async function loadNutritionHistory() {
  if (!state.studentId) return;
  try { renderNutritionHistory(await api(`/students/${state.studentId}/nutrition/logs?limit=5`)); }
  catch (error) { console.error("Could not load meal notes", error); }
}
async function loadGoogleStatus() {
  try { const status = await api("/google/status"); $("#google-status").textContent = status.connected ? `Connected: ${status.google_email || "Google Calendar"}` : "Google Calendar not connected"; $("#google-connect-button").textContent = status.connected ? "Reconnect Google Calendar" : "Connect Google Calendar"; $("#sync-button").hidden = !status.connected; return status; }
  catch { $("#google-status").textContent = "Sign in to connect Google Calendar"; return null; }
}
async function refreshCalendarInBackground() {
  if (document.hidden || !state.studentId) return;
  try {
    const google = await loadGoogleStatus();
    if (!google?.connected) return;
    await api("/google/sync", { method: "POST", body: "{}" });
    const events = await api(`/students/${state.studentId}/calendar/events?start=${encodeURIComponent(`${localDate(mondayOf(localDate()))}T00:00:00`)}&end=${encodeURIComponent(`${localDate(addDays(mondayOf(localDate()), 7))}T00:00:00`)}`);
    state.events = events; renderWeek(); renderSchedule(); renderSummary();
  } catch (error) { console.error("Background calendar refresh failed", error); }
}
async function syncGoogleCalendar() {
  const button = $("#sync-button"); button.disabled = true; button.textContent = "Syncing…";
  try { const result = await api("/google/sync", { method: "POST", body: "{}" }); await loadDashboard(); setMessage($("#checkin-message"), `Google Calendar synced · ${result.imported} new, ${result.updated} updated.`); }
  catch (error) { notify(error.message, "error"); }
  finally { button.disabled = false; button.textContent = "↻ Sync Google Calendar"; }
}
async function editEvent(event) {
  editingEventId = event.id;
  $("#event-title").value = event.title;
  $("#event-start").value = toLocalDateTimeInput(event.starts_at);
  $("#event-end").value = toLocalDateTimeInput(event.ends_at);
  $("#event-category").value = event.category;
  $("#event-dialog h2").textContent = "Update your event";
  $("#event-form .primary-button").innerHTML = "Save changes <span>↗</span>";
  $("#event-dialog").showModal();
}
function toLocalDateTimeInput(value) { const d = new Date(value); const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return local.toISOString().slice(0, 16); }
async function deleteEvent(event) {
  if (!await confirmAction({ title: "Remove this event?", message: `“${event.title}” will be removed from your schedule${event.provider === "google" ? " and Google Calendar" : ""}.`, confirmLabel: "Remove event", danger: true })) return;
  try { await api(`/students/${state.studentId}/calendar/events/${event.id}`, { method: "DELETE" }); await loadDashboard(); }
  catch (error) { notify(error.message, "error"); }
}
function addDays(date, days) { const d = new Date(date); d.setDate(d.getDate() + days); return d; }
function selectMood(value) { state.mood = value ? Number(value) : null; $("#mood-value").value = state.mood || ""; document.querySelectorAll(".mood-option").forEach((button) => button.classList.toggle("selected", Number(button.dataset.mood) === state.mood)); }
function appendMessage(role, text, time = "JUST NOW") {
  const wrap = $("#chat-messages"); const row = document.createElement("div"); row.className = role === "assistant" ? "day-message" : "user-message";
  if (role === "assistant") row.innerHTML = `<div class="message-avatar">✳</div><div><span class="message-author">BALM <small>${time}</small></span><div class="bubble"></div></div>`;
  else row.innerHTML = `<div><span class="message-author" style="text-align:right">YOU <small>${time}</small></span><div class="bubble"></div></div>`;
  row.querySelector(".bubble").textContent = text; wrap.append(row); wrap.scrollTop = wrap.scrollHeight; return row;
}
async function loadChatHistory() {
  if (!state.studentId) return;
  try { const history = await api(`/students/${state.studentId}/chat/history?limit=30`); if (!history.length) return; const box = $("#chat-messages"); box.replaceChildren(); history.forEach((item) => appendMessage(item.role, item.content, new Date(item.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toUpperCase())); }
  catch (error) { console.error(error); }
}
async function sendChat(message) {
  if (!message.trim() || !state.studentId) return;
  appendMessage("user", message.trim()); const button = $("#send-button"); button.disabled = true; button.textContent = "…";
  const pending = appendMessage("assistant", "Let me think that through with you…");
  try { const result = await api(`/students/${state.studentId}/chat`, { method: "POST", body: JSON.stringify({ message: message.trim() }) }); pending.remove(); appendMessage("assistant", result.reply); }
  catch (error) { pending.remove(); appendMessage("assistant", error.message.includes("OPENAI_API_KEY") ? "I’m not connected just yet. Please add OPENAI_API_KEY in the server’s .env file, then restart the app." : "I’m having a little trouble connecting right now. Your message is still here—please try again in a moment."); }
  finally { button.disabled = false; button.textContent = "↑"; }
}

let authMode = "login";
function showAuthMode(mode) { authMode = mode; $("#auth-title").textContent = mode === "signup" ? "Create your space" : "Sign in to your space"; $("#auth-submit").innerHTML = `${mode === "signup" ? "Create account" : "Sign in"} <span>↗</span>`; $("#auth-switch").textContent = mode === "signup" ? "Already have an account? Sign in" : "New here? Create an account"; $("#signup-name-wrap").hidden = mode !== "signup"; $("#account-password").autocomplete = mode === "signup" ? "new-password" : "current-password"; $("#account-password").minLength = mode === "signup" ? 10 : 1; }
showAuthMode("login");
$("#auth-switch").addEventListener("click", () => showAuthMode(authMode === "login" ? "signup" : "login"));
$("#student-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const message = $("#auth-message");
  const body = { email: $("#account-email").value.trim(), password: $("#account-password").value };
  if (authMode === "signup") body.display_name = $("#student-name").value.trim() || body.email.split("@")[0];
  try { const account = await api(`/auth/${authMode === "signup" ? "signup" : "login"}`, { method: "POST", body: JSON.stringify(body) }); state.studentId = String(account.student_id); state.studentName = account.display_name; localStorage.setItem("daywellStudentId", state.studentId); localStorage.setItem("daywellStudentName", state.studentName); localStorage.setItem("daywellOnboarded", "1"); $("#student-dialog").close(); setIdentity(state.studentName); await loadDashboard(); await loadChatHistory(); }
  catch (error) { setMessage(message, error.message, true); }
});
$("#profile-button").addEventListener("click", async () => { if (state.studentId) { if (await confirmAction({ title: "Take a break?", message: "You’ll be signed out of Pace. Your Google Calendar will stay connected to your account.", confirmLabel: "Sign out" })) { try { await api("/auth/logout", { method: "POST", body: "{}" }); state.studentId = null; $("#student-dialog").showModal(); showAuthMode("login"); } catch (error) { notify(error.message, "error"); } } } else { $("#student-dialog").showModal(); } });
$("#add-event-button").addEventListener("click", () => $("#event-dialog").showModal());
$("#empty-add-event").addEventListener("click", () => $("#event-dialog").showModal());
$("#event-dialog").addEventListener("close", () => { if (editingEventId !== null) { editingEventId = null; $("#event-form").reset(); $("#event-dialog h2").textContent = "Add to your week"; $("#event-form .primary-button").innerHTML = "Add to my week <span>↗</span>"; } });
$("#event-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (!state.studentId) return;
  const start = new Date($("#event-start").value), end = new Date($("#event-end").value);
  const editing = editingEventId !== null;
  const existing = state.events.find((item) => item.id === editingEventId);
  const body = { title: $("#event-title").value.trim(), starts_at: start.toISOString(), ends_at: end.toISOString(), category: $("#event-category").value, provider: existing?.provider || "manual", external_id: existing?.external_id || "" };
  try { await api(editing ? `/students/${state.studentId}/calendar/events/${editingEventId}` : `/students/${state.studentId}/calendar/events`, { method: editing ? "PATCH" : "POST", body: JSON.stringify(body) }); $("#event-dialog").close(); $("#event-form").reset(); editingEventId = null; $("#event-dialog h2").textContent = "Add to your week"; $("#event-form .primary-button").innerHTML = "Add to my week <span>↗</span>"; await loadDashboard(); }
  catch (error) { notify(error.message, "error"); }
});
$("#google-connect-button").addEventListener("click", () => { window.location.href = "/api/v1/google/connect"; });
$("#sync-button").addEventListener("click", syncGoogleCalendar);
$("#rest-schedule-button").addEventListener("click", async () => {
  if (!state.restCandidates.length || !state.googleConnected) return;
  const count = state.restCandidates.length;
  if (!await confirmAction({ title: "Make room for recovery?", message: "Pace found up to " + count + " protected two-hour rest block(s) in open calendar gaps over the next week. These will be added to Google Calendar.", confirmLabel: "Add rest blocks" })) return;
  const button = $("#rest-schedule-button"); button.disabled = true; button.textContent = "Finding space…";
  try {
    const result = await api("/students/" + state.studentId + "/calendar/rest-blocks", { method: "POST", body: "{}" });
    notify("Added " + result.created + " protected rest block(s) to Google Calendar.");
    await loadDashboard();
  } catch (error) { notify(error.message, "error"); }
  finally { button.innerHTML = "Schedule rest blocks <span>↗</span>"; renderInsights(); }
});
$("#sync-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (!state.studentId) return;
  try { const events = JSON.parse($("#sync-json").value); if (!Array.isArray(events)) throw new Error("Paste a JSON array of events."); const result = await api(`/students/${state.studentId}/calendar/sync`, { method: "POST", body: JSON.stringify({ provider: $("#sync-provider").value, events: events.map((item) => ({ ...item, provider: $("#sync-provider").value })) }) }); $("#sync-dialog").close(); $("#sync-form").reset(); await loadDashboard(); notify(`Imported ${result.imported} and updated ${result.updated} events.`); }
  catch (error) { notify(error instanceof SyntaxError ? "That JSON does not look valid. Please check it and try again." : error.message, "error"); }
});
document.querySelectorAll(".mood-option").forEach((button) => button.addEventListener("click", () => selectMood(button.dataset.mood)));
$("#checkin-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (!state.studentId) return; const message = $("#checkin-message");
  const body = { entry_date: localDate(), sleep_hours: $("#sleep-hours").value === "" ? null : Number($("#sleep-hours").value), mood: state.mood, energy: $("#energy-level").value === "" ? null : Number($("#energy-level").value), stress: $("#stress-level").value === "" ? null : Number($("#stress-level").value), notes: $("#checkin-note").value.trim() || null };
  try { await api(`/students/${state.studentId}/wellbeing`, { method: "PUT", body: JSON.stringify(body) }); setMessage(message, "Saved. Thank you for checking in with yourself."); await loadDashboard(); }
  catch (error) { setMessage(message, error.message, true); }
});
let nutritionPreviewUrl = null;
async function prepareNutritionUpload(file) {
  const maxRequestImageBytes = 3 * 1024 * 1024;
  if (file.size <= maxRequestImageBytes) return file;
  if (!window.createImageBitmap) throw new Error("This photo is too large to send. Please choose a smaller image.");
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  let scale = Math.min(1, 2000 / Math.max(bitmap.width, bitmap.height));
  try {
    for (let attempt = 0; attempt < 6; attempt += 1) {
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.86));
      if (!blob) break;
      if (blob.size <= maxRequestImageBytes) return new File([blob], "meal-photo.jpg", { type: "image/jpeg" });
      scale *= 0.78;
    }
  } finally { bitmap.close(); }
  throw new Error("This photo couldn’t be resized enough to upload. Please choose a smaller image.");
}
$("#nutrition-image").addEventListener("change", (event) => {
  if (nutritionPreviewUrl) URL.revokeObjectURL(nutritionPreviewUrl);
  const image = event.target.files[0]; const preview = $("#nutrition-preview");
  nutritionPreviewUrl = image ? URL.createObjectURL(image) : null;
  preview.hidden = !image; if (image) preview.src = nutritionPreviewUrl;
});
$("#nutrition-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (!state.studentId) return;
  const form = event.currentTarget; const image = $("#nutrition-image").files[0]; const dish = $("#nutrition-hint").value.trim(); const button = $("#nutrition-submit"); const message = $("#nutrition-message");
  if (!image && !dish) { setMessage(message, "Type a dish name, add a photo, or include both.", true); return; }
  button.disabled = true; button.textContent = "A moment while I take a look…"; setMessage(message, image ? "Your meal photo is being analyzed securely." : "Putting together a gentle suggestion.");
  try {
    const body = new FormData(); if (image) body.append("file", await prepareNutritionUpload(image)); body.append("dish_hint", dish);
    const result = await api(`/students/${state.studentId}/nutrition/analyze-image`, { method: "POST", body });
    $("#nutrition-food").textContent = result.detected_food; $("#nutrition-tag").textContent = result.quality_tag; $("#nutrition-tip").textContent = result.feedback_tip; $("#nutrition-result").hidden = false;
    await loadNutritionHistory(); form.reset(); $("#nutrition-preview").hidden = true; if (nutritionPreviewUrl) URL.revokeObjectURL(nutritionPreviewUrl); nutritionPreviewUrl = null;
    setMessage(message, "Suggestion saved to your meal notes.");
  } catch (error) { setMessage(message, error.message, true); }
  finally { button.disabled = false; button.innerHTML = "Get a gentle suggestion <span>↗</span>"; }
});
$("#chat-form").addEventListener("submit", async (event) => { event.preventDefault(); const input = $("#chat-input"); const value = input.value; if (!value.trim()) return; input.value = ""; input.style.height = "auto"; await sendChat(value); });
$("#chat-input").addEventListener("input", (event) => { event.target.style.height = "auto"; event.target.style.height = `${Math.min(event.target.scrollHeight, 95)}px`; });
$("#chat-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("#chat-form").requestSubmit(); } });
document.querySelectorAll(".suggestion").forEach((button) => button.addEventListener("click", () => sendChat(button.dataset.prompt)));

setToday(); renderWeek(); renderSchedule(); renderSummary(); ensureStudent().then(async (signedIn) => { if (signedIn) { setIdentity(state.studentName || "there"); await loadDashboard(); await loadNutritionHistory(); await loadChatHistory(); const params = new URLSearchParams(window.location.hash.split("?")[1] || ""); if (params.has("google")) { history.replaceState(null, "", window.location.pathname); if (params.get("google") === "connected") { await loadGoogleStatus(); await loadDashboard(); notify("Google Calendar is connected and synced."); } else if (params.get("google") === "sync_error") { await loadGoogleStatus(); notify("Google Calendar is connected, but its first sync needs attention. Try Sync from My Schedule.", "error"); } else if (params.get("google") === "scope_error") { await loadGoogleStatus(); notify("Google didn’t grant Calendar access. Reconnect and approve the calendar.events permission.", "error"); } else { notify("Google Calendar wasn’t connected. You can try again whenever you’re ready.", "error"); } } } });
setInterval(refreshCalendarInBackground, 60_000);
