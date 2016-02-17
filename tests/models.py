from django.db import models


class SomeModel(models.Model):
    text_field = models.TextField(blank=True)
    char_field = models.CharField(blank=True, max_length=120)
    many_related_field = models.ManyToManyField('OtherModel', related_name='related_name', blank=True)
    file_field = models.FileField(blank=True, null=True, upload_to='tmp/')
    image_field = models.ImageField(blank=True, null=True, upload_to='tmp/')
    digital_field = models.FloatField(null=True)
    int_field = models.IntegerField()
    unique_int_field = models.IntegerField(null=True, blank=True, unique=True)
    email_field = models.EmailField(blank=True)
    foreign_key_field = models.ForeignKey('OtherModel', null=True)
    date_field = models.DateField(blank=True, null=True)
    datetime_field = models.DateTimeField(blank=True, null=True)
    bool_field = models.BooleanField(default=False)

    class Meta:
        app_label = 'ttoolly'


class OtherModel(models.Model):

    other_text_field = models.TextField(blank=True)
    class Meta:
        app_label = 'ttoolly'
