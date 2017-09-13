# -*- coding: utf-8
from __future__ import unicode_literals

import os

from django.core.files.base import ContentFile
from django.test import TestCase
from test_project.test_app.models import SomeModel, OtherModel
from ttoolly.models import (FormAddTestMixIn, FormEditTestMixIn, FormDeleteTestMixIn)
from ttoolly.utils import FILE_TYPES


class TestSomeModel(FormAddTestMixIn, FormEditTestMixIn, FormDeleteTestMixIn, TestCase):

    all_fields = ('foreign_key_field', 'unique_int_field', 'int_field', 'email_field', 'char_field', 'file_field',
                  'datetime_field', 'date_field', 'text_field', 'digital_field', 'many_related_field', 'image_field',
                  'bool_field', 'one_to_one_field', 'one_to_one_field2')
    choice_fields = ('foreign_key_field', 'one_to_one_field', 'one_to_one_field2')
    custom_error_messages = {'image_field': {'wrong_extension': [
        'Загрузите правильное изображение. Файл, который вы загрузили, поврежден или не является изображением.']}}
    datetime_fields = ('datetime_field',)
    default_params = {'digital_field': 1.56,
                      'int_field': 34,
                      'email_field': '',
                      'unique_int_field': 5}
    file_fields_params = {'image_field': {'extensions': ('jpg', 'jpeg', 'png')},
                          'file_field': {}}
    fixtures = ('tests/fixture.json',)
    int_fields = ('unique_int_field', 'int_field')
    max_decimal_places = {'digital_field': 2}
    max_fields_length = {'char_field': 120,
                         'digital_field': 250.1,
                         'email_field': 254,
                         'file_field': 100,
                         'image_field': 100,
                         'int_field': 500,
                         'unique_int_field': 9999999}
    min_fields_length = {'digital_field': -100.5,
                         'int_field': -5,
                         'unique_int_field': 0}
    multiselect_fields = ('many_related_field',)
    obj = SomeModel
    required_fields = ('digital_field', 'int_field')
    unique_fields = ('unique_int_field', )
    url_add = 'somemodel-create'
    url_delete = 'somemodel-delete'
    url_edit = 'somemodel-update'

    def get_params_according_to_type(self, value, params_value):
        if isinstance(params_value, FILE_TYPES + (ContentFile,)):
            value, params_value = super(TestSomeModel, self).get_params_according_to_type(value, params_value)
            if len(params_value) == 100:
                name, ext = os.path.splitext(params_value)
                # django replace last 8 symbols in name to random string
                params_value = name[:-(len('tmp/') + 8)] + ext
            return value, params_value
        return super(TestSomeModel, self).get_params_according_to_type(value, params_value)

    def setUp(self):
        other_model_pks = OtherModel.objects.all().values_list('pk', flat=True)
        self.choice_fields_values = {'foreign_key_field': other_model_pks,
                                     'many_related_field': other_model_pks,
                                     'one_to_one_field': other_model_pks,
                                     'one_to_one_field2': self.obj.objects.all().values_list('pk', flat=True)}
