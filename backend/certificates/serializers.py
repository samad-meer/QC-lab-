from rest_framework import serializers

from accounts.authz import OVERRIDE, has_perm
from lims.serializers import stage_payload
from lims.workflow import may_sign_stage
from .models import CertStatus, Certificate, PrintEvent, Signature
from .services import awaiting_stage, can_open_copy, review_stages, signature_chain


class SignatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Signature
        fields = ["meaning", "name_snapshot", "signed_at"]


class PrintEventSerializer(serializers.ModelSerializer):
    printed_by_name = serializers.SerializerMethodField()
    can_open = serializers.SerializerMethodField()

    class Meta:
        model = PrintEvent
        fields = ["copy_number", "printed_by_name", "printed_at", "can_open"]

    def get_printed_by_name(self, obj):
        return obj.printed_by.display_name()

    def get_can_open(self, obj):
        """Recorded but never opened, by the person asking, recently: their window closed before it loaded."""
        request = self.context.get("request")
        return bool(request) and can_open_copy(obj, request.user)


class CertificateSerializer(serializers.ModelSerializer):
    signatures = SignatureSerializer(many=True, read_only=True)
    prints = PrintEventSerializer(many=True, read_only=True)
    sample_id = serializers.IntegerField(read_only=True)
    workflow_name = serializers.CharField(source="sample.workflow_version.workflow.name", read_only=True)
    stages = serializers.SerializerMethodField()
    chain = serializers.SerializerMethodField()
    awaiting_stage = serializers.SerializerMethodField()
    my_turn = serializers.SerializerMethodField()
    can_sign = serializers.SerializerMethodField()
    withdrawn_by_name = serializers.SerializerMethodField()
    can_withdraw = serializers.SerializerMethodField()

    class Meta:
        model = Certificate
        fields = [
            "id", "sample_id", "version", "status", "content", "content_hash",
            "verification_uuid", "created_at", "superseded_reason",
            "signatures", "prints", "workflow_name", "stages", "chain",
            "awaiting_stage", "my_turn", "can_sign",
            "withdrawn_at", "withdrawn_reason", "withdrawn_by_name", "can_withdraw",
        ]

    def get_withdrawn_by_name(self, obj):
        return obj.withdrawn_by.display_name() if obj.withdrawn_by_id else None

    def get_can_withdraw(self, obj):
        request = self.context.get("request")
        return bool(request) and obj.status == CertStatus.APPROVED and has_perm(request.user, "cert.withdraw")

    def get_stages(self, obj):
        return [stage_payload(s) for s in review_stages(obj)]

    def get_chain(self, obj):
        """Every signature this certificate needs, in order — signed or not yet."""
        return [
            {
                "code": row["code"],
                "title": row["title"],
                "holder": row["holder"],
                "name_snapshot": row["signature"].name_snapshot if row["signature"] else None,
                "signed_at": row["signature"].signed_at if row["signature"] else None,
            }
            for row in signature_chain(obj)
        ]

    def get_awaiting_stage(self, obj):
        stage = awaiting_stage(obj)
        return stage_payload(stage) if stage else None

    def get_my_turn(self, obj):
        request = self.context.get("request")
        if request is None:
            return False
        stage = awaiting_stage(obj)
        return may_sign_stage(request.user, stage) and not obj.signatures.filter(user=request.user).exists()

    def get_can_sign(self, obj):
        """my_turn is what is waiting on them; this adds what an administrator may step in on."""
        request = self.context.get("request")
        return self.get_my_turn(obj) or bool(
            request is not None and awaiting_stage(obj) is not None and has_perm(request.user, OVERRIDE)
        )
