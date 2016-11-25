# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.http import HttpResponse
from django.views.generic.edit import CreateView, UpdateView, DeleteView

from test_project.test_app.forms import SomeModelForm
from test_project.test_app.models import SomeModel


class SomeModelCreateView(CreateView):
    model = SomeModel
    form_class = SomeModelForm
    template_name = 'someform.html'
    success_url = '.'


class SomeModelUpdateView(UpdateView):
    model = SomeModel
    form_class = SomeModelForm
    template_name = 'someform.html'
    success_url = '.'


class SomeModelDeleteView(DeleteView):
    model = SomeModel
    template_name = 'confirm_delete.html'
    success_url = '.'

    def delete(self, request, *args, **kwargs):
        super(SomeModelDeleteView, self).delete(request, *args, **kwargs)
        return HttpResponse()
