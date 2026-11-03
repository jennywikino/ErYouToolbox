"""Missing-runtime checks are simulated; they are not clean-Windows acceptance."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
import desktop_app


class RuntimePromptTests(unittest.TestCase):
    def test_missing_webview_registry_returns_false(self):
        with patch('winreg.OpenKey',side_effect=FileNotFoundError('Runtime absent')):
            self.assertFalse(desktop_app.webview2_available())

    def test_missing_webview_reports_official_url_before_userdata(self):
        with patch.object(sys,'argv',['desktop_app']), patch.object(desktop_app,'webview2_available',return_value=False), patch.object(desktop_app,'prepare_data') as data, patch.object(desktop_app,'portable_root') as home, patch('ctypes.windll.user32.MessageBoxW') as dialog:
            self.assertEqual(desktop_app.main(),1)
            data.assert_not_called()
            home.assert_not_called()
            message=dialog.call_args.args[1]
            self.assertIn('WebView2 Runtime',message)
            self.assertIn('https://developer.microsoft.com/microsoft-edge/webview2/',message)
            self.assertEqual(dialog.call_args.args[2],'妙妙二玩箱启动失败')
