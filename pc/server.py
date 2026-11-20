"""PRJ-022 Grade Scanner - the marking website (server.py)

Start it with start_server.bat, or:  python pc\\server.py
Then open http://127.0.0.1:8022 in the browser.
"""
import csv
import datetime
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
import uvicorn
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import grader
import marking
import scanjob
import settings as S
import sheet
import storage

app = FastAPI(title="PRJ-022 Grade Scanner")


def bad(message, code=400):
    raise HTTPException(code, message)


def get_exam(exam_id):
    try:
        return storage.load_exam(exam_id)
    except (KeyError, ValueError):
        bad("Exam not found.", 404)


def get_results(batch_id):
    try:
        return storage.load_results(batch_id)
    except (KeyError, ValueError):
        bad("Batch not found.", 404)


def get_student(results, student_id):
    for s in results["students"]:
        if s["id"] == student_id:
            return s
    bad("Student not found.", 404)


# ------------------------------------------------------------------ status
@app.get("/api/status")
def status():
    port = scanjob.pico_port()
    return {"pico": {"found": port is not None, "port": port},
            "classifier": grader.describe(),
            "reader": S.OCR_MODEL,
            "marking": {"pending": marking.pending(), "models": marking.state["models"],
                        "error": marking.state["error"]},
            "scan": scanjob.job.snapshot()}


# ------------------------------------------------------------------ exams
@app.get("/api/exams")
def exams():
    return storage.list_exams()


@app.get("/api/exams/{exam_id}")
def exam(exam_id: str):
    return get_exam(exam_id)


@app.post("/api/exams")
def exam_save(body: dict = Body(...)):
    exam_id = body.get("id") or None
    if exam_id:
        get_exam(exam_id)
    try:
        sheet.layout(storage.clean_exam(body))      # refuse an exam that cannot be printed
        saved = storage.save_exam(body, exam_id)
    except (ValueError, sheet.SheetError) as e:
        bad(str(e))
    return saved


@app.delete("/api/exams/{exam_id}")
def exam_delete(exam_id: str):
    get_exam(exam_id)
    storage.delete_exam(exam_id)
    return {"ok": True}


@app.get("/api/exams/{exam_id}/sheet.pdf")
def exam_sheet(exam_id: str):
    data = sheet.pdf_bytes(get_exam(exam_id))
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": 'inline; filename="answer-sheet-%s.pdf"' % exam_id})


# ------------------------------------------------------------------ scanning
@app.post("/api/scan/start")
def scan_start(body: dict = Body(...)):
    exam = get_exam(body.get("exam_id") or "")
    count = body.get("count")
    try:
        batch = scanjob.job.start(exam, str(body.get("name") or exam["title"]),
                                  bool(body.get("simulate")), int(count) if count else None)
    except (RuntimeError, sheet.SheetError) as e:
        bad(str(e))
    return {"batch": batch}


@app.post("/api/scan/stop")
def scan_stop():
    scanjob.job.stop()
    return {"ok": True}


@app.post("/api/scan/resume")
def scan_resume():
    scanjob.job.resume()
    return {"ok": True}


@app.post("/api/batches/upload")
async def upload(exam_id: str = Form(...), name: str = Form(""),
                 files: list[UploadFile] = File(...)):
    """Mark photos of answer sheets chosen from the PC instead of scanned."""
    exam = get_exam(exam_id)
    images = []
    for f in files:
        img = cv2.imdecode(np.frombuffer(await f.read(), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            bad("%s is not a picture." % f.filename)
        images.append(img)
    batch = storage.new_batch(name or exam["title"], exam)
    for n, img in enumerate(images, 1):
        filename = "sheet_%03d.jpg" % n
        cv2.imwrite(str(storage.batch_dir(batch) / filename), img,
                    [cv2.IMWRITE_JPEG_QUALITY, S.JPEG_QUALITY])
        storage.add_manifest_row(batch, [n, filename, datetime.datetime.now().isoformat(
            timespec="seconds"), "0.0", "0", "uploaded"])
        marking.enqueue(batch, filename)
    return {"batch": batch}


# ------------------------------------------------------------------ results
@app.get("/api/batches")
def batches():
    return storage.list_batches()


@app.get("/api/batches/{batch_id}")
def batch(batch_id: str):
    return get_results(batch_id)


@app.get("/api/batches/{batch_id}/file/{path:path}")
def batch_file(batch_id: str, path: str):
    get_results(batch_id)
    folder = storage.batch_dir(batch_id).resolve()
    target = (folder / path).resolve()
    if folder not in target.parents or target.suffix.lower() != ".jpg" or not target.is_file():
        bad("File not found.", 404)
    return FileResponse(target)


@app.post("/api/batches/{batch_id}/students/{student_id}")
def student_update(batch_id: str, student_id: int, body: dict = Body(...)):
    with storage.LOCK:
        results = get_results(batch_id)
        student = get_student(results, student_id)
        student["name"] = str(body.get("name") or "").strip()[:80]
        storage.save_results(batch_id, results)
    return student


@app.post("/api/batches/{batch_id}/students/{student_id}/answers/{qid}")
def answer_update(batch_id: str, student_id: int, qid: str, body: dict = Body(...)):
    """Either {"text": ...} to correct the recognised text (the answer is marked
    again), or {"point": 0, "override": "supports"} to correct one verdict."""
    with storage.LOCK:
        results = get_results(batch_id)
        student = get_student(results, student_id)
        if qid not in student["answers"]:
            bad("Answer not found.", 404)
        if "text" in body:
            marking.regrade(results, student, qid, str(body["text"]))
        else:
            verdict = body.get("override")
            index = body.get("point")
            if verdict not in (None,) + grader.VERDICTS or not isinstance(index, int) or \
                    not 0 <= index < len(student["answers"][qid]["points"]):
                bad("Bad verdict.")
            marking.set_override(results, student, qid, index, verdict)
        storage.save_results(batch_id, results)
    return student


@app.get("/api/batches/{batch_id}/export.csv")
def export(batch_id: str):
    results = get_results(batch_id)
    questions = results["exam"]["questions"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["student", "name"] + ["Q%d" % n for n in range(1, len(questions) + 1)] +
               ["total", "out_of", "needs_review"])
    out_of = storage.exam_marks(results["exam"])
    for s in results["students"]:
        w.writerow([s["id"], s["name"]] +
                   ["%g" % s["answers"][q["id"]]["marks"] if q["id"] in s["answers"] else ""
                    for q in questions] +
                   ["%g" % s["total"], "%g" % out_of, s["flags"]])
    return Response(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="%s.csv"' % batch_id})


app.mount("/", StaticFiles(directory=str(S.STATIC), html=True), name="static")


def main():
    os.makedirs(S.EXAMS, exist_ok=True)
    os.makedirs(S.SCANS, exist_ok=True)
    marking.start()
    print("PRJ-022 Grade Scanner: open http://%s:%d in the browser. Ctrl+C stops the server."
          % (S.HOST, S.PORT))
    if "--open" in sys.argv:
        import threading
        import webbrowser
        threading.Timer(1.5, webbrowser.open, ["http://%s:%d" % (S.HOST, S.PORT)]).start()
    uvicorn.run(app, host=S.HOST, port=S.PORT, log_level="warning")


if __name__ == "__main__":
    main()
