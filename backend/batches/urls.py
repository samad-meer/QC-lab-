from django.urls import path

from . import api

urlpatterns = [
    path("batches/", api.batches),
    path("batches/lookup/", api.lookup),
    path("batches/<int:pk>/", api.batch_detail),
    path("batches/<int:pk>/disposition/", api.disposition),
    path("batches/<int:pk>/qc-stages/", api.add_stage),
    path("batches/<int:pk>/qc-stages/<int:stage_id>/record/", api.record_stage),
    path("batches/<int:pk>/qc-stages/<int:stage_id>/applicability/", api.stage_applicability),
    path("batches/<int:pk>/qc-stages/<int:stage_id>/entries/", api.stage_entries),
    path("batches/<int:pk>/qc-stages/<int:stage_id>/sign/", api.stage_sign),
    path("batches/<int:pk>/qc-stages/<int:stage_id>/assign/", api.stage_assign),
    path("products/<int:pk>/qc-stages/", api.product_stages),
    path("products/<int:pk>/qc-stages/versions/<int:version>/", api.product_stage_version),
    path("checkpoint-kinds/", api.checkpoint_presets),
    path("checkpoint-kinds/in-use/", api.checkpoint_kinds_in_use),
    path("checkpoint-kinds/<int:pk>/", api.checkpoint_preset_detail),
    path("batches/<int:pk>/documents/", api.documents),
    path("batch-record-files/<int:pk>/", api.record_file),
    path("batch-documents/<int:pk>/", api.document_file),
    path("batch-documents/<int:pk>/withdraw/", api.document_withdraw),
    path("batch-numbering/", api.numbering_rule),
]
