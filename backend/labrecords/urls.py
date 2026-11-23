from django.urls import path

from . import api

urlpatterns = [
    path("registers/", api.registers),
    path("result-options/", api.result_options),
    path("method-choices/", api.method_choices),
    path("samples/<int:pk>/custody/", api.custody),
    path("<slug:key>/", api.register),
    path("<slug:key>/<int:pk>/", api.record_detail),
    path("<slug:key>/<int:pk>/<slug:action>/", api.act),
]
