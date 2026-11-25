from django.contrib import admin
from django.urls import path, include

from qcm import views

admin.site.site_header = "Secure QCM – Administration technique"
admin.site.site_title = "Secure QCM"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", views.UnifiedLoginView.as_view(), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("qcm.urls")),
]
