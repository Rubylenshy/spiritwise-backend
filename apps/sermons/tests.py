from rest_framework.test import APITestCase

from apps.users.models import User
from .models import Sermon, Series, Tag


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


class LongNameTests(APITestCase):
    def test_long_titles_get_slugs_that_fit(self):
        long = 'A' * 255
        tag = Tag.objects.create(name=long)
        series = Series.objects.create(title=long)
        first = Sermon.objects.create(title=long, speaker='S' * 255)
        second = Sermon.objects.create(title=long, speaker='S')
        self.assertEqual(len(tag.slug), 255)
        self.assertLessEqual(len(series.slug), 255)
        self.assertNotEqual(first.slug, second.slug)
        self.assertLessEqual(len(second.slug), 255)


class ManageTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin', email='admin@example.com', password='pw', first_name='A', is_staff=True,
        )
        self.client.force_authenticate(self.admin)
        self.series = Series.objects.create(title='Romans')
        self.tag = Tag.objects.create(name='Faith')
        self.draft = Sermon.objects.create(title='Draft', speaker='S', is_published=False)

    def test_listener_is_forbidden(self):
        listener = User.objects.create_user(
            username='listener', email='listener@example.com', password='pw', first_name='L',
        )
        self.client.force_authenticate(listener)
        self.assertEqual(self.client.get('/api/sermons/manage/sermons/').status_code, 403)
        self.assertEqual(self.client.post('/api/sermons/manage/tags/', {'name': 'X'}).status_code, 403)

    def test_sermon_list_includes_drafts(self):
        data = self.client.get('/api/sermons/manage/sermons/?status=draft').json()
        self.assertEqual([s['id'] for s in data['results']], [self.draft.id])

    def test_edit_sermon(self):
        res = self.client.patch(f'/api/sermons/manage/sermons/{self.draft.pk}/', {
            'title': 'Final', 'series': self.series.pk, 'tag_ids': [self.tag.pk], 'is_published': True,
        }, format='json')
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual((body['title'], body['series'], body['series_title']), ('Final', self.series.pk, 'Romans'))
        self.assertEqual([t['name'] for t in body['tags']], ['Faith'])
        self.draft.refresh_from_db()
        self.assertTrue(self.draft.is_published)

    def test_clear_sermon_series_and_tags(self):
        self.draft.series = self.series
        self.draft.save()
        self.draft.tags.add(self.tag)
        res = self.client.patch(f'/api/sermons/manage/sermons/{self.draft.pk}/',
                                {'series': None, 'tag_ids': []}, format='json')
        self.assertEqual((res.json()['series'], res.json()['tags']), (None, []))

    def test_sermons_cannot_be_deleted(self):
        res = self.client.delete(f'/api/sermons/manage/sermons/{self.draft.pk}/')
        self.assertEqual(res.status_code, 405)

    def test_tag_crud(self):
        res = self.client.post('/api/sermons/manage/tags/', {'name': '  New   Hope '}, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual((res.json()['name'], res.json()['slug'], res.json()['sermon_count']), ('New Hope', 'new-hope', 0))

        tag_id = res.json()['id']
        res = self.client.patch(f'/api/sermons/manage/tags/{tag_id}/', {'name': 'Hope'}, format='json')
        self.assertEqual(res.json()['slug'], 'hope')

        self.assertEqual(self.client.post('/api/sermons/manage/tags/', {'name': 'faith'}).status_code, 400)
        self.assertEqual(self.client.delete(f'/api/sermons/manage/tags/{tag_id}/').status_code, 204)
        self.assertFalse(Tag.objects.filter(pk=tag_id).exists())

    def test_series_crud(self):
        self.assertEqual(self.client.post('/api/sermons/manage/series/', {'title': 'romans'}).status_code, 400)

        res = self.client.post('/api/sermons/manage/series/', {'title': 'Psalms'}, format='json')
        self.assertEqual(res.status_code, 201)
        series_id = res.json()['id']

        self.draft.series_id = series_id
        self.draft.save()
        res = self.client.patch(f'/api/sermons/manage/series/{series_id}/', {'description': 'Songs'}, format='json')
        self.assertEqual((res.json()['description'], res.json()['sermon_count']), ('Songs', 1))

        self.assertEqual(self.client.delete(f'/api/sermons/manage/series/{series_id}/').status_code, 204)
        self.draft.refresh_from_db()
        self.assertIsNone(self.draft.series)
