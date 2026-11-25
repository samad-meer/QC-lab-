from django.urls import path

from . import api

urlpatterns = [
    path("tasks/", api.tasks),
    path("samples/<int:pk>/execution/", api.execution),
    path("samples/<int:pk>/checklist/", api.checklist_answer),
    path("samples/<int:pk>/attachments/", api.upload),
    path("samples/<int:pk>/comments/", api.comment),
    path("samples/<int:pk>/candidates/", api.candidates),
    path("samples/<int:pk>/assignments/", api.assignment),
    path("samples/assign-testing/", api.assign_testing),
    path("samples/assign-testing/candidates/", api.testing_candidates),
    path("assign/overview/", api.assign_overview),
    path("samples/<int:pk>/hold/", api.hold),
    path("samples/<int:pk>/retests/", api.retest_request),
    path("samples/<int:pk>/waivers/", api.waive),
    path("samples/<int:pk>/receipt/complete/", api.receipt_complete),
    path("attachments/<int:pk>/", api.attachment_file),
    path("attachments/<int:pk>/withdraw/", api.attachment_withdraw),
    path("assignments/<int:pk>/respond/", api.assignment_respond),
    path("retests/<int:pk>/decide/", api.retest_decide),
]
