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
    get_clip_effect_tools,
    get_tool_animatable_inputs,
    compute_default_range_for_input,
    inject_keyframes_to_fusion_comp,
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

    def test_extended_presets_and_alias(self):
        # Verify expanded presets
        self.assertIn("Blur: BlurSize (Sfocatura)", TARGET_PRESETS)
        self.assertIn("Glow: Glow (Bagliore Luminoso)", TARGET_PRESETS)
        self.assertIn("CameraShake: Overall Strength (Scuotimento)", TARGET_PRESETS)
        # Verify backwards compatibility alias
        self.assertIn("BrightnessContrast: Gain", TARGET_PRESETS)
        self.assertEqual(TARGET_PRESETS["BrightnessContrast: Gain"]["tool"], "BrightnessContrast")

    def test_get_clip_effect_tools(self):
        comp = MockFusionComp()
        comp.tools["MediaIn1"] = MockFusionTool("MediaIn1", "MediaIn")
        comp.tools["MediaOut1"] = MockFusionTool("MediaOut1", "MediaOut")
        comp.tools["Spline1"] = MockFusionTool("Spline1", "BezierSpline")
        comp.tools["Blur1"] = MockFusionTool("Blur1", "Blur")
        comp.tools["OFX_Glow1"] = MockFusionTool("OFX_Glow1", "OpenFX")

        effects = get_clip_effect_tools(comp)
        self.assertEqual(len(effects), 2)
        self.assertIn("Blur1 [Blur]", effects)
        self.assertIn("OFX_Glow1 [OpenFX]", effects)
        self.assertEqual(effects["Blur1 [Blur]"]["name"], "Blur1")

    def test_get_tool_animatable_inputs(self):
        tool = MockFusionTool("TestEffect1", "CustomPlugin")
        tool.inputs = {
            1: MockFusionInput("BlurSize", "Blur Size", "Number", is_passive=False, min_scale=0.0, max_scale=10.0),
            2: MockFusionInput("Center", "Center", "Point", is_passive=False),
            3: MockFusionInput("_HiddenInternal", "Hidden", "Number", is_passive=False),
            4: MockFusionInput("PassiveInput", "Passive Input", "Number", is_passive=True),
            5: MockFusionInput("ProcessMode", "Process Mode", "Number", is_passive=False),
        }

        inputs = get_tool_animatable_inputs(tool)
        input_ids = [inp["id"] for inp in inputs]

        # BlurSize and Point X/Y should be present
        self.assertIn("BlurSize", input_ids)
        self.assertIn("Center_X", input_ids)
        self.assertIn("Center_Y", input_ids)

        # Internal and passive inputs should be filtered out
        self.assertNotIn("_HiddenInternal", input_ids)
        self.assertNotIn("PassiveInput", input_ids)
        self.assertNotIn("ProcessMode", input_ids)

    def test_compute_default_range_for_input(self):
        tool = MockFusionTool("Blur1", "Blur")
        tool.SetInput("BlurSize", 2.0)

        inp_info = {
            "tool": tool,
            "id": "BlurSize",
            "base_id": "BlurSize",
            "is_point": False,
            "min_scale": 0.0,
            "max_scale": 10.0,
        }
        min_v, max_v = compute_default_range_for_input(inp_info)
        self.assertAlmostEqual(min_v, 2.0)
        self.assertAlmostEqual(max_v, 3.0)

        # Point range test
        point_info = {
            "tool": tool,
            "id": "Center_X",
            "base_id": "Center",
            "is_point": True,
            "point_axis": "X",
        }
        min_p, max_p = compute_default_range_for_input(point_info)
        self.assertAlmostEqual(min_p, 0.5)
        self.assertAlmostEqual(max_p, 0.55)

    def test_inject_keyframes_preset_and_custom(self):
        comp = MockFusionComp()
        comp.tools["MediaIn1"] = MockFusionTool("MediaIn1", "MediaIn")
        comp.tools["MediaOut1"] = MockFusionTool("MediaOut1", "MediaOut")
        # Add a custom effect node
        custom_node = MockFusionTool("DirectionalBlur1", "DirectionalBlur")
        custom_node.inputs["BlurSize"] = MockFusionInput("BlurSize", "Blur Size", "Number")
        comp.tools["DirectionalBlur1"] = custom_node

        video_item = MockTimelineItem(comp)

        # 1. Preset Injection
        node_name, count = inject_keyframes_to_fusion_comp(
            video_item, "Blur: BlurSize (Sfocatura)", [0.1, 0.5, 1.2], start_comp_frame=10
        )
        self.assertEqual(node_name, "AudioEnvelope_Blur")
        self.assertEqual(count, 3)
        blur_tool = comp.FindTool("AudioEnvelope_Blur")
        self.assertIsNotNone(blur_tool)
        self.assertEqual(blur_tool.input_values["BlurSize"][10.0], 0.1)
        self.assertEqual(blur_tool.input_values["BlurSize"][11.0], 0.5)
        self.assertEqual(blur_tool.input_values["BlurSize"][12.0], 1.2)

        # 2. Custom Clip Effect Injection
        custom_spec = {
            "mode": "custom",
            "inp_info": {
                "tool_name": "DirectionalBlur1",
                "id": "BlurSize",
                "base_id": "BlurSize",
                "is_point": False,
                "point_axis": None,
            },
        }
        node_name_custom, count_custom = inject_keyframes_to_fusion_comp(
            video_item, custom_spec, [0.2, 0.8], start_comp_frame=0
        )
        self.assertEqual(node_name_custom, "DirectionalBlur1")
        self.assertEqual(count_custom, 2)
        self.assertEqual(custom_node.input_values["BlurSize"][0.0], 0.2)
        self.assertEqual(custom_node.input_values["BlurSize"][1.0], 0.8)

    def test_inject_keyframes_point_coordinate(self):
        comp = MockFusionComp()
        comp.tools["MediaIn1"] = MockFusionTool("MediaIn1", "MediaIn")
        comp.tools["MediaOut1"] = MockFusionTool("MediaOut1", "MediaOut")
        transform_node = MockFusionTool("Transform1", "Transform")
        transform_node.inputs["Center"] = MockFusionInput("Center", "Center", "Point")
        comp.tools["Transform1"] = transform_node

        video_item = MockTimelineItem(comp)

        # Inject into Center (X axis)
        point_spec = {
            "mode": "custom",
            "inp_info": {
                "tool_name": "Transform1",
                "id": "Center_X",
                "base_id": "Center",
                "is_point": True,
                "point_axis": "X",
            },
        }
        node_name, count = inject_keyframes_to_fusion_comp(
            video_item, point_spec, [0.52, 0.58], start_comp_frame=5
        )
        self.assertEqual(node_name, "Transform1")
        self.assertEqual(count, 2)
        self.assertEqual(transform_node.input_values["Center"][5.0], [0.52, 0.5])
        self.assertEqual(transform_node.input_values["Center"][6.0], [0.58, 0.5])



# ==============================================================================
# MOCKS FOR UNIT TESTING
# ==============================================================================

class MockFusionInput:
    def __init__(self, inps_id, name, data_type, is_passive=False, min_scale=None, max_scale=None, default=None):
        self.attrs = {
            "INPS_ID": inps_id,
            "INPS_Name": name,
            "INPS_DataType": data_type,
            "INPB_Passive": is_passive,
            "INPN_MinScale": min_scale,
            "INPN_MaxScale": max_scale,
            "INPN_Default": default,
        }
        self.connected_output = None

    def GetAttrs(self, attr_name=None):
        if attr_name:
            return self.attrs.get(attr_name)
        return self.attrs

    def GetConnectedOutput(self):
        return self.connected_output


class MockFusionTool:
    def __init__(self, name, reg_id):
        self.attrs = {"TOOLS_Name": name, "TOOLS_RegID": reg_id}
        self.inputs = {}
        self.input_values = {}
        self.connected_inputs = {}
        self.Input = MockFusionInput("Input", "Input", "Image")

    def GetAttrs(self, attr_name=None):
        if attr_name:
            return self.attrs.get(attr_name)
        return self.attrs

    def SetAttrs(self, d):
        self.attrs.update(d)

    def GetInputList(self):
        return self.inputs

    def ConnectInput(self, name, target):
        self.connected_inputs[name] = target
        if name in self.inputs:
            self.inputs[name].connected_output = target

    def SetInput(self, name, val, frame=0):
        if name not in self.input_values:
            self.input_values[name] = {}
        self.input_values[name][frame] = val

    def GetInput(self, name, frame=0):
        if name in self.input_values and frame in self.input_values[name]:
            return self.input_values[name][frame]
        return 0.0


class MockFusionComp:
    def __init__(self):
        self.tools = {}
        self.locked = False

    def GetToolList(self, selected=False):
        return {i + 1: t for i, t in enumerate(self.tools.values())}

    def FindTool(self, name):
        for t in self.tools.values():
            if t.GetAttrs("TOOLS_Name") == name:
                return t
        return self.tools.get(name)

    def AddTool(self, tool_type):
        name = f"{tool_type}1"
        tool = MockFusionTool(name, tool_type)
        self.tools[name] = tool
        return tool

    def Lock(self):
        self.locked = True

    def Unlock(self):
        self.locked = False

    def BezierSpline(self):
        return MockFusionTool("Spline", "BezierSpline")

    def XYPath(self):
        return MockFusionTool("XYPath", "XYPath")


class MockTimelineItem:
    def __init__(self, comp):
        self.comp = comp

    def GetFusionCompByIndex(self, idx):
        return self.comp

    def AddFusionComp(self):
        return self.comp


if __name__ == "__main__":
    unittest.main()
