#!/usr/bin/env python
import os
import sys

from django.conf import settings
from django.core.management import execute_from_command_line


if not settings.configured:
    PROJECT_PATH = os.path.realpath(os.path.dirname(__file__))
    test_runners_args = {}
    settings.configure(
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            },
        },
        INSTALLED_APPS=(
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'django.contrib.admin',
            'ttoolly',
            'tests',
        ),
        ROOT_URLCONF='tests.urls',
        USE_TZ=True,
        SECRET_KEY='foobar',
        TEMPLATE_DIRS=(PROJECT_PATH + '/tests/templates/'),
        COLORIZE_TESTS=True,
        LANGUAGE_CODE='ru-RU',
        **test_runners_args
    )


def runtests():
    argv = sys.argv[:1] + ['test'] + sys.argv[1:]
    execute_from_command_line(argv)


if __name__ == '__main__':
    runtests()
