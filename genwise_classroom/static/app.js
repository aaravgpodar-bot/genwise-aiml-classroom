const state = {
  user: null,
  section: "dashboard",
  resourceView: localStorage.getItem("genwise-resource-view") || "cards",
  assignments: [],
  submissions: [],
  pendingAssignmentId: "",
};

const titles = {
  dashboard: "Dashboard",
  assignments: "Assignments",
  resources: "Resources",
  inbox: "Inbox",
  submissions: "Submissions",
  "teacher-room": "Teacher Room",
  people: "People",
  ai: "AI Assistant",
  saved: "Saved",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function toast(message, type = "ok") {
  const wrap = $("#toast");
  const note = document.createElement("div");
  note.className = `toast ${type === "error" ? "error" : ""}`;
  note.textContent = message;
  wrap.appendChild(note);
  setTimeout(() => note.remove(), 4200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: options.body instanceof FormData
      ? options.headers || {}
      : { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "Something went wrong.");
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function compactDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function dueDate(value) {
  if (!value) return "No due date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `Due ${date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}`;
}

function fileSize(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(bytes);
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`;
}

function tagsHtml(tags) {
  const values = String(tags || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
  if (!values.length) return "";
  return `<div class="badge-row">${values.map((tag) => `<span class="badge">${escapeHtml(tag)}</span>`).join("")}</div>`;
}

function itemLinks(item) {
  const links = [];
  if (item.url) {
    links.push(`<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">Open link</a>`);
  }
  if (item.preview_url) {
    links.push(`<a href="${escapeHtml(item.preview_url)}" target="_blank" rel="noreferrer">Preview file</a>`);
  }
  if (item.download_url) {
    const label = item.original_filename ? `Download ${escapeHtml(item.original_filename)}` : "Download file";
    links.push(`<a href="${escapeHtml(item.download_url)}">${label}</a>`);
  }
  return links.length ? `<div class="action-row">${links.join("")}</div>` : "";
}

function applyRoleVisibility() {
  const isTeacher = state.user?.role === "teacher";
  $$(".teacher-only").forEach((el) => el.classList.toggle("hidden", !isTeacher));
  $$(".student-only").forEach((el) => el.classList.toggle("hidden", isTeacher));
}

function setSignedIn(user) {
  state.user = user;
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#user-pill").textContent = `${user.name} · ${user.role}`;
  applyRoleVisibility();
}

function setSignedOut() {
  state.user = null;
  $("#auth-view").classList.remove("hidden");
  $("#app-view").classList.add("hidden");
}

function setSection(section) {
  if (!titles[section]) return;
  state.section = section;
  $$(".nav-button").forEach((button) => button.classList.toggle("active", button.dataset.section === section));
  $$(".view").forEach((view) => view.classList.toggle("active-view", view.id === section));
  $("#section-title").textContent = titles[section];
  loadSection(section);
}

function emptyState(text) {
  return `<div class="empty-state">${escapeHtml(text)}</div>`;
}

function resourceCard(item) {
  const pinned = item.pinned ? `<span class="badge pinned">Pinned</span>` : "";
  const saveButton = item.saved
    ? `<button data-unsave="${item.id}" type="button">Saved</button>`
    : `<button data-save="${item.id}" type="button">Save</button>`;
  const teacherTools = state.user.role === "teacher"
    ? `<button data-pin-resource="${item.id}" data-pinned="${item.pinned ? "1" : "0"}" type="button">${item.pinned ? "Unpin" : "Pin"}</button>
       <button class="danger" data-delete-resource="${item.id}" type="button">Delete</button>`
    : "";
  const summary = item.description || item.body || item.url || "No description yet.";
  return `
    <article class="panel item-card">
      <div>
        <div class="item-title-row">
          <h3>${escapeHtml(item.title)}</h3>
          ${pinned}
        </div>
        <div class="item-meta">${escapeHtml(item.kind)} · ${escapeHtml(item.uploader_name || "Teacher")} · ${compactDate(item.created_at)}</div>
      </div>
      <div class="item-body">${escapeHtml(summary).replaceAll("\n", "<br>")}</div>
      ${tagsHtml(item.tags)}
      ${itemLinks(item)}
      <div class="action-row">${saveButton}${teacherTools}</div>
    </article>
  `;
}

function renderResources(items, target = $("#resources-list")) {
  target.classList.toggle("list-mode", state.resourceView === "list");
  target.innerHTML = items.length ? items.map(resourceCard).join("") : emptyState("No resources yet.");
}

function assignmentCard(item) {
  const pinned = item.pinned ? `<span class="badge pinned">Pinned</span>` : "";
  const status = `<span class="badge ${item.status === "open" ? "pinned" : ""}">${escapeHtml(item.status)}</span>`;
  const saveButton = item.saved
    ? `<button data-unsave-assignment="${item.id}" type="button">Saved</button>`
    : `<button data-save-assignment="${item.id}" type="button">Save</button>`;
  const teacherTools = state.user.role === "teacher"
    ? `<button data-pin-assignment="${item.id}" data-pinned="${item.pinned ? "1" : "0"}" type="button">${item.pinned ? "Unpin" : "Pin"}</button>
       <button data-status-assignment="${item.id}" data-status="${item.status === "open" ? "closed" : "open"}" type="button">${item.status === "open" ? "Close" : "Reopen"}</button>
       <button class="danger" data-delete-assignment="${item.id}" type="button">Archive</button>`
    : "";
  const studentTools = state.user.role === "student" && item.status === "open"
    ? `<button class="primary" data-start-submission="${item.id}" type="button">${item.my_submission_count ? "Submit again" : "Submit work"}</button>`
    : "";
  const summary = item.instructions || item.url || "No instructions yet.";
  const submissionInfo = state.user.role === "teacher"
    ? `${item.submission_count || 0} submissions`
    : item.my_submission_count ? "Submitted" : "Not submitted";
  return `
    <article class="panel item-card">
      <div>
        <div class="item-title-row">
          <h3>${escapeHtml(item.title)}</h3>
          <div class="badge-row">${pinned}${status}</div>
        </div>
        <div class="item-meta">${dueDate(item.due_at)} - ${escapeHtml(item.creator_name || "Instructor")} - ${submissionInfo}</div>
      </div>
      <div class="item-body">${escapeHtml(summary).replaceAll("\n", "<br>")}</div>
      ${itemLinks(item)}
      <div class="action-row">${studentTools}${saveButton}${teacherTools}</div>
    </article>
  `;
}

function renderAssignments(items, target = $("#assignments-list")) {
  target.innerHTML = items.length ? items.map(assignmentCard).join("") : emptyState("No assignments yet.");
}

function resourceReviewCard(item) {
  const statusBadge = `<span class="badge ${item.status === "pending" ? "pinned" : ""}">${escapeHtml(item.status)}</span>`;
  const summary = item.description || item.body || item.url || "No details added.";
  const teacherActions = state.user.role === "teacher" && item.status !== "deleted"
    ? `
      <label class="full-span">Teacher comment
        <textarea data-review-comment="${item.id}" rows="2" placeholder="Optional comment for the student">${escapeHtml(item.teacher_comment || "")}</textarea>
      </label>
      <div class="action-row">
        <button data-review-action="${item.id}" data-action="publish" type="button">Publish publicly</button>
        <button data-review-action="${item.id}" data-action="private" type="button">Keep private</button>
        <button data-review-action="${item.id}" data-action="comment" type="button">Save comment</button>
        <button class="danger" data-review-action="${item.id}" data-action="delete" type="button">Delete</button>
      </div>
    `
    : "";
  return `
    <article class="panel item-card">
      <div class="item-title-row">
        <div>
          <h3>${escapeHtml(item.title)}</h3>
          <div class="item-meta">${escapeHtml(item.student_name || "Student")} · ${escapeHtml(item.kind)} · ${compactDate(item.created_at)}</div>
        </div>
        ${statusBadge}
      </div>
      <div class="item-body">${escapeHtml(summary).replaceAll("\n", "<br>")}</div>
      ${item.teacher_comment ? `<div class="reply"><strong>Teacher comment</strong><p>${escapeHtml(item.teacher_comment)}</p></div>` : ""}
      ${tagsHtml(item.tags)}
      ${itemLinks(item)}
      ${teacherActions}
    </article>
  `;
}

async function loadResourceReviews() {
  const panel = $("#resource-reviews-panel");
  if (!panel) return;
  const data = await api("/api/resource-reviews");
  const reviews = data.reviews || [];
  panel.classList.toggle("hidden", reviews.length === 0);
  $("#resource-reviews-list").innerHTML = reviews.length ? reviews.map(resourceReviewCard).join("") : emptyState("No student resource uploads yet.");
}

async function loadResources(savedOnly = false) {
  const q = savedOnly ? "" : $("#resource-search")?.value || "";
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (savedOnly) params.set("saved", "1");
  const data = await api(`/api/resources?${params}`);
  renderResources(data.resources || [], savedOnly ? $("#saved-list") : $("#resources-list"));
  if (!savedOnly) await loadResourceReviews();
}

async function loadAssignments(savedOnly = false) {
  const q = savedOnly ? "" : $("#assignment-search")?.value || "";
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (savedOnly) params.set("saved", "1");
  const data = await api(`/api/assignments?${params}`);
  if (!savedOnly) {
    state.assignments = data.assignments || [];
  }
  renderAssignments(data.assignments || [], savedOnly ? $("#saved-list") : $("#assignments-list"));
}

async function loadSaved() {
  const [resources, assignments] = await Promise.all([
    api("/api/resources?saved=1"),
    api("/api/assignments?saved=1"),
  ]);
  const savedResources = resources.resources || [];
  const savedAssignments = assignments.assignments || [];
  $("#saved-list").innerHTML = [
    ...savedAssignments.map(assignmentCard),
    ...savedResources.map(resourceCard),
  ].join("") || emptyState("Saved resources and assignments will appear here.");
}

function dashboardList(items, renderer, empty) {
  if (!items?.length) return emptyState(empty);
  return items.map(renderer).join("");
}

function tinyResource(item) {
  return `
    <div class="metric-row">
      <div>
        <strong style="font-size:15px;color:var(--ink)">${escapeHtml(item.title)}</strong>
        <div class="item-meta">${escapeHtml(item.kind || "resource")} · ${compactDate(item.created_at)}</div>
      </div>
      ${item.download_url ? `<a href="${escapeHtml(item.download_url)}">Download</a>` : ""}
    </div>
  `;
}

function tinyInbox(item) {
  return `
    <div class="metric-row">
      <div>
        <strong style="font-size:15px;color:var(--ink)">${escapeHtml(item.title)}</strong>
        <div class="item-meta">${escapeHtml(item.author_name)} · ${compactDate(item.created_at)}</div>
      </div>
    </div>
  `;
}

function tinyAssignment(item) {
  const detail = state.user.role === "teacher"
    ? `${item.submission_count || 0} submissions`
    : item.my_submission_count ? "Submitted" : "Not submitted";
  return `
    <div class="metric-row">
      <div>
        <strong style="font-size:15px;color:var(--ink)">${escapeHtml(item.title)}</strong>
        <div class="item-meta">${dueDate(item.due_at)} - ${detail}</div>
      </div>
      <button data-jump="assignments" type="button">Open</button>
    </div>
  `;
}

function renderDashboard(data) {
  const grid = $("#dashboard-grid");
  const sharedCards = `
    <article class="panel dashboard-card">
      <h2>Assignments</h2>
      ${dashboardList(data.recent_assignments, tinyAssignment, "No assignments posted yet.")}
    </article>
    <article class="panel dashboard-card">
      <h2>Recent Resources</h2>
      ${dashboardList(data.recent_resources, tinyResource, "No public resources yet.")}
    </article>
    <article class="panel dashboard-card">
      <h2>Inbox Updates</h2>
      ${dashboardList(data.recent_inbox, tinyInbox, "No inbox messages yet.")}
    </article>
    <article class="panel dashboard-card">
      <h2>Saved</h2>
      ${dashboardList([...(data.saved_assignments || []), ...(data.saved_resources || [])], (item) => item.instructions !== undefined ? tinyAssignment(item) : tinyResource(item), "Saved items will appear here.")}
    </article>
  `;

  if (state.user.role === "teacher") {
    const pending = data.pending_users || [];
    const submissions = data.recent_submissions || [];
    const activity = data.student_activity || [];
    const resourceReviews = data.resource_reviews || [];
    grid.innerHTML = `
      <article class="panel dashboard-card">
        <h2>Account Requests</h2>
        <div class="metric-row"><span>Waiting</span><strong>${pending.length}</strong></div>
        ${pending.slice(0, 4).map((user) => `<div class="item-meta">${escapeHtml(user.name)} · ${escapeHtml(user.role)}</div>`).join("") || `<p class="hint">No pending accounts.</p>`}
      </article>
      <article class="panel dashboard-card">
        <h2>Recent Submissions</h2>
        ${dashboardList(submissions, (item) => `
          <button data-open-submission="${item.id}" type="button" style="text-align:left">
            ${escapeHtml(item.title)}<br><span class="item-meta">${escapeHtml(item.student_name)} · ${item.comment_count} comments</span>
          </button>
        `, "No student submissions yet.")}
      </article>
      <article class="panel dashboard-card">
        <h2>Student Activity</h2>
        ${dashboardList(activity, (student) => `
          <div class="metric-row">
            <span>${escapeHtml(student.name)}</span>
            <strong>${student.submissions}</strong>
          </div>
        `, "No active students yet.")}
      </article>
      <article class="panel dashboard-card">
        <h2>Student Resource Uploads</h2>
        <div class="metric-row"><span>Pending review</span><strong>${resourceReviews.length}</strong></div>
        ${dashboardList(resourceReviews, (item) => `
          <button data-jump="resources" type="button" style="text-align:left">
            ${escapeHtml(item.title)}<br><span class="item-meta">${escapeHtml(item.student_name)} · ${compactDate(item.created_at)}</span>
          </button>
        `, "No student resource uploads waiting.")}
      </article>
      ${sharedCards}
    `;
  } else {
    const myResourceReviews = data.my_resource_reviews || [];
    grid.innerHTML = `
      <article class="panel dashboard-card">
        <h2>Latest Teacher Comments</h2>
        ${dashboardList(data.latest_teacher_comments, (comment) => `
          <div class="reply">
            <div class="item-meta">${escapeHtml(comment.submission_title)} · ${escapeHtml(comment.teacher_name)}</div>
            <p>${escapeHtml(comment.body)}</p>
          </div>
        `, "Teacher feedback will appear here.")}
      </article>
      <article class="panel dashboard-card">
        <h2>My Submissions</h2>
        ${dashboardList(data.my_submissions, (item) => `
          <button data-open-submission="${item.id}" type="button" style="text-align:left">
            ${escapeHtml(item.title)}<br><span class="item-meta">${item.comment_count} teacher comments</span>
          </button>
        `, "Your private submissions will appear here.")}
      </article>
      <article class="panel dashboard-card">
        <h2>AI Assistant</h2>
        <p class="item-body">Ask research questions and search classroom resources without drafting classwork for you.</p>
        <button type="button" data-jump="ai">Open assistant</button>
      </article>
      <article class="panel dashboard-card">
        <h2>My Resource Uploads</h2>
        ${dashboardList(myResourceReviews, (item) => `
          <div class="metric-row">
            <span>${escapeHtml(item.title)}</span>
            <strong style="font-size:13px">${escapeHtml(item.status)}</strong>
          </div>
        `, "Your resource uploads will appear here.")}
      </article>
      ${sharedCards}
    `;
  }
  $("#notification-count").textContent = data.unread_notifications || 0;
}

async function loadDashboard() {
  const data = await api("/api/dashboard");
  renderDashboard(data);
}

function inboxPost(post) {
  const teacherTools = state.user.role === "teacher"
    ? `<button data-pin-inbox="${post.id}" data-pinned="${post.pinned ? "1" : "0"}" type="button">${post.pinned ? "Unpin" : "Pin"}</button>
       <button class="danger" data-delete-inbox="${post.id}" type="button">Delete</button>`
    : post.author_id === state.user.id
      ? `<button class="danger" data-delete-inbox="${post.id}" type="button">Delete</button>`
      : "";
  return `
    <article class="panel feed-post">
      <div class="item-title-row">
        <div>
          <h3>${escapeHtml(post.title)}</h3>
          <div class="item-meta">${escapeHtml(post.author_name)} · ${escapeHtml(post.author_role)} · ${compactDate(post.created_at)}</div>
        </div>
        ${post.pinned ? `<span class="badge pinned">Pinned</span>` : ""}
      </div>
      <div class="item-body">${escapeHtml(post.body || "").replaceAll("\n", "<br>")}</div>
      ${itemLinks(post)}
      <div class="reply-list">
        ${(post.replies || []).map((reply) => `
          <div class="reply">
            <div class="item-meta">${escapeHtml(reply.author_name)} · ${compactDate(reply.created_at)}</div>
            <p>${escapeHtml(reply.body)}</p>
          </div>
        `).join("")}
      </div>
      <form class="reply-form" data-inbox-reply="${post.id}">
        <textarea name="body" rows="2" placeholder="Reply to this inbox post"></textarea>
        <button type="submit">Reply</button>
      </form>
      <div class="action-row">${teacherTools}</div>
    </article>
  `;
}

async function loadInbox() {
  const data = await api("/api/inbox");
  $("#inbox-list").innerHTML = data.posts?.length ? data.posts.map(inboxPost).join("") : emptyState("No inbox posts yet.");
}

async function loadAssignmentOptions() {
  const select = $("#submission-assignment-select");
  if (!select || state.user.role !== "student") return;
  const data = await api("/api/assignments");
  const assignments = data.assignments || [];
  state.assignments = assignments;
  const openAssignments = assignments.filter((item) => item.status === "open");
  const selected = state.pendingAssignmentId || select.value;
  select.innerHTML = `<option value="">No assignment</option>${openAssignments.map((item) => `
    <option value="${item.id}">${escapeHtml(item.title)}${item.due_at ? ` - ${escapeHtml(dueDate(item.due_at))}` : ""}</option>
  `).join("")}`;
  if (selected && openAssignments.some((item) => String(item.id) === String(selected))) {
    select.value = selected;
    const assignment = openAssignments.find((item) => String(item.id) === String(selected));
    const titleInput = $("#submission-form input[name=\"title\"]");
    if (titleInput && !titleInput.value) {
      titleInput.value = `Submission for ${assignment.title}`;
    }
    state.pendingAssignmentId = "";
  }
}

function submissionCard(item) {
  const detail = item.description || item.text_content || item.url || "No details added.";
  const assignment = item.assignment_title ? `<div class="item-meta">Assignment: ${escapeHtml(item.assignment_title)}</div>` : "";
  return `
    <article class="panel item-card">
      <div>
        <h3>${escapeHtml(item.title)}</h3>
        <div class="item-meta">${escapeHtml(item.student_name || state.user.name)} · ${compactDate(item.created_at)} · ${item.comment_count || 0} teacher comments</div>
      </div>
      ${assignment}
      <div class="item-body">${escapeHtml(detail).replaceAll("\n", "<br>")}</div>
      ${itemLinks(item)}
      <div class="action-row">
        <button data-open-submission="${item.id}" type="button">Open comments</button>
      </div>
    </article>
  `;
}

async function loadSubmissions() {
  await loadAssignmentOptions();
  const data = await api("/api/submissions");
  state.submissions = data.submissions || [];
  $("#submissions-list").innerHTML = state.submissions.length
    ? state.submissions.map(submissionCard).join("")
    : emptyState(state.user.role === "teacher" ? "No student submissions yet." : "You have not sent any private submissions yet.");
}

async function openSubmission(id) {
  if (!state.submissions.length) {
    await loadSubmissions();
  }
  const item = state.submissions.find((submission) => Number(submission.id) === Number(id));
  if (!item) {
    toast("Submission not found in the current list.", "error");
    return;
  }
  const data = await api(`/api/submissions/${id}/comments`);
  $("#submission-dialog-title").textContent = item.title;
  $("#submission-dialog-body").innerHTML = `
    <div class="item-meta">${escapeHtml(item.student_name || state.user.name)} · ${compactDate(item.created_at)}</div>
    ${item.assignment_title ? `<div class="item-meta">Assignment: ${escapeHtml(item.assignment_title)}</div>` : ""}
    <p class="item-body">${escapeHtml(item.description || "").replaceAll("\n", "<br>")}</p>
    ${item.text_content ? `<div class="reply"><strong>Text entry</strong><p>${escapeHtml(item.text_content).replaceAll("\n", "<br>")}</p></div>` : ""}
    ${itemLinks(item)}
    <div class="comment-thread">
      <h3>Teacher Comments</h3>
      ${(data.comments || []).length ? data.comments.map((comment) => `
        <div class="comment">
          <div class="item-meta">${escapeHtml(comment.teacher_name)} · ${compactDate(comment.created_at)}</div>
          <p>${escapeHtml(comment.body)}</p>
        </div>
      `).join("") : emptyState("No teacher comments yet.")}
    </div>
    ${state.user.role === "teacher" ? `
      <form id="teacher-comment-form" class="stacked" data-submission="${item.id}">
        <label>New teacher comment
          <textarea name="body" rows="4" required></textarea>
        </label>
        <button class="primary" type="submit">Add comment</button>
      </form>
    ` : ""}
  `;
  $("#submission-dialog").showModal();
}

function teacherRoomCard(item) {
  return `
    <article class="panel item-card">
      <div class="item-title-row">
        <div>
          <h3>${escapeHtml(item.title)}</h3>
          <div class="item-meta">${escapeHtml(item.kind)} · ${escapeHtml(item.uploader_name)} · ${compactDate(item.created_at)}</div>
        </div>
        ${item.pinned ? `<span class="badge pinned">Pinned</span>` : ""}
      </div>
      <div class="item-body">${escapeHtml(item.description || item.body || item.url || "").replaceAll("\n", "<br>")}</div>
      ${tagsHtml(item.tags)}
      ${itemLinks(item)}
      <div class="action-row">
        <button data-pin-teacher-item="${item.id}" data-pinned="${item.pinned ? "1" : "0"}" type="button">${item.pinned ? "Unpin" : "Pin"}</button>
        <button class="danger" data-delete-teacher-item="${item.id}" type="button">Delete</button>
      </div>
    </article>
  `;
}

async function loadTeacherRoom() {
  const data = await api("/api/teacher-room");
  $("#teacher-room-list").innerHTML = data.items?.length ? data.items.map(teacherRoomCard).join("") : emptyState("No teacher-only items yet.");
}

async function loadPeople() {
  const data = await api("/api/users");
  const rows = data.users.map((user) => `
    <tr>
      <td><strong>${escapeHtml(user.name)}</strong><br><span class="item-meta">${escapeHtml(user.email)}</span></td>
      <td>${escapeHtml(user.role)}</td>
      <td>${user.approved ? "Approved" : "Waiting"}</td>
      <td>${user.disabled ? "Disabled" : "Active"}</td>
      <td>${compactDate(user.created_at)}</td>
      <td>
        <div class="action-row">
          ${user.approved ? "" : `<button data-approve-user="${user.id}" type="button">Approve</button>`}
          <button data-role-user="${user.id}" data-role="${user.role}" type="button">Make ${user.role === "teacher" ? "student" : "teacher"}</button>
          <button data-disable-user="${user.id}" data-disabled="${user.disabled ? "1" : "0"}" type="button">${user.disabled ? "Enable" : "Disable"}</button>
        </div>
      </td>
    </tr>
  `).join("");
  $("#people-list").innerHTML = `
    <table>
      <thead><tr><th>User</th><th>Role</th><th>Approval</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderAiMessages(messages) {
  $("#ai-messages").innerHTML = messages.length ? messages.map((message) => {
    let citations = [];
    try {
      citations = JSON.parse(message.citations_json || "[]");
    } catch {
      citations = [];
    }
    const cites = citations.length
      ? `<div class="ai-citations">Sources used: ${citations.map((item) => escapeHtml(item.title)).join(", ")}</div>`
      : "";
    return `<div class="ai-bubble ${message.role}">${escapeHtml(message.content)}${cites}</div>`;
  }).join("") : emptyState("Ask a research question to begin.");
  $("#ai-messages").scrollTop = $("#ai-messages").scrollHeight;
}

async function loadAi() {
  const [profile, history] = await Promise.all([
    api("/api/ai/profile"),
    api("/api/ai/history"),
  ]);
  const form = $("#ai-profile-form");
  form.tone.value = profile.profile.tone || "";
  form.helpfulness.value = profile.profile.helpfulness || "";
  form.focus.value = profile.profile.focus || "";
  form.custom_instructions.value = profile.profile.custom_instructions || "";
  renderAiMessages(history.messages || []);
}

async function loadNotifications() {
  const data = await api("/api/notifications");
  $("#notifications-list").innerHTML = data.notifications?.length
    ? data.notifications.map((note) => `
      <div class="reply">
        <div class="item-meta">${note.read_at ? "Read" : "Unread"} · ${compactDate(note.created_at)}</div>
        <p>${escapeHtml(note.message)}</p>
      </div>
    `).join("")
    : emptyState("No notifications yet.");
}

async function loadSection(section) {
  try {
    if (section === "dashboard") await loadDashboard();
    if (section === "assignments") await loadAssignments();
    if (section === "resources") await loadResources();
    if (section === "inbox") await loadInbox();
    if (section === "submissions") await loadSubmissions();
    if (section === "teacher-room") await loadTeacherRoom();
    if (section === "people") await loadPeople();
    if (section === "ai") await loadAi();
    if (section === "saved") await loadSaved();
  } catch (error) {
    toast(error.message, "error");
  }
}

function formToJson(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function resetForm(form) {
  form.reset();
}

async function submitMultipart(form, path, success) {
  const button = $("button[type='submit']", form);
  button.disabled = true;
  try {
    await api(path, { method: "POST", body: new FormData(form) });
    toast(success);
    resetForm(form);
    await loadSection(state.section);
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function init() {
  if (localStorage.getItem("genwise-theme") === "dark") {
    document.body.classList.add("dark");
  }
  $$(".segmented button").forEach((button) => {
    button.classList.toggle("active", button.dataset.resourceView === state.resourceView);
  });

  $("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const data = await api("/api/login", { method: "POST", body: JSON.stringify(formToJson(event.currentTarget)) });
      setSignedIn(data.user);
      setSection("dashboard");
    } catch (error) {
      toast(error.message, "error");
    }
  });

  $("#register-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      const data = await api("/api/register", { method: "POST", body: JSON.stringify(formToJson(form)) });
      toast(data.message || "Account requested.");
      form.reset();
    } catch (error) {
      toast(error.message, "error");
    }
  });

  $("#logout-button").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST", body: JSON.stringify({}) });
    setSignedOut();
  });

  $("#theme-toggle").addEventListener("click", () => {
    document.body.classList.toggle("dark");
    localStorage.setItem("genwise-theme", document.body.classList.contains("dark") ? "dark" : "light");
  });

  $("#jump-to-signup").addEventListener("click", () => {
    const nameInput = $("#register-form input[name=\"name\"]");
    nameInput.scrollIntoView({ behavior: "smooth", block: "center" });
    nameInput.focus();
  });

  $("#top-signup-button").addEventListener("click", () => {
    $("#signup-dialog").showModal();
    $("#top-signup-form input[name=\"name\"]").focus();
  });

  $("#close-signup-dialog").addEventListener("click", () => $("#signup-dialog").close());

  $("#account-button").addEventListener("click", () => {
    $("#account-name").textContent = state.user?.name || "Account";
    $("#account-email").textContent = `${state.user?.email || ""} · ${state.user?.role || ""}`;
    $("#account-dialog").showModal();
  });

  $("#close-account-dialog").addEventListener("click", () => $("#account-dialog").close());

  $("#top-signup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $("button[type=\"submit\"]", form);
    button.disabled = true;
    try {
      const data = await api("/api/register", { method: "POST", body: JSON.stringify(formToJson(form)) });
      toast(data.message || "Account requested.");
      form.reset();
      $("#signup-dialog").close();
      if (state.user?.role === "teacher" && state.section === "people") {
        await loadPeople();
      }
      if (state.section === "dashboard") {
        await loadDashboard();
      }
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("#password-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = formToJson(form);
    const button = $("button[type=\"submit\"]", form);
    button.disabled = true;
    try {
      const result = await api("/api/account/password", {
        method: "POST",
        body: JSON.stringify(data),
      });
      toast(result.message || "Password updated.");
      form.reset();
      $("#account-dialog").close();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $$(".nav-button").forEach((button) => {
    button.addEventListener("click", () => setSection(button.dataset.section));
  });

  $("#resource-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitMultipart(
      event.currentTarget,
      "/api/resources",
      state.user?.role === "teacher" ? "Resource published." : "Resource sent to teachers for review."
    );
  });

  $("#assignment-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitMultipart(event.currentTarget, "/api/assignments", "Assignment posted.");
  });

  $("#assignment-search-button").addEventListener("click", () => loadAssignments());
  $("#assignment-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadAssignments();
    }
  });

  $("#resource-search-button").addEventListener("click", () => loadResources());
  $("#resource-search").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadResources();
    }
  });

  $$(".segmented button").forEach((button) => {
    button.addEventListener("click", () => {
      state.resourceView = button.dataset.resourceView;
      localStorage.setItem("genwise-resource-view", state.resourceView);
      $$(".segmented button").forEach((item) => item.classList.toggle("active", item === button));
      loadSection(state.section);
    });
  });

  $("#inbox-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitMultipart(event.currentTarget, "/api/inbox", "Inbox message posted.");
  });

  $("#submission-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitMultipart(event.currentTarget, "/api/submissions", "Submission sent to teachers.");
  });

  $("#teacher-room-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitMultipart(event.currentTarget, "/api/teacher-room", "Teacher room item saved.");
  });

  $("#ai-profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/ai/profile", { method: "POST", body: JSON.stringify(formToJson(event.currentTarget)) });
      toast("AI Assistant settings saved.");
    } catch (error) {
      toast(error.message, "error");
    }
  });

  $("#ai-chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const message = form.message.value.trim();
    if (!message) return;
    form.message.value = "";
    const existing = $$(".ai-bubble", $("#ai-messages")).map((node) => ({
      role: node.classList.contains("user") ? "user" : "assistant",
      content: node.textContent,
      citations_json: "[]",
    }));
    renderAiMessages([...existing, { role: "user", content: message, citations_json: "[]" }]);
    try {
      await api("/api/ai/chat", { method: "POST", body: JSON.stringify({ message }) });
      await loadAi();
    } catch (error) {
      toast(error.message, "error");
    }
  });

  $("#notification-button").addEventListener("click", async () => {
    await loadNotifications();
    $("#notifications-dialog").showModal();
    await api("/api/notifications", { method: "POST", body: JSON.stringify({}) });
    $("#notification-count").textContent = "0";
  });
  $("#close-notifications-dialog").addEventListener("click", () => $("#notifications-dialog").close());
  $("#close-submission-dialog").addEventListener("click", () => $("#submission-dialog").close());

  document.addEventListener("submit", async (event) => {
    const replyForm = event.target.closest("[data-inbox-reply]");
    if (replyForm) {
      event.preventDefault();
      const body = replyForm.body.value.trim();
      if (!body) return;
      try {
        await api(`/api/inbox/${replyForm.dataset.inboxReply}/reply`, {
          method: "POST",
          body: JSON.stringify({ body }),
        });
        await loadInbox();
      } catch (error) {
        toast(error.message, "error");
      }
      return;
    }

    const commentForm = event.target.closest("#teacher-comment-form");
    if (commentForm) {
      event.preventDefault();
      const body = commentForm.body.value.trim();
      if (!body) return;
      try {
        await api(`/api/submissions/${commentForm.dataset.submission}/comments`, {
          method: "POST",
          body: JSON.stringify({ body }),
        });
        toast("Teacher comment added.");
        $("#submission-dialog").close();
        await loadSubmissions();
        await openSubmission(commentForm.dataset.submission);
      } catch (error) {
        toast(error.message, "error");
      }
    }
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;

    try {
      if (button.dataset.jump) setSection(button.dataset.jump);
      if (button.dataset.startSubmission) {
        state.pendingAssignmentId = button.dataset.startSubmission;
        setSection("submissions");
      }
      if (button.dataset.openSubmission) await openSubmission(button.dataset.openSubmission);
      if (button.dataset.saveAssignment) {
        await api(`/api/assignments/${button.dataset.saveAssignment}/save`, { method: "POST", body: JSON.stringify({}) });
        await loadSection(state.section);
      }
      if (button.dataset.unsaveAssignment) {
        await api(`/api/assignments/${button.dataset.unsaveAssignment}/save`, { method: "DELETE" });
        await loadSection(state.section);
      }
      if (button.dataset.deleteAssignment) {
        if (!confirm("Archive this assignment?")) return;
        await api(`/api/assignments/${button.dataset.deleteAssignment}`, { method: "DELETE" });
        await loadSection(state.section);
      }
      if (button.dataset.pinAssignment) {
        await api(`/api/assignments/${button.dataset.pinAssignment}`, {
          method: "PATCH",
          body: JSON.stringify({ pinned: button.dataset.pinned !== "1" }),
        });
        await loadSection(state.section);
      }
      if (button.dataset.statusAssignment) {
        await api(`/api/assignments/${button.dataset.statusAssignment}`, {
          method: "PATCH",
          body: JSON.stringify({ status: button.dataset.status }),
        });
        await loadSection(state.section);
      }
      if (button.dataset.save) {
        await api(`/api/resources/${button.dataset.save}/save`, { method: "POST", body: JSON.stringify({}) });
        await loadSection(state.section);
      }
      if (button.dataset.unsave) {
        await api(`/api/resources/${button.dataset.unsave}/save`, { method: "DELETE" });
        await loadSection(state.section);
      }
      if (button.dataset.deleteResource) {
        if (!confirm("Delete this resource for everyone?")) return;
        await api(`/api/resources/${button.dataset.deleteResource}`, { method: "DELETE" });
        await loadSection(state.section);
      }
      if (button.dataset.pinResource) {
        await api(`/api/resources/${button.dataset.pinResource}`, {
          method: "PATCH",
          body: JSON.stringify({ pinned: button.dataset.pinned !== "1" }),
        });
        await loadSection(state.section);
      }
      if (button.dataset.reviewAction) {
        const reviewId = button.dataset.reviewAction;
        const action = button.dataset.action;
        if (action === "delete" && !confirm("Delete this student resource upload?")) return;
        if (action === "publish" && !confirm("Publish this student upload for the whole class?")) return;
        const comment = $(`[data-review-comment="${reviewId}"]`)?.value || "";
        await api(`/api/resource-reviews/${reviewId}`, {
          method: "PATCH",
          body: JSON.stringify({ action, teacher_comment: comment }),
        });
        toast("Student resource upload updated.");
        await loadSection(state.section);
      }
      if (button.dataset.deleteInbox) {
        if (!confirm("Delete this inbox post?")) return;
        await api(`/api/inbox/${button.dataset.deleteInbox}`, { method: "DELETE" });
        await loadInbox();
      }
      if (button.dataset.pinInbox) {
        await api(`/api/inbox/${button.dataset.pinInbox}`, {
          method: "PATCH",
          body: JSON.stringify({ pinned: button.dataset.pinned !== "1" }),
        });
        await loadInbox();
      }
      if (button.dataset.deleteTeacherItem) {
        if (!confirm("Delete this teacher-room item?")) return;
        await api(`/api/teacher-room/${button.dataset.deleteTeacherItem}`, { method: "DELETE" });
        await loadTeacherRoom();
      }
      if (button.dataset.pinTeacherItem) {
        await api(`/api/teacher-room/${button.dataset.pinTeacherItem}`, {
          method: "PATCH",
          body: JSON.stringify({ pinned: button.dataset.pinned !== "1" }),
        });
        await loadTeacherRoom();
      }
      if (button.dataset.approveUser) {
        await api(`/api/users/${button.dataset.approveUser}`, {
          method: "PATCH",
          body: JSON.stringify({ approved: 1 }),
        });
        await loadPeople();
        if (state.section === "dashboard") await loadDashboard();
      }
      if (button.dataset.disableUser) {
        await api(`/api/users/${button.dataset.disableUser}`, {
          method: "PATCH",
          body: JSON.stringify({ disabled: button.dataset.disabled !== "1", approved: 1 }),
        });
        await loadPeople();
      }
      if (button.dataset.roleUser) {
        await api(`/api/users/${button.dataset.roleUser}`, {
          method: "PATCH",
          body: JSON.stringify({ role: button.dataset.role === "teacher" ? "student" : "teacher", approved: 1 }),
        });
        await loadPeople();
      }
    } catch (error) {
      toast(error.message, "error");
    }
  });

  try {
    const data = await api("/api/me");
    if (data.user) {
      setSignedIn(data.user);
      setSection("dashboard");
    } else {
      setSignedOut();
    }
  } catch {
    setSignedOut();
  }
}

init();
