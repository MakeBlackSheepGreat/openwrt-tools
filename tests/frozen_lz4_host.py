"""Decode a real ramdisk inside the shipped host backend; never access a device."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def child():
    import ctypes
    import stat
    from backend.native_boot import codec
    if not getattr(sys,'frozen',False):
        raise AssertionError('This check must execute inside the frozen backend')
    boot=codec()
    helper=Path(boot.__file__).with_name('lz4raw-aarch64.so')
    blob=helper.read_bytes()
    if blob[:5]!=b'\x7fELF\x02' or int.from_bytes(blob[18:20],'little')!=183:
        raise AssertionError('The device-only ELF payload must remain packaged')
    previous=ctypes.CDLL
    def forbidden(*args,**kwargs):
        raise AssertionError('Host attempted to load a device ELF')
    ctypes.CDLL=forbidden
    try:
        payload=b'#!/bin/sh\nexec /sbin/init\n'
        ramdisk=boot.overlay({'init':(payload,stat.S_IFREG|0o755)})
        archives=list(boot.archives(ramdisk))
        contents={name:data for name,data,mode in boot.entries(archives[0])}
        if contents.get('init')!=payload:
            raise AssertionError('Frozen host ramdisk decode changed bytes')
        if boot.block_decode(b'\x11a\x01\x00')!=b'aaaaaa':
            raise AssertionError('Frozen host overlapping LZ4 decode failed')
    finally:
        ctypes.CDLL=previous
    print(json.dumps({'ok':True,'frozen':True,'host':sys.platform,'device_elf_loads':0}))


if __name__=='__main__':
    if getattr(sys,'frozen',False):
        child()
    else:
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('backend',type=Path)
        args=parser.parse_args()
        result=subprocess.run([str(args.backend),'--run-tool',str(Path(__file__).resolve())],
                              capture_output=True,text=True,encoding='utf8',timeout=30,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
        print(result.stdout.strip())
