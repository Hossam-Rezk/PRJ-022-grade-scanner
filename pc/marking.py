"""Turns a sheet photo into marks: straighten the page, cut out each answer,
read the handwriting, compare with the model answer, write results.json.

Sheets are marked one at a time by a background worker, so scanning never
waits for the (slower) reading and marking."""
import os
import queue
import threading
import traceback

import cv2
from PIL import Image

import grader
import ocr
import settings as S
import sheet
import storage

BLANK_INK = 0.004        # a line with less ink than this is treated as empty

_jobs = queue.Queue()
state = {"models": "not loaded", "error": None, "busy": False}


# ------------------------------------------------------------------ marks
def mark_points(question, text):
    """Fresh verdicts for every key point of a question."""
    text = (text or "").strip()
    if not text:
        return [{"verdict": "blank", "confidence": 1.0, "probs": {}, "override": None}
                for _ in question["points"]]
    verdicts = grader.get_grader().classify([(text, p["text"]) for p in question["points"]])
    for v in verdicts:
        v["override"] = None
    return verdicts


def summarise(answer, question):
    """Work out marks, overall verdict and the review flag from the key points."""
    marks, effective, unsure = 0.0, [], False
    for point, result in zip(question["points"], answer["points"]):
        verdict = result.get("override") or result["verdict"]
        effective.append(verdict)
        if verdict == "supports":
            marks += point["marks"]
        if not result.get("override") and (verdict == "neither" or (
                verdict != "blank" and result["confidence"] < S.REVIEW_BELOW)):
            unsure = True
    if all(v == "blank" for v in effective):
        overall = "blank"
    elif "contradicts" in effective:
        overall = "contradicts"
    elif all(v == "supports" for v in effective):
        overall = "supports"
    elif "supports" in effective:
        overall = "partial"
    else:
        overall = "neither"
    answer.update(marks=marks, verdict=overall, flagged=unsure)
    return answer


def total(student):
    student["total"] = sum(a["marks"] for a in student["answers"].values())
    student["flags"] = sum(1 for a in student["answers"].values() if a["flagged"])


def regrade(results, student, qid, text):
    question = next(q for q in results["exam"]["questions"] if q["id"] == qid)
    answer = student["answers"][qid]
    answer["text"] = text.strip()
    answer["edited"] = answer["text"] != answer.get("ocr_text", "")
    answer["points"] = mark_points(question, answer["text"])
    summarise(answer, question)
    total(student)


def set_override(results, student, qid, index, verdict):
    question = next(q for q in results["exam"]["questions"] if q["id"] == qid)
    answer = student["answers"][qid]
    point = answer["points"][index]
    point["override"] = verdict if verdict and verdict != point["verdict"] else None
    if answer["text"]:
        storage.save_correction(answer["text"], question["points"][index]["text"], point["override"])
    summarise(answer, question)
    total(student)


# ------------------------------------------------------------------ one sheet
def process(batch_id, filename):
    folder = storage.batch_dir(batch_id)
    image = cv2.imread(str(folder / filename))
    if image is None:
        raise sheet.SheetError("The photo could not be opened.")
    exam = storage.load_results(batch_id)["exam"]
    pages = sheet.layout(exam)
    page_index, warped = sheet.locate(image)
    if page_index >= len(pages):
        raise sheet.SheetError("This sheet is page %d, but the exam has %d page(s). "
                               "Was it printed for another exam?" % (page_index + 1, len(pages)))
    page = pages[page_index]
    os.makedirs(folder / "pages", exist_ok=True)
    os.makedirs(folder / "crops", exist_ok=True)
    cv2.imwrite(str(folder / "pages" / filename), warped, [cv2.IMWRITE_JPEG_QUALITY, 88])

    # collect every non-empty writing line, read them all in one go
    stem = os.path.splitext(filename)[0]
    line_images, owners = [], []
    if page_index == 0:
        x, y, w, h = page["name_box"]
        img, ink = sheet.clean(sheet.crop(warped, [x + 18, y + 1, w - 20, h - 2]))
        if ink >= BLANK_INK:
            line_images.append(Image.fromarray(img))
            owners.append("name")
    crops = {}
    for q in page["questions"]:
        crop_name = "crops/%s_%s.jpg" % (stem, q["id"])
        cv2.imwrite(str(folder / crop_name), sheet.crop(warped, q["write"]),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
        crops[q["id"]] = crop_name
        for rect in q["lines"]:
            img, ink = sheet.clean(sheet.crop(warped, rect))
            if ink >= BLANK_INK:
                line_images.append(Image.fromarray(img))
                owners.append(q["id"])
    state["models"] = "loading the handwriting reader" if ocr._reader is None else state["models"]
    texts = ocr.get_reader().read(line_images)
    state["models"] = "loading the classifier" if grader._grader is None else state["models"]
    grader.get_grader()
    state["models"] = "ready"
    read = {}
    for owner, text in zip(owners, texts):
        read[owner] = (read.get(owner, "") + " " + text).strip()

    by_id = {q["id"]: q for q in exam["questions"]}
    answers = {}
    for q in page["questions"]:
        text = read.get(q["id"], "")
        answer = {"text": text, "ocr_text": text, "edited": False, "crop": crops[q["id"]],
                  "points": mark_points(by_id[q["id"]], text)}
        answers[q["id"]] = summarise(answer, by_id[q["id"]])

    with storage.LOCK:
        results = storage.load_results(batch_id)
        students = results["students"]
        if page_index == 0 or not students:
            student = {"id": len(students) + 1, "name": read.get("name", ""),
                       "sheets": [], "answers": {}}
            students.append(student)
        else:
            student = students[-1]
        student["sheets"].append(filename)
        student["answers"].update(answers)
        total(student)
        for s in results["sheets"]:
            if s["file"] == filename:
                s.update(status="done", page=page_index + 1, student=student["id"])
        storage.save_results(batch_id, results)


def _fail(batch_id, filename, message):
    with storage.LOCK:
        results = storage.load_results(batch_id)
        for s in results["sheets"]:
            if s["file"] == filename:
                s.update(status="error", error=message)
        storage.save_results(batch_id, results)


def _worker():
    while True:
        batch_id, filename = _jobs.get()
        state["busy"] = True
        try:
            process(batch_id, filename)
            state["error"] = None
        except sheet.SheetError as e:
            _fail(batch_id, filename, str(e))
        except Exception as e:                       # keep the worker alive
            traceback.print_exc()
            state["error"] = "%s: %s" % (type(e).__name__, e)
            try:
                _fail(batch_id, filename, "Marking failed: %s" % e)
            except Exception:
                pass
        finally:
            state["busy"] = False
            _jobs.task_done()


def enqueue(batch_id, filename, warning=""):
    with storage.LOCK:
        results = storage.load_results(batch_id)
        results["sheets"].append({"file": filename, "status": "queued", "warning": warning})
        storage.save_results(batch_id, results)
    _jobs.put((batch_id, filename))


def requeue_unfinished():
    """After a restart, pick up sheets that were scanned but not yet marked."""
    for b in storage.list_batches():
        if b["pending"]:
            for s in storage.load_results(b["id"])["sheets"]:
                if s["status"] == "queued":
                    _jobs.put((b["id"], s["file"]))


def pending():
    return _jobs.unfinished_tasks


def start():
    threading.Thread(target=_worker, daemon=True, name="marking").start()
    requeue_unfinished()
