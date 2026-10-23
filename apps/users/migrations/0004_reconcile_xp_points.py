from django.db import migrations
from django.db.models import Sum


def reconcile_xp_points(apps, schema_editor):
    """
    award_xp() used to read-modify-write `xp_points` on a possibly stale user
    instance, so concurrent awards (two progress syncs, a sync plus an answer)
    could overwrite each other. The ledger row was always written, so it holds
    every award: raise each balance that fell behind it. Balances above the
    ledger (seeded or admin-edited) are left alone.
    """
    User = apps.get_model('users', 'User')
    XPTransaction = apps.get_model('users', 'XPTransaction')
    totals = XPTransaction.objects.values('user_id').annotate(total=Sum('points'))
    for row in totals:
        User.objects.filter(pk=row['user_id'], xp_points__lt=row['total']).update(xp_points=row['total'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_longer_badge_name'),
    ]

    operations = [
        migrations.RunPython(reconcile_xp_points, migrations.RunPython.noop),
    ]
