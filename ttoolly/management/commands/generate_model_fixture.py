# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, absolute_import
from django.core.management.base import BaseCommand
from ttoolly.utils import unicode_to_readable, generate_random_obj
from django.core import serializers
from optparse import make_option

from django.apps import apps
get_model = apps.get_model


class Command(BaseCommand):

    help = ("Write to file the contents of the database as a fixture with "
            "readable unicode text")
    args = 'appname.ModelName'

    def add_arguments(self, parser):
        parser.add_argument('label', metavar='app_label.ModelName')
        parser.add_argument('-f', '--file', dest='path_to_file', default=None,
                            help='Specifies the output file path.')
        parser.add_argument('-r', '--random_text_file', dest='path_to_random_file', default=None,
                            help='Specifies the file with some text for generate random object.')

    def handle(self, *label, **kwargs):
        path_to_file = kwargs.get('path_to_file')
        app_label, model_label = kwargs.get('label').split('.')
        obj_model = get_model(app_label, model_label)
        obj = generate_random_obj(obj_model, filename=kwargs.get('path_to_random_file'), with_save=False)

        """Объект создается без сохранения, поэтому исключаем m2m"""
        fields = [f.name for f in set(obj_model._meta.fields).difference(obj_model._meta.many_to_many)]

        text = unicode_to_readable(
            serializers.serialize('json', [obj, ], indent=4, use_natural_foreign_keys=True, fields=fields))

        if path_to_file:
            with open(path_to_file, 'ab') as f:
                f.write(text.encode('utf-8'))
        else:
            print(text)
