"""
Text-to-Speech module for Polly Connect
Generates audio responses to send back to ESP32
"""

import io
import logging
import tempfile
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import TTS engines
TTS_ENGINES = []

try:
    import pyttsx3
    TTS_ENGINES.append("pyttsx3")
except ImportError:
    pass

try:
    from gtts import gTTS
    TTS_ENGINES.append("gtts")
except ImportError:
    pass

# espeak is typically available on Linux
try:
    import subprocess
    result = subprocess.run(["which", "espeak"], capture_output=True)
    if result.returncode == 0:
        TTS_ENGINES.append("espeak")
except:
    pass

logger.info(f"Available TTS engines: {TTS_ENGINES}")


class TTSEngine:
    """
    Text-to-speech engine.
    
    Supports multiple backends:
    - pyttsx3: Cross-platform, offline
    - espeak: Linux, offline
    - gtts: Google TTS, requires internet
    """
    
    def __init__(self, engine: str = "auto", rate: int = 150, voice: str = ""):
        """
        Initialize TTS engine.
        
        Args:
            engine: Engine to use (auto, pyttsx3, espeak, gtts)
            rate: Speech rate (words per minute)
            voice: Voice ID (engine-specific)
        """
        self.rate = rate
        self.voice = voice
        self.engine_name = engine
        self.engine = None
        
        if engine == "auto":
            # Pick best available
            if "pyttsx3" in TTS_ENGINES:
                self.engine_name = "pyttsx3"
            elif "espeak" in TTS_ENGINES:
                self.engine_name = "espeak"
            elif "gtts" in TTS_ENGINES:
                self.engine_name = "gtts"
            else:
                logger.warning("No TTS engine available!")
                self.engine_name = None
                
        if self.engine_name == "pyttsx3":
            try:
                self.engine = pyttsx3.init()
                self.engine.setProperty('rate', rate)
                if voice:
                    self.engine.setProperty('voice', voice)
                logger.info("Initialized pyttsx3 TTS engine")
            except Exception as e:
                logger.error(f"Failed to init pyttsx3: {e}")
                self.engine_name = None
                
        logger.info(f"Using TTS engine: {self.engine_name}")
        
    def speak(self, text: str) -> Optional[bytes]:
        """
        Convert text to speech audio.
        
        Args:
            text: Text to speak
            
        Returns:
            WAV audio bytes, or None if failed
        """
        if not text:
            return None
            
        if not self.engine_name:
            logger.warning("No TTS engine available")
            return None
            
        try:
            if self.engine_name == "pyttsx3":
                return self._speak_pyttsx3(text)
            elif self.engine_name == "espeak":
                return self._speak_espeak(text)
            elif self.engine_name == "gtts":
                return self._speak_gtts(text)
        except Exception as e:
            logger.error(f"TTS error: {e}", exc_info=True)
            return None
            
    def _speak_pyttsx3(self, text: str) -> Optional[bytes]:
        """Generate speech using pyttsx3."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
            
        try:
            self.engine.save_to_file(text, temp_path)
            self.engine.runAndWait()
            
            with open(temp_path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    def _speak_espeak(self, text: str) -> Optional[bytes]:
        """Generate speech using espeak."""
        import subprocess
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
            
        try:
            cmd = [
                "espeak",
                "-w", temp_path,
                "-s", str(self.rate),
                text
            ]
            if self.voice:
                cmd.extend(["-v", self.voice])
                
            subprocess.run(cmd, check=True, capture_output=True)
            
            with open(temp_path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    def _speak_gtts(self, text: str) -> Optional[bytes]:
        """Generate speech using Google TTS (requires internet)."""
        from gtts import gTTS
        from pydub import AudioSegment
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            mp3_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
            
        try:
            # Generate MP3
            tts = gTTS(text=text, lang='en')
            tts.save(mp3_path)
            
            # Convert to WAV
            audio = AudioSegment.from_mp3(mp3_path)
            audio = audio.set_frame_rate(16000).set_channels(1)
            audio.export(wav_path, format="wav")
            
            with open(wav_path, "rb") as f:
                return f.read()
        finally:
            for path in [mp3_path, wav_path]:
                if os.path.exists(path):
                    os.unlink(path)


# Test
if __name__ == "__main__":
    print(f"Available engines: {TTS_ENGINES}")
    
    if TTS_ENGINES:
        tts = TTSEngine()
        audio = tts.speak("Hello, I am Polly. How can I help you?")
        if audio:
            print(f"Generated {len(audio)} bytes of audio")
            # Save for testing
            with open("test_tts.wav", "wb") as f:
                f.write(audio)
            print("Saved to test_tts.wav")
        else:
            print("Failed to generate audio")
    else:
        print("No TTS engines available")
