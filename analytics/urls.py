from django.urls import path
from . import views

urlpatterns = [
    # Admin Dashboards
    path('admin/overview/', views.AdminOverviewView.as_view(), name='analytics-admin-overview'),
    path('admin/donations/', views.AdminDonationsView.as_view(), name='analytics-admin-donations'),
    path('admin/ngos/', views.AdminNGOsView.as_view(), name='analytics-admin-ngos'),
    path('admin/csr/', views.AdminCSRView.as_view(), name='analytics-admin-csr'),
    path('admin/grievances/', views.AdminGrievancesView.as_view(), name='analytics-admin-grievances'),
    
    # Role Dashboards
    path('donor/me/', views.DonorDashboardView.as_view(), name='analytics-donor-me'),
    path('ngo/me/', views.NGODashboardView.as_view(), name='analytics-ngo-me'),
    path('company/me/', views.CompanyDashboardView.as_view(), name='analytics-company-me'),
    
    # Exports
    path('export/donations/', views.ExportDonationsView.as_view(), name='analytics-export-donations'),
    path('export/ngos/', views.ExportNGOsView.as_view(), name='analytics-export-ngos'),
    path('export/csr/', views.ExportCSRView.as_view(), name='analytics-export-csr'),
    path('export/grievances/', views.ExportGrievancesView.as_view(), name='analytics-export-grievances'),
    path('export/form-csr-1/', views.ExportFormCSR1View.as_view(), name='analytics-export-form-csr-1'),
]
