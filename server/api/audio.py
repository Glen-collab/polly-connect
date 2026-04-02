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
import os
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
    # Per-device wake word detector (model has internal state that gets corrupted
    # when multiple audio streams are interleaved). Cache per device_id to avoid
    # loading a new model on every reconnect (saves ~500MB RAM).
    from core.wakeword import WakeWordDetector
    _shared_detector = app.state.wake_word_detector
    if not hasattr(app.state, '_device_detectors'):
        app.state._device_detectors = {}
    # device_id not known yet — will be set after connect message. Use shared for now,
    # swap to per-device after we know the device_id.
    detector = _shared_detector
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
    SQUAWK_COOLDOWN = 5.0     # ignore triggers for 5s after squawk (speaker echo)
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

    # Mutable container so _log_event captures current tenant_id and DB device_id
    _evt_ctx = {"tenant_id": 1, "db_device_id": device_id}

    def _log_event(evt_type, intent=None, success=1, detail=None):
        """Log a device event for admin dashboard (never crashes pipeline)."""
        try:
            db.log_device_event(_evt_ctx["db_device_id"], _evt_ctx["tenant_id"],
                                evt_type, intent=intent, success=success, detail=detail)
        except Exception:
            pass

    try:
        while True:
            try:
                message = await websocket.receive()
            except RuntimeError as e:
                # "Cannot call receive once a disconnect message has been received"
                logger.info(f"WebSocket already disconnected: {e}")
                break

            if "text" in message:
                try:
                    msg_data = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                event = msg_data.get("event")

                if event == "connect":
                    device_id = msg_data.get("device_id", "unknown")
                    tenant_id = 1  # default
                    # Record firmware version if provided
                    fw_version = msg_data.get("fw_version")
                    fw_variant = msg_data.get("fw_variant")
                    # Authenticate device
                    device_info = verify_device_api_key(msg_data.get("api_key", ""), db)
                    if device_info:
                        # Guard: reject unclaimed devices with claim codes
                        if device_info.get("claim_code") and not device_info.get("claimed_at"):
                            logger.warning(f"Unclaimed device rejected: {device_id} (claim_code={device_info['claim_code']})")
                            await websocket.send_json({"event": "connected", "message": "Streaming mode ready"})
                            # Tell user to claim their device
                            unclaimed_msg = "Hello! I'm not set up yet. Please visit polly connect dot com, log in, and enter your claim code to activate me."
                            await _send_tts(websocket, tts, unclaimed_msg)
                            await websocket.close()
                            return

                        conv_state = cmd._get_state(device_id)
                        # Reset conversation mode on reconnect so stale
                        # FOLLOWUP_WAIT / STORY_PROMPT state doesn't persist
                        conv_state.reset()
                        conv_state.tenant_id = device_info["tenant_id"]
                        conv_state.user_id = device_info["user_id"]
                        tenant_id = device_info["tenant_id"]
                        # Save firmware info using the DB device_id
                        db_device_id = device_info.get("device_id") or device_id
                        if fw_version:
                            db.update_device_firmware_info(db_device_id, fw_version, fw_variant)
                            logger.info(f"Device {device_id} firmware: v{fw_version} ({fw_variant})")
                        logger.info(f"Continuous stream device: {device_id} (tenant={device_info['tenant_id']})")

                        # Mark device as seen (for admin dashboard online status)
                        try:
                            db.update_device_last_seen(db_device_id)
                        except Exception:
                            pass

                        # Swap to per-device wake word detector (cached, reused on reconnect)
                        if _shared_detector.ready and _shared_detector.model_path:
                            if device_id not in app.state._device_detectors:
                                app.state._device_detectors[device_id] = WakeWordDetector(
                                    model_path=_shared_detector.model_path,
                                    threshold=_shared_detector.threshold,
                                )
                                logger.info(f"Created wake word detector for {device_id}")
                            else:
                                app.state._device_detectors[device_id].reset()
                            detector = app.state._device_detectors[device_id]

                        # Load voice volume + default speaker from user profile
                        try:
                            user_profile = db.get_or_create_user(tenant_id=tenant_id)
                            conv_state.voice_volume = user_profile.get("voice_volume") or 100
                            # Default speaker to owner name so stories aren't "Unknown"
                            if not conv_state.speaker_name:
                                conv_state.speaker_name = user_profile.get("familiar_name") or user_profile.get("name")
                            logger.info(f"Voice volume: {conv_state.voice_volume}%")
                        except Exception:
                            conv_state.voice_volume = 100
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

                        # Swap to per-device wake word detector
                        if _shared_detector.ready and _shared_detector.model_path:
                            if device_id not in app.state._device_detectors:
                                app.state._device_detectors[device_id] = WakeWordDetector(
                                    model_path=_shared_detector.model_path,
                                    threshold=_shared_detector.threshold,
                                )
                            else:
                                app.state._device_detectors[device_id].reset()
                            detector = app.state._device_detectors[device_id]

                    # Register for medication reminders
                    if med_scheduler:
                        med_scheduler.register_websocket(device_id, websocket, tenant_id)

                    # Load family names into intent parser for person detection
                    try:
                        family_members = db.get_family_members(tenant_id=tenant_id)
                        family_names = set()
                        relation_to_name = {}
                        for m in family_members:
                            family_names.add(m["name"].lower().split()[0])  # first name
                            family_names.add(m["name"].lower())  # full name
                            if m.get("relation_to_owner"):
                                rel = m["relation_to_owner"].lower()
                                family_names.add(rel)
                                relation_to_name[rel] = m["name"]
                        intent_parser._family_names = family_names
                        intent_parser._relation_to_name = relation_to_name
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
                    _evt_ctx["tenant_id"] = tenant_id
                    _evt_ctx["db_device_id"] = device_info.get("device_id", device_id) if device_info else device_id
                    _log_event("connect")

                    # Load merged device + tenant settings (device overrides > tenant defaults)
                    ds = {"squawk_interval": 10, "chatter_interval": 45,
                          "quiet_hours_start": 21, "quiet_hours_end": 7,
                          "squawk_volume": 30, "rms_threshold": None,
                          "message_nag_enabled": 1}
                    try:
                        ds = db.get_device_settings(device_id, tenant_id)
                    except Exception:
                        pass

                    squawk_int = ds["squawk_interval"]
                    chatter_int = ds["chatter_interval"]
                    quiet_start = ds["quiet_hours_start"]
                    quiet_end = ds["quiet_hours_end"]
                    squawk_vol = ds["squawk_volume"]
                    user_rms_threshold = ds.get("rms_threshold")
                    msg_nag_enabled = ds.get("message_nag_enabled", 1)

                    # Apply user's RMS threshold if set
                    if user_rms_threshold is not None:
                        from core.vad_wakeword import VADWakeWordDetector
                        if isinstance(detector, VADWakeWordDetector):
                            detector.rms_threshold = user_rms_threshold
                            vad_threshold = user_rms_threshold
                            recording_silence_threshold = max(vad_threshold // 2, 50)
                            logger.info(f"RMS threshold set to {user_rms_threshold} from user profile")

                    # Register for ambient squawk sounds + startup squawk
                    if squawk_mgr:
                        squawk_mgr.register_device(device_id, websocket,
                                                   squawk_interval=squawk_int,
                                                   chatter_interval=chatter_int,
                                                   quiet_hours_start=quiet_start,
                                                   quiet_hours_end=quiet_end,
                                                   squawk_volume=squawk_vol,
                                                   message_nag_enabled=msg_nag_enabled)
                        # Load DB snooze state (survives restarts/disconnects)
                        try:
                            snoozed_str = ds.get("squawk_snoozed_until")
                            if snoozed_str:
                                from datetime import datetime as _dt
                                remaining_sec = (_dt.fromisoformat(snoozed_str) - _dt.utcnow()).total_seconds()
                                if remaining_sec > 0:
                                    squawk_mgr.snooze(device_id, int(remaining_sec / 60) + 1)
                            if ds.get("squawk_quiet_override"):
                                squawk_mgr._quiet_override[device_id] = True
                        except Exception:
                            pass

                        # Register nostalgia callback for chatter slots (20% chance)
                        _ns_tid = tenant_id
                        _ns_db = db
                        _ns_tts = tts
                        _ns_ws = websocket
                        _ns_smgr = squawk_mgr
                        _ns_dev = device_id
                        _ns_cmd = cmd
                        async def _nostalgia_chatter():
                            snippet = _ns_db.get_next_nostalgia_snippet(_ns_tid)
                            if snippet:
                                _ns_db.mark_nostalgia_used(snippet["id"])
                                logger.info(f"Nostalgia snippet → {_ns_dev}: {snippet['text'][:60]}...")
                                await _send_tts(_ns_ws, _ns_tts, snippet["text"],
                                                squawk_mgr=_ns_smgr, device_id=_ns_dev)
                                # Set last_response so "repeat" works
                                if _ns_cmd:
                                    _ns_cmd._last_response[_ns_dev] = snippet["text"]
                            else:
                                await _ns_smgr.send_chatter(_ns_dev)
                        squawk_mgr.register_nostalgia_callback(device_id, _nostalgia_chatter)

                        # Register prayer recording scheduler
                        _pr_db = db
                        _pr_tts = tts
                        _pr_ws = websocket
                        _pr_smgr = squawk_mgr
                        _pr_dev = device_id
                        _pr_tid = tenant_id
                        _pr_cmd = cmd
                        _pr_last_check = [0]  # mutable for closure

                        async def _check_scheduled_prayers():
                            """Check if any prayer recordings should play right now."""
                            import time as _time
                            now = _time.time()
                            # Only check once per minute
                            if now - _pr_last_check[0] < 60:
                                return False
                            _pr_last_check[0] = now

                            from datetime import datetime
                            from core.medications import _get_local_now
                            local_now = _get_local_now()
                            current_time = local_now.strftime("%H:%M")
                            day_of_week = local_now.weekday()
                            # Python weekday: Mon=0, Sun=6. Our schedule: Sun=0, Sat=6
                            day_of_week = (day_of_week + 1) % 7

                            prayers = _pr_db.get_scheduled_prayers(_pr_tid, day_of_week)
                            for prayer in prayers:
                                sched_time = prayer.get("schedule_time", "")
                                if not sched_time:
                                    continue
                                # Check if current time matches schedule (within 1 min window)
                                if sched_time == current_time:
                                    audio_file = prayer.get("audio_filename")
                                    if not audio_file:
                                        continue
                                    import os
                                    recordings_dir = os.path.join(
                                        os.path.dirname(os.path.dirname(__file__)),
                                        "static", "recordings"
                                    )
                                    filepath = os.path.join(recordings_dir, audio_file)
                                    if os.path.exists(filepath):
                                        speaker = prayer.get("speaker_name", "")
                                        title = prayer.get("title", "a prayer")
                                        logger.info(f"Scheduled prayer → {_pr_dev}: {speaker}'s {title}")
                                        # Send intro TTS then the recorded audio
                                        intro = f"{speaker}'s {prayer.get('category', 'prayer')}."
                                        await _send_tts(_pr_ws, _pr_tts, intro,
                                                       squawk_mgr=_pr_smgr, device_id=_pr_dev)
                                        # Send the recorded WAV
                                        with open(filepath, "rb") as f:
                                            wav_data = f.read()
                                        await _pr_smgr._send_wav(_pr_dev, wav_data)
                                        _pr_db.update_prayer_recording_played(prayer["id"])
                                        # Set last_response so "repeat" works
                                        if _pr_cmd:
                                            _pr_cmd._last_response[_pr_dev] = intro
                                        return True
                            return False

                        squawk_mgr.register_prayer_callback(device_id, _check_scheduled_prayers)

                        # Register message nag callback
                        _msg_db = db
                        _msg_tid = tenant_id
                        _msg_ws = websocket
                        _msg_tts = tts
                        _msg_smgr = squawk_mgr
                        _msg_dev = device_id
                        _msg_cmd = cmd
                        async def _has_messages():
                            msgs = _msg_db.get_messages_for(tenant_id=_msg_tid, device_id=_msg_dev)
                            return len(msgs) > 0
                        async def _tts_message(text):
                            await _send_tts(_msg_ws, _msg_tts, text,
                                           squawk_mgr=_msg_smgr, device_id=_msg_dev)
                            if _msg_cmd:
                                _msg_cmd._last_response[_msg_dev] = "You have messages on the board. Say 'check messages' to hear them."
                        squawk_mgr.register_message_callback(device_id, _has_messages, _tts_message)
                        # No startup squawk — scheduler handles timing with RECONNECT_GRACE

                    continue

                if event == "ping":
                    await websocket.send_json({"event": "pong"})
                    # Update last_seen on ping (~every 30s) for admin dashboard
                    if db_device_id:
                        try:
                            db.update_device_last_seen(db_device_id)
                        except Exception:
                            pass
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

                            # Auto-tag story with people, places, years
                            if transcript:
                                try:
                                    db.auto_tag_story(story_id, transcript, tenant_id=conv_state.tenant_id)
                                except Exception:
                                    pass

                            # Extract memory metadata if we have transcript
                            if transcript and len(transcript) > 20:
                                extractor = getattr(app.state, "memory_extractor", None)
                                if extractor:
                                    metadata = extractor.extract(
                                        transcript,
                                        speaker=conv_state.speaker_name,
                                    )
                                    mem_bucket = metadata.get("bucket", "ordinary_world")
                                    mem_phase = metadata.get("life_phase", "unknown")
                                    db.save_memory(
                                        story_id=story_id,
                                        speaker=metadata.get("speaker"),
                                        bucket=mem_bucket,
                                        life_phase=mem_phase,
                                        text_summary=metadata.get("text_summary", ""),
                                        text=transcript,
                                        people=",".join(metadata.get("people", [])),
                                        locations=",".join(metadata.get("locations", [])),
                                        emotions=",".join(metadata.get("emotions", [])),
                                        fingerprint=extractor.compute_fingerprint(metadata),
                                        tenant_id=conv_state.tenant_id,
                                    )
                                    # Flag matching chapters as needing refresh
                                    try:
                                        db.flag_chapters_for_refresh(
                                            mem_bucket, mem_phase,
                                            tenant_id=conv_state.tenant_id,
                                        )
                                    except Exception:
                                        pass

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
                            # Ignore speaker feedback after squawk/chatter
                            if squawk_mgr and not squawk_mgr.is_playing(device_id):
                                squawk_end = squawk_mgr.last_squawk_end.get(device_id, 0)
                                if time.monotonic() - squawk_end < SQUAWK_COOLDOWN:
                                    continue
                            # Interrupt squawk if playing
                            if squawk_mgr and squawk_mgr.is_playing(device_id):
                                squawk_mgr.stop_playback(device_id)
                            if squawk_mgr:
                                squawk_mgr.reset_idle_timer(device_id)
                            logger.info(f"Voice detected in conversational mode (device: {device_id})")
                            if squawk_mgr:
                                squawk_mgr.set_busy(device_id, True)
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
                        # Ignore triggers during cooldown after squawk/chatter
                        if squawk_mgr and not squawk_mgr.is_playing(device_id):
                            squawk_end = squawk_mgr.last_squawk_end.get(device_id, 0)
                            if time.monotonic() - squawk_end < RESPONSE_COOLDOWN:
                                continue

                        # Interrupt any playing squawk/chatter
                        if squawk_mgr and squawk_mgr.is_playing(device_id):
                            squawk_mgr.stop_playback(device_id)
                            logger.info(f"Squawk interrupted by wake word → {device_id}")

                        logger.info(f"*** WAKE WORD DETECTED (device: {device_id}) ***")
                        if squawk_mgr:
                            squawk_mgr.set_busy(device_id, True)
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

                        # Send instant acknowledgment chirp (pre-cached, ~0.3s)
                        # Skip in conversational mode — we might decide nobody spoke
                        ack_cache = getattr(app.state, "ack_cache", None)
                        is_conversational = conv_state and conv_state.is_conversational
                        if ack_cache and ack_cache.ready and not is_conversational:
                            ack_dur = await ack_cache.send_ack(
                                websocket, squawk_mgr=squawk_mgr, device_id=device_id)
                            if ack_dur > 0:
                                logger.info(f"Ack chirp sent ({ack_dur:.2f}s)")

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
                            db_device_id=_evt_ctx.get("db_device_id"),
                        ) or 0.0

                        # After processing, reset state
                        # Dynamic cooldown: base 3s + audio playback time
                        # ESP32 buffers audio, so it's still playing after we finish sending
                        if squawk_mgr:
                            squawk_mgr.set_busy(device_id, False)
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
        _log_event("disconnect")
    except Exception as e:
        import traceback
        logger.error(f"Continuous stream error: {e}")
        traceback.print_exc()
        _log_event("error", detail=str(e)[:500])
    finally:
        if squawk_mgr:
            squawk_mgr.set_busy(device_id, False)
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
    db_device_id: str = None,
) -> float:
    """Run STT → intent parse → CommandProcessor → TTS on buffered command audio.
    Returns estimated TTS playback duration in seconds for cooldown calculation."""
    # Load pronunciation guide for this tenant
    _pronunciations = []
    try:
        _db = getattr(websocket.app.state, "db", None)
        if _db:
            _conv = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
            _tid = _conv.tenant_id if _conv else 1
            _pronunciations = _db.get_pronunciations(_tid)
    except Exception:
        pass

    if len(command_audio) == 0 and not pre_transcription:
        await websocket.send_json({"event": "response", "text": "I didn't hear anything.", "audio": None})
        return 0.0

    # Save WAV first for conversational recordings (story answers)
    # Audio is preserved even if transcription or connection fails
    _saved_wav_filename = None
    conv_state_check = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
    if conv_state_check and conv_state_check.is_conversational and len(command_audio) > 16000:
        try:
            import uuid as _uuid
            wav_buf = io.BytesIO()
            with wave.open(wav_buf, 'wb') as wf:
                wf.setnchannels(settings.CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(settings.SAMPLE_RATE)
                wf.writeframes(command_audio)
            recordings_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "recordings")
            os.makedirs(recordings_dir, exist_ok=True)
            _saved_wav_filename = f"story_{device_id}_{_uuid.uuid4().hex[:8]}.wav"
            filepath = os.path.join(recordings_dir, _saved_wav_filename)
            with open(filepath, "wb") as f:
                f.write(wav_buf.getvalue())
            duration_sec = len(command_audio) / (settings.SAMPLE_RATE * 2)
            logger.info(f"Story audio saved: {_saved_wav_filename} ({duration_sec:.1f}s)")
        except Exception as e:
            logger.warning(f"Failed to save story WAV: {e}")
            _saved_wav_filename = None

    if pre_transcription:
        transcription = pre_transcription
    else:
        # Cap audio at 60s for Google STT (synchronous API limit)
        # Full audio is already saved as WAV above for story mode
        max_stt_bytes = settings.SAMPLE_RATE * 2 * 60  # 60 seconds of 16kHz 16-bit mono
        stt_audio = command_audio[:max_stt_bytes] if len(command_audio) > max_stt_bytes else command_audio
        if len(command_audio) > max_stt_bytes:
            logger.info(f"Audio exceeds 60s ({len(command_audio)} bytes), sending first 60s to STT")

        # Wrap raw PCM in WAV header for STT
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wf:
            wf.setnchannels(settings.CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(settings.SAMPLE_RATE)
            wf.writeframes(stt_audio)
        wav_bytes = wav_buffer.getvalue()

        # Transcribe with timeout to prevent hang
        try:
            transcription = await asyncio.wait_for(
                asyncio.to_thread(transcriber.transcribe, wav_bytes),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.error(f"STT timed out after 30s for {len(stt_audio)} bytes")
            transcription = ""

    logger.info(f"Transcription: {transcription}")

    if not transcription:
        # If in story mode with saved audio, still preserve it as a story
        if _saved_wav_filename and conv_state_check and conv_state_check.is_conversational:
            try:
                _db = getattr(websocket.app.state, "db", None)
                _tid = conv_state_check.tenant_id if conv_state_check else 1
                _q = getattr(conv_state_check, "current_question", None)
                _speaker = None
                try:
                    _usr = _db.get_or_create_user(tenant_id=_tid) if _db else {}
                    _speaker = _usr.get("name") or None
                except Exception:
                    pass
                story_id = _db.save_story(
                    transcript="(Transcription pending — long recording)",
                    audio_s3_key=_saved_wav_filename,
                    speaker_name=_speaker,
                    source="voice",
                    duration_seconds=len(command_audio) / (settings.SAMPLE_RATE * 2),
                    tenant_id=_tid,
                    question_text=_q,
                )
                logger.info(f"Saved story audio without transcription: id={story_id}, wav={_saved_wav_filename}")
                fallback = "I got your recording saved, but I had trouble with the transcription. You can check it on the stories page."
                await websocket.send_json({"event": "response", "text": fallback, "audio": None})
                dur = await _send_tts(websocket, tts, fallback, squawk_mgr=squawk_mgr, device_id=device_id)
                return dur
            except Exception as e:
                logger.error(f"Failed to save story without transcription: {e}")

        fallback = "I didn't catch that."
        await websocket.send_json({"event": "response", "text": fallback, "audio": None})
        dur = await _send_tts(websocket, tts, fallback, squawk_mgr=squawk_mgr, device_id=device_id)
        return dur

    # Strip wake phrase from transcription
    if not skip_wake_check:
        if detector and isinstance(detector, VADWakeWordDetector):
            # VAD mode: must contain wake phrase or reject
            is_wake, cleaned = detector.check_transcription(transcription)
            if not is_wake:
                text_check = transcription.lower().strip()
                repeat_phrases = ["repeat", "say that again", "say it again", "what did you say",
                                  "can you repeat", "repeat that", "one more time", "slower"]
                if any(p in text_check for p in repeat_phrases):
                    logger.info(f"VAD: no wake phrase but repeat command detected: {transcription}")
                    transcription = text_check
                else:
                    logger.info(f"VAD: no wake phrase in transcription, ignoring: {transcription}")
                    await websocket.send_json({"event": "no_wake_word", "text": transcription})
                    return 0.0
            else:
                logger.info(f"VAD: wake phrase found, command: {cleaned}")
                transcription = cleaned
        else:
            # OpenWakeWord mode: model already confirmed wake word, just strip the phrase
            import re as _re
            text_lower = transcription.lower().strip()
            for phrase in ["hey polly", "hey poly", "hey holly", "hey paulie",
                           "hey pauly", "hey paul", "polly", "poly"]:
                if text_lower.startswith(phrase):
                    cleaned = text_lower[len(phrase):].strip()
                    cleaned = _re.sub(r'^[,.\s]+', '', cleaned)
                    if cleaned:
                        logger.info(f"Wake phrase stripped: '{transcription}' → '{cleaned}'")
                        transcription = cleaned
                    break

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

    # Skip intent parsing in conversational mode — the answer is a story, not a command.
    # Only parse intent if we're in COMMAND mode.
    conv_state = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
    if conv_state and conv_state.is_conversational:
        intent_result = {"intent": "story_answer", "confidence": 1.0}
        logger.info(f"Intent: story_answer (conversational mode, skipped intent parse)")
    else:
        intent_result = intent_parser.parse(transcription)
        logger.info(f"Intent: {intent_result}")

    # Log command event for admin dashboard
    try:
        _db = getattr(websocket.app.state, "db", None)
        if _db:
            _conv = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
            _tid = _conv.tenant_id if _conv else 1
            _db.log_device_event(db_device_id or device_id, _tid, "command",
                                 intent=intent_result.get("intent"))
    except Exception:
        pass

    # Weather: play Almanac buffer while fetching weather in parallel
    if intent_result.get("intent") == "weather" and getattr(cmd, 'weather', None):
        from core.weather import get_almanac_note

        # Build location override from user settings
        _weather_loc = None
        try:
            _db = getattr(websocket.app.state, "db", None)
            if _db:
                _conv = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
                _tid = _conv.tenant_id if _conv else 1
                _wu = _db.get_or_create_user(tenant_id=_tid)
                if _wu and _wu.get("location_lat") and _wu.get("location_lon"):
                    _weather_loc = (_wu["location_lat"], _wu["location_lon"],
                                    _wu.get("location_city") or "your area")
        except Exception:
            pass
        _weather_ip = (cmd._get_state(device_id).client_ip
                       if hasattr(cmd, '_get_state') else None)

        # Start weather fetch in background thread (runs during TTS playback)
        weather_task = asyncio.ensure_future(
            asyncio.to_thread(_fetch_weather_sync, cmd.weather, _weather_ip, _weather_loc)
        )

        # Play Almanac fun fact immediately (takes ~8-10s to speak = plenty of fetch time)
        almanac_note = get_almanac_note()
        buffer_text = f"Did you know? {almanac_note}"
        await _send_tts(websocket, tts, buffer_text, squawk_mgr=squawk_mgr, device_id=device_id)

        # Weather should be ready by now
        try:
            weather_text = await weather_task
        except Exception as e:
            logger.error(f"Weather fetch error: {e}")
            weather_text = "I couldn't get the weather right now. Try again in a moment."

        await websocket.send_json({
            "event": "response", "text": weather_text,
            "intent": "weather", "transcription": transcription,
            "mode": ConversationMode.COMMAND.value,
        })
        duration = await _send_tts(websocket, tts, weather_text, squawk_mgr=squawk_mgr,
                                   device_id=device_id, pronunciations=_pronunciations)
        if squawk_mgr:
            asyncio.ensure_future(squawk_mgr.maybe_post_response_squawk(device_id, tts_duration=duration))
        return duration

    # Get owner's familiar name for personalized buffers
    _owner_name = None
    try:
        _db = getattr(websocket.app.state, "db", None)
        if _db:
            _conv = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
            _tid = _conv.tenant_id if _conv else 1
            _usr = _db.get_or_create_user(tenant_id=_tid)
            _owner_name = _usr.get("familiar_name") or _usr.get("name") or None
    except Exception:
        pass

    # Send a "thinking" buffer for hear_stories before GPT runs
    # Track buffer send time so we can ensure ESP32 finishes playback before
    # sending the main response (ESP32 holds a mutex during playback — if new
    # audio chunks arrive before it releases, the WS handler blocks and the
    # TCP buffer overflows, crashing the device).
    _buffer_sent_at = None
    _buffer_duration = 0.0

    if intent_result.get("intent") == "hear_stories":
        import random as _rnd
        _n = _owner_name
        buffer_phrases = [
            f"Oh {_n}, let me find a good one." if _n else "Oh, let me find a good one.",
            f"Hold on {_n}, let me look through some memories." if _n else "Hold on, let me look through some memories.",
            f"Give me just a moment {_n}, I want to find something special." if _n else "Give me just a moment to find something special.",
            f"Ooh {_n}, I know just the one. One moment." if _n else "Ooh, I know just the one. One moment.",
            f"Let me flip through the memory book for you, {_n}." if _n else "Let me flip through the memory book.",
            f"Hmm, let me remember. Just a second, {_n}." if _n else "Hmm, let me remember. Just a second.",
            f"Oh {_n}, I love this part. Let me find it." if _n else "Oh, I love this part. Let me find it.",
            f"Let me think of a good story for you, {_n}." if _n else "Let me think of a story for you.",
            "Let me pull up something from the family stories.",
            "Oh, this is going to be a good one. Hang tight.",
            f"You're going to love this one, {_n}. Just a moment." if _n else "You're going to love this one. Just a moment.",
            "Let me dig into the family memories real quick.",
            f"Alright {_n}, let's see what we've got." if _n else "Alright, let's see what we've got.",
            "Oh, I've got just the thing. One second.",
            f"Let me find something wonderful for you, {_n}." if _n else "Let me find something wonderful for you.",
            "Hmm, so many good ones to choose from. Give me a moment.",
            f"Sit tight {_n}, I'm looking for something special." if _n else "Sit tight, I'm looking for something special.",
            "Let me think back. There's a great one I want to share.",
            f"Oh {_n}, you'll enjoy this. Let me pull it together." if _n else "Oh, you'll enjoy this. Let me pull it together.",
            "Let me weave together a nice story from the memories.",
        ]
        buffer_phrase = _rnd.choice(buffer_phrases)
        _buffer_sent_at = time.monotonic()
        _buffer_duration = await _send_tts(websocket, tts, buffer_phrase, squawk_mgr=squawk_mgr,
                        device_id=device_id, pronunciations=_pronunciations)

    # Send a reverent buffer for prayer before GPT runs
    if intent_result.get("intent") == "prayer":
        import random as _rnd
        _n = _owner_name
        buffer_phrases = [
            f"Please bow your head in silence for a moment, {_n}. Let us come before the Lord together." if _n else "Please bow your head in silence for a moment. Let us come before the Lord together.",
            f"Now let us pray. Please bow your head in silence, {_n}, while I prepare this prayer for you." if _n else "Now let us pray. Please bow your head in silence while I prepare this prayer for you.",
            f"Let's be still and quiet for a moment, {_n}. Take a deep breath and let the Lord into your heart." if _n else "Let's be still and quiet for a moment. Take a deep breath and let the Lord into your heart.",
            f"Close your eyes, {_n}. Let's take a moment of silence together before we pray." if _n else "Close your eyes. Let's take a moment of silence together before we pray.",
            f"{_n}, let's bow our heads and be still. Give yourself a moment of peace before we begin." if _n else "Let's bow our heads and be still. Give yourself a moment of peace before we begin.",
            f"Please take a moment of quiet, {_n}. Let the world slow down while I lead us in prayer." if _n else "Please take a moment of quiet. Let the world slow down while I lead us in prayer.",
        ]
        buffer_phrase = _rnd.choice(buffer_phrases)
        _buffer_sent_at = time.monotonic()
        _buffer_duration = await _send_tts(websocket, tts, buffer_phrase, squawk_mgr=squawk_mgr,
                        device_id=device_id, pronunciations=_pronunciations)

    # Attach saved WAV filename to conversation state for story saving
    if _saved_wav_filename and conv_state_check:
        conv_state_check._pending_wav = _saved_wav_filename

    # Use conversation-aware processing if available
    if hasattr(cmd, 'process_in_context'):
        response_text, new_mode = await cmd.process_in_context(intent_result, transcription, device_id)
        logger.info(f"Response: {response_text} (mode: {new_mode.value})")
    else:
        response_text = await cmd.process(intent_result, transcription, device_id)
        new_mode = ConversationMode.COMMAND
        logger.info(f"Response: {response_text}")

    # Ensure ESP32 has finished playing the buffer phrase before we send
    # the main response audio.  The ESP32 holds a mutex during i2s playback;
    # if new audio_chunk messages arrive while the mutex is held, the WS
    # event handler blocks and the TCP receive buffer overflows → crash.
    # Wait for: buffer playback + 2s mic drain + 0.5s margin.
    if _buffer_sent_at and _buffer_duration > 0:
        elapsed = time.monotonic() - _buffer_sent_at
        needed = _buffer_duration + 2.5  # playback + drain + margin
        if elapsed < needed:
            wait_time = needed - elapsed
            logger.info(f"Waiting {wait_time:.1f}s for ESP32 buffer playback to finish")
            await asyncio.sleep(wait_time)

    # Send text response
    await websocket.send_json({
        "event": "response",
        "text": response_text,
        "intent": intent_result.get("intent"),
        "transcription": transcription,
        "mode": new_mode.value,
    })

    # Check for prayer recording playback marker
    if response_text and "__PLAY_PRAYER__" in response_text:
        import re as _re
        match = _re.match(r"__PLAY_PRAYER__(.+?)__INTRO__(.+)", response_text)
        if match:
            audio_file = match.group(1)
            intro_text = match.group(2)
            recordings_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "static", "recordings"
            )
            filepath = os.path.join(recordings_dir, audio_file)

            # Send the intro TTS first
            await websocket.send_json({
                "event": "response", "text": intro_text,
                "intent": "prayer", "transcription": transcription,
                "mode": new_mode.value,
            })
            intro_dur = await _send_tts(websocket, tts, intro_text,
                                         squawk_mgr=squawk_mgr, device_id=device_id,
                                         pronunciations=_pronunciations)

            # Then play the recorded WAV (apply voice volume)
            if os.path.exists(filepath) and squawk_mgr:
                await asyncio.sleep(0.3)  # brief pause between intro and message
                with open(filepath, "rb") as f:
                    wav_data = f.read()
                # Scale volume to match blessing volume setting
                try:
                    _db = getattr(websocket.app.state, "db", None)
                    _cmd = getattr(websocket.app.state, "cmd", None)
                    _cs = _cmd._get_state(device_id) if _cmd else None
                    _tid = _cs.tenant_id if _cs else 1
                    _usr = _db.get_or_create_user(tenant_id=_tid) if _db else {}
                    _vol = _usr.get("blessing_volume", 80)
                    if _vol is None:
                        _vol = 80
                    if _vol < 100:
                            import numpy as _np
                            # Skip WAV header (44 bytes) if present
                            hdr = 44 if wav_data[:4] == b'RIFF' else 0
                            samples = _np.frombuffer(wav_data[hdr:], dtype=_np.int16).astype(_np.float32)
                            samples = samples * (_vol / 100.0)
                            samples = _np.clip(samples, -32768, 32767).astype(_np.int16)
                            wav_data = wav_data[:hdr] + samples.tobytes()
                except Exception:
                    pass
                ws = squawk_mgr._active_devices.get(device_id, websocket)
                await squawk_mgr._send_wav(ws, device_id, wav_data)
                duration = len(wav_data) / 32000.0 + intro_dur
            else:
                duration = intro_dur
            return duration

    # Generate and send TTS audio (with pronunciation guide)
    duration = await _send_tts(websocket, tts, response_text, squawk_mgr=squawk_mgr,
                               device_id=device_id, pronunciations=_pronunciations)

    # Maybe squawk after responding (parrot personality)
    if squawk_mgr:
        asyncio.ensure_future(squawk_mgr.maybe_post_response_squawk(device_id, tts_duration=duration))

    return duration


def _fetch_weather_sync(weather_service, client_ip, location_override):
    """Synchronous weather fetch for use in asyncio.to_thread."""
    return weather_service.get_weather(
        client_ip=client_ip,
        location_override=location_override,
    )


async def _send_tts(websocket: WebSocket, tts, text: str, squawk_mgr=None,
                    device_id: str = None, pronunciations: list = None) -> float:
    """Generate TTS audio and send as chunked base64. Returns estimated playback duration in seconds."""
    try:
        # Apply pronunciation guide if available
        if pronunciations:
            from core.pronunciation import apply_pronunciations
            text = apply_pronunciations(text, pronunciations)

        tts_audio = tts.synthesize(text)
        if not tts_audio:
            return 0.0

        # Apply voice volume scaling from device's conversation state
        try:
            cmd = getattr(websocket.app.state, "cmd", None)
            if cmd and device_id:
                conv_state = cmd._get_state(device_id)
                vol = getattr(conv_state, "voice_volume", 100)
                if vol < 100:
                    import numpy as np
                    factor = vol / 100.0
                    samples = np.frombuffer(tts_audio, dtype=np.int16).astype(np.float32)
                    samples = samples * factor
                    samples = np.clip(samples, -32768, 32767).astype(np.int16)
                    tts_audio = samples.tobytes()
        except Exception:
            pass  # If anything fails, send at full volume

        # Estimate playback duration: 16kHz, 16-bit mono = 32000 bytes/sec
        audio_duration = len(tts_audio) / 32000.0

        # Acquire send lock if available (prevents concurrent writes with squawk)
        lock = squawk_mgr.get_send_lock(device_id) if squawk_mgr and device_id else None

        async def _do_send():
            # Smaller chunks + longer delays for large audio to avoid
            # overwhelming ESP32's WebSocket receive buffer / TCP stack.
            # ESP32 buffers all chunks before playback, so we need to
            # pace the sends to avoid TCP buffer overflow → freeze.
            total_len = len(tts_audio)
            if total_len > 128000:  # ~4s of audio — large response
                chunk_size = 4000
                chunk_delay = 0.08
            elif total_len > 64000:  # ~2s of audio — medium response
                chunk_size = 6000
                chunk_delay = 0.06
            else:
                chunk_size = 8000
                chunk_delay = 0.05

            for i in range(0, total_len, chunk_size):
                chunk = tts_audio[i:i + chunk_size]
                chunk_b64 = base64.b64encode(chunk).decode()
                await websocket.send_json({
                    "event": "audio_chunk",
                    "audio": chunk_b64,
                    "final": (i + chunk_size >= total_len),
                })
                await asyncio.sleep(chunk_delay)

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
        try:
            _db = getattr(websocket.app.state, "db", None)
            if _db:
                _db.log_device_event(device_id or "unknown", 1, "error",
                                     detail=f"TTS: {str(e)[:400]}")
        except Exception:
            pass
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
                # Record firmware version if provided
                fw_version = message.get("fw_version")
                fw_variant = message.get("fw_variant")
                # Authenticate device
                device_info = verify_device_api_key(message.get("api_key", ""), app.state.db)
                if device_info:
                    conv_state_obj = cmd._get_state(device_id)
                    conv_state_obj.tenant_id = device_info["tenant_id"]
                    conv_state_obj.user_id = device_info["user_id"]
                    tenant_id_ev = device_info["tenant_id"]
                    # Save firmware info using the DB device_id
                    db_device_id = device_info.get("device_id") or device_id
                    if fw_version:
                        app.state.db.update_device_firmware_info(db_device_id, fw_version, fw_variant)
                        logger.info(f"Device {device_id} firmware: v{fw_version} ({fw_variant})")
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
                            _cs = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
                            if _cs and _cs.is_conversational:
                                intent_result = {"intent": "story_answer", "confidence": 1.0}
                                logger.info(f"Intent: story_answer (conversational mode)")
                            else:
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

                _cs = cmd._get_state(device_id) if hasattr(cmd, '_get_state') else None
                if _cs and _cs.is_conversational:
                    intent_result = {"intent": "story_answer", "confidence": 1.0}
                    logger.info(f"Intent: story_answer (conversational mode)")
                else:
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
