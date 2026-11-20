"""Decides whether a student answer supports or contradicts a model answer.

The model reads the pair (student answer, model answer key point) and gives one
of three verdicts: supports, contradicts, neither. It uses the fine-tuned model
from the model folder when there is one (made by training/train_classifier.ipynb
on Colab), otherwise a general-purpose entailment model."""
import threading
import zipfile

import settings as S

VERDICTS = ("supports", "contradicts", "neither")
_lock = threading.Lock()
_grader = None


def verdict_of(label):
    name = str(label).lower()
    if "contra" in name:
        return "contradicts"
    if "entail" in name or "support" in name or name == "correct":
        return "supports"
    return "neither"


def _config_folder():
    for cfg in [S.MODEL_DIR / "config.json"] + sorted(S.MODEL_DIR.glob("*/config.json")):
        if cfg.exists():
            return cfg.parent
    return None


def find_model():
    """Folder of the fine-tuned model, or None. A zip dropped into the model
    folder is unpacked the first time."""
    if not S.MODEL_DIR.is_dir():
        return None
    folder = _config_folder()
    if folder is None:
        for z in sorted(S.MODEL_DIR.glob("*.zip")):
            with zipfile.ZipFile(z) as f:
                f.extractall(S.MODEL_DIR)
        folder = _config_folder()
    return folder


def describe():
    folder = find_model()
    if folder:
        return {"fine_tuned": True, "name": "Fine-tuned model (%s folder)" % folder.name}
    return {"fine_tuned": False, "name": S.FALLBACK_CLASSIFIER}


class Grader:
    def __init__(self):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        folder = find_model()
        source = str(folder) if folder else S.FALLBACK_CLASSIFIER
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(source)
        self.model = AutoModelForSequenceClassification.from_pretrained(source)
        self.model.eval()
        self.fine_tuned = folder is not None
        labels = self.model.config.id2label
        self.columns = [verdict_of(labels[i]) for i in range(len(labels))]
        if set(self.columns) != set(VERDICTS):
            raise RuntimeError("The classifier's labels %s are not the three expected verdicts."
                               % list(labels.values()))
        self.lock = threading.Lock()

    def classify(self, pairs):
        """pairs: list of (student answer, model answer). Returns one dict per
        pair: verdict, confidence, and the probability of each verdict."""
        if not pairs:
            return []
        with self.lock:
            enc = self.tokenizer([p[0] for p in pairs], [p[1] for p in pairs], padding=True,
                                 truncation=True, max_length=256, return_tensors="pt")
            with self.torch.no_grad():
                probs = self.model(**enc).logits.softmax(-1).tolist()
        out = []
        for row in probs:
            by = {v: 0.0 for v in VERDICTS}
            for column, p in zip(self.columns, row):
                by[column] += p
            best = max(by, key=by.get)
            out.append({"verdict": best, "confidence": round(by[best], 3),
                        "probs": {k: round(v, 3) for k, v in by.items()}})
        return out


def get_grader():
    global _grader
    with _lock:
        if _grader is None:
            _grader = Grader()
        return _grader
