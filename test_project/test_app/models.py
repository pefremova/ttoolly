# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator


class SomeModel(models.Model):
    text_field = models.TextField(blank=True)
    char_field = models.CharField(blank=True, max_length=120)
    many_related_field = models.ManyToManyField('OtherModel', related_name='related_name', blank=True)
    file_field = models.FileField(blank=True, null=True, upload_to='tmp/')
    image_field = models.ImageField(blank=True, null=True, upload_to='tmp/')
    digital_field = models.FloatField(null=True, validators=[MinValueValidator(-100.5), MaxValueValidator(250.1)])
    int_field = models.IntegerField(validators=[MinValueValidator(-5), MaxValueValidator(500)])
    unique_int_field = models.IntegerField(null=True, blank=True, unique=True, verbose_name='Уникальное поле',
                                           validators=[MinValueValidator(0), MaxValueValidator(9999999)])
    email_field = models.EmailField(blank=True)
    foreign_key_field = models.ForeignKey('OtherModel', blank=True, null=True, on_delete=models.CASCADE)
    date_field = models.DateField(blank=True, null=True)
    datetime_field = models.DateTimeField(blank=True, null=True)
    bool_field = models.BooleanField(default=False)
    one_to_one_field = models.OneToOneField('OtherModel', related_name='one_to_one_related_name', blank=True, null=True, on_delete=models.CASCADE)
    one_to_one_field2 = models.OneToOneField('SomeModel', blank=True, null=True, on_delete=models.CASCADE)

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
