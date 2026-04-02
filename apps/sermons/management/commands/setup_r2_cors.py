"""
Usage:
    python manage.py setup_r2_cors

Sets CORS policy on the R2 bucket to allow audio streaming from any origin.
Run this once after setting up R2 credentials.
"""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Set CORS rules on the R2 bucket for audio streaming'

    def handle(self, *args, **options):
        from apps.sermons.r2 import get_r2_client

        client = get_r2_client()
        bucket = settings.AWS_STORAGE_BUCKET_NAME

        cors_config = {
            'CORSRules': [
                {
                    'AllowedHeaders': ['*'],
                    'AllowedMethods': ['GET', 'HEAD'],
                    'AllowedOrigins': ['*'],
                    'ExposeHeaders': [
                        'Content-Length',
                        'Content-Range',
                        'Accept-Ranges',
                        'ETag',
                    ],
                    'MaxAgeSeconds': 3600,
                }
            ]
        }

        try:
            client.put_bucket_cors(
                Bucket=bucket,
                CORSConfiguration=cors_config,
            )
            self.stdout.write(self.style.SUCCESS(
                f'CORS rules set on bucket: {bucket}'
            ))

            # Verify
            result = client.get_bucket_cors(Bucket=bucket)
            for rule in result['CORSRules']:
                self.stdout.write(f"  Origins: {rule['AllowedOrigins']}")
                self.stdout.write(f"  Methods: {rule['AllowedMethods']}")
                self.stdout.write(f"  Exposed headers: {rule['ExposeHeaders']}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed: {e}'))
