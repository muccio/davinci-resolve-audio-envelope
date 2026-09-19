#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_audio_envelope.py
-----------------------
Unit tests for AudioEnvelopeToVideo DSP and logic.
"""

import os
import wave
import struct
import math
import tempfile
import unittest

from AudioEnvelopeToVideo import (
    read_audio_file,
    compute_frame_rms,
    apply_envelope_follower,
    map_envelope_to_range,
    timecode_to_seconds,
    TARGET_PRESETS,
    FREQUENCY_PRESETS,
    PurePythonFFT,
    compute_frame_fft_band,
)

class TestAudioEnvelope(unittest.TestCase):

    def setUp(self):
        # Create a synthetic 1-second 48kHz stereo WAV file with a pulse
        self.temp_dir = tempfile.mkdtemp()
        self.wav_path = os.path.join(self.temp_dir, "test_synth.wav")
        self.sr = 48000
        self.num_frames = self.sr * 1  # 1 second

        with wave.open(self.wav_path, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sr)

            samples = []
            for i in range(self.num_frames):
                # Sine wave with bursting amplitude in the middle
                t = i / float(self.sr)
                amp = 0.8 if 0.4 <= t <= 0.6 else 0.05
                val = int(amp * 32767.0 * math.sin(2.0 * math.pi * 440.0 * t))
                # Stereo pair
                samples.append(struct.pack("<hh", val, val))

            wf.writeframes(b"".join(samples))

    def tearDown(self):
        if os.path.exists(self.wav_path):
            os.remove(self.wav_path)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_audio_read(self):
        data, sr = read_audio_file(self.wav_path)
        self.assertEqual(sr, 48000)
        self.assertEqual(len(data), 48000)
        # Check that center has higher amplitude than start
        center_rms = math.sqrt(sum(x*x for x in data[20000:28000]) / 8000)
        start_rms = math.sqrt(sum(x*x for x in data[0:8000]) / 8000)
        self.assertGreater(center_rms, start_rms)

    def test_dsp_rms_and_envelope(self):
        data, sr = read_audio_file(self.wav_path)
        fps = 24.0
        frame_count = 24  # 1 second of video

        rms_list = compute_frame_rms(data, sr, frame_start_idx=0, frame_count=frame_count, fps=fps)
        self.assertEqual(len(rms_list), 24)

        # Apply envelope follower
        env = apply_envelope_follower(rms_list, attack_val=0.1, release_val=0.6, window_size=3)
        self.assertEqual(len(env), 24)

        # Check peak occurs around frame 10-14 (0.4s - 0.6s)
        max_idx = env.index(max(env))
        self.assertTrue(9 <= max_idx <= 15, f"Peak at frame {max_idx}")

        # Map to Zoom range (1.0 to 1.5)
        mapped = map_envelope_to_range(env, 1.0, 1.5)
        self.assertEqual(len(mapped), 24)
        self.assertAlmostEqual(min(mapped), 1.0, places=2)
        self.assertAlmostEqual(max(mapped), 1.5, places=2)

    def test_timecode_parsing(self):
        self.assertAlmostEqual(timecode_to_seconds("01:00:00:00", 24.0), 3600.0)
        self.assertAlmostEqual(timecode_to_seconds("00:00:01:12", 24.0), 1.5)
        self.assertAlmostEqual(timecode_to_seconds("00:00:00;00", 29.97), 0.0)

    def test_presets_structure(self):
        self.assertIn("Transform: Size (Zoom)", TARGET_PRESETS)
        self.assertIn("BrightnessContrast: Gain", TARGET_PRESETS)
        for k, p in TARGET_PRESETS.items():
            self.assertIn("tool", p)
            self.assertIn("param", p)
            self.assertIn("default_min", p)
            self.assertIn("default_max", p)

    def test_silence_edge_case(self):
        # Array of complete silence
        silent_samples = [0.0] * 48000
        rms_list = compute_frame_rms(silent_samples, 48000, 0, 24, 24.0)
        self.assertEqual(rms_list, [0.0] * 24)
        env = apply_envelope_follower(rms_list, 0.1, 0.6, 3)
        mapped = map_envelope_to_range(env, 1.0, 2.0)
        self.assertEqual(mapped, [1.0] * 24)

    def test_fractional_fps(self):
        # Test fractional framerates: 23.976, 29.97, 59.94
        for fps in (23.976, 29.97, 59.94):
            data, sr = read_audio_file(self.wav_path)
            num_frames = int(round(fps))
            rms_list = compute_frame_rms(data, sr, 0, num_frames, fps)
            self.assertEqual(len(rms_list), num_frames)
            self.assertTrue(all(x >= 0.0 for x in rms_list))

    def test_24bit_wav_reading(self):
        # Create a synthetic 24-bit WAV file
        path_24 = os.path.join(self.temp_dir, "test_24bit.wav")
        try:
            with wave.open(path_24, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(3)  # 24-bit
                wf.setframerate(48000)
                samples_bytes = []
                for i in range(4800):
                    val = int(0.5 * 8388607.0 * math.sin(2.0 * math.pi * 100.0 * (i / 48000.0)))
                    b = val.to_bytes(3, byteorder="little", signed=True)
                    samples_bytes.append(b)
                wf.writeframes(b"".join(samples_bytes))

            data, sr = read_audio_file(path_24)
            self.assertEqual(sr, 48000)
            self.assertEqual(len(data), 4800)
            max_val = max(data)
            self.assertAlmostEqual(max_val, 0.5, places=1)
        finally:
            if os.path.exists(path_24):
                os.remove(path_24)

    def test_fft_engine(self):
        fft = PurePythonFFT(1024)
        # Test 100 Hz pure sine wave at 48000 Hz
        sr = 48000
        samples = [math.sin(2.0 * math.pi * 100.0 * i / sr) for i in range(1024)]
        X = fft.transform(samples)
        # Bin corresponding to 100 Hz: 100 / (48000 / 1024) = 2.13 -> bin 2
        mags = [abs(val) for val in X[:512]]
        peak_bin = mags.index(max(mags))
        self.assertIn(peak_bin, (2, 3), f"Peak should be at bin 2, got {peak_bin}")

    def test_fft_band_isolation(self):
        # Create a signal with 60 Hz bass and 8000 Hz treble
        sr = 48000
        samples = [
            0.8 * math.sin(2.0 * math.pi * 60.0 * i / sr) +
            0.1 * math.sin(2.0 * math.pi * 8000.0 * i / sr)
            for i in range(48000)
        ]
        # Low band (20 - 150 Hz)
        bass_energy = compute_frame_fft_band(samples, sr, 0, 10, 24.0, 20.0, 150.0)
        # High band (5000 - 15000 Hz)
        treble_energy = compute_frame_fft_band(samples, sr, 0, 10, 24.0, 5000.0, 15000.0)

        self.assertEqual(len(bass_energy), 10)
        self.assertEqual(len(treble_energy), 10)
        # Bass energy should be significantly higher than treble energy
        self.assertGreater(max(bass_energy), max(treble_energy) * 3.0)

    def test_frequency_presets(self):
        self.assertIn("Sub-Bass / Cassa (20 - 90 Hz)", FREQUENCY_PRESETS)
        self.assertIn("Treble / Hi-Hat & Piatti (7000 - 18000 Hz)", FREQUENCY_PRESETS)
        for name, (min_f, max_f) in FREQUENCY_PRESETS.items():
            self.assertGreaterEqual(min_f, 0)
            self.assertGreater(max_f, min_f)

if __name__ == "__main__":
    unittest.main()
