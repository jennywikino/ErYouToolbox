"""Brand assets are supplied files; never regenerate or touch user data."""
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrandingTests(unittest.TestCase):
    def test_supplied_png_and_multisize_ico(self):
        folder=ROOT/'assets/branding'
        self.assertEqual((folder/'MiaomiaoEryouxiang_icon.png').read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
        ico=(folder/'MiaomiaoEryouxiang_icon.ico').read_bytes()
        reserved,kind,count=struct.unpack('<HHH',ico[:6])
        self.assertEqual((reserved,kind),(0,1))
        self.assertGreater(count,0)
        for i in range(count):
            size,offset=struct.unpack('<II',ico[6+i*16+8:6+i*16+16])
            self.assertLessEqual(offset+size,len(ico))

    def test_windows_metadata_and_internal_identity(self):
        metadata=(ROOT/'assets/branding/windows_version.txt').read_text(encoding='utf-8')
        for field in ('FileDescription','ProductName'):
            self.assertIn(f"StringStruct('{field}', '妙妙二玩箱')",metadata)
        self.assertIn("StringStruct('InternalName', 'ErYouToolbox')",metadata)
        self.assertIn("StringStruct('OriginalFilename', '妙妙二玩箱.exe')",metadata)

    def test_no_new_userdata_location(self):
        source=(ROOT/'scripts/desktop_app.py').read_text(encoding='utf-8')
        self.assertIn("Path(home).resolve() / 'userdata'",source)
        self.assertIn("'data/eryoutoolbox.db'",source)
        self.assertIn("instance_lock(home/'.desktop.lock')",source)
