from django.urls import path

from . import api, rules_api

urlpatterns = [
    path("notifications/", api.notifications),
    path("notifications/read-all/", api.mark_all_read),
    path("notifications/<int:pk>/read/", api.mark_read),
    path("notification-rules/", rules_api.notification_rules),
    path("notification-rules/test-email/", rules_api.test_email),
    path("notification-rules/<str:event>/", rules_api.notification_rule),
]
