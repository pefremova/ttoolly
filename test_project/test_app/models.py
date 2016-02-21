# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models


class SomeModel(models.Model):
    text_field = models.TextField(blank=True)
    char_field = models.CharField(blank=True, max_length=120)
    many_related_field = models.ManyToManyField('OtherModel', related_name='related_name', blank=True)
    file_field = models.FileField(blank=True, null=True, upload_to='tmp/')
    image_field = models.ImageField(blank=True, null=True, upload_to='tmp/')
    digital_field = models.FloatField(null=True)
    int_field = models.IntegerField()
    unique_int_field = models.IntegerField(null=True, blank=True, unique=True, verbose_name=u'Уникальное поле')
    email_field = models.EmailField(blank=True)
    foreign_key_field = models.ForeignKey('OtherModel', blank=True, null=True)
    date_field = models.DateField(blank=True, null=True)
    datetime_field = models.DateTimeField(blank=True, null=True)
    bool_field = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'SomeModel'
        verbose_name_plural = 'SomeModels'
        ordering = ['pk']

    def __str__(self):
        return 'SomeModel: %s' % self.pk


class OtherModel(models.Model):
    other_text_field = models.TextField(blank=True)

    class Meta:
        verbose_name = 'OtherModel'
        verbose_name_plural = 'OtherModels'
        ordering = ['pk']

    def __str__(self):
        return 'OtherModel: %s' % self.pk
