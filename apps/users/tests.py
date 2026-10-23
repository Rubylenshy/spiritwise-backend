from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import User, XPTransaction


def _user(username='listener', **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password='pw', first_name='L', **extra,
    )


class AvatarTests(APITestCase):
    def setUp(self):
        self.user = _user()
        self.client.force_authenticate(self.user)

    def _upload(self):
        image = SimpleUploadedFile('me.jpg', b'\xff\xd8\xff\xe0jpeg', content_type='image/jpeg')
        return self.client.post('/api/auth/avatar/', {'avatar': image}, format='multipart')

    def test_upload_returns_absolute_url(self):
        res = self._upload()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['avatar'].startswith('http://testserver/media/avatars/'))
        self.user.avatar.delete(save=False)

    def test_delete_clears_avatar(self):
        self._upload()
        res = self.client.delete('/api/auth/avatar/')
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.json()['avatar'])
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

    def test_profile_save_keeps_concurrent_xp(self):
        # Another request awards XP after this one loaded the user
        User.objects.filter(pk=self.user.pk).update(xp_points=75)
        self.client.patch('/api/auth/profile/', {'first_name': 'New'}, format='json')
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.xp_points), ('New', 75))


class LeaderboardTests(APITestCase):
    def test_all_time_is_at_least_this_month(self):
        user = _user()
        user.award_xp(50)
        user.award_xp(50)
        self.client.force_authenticate(user)
        monthly = self.client.get('/api/engagement/leaderboard/?period=monthly').json()
        all_time = self.client.get('/api/engagement/leaderboard/?period=all_time').json()
        self.assertEqual(monthly['my_xp'], 100)
        self.assertEqual(all_time['my_xp'], 100)


class ReconcileXPMigrationTests(APITestCase):
    def test_raises_balances_behind_the_ledger(self):
        from importlib import import_module
        from django.apps import apps
        reconcile = import_module('apps.users.migrations.0004_reconcile_xp_points').reconcile_xp_points

        behind, ahead = _user('behind'), _user('ahead', xp_points=500)
        XPTransaction.objects.create(user=behind, points=50)
        XPTransaction.objects.create(user=behind, points=50)
        XPTransaction.objects.create(user=ahead, points=50)
        User.objects.filter(pk=behind.pk).update(xp_points=50)  # the lost update

        reconcile(apps, None)
        behind.refresh_from_db()
        ahead.refresh_from_db()
        self.assertEqual((behind.xp_points, ahead.xp_points), (100, 500))


@override_settings(GOOGLE_OAUTH_CLIENT_ID='client-id')
class GoogleLoginTests(APITestCase):
    def _login(self, **claims):
        claims = {'email': 'new.person@gmail.com', 'email_verified': True, 'given_name': 'New', **claims}
        with mock.patch('google.oauth2.id_token.verify_oauth2_token', return_value=claims) as verify:
            res = self.client.post('/api/auth/google/', {'credential': 'token'}, format='json')
        self.assertEqual(verify.call_args.args[2], 'client-id')
        return res

    def test_creates_account_on_first_sign_in(self):
        res = self._login()
        self.assertEqual(res.status_code, 201)
        body = res.json()
        self.assertTrue(body['created'])
        self.assertEqual(body['user']['username'], 'new.person')
        self.assertIn('access', body)
        self.assertFalse(User.objects.get(email='new.person@gmail.com').has_usable_password())

    def test_signs_into_existing_account_by_email(self):
        existing = _user('new.person')
        existing.email = 'New.Person@gmail.com'
        existing.save()
        res = self._login()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['user']['id'], existing.id)

    def test_username_collision_gets_suffix(self):
        _user('new.person')
        self.assertEqual(self._login().json()['user']['username'], 'new.person2')

    def test_rejects_unverified_email(self):
        self.assertEqual(self._login(email_verified=False).status_code, 401)

    def test_rejects_invalid_token(self):
        with mock.patch('google.oauth2.id_token.verify_oauth2_token', side_effect=ValueError):
            res = self.client.post('/api/auth/google/', {'credential': 'bad'}, format='json')
        self.assertEqual(res.status_code, 401)
