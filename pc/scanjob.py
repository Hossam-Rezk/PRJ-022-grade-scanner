"""Runs one scanning batch for the website, in a background thread.

Uses the Pico link and the camera from scanner.py unchanged. The loop is the
same as scanner.py's batch mode, except that problems are shown on the website
(with Continue / Stop buttons) instead of asked in the CMD window."""
import datetime
import threading
import time

import cv2
import numpy as np

import marking
import scanner
import settings as S
import sheet
import storage


class SimCamera:
    """Pretend camera: shows filled-in answer sheets for the chosen exam, as a
    1920 x 1080 photo with the sheet lying sideways and slightly crooked."""

    def __init__(self, exam):
        self.width, self.height = 1920, 1080
        pages = sheet.layout(exam)
        people = exam.get("sim_answers") or [
            {"name": "Model Student",
             "answers": {q["id"]: " ".join(p["text"] for p in q["points"])
                         for q in exam["questions"]}},
            {"name": "Blank Student", "answers": {}}]
        self.frames = []
        for n, person in enumerate(people):
            for i in range(len(pages)):
                page = sheet.render_page(exam, pages, i, person.get("answers"), person.get("name"))
                self.frames.append(self._photo(page, seed=n * 20 + i))
        self.count = 0

    def _photo(self, page, seed):
        rng = np.random.default_rng(seed)
        img = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        h = 1030
        w = int(img.shape[1] * h / img.shape[0])
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
        frame = np.full((self.height, self.width, 3), 45, np.uint8)
        x0, y0 = (self.width - w) // 2, (self.height - h) // 2
        frame[y0:y0 + h, x0:x0 + w] = img
        turn = cv2.getRotationMatrix2D((self.width / 2, self.height / 2),
                                       float(rng.uniform(-1.5, 1.5)), 0.97)
        frame = cv2.warpAffine(frame, turn, (self.width, self.height), borderValue=(45, 45, 45))
        frame = cv2.GaussianBlur(frame, (3, 3), 0)
        noise = rng.normal(0, 3, frame.shape)
        return np.clip(frame.astype(np.float32) * 0.93 + noise, 0, 255).astype(np.uint8)

    def capture_best(self, n=5):
        frame = self.frames[self.count % len(self.frames)]
        self.count += 1
        return frame, scanner.sharpness(frame)

    def close(self):
        pass


class ScanJob:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "idle"          # idle, running, paused, finished, error
        self.message = ""
        self.log = []
        self.batch = None
        self.count = 0
        self.simulate = False
        self.thread = None
        self._stop = threading.Event()
        self._resume = threading.Event()

    def snapshot(self):
        with self.lock:
            return {"state": self.state, "message": self.message, "log": self.log[-60:],
                    "batch": self.batch, "count": self.count, "simulate": self.simulate}

    def say(self, text):
        with self.lock:
            self.log.append("%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), text))

    def set(self, state, message=""):
        with self.lock:
            self.state, self.message = state, message
        if message:
            self.say(message)

    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, exam, name, simulate, max_sheets=None):
        if self.busy():
            raise RuntimeError("A scan is already running.")
        sheet.layout(exam)                       # fail early if the exam cannot be laid out
        self._stop.clear()
        self._resume.clear()
        with self.lock:
            self.log, self.count, self.simulate = [], 0, simulate
            self.batch = storage.new_batch(name, exam)
            self.state, self.message = "running", ""
        self.thread = threading.Thread(target=self._run, args=(exam, simulate, max_sheets),
                                       daemon=True, name="scan")
        self.thread.start()
        return self.batch

    def stop(self):
        self._stop.set()
        self._resume.set()

    def resume(self):
        self._resume.set()

    def _wait_for_teacher(self, pico, problem):
        """Pause until Continue or Stop is pressed. True = go on."""
        self.set("paused", problem + " Clear the paper path, then press Continue.")
        self._resume.clear()
        self._resume.wait()
        if self._stop.is_set():
            return False
        pico.send("RESET")
        self.set("running", "Continuing.")
        return True

    def _run(self, exam, simulate, max_sheets):
        pico = cam = None
        try:
            if simulate:
                cam = SimCamera(exam)
                pico = scanner.FakePico(sheets=len(cam.frames))
                pico.poll_events = lambda: []
            else:
                pico, cam = scanner.open_hardware(False)
            self.say("Pico: %s   Camera: %d x %d" % (pico.port, cam.width, cam.height))
            pico.send("LED green")
            while not self._stop.is_set() and (max_sheets is None or self.count < max_sheets):
                reply = pico.send("FEED", timeout=S.FEED_TIMEOUT_S)
                if reply.startswith("ERR NO_PAPER"):
                    self.say("Tray empty.")
                    break
                if reply.startswith("ERR SHEET_PRESENT"):
                    self.say("A sheet was already inside. Pushing it out (it is not saved).")
                    reply = pico.send("EJECT", timeout=S.FEED_TIMEOUT_S)
                    if reply.startswith("OK"):
                        continue
                if reply.startswith("ERR"):
                    if not self._wait_for_teacher(pico, "Pico: %s." % reply):
                        break
                    continue
                time.sleep(0 if simulate else S.SETTLE_SECONDS)
                image, score = cam.capture_best()
                number = self.count + 1
                filename = "sheet_%03d.jpg" % number
                cv2.imwrite(str(storage.batch_dir(self.batch) / filename), image,
                            [cv2.IMWRITE_JPEG_QUALITY, S.JPEG_QUALITY])
                reply = pico.send("EJECT", timeout=S.FEED_TIMEOUT_S)
                length, notes = 0.0, []
                if reply.startswith("OK") and "length_mm=" in reply:
                    length = float(reply.split("length_mm=")[1].split()[0])
                    if scanner.check_length(length):
                        notes.append(scanner.check_length(length))
                elif reply.startswith("ERR"):
                    notes.append("eject problem: " + reply)
                if score < scanner.BLURRY_BELOW:
                    notes.append("blurry (sharpness %.0f)" % score)
                warning = "; ".join(notes)
                storage.add_manifest_row(self.batch, [
                    number, filename, datetime.datetime.now().isoformat(timespec="seconds"),
                    "%.1f" % length, "%.0f" % score, warning])
                marking.enqueue(self.batch, filename, warning)
                with self.lock:
                    self.count = number
                self.say("Sheet %d saved%s" % (number, ("  WARNING: " + warning) if warning else ""))
                if warning:
                    pico.send("BEEP 2")
                if reply.startswith("ERR") and not self._wait_for_teacher(pico, "Pico: %s." % reply):
                    break
            if self._stop.is_set():
                pico.stop()
                time.sleep(0.3)
            self.set("finished", "Done: %d sheet(s) scanned%s." % (
                self.count, " (stopped by you)" if self._stop.is_set() else ""))
        except (scanner.PicoError, RuntimeError, ImportError, sheet.SheetError) as e:
            self.set("error", "PROBLEM: %s" % e)
        except Exception as e:
            self.set("error", "PROBLEM: %s: %s" % (type(e).__name__, e))
        finally:
            if pico is not None:
                try:
                    pico.send("MOTORS OFF")
                    pico.send("LED green")
                    if self.count:
                        pico.send("BEEP 2")
                except Exception:
                    pass
                pico.close()
            if cam is not None:
                cam.close()


def pico_port():
    """The Pico's USB serial port name, or None. Does not open the port."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for p in list_ports.comports():
        if p.vid == scanner.PICO_USB_VENDOR:
            return p.device
    return None


job = ScanJob()
