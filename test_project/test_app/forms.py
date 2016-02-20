# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django import forms, VERSION

from test_project.test_app.models import SomeModel


class SomeModelForm(forms.ModelForm):
    class Meta:
        model = SomeModel
        if VERSION >= (1, 7):
            fields = '__all__'
