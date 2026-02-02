# SoupaWhisper

A simple push-to-talk voice dictation tool for Linux using faster-whisper. Hold a key to record, release to transcribe, and it automatically copies to clipboard and types into the active input.

## Requirements

- Python 3.10+
- Poetry
- Linux with X11 (ALSA audio)

## Supported Distros

- Ubuntu / Pop!_OS / Debian (apt)
- Fedora (dnf)
- Arch Linux (pacman)
- openSUSE (zypper)

## Installation

```bash
git clone https://github.com/ksred/soupawhisper.git
cd soupawhisper
chmod +x install.sh
./install.sh
```

The installer will:
1. Detect your package manager
2. Install system dependencies
3. Install Python dependencies via Poetry
4. Set up the config file
5. Optionally install as a systemd service

### Manual Installation

```bash
# Ubuntu/Debian
sudo apt install alsa-utils xclip xdotool libnotify-bin

# Fedora
sudo dnf install alsa-utils xclip xdotool libnotify

# Arch
sudo pacman -S alsa-utils xclip xdotool libnotify

# Then install Python deps
poetry install
```

### GPU Support (Optional)

For NVIDIA GPU acceleration, install cuDNN 9:

```bash
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install libcudnn9-cuda-12
```

Then edit `~/.config/soupawhisper/config.ini`:
```ini
device = cuda
compute_type = float16
```

## Usage

```bash
poetry run python dictate.py
```

- Hold a configured hotkey to record (default: **F12**)
- Release to transcribe → copies to clipboard and types into active input
- Press **Ctrl+C** to quit (when running manually)

### Multi-Language Dictation

SoupaWhisper supports multiple languages with different hotkeys:

```ini
[whisper]
model_size = small    # Used for all languages

[languages]
en = f12    # English → automatically uses small.en
nl = f11    # Dutch → automatically uses small (multilingual)
de = f10    # German → automatically uses small (multilingual)
```

The `.en` model variant is automatically selected for English (faster and more accurate). Models are loaded on first use.

## Run as a systemd Service

The installer can set this up automatically. If you skipped it, run:

```bash
./install.sh  # Select 'y' when prompted for systemd
```

### Service Commands

```bash
systemctl --user start soupawhisper     # Start
systemctl --user stop soupawhisper      # Stop
systemctl --user restart soupawhisper   # Restart
systemctl --user status soupawhisper    # Status
journalctl --user -u soupawhisper -f    # View logs
```

## Configuration

Edit `~/.config/soupawhisper/config.ini`:

```ini
[whisper]
# Model size: tiny, base, small, medium, large-v3
# English automatically uses .en variant (e.g., small → small.en)
model_size = small

# Device: cpu or cuda (cuda requires cuDNN)
device = cpu

# Compute type: int8 for CPU, float16 for GPU
compute_type = int8

[languages]
# Format: language_code = hotkey
en = f12
nl = f11

[behavior]
# Type text into active input field
auto_type = true

# Show desktop notifications
notifications = true
```

Create the config directory and file if it doesn't exist:
```bash
mkdir -p ~/.config/soupawhisper
cp /path/to/soupawhisper/config.example.ini ~/.config/soupawhisper/config.ini
```

## Troubleshooting

**No audio recording:**
```bash
# Check your input device
arecord -l

# Test recording
arecord -d 3 test.wav && aplay test.wav
```

**Permission issues with keyboard:**
```bash
sudo usermod -aG input $USER
# Then log out and back in
```

**cuDNN errors with GPU:**
```
Unable to load any of {libcudnn_ops.so.9...}
```
Install cuDNN 9 (see GPU Support section above) or switch to CPU mode.

## Model Sizes

| model_size | Size | Speed | Notes |
|------------|------|-------|-------|
| tiny | ~75MB | Fastest | Basic accuracy |
| base | ~150MB | Fast | Good for most use |
| small | ~500MB | Medium | Better accuracy |
| medium | ~1.5GB | Slower | High accuracy |
| large-v3 | ~3GB | Slowest | Best accuracy |

- English automatically uses the `.en` variant (faster and more accurate)
- Other languages use the multilingual model with language hint
- Models are loaded lazily - only used models consume memory
- **Recommended**: `small` for good balance of speed and accuracy
