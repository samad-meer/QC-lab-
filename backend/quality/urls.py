from django.urls import path

from . import api

urlpatterns = [
    path("investigations/", api.investigations),
    path("investigations/options/", api.options),
    path("investigations/<int:pk>/", api.investigation_detail),
    path("investigations/<int:pk>/actions/", api.add_action),
    path("investigations/<int:pk>/actions/<int:action_id>/complete/", api.complete_action),
    path("investigations/<int:pk>/actions/<int:action_id>/verify/", api.verify_action),
    path("investigations/<int:pk>/submit/", api.submit),
    path("investigations/<int:pk>/return/", api.send_back),
    path("investigations/<int:pk>/close/", api.close),
    path("investigations/<int:pk>/lab-finding/", api.lab_finding),
    path("samples/<int:pk>/close/", api.close_sample),
    path("quality-rules/", api.quality_rules),
]
