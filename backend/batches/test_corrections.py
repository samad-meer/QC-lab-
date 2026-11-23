"""A correction reaches work not yet signed, and never slips past a signed certificate."""
from certificates.models import Certificate
from lims.models import Sample
from .tests import TraceTestBase


class CorrectionAndCertificateTests(TraceTestBase):
    def in_review(self):
        sample = self.registered(expiry_date="2028-01-31")
        self.enter_results(sample)
        self.sign_analyst(sample)
        sample.refresh_from_db()
        return sample

    def test_a_certificate_in_review_is_not_left_with_a_known_mistake(self):
        sample = self.in_review()
        r = self.patch_batch(sample.batch, expiry_date="2027-01-31", reason="Wrong year")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Send it back first", r.data["detail"])
        sample.batch.refresh_from_db()
        self.assertEqual(str(sample.batch.expiry_date), "2028-01-31")

    def test_a_detail_the_certificate_does_not_carry_can_still_change(self):
        sample = self.in_review()
        r = self.patch_batch(sample.batch, notes="Stored in bay 4", reason="Added")
        self.assertEqual(r.status_code, 200, r.content)

    def test_after_a_send_back_the_correction_reaches_the_sample(self):
        sample = self.in_review()
        cert = Certificate.objects.get(sample=sample)
        self.assertEqual(self.send_back(cert, self.checker, "Expiry is wrong").status_code, 200)
        r = self.patch_batch(sample.batch, expiry_date="2027-01-31", reason="Wrong year")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(str(Sample.objects.get(pk=sample.pk).expiry_date), "2027-01-31")
