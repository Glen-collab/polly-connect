# Hey Polly Wake Word Training — Clean Slate v3

> Start a **brand new Colab notebook**. Paste each cell in order.
> Every phase saves a checkpoint to Google Drive so you never lose progress.

---

## Phase 1: Google Drive + System Setup

### Cell 1 — Mount Google Drive FIRST
```python
from google.colab import drive
drive.mount('/content/drive')

import os
SAVE = "/content/drive/MyDrive/hey_polly_training"
os.makedirs(SAVE, exist_ok=True)
print(f"Save dir: {SAVE}")
print("Everything important gets backed up here!")
```

### Cell 2 — Check environment
```python
!python --version
!nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "CPU-only (slower but works)"
```

### Cell 3 — Install ALL system dependencies at once
```python
%%bash
apt-get update -qq > /dev/null 2>&1
apt-get install -y -qq espeak-ng git-lfs ffmpeg > /dev/null 2>&1
espeak-ng --version
git lfs version
echo "System deps OK"
```

### Cell 4 — Install ALL Python dependencies at once
```python
import sys
!{sys.executable} -m pip install -q \
    piper-tts \
    openwakeword \
    onnxruntime \
    numpy \
    soundfile \
    audiomentations \
    scipy \
    torch \
    torchaudio \
    speechbrain \
    torchinfo \
    torchmetrics \
    torch_audiomentations \
    pronouncing \
    mutagen \
    acoustics \
    onnxscript \
    datasets \
    huggingface_hub \
    tensorflow \
    tqdm \
    pyyaml

# Verify the two critical imports
from piper import PiperVoice
print("piper-tts OK")
from openwakeword.model import Model
print("openwakeword OK")
```

> **If openwakeword fails to import**, restart the runtime (Runtime → Restart runtime),
> then re-run Cell 1 (Drive mount) and Cell 4 only.

---

## Phase 2: Download Voice Models

### Cell 5 — Download Piper voice models
```python
from huggingface_hub import hf_hub_download
import os, shutil

voices_dir = "/content/voices"
os.makedirs(voices_dir, exist_ok=True)

models = [
    ("rhasspy/piper-voices", "en/en_US/lessac/medium/en_US-lessac-medium.onnx"),
    ("rhasspy/piper-voices", "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"),
    ("rhasspy/piper-voices", "en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx"),
    ("rhasspy/piper-voices", "en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx.json"),
    ("rhasspy/piper-voices", "en/en_US/amy/medium/en_US-amy-medium.onnx"),
    ("rhasspy/piper-voices", "en/en_US/amy/medium/en_US-amy-medium.onnx.json"),
    ("rhasspy/piper-voices", "en/en_GB/cori/medium/en_GB-cori-medium.onnx"),
    ("rhasspy/piper-voices", "en/en_GB/cori/medium/en_GB-cori-medium.onnx.json"),
]

for repo_id, filename in models:
    basename = filename.split("/")[-1]
    print(f"Downloading {basename}...")
    path = hf_hub_download(repo_id=repo_id, filename=filename, local_dir=voices_dir)
    flat_path = f"{voices_dir}/{basename}"
    if os.path.abspath(path) != os.path.abspath(flat_path):
        shutil.copy2(path, flat_path)
    print(f"  {os.path.getsize(flat_path):,} bytes")

print("\nAll voice models OK")
```

---

## Phase 3: Clone Repos + Fix Resource Models

### Cell 6 — Clone piper-sample-generator
```python
!rm -rf /content/piper-sample-generator
!git clone --depth 1 https://github.com/rhasspy/piper-sample-generator.git /content/piper-sample-generator
print("piper-sample-generator OK")
```

### Cell 7 — Clone OpenWakeWord + copy resource models from pip package
```python
import os, shutil

# Clone the repo (for training scripts)
!rm -rf /content/openWakeWord
!git clone --depth 1 https://github.com/dscripka/openWakeWord.git /content/openWakeWord

# Git LFS doesn't reliably pull the resource models on Colab.
# Instead, copy them from the pip-installed openwakeword package.
import openwakeword
pip_res = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
git_res = "/content/openWakeWord/openwakeword/resources/models"
os.makedirs(git_res, exist_ok=True)

print("Copying resource models from pip package to git clone:")
for f in os.listdir(pip_res):
    shutil.copy2(f"{pip_res}/{f}", f"{git_res}/{f}")
    print(f"  {f}: {os.path.getsize(f'{git_res}/{f}'):,} bytes")

# Verify the two critical files
for needed in ["melspectrogram.onnx", "embedding_model.onnx"]:
    path = f"{git_res}/{needed}"
    assert os.path.exists(path) and os.path.getsize(path) > 1000, f"MISSING: {needed}"

print("\nResource models OK!")
```

### Cell 8 — Install OpenWakeWord training extras
```python
import sys
!cd /content/openWakeWord && {sys.executable} -m pip install -q ".[train]"
print("Training extras installed OK")
```

---

## Phase 4: Verify Piper TTS Works

### Cell 9 — Generate 5 test samples
```python
import sys, os
sys.path.insert(0, '/content/piper-sample-generator')
from generate_samples import generate_samples_onnx

test_dir = "/content/test_piper"
os.makedirs(test_dir, exist_ok=True)

print("Generating 5 test samples...")
generate_samples_onnx(
    text=["hey polly"],
    output_dir=test_dir,
    model="/content/voices/en_US-lessac-medium.onnx",
    max_samples=5,
    length_scales=(0.75, 1.0, 1.25),
    noise_scales=(0.667,),
    noise_scale_ws=(0.8,),
)

files = sorted(os.listdir(test_dir))
print(f"\nGenerated {len(files)} files:")
for f in files:
    print(f"  {f} — {os.path.getsize(f'{test_dir}/{f}'):,} bytes")

assert len(files) >= 5, f"FAILED: Expected 5 files, got {len(files)}"
print("\n=== PIPER TTS WORKS! ===")
```

### Cell 10 — Listen to a sample
```python
import IPython.display as ipd
ipd.Audio("/content/test_piper/0.wav")
```

> **STOP if Cell 9 failed.** Don't continue until Piper generates files.

---

## Phase 5: Generate Full Synthetic Dataset

### Cell 11 — Generate ~5000 samples
```python
import sys, os, shutil
sys.path.insert(0, '/content/piper-sample-generator')
from generate_samples import generate_samples_onnx

output_dir = "/content/synthetic_positive"
if os.path.exists(output_dir):
    shutil.rmtree(output_dir)

counter = 0

def gen(model_path, n, length_scales, noise_scales, noise_ws, max_spk=None):
    global counter
    temp = "/content/_temp"
    if os.path.exists(temp): shutil.rmtree(temp)
    os.makedirs(temp)
    kw = dict(text=["hey polly"], output_dir=temp, model=model_path,
              max_samples=n, length_scales=length_scales,
              noise_scales=noise_scales, noise_scale_ws=noise_ws)
    if max_spk: kw["max_speakers"] = max_spk
    generate_samples_onnx(**kw)
    os.makedirs(output_dir, exist_ok=True)
    for f in sorted(os.listdir(temp)):
        os.rename(f"{temp}/{f}", f"{output_dir}/{counter}.wav")
        counter += 1
    shutil.rmtree(temp)

print("=== libritts_r (4000 samples) ===")
gen("/content/voices/en_US-libritts_r-medium.onnx", 4000,
    (0.75, 0.85, 1.0, 1.15, 1.3), (0.667, 0.8), (0.8,), max_spk=200)
print(f"  Total: {counter}")

print("\n=== lessac (350 samples) ===")
gen("/content/voices/en_US-lessac-medium.onnx", 350,
    (0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.5), (0.5,0.667,0.8,1.0), (0.6,0.8,1.0))
print(f"  Total: {counter}")

print("\n=== amy (350 samples) ===")
gen("/content/voices/en_US-amy-medium.onnx", 350,
    (0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.5), (0.5,0.667,0.8,1.0), (0.6,0.8,1.0))
print(f"  Total: {counter}")

print("\n=== cori (300 samples) ===")
gen("/content/voices/en_GB-cori-medium.onnx", 300,
    (0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.5), (0.5,0.667,0.8,1.0), (0.6,0.8,1.0))

print(f"\n{'='*40}")
print(f"TOTAL: {counter} synthetic samples")
```

### Cell 12 — CHECKPOINT: Save synthetic samples to Drive
```python
import shutil, os
SAVE = "/content/drive/MyDrive/hey_polly_training"

# Zip for faster copy
!cd /content && zip -q -r synthetic_positive.zip synthetic_positive/
shutil.copy2("/content/synthetic_positive.zip", f"{SAVE}/synthetic_positive.zip")
size = os.path.getsize(f"{SAVE}/synthetic_positive.zip") / 1e6
print(f"Saved synthetic_positive.zip to Drive ({size:.0f} MB)")
```

---

## Phase 6: Upload Real Samples + Organize

### Cell 13 — Upload real samples
```python
import os, zipfile, shutil

zip_path = "/content/hey_polly_samples.zip"
if not os.path.exists(zip_path):
    from google.colab import files
    print("Upload hey_polly_samples.zip:")
    uploaded = files.upload()
    zip_path = "/content/" + list(uploaded.keys())[0]

extract_dir = "/content/real_samples"
if os.path.exists(extract_dir): shutil.rmtree(extract_dir)

with zipfile.ZipFile(zip_path, 'r') as z:
    z.extractall(extract_dir)

for root, dirs, fl in os.walk(extract_dir):
    wc = len([f for f in fl if f.endswith('.wav')])
    if wc > 0: print(f"  {root}: {wc} wav files")

print("\nReal samples OK")
```

### Cell 14 — Organize training directory + resample to 16kHz
```python
import os, shutil, random
import soundfile as sf_lib
import numpy as np
from scipy.signal import resample

train_dir = "/content/my_custom_model/hey_polly"
if os.path.exists(train_dir): shutil.rmtree(train_dir)
for sub in ["positive_train","positive_test","negative_train","negative_test"]:
    os.makedirs(f"{train_dir}/{sub}", exist_ok=True)

# Find real sample dirs
real_pos = real_neg = None
for root, dirs, _ in os.walk("/content/real_samples"):
    for d in dirs:
        full = os.path.join(root, d)
        if not any(f.endswith('.wav') for f in os.listdir(full)): continue
        if "pos" in d.lower(): real_pos = full
        elif "neg" in d.lower(): real_neg = full

print(f"Positive: {real_pos}\nNegative: {real_neg}")
random.seed(42)

# Real positive 80/20
rp = sorted([f for f in os.listdir(real_pos) if f.endswith('.wav')])
random.shuffle(rp); s = int(len(rp)*0.8)
for f in rp[:s]: shutil.copy2(f"{real_pos}/{f}", f"{train_dir}/positive_train/real_{f}")
for f in rp[s:]: shutil.copy2(f"{real_pos}/{f}", f"{train_dir}/positive_test/real_{f}")
print(f"Real positive: {s} train / {len(rp)-s} test")

# Real negative 80/20
if real_neg:
    rn = sorted([f for f in os.listdir(real_neg) if f.endswith('.wav')])
    random.shuffle(rn); sn = int(len(rn)*0.8)
    for f in rn[:sn]: shutil.copy2(f"{real_neg}/{f}", f"{train_dir}/negative_train/real_{f}")
    for f in rn[sn:]: shutil.copy2(f"{real_neg}/{f}", f"{train_dir}/negative_test/real_{f}")
    print(f"Real negative: {sn} train / {len(rn)-sn} test")

# Synthetic positive 80/20
sy = sorted(os.listdir("/content/synthetic_positive"))
random.shuffle(sy); ss = int(len(sy)*0.8)
for f in sy[:ss]: shutil.copy2(f"/content/synthetic_positive/{f}", f"{train_dir}/positive_train/synth_{f}")
for f in sy[ss:]: shutil.copy2(f"/content/synthetic_positive/{f}", f"{train_dir}/positive_test/synth_{f}")
print(f"Synthetic positive: {ss} train / {len(sy)-ss} test")

# Resample ALL training clips to 16kHz (Piper outputs 22050Hz, OpenWakeWord needs 16kHz)
TARGET_SR = 16000
resampled = 0
for sub in ["positive_train","positive_test","negative_train","negative_test"]:
    d = f"{train_dir}/{sub}"
    for fname in os.listdir(d):
        if not fname.endswith('.wav'): continue
        path = f"{d}/{fname}"
        data, sr = sf_lib.read(path)
        if sr != TARGET_SR:
            n_samples = int(len(data) * TARGET_SR / sr)
            data_16k = resample(data, n_samples).astype(np.float32)
            sf_lib.write(path, data_16k, TARGET_SR)
            resampled += 1
print(f"\nResampled {resampled} files to 16kHz")

print(f"\n{'='*40}")
for sub in ["positive_train","positive_test","negative_train","negative_test"]:
    print(f"  {sub}: {len(os.listdir(f'{train_dir}/{sub}'))} files")
```

---

## Phase 7: Apply Patches + Download Datasets

### Cell 15 — Apply ALL patches (on-disk so subprocesses get them too)
```python
import pathlib

fixed = []

# --- speechbrain patch ---
for pyver in ["3.10", "3.11", "3.12"]:
    sb = pathlib.Path(f"/usr/local/lib/python{pyver}/dist-packages/speechbrain/utils/torch_audio_backend.py")
    if sb.exists():
        t = sb.read_text()
        if "torchaudio.list_audio_backends()" in t:
            sb.write_text(t.replace(
                "available_backends = torchaudio.list_audio_backends()",
                "available_backends = ['soundfile']"
            ))
            fixed.append(f"speechbrain({pyver})")

# --- torch_audiomentations patches (BOTH set_audio_backend AND torchaudio.info) ---
try:
    import torch_audiomentations
    pkg = pathlib.Path(torch_audiomentations.__file__).parent
    for f in pkg.rglob("*.py"):
        t = f.read_text()
        changed = False
        if "torchaudio.set_audio_backend" in t:
            t = t.replace("torchaudio.set_audio_backend", "pass  #")
            changed = True
        if "torchaudio.info" in t:
            t = t.replace(
                "info = torchaudio.info(str(file_path))",
                "import soundfile as _sf; _i = _sf.info(str(file_path)); "
                "info = type('Info', (), {'num_frames': _i.frames, 'sample_rate': _i.samplerate})()"
            )
            changed = True
        if changed:
            f.write_text(t)
            fixed.append(f"torch_audiomentations/{f.name}")
except ImportError: pass

# --- torchaudio in-memory patches (for any Python cells that use it directly) ---
import torchaudio
if not hasattr(torchaudio, 'info'):
    import soundfile as sf
    class _AI:
        def __init__(self, sr, nf): self.sample_rate=sr; self.num_frames=nf
    torchaudio.info = lambda fp: _AI(sf.info(str(fp)).samplerate, sf.info(str(fp)).frames)
    fixed.append("torchaudio.info")
if not hasattr(torchaudio, 'list_audio_backends'):
    torchaudio.list_audio_backends = lambda: ["soundfile"]
    fixed.append("list_audio_backends")
if not hasattr(torchaudio, 'get_audio_backend'):
    torchaudio.get_audio_backend = lambda: "soundfile"
    fixed.append("get_audio_backend")
if not hasattr(torchaudio, 'set_audio_backend'):
    torchaudio.set_audio_backend = lambda x: None
    fixed.append("set_audio_backend")

print(f"Patched: {', '.join(fixed) if fixed else 'none needed'}")
```

### Cell 16 — Download training datasets
```python
import os, numpy as np, soundfile as sf, datasets
from huggingface_hub import hf_hub_download

print("MIT Room Impulse Responses...")
mit = datasets.load_dataset("davidscripka/MIT_environmental_impulse_responses", split="train")
os.makedirs("/content/mit_rirs", exist_ok=True)
for i, ex in enumerate(mit):
    a = ex["audio"]
    sf.write(f"/content/mit_rirs/rir_{i}.wav", np.array(a["array"],dtype=np.float32), a["sampling_rate"])
print(f"  {i+1} RIRs saved")

print("\nACAV100M features...")
hf_hub_download(repo_id="davidscripka/openwakeword_features",
    filename="openwakeword_features_ACAV100M_2000_hrs_16bit.npy",
    repo_type="dataset", local_dir="/content")
print("  OK")

print("\nValidation features...")
hf_hub_download(repo_id="davidscripka/openwakeword_features",
    filename="validation_set_features.npy",
    repo_type="dataset", local_dir="/content")
print("  OK")

print("\nAll datasets OK")
```

### Cell 17 — Generate background noise
```python
import numpy as np, soundfile as sf, os
os.makedirs("/content/background_clips", exist_ok=True)
for i in range(50):
    n = int(np.random.uniform(3,10)*16000)
    k = np.random.choice(["w","p","b","q"])
    if k=="w": a=np.random.randn(n).astype(np.float32)*0.1
    elif k=="p":
        from scipy.signal import lfilter
        a=lfilter([.05,-.096,.051,-.005],[1,-2.495,2.017,-.522],np.random.randn(n)).astype(np.float32)*0.1
    elif k=="b":
        a=np.cumsum(np.random.randn(n)).astype(np.float32)
        a=a/(np.abs(a).max()+1e-8)*0.1
    else: a=np.random.randn(n).astype(np.float32)*0.005
    sf.write(f"/content/background_clips/bg_{i:03d}.wav",a,16000)
print(f"Generated {len(os.listdir('/content/background_clips'))} noise clips OK")
```

---

## Phase 8: Train

### Cell 18 — Write config
```python
config = """
model_name: hey_polly
target_phrase:
  - "hey polly"
custom_negative_phrases: []
n_samples: 5000
n_samples_val: 1000
tts_batch_size: 50
augmentation_batch_size: 16
augmentation_rounds: 10
piper_sample_generator_path: /content/piper-sample-generator
output_dir: /content/my_custom_model
rir_paths:
  - /content/mit_rirs
background_paths:
  - /content/background_clips
background_paths_duplication_rate:
  - 1
false_positive_validation_data_path: /content/validation_set_features.npy
feature_data_files:
  ACAV100M_sample: /content/openwakeword_features_ACAV100M_2000_hrs_16bit.npy
batch_n_per_class:
  ACAV100M_sample: 256
  adversarial_negative: 25
  positive: 25
model_type: dnn
layer_size: 32
steps: 10000
max_negative_weight: 1500
target_false_positives_per_hour: 0.2
"""
with open("/content/hey_polly_config.yaml","w") as f: f.write(config.strip())
print("Config written OK")
```

### Cell 19 — Run augmentation
```python
!cd /content/openWakeWord && PYTHONPATH=/content/openWakeWord:$PYTHONPATH \
    python openwakeword/train.py \
    --training_config /content/hey_polly_config.yaml \
    --augment_clips 2>&1 | tee /content/augment_log.txt
print("\nAugmentation done")
```

### Cell 20 — CHECKPOINT: Save augmentation to Drive
```python
import shutil
SAVE = "/content/drive/MyDrive/hey_polly_training"
shutil.copy2("/content/augment_log.txt", f"{SAVE}/augment_log.txt")
# Save the augmented features so we don't have to redo this
!cd /content && zip -q -r my_custom_model_checkpoint.zip my_custom_model/
shutil.copy2("/content/my_custom_model_checkpoint.zip", f"{SAVE}/my_custom_model_checkpoint.zip")
print("Augmentation checkpoint saved to Drive!")
```

### Cell 21 — Train the model
```python
!cd /content/openWakeWord && PYTHONPATH=/content/openWakeWord:$PYTHONPATH \
    python openwakeword/train.py \
    --training_config /content/hey_polly_config.yaml \
    --train_model 2>&1 | tee /content/train_log.txt
print("\nTraining done")
```

### Cell 22 — IMMEDIATELY save model to Drive
```python
import glob, shutil, os
SAVE = "/content/drive/MyDrive/hey_polly_training"

for f in glob.glob("/content/my_custom_model/**/*.onnx", recursive=True):
    dest = f"{SAVE}/{os.path.basename(f)}"
    shutil.copy2(f, dest)
    print(f"SAVED: {dest} ({os.path.getsize(dest):,} bytes)")

for f in glob.glob("/content/my_custom_model/**/*.onnx.data", recursive=True):
    dest = f"{SAVE}/{os.path.basename(f)}"
    shutil.copy2(f, dest)
    print(f"SAVED: {dest}")

shutil.copy2("/content/train_log.txt", f"{SAVE}/train_log.txt")
print(f"\nModel + logs saved to Drive: {SAVE}")
```

---

## Phase 9: Test + Download

### Cell 23 — Test the model
```python
import sys
!{sys.executable} -m pip install -q openwakeword soundfile numpy

import os, glob, numpy as np, soundfile as sf
from openwakeword.model import Model

# Find model
mf = glob.glob("/content/my_custom_model/**/*.onnx", recursive=True)
if not mf: mf = glob.glob("/content/drive/MyDrive/hey_polly_training/*.onnx")
print(f"Model: {mf}")

model = Model(wakeword_models=[mf[0]])
THRESHOLD = 0.5

# Test positive
pos = sorted(glob.glob("/content/my_custom_model/hey_polly/positive_test/*.wav"))[:20]
det = 0
print("\nPOSITIVE (should detect):")
for f in pos:
    d,_ = sf.read(f, dtype='int16')
    mx = max((list(model.predict(d[i:i+1280]).values())[0] for i in range(0,len(d)-1280,1280)), default=0)
    if mx > THRESHOLD: det += 1
    print(f"  {os.path.basename(f)}: {mx:.3f} {'YES' if mx>THRESHOLD else 'no'}")
print(f"Recall: {det}/{len(pos)} ({det/max(1,len(pos))*100:.0f}%)")

# Test negative
neg = sorted(glob.glob("/content/my_custom_model/hey_polly/negative_test/*.wav"))[:20]
fp = 0
print("\nNEGATIVE (should NOT detect):")
for f in neg:
    d,_ = sf.read(f, dtype='int16')
    mx = max((list(model.predict(d[i:i+1280]).values())[0] for i in range(0,len(d)-1280,1280)), default=0)
    if mx > THRESHOLD: fp += 1
    print(f"  {os.path.basename(f)}: {mx:.3f} {'FP!' if mx>THRESHOLD else 'ok'}")
print(f"False positives: {fp}/{len(neg)} ({fp/max(1,len(neg))*100:.0f}%)")
```

### Cell 24 — Download model
```python
from google.colab import files
import glob, os

SAVE = "/content/drive/MyDrive/hey_polly_training"
for f in glob.glob(f"{SAVE}/*.onnx") + glob.glob(f"{SAVE}/*.onnx.data"):
    print(f"Downloading: {os.path.basename(f)} ({os.path.getsize(f):,} bytes)")
    files.download(f)
print("\nDone! Copy .onnx to polly-connect/wake-word/ and test with test_model.py")
```

---

## Recovery: If Runtime Disconnects

```python
from google.colab import drive
drive.mount('/content/drive')

import os
SAVE = "/content/drive/MyDrive/hey_polly_training"
print("Files on Drive:")
for f in os.listdir(SAVE):
    print(f"  {f} ({os.path.getsize(f'{SAVE}/{f}'):,} bytes)")
```

If you have `my_custom_model_checkpoint.zip` on Drive, you can restore and skip to training:
```python
import shutil
shutil.copy2(f"{SAVE}/my_custom_model_checkpoint.zip", "/content/")
!cd /content && unzip -q my_custom_model_checkpoint.zip
print("Checkpoint restored! Skip to Cell 21 (training)")
```

---

## All Known Fixes (built into this guide)

| Problem | How it's fixed |
|---------|---------------|
| Voice model download corrupted | Uses `huggingface_hub` instead of `wget` (Cell 5) |
| `melspectrogram.onnx` missing | Copies from pip-installed openwakeword package (Cell 7) |
| `openwakeword` import fails | Uses `{sys.executable} -m pip install` (Cell 4) |
| `generate_adversarial_texts` import error | `PYTHONPATH` prefix forces git clone's code (Cells 19, 21) |
| `torchaudio.info` missing in subprocess | Patched on-disk in `torch_audiomentations/utils/io.py` (Cell 15) |
| `torchaudio.list_audio_backends` missing | Patched on-disk in speechbrain + in-memory (Cell 15) |
| `set_audio_backend` error | Patched on-disk in torch_audiomentations (Cell 15) |
| Wrong sample rate (22050 vs 16000) | All clips resampled to 16kHz in Cell 14 |
| Missing pip packages (torchinfo etc) | ALL installed upfront in Cell 4 |
| "features already exist" skip | Delete stale `.npy`: `!rm -f /content/my_custom_model/hey_polly/*.npy` |
| Runtime disconnect loses work | Drive saves after every major step |
| Model not saved after training | Cell 22 saves immediately |
