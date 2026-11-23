from django.urls import path

from . import api, prints

urlpatterns = [
    path("test-templates/", api.test_templates),
    path("test-templates/<str:code>/versions/", api.test_template_version),
    path("products/<int:pk>/specifications/", api.product_specifications),
    path("specifications/<int:pk>/", api.draft_specification),
    path("specifications/<int:pk>/approve/", api.approve_specification),
    path("specifications/<int:pk>/review-date/", api.specification_review_date),
    path("certificate-templates/", api.certificate_templates),
    path("certificate-templates/<int:pk>/", api.certificate_template_detail),
    path("samples/<int:pk>/label/", prints.sample_label),
    path("samples/<int:pk>/record/", prints.sample_record),
    path("batches/<int:pk>/label/", prints.batch_label),
    path("batches/<int:pk>/record/", prints.batch_record),
]
