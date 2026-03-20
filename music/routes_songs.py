"""
routes_songs.py
---------------
Flask blueprint — drop into polly-connect alongside your existing routes.

Register in your app factory:
    from routes_songs import songs_bp
    app.register_blueprint(songs_bp)
"""

import os
import json
from flask import Blueprint, request, jsonify, send_file, session
from functools import wraps
from io import BytesIO

from song_pipeline import chapter_to_song, book_to_album

songs_bp = Blueprint("songs", __name__, url_prefix="/api/songs")


# ── Auth guard (reuse your existing decorator pattern) ────────────────────────
def subscription_required(tier="family"):
    """
    Require at least 'family' tier for single songs, 'legacy' for full albums.
    Adapt to match your existing subscription_required decorator logic.
    """
    tier_rank = {"free": 0, "family": 1, "legacy": 2}

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_tier = session.get("subscription_tier", "free")
            if tier_rank.get(user_tier, 0) < tier_rank.get(tier, 0):
                return jsonify({"error": f"Upgrade to {tier} tier to use this feature."}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── POST /api/songs/chapter ───────────────────────────────────────────────────
@songs_bp.route("/chapter", methods=["POST"])
@subscription_required(tier="family")
def generate_chapter_song():
    """
    Generate a song brief (lyrics + style prompt) for a single chapter.
    Audio generation is optional — set generate_audio=true to get MP3 bytes
    back as base64 (costs ElevenLabs credits, so default is brief-only).

    Request JSON:
    {
        "chapter_title": "Chapter 3: Leaving the Farm",
        "chapter_text":  "...",
        "person_name":   "Ruth Elaine Kowalski",
        "genre":         "auto" | "country" | "soul" | "folk" | etc,
        "generate_audio": false
    }
    """
    data = request.get_json()

    required = ["chapter_title", "chapter_text", "person_name"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    result = chapter_to_song(
        chapter_text=data["chapter_text"],
        chapter_title=data["chapter_title"],
        person_name=data["person_name"],
        genre_preference=data.get("genre", "auto"),
        generate_audio_file=data.get("generate_audio", False),
    )

    # Don't send raw bytes over JSON — encode if present
    audio_b64 = None
    if result["audio_bytes"]:
        import base64
        audio_b64 = base64.b64encode(result["audio_bytes"]).decode("utf-8")

    return jsonify({
        "song_title":    result["song_title"],
        "genre":         result["genre"],
        "lyrics":        result["lyrics"],
        "style_prompt":  result["style_prompt"],
        "jungian_stage": result["jungian_stage"],
        "audio_b64":     audio_b64,
        "song_brief":    result["song_brief"],
    })


# ── POST /api/songs/album ─────────────────────────────────────────────────────
@songs_bp.route("/album", methods=["POST"])
@subscription_required(tier="legacy")
def generate_full_album():
    """
    Legacy tier only. Process every chapter and return a full tracklist.
    Audio generation is expensive — set generate_audio=true only when ready
    to produce final deliverable.

    Request JSON:
    {
        "person_name": "Ruth Elaine Kowalski",
        "genre":       "auto",
        "generate_audio": false,
        "chapters": [
            {"title": "Chapter 1: The Early Years", "text": "..."},
            {"title": "Chapter 2: Leaving Home",    "text": "..."}
        ]
    }
    """
    data = request.get_json()

    if not data.get("chapters") or not isinstance(data["chapters"], list):
        return jsonify({"error": "chapters must be a non-empty list"}), 400
    if not data.get("person_name"):
        return jsonify({"error": "person_name is required"}), 400

    album = book_to_album(
        chapters=data["chapters"],
        person_name=data["person_name"],
        genre_preference=data.get("genre", "auto"),
        generate_audio_file=data.get("generate_audio", False),
    )

    # Strip raw bytes from JSON response
    clean_album = []
    for track in album:
        import base64
        audio_b64 = None
        if track.get("audio_bytes"):
            audio_b64 = base64.b64encode(track["audio_bytes"]).decode("utf-8")
        clean_album.append({
            "track_number":  track["track_number"],
            "chapter_title": track["chapter_title"],
            "song_title":    track["song_title"],
            "genre":         track["genre"],
            "lyrics":        track["lyrics"],
            "style_prompt":  track["style_prompt"],
            "jungian_stage": track["jungian_stage"],
            "audio_b64":     audio_b64,
        })

    return jsonify({
        "person_name": data["person_name"],
        "total_tracks": len(clean_album),
        "album": clean_album,
    })


# ── GET /api/songs/audio/<song_id> ────────────────────────────────────────────
@songs_bp.route("/audio/<song_id>", methods=["GET"])
@subscription_required(tier="family")
def stream_song_audio(song_id):
    """
    Stream a previously generated audio file by ID.
    Wire this to wherever you're persisting generated songs
    (filesystem, S3, Cloudflare R2, etc).

    Swap the stub below for your actual storage retrieval.
    """
    # ── STUB: replace with your storage layer ──
    audio_path = f"/tmp/polly_songs/{song_id}.mp3"
    if not os.path.exists(audio_path):
        return jsonify({"error": "Song not found"}), 404

    return send_file(
        audio_path,
        mimetype="audio/mpeg",
        as_attachment=False,
        download_name=f"polly_song_{song_id}.mp3",
    )
