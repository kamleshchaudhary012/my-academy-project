"""
CSR Notification Hooks & Service Unit Tests — Phase CSR-2.7
===========================================================
Comprehensive unit tests for the event-driven notification infrastructure of the CSR Connect module.
Validates all 8 frozen lifecycle events from CSR-2.0 Section 16, server-authoritative recipient
resolution, template privacy sanitization, and strict failure isolation.
"""

from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.core import mail
from django.db import transaction
from django.contrib.auth import get_user_model

from csr.models import (
    CompanyProfile,
    CSRRequirement,
    CSRSupportRequest,
    CSRPartnership,
    PartnershipMilestone,
    CompanyVerificationStatus,
    CSRRequirementStatus,
    CSRSupportRequestStatus,
    MilestoneStatus,
    ScheduleVIICategory,
    LocationScope,
    BeneficiaryDemographic,
)
from csr.services.notification_service import (
    CSRNotificationEventType,
    send_csr_email,
    notify_support_request_created,
    notify_support_request_status_changed,
    notify_partnership_created,
    notify_partnership_mou_uploaded,
    notify_milestone_status_changed,
    notify_verification_status_changed,
    dispatch_csr_notification,
)
from csr.services.notification_hooks import (
    notify_support_request_created as hook_notify_support_request_created,
    notify_support_request_status_changed as hook_notify_support_request_status_changed,
    notify_partnership_created as hook_notify_partnership_created,
    notify_partnership_mou_uploaded as hook_notify_partnership_mou_uploaded,
    notify_milestone_status_changed as hook_notify_milestone_status_changed,
    notify_verification_status_changed as hook_notify_verification_status_changed,
    dispatch_csr_notification as hook_dispatch_csr_notification,
)
from csr.tests.helpers import (
    make_user,
    make_company_profile,
    make_ngo_profile,
    make_csr_requirement,
    make_csr_partnership,
    make_partnership_milestone,
)

User = get_user_model()


class CSRNotificationHooksTests(TestCase):
    """Exhaustive tests for CSR notification hooks and email rendering."""

    def setUp(self):
        mail.outbox.clear()

        # Set up Company user and profile
        self.company_user = make_user(
            email="csr_spoc@tatapower.com",
            full_name="Ratan Sharma",
            role=User.Role.COMPANY,
        )
        self.company = make_company_profile(
            user=self.company_user,
            company_name="Tata Power Renewable Energy Ltd",
            verification_status=CompanyVerificationStatus.APPROVED,
        )

        # Set up NGO user and profile
        self.ngo_user = make_user(
            email="lead@gramin-vikas.org",
            full_name="Dr. Anil Deshmukh",
            role=User.Role.NGO,
        )
        self.ngo = make_ngo_profile(
            user=self.ngo_user,
            display_name="Gramin Vikas Sansthan",
            legal_name="Gramin Vikas Sansthan Trust",
        )

        # Set up CSR Requirement
        self.requirement = make_csr_requirement(
            ngo=self.ngo,
            title="Solar Micro-Grids in Rural Maharashtra",
            schedule_vii_category=ScheduleVIICategory.ENVIRONMENTAL_SUSTAINABILITY,
            state="Maharashtra",
            district="Pune",
            location_scope=LocationScope.SPECIFIC_DISTRICT,
            beneficiary_demographic=BeneficiaryDemographic.RURAL_COMMUNITIES,
            total_estimated_budget=Decimal("1500000.00"),
            required_csr_funding=Decimal("1200000.00"),
            start_date=date.today(),
            expected_completion_date=date.today() + timedelta(days=365),
            status=CSRRequirementStatus.OPEN_FOR_CSR,
        )

        # Set up Support Request
        self.support_request = CSRSupportRequest.objects.create(
            requirement=self.requirement,
            company=self.company,
            proposed_funding=Decimal("1200000.00"),
            message="We would like to fully fund this solar initiative under our FY27 CSR budget.",
            status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
        )

        # Set up Partnership
        self.partnership = make_csr_partnership(
            company=self.company,
            ngo=self.ngo,
            requirement=self.requirement,
            support_request=self.support_request,
            agreed_funding_amount=Decimal("1200000.00"),
        )

        # Set up Milestone
        self.milestone = make_partnership_milestone(
            partnership=self.partnership,
            title="Phase 1: Procurement of Solar Panels & Inverters",
            target_completion_date=date.today() + timedelta(days=90),
            completion_percentage=25,
            status=MilestoneStatus.PENDING,
        )

    # --------------------------------------------------------------------------
    # 1. Event Coverage (All 8 Frozen Events from CSR-2.0 Section 16)
    # --------------------------------------------------------------------------

    def test_event_1_support_request_submitted_notifies_ngo(self):
        """Event 1: Support request submission sends email to owning NGO primary contact."""
        result = notify_support_request_created(self.support_request)
        self.assertTrue(result["success"])
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.to, ["lead@gramin-vikas.org"])
        self.assertIn("Solar Micro-Grids", email.subject)
        self.assertIn("Tata Power Renewable Energy Ltd", email.body)
        self.assertIn("₹1,200,000.00", email.body)

    def test_event_2_support_request_accepted_notifies_company(self):
        """Event 2: Support request acceptance sends email to Company CSR contact."""
        self.support_request.status = CSRSupportRequestStatus.ACCEPTED
        self.support_request.save()

        result = notify_support_request_status_changed(
            self.support_request,
            old_status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
            new_status=CSRSupportRequestStatus.ACCEPTED,
        )
        self.assertTrue(result["success"])
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.to, ["csr_spoc@tatapower.com"])
        self.assertIn("Accepted", email.subject)
        self.assertIn("Gramin Vikas Sansthan", email.body)
        self.assertIn("Solar Micro-Grids", email.body)

    def test_event_3_support_request_rejected_notifies_company(self):
        """Event 3: Support request rejection sends email to Company CSR contact."""
        self.support_request.status = CSRSupportRequestStatus.REJECTED
        self.support_request.rejection_reason = "Capacity already allocated to another partner."
        self.support_request.save()

        result = notify_support_request_status_changed(
            self.support_request,
            old_status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
            new_status=CSRSupportRequestStatus.REJECTED,
        )
        self.assertTrue(result["success"])
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.to, ["csr_spoc@tatapower.com"])
        self.assertIn("Update", email.subject)
        self.assertIn("Capacity already allocated", email.body)

    def test_event_4_partnership_mou_uploaded_notifies_both_parties(self):
        """Event 4: Partnership MoU upload sends email to both Company and NGO."""
        result = notify_partnership_mou_uploaded(self.partnership)
        self.assertTrue(result["success"])
        self.assertEqual(len(mail.outbox), 2)

        recipients = {mail.outbox[0].to[0], mail.outbox[1].to[0]}
        self.assertEqual(recipients, {"csr_spoc@tatapower.com", "lead@gramin-vikas.org"})
        for email in mail.outbox:
            self.assertIn("MoU Updated", email.subject)
            self.assertIn("Solar Micro-Grids", email.body)

    def test_event_5_milestone_evidence_submitted_notifies_company(self):
        """Event 5: Milestone evidence submission sends email to Company reviewer."""
        result = notify_milestone_status_changed(
            self.milestone,
            old_status=MilestoneStatus.PENDING,
            new_status=MilestoneStatus.SUBMITTED,
        )
        self.assertTrue(result["success"])
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.to, ["csr_spoc@tatapower.com"])
        self.assertIn("Milestone Evidence Ready", email.subject)
        self.assertIn("Phase 1: Procurement", email.body)
        self.assertIn("25%", email.body)

    def test_event_6_milestone_verified_notifies_ngo(self):
        """Event 6: Milestone verification sends email to NGO project lead."""
        result = notify_milestone_status_changed(
            self.milestone,
            old_status=MilestoneStatus.SUBMITTED,
            new_status=MilestoneStatus.VERIFIED,
        )
        self.assertTrue(result["success"])
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.to, ["lead@gramin-vikas.org"])
        self.assertIn("Successfully Verified", email.subject)
        self.assertIn("Phase 1: Procurement", email.body)
        self.assertIn("VERIFIED", email.body)

    def test_event_7_company_verification_status_notifies_company(self):
        """Event 7: Company verification approval/rejection sends email to Company user."""
        result = notify_verification_status_changed(
            entity_type="COMPANY",
            entity_id=self.company.id,
            status="APPROVED",
            admin_notes="All CIN and MCA records verified successfully.",
        )
        self.assertTrue(result["success"])
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.to, ["csr_spoc@tatapower.com"])
        self.assertIn("Company CSR Verification: APPROVED", email.subject)
        self.assertIn("All CIN and MCA records", email.body)

    def test_event_8_requirement_verification_status_notifies_ngo(self):
        """Event 8: Requirement review approval sends email to NGO author."""
        result = notify_verification_status_changed(
            entity_type="REQUIREMENT",
            entity_id=self.requirement.id,
            status="OPEN_FOR_CSR",
            admin_notes="Proposal meets Schedule VII criteria.",
        )
        self.assertTrue(result["success"])
        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]
        self.assertEqual(email.to, ["lead@gramin-vikas.org"])
        self.assertIn("CSR Requirement Review: OPEN_FOR_CSR", email.subject)
        self.assertIn("Proposal meets Schedule VII criteria", email.body)

    # --------------------------------------------------------------------------
    # 2. Generic Dispatcher Integration
    # --------------------------------------------------------------------------

    def test_generic_dispatcher_for_all_events(self):
        """Test dispatch_csr_notification handles all frozen event enums."""
        # Dispatch support request accepted
        res = dispatch_csr_notification(
            CSRNotificationEventType.CSR_SUPPORT_REQUEST_ACCEPTED,
            {"support_request": self.support_request},
        )
        self.assertTrue(res["success"])
        self.assertEqual(len(mail.outbox), 1)

        # Dispatch milestone verified
        res2 = dispatch_csr_notification(
            CSRNotificationEventType.CSR_MILESTONE_VERIFIED,
            {"milestone": self.milestone},
        )
        self.assertTrue(res2["success"])
        self.assertEqual(len(mail.outbox), 2)

    def test_generic_dispatcher_unhandled_event(self):
        """Unhandled event returns error dictionary without raising."""
        res = dispatch_csr_notification("UNKNOWN_EVENT_TYPE", {})
        self.assertFalse(res["success"])
        self.assertIn("Unhandled event type", res["error"])

    # --------------------------------------------------------------------------
    # 3. Hook Module Re-export Parity
    # --------------------------------------------------------------------------

    def test_notification_hooks_re_export_parity(self):
        """Functions in notification_hooks behave identically to notification_service."""
        res1 = hook_notify_support_request_created(self.support_request)
        self.assertTrue(res1["success"])
        self.assertEqual(len(mail.outbox), 1)

        res2 = hook_dispatch_csr_notification(
            CSRNotificationEventType.CSR_PARTNERSHIP_MOU_UPLOADED,
            {"partnership": self.partnership},
        )
        self.assertTrue(res2["success"])
        self.assertEqual(len(mail.outbox), 3)

    # --------------------------------------------------------------------------
    # 4. Server-Authoritative Recipient Resolution & Missing Email Safety
    # --------------------------------------------------------------------------

    def test_missing_recipient_email_handled_gracefully(self):
        """If user has no email address, notification logs and exits cleanly without raising."""
        self.company_user.email = ""
        self.company_user.save()

        result = notify_support_request_status_changed(
            self.support_request,
            old_status=CSRSupportRequestStatus.PENDING_NGO_REVIEW,
            new_status=CSRSupportRequestStatus.ACCEPTED,
        )
        self.assertFalse(result["success"])
        self.assertTrue(result.get("skipped", False))
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_entity_id_handled_gracefully(self):
        """Invalid entity ID in verification hook returns failure dict without raising."""
        result = notify_verification_status_changed(
            entity_type="COMPANY",
            entity_id=999999,
            status="APPROVED",
        )
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    # --------------------------------------------------------------------------
    # 5. Privacy & Template Safety (No Sensitive Leaks)
    # --------------------------------------------------------------------------

    def test_template_safety_no_pii_or_financial_secrets(self):
        """Rendered emails must NEVER contain PAN, bank details, file paths, or JWTs."""
        notify_support_request_created(self.support_request)
        notify_partnership_mou_uploaded(self.partnership)
        notify_milestone_status_changed(self.milestone, "PENDING", "SUBMITTED")

        for email in mail.outbox:
            body = email.body
            self.assertNotIn("PAN", body)
            self.assertNotIn("IFSC", body)
            self.assertNotIn("bank_account", body)
            self.assertNotIn("/media/", body)
            self.assertNotIn("Bearer ", body)
            self.assertNotIn("http://external", body)
            self.assertNotIn("https://external", body)

    # --------------------------------------------------------------------------
    # 6. Failure Safety & Exception Isolation
    # --------------------------------------------------------------------------

    def test_smtp_failure_does_not_raise(self):
        """SMTP / Network failure is caught, logged, and never raises to caller."""
        with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=Exception("SMTP Connection Timeout")):
            result = notify_support_request_created(self.support_request)
            self.assertFalse(result["success"])
            self.assertIn("SMTP Connection Timeout", result["error"])

    # --------------------------------------------------------------------------
    # 7. Transaction Safety (on_commit Simulation)
    # --------------------------------------------------------------------------

    def test_transaction_on_commit_pattern(self):
        """Demonstrates transaction.on_commit executes notification safely after commit."""
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                self.support_request.status = CSRSupportRequestStatus.ACCEPTED
                self.support_request.save()
                transaction.on_commit(
                    lambda: notify_support_request_status_changed(
                        self.support_request,
                        CSRSupportRequestStatus.PENDING_NGO_REVIEW,
                        CSRSupportRequestStatus.ACCEPTED,
                    )
                )

        # After atomic block commits and on_commit callbacks execute
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["csr_spoc@tatapower.com"])

    # --------------------------------------------------------------------------
    # 8. Purity & Decoupling
    # --------------------------------------------------------------------------

    def test_notification_service_has_zero_payment_imports(self):
        """Verifies notification_service does not import payment or donation models."""
        import csr.services.notification_service as ns
        self.assertFalse(hasattr(ns, "RazorpayService"))
        self.assertFalse(hasattr(ns, "MonetaryDonation"))
        self.assertFalse(hasattr(ns, "TaxReceiptRecord"))
        self.assertFalse(hasattr(ns, "Form10BECertificate"))
