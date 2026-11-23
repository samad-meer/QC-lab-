from datetime import timedelta

from rest_framework import serializers

from accounts.authz import OVERRIDE, has_perm
from labrecords.rawdata import payload as raw_data_payload
from .evaluation import reported_value
from .models import (
    Product,
    Sample,
    SampleSource,
    SampleStatus,
    Section,
    Specification,
    TestDefinition,
    TestResult,
    WorkflowEvent,
)


def stage_payload(stage) -> dict:
    """One review stage as every screen shows it."""
    return {
        "order": stage.order,
        "code": stage.code,
        "name": stage.name,
        "signature_title": stage.signature_title,
        "holder_title": stage.holder_title,
        "holder": stage.holder,
        "role_id": stage.role_id,
        "role_name": stage.role.name,
        "requires_acceptance": stage.requires_acceptance,
    }


def workflow_version_payload(version) -> dict | None:
    if version is None:
        return None
    return {
        "id": version.workflow_id,
        "name": version.workflow.name,
        "version": version.version,
        "stages": [stage_payload(s) for s in version.stages.select_related("role")],
        # How many checks the front desk makes on arrival, before testing can start.
        "receipt_checks": version.checklist.filter(stage__isnull=True, for_receipt=True).count(),
    }


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = ["id", "code", "name"]


class TestDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestDefinition
        fields = [
            "id", "order", "name", "method", "method_record", "unit", "limit_type",
            "min_value", "max_value", "decimals", "text_expected", "limit_text",
        ]


class SpecificationSerializer(serializers.ModelSerializer):
    tests = TestDefinitionSerializer(many=True, read_only=True)

    class Meta:
        model = Specification
        # stage_name is set when these are one QC stage's own tests; label says which, in words.
        fields = ["id", "version", "status", "effective_date", "stage_name", "label", "tests"]


class ProductSerializer(serializers.ModelSerializer):
    section = serializers.SlugRelatedField(slug_field="code", read_only=True)
    current_spec_version = serializers.SerializerMethodField()
    workflow = serializers.SerializerMethodField()
    qc_stages = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "code", "name", "section", "current_spec_version", "workflow",
            "dosage_form", "strength", "storage_condition", "qc_stages",
        ]

    def get_current_spec_version(self, obj):
        spec = obj.current_specification()
        return spec.version if spec else None

    def get_qc_stages(self, obj):
        """
        The stages a sample of a new batch can be registered for, with the tests each
        gets and what it waits for. A known batch has its own.
        """
        from batches.stages import registration_options

        return registration_options(obj, None)

    def get_workflow(self, obj):
        """The review chain a sample registered now would be bound to."""
        workflow = obj.review_workflow()
        return workflow_version_payload(workflow.current_version()) if workflow else None


class TestResultSerializer(serializers.ModelSerializer):
    test_definition_id = serializers.IntegerField(source="test_definition.id", read_only=True)
    test_name = serializers.CharField(source="test_definition.name", read_only=True)
    limit_text = serializers.CharField(source="test_definition.limit_text", read_only=True)
    unit = serializers.CharField(source="test_definition.unit", read_only=True)
    reported = serializers.SerializerMethodField()
    entered_by_name = serializers.SerializerMethodField()
    superseded_by_name = serializers.SerializerMethodField()
    raw_data = serializers.SerializerMethodField()

    class Meta:
        model = TestResult
        fields = [
            "id", "test_definition_id", "test_name", "limit_text", "unit",
            "value_numeric", "value_text", "reported", "outcome",
            "entered_by_name", "entered_at",
            "is_superseded", "superseded_at", "superseded_by_name", "supersede_reason", "raw_data",
        ]

    def get_reported(self, obj):
        return reported_value(obj)

    def get_raw_data(self, obj):
        return raw_data_payload(obj)

    def get_entered_by_name(self, obj):
        return obj.entered_by.display_name()

    def get_superseded_by_name(self, obj):
        return obj.superseded_by_user.display_name() if obj.superseded_by_user else None


class WorkflowEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowEvent
        fields = ["id", "at", "actor_name", "from_status", "to_status", "comment"]

    def get_actor_name(self, obj):
        return obj.actor.display_name()


class SampleListSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    section_code = serializers.CharField(source="section.code", read_only=True)
    analyst_name = serializers.SerializerMethodField()
    has_failures = serializers.SerializerMethodField()
    status_label = serializers.CharField(read_only=True)
    review_stage_order = serializers.SerializerMethodField()
    my_turn = serializers.SerializerMethodField()
    can_sign = serializers.SerializerMethodField()
    batch_label = serializers.CharField(read_only=True)

    class Meta:
        model = Sample
        fields = [
            "id", "sample_no", "product_name", "product_code", "section_code",
            "batch_id", "batch_no", "batch_label", "reference", "due_date", "status", "status_label",
            "review_stage_order", "my_turn", "can_sign", "analyst_name", "assigned_analyst_id", "received_at", "has_failures",
        ]

    def get_analyst_name(self, obj):
        return obj.assigned_analyst.display_name()

    def get_has_failures(self, obj):
        return obj.has_failures()

    def get_review_stage_order(self, obj):
        return obj.review_stage.order if obj.review_stage_id else None

    def get_my_turn(self, obj):
        """Waiting at a stage the caller's role signs. (Signing again is still refused.)"""
        from .workflow import may_sign_stage

        request = self.context.get("request")
        return bool(
            request is not None
            and obj.status == SampleStatus.IN_REVIEW
            and may_sign_stage(request.user, obj.review_stage)
        )

    def get_can_sign(self, obj):
        """my_turn is what is waiting on them; this adds what an administrator may step in on."""
        request = self.context.get("request")
        return self.get_my_turn(obj) or bool(
            request is not None and obj.status == SampleStatus.IN_REVIEW and has_perm(request.user, OVERRIDE)
        )


class SampleDetailSerializer(SampleListSerializer):
    specification = SpecificationSerializer(read_only=True)
    results = serializers.SerializerMethodField()
    events = WorkflowEventSerializer(many=True, read_only=True)
    registered_by_name = serializers.SerializerMethodField()
    closed_by_name = serializers.SerializerMethodField()
    investigations = serializers.SerializerMethodField()
    certificates = serializers.SerializerMethodField()
    workflow = serializers.SerializerMethodField()
    batch_internal_id = serializers.CharField(source="batch.internal_id", read_only=True, default="")
    manufacturing_site = serializers.CharField(source="batch.manufacturing_site", read_only=True, default="")
    qc_stage_name = serializers.CharField(source="qc_stage.name", read_only=True, default="")

    class Meta(SampleListSerializer.Meta):
        fields = SampleListSerializer.Meta.fields + [
            "qc_stage_name", "quantity", "received_from", "registered_by_name",
            "manufacturing_date", "expiry_date", "past_expiry_reason", "closed_reason", "closed_at", "closed_by_name",
            "investigations",
            "storage_condition", "batch_internal_id", "manufacturing_site",
            "specification", "results", "events", "certificates", "workflow",
        ]

    def get_workflow(self, obj):
        """The version bound at registration — never the workflow as edited since."""
        return workflow_version_payload(obj.workflow_version)

    def get_results(self, obj):
        return TestResultSerializer(
            obj.results.select_related("test_definition", "entered_by", "superseded_by_user", "raw_data__instrument")
            .prefetch_related("raw_data__materials", "raw_data__readings").all(),
            many=True,
        ).data

    def get_investigations(self, obj):
        return [
            {"id": i.id, "reference": i.reference, "kind": i.get_kind_display(), "status": i.status,
             "status_label": i.get_status_display(), "test_name": i.test_definition.name if i.test_definition_id else "",
             "conclusion": i.get_conclusion_display()}
            for i in obj.investigations.select_related("test_definition").order_by("-opened_at", "-id")
        ]

    def get_closed_by_name(self, obj):
        return obj.closed_by.display_name() if obj.closed_by_id else None

    def get_registered_by_name(self, obj):
        return obj.registered_by.display_name()

    def get_certificates(self, obj):
        return [
            {"id": c.id, "version": c.version, "status": c.status, "created_at": c.created_at}
            for c in obj.certificates.order_by("version")
        ]


class SampleRegisterSerializer(serializers.Serializer):
    """
    Error text is written to be read by the person at the front desk, not by
    a developer: it names the field as it appears on screen and says what is
    wrong with what they typed.
    """

    product_id = serializers.IntegerField(
        error_messages={"required": "Choose a product.", "invalid": "Choose a product."}
    )
    # A sample comes from a batch unless the front desk says it does not.
    from_batch = serializers.BooleanField(required=False, default=True)
    batch_no = serializers.CharField(
        max_length=60, required=False, allow_blank=True,
        error_messages={"max_length": "The batch number cannot be longer than 60 characters."},
    )
    reference = serializers.CharField(
        max_length=200, required=False, allow_blank=True,
        error_messages={"max_length": "Keep this under 200 characters."},
    )
    manufacturing_site = serializers.CharField(
        max_length=120, required=False, allow_blank=True,
        error_messages={"max_length": "Keep the manufacturing site under 120 characters."},
    )
    quantity = serializers.CharField(
        max_length=60,
        error_messages={
            "required": "Enter how much was received, e.g. “60 tablets”.",
            "blank": "Enter how much was received, e.g. “60 tablets”.",
            "max_length": "Keep the quantity under 60 characters.",
        },
    )
    received_from = serializers.CharField(
        max_length=200,
        error_messages={
            "required": "Choose who the sample came from.",
            "blank": "Choose who the sample came from.",
        },
    )
    received_at = serializers.DateTimeField(
        error_messages={
            "required": "Enter the date and time the sample arrived.",
            "invalid": "That is not a valid date and time.",
        }
    )
    due_date = serializers.DateField(
        error_messages={
            "required": "Enter the date the result is due.",
            "invalid": "That is not a valid date. Use the date picker.",
        }
    )
    analyst_id = serializers.IntegerField(
        error_messages={"required": "Choose an analyst.", "invalid": "Choose an analyst."}
    )
    # Optional: a raw material drum may carry no manufacturing date, and an
    # in-process sample has no expiry.
    manufacturing_date = serializers.DateField(
        required=False, allow_null=True,
        error_messages={"invalid": "That is not a valid manufacturing date."},
    )
    expiry_date = serializers.DateField(
        required=False, allow_null=True,
        error_messages={"invalid": "That is not a valid expiry or retest date."},
    )
    storage_condition = serializers.CharField(
        required=False, allow_blank=True, max_length=120,
        error_messages={"max_length": "Keep the storage condition under 120 characters."},
    )
    past_expiry_reason = serializers.CharField(
        required=False, allow_blank=True, max_length=300,
        error_messages={"max_length": "Keep the reason under 300 characters."},
    )
    # The batch's QC stage this sample was taken for, where its product has stages.
    qc_stage_id = serializers.IntegerField(
        required=False, allow_null=True, error_messages={"invalid": "Choose the QC stage."},
    )

    def validate_received_from(self, value):
        # Picked from the lab's list, so one source is never spelled three ways.
        source = SampleSource.objects.filter(is_active=True, name__iexact=" ".join(value.split())).first()
        if source is None:
            raise serializers.ValidationError(
                "Choose a name from the list. If it is not there, ask an administrator to add it."
            )
        return source.name

    def validate_received_at(self, value):
        from django.utils import timezone

        if value > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError("The sample cannot have arrived in the future.")
        return value

    def validate(self, attrs):
        received = attrs.get("received_at")
        due = attrs.get("due_date")
        if received and due and due < received.date():
            raise serializers.ValidationError(
                {"due_date": "The due date cannot be before the sample arrived."}
            )
        if attrs.get("from_batch", True):
            if not (attrs.get("batch_no") or "").strip():
                raise serializers.ValidationError({"batch_no": "Enter the batch or lot number."})
        elif not (attrs.get("reference") or "").strip():
            raise serializers.ValidationError(
                {"reference": "Say what this sample is, e.g. “Purified water, point WP-3”."}
            )
        return attrs
