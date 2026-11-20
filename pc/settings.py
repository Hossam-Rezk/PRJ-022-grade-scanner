"""PRJ-022 Grade Scanner - settings for the marking website."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXAMS = DATA / "exams"                  # one JSON file per exam
CORRECTIONS = DATA / "corrections.csv"  # teacher corrections, reusable for training
SCANS = ROOT / "scans"                  # one folder per scanned batch
MODEL_DIR = ROOT / "model"              # the fine-tuned classifier from Colab goes here
STATIC = Path(__file__).resolve().parent / "static"

HOST = "127.0.0.1"
PORT = 8022

# Used until a fine-tuned model is placed in the model folder.
FALLBACK_CLASSIFIER = "cross-encoder/nli-distilroberta-base"
# Handwriting reader. "microsoft/trocr-small-handwritten" is faster but less accurate.
OCR_MODEL = "microsoft/trocr-base-handwritten"

REVIEW_BELOW = 0.60     # a verdict less confident than this is flagged for the teacher
FEED_TIMEOUT_S = 30
SETTLE_SECONDS = 0.5
JPEG_QUALITY = 95
