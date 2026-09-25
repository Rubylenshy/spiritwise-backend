from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.users'
    label = 'users'

    def ready(self):
        from spiritwise.rls import enable_rls
        # post_migrate fires once per app; hooking one sender runs it once per
        # `migrate`, after every app's tables exist.
        post_migrate.connect(enable_rls, sender=self, dispatch_uid='spiritwise-enable-rls')
