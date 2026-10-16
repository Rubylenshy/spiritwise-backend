from rest_framework.test import APITestCase

from apps.users.models import User
from .models import Sermon, Series


class SeriesCoverImageTests(APITestCase):
    def setUp(self):
        user = User.objects.create_user(
            username='listener', email='listener@example.com', password='pw', first_name='L',
        )
        self.client.force_authenticate(user)
        self.series = Series.objects.create(title='Romans', cover_image='series/romans.jpg')
        Sermon.objects.create(title='Romans 1', speaker='Speaker', series=self.series)

    def test_series_list_cover_is_absolute(self):
        data = self.client.get('/api/sermons/series/').json()
        self.assertEqual(data[0]['cover_image'], 'http://testserver/media/series/romans.jpg')

    def test_series_detail_cover_is_absolute(self):
        data = self.client.get(f'/api/sermons/series/{self.series.pk}/').json()
        self.assertEqual(data['cover_image'], 'http://testserver/media/series/romans.jpg')
