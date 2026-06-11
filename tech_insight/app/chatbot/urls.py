from django.urls import path

from . import views, news_api

app_name = "chatbot"

urlpatterns = [
    path("", views.index, name="index"),
    path("ask/", views.ask, name="ask"),
    path("ask-stream/", views.ask_stream, name="ask_stream"),
    path("news/", views.news, name="news"),
    # 뉴스 Discovery API
    path("api/rss-feeds/", news_api.feeds, name="rss_feeds"),
    path("api/rss/<int:feed_id>/", news_api.feed_items, name="rss_items"),
    path("api/add-news/", news_api.add_news, name="add_news"),
]
