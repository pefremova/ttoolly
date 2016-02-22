# -*- coding: utf-8
from ttoolly.models import (FormAddTestMixIn, FormEditTestMixIn, FormDeleteTestMixIn, FormAddFileTestMixIn,
                            FormEditFileTestMixIn)
from django.test import TestCase
from test_project.test_app.models import SomeModel, OtherModel


class TestSomeModel(FormAddTestMixIn, FormAddFileTestMixIn, FormEditTestMixIn, FormEditFileTestMixIn,
                    FormDeleteTestMixIn, TestCase):
    
    all_fields = ('foreign_key_field', 'unique_int_field', 'int_field', 'email_field', 'char_field', 'file_field',
                  'datetime_field', 'date_field', 'text_field', 'digital_field', 'many_related_field', 'image_field',
                  'bool_field')
    choice_fields = ('foreign_key_field',)
    default_params = {'digital_field': 1.56,
                      'int_field': 34,
                      'email_field': '',
                      'unique_int_field': 5}
    file_fields_params = {'image_field': {'extensions': ('jpg', 'jpeg', 'png')},
                          'file_field': {}}
    fixtures = ('tests/fixture.json',)
    int_fields = ('unique_int_field', 'int_field')
    max_fields_length = (('char_field', 120),
                         ('digital_field', 250.1),
                         ('int_field', 500),
                         ('unique_int_field', 9999999))
    min_fields_length = (('digital_field', -100.5),
                         ('int_field', -5),
                         ('unique_int_field', 0))
    multiselect_fields = ('many_related_field',)
    obj = SomeModel
    required_fields = ('digital_field', 'int_field')
    unique_fields = ('unique_int_field', )
    url_add = 'somemodel-create'
    url_delete = 'somemodel-delete'
    url_edit = 'somemodel-update'
    
    def setUp(self):
        other_model_pks = OtherModel.objects.all().values_list('pk', flat=True)
        self.choice_fields_values = {'foreign_key_field': other_model_pks,
                                     'many_related_field': other_model_pks}
    
    
