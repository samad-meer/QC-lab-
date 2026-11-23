from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("site-admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/", include("lims.urls")),
    path("api/", include("certificates.urls")),
    path("api/", include("execution.urls")),
    path("api/", include("batches.urls")),
    path("api/", include("standards.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("quality.urls")),
    path("api/lab/", include("labrecords.urls")),
    path("api/", include("reports.urls")),
    # Public read-only verification page reached via the QR code on the COA.
    path("verify/", include("certificates.verify_urls")),
]
