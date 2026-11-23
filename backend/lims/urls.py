from django.urls import path

from . import products_api, sections_api, sources_api, views, workflow_api

urlpatterns = [
    path("section-master/", sections_api.section_master),
    path("section-master/<int:pk>/", sections_api.section_detail),
    path("sample-sources/", sources_api.sample_sources),
    path("sample-source-master/", sources_api.source_master),
    path("sample-source-master/<int:pk>/", sources_api.source_detail),
    path("workflows/", workflow_api.workflows),
    path("workflows/<int:pk>/", workflow_api.workflow_detail),
    path("workflows/<int:pk>/stages/", workflow_api.workflow_stages),
    path("workflows/<int:pk>/history/", workflow_api.workflow_history),
    path("products/<int:pk>/workflow/", workflow_api.product_workflow),
    path("sections/", views.sections),
    path("products/", views.products),
    path("product-master/", products_api.product_master),
    path("product-master/<int:pk>/", products_api.product_master_detail),
    path("analysts/", views.analysts),
    path("summary/", views.summary),
    path("samples/", views.samples),
    path("samples/<int:pk>/", views.sample_detail),
    path("samples/<int:pk>/results/", views.enter_result),
]
