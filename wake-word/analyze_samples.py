"""
Analyze wake word samples for quality and consistency.
Checks: volume levels, duration, silence ratio, frequency characteristics,
and separation between positive and negative samples.
"""

import numpy as np
import soundfile as sf
import os
import glob
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSITIVE_DIR = os.path.join(SCRIPT_DIR, "positive")
NEGATIVE_DIR = os.path.join(SCRIPT_DIR, "negative")


def analyze_file(filepath):
    """Analyze a single audio file."""
    try:
        data, sr = sf.read(filepath, dtype='int16')
    except Exception as e:
        return {"error": str(e), "file": os.path.basename(filepath)}

    float_data = data.astype(np.float32) / 32768.0
    duration = len(data) / sr

    # Volume metrics
    rms = np.sqrt(np.mean(float_data ** 2))
    peak = np.max(np.abs(float_data))
    db_rms = 20 * np.log10(rms + 1e-10)
    db_peak = 20 * np.log10(peak + 1e-10)

    # Silence analysis (frames below -40dB)
    frame_size = int(sr * 0.025)  # 25ms frames
    hop = int(sr * 0.010)  # 10ms hop
    silent_frames = 0
    total_frames = 0
    for i in range(0, len(float_data) - frame_size, hop):
        frame = float_data[i:i + frame_size]
        frame_rms = np.sqrt(np.mean(frame ** 2))
        frame_db = 20 * np.log10(frame_rms + 1e-10)
        total_frames += 1
        if frame_db < -40:
            silent_frames += 1

    silence_ratio = silent_frames / max(total_frames, 1)

    # Energy distribution (where is the speech?)
    thirds = np.array_split(float_data, 3)
    energy_per_third = [np.sqrt(np.mean(t ** 2)) for t in thirds]
    energy_total = sum(energy_per_third)
    energy_distribution = [e / max(energy_total, 1e-10) for e in energy_per_third]

    # Zero crossing rate (rough indicator of speech vs noise)
    zcr = np.sum(np.abs(np.diff(np.sign(float_data)))) / (2 * len(float_data))

    # Clipping detection
    clip_threshold = 0.95
    clipped_samples = np.sum(np.abs(float_data) > clip_threshold)
    clip_ratio = clipped_samples / len(float_data)

    return {
        "file": os.path.basename(filepath),
        "duration": duration,
        "sample_rate": sr,
        "rms": rms,
        "peak": peak,
        "db_rms": db_rms,
        "db_peak": db_peak,
        "silence_ratio": silence_ratio,
        "energy_distribution": energy_distribution,
        "zcr": zcr,
        "clip_ratio": clip_ratio,
    }


def flag_issues(result, sample_type):
    """Flag potential problems with a sample."""
    issues = []

    if "error" in result:
        return [f"BROKEN FILE: {result['error']}"]

    if result["db_rms"] < -35:
        issues.append("TOO QUIET (RMS < -35dB)")
    if result["db_rms"] > -5:
        issues.append("TOO LOUD (RMS > -5dB)")
    if result["clip_ratio"] > 0.001:
        issues.append(f"CLIPPING ({result['clip_ratio']*100:.1f}% samples clipped)")
    if result["silence_ratio"] > 0.85:
        if sample_type == "positive":
            issues.append("MOSTLY SILENCE (>85% - might not have speech)")
    if result["duration"] < 0.5:
        issues.append("TOO SHORT (<0.5s)")
    if result["sample_rate"] != 16000:
        issues.append(f"WRONG SAMPLE RATE ({result['sample_rate']} - should be 16000)")

    return issues


def print_report(results, sample_type):
    """Print analysis report for a set of samples."""
    valid = [r for r in results if "error" not in r]
    if not valid:
        print("  No valid samples!")
        return {}

    rms_values = [r["db_rms"] for r in valid]
    peak_values = [r["db_peak"] for r in valid]
    silence_values = [r["silence_ratio"] for r in valid]
    zcr_values = [r["zcr"] for r in valid]

    print(f"\n  Count: {len(valid)} samples")
    print(f"  Duration: {valid[0]['duration']:.1f}s each, {valid[0]['sample_rate']}Hz")

    print(f"\n  Volume (RMS dB):")
    print(f"    Min:    {min(rms_values):.1f} dB")
    print(f"    Max:    {max(rms_values):.1f} dB")
    print(f"    Mean:   {np.mean(rms_values):.1f} dB")
    print(f"    StdDev: {np.std(rms_values):.1f} dB")
    print(f"    Range:  {max(rms_values) - min(rms_values):.1f} dB spread")

    print(f"\n  Peak (dB):")
    print(f"    Min:    {min(peak_values):.1f} dB")
    print(f"    Max:    {max(peak_values):.1f} dB")

    print(f"\n  Silence Ratio:")
    print(f"    Min:    {min(silence_values)*100:.0f}%")
    print(f"    Max:    {max(silence_values)*100:.0f}%")
    print(f"    Mean:   {np.mean(silence_values)*100:.0f}%")

    print(f"\n  Zero Crossing Rate (speech indicator):")
    print(f"    Mean:   {np.mean(zcr_values):.4f}")
    print(f"    StdDev: {np.std(zcr_values):.4f}")

    # Volume distribution buckets
    print(f"\n  Volume Distribution:")
    very_quiet = sum(1 for v in rms_values if v < -35)
    quiet = sum(1 for v in rms_values if -35 <= v < -25)
    normal = sum(1 for v in rms_values if -25 <= v < -15)
    loud = sum(1 for v in rms_values if -15 <= v < -5)
    very_loud = sum(1 for v in rms_values if v >= -5)
    print(f"    Very quiet (<-35dB): {very_quiet}")
    print(f"    Quiet (-35 to -25):  {quiet}")
    print(f"    Normal (-25 to -15): {normal}")
    print(f"    Loud (-15 to -5):    {loud}")
    print(f"    Very loud (>-5dB):   {very_loud}")

    # Flag problematic files
    flagged = []
    for r in results:
        issues = flag_issues(r, sample_type)
        if issues:
            flagged.append((r["file"], issues))

    if flagged:
        print(f"\n  FLAGGED SAMPLES ({len(flagged)}):")
        for fname, issues in flagged[:20]:  # Show max 20
            print(f"    {fname}: {', '.join(issues)}")
        if len(flagged) > 20:
            print(f"    ... and {len(flagged) - 20} more")
    else:
        print(f"\n  No issues found!")

    return {
        "rms_mean": np.mean(rms_values),
        "rms_std": np.std(rms_values),
        "zcr_mean": np.mean(zcr_values),
        "zcr_std": np.std(zcr_values),
        "silence_mean": np.mean(silence_values),
    }


def separation_analysis(pos_stats, neg_stats):
    """Check how well separated positive and negative samples are."""
    print("\n" + "=" * 60)
    print("  SEPARATION ANALYSIS")
    print("=" * 60)

    if not pos_stats or not neg_stats:
        print("  Need both positive and negative samples for comparison.")
        return

    rms_diff = abs(pos_stats["rms_mean"] - neg_stats["rms_mean"])
    zcr_diff = abs(pos_stats["zcr_mean"] - neg_stats["zcr_mean"])

    print(f"\n  Volume difference (positive vs negative): {rms_diff:.1f} dB")
    if rms_diff < 3:
        print("    GOOD - Similar volume levels (model learns content, not volume)")
    elif rms_diff < 8:
        print("    OK - Slight volume difference (acceptable)")
    else:
        print("    WARNING - Large volume gap. Model might learn volume instead of speech.")
        print("    Try recording negatives at similar volume to positives.")

    print(f"\n  Speech pattern difference (ZCR): {zcr_diff:.4f}")
    if zcr_diff > 0.02:
        print("    GOOD - Clear difference in speech patterns")
    else:
        print("    OK - Similar patterns (this is normal if negatives include speech)")

    silence_diff = abs(pos_stats["silence_mean"] - neg_stats["silence_mean"])
    print(f"\n  Silence ratio difference: {silence_diff*100:.0f}%")
    if silence_diff > 0.3:
        print("    WARNING - Big silence difference.")
        print("    If negatives are mostly silence, add more speech negatives.")
        print("    (Words like 'Hey Holly', 'Probably', normal conversation)")
    else:
        print("    GOOD - Similar speech/silence balance")


def main():
    print("=" * 60)
    print("  POLLY WAKE WORD - SAMPLE QUALITY ANALYSIS")
    print("=" * 60)

    # Analyze positive samples
    pos_files = sorted(glob.glob(os.path.join(POSITIVE_DIR, "*.wav")))
    neg_files = sorted(glob.glob(os.path.join(NEGATIVE_DIR, "*.wav")))

    print(f"\n  Found: {len(pos_files)} positive, {len(neg_files)} negative samples")

    print("\n" + "=" * 60)
    print("  POSITIVE SAMPLES ('Hey Polly')")
    print("=" * 60)
    pos_results = [analyze_file(f) for f in pos_files]
    pos_stats = print_report(pos_results, "positive")

    print("\n" + "=" * 60)
    print("  NEGATIVE SAMPLES (not 'Hey Polly')")
    print("=" * 60)
    neg_results = [analyze_file(f) for f in neg_files]
    neg_stats = print_report(neg_results, "negative")

    # Separation analysis
    separation_analysis(pos_stats, neg_stats)

    # Overall verdict
    print("\n" + "=" * 60)
    print("  OVERALL VERDICT")
    print("=" * 60)

    issues = []
    if len(pos_files) < 50:
        issues.append(f"Need more positive samples ({len(pos_files)}/100 minimum)")
    if len(neg_files) < 100:
        issues.append(f"Need more negative samples ({len(neg_files)}/200 minimum)")

    pos_flagged = sum(1 for r in pos_results if flag_issues(r, "positive"))
    neg_flagged = sum(1 for r in neg_results if flag_issues(r, "negative"))
    if pos_flagged > len(pos_results) * 0.2:
        issues.append(f"{pos_flagged} positive samples have issues (>20%)")
    if neg_flagged > len(neg_results) * 0.2:
        issues.append(f"{neg_flagged} negative samples have issues (>20%)")

    if not issues:
        print("\n  READY TO TRAIN!")
        print("  Your samples look good. Proceed to model training.")
    else:
        print("\n  ISSUES TO ADDRESS:")
        for issue in issues:
            print(f"    - {issue}")
        print("\n  Fix these for better wake word accuracy, or proceed anyway.")

    print()


if __name__ == "__main__":
    main()
