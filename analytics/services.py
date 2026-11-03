from django.db.models import Sum, Count, Avg, F, ExpressionWrapper, DurationField, Q
from django.db.models.functions import TruncMonth, TruncWeek, TruncDay
from django.apps import apps
from django.utils import timezone
import csv
from io import StringIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO

def get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)

class AdminAnalyticsService:
    @staticmethod
    def get_overview():
        MonetaryDonation = get_model('campaigns', 'MonetaryDonation')
        NGOProfile = get_model('ngo', 'NGOProfile')
        Campaign = get_model('campaigns', 'Campaign')
        CompanyProfile = get_model('csr', 'CompanyProfile')
        CSRPartnership = get_model('csr', 'CSRPartnership')
        GrievanceTicket = get_model('grievances', 'GrievanceTicket')

        # Donations
        donations = MonetaryDonation.objects.filter(status='SUCCESS')
        total_donations = donations.aggregate(total=Sum('amount'), count=Count('id'))
        
        by_month = list(donations.annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(amount=Sum('amount'), count=Count('id'))
            .order_by('month'))

        # NGOs
        ngo_stats = NGOProfile.objects.aggregate(
            total=Count('id'),
            verified=Count('id', filter=Q(status=NGOProfile.Status.APPROVED)),
            pending=Count('id', filter=Q(status__in=[NGOProfile.Status.SUBMITTED, NGOProfile.Status.UNDER_REVIEW])),
            rejected=Count('id', filter=Q(status=NGOProfile.Status.REJECTED))
        )

        # Campaigns
        campaign_stats = Campaign.objects.aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(status=Campaign.Status.ACTIVE)),
            completed=Count('id', filter=Q(status=Campaign.Status.COMPLETED)),
            draft=Count('id', filter=Q(status=Campaign.Status.DRAFT))
        )

        # CSR
        csr_partnerships = CSRPartnership.objects.all()
        total_spend = csr_partnerships.aggregate(total=Sum('agreed_funding_amount'))['total'] or 0.00
        
        # Grievances
        from grievances.models import GrievanceStatus
        grievances = GrievanceTicket.objects.all()
        grievance_stats = grievances.aggregate(
            total=Count('id'),
            open=Count('id', filter=Q(status=GrievanceStatus.OPEN)),
            in_review=Count('id', filter=Q(status=GrievanceStatus.IN_REVIEW)),
            resolved=Count('id', filter=Q(status=GrievanceStatus.RESOLVED)),
            closed=Count('id', filter=Q(status=GrievanceStatus.CLOSED))
        )

        return {
            "donations": {
                "total_amount": total_donations['total'] or 0.00,
                "total_count": total_donations['count'],
                "by_month": by_month,
                "top_campaigns": []
            },
            "ngos": ngo_stats,
            "campaigns": campaign_stats,
            "csr": {
                "companies": CompanyProfile.objects.count(),
                "active_partnerships": CSRPartnership.objects.filter(status='ACTIVE').count(),
                "total_spend": total_spend,
                "by_sector": []
            },
            "grievances": grievance_stats,
            "recent_activity": []
        }

    @staticmethod
    def get_donations(from_date=None, to_date=None, group_by='day'):
        MonetaryDonation = get_model('campaigns', 'MonetaryDonation')
        qs = MonetaryDonation.objects.filter(status='SUCCESS')
        
        if from_date: qs = qs.filter(created_at__gte=from_date)
        if to_date: qs = qs.filter(created_at__lte=to_date)
            
        trunc_func = TruncDay if group_by == 'day' else TruncWeek if group_by == 'week' else TruncMonth
        return list(qs.annotate(period=trunc_func('created_at')).values('period').annotate(amount=Sum('amount'), count=Count('id')).order_by('period'))

    @staticmethod
    def get_ngos():
        NGOProfile = get_model('ngo', 'NGOProfile')
        return NGOProfile.objects.values('status').annotate(count=Count('id'))

    @staticmethod
    def get_csr():
        CSRPartnership = get_model('csr', 'CSRPartnership')
        return CSRPartnership.objects.values('status').annotate(count=Count('id'), total_amount=Sum('agreed_funding_amount'))

    @staticmethod
    def get_grievances():
        GrievanceTicket = get_model('grievances', 'GrievanceTicket')
        return GrievanceTicket.objects.values('status', 'priority').annotate(count=Count('id'))

class DonorAnalyticsService:
    @staticmethod
    def get_dashboard(user):
        MonetaryDonation = get_model('campaigns', 'MonetaryDonation')
        qs = MonetaryDonation.objects.filter(donor=user, status='SUCCESS')
        total = qs.aggregate(amount=Sum('amount'), count=Count('id'))
        
        return {
            "total_donated": total['amount'] or 0.00,
            "donation_count": total['count'],
            "tax_savings_estimate": float(total['amount'] or 0.00) * 0.5, # Dummy estimate
            "campaigns_supported": qs.values('campaign').distinct().count(),
            "by_month": list(qs.annotate(month=TruncMonth('created_at')).values('month').annotate(amount=Sum('amount')).order_by('month')),
            "recent_donations": list(qs.order_by('-created_at').values('id', 'amount', 'created_at')[:5])
        }

class NgoAnalyticsService:
    @staticmethod
    def get_dashboard(user):
        MonetaryDonation = get_model('campaigns', 'MonetaryDonation')
        Campaign = get_model('campaigns', 'Campaign')
        
        campaigns = Campaign.objects.filter(ngo__user=user)
        donations = MonetaryDonation.objects.filter(campaign__in=campaigns, status='SUCCESS')
        
        total = donations.aggregate(amount=Sum('amount'), count=Count('id'))
        
        return {
            "total_received": total['amount'] or 0.00,
            "donor_count": donations.values('donor').distinct().count(),
            "campaigns_count": campaigns.count(),
            "campaign_performance": [],
            "by_month": list(donations.annotate(month=TruncMonth('created_at')).values('month').annotate(amount=Sum('amount')).order_by('month'))
        }

class CompanyAnalyticsService:
    @staticmethod
    def get_dashboard(user):
        CSRPartnership = get_model('csr', 'CSRPartnership')
        qs = CSRPartnership.objects.filter(company__user=user)
        
        total_spend = qs.aggregate(total=Sum('agreed_funding_amount'))['total'] or 0.00
        active_count = qs.filter(status='ACTIVE').count()
        completed_count = qs.filter(status='COMPLETED').count()
        
        return {
            "total_csr_spend": total_spend,
            "spend_by_sector": [],
            "active_partnerships": active_count,
            "completed_partnerships": completed_count,
            "milestone_completion_percentage": 0.0,
            "compliance_status": "COMPLIANT"
        }

class ExportService:
    @staticmethod
    def export_csv(headers, data):
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        for row in data:
            writer.writerow(row)
        return output.getvalue()
    
    @staticmethod
    def export_excel(headers, data):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        for row in data:
            ws.append(row)
        output = BytesIO()
        wb.save(output)
        return output.getvalue()

    @staticmethod
    def export_pdf(title, headers, data):
        output = BytesIO()
        p = canvas.Canvas(output, pagesize=letter)
        p.drawString(100, 750, title)
        y = 730
        for row in data:
            p.drawString(100, y, str(row))
            y -= 20
        p.showPage()
        p.save()
        return output.getvalue()
