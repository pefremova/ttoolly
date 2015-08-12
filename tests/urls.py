from django.conf.urls import patterns

from .views import SomeModelView

urlpatterns = patterns('',
    (r'^test-url/$', SomeModelView.as_view()),
)
