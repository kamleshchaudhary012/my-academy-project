"""
DaanGives NGO Owner Views — Phase 3.3.2-E
===========================================
Implements the NGO Owner API endpoints for Profile, Address, Legal, Bank, Leadership, and Documents:

  1. GET   /api/v1/ngo/profile/me/
  2. POST  /api/v1/ngo/profile/
  3. PATCH /api/v1/ngo/profile/me/
  4. GET   /api/v1/ngo/address/me/
  5. POST  /api/v1/ngo/address/me/
  6. PUT   /api/v1/ngo/address/me/
  7. GET   /api/v1/ngo/legal/me/
  8. POST  /api/v1/ngo/legal/me/
  9. PATCH /api/v1/ngo/legal/me/
 10. GET   /api/v1/ngo/bank/me/
 11. POST  /api/v1/ngo/bank/me/
 12. PATCH /api/v1/ngo/bank/me/
 13. GET   /api/v1/ngo/leadership/
 14. POST  /api/v1/ngo/leadership/
 15. GET   /api/v1/ngo/leadership/<uuid:pk>/
 16. PATCH /api/v1/ngo/leadership/<uuid:pk>/
 17. DELETE /api/v1/ngo/leadership/<uuid:pk>/
 18. GET   /api/v1/ngo/documents/
 19. POST  /api/v1/ngo/documents/
 20. GET   /api/v1/ngo/documents/<uuid:pk>/
 21. DELETE /api/v1/ngo/documents/<uuid:pk>/
 22. GET   /api/v1/ngo/documents/<uuid:pk>/download/

Security & Versioning Rules Enforced:
  - All endpoints require JWT auth & role == 'NGO' (via IsNgoOwner permission).
  - Ownership is derived strictly from request.user (never from body/query params).
  - Uploads & Deactivations allowed ONLY in DRAFT or CORRECTION_REQUIRED status.
  - Upload replacements atomically deactivate previous version (`is_active=False`, `replaces=old_doc`).
  - Downloads served securely via FileResponse with ownership & file existence check (never raw MEDIA_URL).
  - DELETE soft-deactivates document (`is_active=False`) retaining file for audit history.
"""

import os
import mimetypes
from django.db import transaction
from django.utils import timezone
from django.http import FileResponse
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils.translation import gettext_lazy as _

from ngo.models import (
    NGOProfile,
    NGOAddress,
    NGOLegalInfo,
    NGOBankInfo,
    NGOLeadership,
    NGODocument,
    NGOVerification,
)
from ngo.serializers import (
    NGOProfileSerializer,
    NGOAddressSerializer,
    NGOLegalInfoSerializer,
    NGOBankInfoSerializer,
    NGOLeadershipSerializer,
    NGODocumentSerializer,
    NGOVerificationHistorySerializer,
)
from ngo.permissions import IsNgoOwner
from ngo.services.submission_service import (
    submit_ngo_application,
    CompletenessError,
    ConflictError,
    LockedStatusError,
)
from ngo.services.verification_service import StatusTransitionError



class NGOProfileMeView(APIView):
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def get(self, request):
        # select_related prefetches user and verification in one SQL JOIN,
        # avoiding extra queries when the serializer accesses related fields.
        profile = NGOProfile.objects.select_related(
            'user', 'verification',
        ).filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = NGOProfileSerializer(profile, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Profile modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = NGOProfileSerializer(profile, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NGOLogoUploadView(APIView):
    """
    POST /api/v1/ngo/profile/logo/ — Upload or replace NGO logo.
    DELETE /api/v1/ngo/profile/logo/ — Remove NGO logo.
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response({'detail': 'NGO profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        file_obj = request.FILES.get('logo') or request.FILES.get('image') or request.FILES.get('profile_image')
        if not file_obj:
            return Response({'logo': ['No logo image file provided in request.']}, status=status.HTTP_400_BAD_REQUEST)

        from users.image_validators import validate_image_file
        try:
            validate_image_file(file_obj)
        except DjangoValidationError as e:
            return Response({'logo': list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        if profile.logo:
            try:
                profile.logo.delete(save=False)
            except Exception:
                pass

        profile.logo = file_obj
        profile.save(update_fields=['logo', 'updated_at'])

        return Response(
            {
                'message': 'NGO logo updated successfully.',
                'profile': NGOProfileSerializer(profile, context={'request': request}).data,
            },
            status=status.HTTP_200_OK
        )

    def delete(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response({'detail': 'NGO profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        if profile.logo:
            try:
                profile.logo.delete(save=False)
            except Exception:
                pass
            profile.logo = None
            profile.save(update_fields=['logo', 'updated_at'])

        return Response(
            {
                'message': 'NGO logo removed successfully.',
                'profile': NGOProfileSerializer(profile, context={'request': request}).data,
            },
            status=status.HTTP_200_OK
        )


class NGOProfileCreateView(APIView):
    """
    POST /api/v1/ngo/profile/ — Create initial NGOProfile for authenticated NGO user.
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def post(self, request):
        if NGOProfile.objects.filter(user=request.user).exists():
            return Response(
                {'detail': 'NGO profile already exists for this user.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = NGOProfileSerializer(data=request.data)
        if serializer.is_valid():
            profile = serializer.save(
                user=request.user,
                status=NGOProfile.Status.DRAFT,
                is_active=False,
            )
            NGOVerification.objects.get_or_create(ngo=profile)
            return Response(NGOProfileSerializer(profile).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NGOAddressMeView(APIView):
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def get(self, request):
        profile = NGOProfile.objects.select_related('address').filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not hasattr(profile, 'address') or profile.address is None:
            return Response(
                {'detail': 'NGO address not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = NGOAddressSerializer(profile.address)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Address modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if hasattr(profile, 'address') and profile.address is not None:
            return Response(
                {'detail': 'Address already exists for this NGO profile. Use PUT to update.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = NGOAddressSerializer(data=request.data)
        if serializer.is_valid():
            address = serializer.save(ngo=profile)
            return Response(NGOAddressSerializer(address).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Address modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not hasattr(profile, 'address') or profile.address is None:
            return Response(
                {'detail': 'NGO address not found. Use POST to create.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = NGOAddressSerializer(profile.address, data=request.data)
        if serializer.is_valid():
            address = serializer.save()
            return Response(NGOAddressSerializer(address).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NGOLegalMeView(APIView):
    """
    GET   /api/v1/ngo/legal/me/ — Retrieve authenticated NGO's legal information.
    POST  /api/v1/ngo/legal/me/ — Create legal information for authenticated NGO.
    PATCH /api/v1/ngo/legal/me/ — Update legal information for authenticated NGO.
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def get(self, request):
        profile = NGOProfile.objects.select_related('legal_info').filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not hasattr(profile, 'legal_info') or profile.legal_info is None:
            return Response(
                {'detail': 'NGO legal information not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = NGOLegalInfoSerializer(profile.legal_info)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Legal information modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if hasattr(profile, 'legal_info') and profile.legal_info is not None:
            return Response(
                {'detail': 'Legal information already exists for this NGO profile. Use PATCH to update.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = NGOLegalInfoSerializer(data=request.data)
        if serializer.is_valid():
            legal = serializer.save(ngo=profile)
            return Response(NGOLegalInfoSerializer(legal).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Legal information modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not hasattr(profile, 'legal_info') or profile.legal_info is None:
            return Response(
                {'detail': 'NGO legal information not found. Use POST to create.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = NGOLegalInfoSerializer(profile.legal_info, data=request.data, partial=True)
        if serializer.is_valid():
            legal = serializer.save()
            return Response(NGOLegalInfoSerializer(legal).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NGOBankMeView(APIView):
    """
    GET   /api/v1/ngo/bank/me/ — Retrieve authenticated NGO's bank info (masked account number).
    POST  /api/v1/ngo/bank/me/ — Create bank info for authenticated NGO.
    PATCH /api/v1/ngo/bank/me/ — Update bank info for authenticated NGO.
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def get(self, request):
        profile = NGOProfile.objects.select_related('bank_info').filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not hasattr(profile, 'bank_info') or profile.bank_info is None:
            return Response(
                {'detail': 'NGO bank information not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = NGOBankInfoSerializer(profile.bank_info)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _is_bank_editable(self, profile):
        if profile.status == NGOProfile.Status.DRAFT:
            return True
        if profile.status == NGOProfile.Status.CORRECTION_REQUIRED:
            v = getattr(profile, 'verification', None)
            return bool(v and v.bank_correction_requested)
        return False

    def post(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not self._is_bank_editable(profile):
            return Response(
                {'detail': f'Bank information modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if hasattr(profile, 'bank_info') and profile.bank_info is not None:
            return Response(
                {'detail': 'Bank information already exists for this NGO profile. Use PATCH to update.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = NGOBankInfoSerializer(data=request.data)
        if serializer.is_valid():
            bank = serializer.save(ngo=profile)
            return Response(NGOBankInfoSerializer(bank).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not self._is_bank_editable(profile):
            return Response(
                {'detail': f'Bank information modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not hasattr(profile, 'bank_info') or profile.bank_info is None:
            return Response(
                {'detail': 'NGO bank information not found. Use POST to create.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = NGOBankInfoSerializer(profile.bank_info, data=request.data, partial=True)
        if serializer.is_valid():
            bank = serializer.save()
            return Response(NGOBankInfoSerializer(bank).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NGOLeadershipListCreateView(APIView):
    """
    GET  /api/v1/ngo/leadership/ — List all leadership records for authenticated NGO.
    POST /api/v1/ngo/leadership/ — Create a leadership record for authenticated NGO.
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def get(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        leadership_qs = NGOLeadership.objects.filter(ngo=profile)
        serializer = NGOLeadershipSerializer(leadership_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Leadership modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = NGOLeadershipSerializer(data=request.data, context={'ngo': profile})
        if serializer.is_valid():
            leader = serializer.save(ngo=profile)
            return Response(NGOLeadershipSerializer(leader).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NGOLeadershipDetailView(APIView):
    """
    GET    /api/v1/ngo/leadership/<uuid:pk>/ — Retrieve single leadership record.
    PATCH  /api/v1/ngo/leadership/<uuid:pk>/ — Update single leadership record.
    DELETE /api/v1/ngo/leadership/<uuid:pk>/ — Soft-deactivate leadership record.
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def _get_object(self, user, pk):
        profile = NGOProfile.objects.filter(user=user).first()
        if not profile:
            return None, None
        leadership = NGOLeadership.objects.filter(ngo=profile, pk=pk).first()
        return profile, leadership

    def get(self, request, pk):
        profile, leadership = self._get_object(request.user, pk)
        if not profile:
            return Response({'detail': 'NGO profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not leadership:
            return Response({'detail': 'Leadership record not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = NGOLeadershipSerializer(leadership)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, pk):
        profile, leadership = self._get_object(request.user, pk)
        if not profile:
            return Response({'detail': 'NGO profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not leadership:
            return Response({'detail': 'Leadership record not found.'}, status=status.HTTP_404_NOT_FOUND)

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Leadership modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = NGOLeadershipSerializer(leadership, data=request.data, partial=True, context={'ngo': profile})
        if serializer.is_valid():
            leader = serializer.save()
            return Response(NGOLeadershipSerializer(leader).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        profile, leadership = self._get_object(request.user, pk)
        if not profile:
            return Response({'detail': 'NGO profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not leadership:
            return Response({'detail': 'Leadership record not found.'}, status=status.HTTP_404_NOT_FOUND)

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Leadership modification is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        leadership.is_active = False
        leadership.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NGODocumentListCreateView(APIView):
    """
    GET  /api/v1/ngo/documents/ — List all documents belonging to authenticated NGO.
    POST /api/v1/ngo/documents/ — Upload a new document (atomic replacement & versioning).
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def get(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        documents_qs = NGODocument.objects.filter(ngo=profile)
        serializer = NGODocumentSerializer(documents_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Document upload is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = NGODocumentSerializer(data=request.data)
        if serializer.is_valid():
            uploaded_file = serializer.validated_data['file']
            doc_type = serializer.validated_data['document_type']
            original_filename = uploaded_file.name
            file_size_bytes = uploaded_file.size
            mime_type = getattr(uploaded_file, 'content_type', 'application/octet-stream')

            # Find existing active document for versioning
            existing_doc = NGODocument.objects.filter(
                ngo=profile,
                document_type=doc_type,
                is_active=True,
            ).first()

            with transaction.atomic():
                if existing_doc:
                    existing_doc.is_active = False
                    existing_doc.replaced_at = timezone.now()
                    existing_doc.save(update_fields=['is_active', 'replaced_at'])

                doc = serializer.save(
                    ngo=profile,
                    uploaded_by=request.user,
                    original_filename=original_filename,
                    file_size_bytes=file_size_bytes,
                    mime_type=mime_type,
                    is_active=True,
                    replaces=existing_doc,
                )

            return Response(NGODocumentSerializer(doc).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class NGODocumentDetailView(APIView):
    """
    GET    /api/v1/ngo/documents/<uuid:pk>/ — Retrieve metadata for one document.
    DELETE /api/v1/ngo/documents/<uuid:pk>/ — Deactivate document (is_active=False).
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def _get_object(self, user, pk):
        profile = NGOProfile.objects.filter(user=user).first()
        if not profile:
            return None, None
        doc = NGODocument.objects.filter(ngo=profile, pk=pk).first()
        return profile, doc

    def get(self, request, pk):
        profile, doc = self._get_object(request.user, pk)
        if not profile:
            return Response({'detail': 'NGO profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not doc:
            return Response({'detail': 'Document record not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = NGODocumentSerializer(doc)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        profile, doc = self._get_object(request.user, pk)
        if not profile:
            return Response({'detail': 'NGO profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not doc:
            return Response({'detail': 'Document record not found.'}, status=status.HTTP_404_NOT_FOUND)

        if profile.status not in (NGOProfile.Status.DRAFT, NGOProfile.Status.CORRECTION_REQUIRED):
            return Response(
                {'detail': f'Document deactivation is locked in {profile.status} status.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        doc.is_active = False
        doc.replaced_at = timezone.now()
        doc.save(update_fields=['is_active', 'replaced_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class NGODocumentDownloadView(APIView):
    """
    GET /api/v1/ngo/documents/<uuid:pk>/download/ — Securely stream private document file.
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def get(self, request, pk):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response({'detail': 'NGO profile not found.'}, status=status.HTTP_404_NOT_FOUND)

        doc = NGODocument.objects.filter(ngo=profile, pk=pk).first()
        if not doc:
            return Response({'detail': 'Document record not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not doc.is_active:
            return Response({'detail': 'Document is inactive.'}, status=status.HTTP_404_NOT_FOUND)

        if not doc.file or not os.path.exists(doc.file.path):
            return Response({'detail': 'File not found on server.'}, status=status.HTTP_404_NOT_FOUND)

        mime_type = doc.mime_type or mimetypes.guess_type(doc.file.path)[0] or 'application/octet-stream'
        response = FileResponse(open(doc.file.path, 'rb'), content_type=mime_type)
        response['Content-Disposition'] = f'inline; filename="{doc.original_filename}"'
        return response


class NGOSubmitView(APIView):
    """
    POST /api/v1/ngo/submit/ — Submit authenticated NGO application for verification.
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def post(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            submit_ngo_application(profile, request.user)
            profile.refresh_from_db()
            return Response(
                {
                    'message': 'NGO application submitted successfully.',
                    'status': profile.status,
                    'is_active': profile.is_active,
                    'is_public': profile.is_public,
                },
                status=status.HTTP_200_OK,
            )
        except CompletenessError as e:
            return Response(
                {
                    'detail': 'NGO application is incomplete.',
                    'errors': e.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (ConflictError, StatusTransitionError) as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_409_CONFLICT,
            )

        except LockedStatusError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except Exception as e:
            return Response(
                {'detail': f'Submission failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class NGOHistoryView(APIView):
    """
    Returns the immutable verification and submission audit history for the authenticated NGO.
    """
    permission_classes = [IsAuthenticated, IsNgoOwner]

    def get(self, request):
        profile = NGOProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {'detail': 'NGO profile not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        history = profile.history.all().order_by('-timestamp')
        serializer = NGOVerificationHistorySerializer(history, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


