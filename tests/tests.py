# coding: utf-8
from django.test.testcases import TestCase
from ttoolly.models import FormAddTestMixIn, FormAddFileTestMixIn
from .models import SomeModel
from ttoolly.utils import get_random_image

class TestTest(FormAddTestMixIn, FormAddFileTestMixIn, TestCase):

    choice_fields_with_value_in_error = ('many_related_fields',)
    default_params = {'text_field': u'йцу',
                      'many_related_field': [],
                      'file_field': get_random_image(),
                      'int_field': 123,
                      'digital_field': 1.2,
                      'unique_int_field': 24,
                      'email_field': 'test@test.test',
                      'char_field': u'йцуу'}

    file_fields_params = {'file_field': {}}           
    max_fields_length = (('char_field', 120),)
    obj = SomeModel

    required_fields = ('int_field',)
    unique_fields = ('unique_int_field', )
    url_add = '/test-url/'
    with_files = True
