from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import urlencode


class CellarLoginRequiredMiddleware(LoginRequiredMiddleware):
    def handle_no_permission(self, request, view_func):
        if request.method == "POST" or request.headers.get("HX-Request") == "true":
            next_url = request.get_full_path()
            # Card consumption has no GET page; return to the cards where its saved form can retry.
            if request.resolver_match.url_name == "consume":
                next_url = reverse("cellar")
                if request.GET:
                    next_url += "?" + request.GET.urlencode()
            elif request.resolver_match.url_name == "logout":
                next_url = reverse("settings")
            login_url = reverse("login") + "?" + urlencode({"next": next_url})
            # Values remain readable even without JavaScript. Passwords and tokens are excluded.
            draft = [
                (key, value)
                for key, values in request.POST.lists()
                if key not in {"csrfmiddlewaretoken", "token"} and "password" not in key.lower()
                for value in values
            ]
            response = render(
                request,
                "registration/session_expired.html",
                {
                    "login_url": login_url,
                    "draft": draft,
                },
                status=401,
            )
            if request.headers.get("HX-Request") == "true":
                response["HX-Retarget"] = "body"
                response["HX-Reswap"] = "innerHTML"
            return response
        return super().handle_no_permission(request, view_func)


class ResponseSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
            "form-action 'self'"
        )
        response["Referrer-Policy"] = "same-origin"
        if not request.path.startswith("/static/"):
            response["Cache-Control"] = "no-store"
        return response
