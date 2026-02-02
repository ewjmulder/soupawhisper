#!/usr/bin/env python3
"""
SoupaWhisper - Voice dictation tool using faster-whisper.
Hold the hotkey to record, release to transcribe and copy to clipboard.
"""

import argparse
import configparser
import subprocess
import tempfile
import threading
import signal
import sys
import os
from pathlib import Path

from pynput import keyboard
from faster_whisper import WhisperModel

__version__ = "0.1.0"

# Load configuration
CONFIG_PATH = Path.home() / ".config" / "soupawhisper" / "config.ini"


def load_config():
    config = configparser.ConfigParser()

    # Defaults
    defaults = {
        "model_size": "base",
        "device": "cpu",
        "compute_type": "int8",
        "key": "f12",
        "auto_type": "true",
        "notifications": "true",
    }

    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH)

    model_size = config.get("whisper", "model_size", fallback=defaults["model_size"])

    # Load language configurations
    # Format: lang = hotkey
    # Model is determined automatically: .en for English, multilingual for others
    languages = {}
    if config.has_section("languages"):
        for lang, hotkey in config.items("languages"):
            # Use .en model for English (faster/more accurate), multilingual for others
            if lang == "en":
                model = f"{model_size}.en"
            else:
                model = model_size
            languages[lang] = {"key": hotkey.strip(), "model": model}
    else:
        # Backwards compatibility: use single hotkey with auto-detect
        languages["auto"] = {
            "key": config.get("hotkey", "key", fallback=defaults["key"]),
            "model": model_size
        }

    return {
        "model_size": model_size,
        "device": config.get("whisper", "device", fallback=defaults["device"]),
        "compute_type": config.get("whisper", "compute_type", fallback=defaults["compute_type"]),
        "languages": languages,
        "auto_type": config.getboolean("behavior", "auto_type", fallback=True),
        "notifications": config.getboolean("behavior", "notifications", fallback=True),
    }


CONFIG = load_config()


def get_hotkey(key_name):
    """Map key name to pynput key."""
    key_name = key_name.lower()
    if hasattr(keyboard.Key, key_name):
        return getattr(keyboard.Key, key_name)
    elif len(key_name) == 1:
        return keyboard.KeyCode.from_char(key_name)
    else:
        print(f"Unknown key: {key_name}, defaulting to f12")
        return keyboard.Key.f12


# Build hotkey-to-language mapping with model info
HOTKEY_TO_LANG = {}
for lang, lang_config in CONFIG["languages"].items():
    hotkey = get_hotkey(lang_config["key"])
    HOTKEY_TO_LANG[hotkey] = {"lang": lang, "model": lang_config["model"]}

DEVICE = CONFIG["device"]
COMPUTE_TYPE = CONFIG["compute_type"]
AUTO_TYPE = CONFIG["auto_type"]
NOTIFICATIONS = CONFIG["notifications"]


class Dictation:
    def __init__(self):
        self.recording = False
        self.record_process = None
        self.temp_file = None
        self.running = True
        self.active_language = None  # Track which language hotkey is pressed
        self.active_model_name = None  # Track which model to use

        # Model cache: model_name -> {"model": WhisperModel, "loaded": Event, "error": str|None}
        self.models = {}
        self.models_lock = threading.Lock()

        # Print configured hotkeys
        print("Configured languages:")
        for hotkey, config in HOTKEY_TO_LANG.items():
            key_name = hotkey.name if hasattr(hotkey, 'name') else hotkey.char
            lang = config["lang"]
            model = config["model"]
            lang_display = "auto-detect" if lang == "auto" else lang.upper()
            print(f"  [{key_name}] → {lang_display} (model: {model})")
        print("Models will be loaded on first use.")
        print("Press Ctrl+C to quit.")

    def _get_or_load_model(self, model_name):
        """Get a model from cache or load it if not yet loaded."""
        with self.models_lock:
            if model_name not in self.models:
                self.models[model_name] = {
                    "model": None,
                    "loaded": threading.Event(),
                    "error": None
                }
                # Start loading in background
                threading.Thread(
                    target=self._load_model,
                    args=(model_name,),
                    daemon=True
                ).start()
        return self.models[model_name]

    def _load_model(self, model_name):
        """Load a specific model."""
        model_info = self.models[model_name]
        print(f"Loading Whisper model ({model_name})...")
        try:
            model_info["model"] = WhisperModel(model_name, device=DEVICE, compute_type=COMPUTE_TYPE)
            print(f"Model {model_name} loaded.")
        except Exception as e:
            model_info["error"] = str(e)
            print(f"Failed to load model {model_name}: {e}")
            if "cudnn" in str(e).lower() or "cuda" in str(e).lower():
                print("Hint: Try setting device = cpu in your config, or install cuDNN.")
        finally:
            model_info["loaded"].set()

    def notify(self, title, message, icon="dialog-information", timeout=2000):
        """Send a desktop notification."""
        if not NOTIFICATIONS:
            return
        subprocess.run(
            [
                "notify-send",
                "-a", "SoupaWhisper",
                "-i", icon,
                "-t", str(timeout),
                "-h", "string:x-canonical-private-synchronous:soupawhisper",
                title,
                message
            ],
            capture_output=True
        )

    def start_recording(self, language, model_name, hotkey):
        if self.recording:
            return

        # Start loading model if not yet loaded (non-blocking)
        self._get_or_load_model(model_name)

        self.recording = True
        self.active_language = language
        self.active_model_name = model_name
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self.temp_file.close()

        # Record using arecord (ALSA) - works on most Linux systems
        self.record_process = subprocess.Popen(
            [
                "arecord",
                "-f", "S16_LE",  # Format: 16-bit little-endian
                "-r", "16000",   # Sample rate: 16kHz (what Whisper expects)
                "-c", "1",       # Mono
                "-t", "wav",
                self.temp_file.name
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        lang_display = "auto-detect" if language == "auto" else language.upper()
        hotkey_name = hotkey.name if hasattr(hotkey, 'name') else hotkey.char
        print(f"Recording ({lang_display})...")
        self.notify(f"Recording ({lang_display})...", f"Release {hotkey_name.upper()} when done", "audio-input-microphone", 30000)

    def stop_recording(self):
        if not self.recording:
            return

        self.recording = False

        if self.record_process:
            self.record_process.terminate()
            self.record_process.wait()
            self.record_process = None

        print("Transcribing...")
        self.notify("Transcribing...", "Processing your speech", "emblem-synchronizing", 30000)

        # Get the model for this language
        model_info = self._get_or_load_model(self.active_model_name)

        # Wait for model if not loaded yet
        model_info["loaded"].wait()

        if model_info["error"]:
            print(f"Cannot transcribe: model failed to load")
            self.notify("Error", "Model failed to load", "dialog-error", 3000)
            return

        # Transcribe with language setting
        try:
            transcribe_kwargs = {
                "beam_size": 5,
                "vad_filter": True,
            }
            # Only set language if not auto-detect and not using a .en model
            if self.active_language and self.active_language != "auto":
                if not self.active_model_name.endswith(".en"):
                    transcribe_kwargs["language"] = self.active_language

            segments, info = model_info["model"].transcribe(
                self.temp_file.name,
                **transcribe_kwargs,
            )

            text = " ".join(segment.text.strip() for segment in segments)

            if text:
                # Copy to clipboard using xclip
                process = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE
                )
                process.communicate(input=text.encode())

                # Type it into the active input field
                if AUTO_TYPE:
                    subprocess.run(["xdotool", "type", "--clearmodifiers", text])

                print(f"Copied: {text}")
                self.notify("Copied!", text[:100] + ("..." if len(text) > 100 else ""), "emblem-ok-symbolic", 3000)
            else:
                print("No speech detected")
                self.notify("No speech detected", "Try speaking louder", "dialog-warning", 2000)

        except Exception as e:
            print(f"Error: {e}")
            self.notify("Error", str(e)[:50], "dialog-error", 3000)
        finally:
            # Cleanup temp file
            if self.temp_file and os.path.exists(self.temp_file.name):
                os.unlink(self.temp_file.name)

    def on_press(self, key):
        if key in HOTKEY_TO_LANG:
            config = HOTKEY_TO_LANG[key]
            self.start_recording(config["lang"], config["model"], key)

    def on_release(self, key):
        if key in HOTKEY_TO_LANG and self.recording:
            self.stop_recording()

    def stop(self):
        print("\nExiting...")
        self.running = False
        os._exit(0)

    def run(self):
        with keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        ) as listener:
            listener.join()


def check_dependencies():
    """Check that required system commands are available."""
    missing = []

    for cmd in ["arecord", "xclip"]:
        if subprocess.run(["which", cmd], capture_output=True).returncode != 0:
            pkg = "alsa-utils" if cmd == "arecord" else cmd
            missing.append((cmd, pkg))

    if AUTO_TYPE:
        if subprocess.run(["which", "xdotool"], capture_output=True).returncode != 0:
            missing.append(("xdotool", "xdotool"))

    if missing:
        print("Missing dependencies:")
        for cmd, pkg in missing:
            print(f"  {cmd} - install with: sudo apt install {pkg}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="SoupaWhisper - Push-to-talk voice dictation"
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"SoupaWhisper {__version__}"
    )
    parser.parse_args()

    print(f"SoupaWhisper v{__version__}")
    print(f"Config: {CONFIG_PATH}")

    check_dependencies()

    dictation = Dictation()

    # Handle Ctrl+C gracefully
    def handle_sigint(sig, frame):
        dictation.stop()

    signal.signal(signal.SIGINT, handle_sigint)

    dictation.run()


if __name__ == "__main__":
    main()
