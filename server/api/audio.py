"""
Audio streaming endpoint for Polly Connect.

Supports two WebSocket modes:
1. Event-based (existing): ESP32 detects wake word locally, sends audio after detection
2. Continuous stream (new): ESP32 streams all mic audio, server runs OpenWakeWord
"""

import asyncio
import base64
import json
import logging
import io
import random
import time
import wave
from typing import Optional
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.intent_parser import IntentParser
from core.conversation_state import ConversationMode
from core.vad_wakeword import VADWakeWordDetector
from core.story_recorder import StoryRecordingSession
from core.auth import verify_device_api_key, verify_websocket_key
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

intent_parser = IntentParser(use_spacy=False)

# OpenWakeWord processes 1280-sample chunks (80ms at 16kHz)
OWW_CHUNK_SAMPLES = 1280
OWW_CHUNK_BYTES = OWW_CHUNK_SAMPLES * 2  # int16 = 2 bytes


class AudioSession:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.audio_buffer = bytearray()
        self.listening_for_command = False
        self.command_audio = bytearray()

    def add_audio(self, audio_bytes: bytes):
        self.audio_buffer.extend(audio_bytes)

    def clear(self):
        self.audio_buffer = bytearray()

    def clear_command(self):
        self.command_audio = bytearray()

    def get_wav_bytes(self, audio_data: bytearray = None) -> bytes:
        data = audio_data if audio_data else self.audio_buffer
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(settings.CHANNELS)
            wav_file.setsampwidth(2)
            wav_file.setframerate(settings.SAMPLE_RATE)
            wav_file.writeframes(data)
        return wav_buffer.getvalue()


# ─── Continuous Stream Handler ───────────────────────────────────────────────

@router.websocket("/continuous")
async def continuous_stream(websocket: WebSocket):
    """
    Continuous audio streaming with server-side wake word detection.
    """
    await websocket.accept()

    app = websocket.app
    db = app.state.db
    transcriber = app.state.transcriber
    tts = app.state.tts
    detector = app.state.wake_word_detector
    cmd = app.state.cmd

    if not detector.ready:
        logger.error("Wake word detector not ready — rejecting continuous stream")
        await websocket.send_json({"event": "error", "message": "Wake word detector not available"})
        await websocket.close()
        return

    device_id = "unknown"
    pcm_buffer = bytearray()

    state = "listening"
    command_audio = bytearray()
    last_voice_time = 0.0
    command_start_time = 0.0
    last_response_time = 0.0  # cooldown after response to avoid speaker feedback
    RESPONSE_COOLDOWN = 3.0   # ignore triggers for 3s after a response
    still_there_prompted = False  # tracks if we've asked "still there?"
    accumulated_parts = []        # partial audio from before the prompt

    # Story recording session (button-triggered WAV capture)
    story_session = None  # type: StoryRecordingSession

    # Pre-roll: keep last ~1.5 seconds of audio so we capture the wake phrase
    # 16kHz * 2 bytes * 1.5s = 48000 bytes
    PRE_ROLL_SIZE = 48000
    pre_roll = bytearray()

    # Use the VAD threshold for silence detection during recording too
    from core.vad_wakeword import VADWakeWordDetector
    vad_threshold = detector.rms_threshold if isinstance(detector, VADWakeWordDetector) else settings.SILENCE_THRESHOLD_RMS
    # Lower threshold for recording silence — catches softer speech during conversation
    recording_silence_threshold = max(vad_threshold // 2, 50)

    logger.info("Continuous stream connected")

    # Medication scheduler for WebSocket registration
    med_scheduler = getattr(app.state, "med_scheduler", None)
    squawk_mgr = getattr(app.state, "squawk", None)

    try:
        while True:
            message = await websocket.receive()

            if "text" in message:
                try:
                    msg_data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                event = msg_data.get("event")

                if event == "connect":
                    device_id = msg_data.get("device_id", "unknown")
                    tenant_id = 1  # default
                    # Authenticate device
                    device_info = verify_device_api_key(msg_data.get("api_key", ""), db)
                    if device_info:
                        conv_state = cmd._get_state(device_id)
                        # Reset conversation mode on reconnect so stale
                        # FOLLOWUP_WAIT / STORY_PROMPT state doesn't persist
                        conv_state.reset()
                        conv_state.tenant_id = device_info["tenant_id"]
                        conv_state.user_id = device_info["user_id"]
                        tenant_id = device_info["tenant_id"]
                        logger.info(f"Continuous stream device: {device_id} (tenant={device_info['tenant_id']})")
                    elif not verify_websocket_key(msg_data):
                        logger.warning(f"Continuous stream auth failed: {device_id}")
                        await websocket.send_json({"event": "error", "message": "Authentication failed"})
                        await websocket.close()
                        return
                    else:
                        # Global key fallback → tenant 1
                        conv_state = cmd._get_state(device_id)
                        conv_state.reset()
                        conv_state.tenant_id = 1
                        logger.info(f"Continuous stream device: {device_id} (global key, tenant=1)")

                    # Register for medication reminders
                    if med_scheduler:
                        med_scheduler.register_websocket(device_id, websocket, tenant_id)

                    # Load family names into intent parser for person detection
                    try:
                        family_members = db.get_family_members(tenant_id=tenant_id)
                        family_names = set()
                        for m in family_members:
                            family_names.add(m["name"].lower().split()[0])  # first name
                            family_names.add(m["name"].lower())  # full name
                            if m.get("relation_to_owner"):
                                family_names.add(m["relation_to_owner"].lower())
                        intent_parser._family_names = family_names
                        logger.info(f"Loaded {len(family_names)} family names for message board")
                    except Exception as e:
                        logger.warning(f"Could not load family names: {e}")

                    # Store client IP for location-based services (weather)
                    # Use X-Forwarded-For if behind Nginx, otherwise direct client IP
                    conv_state = cmd._get_state(device_id)
                    forwarded_for = None
                    for header_name in ("x-forwarded-for", "x-real-ip"):
                        val = dict(websocket.headers).get(header_name)
                        if val:
                            forwarded_for = val.split(",")[0].strip()
                            break
                    client_host = forwarded_for or (websocket.client.host if websocket.client else None)
                    if client_host:
                        conv_state.client_ip = client_host
                        logger.info(f"Client IP for {device_id}: {client_host}")

                    await websocket.send_json({"event": "connected", "message": "Streaming mode ready"})

                    # Load squawk intervals from user profile
                    squawk_int = 10
                    chatter_int = 45
                    quiet_start = 21
                    quiet_end = 7
                    try:
                        profile = db.get_or_create_user(tenant_id=tenant_id)
                        squawk_int = profile.get("squawk_interval") or 10
                        chatter_int = profile.get("chatter_interval") or 45
                        quiet_start = profile.get("quiet_hours_start") if profile.get("quiet_hours_start") is not None else 21
                        quiet_end = profile.get("quiet_hours_end") if profile.get("quiet_hours_end") is not None else 7
                    except Exception:
                        pass

                    # Register for ambient squawk sounds + startup squawk
                    if squawk_mgr:
                        squawk_mgr.register_device(device_id, websocket,
                                                   squawk_interval=squawk_int,
                                                   chatter_interval=chatter_int,
                                                   quiet_hours_start=quiet_start,
                                                   quiet_hours_end=quiet_end)
                        if not squawk_mgr.is_snoozed(device_id):
                            await squawk_mgr.send_squawk(device_id)

                    continue

                if event == "ping":
                    await websocket.send_json({"event": "pong"})
                    continue

                if event == "story_button":
                    action = msg_data.get("action", "start")
                    conv_state = cmd._get_state(device_id)

                    if action == "start" and story_session is None:
                        # Start story recording
                        tenant_id = conv_state.tenant_id or 1
                        story_session = StoryRecordingSession(device_id, tenant_id)
                        conv_state.mode = ConversationMode.STORY_RECORD
                        logger.info(f"Story recording started for device {device_id}")

                        # Announce via TTS
                        announce = "Recording started. Tell your story, and press the button again when you're done."
                        await websocket.send_json({"event": "story_record_started"})
                        await websocket.send_json({"event": "response", "text": announce, "mode": "story_record"})
                        await _send_tts(websocket, tts, announce, squawk_mgr=squawk_mgr, device_id=device_id)
                        last_response_time = time.monotonic()

                    elif action == "stop" and story_session is not None:
                        # Stop story recording — finalize and save
                        logger.info(f"Story recording stopped for device {device_id}")

                        # Transcribe any remaining segment
                        remaining_wav = story_session.get_segment_wav()
                        if remaining_wav:
                            seg_text = await asyncio.to_thread(transcriber.transcribe, remaining_wav)
                            if seg_text:
                                story_session.add_transcript_segment(seg_text)

                        result = story_session.finish()
                        story_session = None
                        conv_state.mode = ConversationMode.COMMAND

                        # Save story to database
                        transcript = result.get("transcript", "")
                        wav_filename = result.get("wav_filename")
                        duration = result.get("duration_seconds", 0)

                        if transcript or wav_filename:
                            db = app.state.db
                            story_id = db.save_story(
                                transcript=transcript or "(no speech detected)",
                                audio_s3_key=wav_filename,
                                speaker_name=conv_state.speaker_name,
                                source="wav_button",
                                duration_seconds=duration,
                                tenant_id=conv_state.tenant_id,
                            )

                            # Extract memory metadata if we have transcript
                            if transcript and len(transcript) > 20:
                                extractor = getattr(app.state, "memory_extractor", None)
                                if extractor:
                                    metadata = extractor.extract(
                                        transcript,
                                        speaker=conv_state.speaker_name,
                                    )
                                    db.save_memory(
                                        story_id=story_id,
                                        speaker=metadata.get("speaker"),
                                        bucket=metadata.get("bucket", "ordinary_world"),
                                        life_phase=metadata.get("life_phase", "unknown"),
                                        text_summary=metadata.get("text_summary", ""),
                                        text=transcript,
                                        people=",".join(metadata.get("people", [])),
                                        locations=",".join(metadata.get("locations", [])),
                                        emotions=",".join(metadata.get("emotions", [])),
                                        fingerprint=extractor.compute_fingerprint(metadata),
                                        tenant_id=conv_state.tenant_id,
                                    )

                            logger.info(f"Story saved: id={story_id}, wav={wav_filename}, "
                                        f"transcript={len(transcript)} chars, duration={duration:.1f}s")

                        mins = int(duration // 60)
                        secs = int(duration % 60)
                        announce = f"Got it! Recording saved. That was {mins} minutes and {secs} seconds."
                        await websocket.send_json({"event": "story_record_stopped"})
                        await websocket.send_json({"event": "response", "text": announce, "mode": "command"})
                        await _send_tts(websocket, tts, announce, squawk_mgr=squawk_mgr, device_id=device_id)
                        last_response_time = time.monotonic()

                    continue

                continue

            if "bytes" not in message:
                continue

            pcm_data = message["bytes"]

            # Fork audio to story recorder if active
            if story_session is not None:
                rms_val = int(np.sqrt(np.mean(
                    np.frombuffer(pcm_data[:len(pcm_data) - len(pcm_data) % 2], dtype=np.int16
                    ).astype(np.float32) ** 2))) if len(pcm_data) >= 2 else 0
                story_session.add_audio(pcm_data, rms=rms_val)

                # Transcribe segments on silence gaps (background)
                if story_session.should_transcribe_segment():
                    seg_wav = story_session.get_segment_wav()
                    if seg_wav:
                        seg_text = await asyncio.to_thread(transcriber.transcribe, seg_wav)
                        if seg_text:
                            story_session.add_transcript_segment(seg_text)
                            logger.info(f"Story segment transcribed: {seg_text[:80]}...")

                # Auto-stop at 30 minute limit
                if story_session.is_over_limit:
                    logger.info("Story recording hit 30-minute limit, auto-stopping")
                    # Trigger stop by simulating button press
                    remaining_wav = story_session.get_segment_wav()
                    if remaining_wav:
                        seg_text = await asyncio.to_thread(transcriber.transcribe, remaining_wav)
                        if seg_text:
                            story_session.add_transcript_segment(seg_text)

                    result = story_session.finish()
                    conv_state = cmd._get_state(device_id)
                    story_session = None
                    conv_state.mode = ConversationMode.COMMAND

                    transcript = result.get("transcript", "")
                    wav_filename = result.get("wav_filename")
                    duration = result.get("duration_seconds", 0)

                    if transcript or wav_filename:
                        db_ref = app.state.db
                        db_ref.save_story(
                            transcript=transcript or "(no speech detected)",
                            audio_s3_key=wav_filename,
                            speaker_name=conv_state.speaker_name,
                            source="wav_button",
                            duration_seconds=duration,
                            tenant_id=conv_state.tenant_id,
                        )

                    announce = "We hit the thirty minute mark, so I saved your recording. You can start another one anytime."
                    await websocket.send_json({"event": "story_record_stopped"})
                    await websocket.send_json({"event": "response", "text": announce, "mode": "command"})
                    await _send_tts(websocket, tts, announce, squawk_mgr=squawk_mgr, device_id=device_id)
                    last_response_time = time.monotonic()

            pcm_buffer.extend(pcm_data)

            while len(pcm_buffer) >= OWW_CHUNK_BYTES:
                chunk_bytes = bytes(pcm_buffer[:OWW_CHUNK_BYTES])
                del pcm_buffer[:OWW_CHUNK_BYTES]
                chunk_int16 = np.frombuffer(chunk_bytes, dtype=np.int16)

                if state == "listening":
                    # Maintain pre-roll buffer
                    pre_roll.extend(chunk_bytes)
                    if len(pre_roll) > PRE_ROLL_SIZE:
                        pre_roll = pre_roll[-PRE_ROLL_SIZE:]

                    # Get live conversation state for dynamic timeouts
                    conv_state = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None

                    # In conversational mode, skip wake word — go straight to recording
                    if conv_state and conv_state.is_conversational:
                        rms = int(np.sqrt(np.mean(chunk_int16.astype(np.float32) ** 2)))
                        if rms > vad_threshold:
                            # Interrupt squawk if playing
                            if squawk_mgr and squawk_mgr.is_playing(device_id):
                                squawk_mgr.stop_playback(device_id)
                            if squawk_mgr:
                                squawk_mgr.reset_idle_timer(device_id)
                            logger.info(f"Voice detected in conversational mode (device: {device_id})")
                            state = "recording"
                            skip_wake_check = True  # don't require wake phrase
                            command_audio = bytearray(pre_roll)  # include pre-roll
                            last_voice_time = time.monotonic()
                            command_start_time = time.monotonic()
                            await websocket.send_json({"event": "conversation_listening"})
                    elif detector.detected(chunk_int16):
                        # Ignore triggers during cooldown after response (speaker feedback)
                        if time.monotonic() - last_response_time < RESPONSE_COOLDOWN:
                            continue

                        # Interrupt any playing squawk/chatter
                        if squawk_mgr and squawk_mgr.is_playing(device_id):
                            squawk_mgr.stop_playback(device_id)
                            logger.info(f"Squawk interrupted by wake word → {device_id}")

                        logger.info(f"*** WAKE WORD DETECTED (device: {device_id}) ***")
                        detector.reset()

                        # Reset idle squawk timer on activity
                        if squawk_mgr:
                            squawk_mgr.reset_idle_timer(device_id)

                        state = "recording"
                        skip_wake_check = False  # require wake phrase
                        # Include pre-roll so we capture "Hey Polly" before trigger
                        command_audio = bytearray(pre_roll)
                        last_voice_time = time.monotonic()
                        command_start_time = time.monotonic()

                        await websocket.send_json({"event": "wake_word_detected"})

                elif state == "recording":
                    command_audio.extend(chunk_bytes)

                    rms = int(np.sqrt(np.mean(chunk_int16.astype(np.float32) ** 2)))
                    if rms > recording_silence_threshold:
                        last_voice_time = time.monotonic()

                    now = time.monotonic()
                    silence_duration = now - last_voice_time
                    total_duration = now - command_start_time

                    # Use dynamic timeouts from conversation state
                    conv_state = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
                    silence_limit = conv_state.silence_timeout if conv_state else settings.SILENCE_TIMEOUT_S
                    max_duration = conv_state.max_recording if conv_state else settings.MAX_COMMAND_S

                    if silence_duration > silence_limit or total_duration > max_duration:
                        reason = "silence" if silence_duration > silence_limit else "max_duration"

                        # Combine any accumulated audio with current
                        if accumulated_parts:
                            full_audio = bytearray()
                            for part in accumulated_parts:
                                full_audio.extend(part)
                            full_audio.extend(command_audio)
                            command_audio = full_audio
                            accumulated_parts = []

                        logger.info(f"Command recording ended ({reason}), {len(command_audio)} bytes")

                        pre_transcription = None

                        # In conversational mode on silence, transcribe first to decide
                        if (conv_state and conv_state.is_conversational
                                and reason == "silence"
                                and not still_there_prompted):
                            # Quick transcribe to check if user actually spoke
                            check_wav = io.BytesIO()
                            with wave.open(check_wav, 'wb') as wf:
                                wf.setnchannels(settings.CHANNELS)
                                wf.setsampwidth(2)
                                wf.setframerate(settings.SAMPLE_RATE)
                                wf.writeframes(command_audio)
                            check_text = await asyncio.to_thread(
                                transcriber.transcribe, check_wav.getvalue()
                            )

                            if not check_text or not check_text.strip():
                                # No speech detected — prompt "still there?"
                                still_there_prompted = True
                                logger.info("No speech in conversational mode — prompting user")
                                prompt = "Are you still there? Take your time, and say 'I'm done' when you're finished."
                                await websocket.send_json({
                                    "event": "response",
                                    "text": prompt,
                                    "intent": "still_there_prompt",
                                })
                                await _send_tts(websocket, tts, prompt, squawk_mgr=squawk_mgr, device_id=device_id)
                                accumulated_parts.append(bytes(command_audio))
                                state = "listening"
                                command_audio = bytearray()
                                pre_roll = bytearray()
                                last_response_time = time.monotonic()
                                continue

                            # User said something — process it (skip re-transcription)
                            pre_transcription = check_text
                            logger.info(f"Conversational speech detected: {check_text[:100]}")

                        tts_duration = await _process_command(
                            websocket, command_audio, transcriber, tts, cmd, device_id,
                            detector=detector,
                            skip_wake_check=skip_wake_check,
                            pre_transcription=pre_transcription,
                            squawk_mgr=squawk_mgr,
                        ) or 0.0

                        # After processing, reset state
                        # Dynamic cooldown: base 3s + audio playback time
                        # ESP32 buffers audio, so it's still playing after we finish sending
                        still_there_prompted = False
                        RESPONSE_COOLDOWN = max(3.0, tts_duration + 1.0)
                        last_response_time = time.monotonic()
                        pre_roll = bytearray()
                        if conv_state and conv_state.is_conversational:
                            state = "listening"
                            command_audio = bytearray()
                        else:
                            state = "listening"
                            command_audio = bytearray()
                            detector.reset()

    except WebSocketDisconnect:
        logger.info(f"Continuous stream disconnected: {device_id}")
    except Exception as e:
        import traceback
        logger.error(f"Continuous stream error: {e}")
        traceback.print_exc()
    finally:
        if med_scheduler:
            med_scheduler.unregister_websocket(device_id)
        if squawk_mgr:
            squawk_mgr.unregister_device(device_id)


async def _process_command(
    websocket: WebSocket,
    command_audio: bytearray,
    transcriber,
    tts,
    cmd,
    device_id: str = "unknown",
    detector=None,
    skip_wake_check: bool = False,
    pre_transcription: str = None,
    squawk_mgr=None,
) -> float:
    """Run STT → intent parse → CommandProcessor → TTS on buffered command audio.
    Returns estimated TTS playback duration in seconds for cooldown calculation."""
    if len(command_audio) == 0 and not pre_transcription:
        await websocket.send_json({"event": "response", "text": "I didn't hear anything.", "audio": None})
        return 0.0

    if pre_transcription:
        transcription = pre_transcription
    else:
        # Wrap raw PCM in WAV header for STT
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(settings.CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(settings.SAMPLE_RATE)
            wf.writeframes(command_audio)
        wav_bytes = wav_buffer.getvalue()

        # Transcribe
        transcription = await asyncio.to_thread(transcriber.transcribe, wav_bytes)

    logger.info(f"Transcription: {transcription}")

    if not transcription:
        fallback = "I didn't catch that."
        await websocket.send_json({"event": "response", "text": fallback, "audio": None})
        dur = await _send_tts(websocket, tts, fallback, squawk_mgr=squawk_mgr, device_id=device_id)
        return dur

    # If using VAD detector, check transcription for wake phrase (skip in conversational mode)
    if detector and isinstance(detector, VADWakeWordDetector) and not skip_wake_check:
        is_wake, cleaned = detector.check_transcription(transcription)
        if not is_wake:
            logger.info(f"VAD: no wake phrase in transcription, ignoring: {transcription}")
            # Tell ESP32 to resume streaming (no command to process)
            await websocket.send_json({"event": "no_wake_word", "text": transcription})
            return 0.0
        logger.info(f"VAD: wake phrase found, command: {cleaned}")
        transcription = cleaned

    # Check if user is telling the parrot to be quiet
    text_lower = transcription.lower().strip()
    quiet_phrases = ["be quiet", "shut up", "stop squawking", "quiet", "hush",
                     "stop talking", "be quiet polly", "shush"]
    if squawk_mgr and any(p in text_lower for p in quiet_phrases):
        if squawk_mgr.is_playing(device_id):
            squawk_mgr.stop_playback(device_id)
            response_text = random.choice([
                "<speak>Okay okay!<break time=\"500ms\"/>Squawk.</speak>",
                "<speak>Fine, I'll be quiet.<break time=\"500ms\"/>For now.</speak>",
                "<speak>Alright, alright! Sheesh.</speak>",
            ])
            await websocket.send_json({
                "event": "response", "text": response_text,
                "intent": "be_quiet", "transcription": transcription,
                "mode": ConversationMode.COMMAND.value,
            })
            dur = await _send_tts(websocket, tts, response_text, squawk_mgr=squawk_mgr, device_id=device_id)
            return dur
        # Even if not currently playing, acknowledge it
        response_text = random.choice([
            "I wasn't even squawking!", "Who, me? I'm innocent!",
            "I'll try to keep it down.",
        ])
        await websocket.send_json({
            "event": "response", "text": response_text,
            "intent": "be_quiet", "transcription": transcription,
            "mode": ConversationMode.COMMAND.value,
        })
        dur = await _send_tts(websocket, tts, response_text, squawk_mgr=squawk_mgr, device_id=device_id)
        return dur

    # Intent parse
    intent_result = intent_parser.parse(transcription)
    logger.info(f"Intent: {intent_result}")

    # Use conversation-aware processing if available
    if hasattr(cmd, 'process_in_context'):
        response_text, new_mode = await cmd.process_in_context(intent_result, transcription, device_id)
        logger.info(f"Response: {response_text} (mode: {new_mode.value})")
    else:
        response_text = await cmd.process(intent_result, transcription, device_id)
        new_mode = ConversationMode.COMMAND
        logger.info(f"Response: {response_text}")

    # Send text response
    await websocket.send_json({
        "event": "response",
        "text": response_text,
        "intent": intent_result.get("intent"),
        "transcription": transcription,
        "mode": new_mode.value,
    })

    # Generate and send TTS audio
    duration = await _send_tts(websocket, tts, response_text, squawk_mgr=squawk_mgr, device_id=device_id)

    # Maybe squawk after responding (parrot personality)
    if squawk_mgr:
        asyncio.ensure_future(squawk_mgr.maybe_post_response_squawk(device_id))

    return duration


async def _send_tts(websocket: WebSocket, tts, text: str, squawk_mgr=None, device_id: str = None) -> float:
    """Generate TTS audio and send as chunked base64. Returns estimated playback duration in seconds."""
    try:
        tts_audio = tts.synthesize(text)
        if not tts_audio:
            return 0.0

        # Estimate playback duration: 16kHz, 16-bit mono = 32000 bytes/sec
        audio_duration = len(tts_audio) / 32000.0

        # Acquire send lock if available (prevents concurrent writes with squawk)
        lock = squawk_mgr.get_send_lock(device_id) if squawk_mgr and device_id else None

        async def _do_send():
            chunk_size = 8000
            for i in range(0, len(tts_audio), chunk_size):
                chunk = tts_audio[i:i + chunk_size]
                chunk_b64 = base64.b64encode(chunk).decode()
                await websocket.send_json({
                    "event": "audio_chunk",
                    "audio": chunk_b64,
                    "final": (i + chunk_size >= len(tts_audio)),
                })
                await asyncio.sleep(0.05)

        if lock:
            async with lock:
                await _do_send()
        else:
            await _do_send()

        return audio_duration
    except Exception as e:
        import traceback
        logger.error(f"TTS error: {e}")
        traceback.print_exc()
        return 0.0


# ─── Original Event-Based Stream Handler ─────────────────────────────────────

@router.websocket("/stream")
async def audio_stream(websocket: WebSocket):
    await websocket.accept()

    session: Optional[AudioSession] = None
    device_id: str = "unknown"

    app = websocket.app
    transcriber = app.state.transcriber
    tts = app.state.tts
    cmd = app.state.cmd
    med_scheduler_ev = getattr(app.state, "med_scheduler", None)

    try:
        while True:
            raw_message = await websocket.receive_text()

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                continue

            event = message.get("event")

            if event == "connect":
                device_id = message.get("device_id", "unknown")
                session = AudioSession(device_id)
                tenant_id_ev = 1  # default
                # Authenticate device
                device_info = verify_device_api_key(message.get("api_key", ""), app.state.db)
                if device_info:
                    conv_state_obj = cmd._get_state(device_id)
                    conv_state_obj.tenant_id = device_info["tenant_id"]
                    conv_state_obj.user_id = device_info["user_id"]
                    tenant_id_ev = device_info["tenant_id"]
                    logger.info(f"Device connected: {device_id} (tenant={device_info['tenant_id']})")
                elif not verify_websocket_key(message):
                    logger.warning(f"Device auth failed: {device_id}")
                    await websocket.send_json({"event": "error", "message": "Authentication failed"})
                    await websocket.close()
                    return
                else:
                    conv_state_obj = cmd._get_state(device_id)
                    conv_state_obj.tenant_id = 1
                    logger.info(f"Device connected: {device_id} (global key, tenant=1)")

                # Register for medication reminders
                if med_scheduler_ev:
                    med_scheduler_ev.register_websocket(device_id, websocket, tenant_id_ev)

                await websocket.send_json({"event": "connected", "message": "Ready"})

            elif event == "wake_word_detected":
                if not session:
                    session = AudioSession("unknown")
                session.listening_for_command = True
                session.clear_command()
                logger.info(f"Wake word detected by device: {device_id}")
                await websocket.send_json({"event": "wake_ack", "message": "Ready for command"})

            elif event == "audio_stream":
                if not session:
                    session = AudioSession("unknown")
                audio_b64 = message.get("data", "")
                if audio_b64 and session.listening_for_command:
                    audio_bytes = base64.b64decode(audio_b64)
                    session.command_audio.extend(audio_bytes)

            elif event == "command_end":
                if session and session.listening_for_command:
                    session.listening_for_command = False

                    if len(session.command_audio) > 0:
                        wav_bytes = session.get_wav_bytes(session.command_audio)
                        transcription = await asyncio.to_thread(transcriber.transcribe, wav_bytes)
                        logger.info(f"Transcription: {transcription}")

                        if transcription:
                            intent_result = intent_parser.parse(transcription)
                            logger.info(f"Intent: {intent_result}")

                            if hasattr(cmd, 'process_in_context'):
                                response_text, new_mode = await cmd.process_in_context(
                                    intent_result, transcription, device_id)
                            else:
                                response_text = await cmd.process(intent_result, transcription, device_id)
                                new_mode = ConversationMode.COMMAND
                            logger.info(f"Response: {response_text}")

                            await websocket.send_json({
                                "event": "response",
                                "text": response_text,
                                "audio": None,
                                "intent": intent_result.get("intent"),
                                "transcription": transcription,
                                "mode": new_mode.value,
                            })

                            await _send_tts(websocket, tts, response_text)
                        else:
                            await websocket.send_json({
                                "event": "response",
                                "text": "I didn't catch that.",
                                "audio": None
                            })

                    session.clear_command()

            elif event == "audio":
                if not session:
                    session = AudioSession("unknown")
                audio_b64 = message.get("data", "")
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    session.add_audio(audio_bytes)

            elif event == "end_stream":
                if not session or len(session.audio_buffer) == 0:
                    await websocket.send_json({"event": "error", "message": "No audio"})
                    continue

                logger.info(f"Processing {len(session.audio_buffer)} bytes")

                wav_bytes = session.get_wav_bytes()
                transcription = await asyncio.to_thread(transcriber.transcribe, wav_bytes)
                logger.info(f"Transcription: {transcription}")

                if not transcription:
                    await websocket.send_json({
                        "event": "response",
                        "text": "I didn't catch that.",
                        "audio": None
                    })
                    session.clear()
                    continue

                intent_result = intent_parser.parse(transcription)
                logger.info(f"Intent: {intent_result}")

                if hasattr(cmd, 'process_in_context'):
                    response_text, new_mode = await cmd.process_in_context(
                        intent_result, transcription, device_id)
                else:
                    response_text = await cmd.process(intent_result, transcription, device_id)
                    new_mode = ConversationMode.COMMAND
                logger.info(f"Response: {response_text}")

                await websocket.send_json({
                    "event": "response",
                    "text": response_text,
                    "audio": None,
                    "intent": intent_result.get("intent"),
                    "transcription": transcription,
                    "mode": new_mode.value,
                })

                await _send_tts(websocket, tts, response_text)
                session.clear()

            elif event == "ping":
                await websocket.send_json({"event": "pong"})

    except WebSocketDisconnect:
        logger.info(f"Device disconnected: {device_id}")
    finally:
        if med_scheduler_ev:
            med_scheduler_ev.unregister_websocket(device_id)
