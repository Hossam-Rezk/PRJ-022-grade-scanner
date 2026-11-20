// PRJ-022 Grade Scanner - website logic (no build step, no libraries)
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n) => String(Math.round(n * 100) / 100);

const state = { tab: "exams", exams: [], exam: null, batches: [], batchId: null,
                results: null, resultsText: "", studentId: null, status: null };
const LABEL = { supports: "Supports", contradicts: "Contradicts", neither: "Neither",
                partial: "Partly supports", blank: "Blank" };

async function api(path, options = {}) {
  if (options.json !== undefined) {
    options.method = options.method || "POST";
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(options.json);
  }
  const r = await fetch("/api" + path, options);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (e) { /* not JSON */ }
    throw new Error(detail);
  }
  return r.json();
}

let toastTimer;
function toast(text, bad = false) {
  const t = $("#toast");
  t.textContent = text;
  t.className = bad ? "bad" : "";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, bad ? 6000 : 2500);
}
const fail = (e) => toast(e.message || String(e), true);

// ------------------------------------------------------------------ tabs
function showTab(name) {
  state.tab = name;
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((s) => { s.hidden = s.id !== "tab-" + name; });
  if (name === "scan") fillExamSelect();
  if (name === "review" || name === "results") loadBatches().catch(fail);
}
$("#tabs").addEventListener("click", (e) => {
  if (e.target.dataset.tab) showTab(e.target.dataset.tab);
});

// ------------------------------------------------------------------ exams
async function loadExams() {
  state.exams = await api("/exams");
  const list = $("#exam-list");
  list.innerHTML = state.exams.length ? state.exams.map((x) => `
    <button class="item ${state.exam && state.exam.id === x.id ? "active" : ""}" data-id="${esc(x.id)}">
      <span>${esc(x.title)}<small>${x.questions} question(s), ${num(x.marks)} marks</small></span>
    </button>`).join("") : '<div class="empty">No exams yet.</div>';
  fillExamSelect();
}

function fillExamSelect() {
  const sel = $("#scan-exam");
  const keep = sel.value;
  sel.innerHTML = state.exams.map((x) => `<option value="${esc(x.id)}">${esc(x.title)}</option>`).join("");
  if (keep) sel.value = keep;
}

const blankQuestion = () => ({ text: "", lines: 4, points: [{ text: "", marks: 1 }] });

function renderEditor() {
  const x = state.exam;
  const box = $("#exam-editor");
  if (!x) {
    box.innerHTML = '<div class="card empty">Choose an exam on the left, or create a new one.</div>';
    return;
  }
  const total = x.questions.reduce((s, q) => s + q.points.reduce((a, p) => a + (+p.marks || 0), 0), 0);
  box.innerHTML = `
  <div class="card stack">
    <div class="qmeta">
      <label>Exam title<input id="x-title" value="${esc(x.title)}" placeholder="e.g. Cells and Enzymes Quiz"></label>
      <label>Subject<input id="x-subject" value="${esc(x.subject || "Biology")}"></label>
    </div>
    ${x.questions.map((q, i) => `
    <div class="question" data-q="${i}">
      <div class="question-head"><h3>Question ${i + 1}</h3>
        <button class="btn small danger" data-act="del-q">Remove question</button></div>
      <div class="qmeta">
        <label>Question<textarea data-f="text" rows="2">${esc(q.text)}</textarea></label>
        <label>Answer lines on the sheet<input data-f="lines" type="number" min="1" max="12" value="${esc(q.lines)}"></label>
      </div>
      <label style="margin-bottom:4px">Model answer: one key point per row, with its marks</label>
      ${q.points.map((p, k) => `
      <div class="point" data-p="${k}">
        <input data-f="ptext" value="${esc(p.text)}" placeholder="A full sentence, e.g. Water enters the cell by osmosis.">
        <input data-f="marks" type="number" min="0.5" step="0.5" value="${esc(p.marks)}" title="Marks">
        <button class="btn small" data-act="del-p" title="Remove key point">Remove</button>
      </div>`).join("")}
      <button class="btn small" data-act="add-p">+ Add key point</button>
    </div>`).join("")}
    <button class="btn" data-act="add-q">+ Add question</button>
    <hr>
    <div class="row">
      <button class="btn primary" data-act="save">Save exam</button>
      ${x.id ? `<a class="btn" target="_blank" href="/api/exams/${esc(x.id)}/sheet.pdf">Print answer sheet (PDF)</a>
      <button class="btn danger" data-act="delete">Delete exam</button>` : ""}
      <span class="hint">Total: ${num(total)} marks</span>
    </div>
    <p class="hint">Write each key point as one complete sentence: the classifier compares the student's
      answer with it. Print the answer sheet again after any change to the questions or line counts,
      because the sheet layout changes with them.</p>
  </div>`;
}

function readEditor() {
  const x = state.exam;
  x.title = $("#x-title").value;
  x.subject = $("#x-subject").value;
  $$("#exam-editor .question").forEach((el) => {
    const q = x.questions[+el.dataset.q];
    q.text = $('[data-f="text"]', el).value;
    q.lines = +$('[data-f="lines"]', el).value || 4;
    $$(".point", el).forEach((pe) => {
      const p = q.points[+pe.dataset.p];
      p.text = $('[data-f="ptext"]', pe).value;
      p.marks = +$('[data-f="marks"]', pe).value || 0;
    });
  });
}

$("#exam-list").addEventListener("click", async (e) => {
  const item = e.target.closest(".item");
  if (!item) return;
  try {
    state.exam = await api("/exams/" + item.dataset.id);
    renderEditor();
    loadExams();
  } catch (err) { fail(err); }
});

$("#exam-new").addEventListener("click", () => {
  state.exam = { title: "", subject: "Biology", questions: [blankQuestion()] };
  renderEditor();
  loadExams();
});

$("#exam-editor").addEventListener("click", async (e) => {
  const act = e.target.dataset.act;
  if (!act) return;
  readEditor();
  const x = state.exam;
  const qEl = e.target.closest(".question");
  const q = qEl ? x.questions[+qEl.dataset.q] : null;
  try {
    if (act === "add-q") x.questions.push(blankQuestion());
    if (act === "del-q") x.questions.splice(+qEl.dataset.q, 1);
    if (act === "add-p") q.points.push({ text: "", marks: 1 });
    if (act === "del-p") q.points.splice(+e.target.closest(".point").dataset.p, 1);
    if (act === "save") {
      state.exam = await api("/exams", { json: x });
      toast("Exam saved.");
      await loadExams();
    }
    if (act === "delete") {
      if (!confirm('Delete the exam "' + x.title + '"? Batches already scanned keep their marks.')) return;
      await api("/exams/" + x.id, { method: "DELETE" });
      state.exam = null;
      await loadExams();
    }
    renderEditor();
  } catch (err) { fail(err); }
});

// ------------------------------------------------------------------ scan
$("#scan-start").addEventListener("click", async () => {
  const exam_id = $("#scan-exam").value;
  if (!exam_id) return toast("Create an exam first.", true);
  try {
    const r = await api("/scan/start", { json: { exam_id, name: $("#scan-name").value,
      simulate: $("#scan-source").value === "sim" } });
    state.batchId = r.batch;
    state.studentId = null;
    poll();
  } catch (err) { fail(err); }
});
$("#scan-stop").addEventListener("click", () => api("/scan/stop", { json: {} }).then(poll, fail));
$("#scan-resume").addEventListener("click", () => api("/scan/resume", { json: {} }).then(poll, fail));

$("#upload-go").addEventListener("click", async () => {
  const files = $("#upload-files").files;
  const exam_id = $("#scan-exam").value;
  if (!exam_id) return toast("Create an exam first.", true);
  if (!files.length) return toast("Choose one or more photos first.", true);
  const form = new FormData();
  form.append("exam_id", exam_id);
  form.append("name", $("#scan-name").value);
  for (const f of files) form.append("files", f);
  try {
    const r = await api("/batches/upload", { method: "POST", body: form });
    state.batchId = r.batch;
    state.studentId = null;
    $("#upload-files").value = "";
    toast("Photos received. Marking has started; see the Review tab.");
    poll();
  } catch (err) { fail(err); }
});

function renderStatus() {
  const s = state.status;
  if (!s) return;
  const chips = [];
  chips.push(s.pico.found ? `<span class="chip ok">Pico on ${esc(s.pico.port)}</span>`
                          : '<span class="chip">Pico not connected</span>');
  chips.push(s.classifier.fine_tuned ? '<span class="chip ok">Fine-tuned classifier</span>'
    : '<span class="chip warn" title="Train the model on Colab and put it in the model folder">General classifier (not fine-tuned yet)</span>');
  if (s.marking.error) chips.push(`<span class="chip bad" title="${esc(s.marking.error)}">Marking error</span>`);
  else if (s.marking.pending) chips.push(`<span class="chip warn">Marking ${s.marking.pending} sheet(s)${
    s.marking.models !== "ready" ? " - " + esc(s.marking.models) : ""}</span>`);
  $("#chips").innerHTML = chips.join("");

  const scan = s.scan;
  const running = scan.state === "running" || scan.state === "paused";
  $("#scan-start").hidden = running;
  $("#scan-stop").hidden = !running;
  $("#scan-resume").hidden = scan.state !== "paused";
  const msg = $("#scan-message");
  msg.className = "note" + (scan.state === "error" ? " bad" : scan.state === "paused" ? " warn" : "");
  msg.innerHTML = esc(scan.message) + (scan.state === "finished" && scan.batch
    ? ' <a href="#" id="go-review">Open in Review</a>' : "");
  if (scan.log.length) {
    const log = $("#scan-log");
    const text = scan.log.join("\n");
    if (log.textContent !== text) { log.textContent = text; log.scrollTop = log.scrollHeight; }
  }
  $("#scan-progress").innerHTML = `
    <div class="stat"><b>${scan.count}</b><span>sheets scanned</span></div>
    <div class="stat"><b>${s.marking.pending}</b><span>waiting to be marked</span></div>
    <div class="stat"><b>${esc(scan.state)}</b><span>scanner${scan.simulate ? " (simulation)" : ""}</span></div>`;
  if (s.marking.pending && s.marking.models !== "ready" && s.marking.models !== "not loaded") {
    $("#scan-progress").innerHTML += `<p class="hint" style="width:100%">${esc(s.marking.models)}:
      the first time, the models are downloaded (about 2 GB), which can take several minutes.</p>`;
  }
}
document.addEventListener("click", (e) => {
  if (e.target.id === "go-review") { e.preventDefault(); showTab("review"); }
});

// ------------------------------------------------------------------ batches
async function loadBatches() {
  state.batches = await api("/batches");
  if (!state.batchId || !state.batches.some((b) => b.id === state.batchId)) {
    state.batchId = state.batches.length ? state.batches[0].id : null;
  }
  const html = state.batches.map((b) =>
    `<option value="${esc(b.id)}">${esc(b.name)} - ${esc(b.exam)} (${esc(b.created.replace("T", " "))})</option>`
  ).join("") || '<option value="">No batches yet</option>';
  $$(".batch-select").forEach((sel) => {
    if (sel.dataset.html !== html) { sel.innerHTML = html; sel.dataset.html = html; }
    sel.value = state.batchId || "";
  });
  await loadResults(true);
}
$$(".batch-select").forEach((sel) => sel.addEventListener("change", () => {
  state.batchId = sel.value;
  state.studentId = null;
  loadBatches().catch(fail);
}));

async function loadResults(force = false) {
  if (!state.batchId) {
    state.results = null;
    renderReview();
    renderResults();
    return;
  }
  const r = await fetch("/api/batches/" + state.batchId);
  if (!r.ok) return;
  const text = await r.text();
  if (text === state.resultsText && !force) return;
  // do not redraw under the teacher's cursor
  if (!force && $("#student-detail").contains(document.activeElement) &&
      ["TEXTAREA", "INPUT", "SELECT"].includes(document.activeElement.tagName)) return;
  state.resultsText = text;
  state.results = JSON.parse(text);
  renderReview();
  renderResults();
}

const outOf = () => state.results.exam.questions.reduce(
  (s, q) => s + q.points.reduce((a, p) => a + p.marks, 0), 0);

// ------------------------------------------------------------------ review
function renderReview() {
  const r = state.results;
  const list = $("#student-list"), detail = $("#student-detail"), errors = $("#sheet-errors");
  if (!r) {
    list.innerHTML = "";
    errors.innerHTML = "";
    $("#review-summary").textContent = "";
    detail.innerHTML = '<div class="card empty">Nothing scanned yet. Go to the Scan tab first.</div>';
    return;
  }
  const waiting = r.sheets.filter((s) => s.status === "queued").length;
  const flags = r.students.reduce((s, x) => s + x.flags, 0);
  $("#review-summary").textContent = `${r.students.length} student(s), ${flags} answer(s) to check` +
    (waiting ? `, ${waiting} sheet(s) still being marked...` : "");
  if (!r.students.some((s) => s.id === state.studentId)) {
    state.studentId = r.students.length ? r.students[0].id : null;
  }
  list.innerHTML = r.students.map((s) => `
    <button class="item ${s.id === state.studentId ? "active" : ""}" data-id="${s.id}">
      <span>${esc(s.name || "Student " + s.id)}
        <small>${num(s.total)} / ${num(outOf())}${s.flags ? ` <span class="flag">- ${s.flags} to check</span>` : ""}</small></span>
    </button>`).join("") || `<div class="empty">${waiting ? "Marking the first sheet..." : "No students."}</div>`;
  const bad = r.sheets.filter((s) => s.status === "error");
  errors.innerHTML = bad.length ? `<hr><h3>Unreadable sheets</h3>` + bad.map((s) => `
    <p class="hint"><a target="_blank" href="/api/batches/${esc(r.id)}/file/${esc(s.file)}">${esc(s.file)}</a>:
    ${esc(s.error)}</p>`).join("") : "";

  const st = r.students.find((s) => s.id === state.studentId);
  if (!st) {
    detail.innerHTML = `<div class="card empty">${waiting ? "Marking in progress..." : "No student selected."}</div>`;
    return;
  }
  const file = (p) => `/api/batches/${esc(r.id)}/file/${esc(p)}`;
  detail.innerHTML = `
  <div class="stack">
    <div class="card">
      <div class="answer-head">
        <label style="flex:1;margin:0">Student name (as read from the sheet; correct it if needed)
          <input id="st-name" value="${esc(st.name)}" placeholder="Student ${st.id}"></label>
        <div style="text-align:right"><div class="total">${num(st.total)} / ${num(outOf())}</div>
          <span class="hint">${st.flags ? st.flags + " answer(s) to check" : "nothing to check"}</span></div>
      </div>
      <div class="pages">${st.sheets.map((f) =>
        `<a target="_blank" href="${file("pages/" + f)}" title="Open the scanned page"><img src="${file("pages/" + f)}" alt="Scanned page"></a>`).join("")}</div>
    </div>
    ${r.exam.questions.map((q, i) => {
      const a = st.answers[q.id];
      if (!a) return `<div class="answer"><b>Q${i + 1}. ${esc(q.text)}</b><p class="hint">This page has not been scanned for this student.</p></div>`;
      const qMarks = q.points.reduce((s, p) => s + p.marks, 0);
      return `
      <div class="answer ${a.flagged ? "flagged" : ""}" data-q="${esc(q.id)}">
        <div class="answer-head">
          <b>Q${i + 1}. ${esc(q.text)}</b>
          <span class="row" style="flex-wrap:nowrap">${a.flagged ? '<span class="flag">Check</span>' : ""}
            <span class="badge v-${esc(a.verdict)}">${LABEL[a.verdict] || esc(a.verdict)}</span>
            <b>${num(a.marks)} / ${num(qMarks)}</b></span>
        </div>
        <img class="crop" src="${file(a.crop)}" alt="The student's handwriting">
        <label>Recognised text${a.edited ? " (edited by you)" : ""}
          <textarea data-f="text" rows="2">${esc(a.text)}</textarea></label>
        <button class="btn small" data-act="retext">Save text and mark again</button>
        <div style="margin-top:10px">
        ${q.points.map((p, k) => {
          const pt = a.points[k];
          const eff = pt.override || pt.verdict;
          const model = pt.verdict === "blank" ? "no answer written"
            : `model: ${LABEL[pt.verdict].toLowerCase()}, ${Math.round(pt.confidence * 100)}% sure`;
          return `
          <div class="kp" data-p="${k}">
            <div>${esc(p.text)}<small>${model}${pt.override ? " - changed by you" : ""}</small></div>
            <select data-f="verdict" class="v-${esc(eff)}">
              ${eff === "blank" ? '<option value="" selected>Blank</option>' : ""}
              ${["supports", "contradicts", "neither"].map((v) =>
                `<option value="${v}" ${v === eff ? "selected" : ""}>${LABEL[v]}</option>`).join("")}
            </select>
            <div class="marks">${eff === "supports" ? num(p.marks) : 0} / ${num(p.marks)}</div>
          </div>`;
        }).join("")}
        </div>
      </div>`;
    }).join("")}
  </div>`;
}

$("#student-list").addEventListener("click", (e) => {
  const item = e.target.closest(".item");
  if (!item) return;
  state.studentId = +item.dataset.id;
  renderReview();
  window.scrollTo({ top: 0 });
});

async function sendAnswer(qid, body) {
  await api(`/batches/${state.batchId}/students/${state.studentId}/answers/${qid}`, { json: body });
  await loadResults(true);
}

$("#student-detail").addEventListener("click", async (e) => {
  if (e.target.dataset.act !== "retext") return;
  const card = e.target.closest(".answer");
  e.target.disabled = true;
  e.target.textContent = "Marking...";
  try {
    await sendAnswer(card.dataset.q, { text: $('[data-f="text"]', card).value });
    toast("Marked again.");
  } catch (err) { fail(err); loadResults(true); }
});

$("#student-detail").addEventListener("change", async (e) => {
  try {
    if (e.target.id === "st-name") {
      await api(`/batches/${state.batchId}/students/${state.studentId}`, { json: { name: e.target.value } });
      await loadResults(true);
    } else if (e.target.dataset.f === "verdict" && e.target.value) {
      const card = e.target.closest(".answer");
      await sendAnswer(card.dataset.q, { point: +e.target.closest(".kp").dataset.p, override: e.target.value });
    }
  } catch (err) { fail(err); }
});

// ------------------------------------------------------------------ results
function renderResults() {
  const r = state.results;
  const box = $("#results-table");
  const link = $("#export-link");
  link.hidden = !r;
  if (!r || !r.students.length) {
    box.innerHTML = '<div class="empty">No marks yet.</div>';
    return;
  }
  link.href = `/api/batches/${r.id}/export.csv`;
  const qs = r.exam.questions;
  const max = outOf();
  const avg = r.students.reduce((s, x) => s + x.total, 0) / r.students.length;
  box.innerHTML = `<div class="table-wrap"><table>
    <thead><tr><th>#</th><th>Student</th>${qs.map((q, i) =>
      `<th title="${esc(q.text)}">Q${i + 1}<br>/${num(q.points.reduce((s, p) => s + p.marks, 0))}</th>`).join("")}
      <th>Total<br>/${num(max)}</th><th>%</th><th>To check</th></tr></thead>
    <tbody>${r.students.map((s) => `<tr>
      <td>${s.id}</td><td>${esc(s.name || "Student " + s.id)}</td>
      ${qs.map((q) => {
        const a = s.answers[q.id];
        return a ? `<td><span class="badge v-${esc(a.verdict)}" title="${LABEL[a.verdict] || ""}">${num(a.marks)}</span></td>` : "<td>-</td>";
      }).join("")}
      <td class="t">${num(s.total)}</td><td>${max ? Math.round(100 * s.total / max) : 0}%</td>
      <td>${s.flags ? `<span class="flag">${s.flags}</span>` : ""}</td></tr>`).join("")}</tbody>
    <tfoot><tr><td colspan="${qs.length + 2}">Class average</td>
      <td>${num(avg)}</td><td>${max ? Math.round(100 * avg / max) : 0}%</td><td></td></tr></tfoot>
  </table></div>
  <p class="hint">Colours: green = supports the model answer, red = contradicts it, blue = partly
    supports, amber = neither, grey = blank.</p>`;
}

// ------------------------------------------------------------------ live updates
async function poll() {
  try {
    state.status = await api("/status");
    renderStatus();
    const live = state.status.marking.pending || state.status.scan.state === "running";
    if ((state.tab === "review" || state.tab === "results") && (live || state.wasLive)) {
      if (!state.batches.some((b) => b.id === state.batchId)) await loadBatches();
      else await loadResults();
    }
    state.wasLive = live;
  } catch (e) { /* server restarting; try again next time */ }
}

loadExams().then(async () => {
  if (state.exams.length) {
    state.exam = await api("/exams/" + state.exams[0].id);
    loadExams();
  }
  renderEditor();
}).catch(fail);
poll();
setInterval(poll, 1500);
