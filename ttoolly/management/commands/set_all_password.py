# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):

    help = "Changes all users passwords to specified (qwerty by default)"

    def handle(self, *args, **kwargs):
        password = 'qwerty'
        if args:
            password = args[0]
        for user in User.objects.all():
            user.set_password(password)
            user.save()
