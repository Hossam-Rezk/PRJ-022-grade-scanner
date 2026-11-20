# PRJ-022 Grade Scanner: marking website

Scans handwritten biology answer sheets, reads the handwriting, and marks each answer by
deciding whether it **supports**, **contradicts**, or does **neither** for the teacher's
model answer.

## Get the code

The trained model weights (`model/prj022_model/model.safetensors`, about 330 MB) are stored with
Git LFS. Install it once with `git lfs install` before cloning; otherwise that file is only a small
pointer and the website falls back to the general-purpose model.

## Start

1. Plug the Pico into the laptop with the USB cable and close Thonny.
2. Double-click **`setup_pico.bat`** (once, or after changing the files in `pico`).
3. Double-click **`start_server.bat`**. The first run installs what it needs, then the
   website opens at http://127.0.0.1:8022.

The first time a sheet is marked, the handwriting reader and the classifier are downloaded
(about 2 GB). After that no internet is needed.

## Use

1. **Exams**: write the questions. Each model answer is one or more key points, each a
   full sentence with its marks. Print the answer sheet (PDF) at 100% scale on A4.
2. **Scan**: put the filled sheets in the tray and press Start. "Simulation" shows the
   whole flow with no hardware. Photos taken another way can be uploaded instead.
3. **Review**: check the answers flagged "Check". Correct the recognised text or change
   a verdict; the marks update.
4. **Results**: class table and CSV download.

Multi-page exams: scan each student's pages in order (page 1 first). Page 1 starts a new student.

## The included model

`model/prj022_model` is `cross-encoder/nli-distilroberta-base` fine-tuned for 2 epochs on
SciEntsBank and Beetle (SemEval-2013 Task 7) plus a small set of biology answer pairs
(9,015 training pairs). Results on answers never seen in training:

| Test set | Pairs | Accuracy | Macro F1 |
|---|---|---|---|
| SciEntsBank, unseen questions | 733 | 71.9% | 0.636 |
| SciEntsBank, unseen science topics | 4,562 | 67.4% | 0.626 |
| Biology check | 12 | 75.0% | 0.739 |

It is weakest on "contradicts", and still misses answers that use the right words in the wrong
roles, so the website flags uncertain answers for the teacher. Full per-label results are in
`model/prj022_model/test_results.txt`; the report source is `docs/report.html`.

## Train the classifier (Google Colab)

1. Open https://colab.research.google.com, **File > Upload notebook**, choose
   `training/train_classifier.ipynb`.
2. **Runtime > Change runtime type > T4 GPU**, then **Runtime > Run all**.
3. Put the downloaded `prj022_model.zip` into the `model` folder and restart the server.

The same notebook runs on Kaggle (Accelerator: GPU, Internet: on).

Until then the site uses a general-purpose entailment model. Verdicts you correct on the
Review tab are saved in `data/corrections.csv`; to train on them, copy those rows into
`BIOLOGY_TRAIN` in the notebook (S / C / N).

## Where things are (plain files, no database)

| Path | What |
|---|---|
| `data/exams/*.json` | one file per exam |
| `scans/<batch>/` | sheet photos, `manifest.csv`, `results.json` (text, verdicts, marks) |
| `data/corrections.csv` | verdicts the teacher corrected |
| `model/` | the fine-tuned classifier |
| `pc/settings.py` | port, model names, review threshold |
| `pc/scanner.py`, `pico/` | the original scanner program and Pico firmware, unchanged |
