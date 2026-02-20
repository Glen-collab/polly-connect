"""
Test the Hey Polly wake word model against recorded samples.
Usage:
    pip install openwakeword soundfile numpy
    python test_model.py
"""

import os
import glob
import numpy as np
import soundfile as sf
from openwakeword.model import Model

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, "hey_polly.onnx")
POSITIVE_DIR = os.path.join(SCRIPT_DIR, "positive")
NEGATIVE_DIR = os.path.join(SCRIPT_DIR, "negative")

THRESHOLD = 0.5


def test_file(model, filepath):
    """Run wake word detection on a single file. Returns max score."""
    data, sr = sf.read(filepath, dtype='int16')
    chunk_size = 1280
    max_score = 0.0

    for i in range(0, len(data) - chunk_size, chunk_size):
        chunk = data[i:i + chunk_size]
        prediction = model.predict(chunk)
        score = list(prediction.values())[0]
        if score > max_score:
            max_score = score

    return max_score


def main():
    if not os.path.exists(MODEL_PATH):
        print(f"Model not found: {MODEL_PATH}")
        print("Make sure hey_polly.onnx is in the wake-word folder.")
        return

    print("Loading model...")
    model = Model(wakeword_models=[MODEL_PATH])
    print(f"Model loaded: {MODEL_PATH}\n")

    pos_files = sorted(glob.glob(os.path.join(POSITIVE_DIR, "*.wav")))
    neg_files = sorted(glob.glob(os.path.join(NEGATIVE_DIR, "*.wav")))

    print(f"Found {len(pos_files)} positive, {len(neg_files)} negative samples\n")

    # Test positive samples
    print("=" * 50)
    print("POSITIVE SAMPLES (should detect)")
    print("=" * 50)
    pos_detected = 0
    pos_scores = []
    for f in pos_files:
        score = test_file(model, f)
        pos_scores.append(score)
        detected = "YES" if score > THRESHOLD else "no"
        if score > THRESHOLD:
            pos_detected += 1
        print(f"  {os.path.basename(f)}: {score:.3f} - {detected}")

    # Test negative samples
    print(f"\n{'=' * 50}")
    print("NEGATIVE SAMPLES (should NOT detect)")
    print("=" * 50)
    neg_detected = 0
    neg_scores = []
    for f in neg_files:
        score = test_file(model, f)
        neg_scores.append(score)
        detected = "FALSE POSITIVE!" if score > THRESHOLD else "no"
        if score > THRESHOLD:
            neg_detected += 1
        print(f"  {os.path.basename(f)}: {score:.3f} - {detected}")

    # Summary
    print(f"\n{'=' * 50}")
    print("SUMMARY")
    print("=" * 50)
    if pos_files:
        recall = pos_detected / len(pos_files) * 100
        print(f"  Positive recall: {pos_detected}/{len(pos_files)} ({recall:.0f}%)")
        print(f"  Positive scores: min={min(pos_scores):.3f} max={max(pos_scores):.3f} avg={np.mean(pos_scores):.3f}")
    if neg_files:
        fp_rate = neg_detected / len(neg_files) * 100
        print(f"  False positives: {neg_detected}/{len(neg_files)} ({fp_rate:.0f}%)")
        print(f"  Negative scores: min={min(neg_scores):.3f} max={max(neg_scores):.3f} avg={np.mean(neg_scores):.3f}")

    print(f"\n  Threshold: {THRESHOLD}")
    if pos_files and len(pos_scores) > 0:
        if np.mean(pos_scores) < 0.1:
            print("\n  WARNING: Very low positive scores.")
            print("  Model needs retraining with more synthetic samples (Piper TTS).")
            print("  Current model was trained on only 96 real samples - need 5000+.")
        elif recall < 50:
            print("\n  WARNING: Low recall. Consider recording more samples and retraining.")
        else:
            print("\n  Model looks usable! Test with live mic next.")


if __name__ == "__main__":
    main()
