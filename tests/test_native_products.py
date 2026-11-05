"""Product matching needs no optional firmware checkout or connected device."""
import sys
import unittest
import tempfile
import hashlib
import json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class NativeProducts(unittest.TestCase):
    def test_f50pro_and_u30pro_are_separate_products_on_same_soc(self):
        from backend.model_compat import mu300_android,mu300_runtime
        for model,expected in [('MU3356','f50pro'),('MU5358','u30pro'),('MU5358E','u30pro')]:
            profile,warning=mu300_android(model,model,'ums9632',expected)
            self.assertEqual(profile,expected)
            self.assertIsNone(warning)
            self.assertIsNone(mu300_runtime(expected,expected))
            other='u30pro' if expected=='f50pro' else 'f50pro'
            self.assertIsNotNone(mu300_android(model,model,'ums9632',other)[1])
            self.assertIsNotNone(mu300_runtime(expected,other))
            self.assertIsNotNone(mu300_android(model,model,'ums9620',expected)[1])
        self.assertIsNotNone(mu300_android('MU3356','MU3356','ums9632','mu300-family')[1])
        self.assertIsNotNone(mu300_android('F50','F50','ums9620','f50pro')[1])

    def test_manifest_product_selects_native_package_and_keeps_checksums(self):
        from backend.package import inspect_package
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            names=['boot-linux.img','mu300-openwrt.tar.gz','busybox',
                   'rootfs-critical.sha256','rootfs.requirements',
                   'desktop/native_u30pro.py','desktop/boot-runtime.py','OpenWrt-Installer.py']
            checks={}
            for name in names:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
                checks[name]=hashlib.sha256(p.read_bytes()).hexdigest()
            data=dict(format=2,kernel='6.12.94',platform='u30pro',product='f50pro',
                      magisk=checks,desktop={})
            path=root/'desktop/manifest.json';path.write_text(json.dumps(data))
            selected=inspect_package(root)
            self.assertEqual((selected['adapter'],selected['profile'],selected['layout']),
                             ('mu300','f50pro','mu300root-container'))
            data['product']='u30pro';path.write_text(json.dumps(data))
            self.assertEqual(inspect_package(root)['profile'],'u30pro')
            data.pop('product');path.write_text(json.dumps(data))
            self.assertEqual(inspect_package(root)['profile'],'u30pro')
            data.update(product='f50pro');data.pop('platform');path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'boot adapter'):inspect_package(root)
            data['platform']='u30pro';path.write_text(json.dumps(data))
            (root/'desktop/native_u30pro.py').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):inspect_package(root)


if __name__=='__main__': unittest.main(verbosity=2)
