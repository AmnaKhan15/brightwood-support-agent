"""Start a supervised fine-tuning job for a small Gemini model on Vertex AI.

    python finetune/launch_vertex.py --train gs://BUCKET/brightwood/train_vertex.jsonl --val gs://BUCKET/brightwood/val_vertex.jsonl
    python finetune/launch_vertex.py ... --submit      # actually start it (this costs money on your Google Cloud bill)

Before it: upload the files built by build_dataset.py, for example
    gcloud storage cp finetune/data/train_vertex.jsonl finetune/data/val_vertex.jsonl gs://BUCKET/brightwood/

Needs GOOGLE_CLOUD_PROJECT (and GOOGLE_CLOUD_LOCATION, default us-central1) and Google Cloud credentials
(`gcloud auth application-default login`). Without --submit it only prints the job it would start.
When the job finishes, serve the tuned model with GEMINI_USE_VERTEX=true and GEMINI_MODEL=<tuned endpoint>,
then run finetune/compare.py before switching any traffic to it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True, help="gs:// URI of train_vertex.jsonl")
    ap.add_argument("--val", help="gs:// URI of val_vertex.jsonl")
    ap.add_argument("--base", default=os.environ.get("TUNING_BASE_MODEL", "gemini-2.5-flash-lite"), help="the student model to tune")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--name", default="brightwood-support-student")
    ap.add_argument("--submit", action="store_true")
    args = ap.parse_args()

    manifest = ROOT / "finetune" / "data" / "manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text())
        if m.get("dry_run"):
            print("WARNING: the local dataset was built with --dry-run (offline teacher). Rebuild it with a real teacher first.", file=sys.stderr)
        print(f"dataset: {m['train']} train / {m['val']} val examples from teacher {m['teacher']}")
    for uri in filter(None, (args.train, args.val)):
        if not uri.startswith("gs://"):
            raise SystemExit(f"{uri} must be a gs:// URI (upload the file to Cloud Storage first)")

    job = {"base_model": args.base, "training_dataset": args.train, "validation_dataset": args.val,
           "epoch_count": args.epochs, "tuned_model_display_name": args.name,
           "project": os.environ.get("GOOGLE_CLOUD_PROJECT"), "location": os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")}
    print(json.dumps(job, indent=2))
    if not args.submit:
        print("\nDry run: nothing started. Add --submit to start this job.")
        return 0
    if not job["project"]:
        raise SystemExit("set GOOGLE_CLOUD_PROJECT")

    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=job["project"], location=job["location"])
    tuning = client.tunings.tune(
        base_model=args.base,
        training_dataset=types.TuningDataset(gcs_uri=args.train),
        config=types.CreateTuningJobConfig(
            epoch_count=args.epochs, tuned_model_display_name=args.name,
            validation_dataset=types.TuningValidationDataset(gcs_uri=args.val) if args.val else None),
    )
    print(f"started: {tuning.name}  state={tuning.state}")
    print("Check it with: gcloud ai tuning-jobs describe", tuning.name.split("/")[-1], "--region", job["location"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
