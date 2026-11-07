"""Legacy launchers remain loadable; enumeration never changes Windows PnP."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import windows_mtp
from backend.transport import Adb


class WindowsMtpTest(unittest.TestCase):
    def test_legacy_hook_has_no_side_effects(self):
        notice = Mock()
        with patch('subprocess.run', side_effect=AssertionError('must not run PnP commands')):
            windows_mtp.prepare_devices([{'serial': 'MU123', 'label': 'V50'}], notice)
        notice.assert_not_called()

    def test_listing_only_lists_even_with_legacy_flag(self):
        adb = Adb.__new__(Adb)
        adb.mtp_workaround = True
        for serial in (None, 'MU123', '192.0.2.1:5555'):
            with self.subTest(serial=serial):
                adb.serial = serial
                with patch.object(adb, 'call', return_value='List of devices attached\nMU123 device model:V50\n192.0.2.1:5555 device model:E5\n') as call:
                    self.assertEqual(len(adb.devices()), 2)
                    call.assert_called_once_with('devices', '-l')


if __name__ == '__main__':
    unittest.main()
