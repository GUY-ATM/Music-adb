# -*- coding: utf-8 -*-
"""核心业务测试：配置校正、音量解析与绝对调节、按键消息解析、媒体键通道。"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import adb, config, input_hooks


class ConfigTest(unittest.TestCase):
    def test_invalid_binding_falls_back_to_default(self):
        config.cfg = {"prev_button": "left", "next_button": "bad"}
        config.load_config()
        self.assertEqual(config.cfg["prev_button"], "x1")
        self.assertEqual(config.cfg["next_button"], "x2")

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            old_path = config.CONFIG_PATH
            config.CONFIG_PATH = os.path.join(d, "config.json")
            try:
                config.cfg = dict(config.DEFAULT_CONFIG)
                config.cfg["device"] = "192.168.1.5:5555"
                config.cfg["next_button"] = "middle"
                config.save_config()
                config.cfg = dict(config.DEFAULT_CONFIG)
                config.load_config()
                self.assertEqual(config.cfg["device"], "192.168.1.5:5555")
                self.assertEqual(config.cfg["next_button"], "middle")
            finally:
                config.CONFIG_PATH = old_path


class ConfigIdentityTest(unittest.TestCase):
    """load_config 必须原地更新 cfg，否则各模块持有旧字典导致设置读不到也存不下。"""

    def test_load_updates_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            old_path = config.CONFIG_PATH
            config.CONFIG_PATH = os.path.join(d, "config.json")
            try:
                with open(config.CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump({"theme": "light", "prev_button": "vk:112"}, f)

                ref = config.cfg
                ref["theme"] = "dark"
                config.load_config()

                self.assertIs(config.cfg, ref)
                self.assertEqual(config.cfg["theme"], "light")
                self.assertEqual(config.cfg["prev_button"], "vk:112")

                from app import input_hooks as hooks
                from app.ui import main_window
                self.assertIs(main_window.cfg, config.cfg)
                self.assertIs(hooks.cfg, config.cfg)

                # 界面侧修改后保存，文件内容必须同步变化
                main_window.cfg["theme"] = "light"
                config.save_config()
                with open(config.CONFIG_PATH, encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["theme"], "light")
            finally:
                config.CONFIG_PATH = old_path
                config.cfg = dict(config.DEFAULT_CONFIG)


class VolumeTest(unittest.TestCase):
    def setUp(self):
        self.state = {"v": 70, "max": 150}

    def fake_run_adb(self, args, timeout=8):
        if "--get" in args:
            return True, f"[V] volume is {self.state['v']} in range [0..{self.state['max']}]"
        for part in args[-1].split(";"):
            op = part.split()[-1]
            if op == "RAISE":
                self.state["v"] = min(self.state["max"], self.state["v"] + 10)
            elif op == "LOWER":
                self.state["v"] = max(0, self.state["v"] - 10)
        return True, "ok"

    def test_parse(self):
        import re
        m = re.search(r"volume is (\d+) in range \[(\d+)\.\.(\d+)\]",
                      "volume is 70 in range [0..150]")
        self.assertEqual((int(m.group(1)), int(m.group(3))), (70, 150))

    def test_absolute_convergence(self):
        adb.run_adb = self.fake_run_adb
        for target, expect in ((100, 100), (30, 30), (0, 0), (150, 150), (70, 70)):
            ok, msg = adb.set_volume_absolute(target)
            self.assertTrue(ok, msg)
            self.assertEqual(self.state["v"], expect)

    def test_clamp_out_of_range(self):
        adb.run_adb = self.fake_run_adb
        adb.set_volume_absolute(999)
        self.assertEqual(self.state["v"], 150)
        adb.set_volume_absolute(-20)
        self.assertEqual(self.state["v"], 0)


class ChannelTest(unittest.TestCase):
    def test_channels(self):
        calls = []

        def fake(args, timeout=8):
            calls.append(" ".join(args))
            return True, ""

        orig = adb.run_adb
        adb.run_adb = fake
        try:
            adb.send_keyevent("87")
            adb.send_keyevent("24") if "24" in adb.MEDIA_ACTIONS else None
            adb.send_keyevent("164")
        finally:
            adb.run_adb = orig
        self.assertIn("dispatch next", calls[0])
        self.assertIn("adj-volume 3 MUTE", calls[1])


class KeyboardBindingTest(unittest.TestCase):
    def test_make_and_parse(self):
        self.assertEqual(config.make_key_binding(112), "vk:112")
        self.assertEqual(config.make_key_binding(65, config.MOD_CTRL | config.MOD_SHIFT),
                         "vk:65+ctrl+shift")
        self.assertEqual(config.parse_key_binding("vk:65+ctrl+shift"),
                         (65, config.MOD_CTRL | config.MOD_SHIFT))
        self.assertEqual(config.parse_key_binding("vk:65+SHIFT"), (65, config.MOD_SHIFT))

    def test_parse_invalid(self):
        for bad in ("x1", "vk:", "vk:abc", "vk:0", "vk:300", "vk:65+win", ""):
            self.assertIsNone(config.parse_key_binding(bad), bad)

    def test_display(self):
        self.assertEqual(config.binding_display("x1"), "后退键(侧键)")
        self.assertEqual(config.binding_display("vk:112"), "F1")
        self.assertEqual(config.binding_display("vk:65+ctrl"), "Ctrl+A")
        self.assertEqual(config.binding_display("vk:112+ctrl+alt"), "Ctrl+Alt+F1")

    def test_validity(self):
        self.assertTrue(config.is_valid_binding("middle"))
        self.assertTrue(config.is_valid_binding("vk:112"))
        self.assertFalse(config.is_valid_binding("left"))
        self.assertFalse(config.is_valid_binding("vk:bad"))

    def test_load_keeps_keyboard_binding(self):
        with tempfile.TemporaryDirectory() as d:
            old_path = config.CONFIG_PATH
            config.CONFIG_PATH = os.path.join(d, "config.json")
            try:
                with open(config.CONFIG_PATH, "w", encoding="utf-8") as f:
                    f.write('{"prev_button": "vk:113+alt", "next_button": "x2"}')
                config.load_config()
                self.assertEqual(config.cfg["prev_button"], "vk:113+alt")
                self.assertEqual(config.cfg["next_button"], "x2")
            finally:
                config.CONFIG_PATH = old_path
                config.cfg = dict(config.DEFAULT_CONFIG)

    def test_match_key_binding(self):
        old = dict(input_hooks.cfg)
        try:
            input_hooks.cfg["prev_button"] = "vk:113"
            input_hooks.cfg["next_button"] = "vk:112+ctrl"
            self.assertEqual(input_hooks._match_key_binding(113, 0), ("88", "上一曲"))
            self.assertEqual(input_hooks._match_key_binding(112, config.MOD_CTRL),
                             ("87", "下一曲"))
            self.assertIsNone(input_hooks._match_key_binding(112, 0))
            self.assertIsNone(input_hooks._match_key_binding(114, 0))
        finally:
            input_hooks.cfg.clear()
            input_hooks.cfg.update(old)


class MouseMessageTest(unittest.TestCase):
    def _xbutton(self, xbutton):
        import ctypes
        s = input_hooks.MSLLHOOKSTRUCT()
        s.mouseData = xbutton << 16
        return ctypes.cast(ctypes.pointer(s), ctypes.c_void_p).value

    def test_xbutton_messages(self):
        for msg in (input_hooks.WM_XBUTTONDOWN, input_hooks.WM_NCXBUTTONDOWN):
            self.assertEqual(input_hooks._resolve_button(msg, self._xbutton(1)), "x1")
            self.assertEqual(input_hooks._resolve_button(msg, self._xbutton(2)), "x2")

    def test_plain_buttons(self):
        self.assertEqual(
            input_hooks._resolve_button(input_hooks.WM_MBUTTONDOWN, 0), "middle")
        self.assertEqual(
            input_hooks._resolve_button(input_hooks.WM_RBUTTONDOWN, 0), "right")
        self.assertIsNone(input_hooks._resolve_button(0x0200, 0))  # WM_MOUSEMOVE


if __name__ == "__main__":
    unittest.main(verbosity=2)
