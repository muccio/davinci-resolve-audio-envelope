#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AudioEnvelopeToVideo.py
-----------------------
DaVinci Resolve Script (Compatible with Resolve 19, 20, 21+)
Standalone script executable via: Workspace > Scripts > AudioEnvelopeToVideo

Description:
    Analyzes an audio clip on the DaVinci Resolve timeline and converts its
    RMS amplitude envelope into animated keyframe curves applied directly to
    video parameters (Transform, Brightness/Contrast, etc.) inside the Edit Page
    via Fusion Composition, without requiring manual switching to the Fusion Page.

Author: Senior DaVinci Resolve & Fusion Pipeline Developer
"""

import sys
import os
import math
import array
import struct
import subprocess
import traceback

# ==============================================================================
# RESOLVE & FUSION API INITIALIZATION
# ==============================================================================

def get_resolve():
    """
    Connects to the DaVinci Resolve scripting environment.
    Supports execution directly within Resolve (Workspace > Scripts) or externally.
    """
    # Check if resolve is already provided in the global namespace
    if "resolve" in globals() and globals()["resolve"] is not None:
        return globals()["resolve"]

    try:
        import DaVinciResolveScript as bmd
        return bmd.scriptapp("Resolve")
    except ImportError:
        # Resolve fallback paths across platforms
        expected_paths = []
        if sys.platform.startswith("darwin"):
            expected_paths.append("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/")
        elif sys.platform.startswith("win") or sys.platform.startswith("cygwin"):
            prog_data = os.getenv("PROGRAMDATA", "C:\\ProgramData")
            expected_paths.append(os.path.join(prog_data, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules"))
        elif sys.platform.startswith("linux"):
            expected_paths.append("/opt/resolve/Developer/Scripting/Modules/")

        for p in expected_paths:
            if os.path.exists(p) and p not in sys.path:
                sys.path.append(p)

        try:
            import DaVinciResolveScript as bmd
            return bmd.scriptapp("Resolve")
        except Exception:
            return None


def get_bmd():
    """Returns the bmd module providing UIDispatcher."""
    if "bmd" in globals() and globals()["bmd"] is not None:
        return globals()["bmd"]
    try:
        import DaVinciResolveScript as bmd
        return bmd
    except ImportError:
        return None


# ==============================================================================
# AUDIO DSP & FILE DECODING
# ==============================================================================

def find_ffmpeg_bin():
    """
    Locates the ffmpeg executable across standard PATH and known directory locations
    even when running inside a GUI app without an interactive shell environment.
    """
    import shutil
    p = shutil.which("ffmpeg")
    if p and os.path.exists(p):
        return p

    candidates = [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/opt/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
        os.path.expanduser("~/bin/ffmpeg"),
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
        "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def read_audio_file(file_path):
    """
    Robust, multi-tiered audio reader:
      1. soundfile (if installed, handles WAV, AIFF, FLAC, OGG, etc.)
      2. scipy.io.wavfile (if installed, handles standard WAV)
      3. Python standard library 'wave' module (zero-dependency fallback for PCM WAV)
      4. macOS native 'afconvert' CLI (zero-dependency for MP3, AAC, M4A, ALAC on Mac)
      5. ffmpeg CLI (handles MP3, AAC, FLAC, MOV, MP4 audio extraction)

    Returns:
        tuple: (samples_list_or_numpy_array, sample_rate_int)
    """
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f"File audio sorgente non trovato su disco: '{file_path}'")

    # Tier 1: soundfile
    try:
        import soundfile as sf
        data, sr = sf.read(file_path, dtype="float32")
        if len(data.shape) > 1:
            data = data.mean(axis=1)  # Downmix to mono
        return data.tolist(), int(sr)
    except Exception:
        pass

    # Tier 2: scipy.io.wavfile
    try:
        from scipy.io import wavfile
        import numpy as np
        sr, data = wavfile.read(file_path)
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            data = (data.astype(np.float32) - 128.0) / 128.0
        elif data.dtype != np.float32:
            data = data.astype(np.float32)

        if len(data.shape) > 1:
            data = data.mean(axis=1)
        return data.tolist(), int(sr)
    except Exception:
        pass

    # Tier 3: Built-in wave module (Zero-dependency for standard PCM WAV)
    try:
        import wave
        with wave.open(file_path, "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            sr = wf.getframerate()
            n_frames = wf.getnframes()
            raw_bytes = wf.readframes(n_frames)

            if sampwidth == 2:  # 16-bit PCM
                arr = array.array("h")
                arr.frombytes(raw_bytes)
                if n_channels == 1:
                    data = [s / 32768.0 for s in arr]
                else:
                    data = []
                    for i in range(0, len(arr), n_channels):
                        sub = arr[i : i + n_channels]
                        data.append(sum(sub) / (len(sub) * 32768.0))
                return data, int(sr)

            elif sampwidth == 3:  # 24-bit PCM
                data_raw = []
                for i in range(0, len(raw_bytes), 3):
                    b = raw_bytes[i : i + 3]
                    val = int.from_bytes(b, byteorder="little", signed=True)
                    data_raw.append(val / 8388608.0)
                if n_channels == 1:
                    data = data_raw
                else:
                    data = []
                    for i in range(0, len(data_raw), n_channels):
                        sub = data_raw[i : i + n_channels]
                        data.append(sum(sub) / len(sub))
                return data, int(sr)

            elif sampwidth == 4:  # 32-bit PCM
                arr = array.array("i")
                arr.frombytes(raw_bytes)
                if n_channels == 1:
                    data = [s / 2147483648.0 for s in arr]
                else:
                    data = []
                    for i in range(0, len(arr), n_channels):
                        sub = arr[i : i + n_channels]
                        data.append(sum(sub) / (len(sub) * 2147483648.0))
                return data, int(sr)
    except Exception:
        pass

    # Tier 4: macOS native 'afconvert' CLI (zero-dependency, built-in on all Macs)
    if sys.platform == "darwin" and os.path.exists("/usr/bin/afconvert"):
        import tempfile
        tmp_wav = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_f:
                tmp_wav = tmp_f.name
            cmd = ["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16", "-c", "1", file_path, tmp_wav]
            ret = subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ret == 0 and os.path.exists(tmp_wav) and os.path.getsize(tmp_wav) > 44:
                import wave
                with wave.open(tmp_wav, "rb") as wf:
                    sr = wf.getframerate()
                    n_frames = wf.getnframes()
                    raw_bytes = wf.readframes(n_frames)
                    arr = array.array("h")
                    arr.frombytes(raw_bytes)
                    data = [s / 32768.0 for s in arr]
                    return data, int(sr)
        except Exception:
            pass
        finally:
            if tmp_wav and os.path.exists(tmp_wav):
                try:
                    os.remove(tmp_wav)
                except Exception:
                    pass

    # Tier 5: ffmpeg subprocess fallback for MP3/AAC/FLAC/MOV/MP4
    ffmpeg_bin = find_ffmpeg_bin()
    if ffmpeg_bin:
        try:
            cmd = [ffmpeg_bin, "-v", "error", "-i", file_path, "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            raw_audio, _ = proc.communicate()
            if proc.returncode == 0 and len(raw_audio) > 0:
                arr = array.array("h")
                arr.frombytes(raw_audio)
                data = [s / 32768.0 for s in arr]
                return data, 48000
        except Exception:
            pass

    raise RuntimeError(
        f"Impossibile decodificare il file audio: '{os.path.basename(file_path)}'.\n"
        "Suggerimento: Per formati compressi esporta la traccia audio in formato WAV PCM a 16 o 24 bit."
    )


# ==============================================================================
# FFT SPECTRAL ANALYSIS ENGINE
# ==============================================================================

FREQUENCY_PRESETS = {
    "Tutto lo spettro (Full Spectrum)": (20.0, 20000.0),
    "Sub-Bass / Cassa (20 - 90 Hz)": (20.0, 90.0),
    "Bass / Linea di Basso (80 - 250 Hz)": (80.0, 250.0),
    "Low-Mid / Corpo Rullante (250 - 600 Hz)": (250.0, 600.0),
    "Midrange / Voci & Lead (600 - 2500 Hz)": (600.0, 2500.0),
    "High-Mid / Presenza & Attacco (2500 - 7000 Hz)": (2500.0, 7000.0),
    "Treble / Hi-Hat & Piatti (7000 - 18000 Hz)": (7000.0, 18000.0),
    "Personalizzato (Custom Range)": (20.0, 20000.0),
}


class PurePythonFFT:
    """
    High-performance iterative Radix-2 Cooley-Tukey FFT with precomputed
    bit-reversal permutation and twiddle factors for zero-dependency Python environments.
    """
    def __init__(self, size=1024):
        self.size = size
        self.levels = int(math.log2(size))
        self.rev = [0] * size
        for i in range(size):
            r = 0
            for j in range(self.levels):
                if (i >> j) & 1:
                    r |= (1 << (self.levels - 1 - j))
            self.rev[i] = r
        self.twiddle = [math.e ** (-2j * math.pi * k / size) for k in range(size // 2)]

    def transform(self, x):
        n = self.size
        a = [complex(x[self.rev[i]]) for i in range(n)]
        size = 2
        while size <= n:
            half = size // 2
            step = n // size
            for i in range(0, n, size):
                for k in range(half):
                    w = self.twiddle[k * step]
                    u = a[i + k]
                    v = a[i + k + half] * w
                    a[i + k] = u + v
                    a[i + k + half] = u - v
            size *= 2
        return a


def compute_frame_fft_band(audio_samples, sample_rate, frame_start_idx, frame_count, fps, min_hz=20.0, max_hz=20000.0):
    """
    Computes spectral band magnitude using FFT for each frame.
    Supports isolating frequency bands (e.g. Bass 20-90Hz, Hi-Hats 7-18kHz).
    Uses numpy if available, or PurePythonFFT if running in bare Python.
    """
    total_audio_samples = len(audio_samples)
    fft_size = 1024
    freq_res = sample_rate / float(fft_size)

    # Bin indices corresponding to requested frequency interval
    min_bin = max(0, int(math.floor(min_hz / freq_res)))
    max_bin = min(fft_size // 2, int(math.ceil(max_hz / freq_res)))
    if max_bin < min_bin:
        max_bin = min_bin

    # Hann window to minimize spectral leakage
    hann = [0.5 * (1.0 - math.cos(2.0 * math.pi * i / (fft_size - 1))) for i in range(fft_size)]

    use_np = False
    try:
        import numpy as np
        use_np = True
    except ImportError:
        pass

    fft_engine = None if use_np else PurePythonFFT(fft_size)
    band_values = []

    for f in range(frame_count):
        src_frame = frame_start_idx + f
        if src_frame < 0:
            band_values.append(0.0)
            continue

        s_start = int(round(src_frame * sample_rate / fps))
        s_end = s_start + fft_size

        if s_start >= total_audio_samples:
            band_values.append(0.0)
            continue

        chunk = audio_samples[s_start : min(s_end, total_audio_samples)]
        if len(chunk) < fft_size:
            chunk = chunk + [0.0] * (fft_size - len(chunk))

        windowed = [chunk[i] * hann[i] for i in range(fft_size)]

        if use_np:
            spec = np.abs(np.fft.rfft(windowed))
            band = spec[min_bin : max_bin + 1]
            val = float(np.sqrt(np.mean(band ** 2))) if len(band) > 0 else 0.0
        else:
            X = fft_engine.transform(windowed)
            band_sq = [abs(X[k]) ** 2 for k in range(min_bin, max_bin + 1)]
            val = math.sqrt(sum(band_sq) / len(band_sq)) if band_sq else 0.0

        band_values.append(val)

    return band_values


def compute_frame_rms(audio_samples, sample_rate, frame_start_idx, frame_count, fps):
    """
    Computes RMS amplitude for each frame across the requested frame window.
    Accurately handles fractional framerates without drift.

    Args:
        audio_samples: list of normalized float audio samples (-1.0 to 1.0)
        sample_rate: int, e.g. 48000
        frame_start_idx: int, starting frame index in the source audio file
        frame_count: int, number of video frames to compute
        fps: float, timeline framerate (e.g. 23.976, 24.0, 29.97, 60.0)

    Returns:
        list of float RMS values per frame
    """
    total_audio_samples = len(audio_samples)
    rms_list = []

    for f in range(frame_count):
        src_frame = frame_start_idx + f
        if src_frame < 0:
            rms_list.append(0.0)
            continue

        s_start = int(round(src_frame * sample_rate / fps))
        s_end = int(round((src_frame + 1) * sample_rate / fps))

        if s_start >= total_audio_samples or s_start >= s_end:
            rms_list.append(0.0)
            continue

        s_end_clamped = min(s_end, total_audio_samples)
        window = audio_samples[s_start:s_end_clamped]

        if not window:
            rms_list.append(0.0)
            continue

        sum_sq = sum(x * x for x in window)
        rms = math.sqrt(sum_sq / len(window))
        rms_list.append(rms)

    return rms_list


def apply_envelope_follower(rms_list, attack_val, release_val, window_size):
    """
    Applies Attack / Release one-pole IIR smoothing and moving average filtering.

    Formula:
        if RMS[t] > Env[t-1]:  (Attack phase)
            Env[t] = alpha_attack * Env[t-1] + (1 - alpha_attack) * RMS[t]
        else:                   (Release phase)
            Env[t] = alpha_release * Env[t-1] + (1 - alpha_release) * RMS[t]

    Args:
        rms_list: list of raw RMS amplitudes per frame
        attack_val: float 0.0 to 1.0 (0.0 = immediate attack, 1.0 = heavy smoothing)
        release_val: float 0.0 to 1.0 (0.0 = immediate drop, 1.0 = long sustained decay)
        window_size: int, size of centered moving average window (1 = no moving average)

    Returns:
        list of smoothed envelope values
    """
    if not rms_list:
        return []

    # Map [0.0, 1.0] to IIR alpha coefficients
    # 0.0 -> alpha = 0.0 (instantaneous response)
    # 1.0 -> alpha = 0.96 (slow/soft transition)
    alpha_att = max(0.0, min(0.96, attack_val * 0.96))
    alpha_rel = max(0.0, min(0.98, release_val * 0.98))

    env = [0.0] * len(rms_list)
    env[0] = rms_list[0]

    for t in range(1, len(rms_list)):
        cur_rms = rms_list[t]
        prev_env = env[t - 1]
        if cur_rms > prev_env:
            env[t] = alpha_att * prev_env + (1.0 - alpha_att) * cur_rms
        else:
            env[t] = alpha_rel * prev_env + (1.0 - alpha_rel) * cur_rms

    # Apply Moving Average filter if requested
    if window_size > 1 and len(env) > 1:
        half_w = window_size // 2
        smoothed = []
        n = len(env)
        for t in range(n):
            left = max(0, t - half_w)
            right = min(n, t + half_w + 1)
            sub = env[left:right]
            smoothed.append(sum(sub) / len(sub))
        env = smoothed

    return env


def map_envelope_to_range(env, min_out, max_out):
    """
    Normalizes envelope array [0.0, 1.0] and scales to [min_out, max_out].
    """
    if not env:
        return []

    min_e = min(env)
    max_e = max(env)
    delta = max_e - min_e

    output = []
    for val in env:
        norm = (val - min_e) / delta if delta > 1e-7 else 0.0
        scaled = min_out + norm * (max_out - min_out)
        output.append(scaled)

    return output


# ==============================================================================
# TIMELINE & CLIP SYNCHRONIZATION HELPERS
# ==============================================================================

def timecode_to_seconds(tc_str, fps):
    """Parses HH:MM:SS:FF or HH:MM:SS;FF into total seconds."""
    if not tc_str:
        return 0.0
    parts = tc_str.replace(";", ":").split(":")
    if len(parts) == 4:
        try:
            h, m, s, f = [float(p) for p in parts]
            return h * 3600.0 + m * 60.0 + s + (f / fps)
        except ValueError:
            return 0.0
    return 0.0


def get_timeline_playhead_frame(timeline, fps):
    """
    Calculates current playhead frame relative to timeline frame index.
    """
    try:
        start_tc = timeline.GetStartTimecode()
        curr_tc = timeline.GetCurrentTimecode()
        start_frame = timeline.GetStartFrame()

        sec_start = timecode_to_seconds(start_tc, fps)
        sec_curr = timecode_to_seconds(curr_tc, fps)
        diff_sec = sec_curr - sec_start
        return int(round(start_frame + diff_sec * fps))
    except Exception:
        return None


def find_active_clip(timeline, track_type, track_index, playhead_frame):
    """
    Finds the clip on the specified track located under the playhead,
    or falls back to the first clip on that track.
    """
    items = timeline.GetItemListInTrack(track_type, track_index)
    if not items:
        return None

    if playhead_frame is not None:
        for it in items:
            try:
                if it.GetStart() <= playhead_frame < it.GetEnd():
                    return it
            except Exception:
                continue

    return items[0]


# ==============================================================================
# FUSION NODE & KEYFRAME INJECTION
# ==============================================================================

TARGET_PRESETS = {
    # --- TRANSFORM PRESETS ---
    "Transform: Size (Zoom)": {
        "tool": "Transform",
        "node_id": "AudioEnvelope_Transform",
        "param": "Size",
        "default_min": 1.0,
        "default_max": 1.35,
        "description": "Zoom dinamico proporzionale all'ampiezza audio",
    },
    "Transform: Angle (Rotation)": {
        "tool": "Transform",
        "node_id": "AudioEnvelope_Transform",
        "param": "Angle",
        "default_min": 0.0,
        "default_max": 12.0,
        "description": "Rotazione modulata dal beat audio",
    },
    "Transform: Center X": {
        "tool": "Transform",
        "node_id": "AudioEnvelope_Transform",
        "param": "Center_X",
        "default_min": 0.50,
        "default_max": 0.54,
        "description": "Spostamento orizzontale sull'asse X",
    },
    "Transform: Center Y": {
        "tool": "Transform",
        "node_id": "AudioEnvelope_Transform",
        "param": "Center_Y",
        "default_min": 0.50,
        "default_max": 0.54,
        "description": "Spostamento verticale sull'asse Y",
    },
    "Transform: XSize (Scale Width)": {
        "tool": "Transform",
        "node_id": "AudioEnvelope_Transform",
        "param": "XSize",
        "default_min": 1.0,
        "default_max": 1.30,
        "description": "Deformazione scala orizzontale",
    },
    "Transform: YSize (Scale Height)": {
        "tool": "Transform",
        "node_id": "AudioEnvelope_Transform",
        "param": "YSize",
        "default_min": 1.0,
        "default_max": 1.30,
        "description": "Deformazione scala verticale",
    },
    # --- BRIGHTNESS & CONTRAST PRESETS ---
    "BrightnessContrast: Gain (Flash)": {
        "tool": "BrightnessContrast",
        "node_id": "AudioEnvelope_BC",
        "param": "Gain",
        "default_min": 1.0,
        "default_max": 1.80,
        "description": "Flash di luminosità / gain su picchi audio",
    },
    "BrightnessContrast: Lift": {
        "tool": "BrightnessContrast",
        "node_id": "AudioEnvelope_BC",
        "param": "Lift",
        "default_min": 0.0,
        "default_max": 0.25,
        "description": "Sollevamento ombre e neri",
    },
    "BrightnessContrast: Gamma": {
        "tool": "BrightnessContrast",
        "node_id": "AudioEnvelope_BC",
        "param": "Gamma",
        "default_min": 1.0,
        "default_max": 1.60,
        "description": "Modulazione toni medi (gamma)",
    },
    "BrightnessContrast: Saturation": {
        "tool": "BrightnessContrast",
        "node_id": "AudioEnvelope_BC",
        "param": "Saturation",
        "default_min": 1.0,
        "default_max": 2.20,
        "description": "Saturazione colore sul ritmo sonoro",
    },
    # --- BLUR PRESETS ---
    "Blur: BlurSize (Sfocatura)": {
        "tool": "Blur",
        "node_id": "AudioEnvelope_Blur",
        "param": "BlurSize",
        "default_min": 0.0,
        "default_max": 3.0,
        "description": "Sfocatura dinamica modulata dall'audio",
    },
    "Blur: Blend (Mix Sfocatura)": {
        "tool": "Blur",
        "node_id": "AudioEnvelope_Blur",
        "param": "Blend",
        "default_min": 0.0,
        "default_max": 1.0,
        "description": "Dissolvenza mix sfocatura sui picchi sonori",
    },
    # --- GLOW PRESETS ---
    "Glow: Glow (Bagliore Luminoso)": {
        "tool": "Glow",
        "node_id": "AudioEnvelope_Glow",
        "param": "Glow",
        "default_min": 0.0,
        "default_max": 0.85,
        "description": "Bagliore luminoso pulsante a ritmo di musica",
    },
    "Glow: GlowSize (Raggio Bagliore)": {
        "tool": "Glow",
        "node_id": "AudioEnvelope_Glow",
        "param": "GlowSize",
        "default_min": 5.0,
        "default_max": 25.0,
        "description": "Dimensione ed espansione del raggio di bagliore",
    },
    # --- CAMERA SHAKE PRESETS ---
    "CameraShake: Overall Strength (Scuotimento)": {
        "tool": "CameraShake",
        "node_id": "AudioEnvelope_Shake",
        "param": "OverallStrength",
        "default_min": 0.0,
        "default_max": 1.0,
        "description": "Vibrazione/terremoto camera sui colpi di basso",
    },
    "CameraShake: Speed (Velocità Shake)": {
        "tool": "CameraShake",
        "node_id": "AudioEnvelope_Shake",
        "param": "Speed",
        "default_min": 1.0,
        "default_max": 4.0,
        "description": "Velocità di oscillazione della vibrazione camera",
    },
    "CameraShake: XShake (Vibrazione Orizzontale)": {
        "tool": "CameraShake",
        "node_id": "AudioEnvelope_Shake",
        "param": "XShake",
        "default_min": 0.0,
        "default_max": 0.50,
        "description": "Ampiezza vibrazione asse X",
    },
    "CameraShake: YShake (Vibrazione Verticale)": {
        "tool": "CameraShake",
        "node_id": "AudioEnvelope_Shake",
        "param": "YShake",
        "default_min": 0.0,
        "default_max": 0.50,
        "description": "Ampiezza vibrazione asse Y",
    },
}

# Alias for backwards compatibility
TARGET_PRESETS["BrightnessContrast: Gain"] = TARGET_PRESETS["BrightnessContrast: Gain (Flash)"]

# Non-effect Fusion node types to exclude from effect selector
IGNORED_FUSION_TOOLS = {
    "MediaIn", "MediaOut", "BezierSpline", "XYPath", "Polyline",
    "LookUpTable", "PipeRouter", "Underlay", "Note", "TimeSpeed",
    "AudioDisplay",
}


def get_clip_effect_tools(comp):
    """
    Returns a dict mapping display_name -> tool_info dict for all effect tools
    present in the clip's Fusion composition:
    {
        "Blur1 [Blur]": {"name": "Blur1", "reg_id": "Blur", "tool": ToolObject, "comp": comp, "display_name": "Blur1 [Blur]"},
        "ComicBook [Fusion Effect]": {"name": "ComicBook", "reg_id": "GroupOperator", "tool": ToolObject, "comp": comp, "display_name": "ComicBook [Fusion Effect]"},
        ...
    }
    """
    if not comp:
        return {}

    all_tools = {}
    try:
        raw_tools = comp.GetToolList(False)
        if isinstance(raw_tools, dict):
            all_tools = raw_tools
        elif isinstance(raw_tools, (list, tuple)):
            all_tools = {i: t for i, t in enumerate(raw_tools)}
    except Exception:
        return {}

    result = {}
    for tool in all_tools.values():
        if not tool:
            continue
        try:
            name = tool.GetAttrs("TOOLS_Name") or ""
            reg_id = tool.GetAttrs("TOOLS_RegID") or ""
            parent = tool.GetAttrs("TOOLH_GroupParent")
        except Exception:
            continue

        if not name:
            continue

        # Filter out internal subtools of a Group/Macro so user only sees the top-level macro/effect
        if parent is not None:
            continue

        # Filter out system and utility nodes
        if reg_id in IGNORED_FUSION_TOOLS:
            continue
        if name.startswith("MediaIn") or name.startswith("MediaOut"):
            continue

        if reg_id == "GroupOperator":
            label = f"{name} [Fusion Effect]"
        elif reg_id:
            label = f"{name} [{reg_id}]"
        else:
            label = name

        result[label] = {
            "name": name,
            "reg_id": reg_id,
            "tool": tool,
            "comp": comp,
            "display_name": label,
        }

    return result


def get_tool_animatable_inputs(tool):
    """
    Scans a Fusion tool's inputs and returns a list of dicts describing animatable
    Number or Point inputs:
    [
        {
            "id": "BlurSize",
            "name": "Blur Size",
            "display_name": "Blur Size [BlurSize]",
            "data_type": "Number",
            "is_point": False,
            "point_axis": None,
            "base_id": "BlurSize",
            "tool_name": "Blur1",
            "tool": tool,
            "min_scale": 0.0,
            "max_scale": 10.0,
            "default_val": 0.0,
        },
        ...
    ]
    """
    if not tool:
        return []

    try:
        raw_inputs = tool.GetInputList()
    except Exception:
        return []

    inputs_dict = {}
    if isinstance(raw_inputs, dict):
        inputs_dict = raw_inputs
    elif isinstance(raw_inputs, (list, tuple)):
        inputs_dict = {i: inp for i, inp in enumerate(raw_inputs)}

    try:
        tool_name = tool.GetAttrs("TOOLS_Name") or "Tool"
    except Exception:
        tool_name = "Tool"

    animatable = []
    seen_ids = set()

    for inp in inputs_dict.values():
        if not inp:
            continue
        try:
            inp_id = inp.GetAttrs("INPS_ID") or ""
            inp_name = inp.GetAttrs("INPS_Name") or inp_id
            data_type = inp.GetAttrs("INPS_DataType") or ""
            is_passive = bool(inp.GetAttrs("INPB_Passive"))
        except Exception:
            continue

        if not inp_id or is_passive:
            continue

        # Skip internal inputs
        if inp_id.startswith("_") or inp_id in ("ProcessMode", "Nest", "ProcessRange", "ProcessFlags", "Quality"):
            continue

        if inp_id in seen_ids:
            continue
        seen_ids.add(inp_id)

        min_scale = None
        max_scale = None
        default_val = None
        try:
            min_scale = inp.GetAttrs("INPN_MinScale")
            max_scale = inp.GetAttrs("INPN_MaxScale")
            default_val = inp.GetAttrs("INPN_Default")
        except Exception:
            pass

        if data_type == "Number":
            disp = f"{inp_name} [{inp_id}]" if inp_name != inp_id else inp_name
            animatable.append({
                "id": inp_id,
                "name": inp_name,
                "display_name": disp,
                "data_type": "Number",
                "is_point": False,
                "point_axis": None,
                "base_id": inp_id,
                "tool_name": tool_name,
                "tool": tool,
                "min_scale": min_scale,
                "max_scale": max_scale,
                "default_val": default_val,
            })
        elif data_type == "Point":
            disp_x = f"{inp_name} - Asse X [{inp_id}.X]"
            animatable.append({
                "id": f"{inp_id}_X",
                "name": f"{inp_name} (X)",
                "display_name": disp_x,
                "data_type": "Point",
                "is_point": True,
                "point_axis": "X",
                "base_id": inp_id,
                "tool_name": tool_name,
                "tool": tool,
                "min_scale": min_scale,
                "max_scale": max_scale,
                "default_val": default_val,
            })
            disp_y = f"{inp_name} - Asse Y [{inp_id}.Y]"
            animatable.append({
                "id": f"{inp_id}_Y",
                "name": f"{inp_name} (Y)",
                "display_name": disp_y,
                "data_type": "Point",
                "is_point": True,
                "point_axis": "Y",
                "base_id": inp_id,
                "tool_name": tool_name,
                "tool": tool,
                "min_scale": min_scale,
                "max_scale": max_scale,
                "default_val": default_val,
            })

    return animatable


def compute_default_range_for_input(inp_info):
    """
    Computes intelligent default Min and Max values based on the input's current
    value and UI scale limits.
    """
    if not inp_info:
        return 0.0, 1.0

    tool = inp_info.get("tool")
    base_id = inp_info.get("base_id", inp_info.get("id"))
    is_point = inp_info.get("is_point", False)
    point_axis = inp_info.get("point_axis")
    min_scale = inp_info.get("min_scale")
    max_scale = inp_info.get("max_scale")

    curr_val = None
    if tool:
        try:
            curr_val = tool.GetInput(base_id)
        except Exception:
            pass

    if is_point:
        val = 0.5
        if isinstance(curr_val, (list, tuple)) and len(curr_val) >= 2:
            val = float(curr_val[0] if point_axis == "X" else curr_val[1])
        elif isinstance(curr_val, dict):
            val = float(curr_val.get(1 if point_axis == "X" else 2, 0.5))
        return round(val, 3), round(val + 0.05, 3)

    if isinstance(curr_val, (int, float)):
        num = float(curr_val)
        if abs(num) > 0.0001:
            min_v = round(num, 3)
            max_v = round(num * 1.5 if num > 0 else num * 0.5, 3)
            if max_scale is not None and max_v > float(max_scale):
                max_v = round(float(max_scale), 3)
            return min_v, max_v
        else:
            if max_scale is not None and float(max_scale) > 0:
                return 0.0, round(float(max_scale) * 0.5, 3)
            return 0.0, 1.0

    if min_scale is not None and max_scale is not None:
        try:
            return round(float(min_scale), 3), round(float(max_scale), 3)
        except Exception:
            pass

    return 0.0, 1.0


def inject_keyframes_to_fusion_comp(video_item, target, frame_values, start_comp_frame=0):
    """
    Injects keyframe animation into the Fusion composition of the video item.

    Handles:
      - Finding or adding a Fusion composition on the TimelineItem.
      - Target can be a preset key string (e.g. 'Transform: Size (Zoom)')
        or a target dict {'mode': 'preset', 'preset_key': ...}
        or a target dict {'mode': 'custom', 'inp_info': ...}
      - For preset mode: creates or reuses the node and splices it into the pipeline.
      - For custom mode: targets the existing node and its parameter on the clip.
      - Dynamic spline connection: connects BezierSpline or XYPath if needed.
      - Batch keyframe injection using comp.Lock() and comp.Unlock() for high performance.
    """
    # Normalize target specification
    if isinstance(target, str):
        target_info = {"mode": "preset", "preset_key": target}
    elif isinstance(target, dict):
        target_info = target
    else:
        raise ValueError("Parametro 'target' non valido. Deve essere una stringa preset o un dizionario.")

    mode = target_info.get("mode", "preset")

    comp = None
    if mode == "custom":
        inp_info = target_info.get("inp_info", {})
        comp = inp_info.get("comp")
        tool_ref = inp_info.get("tool")
        if not comp and tool_ref and hasattr(tool_ref, "Comp"):
            try:
                comp = tool_ref.Comp()
            except Exception:
                pass

    if not comp and video_item:
        comp = video_item.GetFusionCompByIndex(1)
        if not comp:
            comp = video_item.AddFusionComp()

    if not comp:
        raise RuntimeError("Impossibile creare o recuperare la Fusion Composition per la clip video.")

    if mode == "preset":
        preset_key = target_info["preset_key"]
        if preset_key not in TARGET_PRESETS:
            raise KeyError(f"Preset '{preset_key}' non trovato.")
        preset = TARGET_PRESETS[preset_key]
        tool_type = preset["tool"]
        node_name = preset["node_id"]
        param_name = preset["param"]
        is_point_x = (param_name == "Center_X")
        is_point_y = (param_name == "Center_Y")
        is_point = is_point_x or is_point_y
        point_axis = "X" if is_point_x else ("Y" if is_point_y else None)
        base_param = "Center" if is_point else param_name

        # Check if our envelope tool already exists
        tool = comp.FindTool(node_name)
        if not tool:
            tool = comp.AddTool(tool_type)
            if not tool:
                raise RuntimeError(f"Impossibile aggiungere il nodo Fusion '{tool_type}'.")

            try:
                tool.SetAttrs({"TOOLS_Name": node_name})
            except Exception:
                pass

            # Identify MediaIn and MediaOut tools
            media_in = comp.FindTool("MediaIn1")
            media_out = comp.FindTool("MediaOut1")

            if not media_in or not media_out:
                all_tools = comp.GetToolList(False)
                tools_map = all_tools if isinstance(all_tools, dict) else {i: t for i, t in enumerate(all_tools)}
                for t in tools_map.values():
                    try:
                        reg = t.GetAttrs("TOOLS_RegID")
                        if reg == "MediaIn" and not media_in:
                            media_in = t
                        elif reg == "MediaOut" and not media_out:
                            media_out = t
                    except Exception:
                        pass

            # Wire the node cleanly into the comp pipeline
            if media_out:
                upstream = None
                try:
                    upstream = media_out.Input.GetConnectedOutput()
                except Exception:
                    pass

                if not upstream and media_in:
                    upstream = media_in

                if upstream:
                    try:
                        tool.ConnectInput("Input", upstream)
                    except Exception:
                        pass

                try:
                    media_out.ConnectInput("Input", tool)
                except Exception:
                    pass

    elif mode == "custom":
        inp_info = target_info["inp_info"]
        node_name = inp_info["tool_name"]
        tool = inp_info.get("tool")
        if not tool:
            tool = comp.FindTool(node_name)
        if not tool:
            # Fallback search by TOOLS_Name attribute
            all_tools = comp.GetToolList(False)
            tools_map = all_tools if isinstance(all_tools, dict) else {i: t for i, t in enumerate(all_tools)}
            for t in tools_map.values():
                try:
                    if t.GetAttrs("TOOLS_Name") == node_name:
                        tool = t
                        break
                except Exception:
                    pass

        if not tool:
            raise RuntimeError(f"Nodo effetto '{node_name}' non trovato nella composizione Fusion della clip.")

        param_name = inp_info["id"]
        base_param = inp_info.get("base_id", param_name)
        is_point = inp_info.get("is_point", False)
        point_axis = inp_info.get("point_axis")
        is_point_x = (point_axis == "X")
        is_point_y = (point_axis == "Y")
    else:
        raise ValueError(f"Modalità target sconosciuta: '{mode}'")

    # Connect Spline / Modifiers if not already connected
    if is_point:
        try:
            inputs = tool.GetInputList()
            inp_map = inputs if isinstance(inputs, dict) else {i: inp for i, inp in enumerate(inputs)}
            point_connected = False
            for inp in inp_map.values():
                try:
                    if inp.GetAttrs("INPS_ID") == base_param:
                        point_connected = bool(inp.GetConnectedOutput())
                        break
                except Exception:
                    pass

            if not point_connected:
                xypath = comp.XYPath()
                tool.ConnectInput(base_param, xypath)
                if point_axis == "X":
                    xypath.ConnectInput("X", comp.BezierSpline())
                else:
                    xypath.ConnectInput("Y", comp.BezierSpline())
            else:
                try:
                    conn = tool.GetInput(base_param)
                    if hasattr(conn, "ConnectInput"):
                        conn.ConnectInput(point_axis, comp.BezierSpline())
                except Exception:
                    pass
        except Exception:
            pass
    else:
        try:
            inputs = tool.GetInputList()
            inp_map = inputs if isinstance(inputs, dict) else {i: inp for i, inp in enumerate(inputs)}
            is_connected = False
            for inp in inp_map.values():
                try:
                    if inp.GetAttrs("INPS_ID") == base_param:
                        is_connected = bool(inp.GetConnectedOutput())
                        break
                except Exception:
                    pass

            if not is_connected:
                spline = comp.BezierSpline()
                tool.ConnectInput(base_param, spline)
        except Exception:
            pass

    # Batch Keyframe Injection with comp.Lock() / comp.Unlock()
    comp.Lock()
    try:
        for idx, val in enumerate(frame_values):
            target_frame = float(start_comp_frame + idx)

            if is_point:
                curr = None
                try:
                    curr = tool.GetInput(base_param, target_frame)
                except Exception:
                    pass

                curr_x, curr_y = 0.5, 0.5
                if isinstance(curr, dict):
                    curr_x = curr.get(1, 0.5)
                    curr_y = curr.get(2, 0.5)
                elif isinstance(curr, (list, tuple)) and len(curr) >= 2:
                    curr_x, curr_y = curr[0], curr[1]

                if point_axis == "X":
                    tool.SetInput(base_param, [float(val), float(curr_y)], target_frame)
                elif point_axis == "Y":
                    tool.SetInput(base_param, [float(curr_x), float(val)], target_frame)

            else:
                tool.SetInput(base_param, float(val), target_frame)
    finally:
        comp.Unlock()

    return node_name, len(frame_values)


# ==============================================================================
# USER INTERFACE (UIManager & UIDispatcher)
# ==============================================================================

class AudioEnvelopeApp:
    WINDOW_ID = "com.davinci.audio_envelope_to_video"

    def __init__(self, resolve, fusion=None, bmd_mod=None):
        self.resolve = resolve

        # Resolve Fusion object safely across all environments
        if fusion is not None:
            self.fusion = fusion
        elif "fusion" in globals() and globals()["fusion"] is not None:
            self.fusion = globals()["fusion"]
        elif hasattr(resolve, "Fusion") and callable(resolve.Fusion):
            self.fusion = resolve.Fusion()
        else:
            bmd_temp = bmd_mod or get_bmd()
            self.fusion = bmd_temp.scriptapp("Fusion") if bmd_temp else None

        if not self.fusion:
            raise RuntimeError("Impossibile connettersi all'istanza di Fusion in DaVinci Resolve.")

        self.bmd = bmd_mod or get_bmd()
        self.ui = self.fusion.UIManager
        self.dispatcher = self.bmd.UIDispatcher(self.ui)

        self.project = None
        self.timeline = None
        self.fps = 24.0

        self.v_track_names = []
        self.a_track_names = []

        self.active_video_item = None
        self.active_audio_item = None
        self.audio_file_path = None

        self.current_clip_tools = {}
        self.current_tool_inputs = {}

        self.win = None

    def refresh_project_data(self):
        """Refreshes active project and timeline information."""
        pm = self.resolve.GetProjectManager()
        self.project = pm.GetCurrentProject()
        if not self.project:
            return False, "Nessun progetto aperto in DaVinci Resolve."

        self.timeline = self.project.GetCurrentTimeline()
        if not self.timeline:
            return False, "Nessuna timeline attiva. Apri una timeline nella Edit Page."

        raw_fps = self.timeline.GetSetting("timelineFrameRate")
        try:
            self.fps = float(raw_fps) if raw_fps else 24.0
        except Exception:
            self.fps = 24.0

        v_count = self.timeline.GetTrackCount("video")
        a_count = self.timeline.GetTrackCount("audio")

        self.v_track_names = [f"V{i}: {self.timeline.GetTrackName('video', i) or f'Video {i}'}" for i in range(1, v_count + 1)]
        self.a_track_names = [f"A{i}: {self.timeline.GetTrackName('audio', i) or f'Audio {i}'}" for i in range(1, a_count + 1)]

        return True, "OK"

    def build_ui(self):
        """Constructs the native dark-themed UIManager window layout."""
        # Fonts
        title_font = self.ui.Font({"Family": "Helvetica", "PointSize": 13, "Bold": True})
        section_font = self.ui.Font({"Family": "Helvetica", "PointSize": 10, "Bold": True})
        body_font = self.ui.Font({"Family": "Helvetica", "PointSize": 9})
        mono_font = self.ui.Font({"Family": "Menlo", "PointSize": 9})

        # Header Info Group
        proj_name = self.project.GetName() if self.project else "Sconosciuto"
        tl_name = self.timeline.GetName() if self.timeline else "Nessuna"
        fps_str = f"{self.fps:.3f}".rstrip("0").rstrip(".")

        header_group = self.ui.VGroup({"Weight": 0, "Spacing": 3}, [
            self.ui.Label({
                "Text": "<b>Audio Envelope to Video Keyframes</b>",
                "Font": title_font,
                "Alignment": {"AlignHCenter": True},
            }),
            self.ui.Label({
                "Text": f"<font color='#888888'>Progetto:</font> <b>{proj_name}</b> | <font color='#888888'>Timeline:</font> <b>{tl_name}</b> ({fps_str} fps)",
                "Font": body_font,
                "Alignment": {"AlignHCenter": True},
            }),
        ])

        # Track Selectors Group
        track_group = self.ui.VGroup({"Weight": 0, "Spacing": 4}, [
            self.ui.Label({"Text": "<b>1. SELEZIONE TRACCE & SORGENTI</b>", "Font": section_font}),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Traccia Audio:", "Weight": 0.3, "Font": body_font}),
                self.ui.ComboBox({"ID": "AudioTrackCombo", "Weight": 0.7, "Events": {"CurrentIndexChanged": True}}),
            ]),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Traccia Video:", "Weight": 0.3, "Font": body_font}),
                self.ui.ComboBox({"ID": "VideoTrackCombo", "Weight": 0.7, "Events": {"CurrentIndexChanged": True}}),
            ]),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Button({"ID": "RefreshClipsBtn", "Text": "Rileva Clip su Playhead", "Weight": 1.0}),
            ]),
            self.ui.Label({
                "ID": "ClipInfoLabel",
                "Text": "<font color='#aaaaaa'>Clip Audio:</font> -<br><font color='#aaaaaa'>Clip Video:</font> -",
                "Font": mono_font,
                "WordWrap": True,
            }),
        ])

        # Target Property & Effect Group
        first_preset_key = list(TARGET_PRESETS.keys())[0]
        first_preset = TARGET_PRESETS[first_preset_key]

        target_group = self.ui.VGroup({"Weight": 0, "Spacing": 4}, [
            self.ui.Label({"Text": "<b>2. PARAMETRO TARGET VIDEO & EFFETTI</b>", "Font": section_font}),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Modalità Target:", "Weight": 0.3, "Font": body_font}),
                self.ui.ComboBox({"ID": "TargetModeCombo", "Weight": 0.7, "Events": {"CurrentIndexChanged": True}}),
            ]),
            self.ui.HGroup({"ID": "PresetRow", "Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Preset Rapido:", "Weight": 0.3, "Font": body_font}),
                self.ui.ComboBox({"ID": "TargetPropCombo", "Weight": 0.7, "Events": {"CurrentIndexChanged": True}}),
            ]),
            self.ui.HGroup({"ID": "EffectNodeRow", "Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Effetto / Nodo:", "Weight": 0.3, "Font": body_font}),
                self.ui.ComboBox({"ID": "EffectNodeCombo", "Weight": 0.48, "Events": {"CurrentIndexChanged": True}}),
                self.ui.Button({"ID": "RescanEffectsBtn", "Text": "↻ Rileva", "Weight": 0.22}),
            ]),
            self.ui.HGroup({"ID": "EffectParamRow", "Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Parametro Effetto:", "Weight": 0.3, "Font": body_font}),
                self.ui.ComboBox({"ID": "EffectParamCombo", "Weight": 0.7, "Events": {"CurrentIndexChanged": True}}),
            ]),
            self.ui.Label({
                "ID": "PropDescLabel",
                "Text": f"<i>{first_preset['description']}</i>",
                "Font": body_font,
                "WordWrap": True,
            }),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Valore Min (Silenzio):", "Weight": 0.35, "Font": body_font}),
                self.ui.LineEdit({"ID": "MinValueEdit", "Text": str(first_preset["default_min"]), "Weight": 0.25}),
                self.ui.Label({"Text": "Valore Max (Picco):", "Weight": 0.35, "Font": body_font}),
                self.ui.LineEdit({"ID": "MaxValueEdit", "Text": str(first_preset["default_max"]), "Weight": 0.25}),
            ]),
        ])

        # Frequency Filter / FFT Group
        freq_presets_list = list(FREQUENCY_PRESETS.keys())
        first_freq_key = freq_presets_list[0]
        first_min_hz, first_max_hz = FREQUENCY_PRESETS[first_freq_key]

        freq_group = self.ui.VGroup({"Weight": 0, "Spacing": 4}, [
            self.ui.Label({"Text": "<b>3. ANALISI FFT & FILTRO FREQUENZA</b>", "Font": section_font}),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Banda Audio:", "Weight": 0.3, "Font": body_font}),
                self.ui.ComboBox({"ID": "FreqBandCombo", "Weight": 0.7, "Events": {"CurrentIndexChanged": True}}),
            ]),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Freq Min (Hz):", "Weight": 0.25, "Font": body_font}),
                self.ui.LineEdit({"ID": "MinFreqEdit", "Text": str(int(first_min_hz)), "Weight": 0.25}),
                self.ui.Label({"Text": "Freq Max (Hz):", "Weight": 0.25, "Font": body_font}),
                self.ui.LineEdit({"ID": "MaxFreqEdit", "Text": str(int(first_max_hz)), "Weight": 0.25}),
            ]),
            self.ui.Label({
                "ID": "FreqDescLabel",
                "Text": "<font color='#888888'>Analisi spettrale completa attiva (20 Hz - 20 kHz).</font>",
                "Font": body_font,
            }),
        ])

        # DSP & Envelope Tuning Group
        dsp_group = self.ui.VGroup({"Weight": 0, "Spacing": 4}, [
            self.ui.Label({"Text": "<b>4. DSP & TARATURA INVILUPPO</b>", "Font": section_font}),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Smoothing (Frame Moving Average):", "Weight": 0.7, "Font": body_font}),
                self.ui.SpinBox({"ID": "SmoothSpin", "Minimum": 1, "Maximum": 30, "Value": 3, "Weight": 0.3}),
            ]),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Attack (Reattività):", "Weight": 0.35, "Font": body_font}),
                self.ui.Slider({
                    "ID": "AttackSlider",
                    "Minimum": 0,
                    "Maximum": 100,
                    "Value": 10,
                    "Weight": 0.5,
                    "Events": {"ValueChanged": True, "SliderMoved": True},
                }),
                self.ui.Label({"ID": "AttackValLabel", "Text": "0.10", "Weight": 0.15, "Font": mono_font}),
            ]),
            self.ui.HGroup({"Weight": 0, "Spacing": 6}, [
                self.ui.Label({"Text": "Release (Decadimento):", "Weight": 0.35, "Font": body_font}),
                self.ui.Slider({
                    "ID": "ReleaseSlider",
                    "Minimum": 0,
                    "Maximum": 100,
                    "Value": 60,
                    "Weight": 0.5,
                    "Events": {"ValueChanged": True, "SliderMoved": True},
                }),
                self.ui.Label({"ID": "ReleaseValLabel", "Text": "0.60", "Weight": 0.15, "Font": mono_font}),
            ]),
        ])

        # Execution & Status Group
        exec_group = self.ui.VGroup({"Weight": 0, "Spacing": 6}, [
            self.ui.Button({
                "ID": "ExecuteBtn",
                "Text": "⚡ ESTRAI AUDIO & GENERA AUTOMAZIONE ⚡",
                "Font": section_font,
                "Weight": 0,
            }),
            self.ui.Label({
                "ID": "StatusLabel",
                "Text": "Stato: Pronto. Seleziona le tracce e clicca su Estrai.",
                "Font": body_font,
                "WordWrap": True,
            }),
        ])

        # Main Layout Assembly
        main_layout = self.ui.VGroup({"Spacing": 10, "Margin": 12}, [
            header_group,
            self.ui.VGap(2),
            track_group,
            self.ui.VGap(2),
            target_group,
            self.ui.VGap(2),
            freq_group,
            self.ui.VGap(2),
            dsp_group,
            self.ui.VGap(4),
            exec_group,
        ])

        window_config = {
            "ID": self.WINDOW_ID,
            "WindowTitle": "DaVinci Resolve - Audio Envelope to Video Keyframes",
            "Geometry": [350, 60, 560, 780],
        }

        self.win = self.dispatcher.AddWindow(window_config, main_layout)
        self.connect_events()
        self.populate_dropdowns()
        self.on_refresh_clips_clicked(None)

    def populate_dropdowns(self):
        """Populates ComboBoxes with tracks, presets, modes, and frequency bands."""
        items = self.win.GetItems()

        a_combo = items["AudioTrackCombo"]
        a_combo.Clear()
        for t in self.a_track_names:
            a_combo.AddItem(t)

        v_combo = items["VideoTrackCombo"]
        v_combo.Clear()
        for t in self.v_track_names:
            v_combo.AddItem(t)

        m_combo = items["TargetModeCombo"]
        m_combo.Clear()
        m_combo.AddItem("🎯 Preset Rapidi (Auto-crea nodo se assente)")
        m_combo.AddItem("✨ Effetti sulla Clip (Nodi Fusion & OpenFX esistenti)")

        p_combo = items["TargetPropCombo"]
        p_combo.Clear()
        seen_keys = set()
        for p in TARGET_PRESETS.keys():
            if p not in seen_keys:
                p_combo.AddItem(p)
                seen_keys.add(p)

        f_combo = items["FreqBandCombo"]
        f_combo.Clear()
        for f_name in FREQUENCY_PRESETS.keys():
            f_combo.AddItem(f_name)

        self.update_target_mode_ui()

    def connect_events(self):
        """Binds UI interaction event handlers."""
        # Close Window
        self.win.On[self.WINDOW_ID].Close = self.on_close

        # Buttons
        self.win.On["RefreshClipsBtn"].Clicked = self.on_refresh_clips_clicked
        self.win.On["RescanEffectsBtn"].Clicked = self.on_rescan_effects_clicked
        self.win.On["ExecuteBtn"].Clicked = self.on_execute_clicked

        # Track Combos
        self.win.On["AudioTrackCombo"].CurrentIndexChanged = self.on_track_selection_changed
        self.win.On["VideoTrackCombo"].CurrentIndexChanged = self.on_track_selection_changed

        # Target Mode & Property Combos
        self.win.On["TargetModeCombo"].CurrentIndexChanged = self.on_target_mode_changed
        self.win.On["TargetPropCombo"].CurrentIndexChanged = self.on_target_property_changed
        self.win.On["EffectNodeCombo"].CurrentIndexChanged = self.on_effect_node_changed
        self.win.On["EffectParamCombo"].CurrentIndexChanged = self.on_effect_param_changed

        # Frequency Band Combo
        self.win.On["FreqBandCombo"].CurrentIndexChanged = self.on_freq_band_changed

        # Sliders
        self.win.On["AttackSlider"].ValueChanged = self.on_attack_changed
        self.win.On["AttackSlider"].SliderMoved = self.on_attack_changed
        self.win.On["ReleaseSlider"].ValueChanged = self.on_release_changed
        self.win.On["ReleaseSlider"].SliderMoved = self.on_release_changed

    # --- Event Handlers ---

    def on_close(self, ev):
        self.dispatcher.ExitLoop()

    def update_target_mode_ui(self):
        """Toggles widget states depending on whether presets or clip effects are active."""
        items = self.win.GetItems()
        is_preset = (items["TargetModeCombo"].CurrentIndex == 0)

        try:
            items["TargetPropCombo"].Enabled = is_preset
        except Exception:
            pass
        try:
            items["EffectNodeCombo"].Enabled = not is_preset
            items["RescanEffectsBtn"].Enabled = not is_preset
            items["EffectParamCombo"].Enabled = not is_preset
        except Exception:
            pass

        if is_preset:
            self.on_target_property_changed(None)
        else:
            self.refresh_clip_effects()

    def on_target_mode_changed(self, ev):
        self.update_target_mode_ui()

    def on_rescan_effects_clicked(self, ev):
        self.refresh_clip_effects()

    def refresh_clip_effects(self):
        """Scans all relevant Fusion compositions for effect nodes on the active clip."""
        items = self.win.GetItems()
        node_combo = items["EffectNodeCombo"]
        param_combo = items["EffectParamCombo"]
        node_combo.Clear()
        param_combo.Clear()
        self.current_clip_tools = {}
        self.current_tool_inputs = {}

        if not self.active_video_item:
            node_combo.AddItem("(Seleziona prima una clip video)")
            items["PropDescLabel"].Text = "<font color='#aaaaaa'>Nessuna clip video attiva selezionata sulla timeline.</font>"
            return

        clip_dur = 0
        try:
            clip_dur = int(self.active_video_item.GetDuration())
        except Exception:
            clip_dur = 0

        # Collect candidate compositions
        candidate_comps = []
        seen_comps = set()

        # 1. Compositions explicitly on the TimelineItem
        try:
            comp_count = self.active_video_item.GetFusionCompCount()
            for i in range(1, comp_count + 1):
                c = self.active_video_item.GetFusionCompByIndex(i)
                if c:
                    candidate_comps.append(c)
        except Exception:
            pass

        # 2. Currently open composition in Fusion
        if self.fusion:
            try:
                curr_c = self.fusion.GetCurrentComp()
                if curr_c:
                    candidate_comps.append(curr_c)
            except Exception:
                pass

        # 3. Compositions in fusion.GetCompList() (e.g. Fusion Effects / Templates applied in Edit Page)
        if self.fusion:
            try:
                complist = self.fusion.GetCompList()
                if isinstance(complist, dict):
                    comp_items = list(complist.values())
                elif isinstance(complist, (list, tuple)):
                    comp_items = list(complist)
                else:
                    comp_items = []

                for c in comp_items:
                    if not c:
                        continue
                    c_end = None
                    c_file = ""
                    r_flags = 0
                    try:
                        c_end = c.GetAttrs("COMPN_GlobalEnd")
                        c_file = c.GetAttrs("COMPS_FileName") or ""
                        r_flags = c.GetAttrs("COMPI_RenderFlags") or 0
                    except Exception:
                        pass

                    matches_dur = (c_end is not None and clip_dur > 0 and abs(c_end - (clip_dur - 1)) <= 2)
                    is_template = c_file.endswith(".drfx") or c_file.endswith(".setting")
                    is_active = (r_flags != 0 or bool(c.GetAttrs("COMPB_Modified")))

                    if (matches_dur and (is_template or is_active)) or is_template:
                        candidate_comps.append(c)
            except Exception:
                pass

        # Discover effect tools across all candidate compositions
        tools_dict = {}
        for c in candidate_comps:
            c_ptr = None
            try:
                c_ptr = str(c)
            except Exception:
                c_ptr = id(c)
            if c_ptr in seen_comps:
                continue
            seen_comps.add(c_ptr)

            c_tools = get_clip_effect_tools(c)
            for label, t_info in c_tools.items():
                if label not in tools_dict:
                    tools_dict[label] = t_info

        self.current_clip_tools = tools_dict

        if not tools_dict:
            node_combo.AddItem("(Nessun effetto trovato sulla clip)")
            items["PropDescLabel"].Text = (
                "<font color='#ffaa33'>Nessun effetto rilevato sulla clip. "
                "Aggiungi un effetto (Fusion Effect o OpenFX) dalla Edit Page, poi clicca '↻ Rileva'.</font>"
            )
            return

        for display_name in sorted(tools_dict.keys()):
            node_combo.AddItem(display_name)

        self.on_effect_node_changed(None)

    def on_effect_node_changed(self, ev):
        """Populates the parameter dropdown for the selected effect tool."""
        items = self.win.GetItems()
        node_combo = items["EffectNodeCombo"]
        param_combo = items["EffectParamCombo"]
        param_combo.Clear()
        self.current_tool_inputs = {}

        selected_node_text = node_combo.CurrentText
        tool_info = self.current_clip_tools.get(selected_node_text)
        if not tool_info:
            return

        tool = tool_info["tool"]
        tool_comp = tool_info.get("comp")
        inputs_list = get_tool_animatable_inputs(tool)
        for inp in inputs_list:
            inp["comp"] = tool_comp
        self.current_tool_inputs = {inp["display_name"]: inp for inp in inputs_list}

        if not inputs_list:
            param_combo.AddItem("(Nessun parametro numerico animabile)")
            items["PropDescLabel"].Text = f"<font color='#ffaa33'>Il nodo '{tool_info['name']}' non ha parametri numerici animabili.</font>"
            return

        for inp in inputs_list:
            param_combo.AddItem(inp["display_name"])

        self.on_effect_param_changed(None)

    def on_effect_param_changed(self, ev):
        """Updates min/max values and description for the chosen effect parameter."""
        items = self.win.GetItems()
        param_combo = items["EffectParamCombo"]
        selected_param_text = param_combo.CurrentText
        inp_info = self.current_tool_inputs.get(selected_param_text)
        if not inp_info:
            return

        min_v, max_v = compute_default_range_for_input(inp_info)
        items["MinValueEdit"].Text = str(min_v)
        items["MaxValueEdit"].Text = str(max_v)

        axis_info = f" [Asse {inp_info['point_axis']}]" if inp_info.get("point_axis") else ""
        items["PropDescLabel"].Text = (
            f"<font color='#33bbff'>Nodo: <b>{inp_info['tool_name']}</b> | Parametro: "
            f"<b>{inp_info['name']}{axis_info}</b> (Tipo: {inp_info['data_type']})</font>"
        )

    def on_freq_band_changed(self, ev):
        items = self.win.GetItems()
        selected_text = items["FreqBandCombo"].CurrentText
        preset = FREQUENCY_PRESETS.get(selected_text)
        if preset:
            min_f, max_f = preset
            items["MinFreqEdit"].Text = str(int(min_f) if min_f.is_integer() else min_f)
            items["MaxFreqEdit"].Text = str(int(max_f) if max_f.is_integer() else max_f)
            if min_f <= 25 and max_f >= 19000:
                items["FreqDescLabel"].Text = "<font color='#888888'>Analisi spettrale completa attiva (20 Hz - 20 kHz).</font>"
            else:
                items["FreqDescLabel"].Text = f"<font color='#33bbff'>Filtro passa-banda: {int(min_f)} Hz - {int(max_f)} Hz</font>"

    def on_attack_changed(self, ev):
        items = self.win.GetItems()
        val = items["AttackSlider"].Value / 100.0
        items["AttackValLabel"].Text = f"{val:.2f}"

    def on_release_changed(self, ev):
        items = self.win.GetItems()
        val = items["ReleaseSlider"].Value / 100.0
        items["ReleaseValLabel"].Text = f"{val:.2f}"

    def on_target_property_changed(self, ev):
        items = self.win.GetItems()
        selected_text = items["TargetPropCombo"].CurrentText
        preset = TARGET_PRESETS.get(selected_text)
        if preset:
            items["MinValueEdit"].Text = str(preset["default_min"])
            items["MaxValueEdit"].Text = str(preset["default_max"])
            items["PropDescLabel"].Text = f"<i>{preset['description']}</i>"

    def on_track_selection_changed(self, ev):
        self.on_refresh_clips_clicked(None)

    def on_refresh_clips_clicked(self, ev):
        """Scans tracks and identifies the clips under the playhead or first on track."""
        items = self.win.GetItems()
        a_idx = items["AudioTrackCombo"].CurrentIndex + 1
        v_idx = items["VideoTrackCombo"].CurrentIndex + 1

        if not self.timeline:
            return

        playhead = get_timeline_playhead_frame(self.timeline, self.fps)
        self.active_video_item = find_active_clip(self.timeline, "video", v_idx, playhead)
        self.active_audio_item = find_active_clip(self.timeline, "audio", a_idx, playhead)

        v_desc = "-"
        if self.active_video_item:
            try:
                v_name = self.active_video_item.GetName()
                v_start = self.active_video_item.GetStart()
                v_dur = self.active_video_item.GetDuration()
                v_desc = f"<b>{v_name}</b> (Start: {v_start}, Dur: {v_dur}f)"
            except Exception:
                v_desc = "Clip Video presente"

        a_desc = "-"
        self.audio_file_path = None
        if self.active_audio_item:
            try:
                a_name = self.active_audio_item.GetName()
                a_start = self.active_audio_item.GetStart()
                a_dur = self.active_audio_item.GetDuration()

                # Get file path
                mp_item = self.active_audio_item.GetMediaPoolItem()
                if mp_item:
                    path = mp_item.GetClipProperty("File Path") or mp_item.GetClipProperty("Clip Path")
                    self.audio_file_path = path

                file_ext = os.path.splitext(self.audio_file_path)[1].upper() if self.audio_file_path else "N/D"
                a_desc = f"<b>{a_name}</b> [{file_ext}] (Start: {a_start}, Dur: {a_dur}f)"
            except Exception:
                a_desc = "Clip Audio presente"

        items["ClipInfoLabel"].Text = (
            f"<font color='#aaaaaa'>Clip Audio:</font> {a_desc}<br>"
            f"<font color='#aaaaaa'>Clip Video:</font> {v_desc}"
        )
        items["StatusLabel"].Text = "<font color='#44bb44'>Clip rilevate con successo.</font>"

        # If currently in Effect Node mode, refresh effects from the active video clip
        if items["TargetModeCombo"].CurrentIndex == 1:
            self.refresh_clip_effects()

    def on_execute_clicked(self, ev):
        """Performs DSP extraction and injects keyframes into Fusion."""
        items = self.win.GetItems()

        # Validate clips
        if not self.active_video_item:
            items["StatusLabel"].Text = "<font color='#ff4444'>Errore: Nessuna clip video trovata sulla traccia selezionata.</font>"
            return

        if not self.active_audio_item:
            items["StatusLabel"].Text = "<font color='#ff4444'>Errore: Nessuna clip audio trovata sulla traccia selezionata.</font>"
            return

        if not self.audio_file_path or not os.path.exists(self.audio_file_path):
            # Attempt to re-fetch
            try:
                mp_item = self.active_audio_item.GetMediaPoolItem()
                if mp_item:
                    self.audio_file_path = mp_item.GetClipProperty("File Path") or mp_item.GetClipProperty("Clip Path")
            except Exception:
                pass

        if not self.audio_file_path or not os.path.exists(self.audio_file_path):
            items["StatusLabel"].Text = (
                f"<font color='#ff4444'>Errore: File audio sorgente non trovato su disco. "
                f"Percorso: '{self.audio_file_path}'</font>"
            )
            return

        # Parse numerical parameters
        try:
            min_val = float(items["MinValueEdit"].Text)
            max_val = float(items["MaxValueEdit"].Text)
        except ValueError:
            items["StatusLabel"].Text = "<font color='#ff4444'>Errore: Valori Min e Max devono essere numeri float validi.</font>"
            return

        try:
            min_freq = float(items["MinFreqEdit"].Text)
            max_freq = float(items["MaxFreqEdit"].Text)
            if min_freq < 0 or max_freq <= min_freq:
                raise ValueError()
        except ValueError:
            items["StatusLabel"].Text = "<font color='#ff4444'>Errore: Le frequenze Min e Max devono essere numeri positivi con Max > Min.</font>"
            return

        smooth_window = items["SmoothSpin"].Value
        attack = items["AttackSlider"].Value / 100.0
        release = items["ReleaseSlider"].Value / 100.0

        # Determine target specification (Preset vs Custom Effect)
        is_preset_mode = (items["TargetModeCombo"].CurrentIndex == 0)
        if is_preset_mode:
            target_preset_key = items["TargetPropCombo"].CurrentText
            target_spec = {"mode": "preset", "preset_key": target_preset_key}
            target_display_name = target_preset_key
        else:
            selected_param_text = items["EffectParamCombo"].CurrentText
            inp_info = self.current_tool_inputs.get(selected_param_text)
            if not inp_info:
                items["StatusLabel"].Text = "<font color='#ff4444'>Errore: Seleziona un effetto e un parametro valido sulla clip.</font>"
                return
            target_spec = {"mode": "custom", "inp_info": inp_info}
            target_display_name = f"{inp_info['tool_name']} -> {inp_info['name']}"

        is_full_spectrum = (min_freq <= 25.0 and max_freq >= 19000.0)
        band_str = "Full Spectrum" if is_full_spectrum else f"{int(min_freq)}-{int(max_freq)} Hz"

        if is_full_spectrum:
            items["StatusLabel"].Text = "<font color='#eebb22'>Decodifica audio ed estrazione RMS full-spectrum in corso...</font>"
        else:
            items["StatusLabel"].Text = f"<font color='#eebb22'>Decodifica audio e analisi FFT spettrale ({band_str}) in corso...</font>"

        try:
            # Step 1: Decode Audio
            audio_samples, sample_rate = read_audio_file(self.audio_file_path)

            # Step 2: Time Alignment Calculation
            v_start = int(self.active_video_item.GetStart())
            v_dur = int(self.active_video_item.GetDuration())
            a_start = int(self.active_audio_item.GetStart())
            a_end = int(self.active_audio_item.GetEnd())
            a_left_offset = int(self.active_audio_item.GetLeftOffset())

            # Step 3: Frame-by-frame Extraction (FFT Spectral Band or Full RMS)
            raw_energies = []
            for k in range(v_dur):
                t_frame = v_start + k
                if a_start <= t_frame < a_end:
                    src_audio_frame = a_left_offset + (t_frame - a_start)
                    if is_full_spectrum:
                        s_start = int(round(src_audio_frame * sample_rate / self.fps))
                        s_end = int(round((src_audio_frame + 1) * sample_rate / self.fps))
                        s_len = len(audio_samples)
                        if 0 <= s_start < s_len and s_end > s_start:
                            window = audio_samples[s_start : min(s_end, s_len)]
                            val = math.sqrt(sum(x * x for x in window) / len(window)) if window else 0.0
                        else:
                            val = 0.0
                    else:
                        val = compute_frame_fft_band(
                            audio_samples, sample_rate, src_audio_frame, 1, self.fps, min_freq, max_freq
                        )[0]
                    raw_energies.append(val)
                else:
                    raw_energies.append(0.0)

            # Step 4: DSP Envelope Smoothing & Mapping
            envelope = apply_envelope_follower(raw_energies, attack, release, smooth_window)
            mapped_values = map_envelope_to_range(envelope, min_val, max_val)

            # Step 5: Fusion Keyframe Injection
            comp = None
            if is_preset_mode:
                comp = self.active_video_item.GetFusionCompByIndex(1)
            else:
                comp = inp_info.get("comp")
                if not comp and inp_info.get("tool") and hasattr(inp_info["tool"], "Comp"):
                    try:
                        comp = inp_info["tool"].Comp()
                    except Exception:
                        pass
                if not comp:
                    comp = self.active_video_item.GetFusionCompByIndex(1)

            start_comp_frame = 0
            if comp:
                try:
                    render_start = comp.GetAttrs("COMPN_RenderStart")
                    if render_start is not None:
                        start_comp_frame = int(render_start)
                except Exception:
                    start_comp_frame = 0

            node_name, total_keys = inject_keyframes_to_fusion_comp(
                self.active_video_item, target_spec, mapped_values, start_comp_frame
            )

            items["StatusLabel"].Text = (
                f"<font color='#33dd55'><b>Successo!</b> Generati {total_keys} keyframe sul nodo "
                f"<b>'{node_name}'</b> (Parametro: {target_display_name} | Banda: {band_str}).</font>"
            )

        except Exception as e:
            traceback.print_exc()
            err_msg = str(e).replace("\n", " ")
            items["StatusLabel"].Text = f"<font color='#ff4444'><b>Errore durante l'elaborazione:</b> {err_msg}</font>"

    def show(self):
        """Displays the window and enters the UIDispatcher event loop."""
        if self.win:
            self.win.Show()
            self.dispatcher.RunLoop()
            self.win.Hide()


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================

def main():
    try:
        resolve_app = get_resolve()
        if not resolve_app:
            print("[ERRORE] Impossibile connettersi all'API di DaVinci Resolve.")
            print("Assicurati che DaVinci Resolve sia aperto e che lo script sia eseguito da 'Workspace > Scripts'.")
            return

        fusion_app = None
        if "fusion" in globals() and globals()["fusion"] is not None:
            fusion_app = globals()["fusion"]
        elif hasattr(resolve_app, "Fusion"):
            fusion_app = resolve_app.Fusion()

        bmd_mod = get_bmd()

        app = AudioEnvelopeApp(resolve_app, fusion=fusion_app, bmd_mod=bmd_mod)
        ok, msg = app.refresh_project_data()
        if not ok:
            print(f"[ATTENZIONE] {msg}")

        app.build_ui()
        app.show()
    except Exception as e:
        traceback.print_exc()


if __name__ == "__main__":
    main()
