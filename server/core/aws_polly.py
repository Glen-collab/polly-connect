"""
Amazon Polly TTS backend.
Neural voice "Joanna" — warm and clear for elderly users.
Outputs 16kHz mono PCM wrapped in WAV header.
Free tier: 5M chars/month.
"""

import io
import logging
import os
import struct
import wave
from typing import Optional

from core.tts_base import TTSBackend

logger = logging.getLogger(__name__)

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not available — Amazon Polly disabled")


class AWSPollyTTS(TTSBackend):
    def __init__(
        self,
        voice_id: str = None,
        region: str = None,
    ):
        self.voice_id = voice_id or os.getenv("POLLY_VOICE_ID", "Joanna")
        self.region = region or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self._available = BOTO3_AVAILABLE

        if self._available:
            self._polly = boto3.client("polly", region_name=self.region)
            logger.info(f"Amazon Polly TTS initialized (voice: {self.voice_id}, region: {self.region})")
        else:
            self._polly = None

    @property
    def available(self) -> bool:
        return self._available

    def synthesize(self, text: str) -> Optional[bytes]:
        """Convert text to 16kHz mono WAV bytes using Amazon Polly."""
        if not text or not self._available:
            return None

        try:
            # Use SSML if text contains SSML tags, otherwise plain text
            synth_params = dict(
                OutputFormat="pcm",
                VoiceId=self.voice_id,
                Engine="neural",
                SampleRate="16000",
            )
            if "<speak>" in text:
                synth_params["Text"] = text
                synth_params["TextType"] = "ssml"
            else:
                synth_params["Text"] = text

            response = self._polly.synthesize_speech(**synth_params)

            # Read PCM stream
            pcm_data = response["AudioStream"].read()

            if not pcm_data:
                return None

            # Wrap raw PCM in WAV header (16kHz, 16-bit, mono)
            output = io.BytesIO()
            with wave.open(output, "wb") as wav_out:
                wav_out.setnchannels(1)
                wav_out.setsampwidth(2)
                wav_out.setframerate(16000)
                wav_out.writeframes(pcm_data)

            return output.getvalue()

        except Exception as e:
            logger.error(f"Amazon Polly TTS error: {e}")
            return None
