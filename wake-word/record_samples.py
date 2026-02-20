"""
Polly Wake Word - Sample Recorder
Records "Hey Polly" positive and negative samples for wake word training.

Usage:
    python record_samples.py positive    # Record "Hey Polly" samples
    python record_samples.py negative    # Record non-wake-word samples
    python record_samples.py review      # Listen back to recordings
"""

import sounddevice as sd
import soundfile as sf
import numpy as np
import sys
import os
import time
import glob

SAMPLE_RATE = 16000
CHANNELS = 1
DURATION = 2.0  # seconds per clip
SILENCE_PAD = 0.3  # seconds of silence before/after

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSITIVE_DIR = os.path.join(SCRIPT_DIR, "positive")
NEGATIVE_DIR = os.path.join(SCRIPT_DIR, "negative")

os.makedirs(POSITIVE_DIR, exist_ok=True)
os.makedirs(NEGATIVE_DIR, exist_ok=True)


def get_next_number(directory, prefix):
    existing = glob.glob(os.path.join(directory, f"{prefix}_*.wav"))
    if not existing:
        return 1
    numbers = []
    for f in existing:
        try:
            num = int(os.path.basename(f).replace(f"{prefix}_", "").replace(".wav", ""))
            numbers.append(num)
        except ValueError:
            pass
    return max(numbers) + 1 if numbers else 1


def record_clip():
    print("  Recording...", end="", flush=True)
    audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                   channels=CHANNELS, dtype='int16')
    sd.wait()
    print(" done!")
    return audio


def save_clip(audio, filepath):
    sf.write(filepath, audio, SAMPLE_RATE, subtype='PCM_16')


def play_clip(filepath):
    data, sr = sf.read(filepath, dtype='int16')
    sd.play(data, sr)
    sd.wait()


def show_level(audio):
    rms = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
    peak = np.max(np.abs(audio))
    bars = int(rms / 500)
    print(f"  Level: {'|' * min(bars, 40)} (peak: {peak}, rms: {rms:.0f})")
    if peak < 500:
        print("  WARNING: Very quiet! Speak louder or move closer to the mic.")
    return peak > 500


def record_positive():
    print("\n" + "=" * 60)
    print("  POSITIVE SAMPLE RECORDING - Say 'Hey Polly'")
    print("=" * 60)
    print(f"\nSamples folder: {POSITIVE_DIR}")

    existing = len(glob.glob(os.path.join(POSITIVE_DIR, "positive_*.wav")))
    print(f"Existing samples: {existing}")
    print("\nTips for GOOD positive samples:")
    print("  - Say 'Hey Polly' naturally, like you're talking to someone")
    print("  - Vary your tone: casual, excited, quiet, loud")
    print("  - Vary distance: close to mic, arm's length, across desk")
    print("  - Try slight variations: 'Hey Polly', 'Hey, Polly', 'Hey Polly?'")
    print("  - Record at least 100 samples total (more = better)")
    print("  - Get coworkers to say it too if possible (different voices)")
    print("\nPress ENTER to record, 'p' to playback last, 'q' to quit\n")

    num = get_next_number(POSITIVE_DIR, "positive")

    while True:
        cmd = input(f"  Sample #{num} > ").strip().lower()
        if cmd == 'q':
            break
        if cmd == 'p':
            last = num - 1
            path = os.path.join(POSITIVE_DIR, f"positive_{last:04d}.wav")
            if os.path.exists(path):
                print(f"  Playing {os.path.basename(path)}...")
                play_clip(path)
            else:
                print("  No previous sample to play.")
            continue

        # Countdown
        for i in [3, 2, 1]:
            print(f"  {i}...", end=" ", flush=True)
            time.sleep(0.5)
        print()

        audio = record_clip()
        good = show_level(audio)

        filepath = os.path.join(POSITIVE_DIR, f"positive_{num:04d}.wav")
        save_clip(audio, filepath)
        print(f"  Saved: {os.path.basename(filepath)}")

        if not good:
            print("  (Saved anyway - re-record if it was too quiet)")

        num += 1

    total = len(glob.glob(os.path.join(POSITIVE_DIR, "positive_*.wav")))
    print(f"\nTotal positive samples: {total}")
    if total < 100:
        print(f"  Recommendation: Record {100 - total} more for good accuracy.")


def record_negative():
    print("\n" + "=" * 60)
    print("  NEGATIVE SAMPLE RECORDING - Do NOT say 'Hey Polly'")
    print("=" * 60)
    print(f"\nSamples folder: {NEGATIVE_DIR}")

    existing = len(glob.glob(os.path.join(NEGATIVE_DIR, "negative_*.wav")))
    print(f"Existing samples: {existing}")
    print("\nWhat to record as NEGATIVE samples:")
    print("  - Normal conversation: 'How was your weekend?'")
    print("  - Similar sounds: 'Hey Holly', 'Hey Molly', 'Hey Bobby'")
    print("  - Common words: 'Probably', 'Policy', 'Jolly', 'Trolley'")
    print("  - Background noise: typing, chair moving, door closing")
    print("  - Silence / room tone (just let it record quietly)")
    print("  - Music, TV, or radio in background")
    print("  - Coughing, sneezing, laughing")
    print("  - Record at least 200 negative samples (more = fewer false wakes)")
    print("\nPress ENTER to record, 'p' to playback last, 'q' to quit\n")

    num = get_next_number(NEGATIVE_DIR, "negative")

    while True:
        cmd = input(f"  Sample #{num} > ").strip().lower()
        if cmd == 'q':
            break
        if cmd == 'p':
            last = num - 1
            path = os.path.join(NEGATIVE_DIR, f"negative_{last:04d}.wav")
            if os.path.exists(path):
                print(f"  Playing {os.path.basename(path)}...")
                play_clip(path)
            else:
                print("  No previous sample to play.")
            continue

        for i in [3, 2, 1]:
            print(f"  {i}...", end=" ", flush=True)
            time.sleep(0.5)
        print()

        audio = record_clip()
        show_level(audio)

        filepath = os.path.join(NEGATIVE_DIR, f"negative_{num:04d}.wav")
        save_clip(audio, filepath)
        print(f"  Saved: {os.path.basename(filepath)}")
        num += 1

    total = len(glob.glob(os.path.join(NEGATIVE_DIR, "negative_*.wav")))
    print(f"\nTotal negative samples: {total}")
    if total < 200:
        print(f"  Recommendation: Record {200 - total} more to reduce false wakes.")


def review_samples():
    print("\n" + "=" * 60)
    print("  REVIEW SAMPLES")
    print("=" * 60)

    pos = sorted(glob.glob(os.path.join(POSITIVE_DIR, "positive_*.wav")))
    neg = sorted(glob.glob(os.path.join(NEGATIVE_DIR, "negative_*.wav")))

    print(f"\n  Positive samples: {len(pos)}")
    print(f"  Negative samples: {len(neg)}")
    print(f"\n  Target: 100+ positive, 200+ negative")

    if not pos and not neg:
        print("\n  No samples recorded yet!")
        return

    print("\n  'p' = positive samples, 'n' = negative samples, 'q' = quit")

    while True:
        cmd = input("\n  Review > ").strip().lower()
        if cmd == 'q':
            break

        samples = pos if cmd == 'p' else neg if cmd == 'n' else []
        if not samples:
            print("  Enter 'p' or 'n'")
            continue

        label = "positive" if cmd == 'p' else "negative"
        print(f"\n  Playing {len(samples)} {label} samples (ENTER=next, 'd'=delete, 'q'=stop)")

        for filepath in samples:
            name = os.path.basename(filepath)
            print(f"    {name}", end=" ", flush=True)
            play_clip(filepath)

            action = input("  > ").strip().lower()
            if action == 'q':
                break
            if action == 'd':
                os.remove(filepath)
                print(f"    DELETED {name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nPolly Wake Word Sample Recorder")
        print("-" * 40)
        print("Usage:")
        print("  python record_samples.py positive   Record 'Hey Polly' samples")
        print("  python record_samples.py negative   Record non-wake-word samples")
        print("  python record_samples.py review     Listen back & clean up")
        sys.exit(0)

    mode = sys.argv[1].lower()

    if mode == "positive":
        record_positive()
    elif mode == "negative":
        record_negative()
    elif mode == "review":
        review_samples()
    else:
        print(f"Unknown mode: {mode}")
        print("Use: positive, negative, or review")
