# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf.urls import url

from test_project.test_app.views import SomeModelCreateView, SomeModelUpdateView, SomeModelDeleteView


urlpatterns = [
    url(r'^somemodel/create/$', SomeModelCreateView.as_view(), name='somemodel-create'),
    url(r'^somemodel/(?P<pk>\d+)/update/$', SomeModelUpdateView.as_view(), name='somemodel-update'),
    url(r'^somemodel/(?P<pk>\d+)/delete/$', SomeModelDeleteView.as_view(), name='somemodel-delete')
]
