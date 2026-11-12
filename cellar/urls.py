from django.urls import path

from . import views

urlpatterns = [
    path("", views.cellar, name="cellar"),
    path("wines/", views.wines, name="wines"),
    path("wines/add/", views.wine_create, name="wine_create"),
    path("wines/<int:pk>/edit/", views.wine_edit, name="wine_edit"),
    path("wines/<int:pk>/retire/", views.wine_retire, name="wine_retire"),
    path("wines/<int:pk>/", views.wine_detail, name="wine_detail"),
    path("wines/<int:pk>/consume/", views.consume, name="consume"),
    path("bottles/add/", views.bottle_add, name="bottle_add"),
    path("bottles/<int:pk>/edit/", views.bottle_edit, name="bottle_edit"),
    path("timeline/", views.timeline, name="timeline"),
    path("settings/", views.settings_page, name="settings"),
    path("settings/locations/<int:pk>/", views.location_edit, name="location_edit"),
]
