from pathlib import Path
import runpy
import unittest


class Migration(unittest.TestCase):
    def test_scoped_proxy_keeps_device_auth_and_preserves_legacy_auth(self):
        root=Path(__file__).resolve().parents[1]
        convert=runpy.run_path(str(root/'deploy/relay/switch-027.py'))['candidate']
        block=lambda name:f'''reverse_proxy {name} 127.0.0.1:18770 {{
            header_up -Authorization
            header_up -Tailscale-User-Login
            flush_interval -1
        }}'''
        old=block('@ar_application')+'\n'+block('@ar_accounts')+'''\nreverse_proxy 127.0.0.1:18081 {
 header_up -Authorization
}
basicauth {
 speed TEST_ONLY
}
'''
        updated=convert(old)
        self.assertEqual(updated.count('header_up X-AR-Client-IP {remote_host}'),2)
        self.assertEqual(updated.count('header_up -Authorization'),1)
        self.assertTrue(updated.endswith(old[old.index('reverse_proxy 127.0.0.1:18081'):]))
        with self.assertRaises(ValueError):convert(updated)
        with self.assertRaises(ValueError):convert('unknown configuration')


if __name__=='__main__':unittest.main()
