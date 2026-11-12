from django.contrib.auth.views import LogoutView, PasswordChangeView
from django.urls import include, path

from core.views import ThrottledLoginView, health

urlpatterns = [
    path("accounts/login/", ThrottledLoginView.as_view(), name="login"),
    path("accounts/logout/", LogoutView.as_view(), name="logout"),
    path(
        "accounts/password/",
        PasswordChangeView.as_view(
            template_name="registration/password_change_form.html", success_url="/settings/"
        ),
        name="password_change",
    ),
    path("healthz/", health, name="health"),
    path("", include("cellar.urls")),
]
