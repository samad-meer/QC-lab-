from django.urls import path

from . import views

urlpatterns = [
    path("samples/<int:pk>/sign-analyst/", views.sign_analyst_view),
    path("certificates/<int:pk>/", views.certificate_detail),
    path("certificates/<int:pk>/sign/", views.sign_view),
    path("certificates/<int:pk>/return/", views.return_view),
    path("certificates/<int:pk>/withdraw/", views.withdraw_view),
    path("certificates/<int:pk>/print/", views.print_view_post),
    path("certificates/<int:pk>/print-view/", views.print_view_get),
]
