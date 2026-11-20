"""Plain-file storage: exams are JSON files, each batch is a folder with
its sheet photos, manifest.csv and results.json. No database."""
import csv
import datetime
import json
import os
import re
import threading

import settings as S

LOCK = threading.RLock()
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_LINES = 12


def check_id(value):
    if not isinstance(value, str) or not ID_RE.match(value):
        raise ValueError("bad id")
    return value


def slug(text, fallback="item"):
    out = re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-").lower()[:50]
    return out or fallback


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


# ------------------------------------------------------------------ exams
def clean_exam(raw):
    """Validate an exam coming from the website and return a tidy copy."""
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ValueError("The exam needs a title.")
    questions = []
    for n, q in enumerate(raw.get("questions") or [], 1):
        text = str(q.get("text") or "").strip()
        points = []
        for p in q.get("points") or []:
            ptext = str(p.get("text") or "").strip()
            if not ptext:
                continue
            try:
                marks = float(p.get("marks") or 0)
            except (TypeError, ValueError):
                marks = 0
            if marks <= 0:
                raise ValueError("Question %d: every key point needs marks above 0." % n)
            points.append({"text": ptext, "marks": marks})
        if not text:
            raise ValueError("Question %d has no question text." % n)
        if not points:
            raise ValueError("Question %d needs at least one model answer key point." % n)
        try:
            lines = int(q.get("lines") or 4)
        except (TypeError, ValueError):
            lines = 4
        questions.append({"id": "q%d" % n, "text": text,
                          "lines": max(1, min(MAX_LINES, lines)), "points": points})
    if not questions:
        raise ValueError("The exam needs at least one question.")
    exam = {"title": title, "subject": str(raw.get("subject") or "Biology").strip(),
            "questions": questions}
    if raw.get("sim_answers"):
        exam["sim_answers"] = raw["sim_answers"]
    return exam


def exam_path(exam_id):
    return S.EXAMS / (check_id(exam_id) + ".json")


def list_exams():
    out = []
    if S.EXAMS.is_dir():
        for p in sorted(S.EXAMS.glob("*.json")):
            exam = read_json(p)
            if exam:
                out.append({"id": p.stem, "title": exam.get("title", p.stem),
                            "questions": len(exam.get("questions", [])),
                            "marks": exam_marks(exam)})
    return out


def load_exam(exam_id):
    exam = read_json(exam_path(exam_id))
    if exam is None:
        raise KeyError(exam_id)
    exam["id"] = exam_id
    return exam


def save_exam(raw, exam_id=None):
    exam = clean_exam(raw)
    with LOCK:
        if not exam_id:
            base = slug(exam["title"], "exam")
            exam_id, k = base, 2
            while exam_path(exam_id).exists():
                exam_id, k = "%s-%d" % (base, k), k + 1
        write_json(exam_path(exam_id), exam)
    exam["id"] = exam_id
    return exam


def delete_exam(exam_id):
    path = exam_path(exam_id)
    if path.exists():
        path.unlink()


def exam_marks(exam):
    return sum(p["marks"] for q in exam.get("questions", []) for p in q.get("points", []))


# ------------------------------------------------------------------ batches
def batch_dir(batch_id):
    return S.SCANS / check_id(batch_id)


def new_batch(name, exam):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_id = "%s_%s" % (slug(name, "batch"), stamp)
    folder = batch_dir(batch_id)
    os.makedirs(folder, exist_ok=True)
    with open(folder / "manifest.csv", "w", newline="") as f:
        csv.writer(f).writerow(["sheet", "file", "time", "length_mm", "sharpness", "warning"])
    exam = {k: v for k, v in exam.items() if k != "sim_answers"}
    results = {"id": batch_id, "name": name or "batch",
               "created": datetime.datetime.now().isoformat(timespec="seconds"),
               "exam": exam, "sheets": [], "students": []}
    save_results(batch_id, results)
    return batch_id


def add_manifest_row(batch_id, row):
    with LOCK, open(batch_dir(batch_id) / "manifest.csv", "a", newline="") as f:
        csv.writer(f).writerow(row)


def load_results(batch_id):
    results = read_json(batch_dir(batch_id) / "results.json")
    if results is None:
        raise KeyError(batch_id)
    return results


def save_results(batch_id, results):
    with LOCK:
        write_json(batch_dir(batch_id) / "results.json", results)


def list_batches():
    out = []
    if S.SCANS.is_dir():
        for p in S.SCANS.iterdir():
            r = read_json(p / "results.json") if p.is_dir() else None
            if r:
                sheets = r.get("sheets", [])
                out.append({"id": r["id"], "name": r.get("name", ""), "created": r.get("created", ""),
                            "exam": r["exam"].get("title", ""), "sheets": len(sheets),
                            "pending": sum(1 for s in sheets if s["status"] == "queued"),
                            "students": len(r.get("students", []))})
    out.sort(key=lambda b: b["created"], reverse=True)
    return out


# ------------------------------------------------------------------ corrections
def save_correction(student_answer, reference_answer, label):
    """Remember a verdict the teacher corrected (label None removes it).
    The Colab notebook can train on this file."""
    with LOCK:
        rows = []
        if S.CORRECTIONS.exists():
            with open(S.CORRECTIONS, newline="", encoding="utf-8") as f:
                rows = [r for r in csv.reader(f)][1:]
        rows = [r for r in rows if r[:2] != [student_answer, reference_answer]]
        if label:
            rows.append([student_answer, reference_answer, label])
        os.makedirs(S.DATA, exist_ok=True)
        with open(S.CORRECTIONS, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["student_answer", "reference_answer", "label"])
            w.writerows(rows)
