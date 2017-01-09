# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, absolute_import
from django.core.management.base import BaseCommand
from django.db import models
from optparse import make_option
from ttoolly.utils import prepare_file_for_tests
from django.apps import apps
get_models = apps.get_models


class Command(BaseCommand):

    help = "Create random files for all models, if not exists on file system"

    def add_arguments(self, parser):
        parser.add_argument('--show', dest='show', action="store_true", default=False,
                            help='Only show output, not generate files')

    def handle(self, *args, **kwargs):
        verbosity = int(kwargs.get('verbosity'))
        all_models = get_models(include_auto_created=True)
        models_with_files = {}
        if verbosity:
            print('Found %s models' % len(all_models))
        for model in all_models:
            fields = [f for f in model._meta.fields if isinstance(f, models.FileField)]
            if fields:
                if verbosity > 1:
                    print('In model %s.%s (%s) found file fields: %s' %
                          (model._meta.app_label, model.__name__, model._meta.verbose_name,
                           ', '.join(['%s (%s)' % (f.name, f.verbose_name) for f in fields])))
                models_with_files[model] = fields

        if kwargs.get('show'):
            return
        for model in models_with_files.keys():
            if verbosity > 1:
                print('\nGenerate files for model %s.%s (%s)' %
                      (model._meta.app_label, model.__name__, model._meta.verbose_name))
            for field in models_with_files[model]:
                if verbosity > 1:
                    print('  Generate files for field %s (%s)' % (field.name, field.verbose_name))
                prepare_file_for_tests(model, field.name, verbosity=verbosity)
