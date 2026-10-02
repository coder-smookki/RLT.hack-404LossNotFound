from django.urls import path, re_path
from api import views
urlpatterns = [
    path('api/v1/auth/<str:action>', views.auth),
    re_path(r'^api/v1/(?P<path>.*)$', views.resource),
    re_path(r'^(?P<path>.*)$', views.frontend),
]
handler400 = 'api.views.bad_request'
handler404 = 'api.views.not_found'
handler500 = 'api.views.server_error'
