"""PRJ-022 Grade Scanner - PC program (scanner.py)

Runs the scanning machine from the PC: tells the Pico to feed each exam sheet,
takes the photo with the webcam when the sheet is still, saves it, then tells
the Pico to push the sheet out. Every batch goes into its own folder with a
manifest.csv that the grading step (next phase) reads.

How to start it (in CMD, inside the folder that holds this file):
    python scanner.py --check              test the Pico link and the camera
    python scanner.py --preview            live camera view, to aim and focus the camera
    python scanner.py --name Math-midterm  scan a batch of sheets
    python scanner.py --console            type commands to the Pico by hand
    python scanner.py --simulate           try everything without any hardware
"""
import argparse
import csv
import datetime
import os
import sys
import time

# ============================ SETTINGS ============================
CAMERA_INDEX = 0            # 0 = first camera. Try 1 if the laptop's own camera opens.
CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
SETTLE_SECONDS = 0.5        # wait after the sheet stops, before taking the photo
FRAMES_TO_COMPARE = 5       # photos taken per sheet; the sharpest one is kept
BLURRY_BELOW = 60.0         # sharpness score under this gets a "blurry" warning
JPEG_QUALITY = 95
OUTPUT_FOLDER = "scans"
EXPECTED_LENGTH_MM = 297    # A4 fed short edge first
LENGTH_TOLERANCE_MM = 15    # longer than 297 + 15 -> "possible double sheet"
PICO_PORT = None            # None = find it by itself. Or write e.g. "COM5".
FEED_TIMEOUT_S = 30
# ==================================================================

PICO_USB_VENDOR = 0x2E8A    # Raspberry Pi


class PicoError(Exception):
    pass


# ------------------------------------------------------------------ Pico link
class PicoLink:
    """Talks to main.py on the Pico over the USB cable, one line at a time."""

    def __init__(self, port=None):
        try:
            import serial                       # pyserial
            import serial.tools.list_ports
        except ImportError:
            raise PicoError("pyserial is not installed. Run: python -m pip install pyserial")
        self.serial_mod = serial
        port = port or PICO_PORT or self.find_port()
        if not port:
            raise PicoError("No Pico found. Check the USB cable, and close Thonny "
                            "(only one program can use the Pico at a time).")
        try:
            self.ser = serial.Serial(port, 115200, timeout=0.2)
        except Exception as e:                  # port busy or vanished
            raise PicoError("Could not open %s: %s. Is Thonny still connected?" % (port, e))
        self.port = port
        self.events = []
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        for _ in range(3):
            try:
                reply = self.send("PING", timeout=2)
                if "PONG" in reply:
                    self.version = reply
                    return
            except PicoError:
                pass
        raise PicoError("The Pico on %s does not answer. Is main.py on the Pico? "
                        "Unplug and replug the Pico, then try again." % port)

    def find_port(self):
        from serial.tools import list_ports
        for p in list_ports.comports():
            if p.vid == PICO_USB_VENDOR:
                return p.device
        return None

    def send(self, command, timeout=5.0):
        """Send one command, return the OK/ERR reply. EVT lines are kept in self.events."""
        self.ser.write((command + "\n").encode())
        end = time.time() + timeout
        while time.time() < end:
            raw = self.ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            if line.startswith("EVT"):
                self.events.append(line)
                continue
            if line.startswith("ERR BUSY"):
                continue
            if line.startswith("OK") or line.startswith("ERR"):
                return line
            # anything else (an error printout from the Pico) is shown as-is
            print("  Pico says: " + line)
        raise PicoError("No answer to %s within %d s" % (command, timeout))

    def poll_events(self):
        while True:
            raw = self.ser.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").strip()
            if line.startswith("EVT"):
                self.events.append(line)
        ev, self.events = self.events, []
        return ev

    def stop(self):
        try:
            self.ser.write(b"STOP\n")
        except Exception:
            pass

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


class FakePico:
    """Behaves like the Pico for --simulate: a tray with a few sheets in it."""

    def __init__(self, sheets=3):
        self.port = "SIMULATED"
        self.version = "OK PONG PRJ-022 v1.0 (simulated)"
        self.sheets = sheets
        self.holding = False
        self.events = []

    def send(self, command, timeout=5.0):
        cmd = command.split()[0].upper() if command.split() else ""
        if cmd == "PING":
            return self.version
        if cmd == "FEED":
            if self.holding:
                return "ERR SHEET_PRESENT a sheet is already inside, send EJECT first"
            if self.sheets <= 0:
                return "ERR NO_PAPER IR1 sees no sheet"
            time.sleep(0.3)
            self.sheets -= 1
            self.holding = True
            return "OK FEED sheet ready under the camera"
        if cmd == "EJECT":
            if not self.holding:
                return "ERR NO_SHEET nothing to eject"
            time.sleep(0.2)
            self.holding = False
            return "OK EJECT length_mm=297.2"
        if cmd == "STATUS":
            return "OK STATUS state=%s ir=%d,0,%d,0 motors=off steps_per_mm=42.44 version=1.0" % (
                "HOLDING" if self.holding else "IDLE", 1 if self.sheets else 0,
                1 if self.holding else 0)
        if cmd == "SENSORS":
            return "OK SENSORS %d 0 %d 0" % (1 if self.sheets else 0, 1 if self.holding else 0)
        if cmd in ("LED", "BEEP", "MOTORS", "RESET", "STOP", "JOG", "HELP"):
            return "OK " + command
        return "ERR BAD_COMMAND unknown '%s', send HELP" % cmd

    def poll_events(self):
        # pretend someone refills the tray after a moment (for --simulate --wait)
        self.polls = getattr(self, "polls", 0) + 1
        if self.sheets == 0 and self.polls % 10 == 0 and self.polls <= 10:
            self.sheets = 2
            return ["EVT PAPER_IN"]
        return []

    def stop(self):
        pass

    def close(self):
        pass


# ------------------------------------------------------------------ camera
def sharpness(image):
    """Higher = sharper. Variance of the Laplacian on a smaller grey copy."""
    import cv2
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = grey.shape
    if w > 960:
        grey = cv2.resize(grey, (960, int(h * 960 / w)))
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


class Camera:
    def __init__(self, index=CAMERA_INDEX):
        import cv2
        self.cv2 = cv2
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        if not self.cap.isOpened():
            raise RuntimeError("Camera %d did not open. Is the webcam plugged in? "
                               "Try CAMERA_INDEX = 1 in scanner.py." % index)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        for _ in range(10):                     # let exposure and white balance settle
            self.cap.read()
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("The camera opened but gives no picture. Close other "
                               "programs that use it (Zoom, Teams, Camera app).")
        self.height, self.width = frame.shape[:2]

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("The camera stopped sending pictures. Check its USB cable.")
        return frame

    def capture_best(self, n=FRAMES_TO_COMPARE):
        for _ in range(3):                      # throw away frames buffered while moving
            self.cap.grab()
        best, best_score = None, -1.0
        for _ in range(max(1, n)):
            frame = self.read()
            score = sharpness(frame)
            if score > best_score:
                best, best_score = frame, score
        return best, best_score

    def close(self):
        self.cap.release()


class FakeCamera:
    """Draws a pretend bubble sheet, for --simulate."""

    def __init__(self, index=0):
        self.width, self.height = CAMERA_WIDTH, CAMERA_HEIGHT
        self.count = 0

    def read(self):
        import numpy as np
        import cv2
        img = np.full((self.height, self.width, 3), 40, np.uint8)
        x0, y0 = (self.width - 700) // 2, 40
        cv2.rectangle(img, (x0, y0), (x0 + 700, y0 + 990), (245, 245, 245), -1)
        cv2.putText(img, "SIMULATED SHEET %d" % (self.count + 1), (x0 + 40, y0 + 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (30, 30, 30), 3)
        rng = np.random.default_rng(self.count)
        for q in range(15):
            y = y0 + 150 + q * 55
            cv2.putText(img, str(q + 1), (x0 + 40, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (30, 30, 30), 2)
            pick = int(rng.integers(0, 4))
            for c in range(4):
                centre = (x0 + 140 + c * 90, y)
                cv2.circle(img, centre, 18, (30, 30, 30), 2)
                if c == pick:
                    cv2.circle(img, centre, 14, (30, 30, 30), -1)
        return img

    def capture_best(self, n=FRAMES_TO_COMPARE):
        img = self.read()
        self.count += 1
        return img, sharpness(img)

    def close(self):
        pass


# ------------------------------------------------------------------ helpers
def open_hardware(simulate):
    if simulate:
        return FakePico(), FakeCamera()
    pico = PicoLink()
    try:
        cam = Camera()
    except Exception:
        pico.close()
        raise
    return pico, cam


def check_length(length):
    if length <= 0:
        return ""
    if length > EXPECTED_LENGTH_MM + LENGTH_TOLERANCE_MM:
        return "possible double sheet (%.0f mm)" % length
    if length < EXPECTED_LENGTH_MM - LENGTH_TOLERANCE_MM:
        return "short sheet, folded or torn? (%.0f mm)" % length
    return ""


def ask(prompt):
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


# ------------------------------------------------------------------ modes
def run_check(simulate):
    print("PRJ-022 check")
    ok = True
    try:
        pico = FakePico() if simulate else PicoLink()
        print("  Pico ........ found on %s: %s" % (pico.port, pico.version))
        print("  Status ...... " + pico.send("STATUS"))
        print("  Sensors ..... " + pico.send("SENSORS") + "   (1 = sees paper)")
        pico.send("BEEP 1")
        pico.close()
    except PicoError as e:
        ok = False
        print("  Pico ........ PROBLEM: %s" % e)
    try:
        import cv2
        cam = FakeCamera() if simulate else Camera()
        img, score = cam.capture_best()
        path = "check_photo.jpg"
        cv2.imwrite(path, img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        print("  Camera ...... %d x %d, sharpness %.0f, saved %s" % (cam.width, cam.height,
                                                                  score, path))
        if cam.width < CAMERA_WIDTH:
            print("                (asked for %d x %d: the camera chose a smaller size)" % (
                CAMERA_WIDTH, CAMERA_HEIGHT))
        cam.close()
    except ImportError:
        ok = False
        print("  Camera ...... PROBLEM: OpenCV is not installed. Run: "
              "python -m pip install opencv-python")
    except Exception as e:
        ok = False
        print("  Camera ...... PROBLEM: %s" % e)
    print("RESULT: " + ("everything answered" if ok else "fix the PROBLEM lines above"))
    return 0 if ok else 1


def run_preview(simulate):
    import cv2
    cam = FakeCamera() if simulate else Camera()
    print("Preview: S = save a test photo, R = turn the guide box, Q = quit.")
    portrait = True
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    while True:
        frame = cam.read()
        score = sharpness(frame)
        view = frame.copy()
        h, w = view.shape[:2]
        gh = int(h * 0.92)
        gw = int(gh * 210 / 297) if portrait else int(gh * 297 / 210)
        gw = min(gw, int(w * 0.95))
        x0, y0 = (w - gw) // 2, (h - gh) // 2
        cv2.rectangle(view, (x0, y0), (x0 + gw, y0 + gh), (0, 200, 0), 3)
        cv2.line(view, (w // 2 - 20, h // 2), (w // 2 + 20, h // 2), (0, 200, 0), 2)
        cv2.line(view, (w // 2, h // 2 - 20), (w // 2, h // 2 + 20), (0, 200, 0), 2)
        colour = (0, 180, 0) if score >= BLURRY_BELOW else (0, 0, 255)
        cv2.putText(view, "%dx%d  sharpness %.0f" % (w, h, score), (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, colour, 2)
        cv2.putText(view, "S save   R turn box   Q quit", (20, h - 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        scale = min(1.0, 1280 / w)
        cv2.imshow("PRJ-022 camera preview", cv2.resize(view, (int(w * scale), int(h * scale))))
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("r"):
            portrait = not portrait
        if key == ord("s"):
            path = os.path.join(OUTPUT_FOLDER, "preview_%s.jpg" %
                                datetime.datetime.now().strftime("%H%M%S"))
            cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            print("Saved " + path)
    cam.close()
    cv2.destroyAllWindows()
    return 0


def run_console(simulate):
    pico = FakePico() if simulate else PicoLink()
    print("Connected to %s. Type a command (HELP for the list), or EXIT to quit." % pico.port)
    try:
        while True:
            cmd = input("pico> ").strip()
            if not cmd:
                for ev in pico.poll_events():
                    print("  " + ev)
                continue
            if cmd.lower() in ("exit", "quit", "q"):
                break
            timeout = FEED_TIMEOUT_S if cmd.split()[0].upper() in ("FEED", "EJECT", "JOG") else 5
            try:
                print("  " + pico.send(cmd, timeout=timeout))
            except PicoError as e:
                print("  " + str(e))
            for ev in pico.poll_events():
                print("  " + ev)
    except (EOFError, KeyboardInterrupt):
        pass
    pico.close()
    return 0


def run_batch(name, simulate, wait_for_paper, max_sheets):
    import cv2
    pico, cam = open_hardware(simulate)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "batch"
    folder = os.path.join(OUTPUT_FOLDER, "%s_%s" % (safe, stamp))
    os.makedirs(folder, exist_ok=True)
    manifest_path = os.path.join(folder, "manifest.csv")
    manifest = open(manifest_path, "w", newline="")
    writer = csv.writer(manifest)
    writer.writerow(["sheet", "file", "time", "length_mm", "sharpness", "warning"])
    print("Batch folder: " + folder)
    print("Pico: %s   Camera: %d x %d" % (pico.port, cam.width, cam.height))
    print("Press Ctrl+C to stop at any time.")
    print()
    pico.send("LED green")
    count, warnings = 0, 0
    try:
        while max_sheets is None or count < max_sheets:
            reply = pico.send("FEED", timeout=FEED_TIMEOUT_S)
            if reply.startswith("ERR NO_PAPER"):
                if not wait_for_paper:
                    print("Tray empty.")
                    break
                print("Tray empty. Put the next sheets in (Ctrl+C to finish)...")
                pico.send("LED yellow")
                while not any("PAPER_IN" in e for e in pico.poll_events()):
                    time.sleep(0.2)
                time.sleep(1.0)
                pico.send("LED green")
                continue
            if reply.startswith("ERR SHEET_PRESENT"):
                print("A sheet was already inside. Pushing it out (it is not saved).")
                reply = pico.send("EJECT", timeout=FEED_TIMEOUT_S)
                if reply.startswith("OK"):
                    continue
            if reply.startswith("ERR"):
                print("Pico: " + reply)
                if ask("Clear the paper path, then press Enter to go on (q = quit): ") == "q":
                    break
                pico.send("RESET")
                continue
            time.sleep(SETTLE_SECONDS)
            image, score = cam.capture_best()
            count += 1
            filename = "sheet_%03d.jpg" % count
            cv2.imwrite(os.path.join(folder, filename), image,
                        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            reply = pico.send("EJECT", timeout=FEED_TIMEOUT_S)
            length = 0.0
            notes = []
            if reply.startswith("OK") and "length_mm=" in reply:
                length = float(reply.split("length_mm=")[1].split()[0])
                if check_length(length):
                    notes.append(check_length(length))
            elif reply.startswith("ERR"):
                notes.append("eject problem: " + reply)
            if score < BLURRY_BELOW:
                notes.append("blurry (sharpness %.0f)" % score)
            warning = "; ".join(notes)
            writer.writerow([count, filename, datetime.datetime.now().isoformat(timespec="seconds"),
                             "%.1f" % length, "%.0f" % score, warning])
            manifest.flush()
            print("Sheet %3d  saved %s  length %5.1f mm  sharpness %4.0f  %s" % (
                count, filename, length, score, ("WARNING: " + warning) if warning else ""))
            if warning:
                warnings += 1
                pico.send("BEEP 2")
            if reply.startswith("ERR"):
                print("Pico: " + reply)
                if ask("Clear the paper path, then press Enter to go on (q = quit): ") == "q":
                    break
                pico.send("RESET")
    except KeyboardInterrupt:
        print()
        print("Stopped by you.")
        pico.stop()
        time.sleep(0.3)
    except PicoError as e:
        print("Lost contact with the Pico: %s" % e)
    finally:
        manifest.close()
        try:
            pico.send("MOTORS OFF")
            pico.send("LED green")
            if count:
                pico.send("BEEP 2")
        except Exception:
            pass
        pico.close()
        cam.close()
    print()
    print("Done: %d sheet(s) saved in %s (%d with warnings)." % (count, folder, warnings))
    print("The list of sheets is in %s" % manifest_path)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="PRJ-022 Grade Scanner - PC program")
    ap.add_argument("--check", action="store_true", help="test the Pico link and the camera")
    ap.add_argument("--preview", action="store_true", help="live camera view")
    ap.add_argument("--console", action="store_true", help="type commands to the Pico")
    ap.add_argument("--simulate", action="store_true", help="no hardware needed")
    ap.add_argument("--name", default="batch", help="name of this batch, e.g. Math-midterm")
    ap.add_argument("--wait", action="store_true",
                    help="when the tray is empty, wait for more paper instead of stopping")
    ap.add_argument("--count", type=int, default=None, help="stop after this many sheets")
    a = ap.parse_args(argv)
    try:
        if a.check:
            return run_check(a.simulate)
        if a.preview:
            return run_preview(a.simulate)
        if a.console:
            return run_console(a.simulate)
        return run_batch(a.name, a.simulate, a.wait, a.count)
    except PicoError as e:
        print("PROBLEM: %s" % e)
        return 1
    except RuntimeError as e:
        print("PROBLEM: %s" % e)
        return 1
    except ImportError as e:
        print("PROBLEM: a Python add-on is missing (%s). Run: "
              "python -m pip install pyserial opencv-python" % e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
