"""
The product master: what each product is, kept in one place. The front desk
picks from it; samples, batches, specifications and certificates all hang
off it. Products are never deleted, because records point at them: one no
longer made is deactivated and stops being offered.
"""
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts.authz import has_perm
from audit.services import record
from qclab.listing import filter_by_text, paginated
from reports.list_export import Col, ListExport
from standards.models import CertificateTemplate
from .models import Product, SampleType, Section


def _section_name(code: str) -> str:
    section = Section.objects.filter(code=code).first()
    return section.name if section else code


# Read from the same payload the screen draws, so the file and the list agree.
PRODUCT_EXPORT = ListExport(
    key="products",
    title="Products",
    columns=[
        Col("Code", lambda p: p["code"], 0.8),
        Col("Product", lambda p: p["name"], 1.7),
        Col("Generic name", lambda p: p["generic_name"], 1.4),
        Col("Dosage form", lambda p: p["dosage_form"], 0.9),
        Col("Strength", lambda p: p["strength"], 0.8),
        Col("Section", lambda p: p["section_name"], 1.1),
        Col("Sample type", lambda p: p["sample_type_label"], 0.9),
        Col("Specification", lambda p: f"v{p['current_spec_version']}" if p["current_spec_version"] else "None effective", 0.9),
        Col("QC stages", lambda p: p["qc_stage_count"], 0.6),
        Col("Batches", lambda p: p["batch_count"], 0.6),
        Col("Samples", lambda p: p["sample_count"], 0.6),
        Col("Status", lambda p: "Active" if p["is_active"] else "Inactive", 0.7),
    ],
    filters={"q": "Search", "section": ("Section", _section_name), "active": ("Showing", lambda _: "Active only")},
    rows=lambda records, request: [product_payload(p) for p in records],
)

TEXT_FIELDS = {
    "name": 200, "generic_name": 200, "dosage_form": 60, "strength": 60, "pack_size": 60, "storage_condition": 120,
}


def _bad(message: str):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def product_payload(p: Product) -> dict:
    spec = p.current_specification()
    plan = p.current_stage_plan()
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "generic_name": p.generic_name,
        "section_id": p.section_id,
        "section": p.section.code,
        "section_name": p.section.name,
        "sample_type": p.sample_type,
        "sample_type_label": p.get_sample_type_display() if p.sample_type else "",
        "dosage_form": p.dosage_form,
        "strength": p.strength,
        "pack_size": p.pack_size,
        "storage_condition": p.storage_condition,
        "shelf_life_months": p.shelf_life_months,
        "is_active": p.is_active,
        "certificate_template_id": p.certificate_template_id,
        "current_spec_version": spec.version if spec else None,
        # How many QC stages a batch created now goes through; 0 when none are set up.
        "qc_stage_count": plan.stages.count() if plan else 0,
        "sample_count": getattr(p, "sample_count", None),
        "batch_count": getattr(p, "batch_count", None),
    }


def _clean(data: dict) -> dict:
    """The fields sent, validated. Raises ValueError with a readable message."""
    out = {}
    for field, limit in TEXT_FIELDS.items():
        if field in data:
            value = (data.get(field) or "").strip()
            if len(value) > limit:
                raise ValueError(f"Keep the {field.replace('_', ' ')} under {limit} characters.")
            out[field] = value
    if "name" in out and not out["name"]:
        raise ValueError("Give the product a name.")
    if "sample_type" in data:
        kind = data.get("sample_type") or ""
        if kind and kind not in SampleType.values:
            raise ValueError("Choose a listed sample type.")
        out["sample_type"] = kind
    if "shelf_life_months" in data:
        raw = data.get("shelf_life_months")
        if raw in (None, ""):
            out["shelf_life_months"] = None
        else:
            try:
                months = int(raw)
            except (TypeError, ValueError):
                raise ValueError("The shelf life must be a whole number of months.")
            if not 1 <= months <= 600:
                raise ValueError("The shelf life must be between 1 and 600 months.")
            out["shelf_life_months"] = months
    if "is_active" in data:
        out["is_active"] = bool(data.get("is_active"))
    if "certificate_template_id" in data:
        raw = data.get("certificate_template_id")
        out["certificate_template_id"] = None
        if raw not in (None, ""):
            template = CertificateTemplate.objects.filter(pk=raw if str(raw).isdigit() else 0).first()
            if template is None:
                raise ValueError("Choose a listed certificate template.")
            out["certificate_template_id"] = template.id
    return out


@api_view(["GET", "POST"])
def product_master(request):
    if request.method == "GET":
        qs = Product.objects.select_related("section").annotate(
            sample_count=Count("samples", distinct=True), batch_count=Count("batches", distinct=True),
        )
        section = request.query_params.get("section")
        if section:
            qs = qs.filter(section__code=section)
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        qs = filter_by_text(request, qs, ["code", "name", "generic_name", "dosage_form", "strength"])
        return paginated(
            request, qs.order_by("-is_active", "name", "id"), lambda rows: [product_payload(p) for p in rows],
            export=PRODUCT_EXPORT,
            sample_types=[{"key": k, "label": v} for k, v in SampleType.choices],
            can_manage=has_perm(request.user, "product.manage"),
        )

    if not has_perm(request.user, "product.manage"):
        return Response({"detail": "You do not have permission to manage products."}, status=status.HTTP_403_FORBIDDEN)
    code = (request.data.get("code") or "").strip()
    if not code:
        return _bad("Give the product a code.")
    if len(code) > 30:
        return _bad("Keep the product code under 30 characters.")
    if Product.objects.filter(code__iexact=code).exists():
        return _bad(f"A product with the code {code} already exists.")
    section = Section.objects.filter(pk=request.data.get("section_id") or 0).first()
    if section is None:
        return _bad("Choose a section.")
    try:
        fields = _clean(request.data)
    except ValueError as e:
        return _bad(str(e))
    if not fields.get("name"):
        return _bad("Give the product a name.")
    product = Product.objects.create(code=code, section=section, **fields)
    record(request.user, "PRODUCT_CREATED", "product", product.code, name=product.name, section=section.code)
    return Response(product_payload(product), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
def product_master_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related("section"), pk=pk)
    if request.method == "GET":
        return Response(product_payload(product))

    if not has_perm(request.user, "product.manage"):
        return Response({"detail": "You do not have permission to manage products."}, status=status.HTTP_403_FORBIDDEN)
    reason = (request.data.get("reason") or "").strip()[:500]
    if not reason:
        return _bad("Say why the product is being changed — it stays on the record.")
    try:
        fields = _clean(request.data)
    except ValueError as e:
        return _bad(str(e))
    changed = {f: v for f, v in fields.items() if getattr(product, f) != v}
    if not changed:
        return Response(product_payload(product))
    if "certificate_template_id" in changed and not has_perm(request.user, "template.manage"):
        return Response({"detail": "You do not have permission to choose certificate templates."},
                        status=status.HTTP_403_FORBIDDEN)
    before = {f: getattr(product, f) for f in changed}
    for field, value in changed.items():
        setattr(product, field, value)
    product.save(update_fields=list(changed))
    record(request.user, "PRODUCT_UPDATED", "product", product.code, reason=reason, before=before, after=changed)
    return Response(product_payload(product))
