from django.conf.urls import url

from .views import GalleryListView, GalleryDetailView, ImageListView, ImageDetailView

urlpatterns = [
    url(r'^$', GalleryListView.as_view(), name='list'),
    url(r'^(?P<pk>[0-9]+)/?$', GalleryDetailView.as_view(), name='detail'),
    url(r'^(?P<pk_gallery>[0-9]+)/images/?$', ImageListView.as_view(), name='list-images'),
    url(r'^(?P<pk_gallery>[0-9]+)/images/(?P<pk>[0-9]+)?$', ImageDetailView.as_view(), name='detail-image'),
]
