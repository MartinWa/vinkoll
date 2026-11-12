import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView
from django.db import connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters

from .models import LoginAttempt


def login_buckets(request):
    # REMOTE_ADDR is the direct peer, never a browser-supplied forwarding header.
    # Behind Caddy this intentionally also bounds aggregate attempts through that proxy.
    values = [
        "ip:" + request.META.get("REMOTE_ADDR", ""),
        "user:" + request.POST.get("username", "").strip().casefold()[:150],
    ]
    return [
        hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()
        for value in values
    ]


@method_decorator(login_not_required, name="dispatch")
@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class ThrottledLoginView(LoginView):
    template_name = "registration/login.html"

    def post(self, request, *args, **kwargs):
        now = timezone.now()
        keys = login_buckets(request)
        with transaction.atomic():
            LoginAttempt.objects.filter(expires_at__lte=now).delete()
            buckets = [
                LoginAttempt.objects.get_or_create(
                    key=key,
                    defaults={
                        "expires_at": now
                        + timedelta(seconds=settings.LOGIN_ATTEMPT_WINDOW_SECONDS),
                    },
                )[0]
                for key in keys
            ]
            if any(bucket.count >= settings.LOGIN_ATTEMPT_LIMIT for bucket in buckets):
                # A bound form would authenticate blocked credentials when the template renders.
                response = self.render_to_response(
                    self.get_context_data(
                        form=self.get_form_class()(request=request), throttled=True
                    ),
                    status=429,
                )
                response["Retry-After"] = str(settings.LOGIN_ATTEMPT_WINDOW_SECONDS)
                return response
            for bucket in buckets:
                bucket.count += 1
                bucket.save(update_fields=["count"])
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        # Keep the IP bucket for its bounded window; reset this successfully verified user.
        LoginAttempt.objects.filter(key=login_buckets(self.request)[1]).delete()
        return super().form_valid(form)


@login_not_required
def health(request):
    # Reachable only on the private Docker network; no accounts, versions or cellar data.
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM django_migrations LIMIT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok"})
