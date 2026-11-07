"""No-op compatibility hook for older MU300 package launchers.

Confirmed tasks now prepare Android USB functions through usb_config.py.
Device enumeration never disables Windows device nodes or changes USB modes.
"""


def prepare_devices(devices, notify=None):
    return None
