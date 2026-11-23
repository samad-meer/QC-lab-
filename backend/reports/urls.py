from django.urls import path

from . import api

urlpatterns = [
    path("reports/", api.catalogue),
    path("reports/dashboard/", api.dashboard_view),
    path("reports/documents/sample/<int:pk>/", api.sample_history),
    path("reports/documents/batch/<int:pk>/", api.batch_summary),
    path("reports/documents/product/<int:pk>/", api.product_history),
    path("reports/<slug:key>/definition/", api.report_definition),
    path("reports/<slug:key>/export/", api.report_export),
    path("reports/<slug:key>/", api.report_page),
]
