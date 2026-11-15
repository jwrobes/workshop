#!/usr/bin/env python
"""Merge mlx-whisper segments with pyannote diarization turns into an attributed transcript.

Each whisper segment is assigned to the diarized speaker whose turn overlaps it most;
consecutive same-speaker segments are coalesced into one labeled block.

  python merge.py WHISPER.json TURNS.json
Stdout: "SPEAKER_XX: text" blocks separated by blank lines.
"""
import json
import sys


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def assign(seg_start, seg_end, turns):
    best, best_ov = None, 0.0
    for t0, t1, spk in turns:
        ov = overlap(seg_start, seg_end, t0, t1)
        if ov > best_ov:
            best, best_ov = spk, ov
    if best is not None:
        return best
    # Segment falls in a diarization gap: attach to the nearest turn by midpoint.
    mid = (seg_start + seg_end) / 2
    return min(turns, key=lambda t: abs((t[0] + t[1]) / 2 - mid))[2]


def main():
    whisper = json.load(open(sys.argv[1]))
    segments = [(s["start"], s["end"], s["text"].strip()) for s in whisper["segments"]]

    turns_raw = json.load(open(sys.argv[2]))
    turns = [(t["start"], t["end"], t["speaker"]) for t in turns_raw]

    if not turns:  # Diarization found nothing: emit as a single anonymous block.
        print("SPEAKER_00: " + " ".join(t for _, _, t in segments if t))
        return

    labeled = [(assign(s, e, turns), text) for s, e, text in segments if text]

    blocks = []
    for spk, text in labeled:
        if blocks and blocks[-1][0] == spk:
            blocks[-1] = (spk, blocks[-1][1] + " " + text)
        else:
            blocks.append((spk, text))

    for spk, text in blocks:
        print(f"{spk}: {text}\n")


if __name__ == "__main__":
    main()
