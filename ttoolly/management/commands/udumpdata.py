# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
from ttoolly.utils import unicode_to_readable
from django.core import serializers
from optparse import make_option
from django.apps import apps
get_model = apps.get_model


class Command(BaseCommand):

    help = ("Write to file the contents of the database as a fixture with "
            "readable unicode text\n"
            "Example: manage.py udumpdata accounts.User -f /path/to/file")
    args = 'appname.ModelName'

    def add_arguments(self, parser):
        parser.add_argument('label')
        parser.add_argument('-f', '--file', dest='path_to_file', help='Specifies the output file path.', required=True)
        parser.add_argument('--pk', dest='pks', nargs='+', help='Specifies pks of objects')

    def handle(self, *label, **kwargs):
        path_to_file = kwargs.get('path_to_file')
        app_label, model_label = kwargs.get('label').split('.')
        obj_model = get_model(app_label, model_label)
        qs = obj_model.objects.all()
        if kwargs.get('pks'):
            qs = qs.filter(pk__in=kwargs.get('pks'))
        text = unicode_to_readable(serializers.serialize('json',
                                                         qs, indent=4,
                                                         use_natural_foreign_keys=True))
        with open(path_to_file, 'ab') as f:
            f.write(text.encode('utf-8'))
