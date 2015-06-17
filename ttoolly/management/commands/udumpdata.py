# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
from ttoolly.utils import unicode_to_readable
from django.core import serializers
from django.db.models import get_model
from optparse import make_option


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('-f', '--file', dest='path_to_file',
            help='Specifies the output file path.'),)

    help = ("Write to file the contents of the database as a fixture with "
            "readable unicode text")
    args = 'appname.ModelName'

    def handle(self, *label, **kwargs):
        path_to_file = kwargs.get('path_to_file')
        app_label, model_label = label[0].split('.')
        obj_model = get_model(app_label, model_label)
        text = unicode_to_readable(serializers.serialize('json',
                    obj_model.objects.all(), indent=4, use_natural_keys=True))
        f = open(path_to_file, 'a')
        f.write(text)
        f.close()
