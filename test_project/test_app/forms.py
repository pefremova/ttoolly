# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os

from django import forms

from test_project.test_app.models import SomeModel


class SomeModelForm(forms.ModelForm):
    allowed_extensions = ('jpg', 'jpeg', 'png')

    class Meta:
        model = SomeModel
        fields = '__all__'

    def clean_image_field(self):
        value = self.cleaned_data.get('image_field')
        if value:
            ext = os.path.splitext(value.name)[1][1:].lower()
            if ext not in self.allowed_extensions:
                raise forms.ValidationError('Загрузите правильное изображение. Файл, который вы загрузили, '
                                            'поврежден или не является изображением.')
        return value
