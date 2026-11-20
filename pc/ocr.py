"""Reads handwriting. TrOCR reads one line of writing at a time, so the sheet
reader hands it one image per ruled line."""
import threading

import settings as S

_lock = threading.Lock()
_reader = None


class Reader:
    def __init__(self, name=S.OCR_MODEL):
        import torch
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        self.torch = torch
        self.processor = TrOCRProcessor.from_pretrained(name)
        self.model = VisionEncoderDecoderModel.from_pretrained(name)
        self.model.eval()
        self.name = name

    def read(self, images, batch=8):
        """images: list of PIL images, one line of writing each. Returns texts."""
        out = []
        for i in range(0, len(images), batch):
            chunk = [im.convert("RGB") for im in images[i:i + batch]]
            pixels = self.processor(images=chunk, return_tensors="pt").pixel_values
            with self.torch.no_grad():
                ids = self.model.generate(pixels, max_new_tokens=48)
            out += [t.strip() for t in self.processor.batch_decode(ids, skip_special_tokens=True)]
        return out


def get_reader():
    global _reader
    with _lock:
        if _reader is None:
            _reader = Reader()
        return _reader
