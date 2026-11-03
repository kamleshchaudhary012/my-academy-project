from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from django.http import HttpResponse
from .services import AdminAnalyticsService, DonorAnalyticsService, NgoAnalyticsService, CompanyAnalyticsService, ExportService
from .permissions import IsDonor, IsNGO, IsCompany

class AdminOverviewView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        return Response(AdminAnalyticsService.get_overview())

class AdminDonationsView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        f = request.query_params.get('from')
        t = request.query_params.get('to')
        g = request.query_params.get('group_by', 'day')
        return Response(AdminAnalyticsService.get_donations(f, t, g))

class AdminNGOsView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        return Response(AdminAnalyticsService.get_ngos())

class AdminCSRView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        return Response(AdminAnalyticsService.get_csr())

class AdminGrievancesView(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        return Response(AdminAnalyticsService.get_grievances())

class DonorDashboardView(APIView):
    permission_classes = [IsAuthenticated, IsDonor]
    def get(self, request):
        return Response(DonorAnalyticsService.get_dashboard(request.user))

class NGODashboardView(APIView):
    permission_classes = [IsAuthenticated, IsNGO]
    def get(self, request):
        return Response(NgoAnalyticsService.get_dashboard(request.user))

class CompanyDashboardView(APIView):
    permission_classes = [IsAuthenticated, IsCompany]
    def get(self, request):
        return Response(CompanyAnalyticsService.get_dashboard(request.user))

class BaseExportView(APIView):
    permission_classes = [IsAdminUser]
    
    def perform_content_negotiation(self, request, force=False):
        renderers = self.get_renderers()
        return (renderers[0], renderers[0].media_type)
    
    def get_data(self, request):
        return [], []

    def get(self, request):
        fmt = request.query_params.get('export_format') or request.query_params.get('format', 'csv')
        headers, data = self.get_data(request)
        
        if fmt == 'excel':
            content = ExportService.export_excel(headers, data)
            response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = 'attachment; filename="export.xlsx"'
        elif fmt == 'pdf':
            content = ExportService.export_pdf("Export", headers, data)
            response = HttpResponse(content, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="export.pdf"'
        else:
            content = ExportService.export_csv(headers, data)
            response = HttpResponse(content, content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="export.csv"'
        return response

class ExportDonationsView(BaseExportView):
    def get_data(self, request):
        data = AdminAnalyticsService.get_donations()
        headers = ['Period', 'Amount', 'Count']
        rows = [[d['period'], d['amount'], d['count']] for d in data]
        return headers, rows

class ExportNGOsView(BaseExportView):
    def get_data(self, request):
        data = AdminAnalyticsService.get_ngos()
        headers = ['Status', 'Count']
        rows = [[d['status'], d['count']] for d in data]
        return headers, rows

class ExportCSRView(BaseExportView):
    def get_data(self, request):
        data = AdminAnalyticsService.get_csr()
        headers = ['Status', 'Count', 'Total Amount']
        rows = [[d['status'], d['count'], d['total_amount']] for d in data]
        return headers, rows

class ExportGrievancesView(BaseExportView):
    def get_data(self, request):
        data = AdminAnalyticsService.get_grievances()
        headers = ['Status', 'Priority', 'Count']
        rows = [[d['status'], d['priority'], d['count']] for d in data]
        return headers, rows

class ExportFormCSR1View(APIView):
    permission_classes = [IsAdminUser]
    def get(self, request):
        content = ExportService.export_pdf("Form CSR-1", ["Field", "Value"], [["Company", "N/A"]])
        response = HttpResponse(content, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="form-csr-1.pdf"'
        return response
