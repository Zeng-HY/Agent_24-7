from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_identity import Identity,Limited


class IdentityTests(unittest.TestCase):
    def test_verified_email_links_legacy_account_without_replacing_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Identity(Path(temp)/'state.db')
            store.register('legacy','legacy-password',store.grant('invite'))
            session=store.login('legacy','legacy-password');owner=store.owner(session)
            code=store.email_grant('link','owner@example.test',token=session,old='legacy-password')
            store.consume_email(code)
            self.assertEqual(store.user('owner@example.test')['id'],owner)
            self.assertEqual(store.user('legacy')['id'],owner)
            reset=store.grant('reset',owner)
            store.reset_compatible(reset,'updated-password')
            self.assertFalse(store.valid(session))
            self.assertTrue(store.login('owner@example.test','updated-password'))
            with self.assertRaises(ValueError):store.reset_compatible(reset,'updated-again')

    def test_capacity_expiry_and_retry_time(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Identity(Path(temp)/'state.db',account_limit=1,device_limit=1)
            store.register('alice','alice-password',store.grant('invite'))
            with self.assertRaises(ValueError):store.email_grant('signup','new@example.test','another-password')
            session=store.login('alice','alice-password')
            one=store.start_authorization('a'*43,'one');store.approve(session,one)
            two=store.start_authorization('b'*43,'two')
            with self.assertRaises(ValueError):store.approve(session,two)
            with store.connect() as db:db.execute('UPDATE device_authorizations SET expires=0 WHERE id=?',(two,))
            with self.assertRaises(ValueError):store.authorization(two,'b'*43)
            store.rate('sample',1,30)
            with self.assertRaises(Limited) as result:store.rate('sample',1,30)
            self.assertTrue(1<=result.exception.seconds<=31)


if __name__=='__main__':unittest.main()
