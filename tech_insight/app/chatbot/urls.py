from django.urls import path

from . import views

app_name = "chatbot"

urlpatterns = [
    path("", views.index, name="index"),
    path("ask/", views.ask, name="ask"),
    path("ask-stream/", views.ask_stream, name="ask_stream"),
]
