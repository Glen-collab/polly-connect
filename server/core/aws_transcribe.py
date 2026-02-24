"""
Amazon Transcribe STT backend.
Uploads WAV to S3, runs transcription job, returns text.
Free tier: 60 min/month.
"""

import json
import logging
import os
import time
import uuid

from core.stt_base import STTBackend

logger = logging.getLogger(__name__)

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not available — AWS Transcribe disabled")


class AWSTranscribeSTT(STTBackend):
    def __init__(
        self,
        bucket: str = None,
        region: str = None,
    ):
        self.bucket = bucket or os.getenv("POLLY_S3_BUCKET", "polly-connect-data")
        self.region = region or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self._available = BOTO3_AVAILABLE

        if self._available:
            self._s3 = boto3.client("s3", region_name=self.region)
            self._transcribe_client = boto3.client("transcribe", region_name=self.region)
            logger.info(f"AWS Transcribe STT initialized (bucket: {self.bucket}, region: {self.region})")
        else:
            self._s3 = None
            self._transcribe_client = None

    @property
    def available(self) -> bool:
        return self._available

    def transcribe(self, audio_bytes: bytes, language: str = "en") -> str:
        if not self._available:
            return ""

        job_id = f"polly-{uuid.uuid4().hex[:12]}"
        s3_key = f"audio/temp/{job_id}.wav"

        try:
            # Upload WAV to S3
            self._s3.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=audio_bytes,
                ContentType="audio/wav",
            )

            s3_uri = f"s3://{self.bucket}/{s3_key}"

            # Start transcription job
            self._transcribe_client.start_transcription_job(
                TranscriptionJobName=job_id,
                Media={"MediaFileUri": s3_uri},
                MediaFormat="wav",
                LanguageCode=f"{language}-US" if language == "en" else language,
            )

            # Poll for completion (timeout after 30s)
            for _ in range(60):
                result = self._transcribe_client.get_transcription_job(
                    TranscriptionJobName=job_id
                )
                status = result["TranscriptionJob"]["TranscriptionJobStatus"]
                if status == "COMPLETED":
                    transcript_uri = result["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
                    import urllib.request
                    with urllib.request.urlopen(transcript_uri) as resp:
                        transcript_data = json.loads(resp.read().decode())
                    text = transcript_data["results"]["transcripts"][0]["transcript"]
                    return text.strip()
                elif status == "FAILED":
                    reason = result["TranscriptionJob"].get("FailureReason", "unknown")
                    logger.error(f"Transcription job failed: {reason}")
                    return ""
                time.sleep(0.5)

            logger.error("Transcription job timed out")
            return ""

        except Exception as e:
            logger.error(f"AWS Transcribe error: {e}")
            return ""
        finally:
            # Clean up temp S3 file
            try:
                self._s3.delete_object(Bucket=self.bucket, Key=s3_key)
            except Exception:
                pass
            try:
                self._transcribe_client.delete_transcription_job(
                    TranscriptionJobName=job_id
                )
            except Exception:
                pass
