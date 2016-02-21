# -*- coding: utf-8
from ttoolly.models import FormAddTestMixIn, FormEditTestMixIn, FormDeleteTestMixIn
from django.test import TestCase
from test_project.test_app.models import SomeModel


class TestSomeModel(FormAddTestMixIn, FormEditTestMixIn, FormDeleteTestMixIn, TestCase):
    
    all_fields = ('foreign_key_field', 'unique_int_field', 'int_field', 'email_field', 'char_field', 'file_field',
                  'datetime_field', 'date_field', 'text_field', 'digital_field', 'many_related_field', 'image_field',
                  'bool_field')
    choice_fields = ('foreign_key_field',)
    custom_error_messages = {}
    default_params = {'digital_field': 1.56,
                      'int_field': 34,
                      'email_field': '',
                      'unique_int_field': 5}
    fixtures = ('tests/fixture.json',)
    int_fields = ('unique_int_field', 'int_field')
    max_fields_length = (('char_field', 120),)
    multiselect_fields = ('many_related_field',)
    obj = SomeModel
    required_fields = ('digital_field', 'int_field')
    unique_fields = ('unique_int_field', )
    url_add = 'somemodel-create'
    url_delete = 'somemodel-delete'
    url_edit = 'somemodel-update'
    
    
    
