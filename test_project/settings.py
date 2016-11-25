# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import sys

from django import VERSION as DJANGO_VERSION


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SECRET_KEY = 'foo'
DEBUG = True
ALLOWED_HOSTS = []

INSTALLED_APPS = (
    # 'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    # 'django.contrib.messages',
    # 'django.contrib.staticfiles',

    'ttoolly',
    'tests',

    'test_project.test_app'
)

MIDDLEWARE_CLASSES = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
)


ROOT_URLCONF = 'test_project.urls'


if DJANGO_VERSION < (1, 8):
    TEMPLATE_DIRS = [os.path.join(BASE_DIR, 'test_project/templates')]
else:
    MIDDLEWARE_CLASSES += (
        'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
        'django.middleware.security.SecurityMiddleware'
    )
    TEMPLATES = [
        {
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [os.path.join(BASE_DIR, 'test_project/templates')],
            'APP_DIRS': True,
            'OPTIONS': {
                'context_processors': [
                    'django.template.context_processors.debug',
                    'django.template.context_processors.request',
                    'django.contrib.auth.context_processors.auth',
                    'django.contrib.messages.context_processors.messages',
                ],
            },
        },
    ]

WSGI_APPLICATION = 'test_project.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}


LANGUAGE_CODE = 'ru-RU'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

STATIC_URL = '/static/'


if 'test' in sys.argv:
    from tests.settings_test import *
