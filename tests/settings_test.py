# -*- coding: utf-8 -*-
from __future__ import unicode_literals

DATABASES = {
    'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'},
}

TEST_RUNNER = 'ttoolly.runner.RegexpTestSuiteRunner'
COLORIZE_TESTS = True
