from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase

from apps.sermons.models import Sermon
from apps.users.models import User
from .models import Playlist, PlaylistItem


class PlaylistCoverThumbnailsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='listener', email='listener@example.com', password='pw', first_name='L',
        )
        self.client.force_authenticate(self.user)

    def _sermon(self, title, thumbnail='', **kwargs):
        return Sermon.objects.create(title=title, speaker='Speaker', thumbnail=thumbnail, **kwargs)

    def _playlist(self, name, sermons):
        playlist = Playlist.objects.create(user=self.user, name=name)
        for position, sermon in sermons:
            PlaylistItem.objects.create(playlist=playlist, sermon=sermon, position=position)
        return playlist

    def _list(self):
        response = self.client.get('/api/library/playlists/')
        self.assertEqual(response.status_code, 200)
        return {p['name']: p for p in response.json()}

    def test_first_four_distinct_thumbnails_in_position_order(self):
        self._playlist('Mix', [
            (50, self._sermon('Late', 'sermons/thumbnails/late.jpg')),
            (10, self._sermon('First', 'sermons/thumbnails/a.jpg')),
            (15, self._sermon('No art')),
            (20, self._sermon('Hidden', 'sermons/thumbnails/hidden.jpg', is_published=False)),
            (30, self._sermon('Same art', 'sermons/thumbnails/a.jpg')),
            (40, self._sermon('Second', 'sermons/thumbnails/b.jpg')),
            (45, self._sermon('Third', 'sermons/thumbnails/c.jpg')),
            (60, self._sermon('Fifth', 'sermons/thumbnails/e.jpg')),
        ])

        covers = self._list()['Mix']['cover_thumbnails']

        self.assertEqual(covers, [
            'http://testserver/media/sermons/thumbnails/a.jpg',
            'http://testserver/media/sermons/thumbnails/b.jpg',
            'http://testserver/media/sermons/thumbnails/c.jpg',
            'http://testserver/media/sermons/thumbnails/late.jpg',
        ])

    def test_empty_playlist_has_no_covers(self):
        self._playlist('Empty', [])
        self.assertEqual(self._list()['Empty']['cover_thumbnails'], [])

    def test_list_query_count_does_not_grow_with_playlists(self):
        def make(n):
            for i in range(n):
                self._playlist(f'P{n}-{i}', [
                    (j, self._sermon(f'S{n}-{i}-{j}', f'sermons/thumbnails/{n}-{i}-{j}.jpg'))
                    for j in range(5)
                ])

        make(1)
        with CaptureQueriesContext(connection) as one:
            self._list()
        make(4)
        with CaptureQueriesContext(connection) as five:
            data = self._list()

        self.assertEqual(len(data), 5)
        self.assertEqual(len(five), len(one))
        self.assertTrue(all(len(p['cover_thumbnails']) == 4 for p in data.values()))

    def test_detail_and_create_include_absolute_covers(self):
        sermon = self._sermon('One', 'sermons/thumbnails/one.jpg')
        playlist = self._playlist('Solo', [(1, sermon)])

        detail = self.client.get(f'/api/library/playlists/{playlist.pk}/').json()
        self.assertEqual(detail['cover_thumbnails'], ['http://testserver/media/sermons/thumbnails/one.jpg'])

        created = self.client.post(
            '/api/library/playlists/', {'name': 'New', 'sermon_id': sermon.pk}, format='json',
        ).json()
        self.assertEqual(created['cover_thumbnails'], ['http://testserver/media/sermons/thumbnails/one.jpg'])
