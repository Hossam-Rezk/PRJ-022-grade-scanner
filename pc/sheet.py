"""The printable answer sheet and how a photo of it is read back.

One function (layout) decides where everything sits on the A4 page, in
millimetres. The printer side draws that layout; the reading side finds the
four corner markers in the photo, straightens the page and cuts out the same
rectangles. Marker numbers also tell which page of the exam a sheet is."""
import io

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

A4_W, A4_H = 210.0, 297.0
MARKER = 14.0            # marker side, mm
INSET = 8.0              # marker distance from the paper edge, mm
LEFT, RIGHT = 12.0, 198.0
TOP, BOTTOM = 42.0, 271.0
LINE = 11.0              # height of one writing line, mm
GAP = 4.0                # space between question boxes, mm
PRINT = 300 / 25.4       # pixels per mm when printing (300 dpi)
READ = 8.0               # pixels per mm of the straightened photo
MAX_PAGES = 12           # 4 marker numbers per page, 50 markers in the set

RULE_GREY = (205, 205, 205)
_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_DETECTOR = cv2.aruco.ArucoDetector(_DICT, cv2.aruco.DetectorParameters())


class SheetError(Exception):
    pass


def px(mm):
    return int(round(mm * PRINT))


def _font(names, size_px):
    for name in names:
        try:
            return ImageFont.truetype(name, size_px)
        except OSError:
            pass
    return ImageFont.load_default(size_px)


def text_font(pt, bold=False):
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    return _font(names, int(pt * 300 / 72))


def hand_font(mm):
    return _font(["Inkfree.ttf", "segoesc.ttf", "arial.ttf"], px(mm))


def wrap(text, font, max_px):
    lines, current = [], ""
    for word in str(text).split():
        trial = (current + " " + word).strip()
        if current and font.getlength(trial) > max_px:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]


def marker_origin(corner):
    """Top-left of the marker in corner 0=TL 1=TR 2=BR 3=BL, in mm."""
    x = INSET if corner in (0, 3) else A4_W - INSET - MARKER
    y = INSET if corner in (0, 1) else A4_H - INSET - MARKER
    return x, y


# ------------------------------------------------------------------ layout
HEAD_PT = 10
HEAD_LINE = 4.6          # mm per line of question text


def layout(exam):
    """Where each question box and writing line sits. Returns a list of pages;
    all rectangles are [x, y, width, height] in mm."""
    font = text_font(HEAD_PT)
    pages = [{"name_box": [LEFT, 26.0, RIGHT - LEFT, 12.0], "questions": []}]
    y = TOP
    for n, q in enumerate(exam["questions"], 1):
        marks = sum(p["marks"] for p in q["points"])
        head = wrap("Q%d. %s  [%g mark%s]" % (n, q["text"], marks, "" if marks == 1 else "s"),
                    font, px(RIGHT - LEFT - 6))
        head_h = 3.0 + len(head) * HEAD_LINE
        height = head_h + q["lines"] * LINE + 3.0
        if y + height > BOTTOM and pages[-1]["questions"]:
            pages.append({"name_box": [LEFT, 26.0, RIGHT - LEFT, 12.0], "questions": []})
            y = TOP
        lines = []
        for k in range(q["lines"]):
            rule_y = y + head_h + (k + 1) * LINE
            lines.append([LEFT + 2, rule_y - LINE + 1.0, RIGHT - LEFT - 4, LINE + 1.5])
        pages[-1]["questions"].append({
            "id": q["id"], "box": [LEFT, y, RIGHT - LEFT, height], "head": head,
            "lines": lines, "write": [LEFT + 1, y + head_h, RIGHT - LEFT - 2, q["lines"] * LINE + 2.5],
            "rules": [y + head_h + (k + 1) * LINE for k in range(q["lines"])]})
        y += height + GAP
    if len(pages) > MAX_PAGES:
        raise SheetError("The exam needs %d pages; the most is %d." % (len(pages), MAX_PAGES))
    return pages


# ------------------------------------------------------------------ printing
def render_page(exam, pages, index, answers=None, name=None):
    """Draw page `index` at 300 dpi. `answers` ({question id: text}) and `name`
    are only used by the simulator, to fill the sheet in a handwriting font."""
    page = pages[index]
    img = Image.new("RGB", (px(A4_W), px(A4_H)), "white")
    d = ImageDraw.Draw(img)
    for corner in range(4):
        side = px(MARKER)
        m = cv2.aruco.generateImageMarker(_DICT, index * 4 + corner, side)
        x, y = marker_origin(corner)
        img.paste(Image.fromarray(m).convert("RGB"), (px(x), px(y)))
    d.text((px(28), px(9)), exam["title"], font=text_font(13, True), fill="black")
    d.text((px(28), px(16)), "%s   -   Page %d of %d   -   Write inside the boxes, on the lines." % (
        exam.get("subject", ""), index + 1, len(pages)), font=text_font(8), fill=(70, 70, 70))
    x, y, w, h = page["name_box"]
    d.rectangle([px(x), px(y), px(x + w), px(y + h)], outline="black", width=3)
    d.text((px(x + 2), px(y + 3.5)), "Name:", font=text_font(10, True), fill="black")
    hand = hand_font(6.0)
    ink = (25, 30, 95)
    if name:
        d.text((px(x + 20), px(y + h - 3)), name, font=hand, fill=ink, anchor="ls")
    head_font = text_font(HEAD_PT)
    for q in page["questions"]:
        x, y, w, h = q["box"]
        d.rectangle([px(x), px(y), px(x + w), px(y + h)], outline="black", width=3)
        for k, line in enumerate(q["head"]):
            d.text((px(x + 3), px(y + 2 + k * HEAD_LINE)), line, font=head_font, fill="black")
        for rule_y in q["rules"]:
            d.line([px(x + 3), px(rule_y), px(x + w - 3), px(rule_y)], fill=RULE_GREY, width=2)
        if answers and answers.get(q["id"]):
            written = wrap(answers[q["id"]], hand, px(w - 10))[:len(q["rules"])]
            for rule_y, line in zip(q["rules"], written):
                d.text((px(x + 4), px(rule_y - 1.5)), line, font=hand, fill=ink, anchor="ls")
    return img


def pdf_bytes(exam):
    pages = layout(exam)
    images = [render_page(exam, pages, i) for i in range(len(pages))]
    buf = io.BytesIO()
    images[0].save(buf, "PDF", resolution=300.0, save_all=True, append_images=images[1:])
    return buf.getvalue()


# ------------------------------------------------------------------ reading
def locate(image_bgr):
    """Find the corner markers in a photo. Returns (page index, straightened
    page as a BGR image at READ pixels per mm)."""
    grey = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _DETECTOR.detectMarkers(grey)
    if ids is None or len(ids) == 0:
        raise SheetError("No corner markers found. Is this the printed answer sheet, "
                         "fully inside the camera view?")
    by_page = {}
    for c, i in zip(corners, ids.flatten()):
        by_page.setdefault(int(i) // 4, {})[int(i) % 4] = c.reshape(4, 2)
    page, found = max(by_page.items(), key=lambda kv: len(kv[1]))
    if len(found) < 2:
        raise SheetError("Only one corner marker is visible; at least two are needed. "
                         "Move the camera so the whole sheet is in view.")
    src, dst = [], []
    for corner, pts in found.items():
        ox, oy = marker_origin(corner)
        for (dx, dy), p in zip(((0, 0), (MARKER, 0), (MARKER, MARKER), (0, MARKER)), pts):
            src.append(p)
            dst.append(((ox + dx) * READ, (oy + dy) * READ))
    H, _ = cv2.findHomography(np.array(src, np.float32), np.array(dst, np.float32))
    if H is None:
        raise SheetError("Could not straighten the sheet.")
    warped = cv2.warpPerspective(image_bgr, H, (int(A4_W * READ), int(A4_H * READ)),
                                 borderValue=(255, 255, 255))
    return page, warped


def crop(warped, rect):
    x, y, w, h = rect
    x0, y0 = max(0, int(x * READ)), max(0, int(y * READ))
    return warped[y0:int((y + h) * READ), x0:int((x + w) * READ)]


def clean(crop_bgr):
    """Even out the lighting and drop the pale ruled lines. Returns (grey image
    ready for the handwriting reader, share of pixels that are ink)."""
    grey = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    background = cv2.medianBlur(cv2.dilate(grey, np.ones((15, 15), np.uint8)), 21)
    ratio = grey.astype(np.float32) / np.maximum(background.astype(np.float32), 1.0)
    out = np.clip((ratio - 0.50) / (0.80 - 0.50), 0, 1) * 255
    mask = ratio < 0.62
    ink = float(mask.mean())
    # keep only the part of the line that has writing: the handwriting reader
    # invents text (often digits) when it is given a long empty stretch
    columns = np.flatnonzero(mask.sum(axis=0) >= 2)
    if columns.size:
        margin = int(2 * READ)
        out = out[:, max(0, columns[0] - margin):columns[-1] + margin + 1]
    return out.astype(np.uint8), ink
