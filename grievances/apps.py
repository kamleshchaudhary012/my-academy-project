"""
Grievances Application Configuration
"""
from django.apps import AppConfig


class GrievancesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'grievances'
    verbose_name = 'Grievance & Dispute Ticketing'
