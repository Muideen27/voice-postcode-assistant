"""
Test access to the official N-ATLAS ASR models and run a transcription.

Usage:
    python evals/test_natlas_asr.py check                 # access check for all 4 models (fast, ~1 KB each)
    python evals/test_natlas_asr.py yo my_clip.wav         # transcribe a Yoruba clip
    python evals/test_natlas_asr.py ha my_clip.wav         # Hausa  (ig = Igbo, en = Nigerian English)

Setup (once):
    pip install -U "huggingface_hub[cli]" transformers torch librosa soundfile
    hf auth login        # paste a READ token from huggingface.co/settings/tokens
"""
import sys

from huggingface_hub import hf_hub_download
from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError

REPOS = {
    "yo": "NCAIR1/Yoruba-ASR",
    "ha": "NCAIR1/Hausa-ASR",
    "ig": "NCAIR1/Igbo-ASR",
    "en": "NCAIR1/NigerianAccentedEnglish",
}


def check_access():
    """Download only config.json from each repo - proves the token + gate approval work."""
    for lang, repo in REPOS.items():
        try:
            hf_hub_download(repo, "config.json")
            print(f"[OK]        {lang}  {repo}")
        except GatedRepoError:  # must come before RepositoryNotFoundError (it's a subclass)
            print(f"[GATED]     {lang}  {repo}  -> open the model page and accept the conditions")
        except RepositoryNotFoundError:
            print(f"[NO ACCESS] {lang}  {repo}  -> check the repo name, or run 'hf auth login'")
        except Exception as e:
            print(f"[ERROR]     {lang}  {repo}  -> {e}")


def transcribe(lang, audio_path):
    """Load the full model and transcribe one audio file (16 kHz mono WAV recommended)."""
    import librosa
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    repo = REPOS[lang]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading {repo} on {device} (first run downloads the weights)...")

    proc = WhisperProcessor.from_pretrained(repo)
    model = WhisperForConditionalGeneration.from_pretrained(repo).to(device).eval()

    audio, _ = librosa.load(audio_path, sr=16000, mono=True)
    feats = proc(audio, sampling_rate=16000, return_tensors="pt").input_features.to(device)

    with torch.no_grad():
        ids = model.generate(feats)

    print("\nTranscript:\n" + proc.batch_decode(ids, skip_special_tokens=True)[0])


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "check":
        check_access()
    elif len(sys.argv) == 3 and sys.argv[1] in REPOS:
        transcribe(sys.argv[1], sys.argv[2])
    else:
        print(__doc__)