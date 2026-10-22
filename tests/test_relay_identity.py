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


    def test_six_digit_codes_sign_up_and_reset_with_a_few_tries(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Identity(Path(temp)/'state.db')
            code=store.email_grant('signup','new@example.test','new-account-password')
            self.assertRegex(code.pin,r'^[0-9]{6}$')
            wrong='%06d'%((int(code.pin)+1)%10**6)
            with self.assertRaisesRegex(ValueError,'验证码不对'):store.consume_pin('new@example.test','signup',wrong)
            with self.assertRaisesRegex(ValueError,'验证码已失效'):store.consume_pin('new@example.test','reset',code.pin)  # a sign-up code resets nothing
            owner=store.consume_pin(' New@Example.test ','signup',code.pin)
            self.assertEqual(store.user('new@example.test')['id'],owner)
            with self.assertRaisesRegex(ValueError,'验证码已失效'):store.consume_pin('new@example.test','signup',code.pin)  # once
            session=store.login('new@example.test','new-account-password')
            with store.connect() as db:db.execute('DELETE FROM attempts')  # 10 tries an address per 15 minutes; a fresh quarter of an hour
            # five wrong codes spend it; a new one works, and the link of the spent one is gone too
            spent=store.email_grant('reset','new@example.test')
            for _ in range(4):
                with self.assertRaisesRegex(ValueError,'验证码不对'):store.consume_pin('new@example.test','reset','000000' if spent.pin!='000000' else '111111','another-password')
            with self.assertRaisesRegex(ValueError,'验证码已失效'):store.consume_pin('new@example.test','reset','000000' if spent.pin!='000000' else '111111','another-password')
            with self.assertRaisesRegex(ValueError,'验证码已失效'):store.consume_pin('new@example.test','reset',spent.pin,'another-password')
            with self.assertRaises(ValueError):store.consume_email(spent,'another-password')
            fresh=store.email_grant('reset','new@example.test')
            self.assertEqual(store.consume_pin('new@example.test','reset',fresh.pin,'another-password'),owner)
            self.assertFalse(store.valid(session))
            self.assertTrue(store.login('new@example.test','another-password'))
            self.assertTrue(store.valid(store.start_session(owner)))

    def test_mail_budget_spent_only_by_mail_sent_and_a_full_house_says_so_for_everyone(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Identity(Path(temp)/'state.db',account_limit=2)
            # 忘记密码 and 重新发送 for addresses with nothing to send: no mail, no share of the hour's budget
            for i in range(130):
                self.assertIsNone(store.email_grant('reset',f'nobody{i}@example.test'))
                self.assertIsNone(store.resend_signup(f'nobody{i}@example.test'))
            code=store.email_grant('signup','real@example.test','real-account-password')
            store.consume_pin('real@example.test','signup',code.pin)
            store.register('alice','alice-password',store.grant('invite'))
            # full: the same answer for a taken address and a new one
            for email in ('real@example.test','new@example.test'):
                with self.assertRaisesRegex(ValueError,'名额已满'):store.email_grant('signup',email,'some-password-here')


if __name__=='__main__':unittest.main()
