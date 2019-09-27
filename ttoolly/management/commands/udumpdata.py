# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
from django.core import serializers
from django.apps import apps
import sys
get_model = apps.get_model


class Command(BaseCommand):

    help = ("Write to file the contents of the database as a fixture with "
            "readable unicode text\n"
            "Example: manage.py udumpdata accounts.User -f /path/to/file")
    args = 'appname.ModelName'

    def add_arguments(self, parser):
        parser.add_argument('labels', metavar='label', nargs='+', help='Models for dump')
        parser.add_argument('-f', '--file', dest='path_to_file', help='Specifies the output file path.', required=True)
        parser.add_argument('--pk', dest='pks', nargs='+', help='Specifies pks of objects')

    def handle(self, *args, **kwargs):
        path_to_file = kwargs.get('path_to_file')

        labels = kwargs.get('labels')
        if len(labels) > 1 and kwargs.get('pks'):
            sys.exit("Multiple models labels can't be used with --pk arguments")
        objects_list = []
        for label in labels:
            app_label, model_label = label.split('.')
            obj_model = get_model(app_label, model_label)

            qs = obj_model.objects.all()
            if kwargs.get('pks'):
                qs = qs.filter(pk__in=kwargs.get('pks'))
            objects_list.extend(qs)

            if 'PolymorphicModelBase' in [b.__name__ for b in obj_model.__class__.__bases__]:
                polymorphic_model = obj_model.polymorphic_ctype.field.model
                polymorphic_model = polymorphic_model if polymorphic_model != obj_model else obj_model
                base_objects_qs = polymorphic_model.base_objects.filter(
                    pk__in=qs.values_list('pk', flat=True))
                objects_list.extend(base_objects_qs)

        text = serializers.serialize('json',
                                     objects_list, indent=4, ensure_ascii=False,
                                     use_natural_foreign_keys=True)

        with open(path_to_file, 'ab') as f:
            f.write(text.encode('utf-8'))
