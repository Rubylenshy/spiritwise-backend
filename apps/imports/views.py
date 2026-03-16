from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response

from .models import CloudImportJob
from .serializers import ImportJobSerializer, CreateImportJobSerializer
from .tasks import process_import_job


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsAdminUser])
def import_jobs(request):
    """
    GET  /api/imports/          — list all import jobs (admin only)
    POST /api/imports/          — create + queue a new import job
    """
    if request.method == 'GET':
        jobs = CloudImportJob.objects.select_related('sermon').all()
        return Response(ImportJobSerializer(jobs, many=True).data)

    serializer = CreateImportJobSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    job = serializer.save(requested_by=request.user)

    # Enqueue the Celery task
    process_import_job.delay(job.pk)

    return Response(ImportJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUser])
def import_job_detail(request, pk):
    """
    GET /api/imports/<pk>/
    Poll this endpoint to track progress of a running import.
    """
    try:
        job = CloudImportJob.objects.select_related('sermon').get(pk=pk)
    except CloudImportJob.DoesNotExist:
        return Response({'detail': 'Import job not found.'}, status=status.HTTP_404_NOT_FOUND)

    return Response(ImportJobSerializer(job).data)
