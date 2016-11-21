# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
from ttoolly.utils import unicode_to_readable
from django.core import serializers
from optparse import make_option
from django.apps import apps
get_model = apps.get_model


class Command(BaseCommand):

    help = ("Write to file the contents of the database as a fixture with "
            "readable unicode text")
    args = 'appname.ModelName'

    def add_arguments(self, parser):
        parser.add_argument('label')
        parser.add_argument('-f', '--file', dest='path_to_file', help='Specifies the output file path.')

    def handle(self, *label, **kwargs):
        path_to_file = kwargs.get('path_to_file')
        app_label, model_label = kwargs.get('label').split('.')
        obj_model = get_model(app_label, model_label)
        text = unicode_to_readable(serializers.serialize('json',
                                                         obj_model.objects.all(), indent=4,
                                                         use_natural_foreign_keys=True))
        f = open(path_to_file, 'a')
        f.write(text)
        f.close()
