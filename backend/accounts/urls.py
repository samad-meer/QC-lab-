from django.urls import path

from . import admin_api, profile_api, sessions_api, views

urlpatterns = [
    path("csrf/", views.csrf),
    path("login/", views.login_view),
    path("logout/", views.logout_view),
    path("me/", views.me),
    path("change-password/", views.change_password),
    path("config/", views.config),
    # Self-service — a user's own record and credential
    path("profile/", profile_api.profile),
    path("profile/photo/", profile_api.profile_photo),
    path("users/<int:pk>/photo/", profile_api.user_photo),
    # Administration
    path("permissions/", admin_api.permissions_catalogue),
    path("roles/", admin_api.roles),
    path("role-options/", admin_api.role_options),
    path("roles/<int:pk>/", admin_api.role_detail),
    path("roles/<int:pk>/permissions/", admin_api.role_permissions),
    path("roles/<int:pk>/history/", admin_api.role_history),
    path("users/", admin_api.users),
    path("users/<int:pk>/", admin_api.user_detail),
    path("users/<int:pk>/reset-password/", admin_api.reset_password),
    path("users/<int:pk>/unlock/", sessions_api.unlock),
    path("sessions/", sessions_api.sessions),
    path("sessions/<str:sid>/end/", sessions_api.end_session),
    path("audit/", admin_api.audit_trail),
    path("audit/reviews/", admin_api.audit_reviews),
    path("analytics/", admin_api.analytics),
    path("lab/", admin_api.lab_config),
    path("lab/features/", admin_api.lab_features),
    path("lab/logo/upload/", admin_api.lab_logo),
    path("lab/logo/", admin_api.lab_logo_file),
]
