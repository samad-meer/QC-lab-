from django.urls import path

from . import views

urlpatterns = [
    path("<uuid:uuid>/", views.verify),
]
