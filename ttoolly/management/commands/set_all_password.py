# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
try:
    from django.contrib.auth import get_user_model
except:
    from django.contrib.auth.models import User

    def get_user_model():
        return User


class Command(BaseCommand):

    args = 'password'
    help = "Changes all users passwords to specified (qwerty by default)"

    def add_arguments(self, parser):
        parser.add_argument('-p', '--password', default='qwerty',  help='New password. Default: %(default)s')

    def handle(self, *args, **kwargs):
        password = kwargs.get('password')

        for user in get_user_model().objects.all():
            user.set_password(password)
            user.save()
