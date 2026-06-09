from django.urls import path

from . import views

app_name = "chatbot"

urlpatterns = [
    path("", views.index, name="index"),
    path("ask/", views.ask, name="ask"),
]
