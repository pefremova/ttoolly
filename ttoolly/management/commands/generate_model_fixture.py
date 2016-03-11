# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
from ttoolly.utils import unicode_to_readable, generate_random_obj
from django.core import serializers
from django.db.models import get_model
from optparse import make_option


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('-f', '--file', dest='path_to_file', default=None,
            help='Specifies the output file path.'),
        make_option('-r', '--random_text_file', dest='path_to_random_file', default=None,
            help='Specifies the file with some text for generate random object.'),)

    help = ("Write to file the contents of the database as a fixture with "
            "readable unicode text")
    args = 'appname.ModelName'

    def handle(self, *label, **kwargs):
        path_to_file = kwargs.get('path_to_file')
        app_label, model_label = label[0].split('.')
        obj_model = get_model(app_label, model_label)
        obj = generate_random_obj(obj_model, filename=kwargs.get('path_to_random_file'), with_save=False)
        text = unicode_to_readable(serializers.serialize('json', [obj, ], indent=4, use_natural_keys=True))
        if path_to_file:
            f = open(path_to_file, 'a')
            f.write(text)
            f.close()
        else:
            print text
