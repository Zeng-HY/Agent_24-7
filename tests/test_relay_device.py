import json
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_device import DeviceCredentials, private_directory, request_enrollment


class DeviceTests(unittest.TestCase):
    def test_enrollment_reports_safe_server_reason_without_credentials(self):
        for reason, expected in [('链接或绑定码无效、已使用或已过期', '绑定码无效'),
                                 ('账号不符，未绑定', '绑定码所属账号不符'),
                                 ('sensitive echoed request', '未返回可识别')]:
            opener = Mock()
            opener.open.side_effect = HTTPError('https://relay.example/account/enroll',400,'Bad Request',{},
                io.BytesIO(json.dumps({'error':reason}).encode()))
            with self.assertRaises(ValueError) as caught:
                request_enrollment(opener,'https://relay.example','A'*43,'alice','PC')
            self.assertIn(expected,str(caught.exception))
            self.assertNotIn('A'*43,str(caught.exception))
            self.assertNotIn('sensitive echoed request',str(caught.exception))

    def test_enrollment_trims_clipboard_edges_and_rejects_explanatory_text(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(b'{"id":"test"}')
        result = request_enrollment(opener,'https://relay.example',' \n'+'A'*43+'\r\n','alice','PC')
        self.assertEqual(result,{'id':'test'})
        request = opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data)['code'],'A'*43)
        opener.reset_mock()
        with self.assertRaises(ValueError):
            request_enrollment(opener,'https://relay.example','code: '+'A'*43,'alice','PC')
        opener.open.assert_not_called()

    def test_local_revocation_and_missing_credentials_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'device.json'
            store=DeviceCredentials(path)
            self.assertFalse(store.valid('secret'))
            path.write_text(json.dumps({'gateway_secret':'secret','revoked':False}))
            self.assertTrue(store.valid('secret'))
            self.assertFalse(store.valid('wrong'))
            path.write_text(json.dumps({'gateway_secret':'secret','revoked':True}))
            self.assertFalse(store.valid('secret'))
            path.write_text('{incomplete')
            self.assertFalse(store.valid('secret'))

    @unittest.skipUnless(os.name=='nt','Windows DACL')
    def test_new_credential_directory_has_only_current_user_and_system(self):
        import win32api
        import win32con
        import win32security
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'new-test-device'
            private_directory(folder)
            token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
            try:
                sid=win32security.GetTokenInformation(token,win32security.TokenUser)[0]
            finally:
                token.Close()
            expected={win32security.ConvertSidToStringSid(sid),'S-1-5-18'}
            child=folder/'dummy.txt'
            child.write_text('disposable test data')
            for path in (folder,child):
                sd=win32security.GetNamedSecurityInfo(str(path),win32security.SE_FILE_OBJECT,
                    win32security.DACL_SECURITY_INFORMATION)
                acl=sd.GetSecurityDescriptorDacl()
                actual={win32security.ConvertSidToStringSid(acl.GetAce(i)[2]) for i in range(acl.GetAceCount())}
                self.assertEqual(actual,expected)


if __name__=='__main__':unittest.main()
