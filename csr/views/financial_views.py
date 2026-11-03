"""
CSR Financial & Transparency Views — Phase CSR-Transparency
============================================================
API endpoints for:
- Corporate off-platform bank wire disbursements & transfer evidence
- Admin/Corporate evidence review
- NGO receipt acknowledgements and bank credit confirmation
- NGO ground project expenditure reporting with invoices
- Bilateral grant change requests & approval workflow
- Multi-dimensional financial reconciliation dossiers
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from csr.permissions import (
    IsVerifiedCompanyUser,
    IsVerifiedNgoUser,
    IsPartnershipParticipant,
)
from csr.models import CSRPartnership, CSRDisbursement, CSRExpense, CSRGrantChangeRequest
from csr.serializers.financial_serializers import (
    CSRDisbursementSerializer,
    CSRDisbursementCreateSerializer,
    CSRDisbursementReviewSerializer,
    CSRDisbursementAcknowledgeSerializer,
    CSRExpenseSerializer,
    CSRExpenseCreateSerializer,
    CSRExpenseReviewSerializer,
    CSRGrantChangeRequestSerializer,
    CSRGrantChangeRequestCreateSerializer,
    CSRGrantChangeAdminReviewSerializer,
    CSRGrantChangeCompanyReviewSerializer,
)
from csr.services.financial_service import (
    record_csr_disbursement,
    review_csr_disbursement,
    acknowledge_csr_disbursement,
    report_csr_expense,
    review_csr_expense,
    create_grant_change_request,
    admin_review_grant_change_request,
    company_review_grant_change_request,
    get_partnership_reconciliation_dossier,
    _is_partnership_participant,
)
from csr.services.exceptions import CSRServiceError
from csr.views.company_views import handle_csr_service_error


class CSRPartnershipFinancialsView(APIView):
    """
    Endpoint:
      GET /api/v1/csr/partnerships/<uuid:id>/financials/
      GET /api/v1/ngo/csr/partnerships/<uuid:id>/financials/
      GET /api/v1/admin/csr/partnerships/<uuid:id>/financials/
    Returns the comprehensive financial reconciliation dossier for a bilateral CSR partnership.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        try:
            dossier = get_partnership_reconciliation_dossier(request.user, id, request=request)
            return Response(dossier, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CSRPartnershipDisbursementListView(APIView):
    """
    Endpoint:
      GET  /api/v1/csr/partnerships/<uuid:id>/disbursements/
      POST /api/v1/csr/partnerships/<uuid:id>/disbursements/
    Lists or records itemized corporate bank wire disbursements with evidence.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, id):
        try:
            partnership = CSRPartnership.objects.get(id=id)
        except (CSRPartnership.DoesNotExist, ValueError):
            return Response({'detail': 'CSR partnership not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not _is_partnership_participant(request.user, partnership):
            return Response({'detail': 'CSR partnership not found.'}, status=status.HTTP_404_NOT_FOUND)

        disbursements = CSRDisbursement.objects.filter(partnership=partnership).order_by('-disbursement_date', '-created_at')
        serializer = CSRDisbursementSerializer(disbursements, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, id):
        serializer = CSRDisbursementCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        evidence_file = request.FILES.get('evidence_document')

        try:
            disbursement = record_csr_disbursement(
                user=request.user,
                partnership_id=id,
                data=serializer.validated_data,
                evidence_file=evidence_file,
            )
            read_serializer = CSRDisbursementSerializer(disbursement, context={'request': request})
            return Response(read_serializer.data, status=status.HTTP_201_CREATED)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CSRDisbursementReviewView(APIView):
    """
    Endpoint:
      POST /api/v1/admin/csr/disbursements/<uuid:id>/review/
      POST /api/v1/csr/disbursements/<uuid:id>/review/
    Allows platform administrators to verify or reject bank transfer evidence with explicit reason logging.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        serializer = CSRDisbursementReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            updated = review_csr_disbursement(
                user=request.user,
                disbursement_id=id,
                decision=serializer.validated_data['decision'],
                review_notes=serializer.validated_data.get('review_notes', ''),
            )
            read_serializer = CSRDisbursementSerializer(updated, context={'request': request})
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CSRDisbursementAcknowledgeView(APIView):
    """
    Endpoint:
      POST /api/v1/ngo/csr/disbursements/<uuid:id>/acknowledge/
    Allows recipient NGOs to acknowledge receipt of bank wires or report non-receipt/dispute.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, id):
        serializer = CSRDisbursementAcknowledgeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        receipt_file = request.FILES.get('receipt_document')

        try:
            updated = acknowledge_csr_disbursement(
                user=request.user,
                disbursement_id=id,
                decision=serializer.validated_data['decision'],
                notes=serializer.validated_data.get('notes', ''),
                receipt_document=receipt_file,
            )
            read_serializer = CSRDisbursementSerializer(updated, context={'request': request})
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CSRPartnershipExpenseListCreateView(APIView):
    """
    Endpoint:
      GET  /api/v1/csr/partnerships/<uuid:id>/expenses/
      POST /api/v1/ngo/csr/partnerships/<uuid:id>/expenses/
    Lists ground project expenditures or allows recipient NGO to submit an itemized expense with invoice proof.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, id):
        try:
            partnership = CSRPartnership.objects.get(id=id)
        except (CSRPartnership.DoesNotExist, ValueError):
            return Response({'detail': 'CSR partnership not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not _is_partnership_participant(request.user, partnership):
            return Response({'detail': 'CSR partnership not found.'}, status=status.HTTP_404_NOT_FOUND)

        expenses = CSRExpense.objects.filter(partnership=partnership).order_by('-expense_date', '-created_at')
        serializer = CSRExpenseSerializer(expenses, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, id):
        serializer = CSRExpenseCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        invoice_file = request.FILES.get('invoice_document')

        try:
            expense = report_csr_expense(
                user=request.user,
                partnership_id=id,
                data=serializer.validated_data,
                invoice_document=invoice_file,
            )
            read_serializer = CSRExpenseSerializer(expense, context={'request': request})
            return Response(read_serializer.data, status=status.HTTP_201_CREATED)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CSRExpenseReviewView(APIView):
    """
    Endpoint:
      POST /api/v1/csr/expenses/<uuid:id>/review/
      POST /api/v1/admin/csr/expenses/<uuid:id>/review/
    Allows corporate sponsors or administrators to verify or reject NGO expenditure proofs.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        serializer = CSRExpenseReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            updated = review_csr_expense(
                user=request.user,
                expense_id=id,
                decision=serializer.validated_data['decision'],
                review_notes=serializer.validated_data.get('review_notes', ''),
            )
            read_serializer = CSRExpenseSerializer(updated, context={'request': request})
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


# ===========================================================================
# Grant Change Request Endpoints
# ===========================================================================

class CSRGrantChangeRequestListCreateView(APIView):
    """
    Endpoint:
      GET  /api/v1/csr/partnerships/<uuid:id>/grant-changes/
      GET  /api/v1/ngo/csr/partnerships/<uuid:id>/grant-changes/
      POST /api/v1/ngo/csr/partnerships/<uuid:id>/grant-changes/
      POST /api/v1/csr/partnerships/<uuid:id>/grant-changes/
    Lists or submits bilateral grant change proposals.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, id):
        try:
            partnership = CSRPartnership.objects.get(id=id)
        except (CSRPartnership.DoesNotExist, ValueError):
            return Response({'detail': 'CSR partnership not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not _is_partnership_participant(request.user, partnership):
            return Response({'detail': 'CSR partnership not found.'}, status=status.HTTP_404_NOT_FOUND)

        change_requests = CSRGrantChangeRequest.objects.filter(partnership=partnership).order_by('-created_at')
        serializer = CSRGrantChangeRequestSerializer(change_requests, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, id):
        serializer = CSRGrantChangeRequestCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        budget_file = request.FILES.get('revised_budget_document')

        try:
            change_request = create_grant_change_request(
                user=request.user,
                partnership_id=id,
                proposed_commitment=serializer.validated_data['proposed_commitment'],
                reason=serializer.validated_data['reason'],
                revised_budget_document=budget_file,
            )
            read_serializer = CSRGrantChangeRequestSerializer(change_request, context={'request': request})
            return Response(read_serializer.data, status=status.HTTP_201_CREATED)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CSRGrantChangeAdminReviewView(APIView):
    """
    Endpoint:
      POST /api/v1/admin/csr/grant-changes/<uuid:id>/review/
    Stage 1 review by Platform Administrator for proposed grant change.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, id):
        serializer = CSRGrantChangeAdminReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        mou_file = request.FILES.get('mou_amendment_document')

        try:
            updated = admin_review_grant_change_request(
                user=request.user,
                request_id=id,
                decision=serializer.validated_data['decision'],
                review_notes=serializer.validated_data.get('review_notes', ''),
                mou_amendment_document=mou_file,
            )
            read_serializer = CSRGrantChangeRequestSerializer(updated, context={'request': request})
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)


class CSRGrantChangeCompanyReviewView(APIView):
    """
    Endpoint:
      POST /api/v1/csr/grant-changes/<uuid:id>/review/
    Stage 2 final approval or rejection by Corporate Partner.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        serializer = CSRGrantChangeCompanyReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            updated = company_review_grant_change_request(
                user=request.user,
                request_id=id,
                decision=serializer.validated_data['decision'],
                review_notes=serializer.validated_data.get('review_notes', ''),
            )
            read_serializer = CSRGrantChangeRequestSerializer(updated, context={'request': request})
            return Response(read_serializer.data, status=status.HTTP_200_OK)
        except CSRServiceError as exc:
            return handle_csr_service_error(exc)
