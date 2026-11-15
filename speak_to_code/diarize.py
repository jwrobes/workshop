#!/usr/bin/env python
"""Diarize an audio file on-device with pyannote.audio. Prints speaker turns as JSON.

Uses the LOCAL Pipeline.from_pretrained path only — never the bundled pyannote.ai
cloud SDK — so no audio leaves the machine. Stdout is a JSON list of
{start, end, speaker}; all diagnostics go to stderr.

Run with the meeting venv's python (see setup.sh):
  ~/.local/share/dictate-diarize/.venv/bin/python diarize.py AUDIO.wav \
      [--device mps|cpu] [--num-speakers N | --min-speakers N --max-speakers N]
"""
import argparse
import json
import sys
import time

import torch
from pyannote.audio import Pipeline

MODEL = "pyannote/speaker-diarization-3.1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--device", default="mps", choices=["mps", "cpu"])
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--min-speakers", type=int, default=None)
    ap.add_argument("--max-speakers", type=int, default=None)
    args = ap.parse_args()
    if args.num_speakers and (args.min_speakers or args.max_speakers):
        ap.error("--num-speakers cannot be combined with --min-speakers/--max-speakers")

    pipeline = Pipeline.from_pretrained(MODEL)
    if pipeline is None:
        sys.exit(
            "diarize.py: could not load pyannote pipeline (returned None). Accept model "
            "terms on pyannote/speaker-diarization-3.1, pyannote/segmentation-3.0, and "
            "pyannote/speaker-diarization-community-1, then run `hf auth login`."
        )

    device = torch.device(args.device)
    try:
        pipeline.to(device)
    except Exception as e:  # MPS can lack ops on some setups; CPU always works.
        print(f"diarize.py: {args.device} unavailable ({e}); falling back to cpu", file=sys.stderr)
        device = torch.device("cpu")
        pipeline.to(device)

    kwargs = {}
    if args.num_speakers:
        kwargs["num_speakers"] = args.num_speakers
    if args.min_speakers:
        kwargs["min_speakers"] = args.min_speakers
    if args.max_speakers:
        kwargs["max_speakers"] = args.max_speakers

    t0 = time.time()
    result = pipeline(args.audio, **kwargs)
    # pyannote 4.x returns a DiarizeOutput wrapper; older returns an Annotation directly.
    annotation = getattr(result, "speaker_diarization", result)

    turns = [
        {"start": round(turn.start, 3), "end": round(turn.end, 3), "speaker": spk}
        for turn, _, spk in annotation.itertracks(yield_label=True)
    ]
    n_spk = len({t["speaker"] for t in turns})
    print(
        f"diarize.py: {len(turns)} turns, {n_spk} speakers in {time.time() - t0:.1f}s on {device}",
        file=sys.stderr,
    )
    json.dump(turns, sys.stdout)


if __name__ == "__main__":
    main()
