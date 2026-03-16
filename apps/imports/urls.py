from django.urls import path
from . import views

urlpatterns = [
    path('', views.import_jobs, name='import-jobs'),
    path('<int:pk>/', views.import_job_detail, name='import-job-detail'),
]
