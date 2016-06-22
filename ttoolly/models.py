# -*- coding: utf-8 -*-
import inspect
import json
from copy import copy, deepcopy
from decimal import Decimal
from random import choice, randint, uniform
from shutil import rmtree
from unittest import SkipTest

import sys
from datetime import datetime, date, time

import os
import psycopg2.extensions
import re
import warnings
from django import VERSION as DJANGO_VERSION
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.urlresolvers import reverse, resolve
from django.db import transaction, DEFAULT_DB_ALIAS, connections, models
from django.db.models import Model, Q
from django.db.models.fields import FieldDoesNotExist
from django.template.defaultfilters import filesizeformat
from django.test import TransactionTestCase, TestCase
from django.test.testcases import connections_support_transactions
from lxml.html import document_fromstring
from utils import (format_errors, get_error, get_randname, get_url_for_negative, get_url, get_captcha_codes, move_dir,
                   get_random_email_value, get_fixtures_data, generate_sql, unicode_to_readable,
                   get_fields_list_from_response, get_all_form_errors, generate_random_obj, get_random_jpg_content,
                   get_all_urls, convert_size_to_bytes, get_random_file)

TEMP_DIR = getattr(settings, 'TEST_TEMP_DIR', 'test_temp')


def get_dirs_for_move():
    DIRS_FOR_MOVE = getattr(settings, 'DIRS_FOR_MOVE', [])
    DIRS_FOR_MOVE.extend([el for el in [getattr(settings, 'MEDIA_ROOT', ''), getattr(settings, 'STATIC_ROOT', '')] if
                          el and not any([el.startswith(d) for d in DIRS_FOR_MOVE])])
    return set(DIRS_FOR_MOVE)


def only_with_obj(fn):
    def tmp(self):
        if self.obj:
            return fn(self)
        else:
            raise SkipTest('Need "obj"')
    tmp.__name__ = fn.__name__
    return tmp


def only_with(param_names=None):
    if not isinstance(param_names, (tuple, list)):
        param_names = [param_names, ]

    def decorator(fn):
        def tmp(self):
            def get_value(param_name):
                return getattr(self, param_name, None)

            if all(get_value(param_name) for param_name in param_names):
                return fn(self)
            else:
                raise SkipTest("Need all these params: %s" % repr(param_names))
        tmp.__name__ = fn.__name__
        return tmp
    return decorator


class RequestManager(models.Manager):

    def __init__(self, db_name=None):
        if not db_name:
            db_names = [db for db in connections if db != DEFAULT_DB_ALIAS]
            if db_names:
                db_name = db_names[0]
        self.db_name = db_name
        super(RequestManager, self).__init__()

    def get_query_set(self):
        return super(RequestManager, self).get_query_set().using(self.db_name)


class RequestManagerNew(RequestManager):

    """For Django>=1.8"""

    def get_queryset(self):
        return super(RequestManager, self).get_queryset().using(self.db_name)


class CustomModel(models.Model):

    objects = RequestManager()

    class Meta:
        abstract = True
        managed = False
        app_label = 'ttoolly'


class JsonResponseErrorsMixIn(object):

    def get_all_form_errors(self, response):
        if response.status_code not in (200, 201):
            try:
                return json.loads(response.content)
            except:
                return super(JsonResponseErrorsMixIn, self).get_all_form_errors(response)
        try:
            return json.loads(response.content)['errors']
        except:
            return super(JsonResponseErrorsMixIn, self).get_all_form_errors(response)


class MetaCheckFailures(type):

    def __init__(cls, name, bases, dct):
        def check_errors(fn):
            def tmp(self):
                fn(self)
                self.formatted_assert_errors()
            tmp.with_check_errors_decorator = True
            tmp.__name__ = fn.__name__
            return tmp

        def decorate(cls, bases, dct):
            for attr in cls.__dict__:
                if callable(getattr(cls, attr)) and attr.startswith('test_') and \
                        not getattr(getattr(cls, attr), 'with_check_errors_decorator', False):
                    setattr(cls, attr, check_errors(getattr(cls, attr)))
            bases = cls.__bases__
            for base in bases:
                decorate(base, base.__bases__, base.__dict__)
            return cls

        decorate(cls, bases, dct)
        super(MetaCheckFailures, cls).__init__(name, bases, dct)


class Ring(list):

    def turn(self):
        last = self.pop(0)
        self.append(last)

    def get_and_turn(self):
        res = self[0]
        self.turn()
        return res


class GlobalTestMixIn(object):

    __metaclass__ = MetaCheckFailures

    additional_params = None
    all_unique = None
    choice_fields_values = None
    errors = []
    FILE_FIELDS = ('file', 'filename', 'image', 'preview')
    files = []
    IMAGE_FIELDS = ('image', 'preview', 'photo')
    maxDiff = None
    non_field_error_key = '__all__'
    unique_fields = None

    def __init__(self, *args, **kwargs):
        if self.additional_params is None:
            self.additional_params = {}
        if self.choice_fields_values is None:
            self.choice_fields_values = {}
        if not self.all_unique:
            self.all_unique = {}
        if self.unique_fields is None:
            self.unique_fields = ()
        for el in self.unique_fields:
            if isinstance(el, (tuple, list)):
                key = list(el)
                if key[0].endswith(self.non_field_error_key):
                    key.pop(0)
                self.all_unique[tuple(key)] = el[0]
            else:
                self.all_unique[(el,)] = el
        self.FILE_FIELDS = set(tuple(self.FILE_FIELDS) + tuple(self.IMAGE_FIELDS))
        super(GlobalTestMixIn, self).__init__(*args, **kwargs)

    def _fixture_setup(self):
        if getattr(settings, 'TEST_CASE_NAME', self.__class__.__name__) != self.__class__.__name__:
            delattr(settings, 'TEST_CASE_NAME')
            call_command('flush', verbosity=0, interactive=False, database=DEFAULT_DB_ALIAS)
        super(GlobalTestMixIn, self)._fixture_setup()

    def _post_teardown(self):
        super(GlobalTestMixIn, self)._post_teardown()
        self.for_post_tear_down()

    def _pre_setup(self):
        super(GlobalTestMixIn, self)._pre_setup()
        self.for_pre_setup()

    def for_post_tear_down(self):
        self.del_files()
        if os.path.exists(TEMP_DIR):
            try:
                rmtree(TEMP_DIR)
            except:
                pass
        if getattr(self, 'with_files', False):
            for path in get_dirs_for_move():
                move_dir(path)

    def for_pre_setup(self):
        self.errors = []
        if not os.path.exists(TEMP_DIR):
            os.makedirs(TEMP_DIR)
        if getattr(self, 'with_files', False):
            for path in get_dirs_for_move():
                move_dir(path)

    def assertEqual(self, *args, **kwargs):
        with warnings.catch_warnings(record=True) as warn:
            warnings.simplefilter("always")
            try:
                return super(GlobalTestMixIn, self).assertEqual(*args, **kwargs)
            except Exception, e:
                if warn:
                    message = warn[0].message.message + u'\n' + e.message
                    e.args = (message,)
                raise e

    def _assert_dict_equal(self, d1, d2, parent_key=''):
        text = []
        parent_key = '[%s]' % parent_key.strip('[]') if parent_key else ''
        not_in_second = set(d1.keys()).difference(d2.keys())
        not_in_first = set(d2.keys()).difference(d1.keys())
        if not_in_first:
            text.append('Not in first dict: %s' % repr(list(not_in_first)))
        if not_in_second:
            text.append('Not in second dict: %s' % repr(list(not_in_second)))
        for key in set(d1.keys()).intersection(d2.keys()):
            errors = []
            if d1[key] != d2[key]:
                if isinstance(d1[key], dict) and isinstance(d2[key], dict):
                    res = self._assert_dict_equal(d1[key], d2[key],
                                                  parent_key + '[%s]' % key)
                    if res:
                        text.append(parent_key + '[%s]:\n  ' % key + '\n  '.join(res.splitlines()))
                elif isinstance(d1[key], list) and isinstance(d2[key], list):
                    try:
                        self.assert_list_equal(d1[key], d2[key])
                    except:
                        self.errors_append(errors)
                        text.append('%s[%s]:\n%s' % (parent_key if parent_key else '',
                                                     key, '\n'.join(errors)))
                else:
                    d1_value = d1[key] if ((isinstance(d1[key], str) and isinstance(d2[key], str)) or
                                           (isinstance(d1[key], unicode) and isinstance(d2[key], unicode))) else repr(d1[key])
                    d2_value = d2[key] if ((isinstance(d1[key], str) and isinstance(d2[key], str)) or
                                           (isinstance(d1[key], unicode) and isinstance(d2[key], unicode))) else repr(d2[key])
                    text.append('%s[%s]: %s != %s' %
                                (parent_key if parent_key else '',
                                 key, d1_value, d2_value))
        res = '\n'.join(text)
        if not isinstance(res, unicode):
            res = res.decode('utf-8')
        return res

    def assert_dict_equal(self, d1, d2, msg=None):
        msg = msg + u':\n' if msg else ''
        self.assertIsInstance(d1, dict, msg + 'First argument is not a dictionary')
        self.assertIsInstance(d2, dict, msg + 'Second argument is not a dictionary')

        if d1 != d2:
            diff = self._assert_dict_equal(d1, d2)

            error_message = self._truncateMessage(msg, diff)
            self.fail(self._formatMessage(error_message, None))

    def assert_form_equal(self, form_fields, etalon_fields, text=''):
        text = (text + u':\n') if text else ''
        errors = []
        not_present_fields = set(etalon_fields).difference(form_fields)
        if not_present_fields:
            errors.append(u'Fields %s not at form' % str(list(not_present_fields)))
        present_fields = set(form_fields).difference(etalon_fields)
        if present_fields:
            errors.append(u"Fields %s not need at form" % str(list(present_fields)))
        count_dict_form = {k: form_fields.count(k) for k in form_fields}
        count_dict_etalon = {k: etalon_fields.count(k) for k in etalon_fields}
        for field, count_in_etalon in count_dict_etalon.iteritems():
            count_in_form = count_dict_form.get(field, None)
            if count_in_form and count_in_form != count_in_etalon:
                errors.append(u"Field '%s' present at form %s time(s) (should be %s)" %
                              (field, count_in_form, count_in_etalon))

        if errors:
            error_message = ';\n'.join(errors)
            if text:
                error_message = text + error_message
            raise AssertionError(error_message)

    def assert_list_equal(self, list1, list2, msg=None):
        msg = msg + u':\n' if msg else ''
        self.assertIsInstance(list1, list, msg + 'First argument is not a list')
        self.assertIsInstance(list2, list, msg + 'Second argument is not a list')

        if list1 != list2:
            diff = self._assert_list_equal(list1, list2)
            error_message = self._truncateMessage(msg, diff)
            self.fail(self._formatMessage(error_message, None))

    def _assert_list_equal(self, list1, list2):
        errors = []
        if all([isinstance(el, dict) for el in list1]) and all([isinstance(el, dict) for el in list2]):
            for i, el in enumerate(list2):
                res = self._assert_dict_equal(list1[i], el)
                if res:
                    errors.append('[line %d]: ' % i + res)
        elif all([isinstance(el, list) for el in list1]) and all([isinstance(el, list) for el in list2]):
            for i, el in enumerate(list2):
                res = self._assert_list_equal(list1[i], el)
                if res:
                    errors.append('[line %d]: ' % i + res)
        else:
            try:
                self.assertEqual(list1, list2)
            except:
                _, v, _ = sys.exc_info()
                errors.append(v.message)

        res = '\n'.join(errors)
        if not isinstance(res, unicode):
            res = res.decode('utf-8')
        return res

    def assert_mail_count(self, mails=None, count=None):
        error = ''
        mails = mails or mail.outbox
        mails_count = len(mails)
        if mails_count != count:
            error = 'Sent %d mails expect of %d.' % (mails_count, count)
        if mails_count > 0:
            m_to = [str(m.to) for m in mails]
            m_to.sort()
            error += ' To %s' % ', '.join(m_to)
        if error:
            self.assertEqual(mails_count, count, error)

    def assert_no_form_errors(self, response):
        form_errors = self.get_all_form_errors(response)
        if form_errors:
            raise AssertionError('There are errors at form: ' + repr(form_errors))

    def assert_objects_equal(self, obj1, obj2, exclude=None, other_values=None):
        if not other_values:
            other_values = {}
        if not exclude:
            exclude = []
        exclude = list(exclude)
        if (getattr(self, 'obj', None) and isinstance(obj1, self.obj)) or not getattr(self, 'obj', None):
            exclude.extend(getattr(self, 'exclude_from_check', []))
        local_errors = []

        object_fields = self.get_object_fields(obj1)
        object2_fields = self.get_object_fields(obj2)

        object_fields.extend(object2_fields)
        for field in set(object_fields).difference(exclude):
            try:
                self.assertEqual(self.get_value_for_compare(obj1, field),
                                 other_values.get(field, self.get_value_for_compare(obj2, field)))
            except AssertionError:
                local_errors.append('"%s":\n' % field + get_error())
        if local_errors:
            raise AssertionError(format_errors(local_errors))

    def assert_object_fields(self, obj, params, exclude=None, other_values=None):
        """
        @param exclude: exclude field from check
        @param other_values: dict, set custom value for fields
        """
        params = self.deepcopy(params)
        if not other_values:
            other_values = {}
        if not exclude:
            exclude = []
        exclude = list(exclude)
        if (getattr(self, 'obj', None) and isinstance(obj, self.obj)) or not getattr(self, 'obj', None):
            exclude.extend(getattr(self, 'exclude_from_check', []))
            other_values_for_check = self.deepcopy(getattr(self, 'other_values_for_check', {}))
            for k in other_values_for_check.keys():
                if k in other_values.keys():
                    other_values_for_check.pop(k)
            other_values.update(other_values_for_check)
        params.update(other_values)

        local_errors = []
        object_fields = obj._meta.get_all_field_names()
        object_related_field_names = [name for name in object_fields if
                                      obj._meta.get_field_by_name(name)[0].__class__.__name__ in ('RelatedObject',
                                                                                                  'ManyToOneRel',
                                                                                                  'OneToOneField',
                                                                                                  'ManyToManyField')]
        fields_for_check = set(params.keys()).intersection(object_fields)
        fields_for_check.update([k.split('-')[0] for k in params.keys() if k.split('-')[0]
                                 in object_related_field_names])
        fields_for_check = fields_for_check.difference(exclude)
        obj_related_objects = self.get_related_names(obj)
        one_to_one_fields = [name for name in object_related_field_names if
                             obj._meta.get_field_by_name(name)[0].__class__.__name__ == 'OneToOneField' or
                             getattr(obj._meta.get_field_by_name(name)[0], 'field', None) and
                             obj._meta.get_field_by_name(name)[0].field.__class__.__name__ == 'OneToOneField']

        for field in fields_for_check:
            # TODO: refactor me
            if field in one_to_one_fields:
                cls = obj._meta.get_field_by_name(field)[0]
                _model = getattr(cls, 'related_model', None) or cls.related.parent_model
                value = _model.objects.filter(**{cls.related_query_name(): obj})
                if value:
                    value = value[0]
            else:
                value = getattr(obj, field)

            if field in obj_related_objects.keys() or field in obj_related_objects.values() and \
                (value.__class__.__name__ in ('RelatedManager', 'QuerySet') or
                 set([mr.__name__ for mr in value.__class__.__mro__]).intersection(['Manager', 'Model', 'ModelBase'])):
                if isinstance(params.get(field, None), list):
                    count_for_check = len(params[field])
                else:
                    count_for_check = params.get('%s-TOTAL_FORMS' % obj_related_objects.get(field, field), None)
                if count_for_check and value.__class__.__name__ == 'RelatedManager':
                    try:
                        self.assertEqual(value.all().count(), count_for_check)
                    except Exception, e:
                        local_errors.append('[%s]: count ' % (field.encode('utf-8') if isinstance(field, unicode)
                                                              else field) + str(e))
                for i, el in enumerate(value.all().order_by('pk')
                                       if value.__class__.__name__ in ('RelatedManager','QuerySet')
                                       else [value, ]):
                    _params = dict([(k.replace('%s-%d-' % (obj_related_objects.get(field, field), i), ''),
                                     params[k]) for k in params.keys() if
                                    k.startswith('%s-%d' % (obj_related_objects.get(field, field), i))
                                    and k not in exclude])
                    try:
                        self.assert_object_fields(el, _params)
                    except Exception, e:
                        local_errors.append('[%s]:%s' % (field.encode('utf-8') if isinstance(field, unicode)
                                                         else field, '\n  '.join(str(e).splitlines())))
                continue

            params_value = params[field]
            value, params_value = self.get_params_according_to_type(value, params_value)

            if isinstance(value, unicode):
                value = value.encode('utf-8')
            if isinstance(params_value, unicode):
                params_value = params_value.encode('utf-8')
            try:
                self.assertEqual(value, params_value)
            except AssertionError:
                local_errors.append('[%s]: %s != %s' %
                                    (field,
                                     repr(value) if not isinstance(value, str) else "'%s'" % value,
                                     repr(params_value) if not isinstance(params_value, str)
                                     else "'%s'" % params_value))

        if local_errors:
            raise AssertionError("Values from object != expected values from dict:\n" + "\n".join(local_errors))

    def assert_text_equal_by_symbol(self, first, second, additional=20):
        full_error_text = ''
        if '-v' in sys.argv:
            try:
                self.assertEqual(first, second)
            except AssertionError, e:
                full_error_text = u'\n\nFull error message text:\n%s' % unicode_to_readable(e.message).decode('utf-8')
        first_length = len(first)
        second_length = len(second)
        for n in xrange(max(first_length, second_length)):
            self.assertEqual(first[n:n + 1],
                             second[n:n + 1],
                             ('Not equal in position %d: ' % n +
                              "'%s%s' != '%s%s'" % (first[n: n + additional],
                              '...' if (n + additional < first_length) else '',
                              second[n: n + additional],
                              '...' if (n + additional < second_length) else '')) + full_error_text)

    def assert_xpath_count(self, response, path, count=1, status_code=200):
        self.assertEqual(response.status_code, status_code, "Response status code %s != %s" %
                         (response.status_code, status_code))
        if not ('xml' in response.content and 'encoding' in response.content):
            res = response.content.decode('utf-8')
        else:
            res = response.content
        self.assert_xpath_count_in_html(res, path, count)

    def assert_xpath_count_in_html(self, html, path, count):
        doc = document_fromstring(html)
        real_count = len(doc.xpath(path))
        error_message = 'Found %s instances of \'%s\' (Should be %s)' % (real_count, path, count)
        self.assertEqual(real_count, count, error_message)

    def deepcopy(self, params):
        tmp_params = {}
        old_params = params
        params = copy(params)
        keys = params.keys()
        for k in keys:
            if isinstance(params[k], (ContentFile, file)):
                content_file = params.pop(k)
                content_file.seek(0)
                tmp_params[k] = ContentFile(content_file.read(), content_file.name)
                self.files.extend([old_params[k], content_file, tmp_params[k]])
        params = deepcopy(params)
        params.update(tmp_params)
        return params

    def del_files(self):
        while self.files:
            f = self.files.pop()
            if not f.closed:
                f.close()
            del f

    def errors_append(self, errors=None, text='', color=231):
        if errors is None:
            errors = self.errors
        text = (text + ':\n') if text else ''
        if isinstance(text, str):
            text = text.decode('utf-8')
        if getattr(settings, 'COLORIZE_TESTS', False) and text:
            text = "\x1B[38;5;%dm" % color + text + "\x1B[0m"
        result = text + get_error().decode('utf-8')
        if result:
            errors.append(result)
        return errors

    def formatted_assert_errors(self):
        errors = copy(self.errors)
        self.errors = []
        self.assertFalse(errors, format_errors(errors))

    def generate_random_obj(self, obj_model, additional_params=None, filename=None):
        return generate_random_obj(obj_model, additional_params, filename)

    def get_all_form_messages(self, response):
        try:
            return [ld.message for ld in response.context['messages']._loaded_data]
        except KeyError:
            pass

    def get_all_form_errors(self, response):
        return get_all_form_errors(response)

    def get_error_field(self, message_type, field):
        error_field = re.sub(r'_(\d|ru)$', '', field)
        if message_type == 'max_length' and self.is_file_field(field):
            message_type = 'max_length_file'
        messages_dict = getattr(settings, 'ERROR_MESSAGES', {})
        messages_dict.update(getattr(self, 'custom_error_messages', {}))
        error_message = ''
        if field in messages_dict.keys():
            field_dict = messages_dict[field]
            if message_type in ('max_length', 'max_length_file'):
                error_message = field_dict.get('max_length', field_dict.get('max_length_file', ''))
            else:
                error_message = field_dict.get(message_type, error_message)

        if isinstance(error_message, dict):
            error_field = error_message.keys()[0]
        return error_field

    def get_error_message(self, message_type, field, *args, **kwargs):
        for frame in inspect.getouterframes(inspect.currentframe()):
            if frame[3].startswith('test_'):
                break
        previous_locals = kwargs.get('locals', frame[0].f_locals)
        if 'field' not in previous_locals.iterkeys():
            previous_locals['field'] = field
        if message_type == 'max_length' and self.is_file_field(field):
            message_type = 'max_length_file'
        verbose_obj = self.obj._meta.verbose_name if getattr(self, 'obj', None) else u'Объект'
        if isinstance(verbose_obj, str):
            verbose_obj = verbose_obj.decode('utf-8')
        verbose_field = getattr(self.obj._meta.get_field_by_name(field)[0], 'verbose_name', field) if \
            (getattr(self, 'obj', None) and field in self.obj._meta.get_all_field_names()) else field
        if isinstance(verbose_field, str):
            verbose_field = verbose_field.decode('utf-8')
        ERROR_MESSAGES = {'required': u'Обязательное поле.',
                          'max_length': u'Убедитесь, что это значение содержит не ' + \
                                        u'более {length} символов (сейчас {current_length}).' if
                                                                (previous_locals.get('length', None) is None or
                                                                not isinstance(previous_locals.get('length'), int)) \
                                        else u'Убедитесь, что это значение содержит не ' + \
                                        u'более {length} символов (сейчас {current_length}).'.format(**previous_locals),
                          'max_length_file': u'Убедитесь, что это имя файла содержит не ' + \
                                        u'более {length} символов (сейчас {current_length}).' if
                                                                (previous_locals.get('length', None) is None or
                                                                not isinstance(previous_locals.get('length'), int)) \
                                        else u'Убедитесь, что это имя файла содержит не ' + \
                                        u'более {length} символов (сейчас {current_length}).'.format(**previous_locals),
                          'max_length_digital': u'Убедитесь, что это значение меньше либо равно {max_value}.' if
                                                                    (previous_locals.get('max_value', None) is None) \
                                        else u'Убедитесь, что это значение меньше либо равно {max_value}.'.format(**previous_locals),
                          'min_length': u'Убедитесь, что это значение содержит не ' + \
                                        u'менее {length} символов (сейчас {current_length}).' if
                                                                (previous_locals.get('length', None) is None or
                                                                not isinstance(previous_locals.get('length'), int)) \
                                        else u'Убедитесь, что это значение содержит не ' + \
                                        u'менее {length} символов (сейчас {current_length}).'.format(**previous_locals),
                          'min_length_digital': u'Убедитесь, что это значение больше либо равно {min_value}.' if
                                                                    (previous_locals.get('min_value', None) is None) \
                                        else u'Убедитесь, что это значение больше либо равно {min_value}.'.format(**previous_locals),
                          'wrong_value': u'Выберите корректный вариант. Вашего ' +
                                         u'варианта нет среди допустимых значений.' if previous_locals.get('value', '') == '' \
                                         else u'Выберите корректный вариант. {value} '.format(**previous_locals) +
                                         u'нет среди допустимых значений.',
                          'wrong_value_int': u'Введите целое число.',
                          'wrong_value_digital': u'Введите число.',
                          'wrong_value_email': u'Введите правильный адрес электронной почты.',
                          'unique': u'{verbose_obj} с таким {verbose_field} уже существует.'.format(**locals()),
                          'delete_not_exists': u'Произошла ошибка. Попробуйте позже.',
                          'recovery_not_exists': u'Произошла ошибка. Попробуйте позже.',
                          'empty_file': u'Отправленный файл пуст.',
                          'max_count_file': u'Допускается загрузить не более {max_count} файлов.' if
                                    (previous_locals.get('max_count', None) is None)
                                    else u'Допускается загрузить не более {max_count} файлов.'.format(**previous_locals),
                          'max_size_file': u'Размер файла {filename} больше {max_size}.' if
                                    (previous_locals.get('filename', None) is None or
                                     previous_locals.get('max_size', None) is None)
                                    else u'Размер файла {filename} больше {max_size}.'.format(**previous_locals),
                          'wrong_extension': u'Некорректный формат файла {filename}.' if
                                    previous_locals.get('filename', None) is None
                                    else u'Некорректный формат файла {filename}.'.format(**previous_locals),
                          'min_dimensions': u'Минимальный размер изображения {min_width}x{min_height}' if
                                    (previous_locals.get('min_width', None) is None or
                                     previous_locals.get('min_height', None))
                                     else u'Минимальный размер изображения {min_width}x{min_height}'.format(**previous_locals),
                          'max_sum_size_file': u'Суммарный размер изображений не должен превышать {max_size}.' if
                                    previous_locals.get('max_size', None) is None
                                    else  u'Суммарный размер изображений не должен превышать {max_size}.'.format(**previous_locals),
                          'one_of': u'Оставьте одно из значений в полях {group}.' if
                                    (previous_locals.get('group', None) is None)
                                    else u'Оставьте одно из значений в полях {group}.'.format(**previous_locals)}

        messages_from_settings = getattr(settings, 'ERROR_MESSAGES', {})
        ERROR_MESSAGES.update(messages_from_settings)
        custom_errors = self.deepcopy(getattr(self,
                                              'custom_error_messages', {}).get(field if not
                                                                               isinstance(field, (list, tuple))
                                                                               else tuple(field), {}))

        if isinstance(field, (list, tuple)) and not custom_errors:
            for fi in field:
                custom_errors = custom_errors or self.deepcopy(getattr(self, 'custom_error_messages', {}).get(fi, {}))
                if custom_errors:
                    break

        """в custom_error_messages для числового или файлового поля задано значение как max_length"""
        if message_type in ('max_length_int', 'max_length_digital', 'max_length_file') \
                and 'max_length' in custom_errors.keys() \
                and message_type not in custom_errors.keys():
            custom_errors[message_type] = custom_errors['max_length']

        if message_type in ('min_length_int', 'min_length_digital', 'min_length_file') \
                and 'min_length' in custom_errors.keys() \
                and message_type not in custom_errors.keys():
            custom_errors[message_type] = custom_errors['min_length']

        ERROR_MESSAGES.update(custom_errors)
        error_message = ERROR_MESSAGES.get(message_type, '')
        if field is None:
            return [el.format(**previous_locals) for el in error_message] if isinstance(error_message, list) \
                else error_message.format(**previous_locals)

        if not isinstance(error_message, dict):
            error_field = kwargs.get('error_field', re.sub(r'_(\d|ru)$', '', field) if
                                     not isinstance(field, (list, tuple)) else self.non_field_error_key)
            error_message = {error_field: [error_message] if not isinstance(error_message, list) else error_message}
        else:
            error_message = self.deepcopy(error_message)

        for k, v in error_message.iteritems():
            error_message[k] = [el.format(**previous_locals) for el in v] if \
                                isinstance(v, list) else [v.format(**previous_locals)]
        return error_message

    def get_field_by_name(self, model, field):
        if re.findall(r'[\w_]+\-\d+\-[\w_]+', field):
            obj_related_objects = self.get_related_names(model)
            all_names = model._meta.get_all_field_names()
            field_name = field.split('-')[0]
            field_name = field_name if field_name in all_names else obj_related_objects.get(field_name, field_name)
            related = model._meta.get_field_by_name(field_name)[0]
            model = getattr(related, 'related_model', getattr(getattr(related, 'rel', None), 'to', related.model))
            field = field.split('-')[-1]
        return model._meta.get_field_by_name(field)

    def get_fields_list_from_response(self, response):
        return get_fields_list_from_response(response)

    def get_object_fields(self, obj):
        object_fields = []
        if DJANGO_VERSION < (1, 8):
            fields = [self.get_field_by_name(obj, name)[0] for name in obj._meta.get_all_field_names()]
        else:
            fields = obj._meta.get_fields()
        for field in set(fields):
            if field.__class__.__name__ in ('RelatedObject', 'ManyToOneRel', 'OneToOneRel'):
                object_fields.append(field.get_accessor_name())
            else:
                object_fields.append(field.name)
        return object_fields

    def get_params_according_to_type(self, value, params_value):
        if type(value) == type(params_value):
            return value, params_value
        if value is None:
            value = ''
        if params_value is None:
            params_value = ''

        if isinstance(value, (str, unicode)) and isinstance(params_value, (str, unicode)):
            if isinstance(value, unicode):
                value = value.encode('utf-8')
            if isinstance(params_value, unicode):
                params_value = params_value.encode('utf-8')
            return value, params_value
        if isinstance(value, bool):
            params_value = bool(params_value)
            return value, params_value
        if (isinstance(value, date) or isinstance(value, time)) and not (isinstance(params_value, date) or
                                                                         isinstance(params_value, time)):
            if isinstance(value, datetime):
                value = value.strftime('%d.%m.%Y %H:%M:%S')
            elif isinstance(value, date):
                value = value.strftime('%d.%m.%Y')
            elif isinstance(value, time):
                value = value.strftime('%H:%M:%S')
            return value, params_value

        if isinstance(value, Model):
            value = value.pk
            params_value = int(params_value) if params_value else params_value
        elif value.__class__.__name__ in ('ManyRelatedManager', 'GenericRelatedObjectManager'):
            value = [unicode(v) for v in value.values_list('pk', flat=True)]
            value.sort()
            if isinstance(params_value, list):
                params_value = [unicode(pv) for pv in params_value]
                params_value.sort()
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(params_value, (int, float, str, unicode)) and not isinstance(params_value, bool):
                value = str(value)
                params_value = str(params_value)
        elif isinstance(value, Decimal) and not isinstance(value, bool):
            if isinstance(params_value, (int, Decimal, float, str, unicode)) and not isinstance(params_value, bool):
                value = value
                if isinstance(params_value, (int, float)):
                    params_value = repr(params_value)
                params_value = Decimal(params_value)
        elif (set([m.__name__ for m in value.__class__.__mro__]).intersection(['file', 'FieldFile', 'ImageFieldFile'])
              or isinstance(params_value, (file, ContentFile))):
            if value:
                value = value if (isinstance(value, str) or isinstance(value, unicode)) else value.name
                value = re.sub(r'_[a-zA-Z0-9]+(?=$|\.[\w\d]+$)', '', os.path.basename(value))
            else:
                value = ''
            params_value = params_value if (isinstance(params_value, str) or isinstance(params_value, unicode))\
                                        else params_value.name
            params_value = os.path.basename(params_value)

        return value, params_value

    def is_file_list(self, field):
        return isinstance(((getattr(self, 'default_params', None) and self.default_params.get(field, None))
                           or (getattr(self, 'default_params_add', None) and self.default_params_add.get(field, None))
                           or (getattr(self, 'default_params_edit', None) and self.default_params_edit.get(field, None))),
                          (list, tuple))

    def get_random_file(self, field, length):
        self.with_files = True
        filename = get_randname(length, 'r')
        if getattr(self, 'file_fields_params', {}).get(field, {}).get('extensions', ()):
            ext = choice(getattr(self, 'file_fields_params', {}).get(field, {}).get('extensions', ()))
            filename = filename[:-len(ext) - 1] + '.' + ext
        default_file = ((getattr(self, 'default_params', None) and self.default_params.get(field, None))
                        or (getattr(self, 'default_params_add', None) and self.default_params_add.get(field, None))
                        or (getattr(self, 'default_params_edit', None) and self.default_params_edit.get(field, None)))
        is_list = self.is_file_list(field)
        if default_file and is_list:
            default_file = default_file[0]

        if default_file and os.path.splitext(default_file.name)[1] in ('.tiff', '.jpg', '.jpeg', '.png',):
            type_name = os.path.splitext(default_file.name)[-1]
            if type_name:
                filename = filename[:-len(type_name)] + type_name
            default_file.seek(0)
            text_for_file = default_file.read()
        else:
            if field in self.IMAGE_FIELDS or os.path.splitext(filename)[1] in ('.tiff', '.jpg', '.jpeg', '.png',):
                if not os.path.splitext(filename)[1]:
                    filename = filename[:-4] + ".jpg"
                text_for_file = get_random_jpg_content()
            else:
                text_for_file = get_randname(1000)
        f = ContentFile(text_for_file, name=filename)
        self.files.append(f)
        if is_list:
            return [f, ]
        return f

    def get_related_names(self, model):
        obj_related_objects = dict([(el.get_accessor_name(), getattr(el, 'var_name', el.get_accessor_name())) for el in
                                    model._meta.get_all_related_objects()])
        obj_related_objects.update(getattr(self, 'related_names', {}))
        return obj_related_objects

    def _get_value_for_compare(self, *args, **kwargs):
        raise DeprecationWarning('use get_value_for_compare')

    def get_value_for_compare(self, obj, field):
        if not hasattr(obj, field):
            value = None
        elif getattr(obj, field).__class__.__name__ in ('ManyRelatedManager', 'RelatedManager',
                                                        'GenericRelatedObjectManager'):
            value = [v for v in getattr(obj, field).values_list('pk', flat=True).order_by('pk')]
        else:
            value = getattr(obj, field)
            if 'File' in [m.__name__ for m in getattr(obj, field).__class__.__mro__] and not value:
                value = None
        return value

    def get_value_for_field(self, length, field_name):
        if self.is_email_field(field_name):
            return get_random_email_value(length)
        elif self.is_file_field(field_name):
            value = self.get_random_file(field_name, length)
            return value
        elif self.is_choice_field(field_name) and getattr(self, 'choice_fields_values', {}).get(field_name, ''):
            return choice(self.choice_fields_values[field_name])
        elif self.is_multiselect_field(field_name) and getattr(self, 'choice_fields_values', {}).get(field_name, []):
            values = self.choice_fields_values[field_name]
            return list(set([choice(values) for _ in xrange(randint(1, len(values)))]))
        elif self.is_date_field(field_name):
            if field_name.endswith('1'):
                return datetime.now().strftime('%H:%M')
            else:
                return datetime.now().strftime(settings.DATE_INPUT_FORMATS[0])
        elif self.is_digital_field(field_name):
            if getattr(self, 'obj', None):
                try:
                    if 'ForeignKey' in [b.__name__ for b in
                                        self.get_field_by_name(self.obj, field_name)[0].__class__.__mro__]:
                        return choice(self.obj._meta.get_field_by_name(field_name)[0].rel.to.objects.all()).pk
                except FieldDoesNotExist:
                    pass
            if 'get_digital_values_range' not in dir(self):
                return get_randname(length, 'd')
            values_range = self.get_digital_values_range(field_name)
            if self.is_int_field(field_name):
                return randint(max(values_range['min_values']), min(values_range['max_values']))
            else:
                return uniform(max(values_range['min_values']), min(values_range['max_values']))
        else:
            return get_randname(length, 'w').decode('utf-8')

    def get_value_for_error_message(self, field, value):
        if self.is_file_field(field):
            if isinstance(value, (list, tuple)):
                return ', '.join([el.name for el in value])
            else:
                return value.name
        else:
            return value

    def get_url(self, *args, **kwargs):
        return get_url(*args, **kwargs)

    def get_url_for_negative(self, *args, **kwargs):
        return get_url_for_negative(*args, **kwargs)

    def is_choice_field(self, field):
        return any([field in (getattr(self, 'choice_fields', ()) or ()),
                    field in (getattr(self, 'choice_fields_add', ()) or ()),
                    field in (getattr(self, 'choice_fields_edit', ()) or ()),
                    field in (getattr(self, 'choice_fields_with_value_in_error', ()) or ()),
                    field in (getattr(self, 'choice_fields_add_with_value_in_error', ()) or ()),
                    field in (getattr(self, 'choice_fields_edit_with_value_in_error', ()) or ()), ])

    def is_date_field(self, field):
        return field in getattr(self, 'date_fields', ())

    def is_digital_field(self, field):
        return any([field in (getattr(self, 'digital_fields', ()) or ()),
                    field in (getattr(self, 'digital_fields_add', ()) or ()),
                    field in (getattr(self, 'digital_fields_edit', ()) or ()),
                    (getattr(self, 'default_params', None)
                     and isinstance(self.default_params.get(field, None), int)),
                    (getattr(self, 'default_params_add', None)
                     and isinstance(self.default_params_add.get(field, None), int)),
                    (getattr(self, 'default_params_edit', None)
                     and isinstance(self.default_params_edit.get(field, None), int))])

    def is_email_field(self, field):
        return ([getattr(self, 'email_fields', None),
                 getattr(self, 'email_fields_add', None),
                 getattr(self, 'email_fields_edit', None)] == [None, None, None] and 'email' in field) \
                or any([field in (getattr(self, 'email_fields', ()) or ()),
                        field in (getattr(self, 'email_fields_add', ()) or ()),
                        field in (getattr(self, 'email_fields_edit', ()) or ()), ])

    def is_int_field(self, field):
        return any([field in (getattr(self, 'int_fields', ()) or ()),
                    field in (getattr(self, 'int_fields_add', ()) or ()),
                    field in (getattr(self, 'int_fields_edit', ()) or ()), ])

    def is_file_field(self, field):
        def check_by_params_name(name):
            params = getattr(self, name, None)
            if not params:
                return False
            if isinstance(params.get(field, None), (file, ContentFile)):
                return True
            if (isinstance(params.get(field, None), (list, tuple))
                    and params.get(field)
                    and all([isinstance(el, (file, ContentFile)) for el in params.get(field)])):
                return True
            return False
        return field not in getattr(self, 'not_file', []) and \
                 any([field in self.FILE_FIELDS,
                      re.findall(r'(^|[^a-zA-Z])(file)', field),
                      check_by_params_name('default_params'),
                      check_by_params_name('default_params_add'),
                      check_by_params_name('default_params_edit')])

    def is_multiselect_field(self, field):
        return any([field in (getattr(self, 'multiselect_fields', ()) or ()),
                    field in (getattr(self, 'multiselect_fields_add', ()) or ()),
                    field in (getattr(self, 'multiselect_fields_edit', ()) or ()), ])

    def savepoint_rollback(self, sp):
        if isinstance(self, TestCase):
            transaction.savepoint_rollback(sp)

    def set_empty_value_for_field(self, params, field):
        mro_names = [m.__name__ for m in params[field].__class__.__mro__]
        if 'list' in mro_names or 'tuple' in mro_names or 'ValuesListQuerySet' in mro_names:
            params.pop(field)
        else:
            params[field] = ''

    def update_params(self, params):
        unique_keys = [k for el in self.all_unique.keys() for k in el if not k.endswith(self.non_field_error_key)]
        for key, v in params.iteritems():
            if key in unique_keys:
                default_value = v or (getattr(self, 'default_params', {}) or
                                      getattr(self, 'default_params_add', {}) or
                                      getattr(self, 'default_params_edit', {}) or {}).get(key, None)
                key_for_get_values = key
                if '-' in key:
                    key_for_get_values = '__'.join([key.split('-')[0].replace('_set', ''), key.split('-')[-1]])

                existing_values = [default_value]
                try:
                    existing_values = self.obj.objects.values_list(key_for_get_values, flat=True)
                except:
                    # FIXME: self.obj does not exists or FieldError
                    pass
                n = 0
                if default_value != '' and default_value is not None:
                    while n < 3 and params[key] in existing_values:
                        n += 1
                        params[key] = self.get_value_for_field(10, key)
            elif v and self.is_file_field(key):
                if isinstance(v, (list, tuple)):
                    file_value = self.get_value_for_field(10, key)
                    if not isinstance(file_value, list):
                        file_value = [file_value, ]
                    params[key] = file_value
                else:
                    params[key] = self.get_value_for_field(10, key)
        return params


class LoginMixIn(object):

    def user_login(self, username, password, **kwargs):
        additional_params = kwargs.get('additional_params', getattr(self, 'additional_params', {}))
        url_name = getattr(settings, 'LOGIN_URL_NAME', 'login')
        params = {'username': username, 'password': password,
                  'this_is_the_login_form': 1}
        csrf_cookie = self.client.cookies.get('csrftoken', '')
        if csrf_cookie:
            params['csrfmiddlewaretoken'] = csrf_cookie.value
        else:
            response = self.client.get(reverse(url_name), **additional_params)
            params['csrfmiddlewaretoken'] = response.cookies['csrftoken'].value
        params.update(get_captcha_codes())
        return self.client.post(reverse(url_name), params, **additional_params)

    def user_logout(self, **kwargs):
        additional_params = kwargs.get('additional_params', getattr(self, 'additional_params', {}))
        url_name = getattr(settings, 'LOGOUT_URL_NAME', 'auth_logout')
        return self.client.get(reverse(url_name), **additional_params)


class FormTestMixIn(GlobalTestMixIn):
    obj = None
    all_fields = None
    all_fields_add = None
    all_fields_edit = None
    choice_fields = []
    choice_fields_add = []
    choice_fields_edit = []
    choice_fields_with_value_in_error = []
    choice_fields_add_with_value_in_error = []
    choice_fields_edit_with_value_in_error = []
    default_params = None
    default_params_add = None
    default_params_edit = None
    date_fields = None
    digital_fields = None
    digital_fields_add = None
    digital_fields_edit = None
    disabled_fields = None
    disabled_fields_add = None
    disabled_fields_edit = None
    email_fields = None
    email_fields_add = None
    email_fields_edit = None
    exclude_from_check = []
    filter_params = None
    hidden_fields = None
    hidden_fields_add = None
    hidden_fields_edit = None
    int_fields = None
    int_fields_add = None
    int_fields_edit = None
    max_fields_length = []
    min_fields_length = []
    multiselect_fields = None
    multiselect_fields_add = None
    multiselect_fields_edit = None
    one_of_fields = None
    one_of_fields_add = None
    one_of_fields_edit = None
    required_fields = None
    required_fields_add = None
    required_fields_edit = None
    status_code_success_add = 200
    status_code_success_edit = 200
    status_code_error = 200
    unique_fields_add = None
    unique_fields_edit = None
    url_add = ''
    with_captcha = None

    def __init__(self, *args, **kwargs):
        super(FormTestMixIn, self).__init__(*args, **kwargs)
        if self.default_params is None:
            self.default_params = {}
        if not self.default_params_add:
            self.default_params_add = self.deepcopy(self.default_params)
        if not self.default_params_edit:
            self.default_params_edit = self.deepcopy(self.default_params)

        self.exclude_from_check_add = getattr(self, 'exclude_from_check_add', None) or copy(self.exclude_from_check)
        self.exclude_from_check_edit = getattr(self, 'exclude_from_check_edit', None) or copy(self.exclude_from_check)
        """set required fields attributes"""
        self._prepare_required_fields()

        self._prepare_disabled_fields()
        self._prepare_hidden_fields()

        """set all fields attributes"""
        self._prepare_all_form_fields_list()

        self._prepare_choice_fields()
        if self.with_captcha is None:
            self.with_captcha = any([(self.all_fields and 'captcha' in self.all_fields)
                                     or (self.all_fields_add and 'captcha' in self.all_fields_add)
                                     or (self.all_fields_edit and 'captcha' in self.all_fields_edit)])

        self._prepare_filter_params()
        self._prepare_date_fields()
        self._prepare_digital_fields()
        self._prepare_email_fields()
        self._prepare_multiselect_fields()
        self._prepare_one_of_fields()
        self.unique_fields_add = [el for el in self.all_unique.keys() if
                                  any([field in self.all_fields_add for field in el])]
        self.unique_fields_edit = [el for el in self.all_unique.keys() if
                                   any([field in self.all_fields_edit for field in el])]

        super(FormTestMixIn, self).__init__(*args, **kwargs)

    def _divide_common_and_related_fields(self, fields_list):
        related = []
        common = []
        for v in fields_list:
            if isinstance(v, (list, tuple)):
                related.append(v)
            else:
                common.append(v)
        return common, related

    def _get_all_fields_from_default_params(self, default_params):
        if not default_params:
            return []
        result_all_fields = []
        b = default_params.keys()
        b.sort()
        while b:
            el = b.pop(0)
            if el.endswith('_0'):
                if len(b) > 1:
                    if b[0] == el.replace('_0', '_1') and (len(b) <= 1 or
                                                           not b[1].startswith(el.replace('_0', ''))):
                        result_all_fields.append(el.replace('_0', ''))
                        b.pop(0)
                        continue
            if not el.endswith('_FORMS'):
                result_all_fields.append(el)
        return result_all_fields

    def _get_field_value_by_name(self, obj, field):
        if re.findall(r'[\w_]+\-\d+\-[\w_]+', field):
            value = getattr(getattr(obj, field.split('-')[0]).all()[0], field.split('-')[2])
        else:
            value = getattr(obj, field)
        return value

    def _get_required_from_related(self, fields_list):
        return [l[0] for l in fields_list]

    def _prepare_all_form_fields_list(self):
        if self.all_fields_add is None:
            if self.all_fields is None:
                self.all_fields_add = self._get_all_fields_from_default_params(self.default_params_add)
            else:
                self.all_fields_add = copy(self.all_fields)
        if self.all_fields_edit is None:
            if self.all_fields is None:
                self.all_fields_edit = self._get_all_fields_from_default_params(self.default_params_edit)
            else:
                self.all_fields_edit = copy(self.all_fields)

    def _prepare_choice_fields(self):
        self.choice_fields_add = (self.choice_fields_add or
                                  list(set(self.choice_fields).intersection(self.all_fields_add)))
        self.choice_fields_edit = (self.choice_fields_edit or
                                   list(set(self.choice_fields).intersection(self.all_fields_edit)))

        self.choice_fields_add_with_value_in_error = self.choice_fields_add_with_value_in_error or \
                list(set(self.choice_fields_with_value_in_error).intersection(self.all_fields_add))
        self.choice_fields_edit_with_value_in_error = self.choice_fields_edit_with_value_in_error or \
                list(set(self.choice_fields_with_value_in_error).intersection(self.all_fields_edit))

    def _prepare_date_fields(self):
        if self.date_fields is None:
            self.date_fields = [k for k in self.default_params_add.keys() if 'FORMS' not in k and 'date' in k]
            self.date_fields.extend([k for k in self.all_fields_add if 'FORMS' not in k and 'date' in k])
            self.date_fields.extend([k for k in self.default_params_edit.keys() if 'FORMS' not in k and 'date' in k])
            self.date_fields.extend([k for k in self.all_fields_edit if 'FORMS' not in k and 'date' in k])
            self.date_fields = set(self.date_fields)

    def _prepare_digital_fields(self):
        if self.digital_fields_add is None:
            if self.digital_fields is not None:
                self.digital_fields_add = set(copy(self.digital_fields)).intersection(self.default_params_add.keys())
            else:
                self.digital_fields_add = (set([k for k, v in self.default_params_add.iteritems() if
                                                'FORMS' not in k and isinstance(v, (float, int))
                                                                 and not isinstance(v, bool)])
                                           .difference(self.choice_fields_add)
                                           .difference(self.choice_fields_add_with_value_in_error))
        if self.digital_fields_edit is None:
            if self.digital_fields is not None:
                self.digital_fields_edit = set(copy(self.digital_fields)).intersection(self.default_params_edit.keys())
            else:
                self.digital_fields_edit = (set([k for k, v in self.default_params_edit.iteritems() if
                                                 'FORMS' not in k and isinstance(v, (float, int))
                                                                  and not isinstance(v, bool)])
                                            .difference(self.choice_fields_edit)
                                            .difference(self.choice_fields_edit_with_value_in_error))

        if self.int_fields_add is None:
            if self.int_fields is not None:
                self.int_fields_add = copy(self.int_fields)
            else:
                self.int_fields_add = set([k for k in self.digital_fields_add if
                                           isinstance(self.default_params_add[k], int)])
        if self.int_fields_edit is None:
            if self.int_fields is not None:
                self.int_fields_edit = copy(self.int_fields)
            else:
                self.int_fields_edit = set([k for k in self.digital_fields_edit if
                                            isinstance(self.default_params_edit[k], int)])

        self.digital_fields_add = set(list(self.digital_fields_add) + list(self.int_fields_add))
        self.digital_fields_edit = set(list(self.digital_fields_edit) + list(self.int_fields_edit))

    def _prepare_email_fields(self):
        if self.email_fields_add is None:
            if self.email_fields is not None:
                self.email_fields_add = set(copy(self.email_fields)).intersection(self.default_params_add.keys())
            else:
                self.email_fields_add = (set([k for k in self.default_params_add.iterkeys() if
                                              'FORMS' not in k and 'email' in k]))
        if self.email_fields_edit is None:
            if self.email_fields is not None:
                self.email_fields_edit = set(copy(self.email_fields)).intersection(self.default_params_edit.keys())
            else:
                self.email_fields_edit = (set([k for k in self.default_params_edit.iterkeys() if
                                               'FORMS' not in k and 'email' in k]))

    def _prepare_multiselect_fields(self):
        if self.multiselect_fields_add is None:
            if self.multiselect_fields is not None:
                self.multiselect_fields_add = set(copy(self.multiselect_fields)).intersection(self.default_params_add.keys())
            else:
                self.multiselect_fields_add = (set([k for k, v in self.default_params_add.iteritems() if
                                               'FORMS' not in k and isinstance(v, (list, tuple))]))
        if self.multiselect_fields_edit is None:
            if self.multiselect_fields is not None:
                self.multiselect_fields_edit = set(copy(self.multiselect_fields)).intersection(self.default_params_edit.keys())
            else:
                self.multiselect_fields_edit = (set([k for k, v in self.default_params_edit.iteritems() if
                                                'FORMS' not in k and isinstance(v, (list, tuple))]))

    def _prepare_disabled_fields(self):
        if self.disabled_fields_add is None:
            if self.disabled_fields is None:
                self.disabled_fields_add = ()
            else:
                self.disabled_fields_add = copy(self.disabled_fields)
        if self.disabled_fields_edit is None:
            if self.disabled_fields is None:
                self.disabled_fields_edit = ()
            else:
                self.disabled_fields_edit = copy(self.disabled_fields)

    def _prepare_filter_params(self):
        if self.filter_params is None:
            return
        _filter_params = {}
        for param in self.filter_params:
            if isinstance(param, (list, tuple)):
                _filter_params[param[0]] = param[1]
            else:
                _filter_params[param] = None
        self.filter_params = self.deepcopy(_filter_params)

    def _prepare_hidden_fields(self):
        if self.hidden_fields_add is None:
            self.hidden_fields_add = copy(self.hidden_fields)
        if self.hidden_fields_edit is None:
            self.hidden_fields_edit = copy(self.hidden_fields)

    def _prepare_one_of_fields(self):
        if self.one_of_fields_add is None and self.one_of_fields is not None:
            self.one_of_fields_add = [gr for gr in self.one_of_fields if
                                      len(set(gr).intersection(self.all_fields_add)) == len(gr)]
        if self.one_of_fields_edit is None and self.one_of_fields is not None:
            self.one_of_fields_edit = [gr for gr in self.one_of_fields if
                                       len(set(gr).intersection(self.all_fields_edit)) == len(gr)]

    def _prepare_required_fields(self):
        if self.required_fields_add is None:
            if self.required_fields is None:
                self.required_fields_add = self.default_params_add.keys()
            else:
                self.required_fields_add = copy(self.required_fields)
        if self.required_fields_edit is None:
            if self.required_fields is None:
                self.required_fields_edit = self.default_params_edit.keys()
            else:
                self.required_fields_edit = copy(self.required_fields)
        self.required_fields_add, self.required_related_fields_add = \
            self._divide_common_and_related_fields(self.required_fields_add)
        self.required_fields_edit, self.required_related_fields_edit = \
            self._divide_common_and_related_fields(self.required_fields_edit)

    def create_copy(self, obj_for_edit, fields_for_change=None):
        if fields_for_change is None:
            fields_for_change = set([v for el in self.all_unique.keys() for v in el
                                     if not v.endswith(self.non_field_error_key)])
        """get inline models dictionary"""
        inline_models_dict = {}
        for field in [ff for ff in fields_for_change if re.findall(r'[\w_]+\-\d+\-[\w_]+', ff)]:
            if field not in self.all_fields_edit:
                """only if user can change this field"""
                continue
            set_name = field.split('-')[0]
            inline_models_dict[set_name] = inline_models_dict.get(set_name, ()) + (field.split('-')[-1],)

        additional = {}
        for key in inline_models_dict.keys():
            additional[key] = getattr(obj_for_edit, key).all()
        obj = copy(obj_for_edit)
        obj.pk = None
        obj.id = None

        for field in [ff for ff in fields_for_change if not re.findall(r'[\w_]+\-\d+\-[\w_]+', ff)]:
            if field not in self.all_fields_edit:
                """only if user can change this field"""
                continue
            field_class = obj._meta.get_field_by_name(field)[0]
            value = self._get_field_value_by_name(obj_for_edit, field)
            n = 0
            if value:
                while n < 3 and value == self._get_field_value_by_name(obj_for_edit, field):
                    n += 1
                    value = self.get_value_for_field(10, field)
                    mro_names = [b.__name__ for b in field_class.__class__.__mro__]
                    if 'DateField' in mro_names:
                        try:
                            value = datetime.strptime(value, '%d.%m.%Y').date()
                        except:
                            pass
                    if 'ForeignKey' in mro_names:
                        value = field_class.rel.to.objects.get(pk=value)
                obj.__setattr__(field, value)
        obj.save()
        for set_name, values in additional.iteritems():
            for value in values:
                params = {}
                for f_name in self.get_object_fields(value):
                    f = value._meta.get_field_by_name(value, f_name)[0]
                    mro_names = set([m.__name__ for m in f.__class__.__mro__])
                    if 'AutoField' in mro_names:
                        continue
                    if mro_names.intersection(['ForeignKey', ]) and getattr(f.related, 'parent_model',
                                                                            f.related.model) == obj.__class__:
                        params[f_name] = obj
                    elif f_name in inline_models_dict[set_name]:
                        if getattr(self, 'choice_fields_values', {}).get(set_name + '-0-' + f_name, ''):
                            params[f_name] = f.rel.to.objects.get(pk=choice(self.choice_fields_values[set_name + '-0-' + f_name]))
                        else:
                            params[f_name] = f.rel.to.objects.all()[0] if mro_names.intersection(['ForeignKey', ]) \
                                                                       else self.get_value_for_field(10, f_name)
                    else:
                        params[f_name] = getattr(value, f_name)
                getattr(obj, set_name).add(value.__class__(**params))
        obj.save()
        return obj

    def fill_all_fields(self, fields, params):
        fields = set(fields)
        for field in [f for f in fields if not f.endswith('-DELETE')]:
            existing_value = params.get(field, None)
            if existing_value in (None, '', [], ()):
                if self.is_date_field(field):
                    l = [re.findall('%s_\d' % field, k) for k in params.keys()]
                    subfields = [item for sublist in l for item in sublist]
                    if subfields:
                        for subfield in subfields:
                            existing_value = params.get(subfield, None)
                            if existing_value in (None, '', [], ()):
                                params[field] = self.get_value_for_field(10, field)
                    else:
                        if self.get_field_by_name(self.obj, field)[0].__class__.__name__ == 'DateTimeField':
                            params[field + '_0'] = self.get_value_for_field(10, field + '_0')
                            params[field + '_1'] = self.get_value_for_field(10, field + '_1')
                        continue
                else:
                    params[field] = self.get_value_for_field(10, field)

    def get_digital_values_range(self, field):
        class_name = self.get_field_by_name(self.obj, field)[0].__class__.__name__
        max_value_from_params = dict(getattr(self, 'max_fields_length', ())).get(field, None)
        max_values = [max_value_from_params] if max_value_from_params is not None else []
        min_value_from_params = dict(getattr(self, 'min_fields_length', ())).get(field, None)
        min_values = [min_value_from_params] if min_value_from_params is not None else []
        if 'SmallInteger' in class_name:
            max_values.append(32767)
            if 'Positive' in class_name:
                min_values.append(0)
            else:
                min_values.append(-32767 - 1)
        elif 'Integer' in class_name:
            max_values.extend([2147483647, sys.maxint])
            if 'Positive' in class_name:
                min_values.append(0)
            else:
                min_values.extend([-2147483647 - 1, -sys.maxint - 1])
        elif 'Float' in class_name or 'Decimal' in class_name:
            max_values.append(sys.float_info.max)
            min_values.append(-sys.float_info.max)
        return {'max_values': set(max_values), 'min_values': set(min_values)}

    def get_gt_max(self, field, value):
        if ('Integer' in self.get_field_by_name(self.obj, field)[0].__class__.__name__) or \
                (isinstance(value, int) and value < 1.0e+10):
            return value + 1
        elif value < 1.0e+10:
            digits_count = len(str(value).split('.')[1])
            return value + round(0.1 ** digits_count, digits_count)
        else:
            value = value * 10
            if value == float('inf'):
                return None
            return value

    def get_gt_max_list(self, field, values_list):
        return [value for value in [self.get_gt_max(field, v) for v in values_list] if value]

    def get_lt_min(self, field, value):
        if ('Integer' in self.get_field_by_name(self.obj, field)[0].__class__.__name__) or \
                (isinstance(value, int) and value > -1.0e+10):
            return value - 1
        elif value > -1.0e+10:
            digits_count = len(str(value).split('.')[1])
            return value - round(0.1 ** digits_count, digits_count)
        else:
            value = value * 10
            if value == float('-inf'):
                return None
            return value

    def get_lt_min_list(self, field, values_list):
        return [value for value in [self.get_lt_min(field, v) for v in values_list] if value]

    def check_and_create_objects_for_filter(self, filter_name):
        if filter_name.endswith('exact'):
            filter_name = filter_name.replace('__exact', '')
        else:
            return
        next_obj = self.obj
        existing_values = None
        for i, name in enumerate(filter_name.split('__')):
            field = next_obj._meta.get_field_by_name(name)[0]
            field_class_name = field.__class__.__name__
            if field_class_name == 'ForeignKey':
                next_obj = field.rel.to
            elif field_class_name == 'RelatedObject':
                next_obj = getattr(field, 'related_model', field.model)
            else:
                if i == 0:  # is_public__exact
                    return
                existing_values = set(next_obj.objects.all().values_list(name, flat=True))
                break
        if existing_values is None:
            existing_values = next_obj.objects.all()
        if len(existing_values) > 1:
            return
        else:
            generate_random_obj(next_obj)

    def prepare_depend_from_one_of(self, one_of):
        res = {}
        for gr in one_of:
            for f in gr:
                values = res.get(f, [])
                values.extend(set(gr).difference((f,)))
                res[f] = list(set(values))
        return self.deepcopy(res)

    @only_with_obj
    @only_with(('url_list', 'filter_params'))
    def test_view_list_with_filter_positive(self):
        """
        @author: Polina Efremova
        @note: View list with filter positive
        """
        for field, value in self.filter_params.iteritems():
            value = value if value else ''
            try:
                response = self.client.get(self.get_url(self.url_list), {field: value}, **self.additional_params)
                self.assertEqual(response.status_code, 200)
            except:
                self.errors_append(text='For filter %s=%s' % (field, value))

    @only_with_obj
    @only_with(('url_list', 'filter_params'))
    def test_view_list_with_filter_negative(self):
        """
        @author: Polina Efremova
        @note: View list with filter negative
        """
        for field in self.filter_params.iterkeys():
            self.check_and_create_objects_for_filter(field)
            for value in ('qwe', '1', '0', 'йцу'):
                try:
                    response = self.client.get(self.get_url(self.url_list), {field: value}, follow=True,
                                               **self.additional_params)
                    self.assertEqual(response.status_code, 200)
                except:
                    self.errors_append(text='For filter %s=%s' % (field, value))


class FormAddTestMixIn(FormTestMixIn):

    def assert_objects_count_on_add(self, is_positive, initial_obj_count=0, additional=1):
        if is_positive:
            self.assertEqual(self.obj.objects.count(), initial_obj_count + additional,
                             u'Objects count after add = %s (expect %s)' %
                             (self.obj.objects.count(), initial_obj_count + additional))
        else:
            self.assertEqual(self.obj.objects.count(), initial_obj_count,
                             u'Objects count after wrong add = %s (expect %s)' %
                             (self.obj.objects.count(), initial_obj_count))

    def get_existing_obj(self):
        if 'get_obj_for_edit' in dir(self):
            return self.get_obj_for_edit()
        return self.obj.objects.all()[0]

    def get_existing_obj_with_filled(self, param_names):
        obj = self.get_existing_obj()
        if all([self._get_field_value_by_name(obj, field) for field in param_names]):
            return obj
        filters = Q()
        obj_related_objects = self.get_related_names(self.obj)
        for field in param_names:
            if not re.findall(r'[\w_]+\-\d+\-[\w_]+', field):
                filters &= ~Q(**{'%s__isnull' % field: True})
                field_class = self.get_field_by_name(self.obj, field)[0]
                if not set([c.__name__ for c in field_class.__class__.__mro__]).intersection(('RelatedField',
                                                                                              'ForeignKey',
                                                                                              'IntegerField')):
                    filters &= ~Q(**{field: ''})
            else:
                related_name = obj_related_objects.get(field.split('-')[0], field.split('-')[0])
                filters &= ~Q(**{'%s__%s__isnull' % (related_name, field.split('-')[-1]): True})
                field_class = self.get_field_by_name(self.obj, field)[0]
                if not set([c.__name__ for c in field_class.__class__.__mro__]).intersection(('RelatedField',
                                                                                              'ForeignKey',
                                                                                              'IntegerField')):
                    filters &= ~Q(**{'%s__%s' % (related_name, field.split('-')[-1]): ''})
        qs = self.obj.objects.filter(filters)
        if qs.exists():
            obj = qs[0]
        return obj

    @only_with_obj
    def test_add_page_fields_list_positive(self):
        """
        @author: Polina Efremova
        @note: check that all and only need fields is visible at add page
        """
        response = self.client.get(self.get_url(self.url_add), **self.additional_params)
        form_fields = self.get_fields_list_from_response(response)
        try:
            self.assert_form_equal(form_fields['visible_fields'], self.all_fields_add)
        except:
            self.errors_append(text='For visible fields')
        if self.disabled_fields_add is not None:
            try:
                self.assert_form_equal(form_fields['disabled_fields'], self.disabled_fields_add)
            except:
                self.errors_append(text='For disabled fields')
        if self.hidden_fields_add is not None:
            try:
                self.assert_form_equal(form_fields['hidden_fields'], self.hidden_fields_add)
            except:
                self.errors_append(text='For hidden fields')

    @only_with_obj
    def test_add_object_all_fields_filled_positive(self):
        """
        @author: Polina Efremova
        @note: Create object: fill all fields
        """
        initial_obj_count = self.obj.objects.count()
        old_pks = list(self.obj.objects.values_list('pk', flat=True))
        params = self.deepcopy(self.default_params_add)
        prepared_depends_fields = self.prepare_depend_from_one_of(self.one_of_fields_add) if self.one_of_fields_add else {}
        only_independent_fields = set(self.all_fields_add).difference(prepared_depends_fields.keys())
        for field in prepared_depends_fields.keys():
            self.set_empty_value_for_field(params, field)
        self.fill_all_fields(list(only_independent_fields) + self.required_fields_add +
                             self._get_required_from_related(self.required_related_fields_add), params)
        self.update_params(params)
        if self.with_captcha:
            self.client.get(self.get_url(self.url_add), **self.additional_params)
            params.update(get_captcha_codes())
        try:
            response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
            self.assert_no_form_errors(response)
            self.assertEqual(response.status_code, self.status_code_success_add,
                             'Status code %s != %s' % (response.status_code, self.status_code_success_add))
            self.assert_objects_count_on_add(True, initial_obj_count)
            new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
            exclude = getattr(self, 'exclude_from_check_add', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except:
            self.errors_append()

    @only_with_obj
    @only_with(('one_of_fields_add',))
    def test_add_object_with_group_all_fields_filled_positive(self):
        """
        @author: Polina Efremova
        @note: Create object: fill all fields
        """
        prepared_depends_fields = self.prepare_depend_from_one_of(self.one_of_fields_add)
        only_independent_fields = set(self.all_fields_add).difference(prepared_depends_fields.keys())
        default_params = self.deepcopy(self.default_params_add)
        for field in prepared_depends_fields.keys():
            self.set_empty_value_for_field(default_params, field)
        self.fill_all_fields(list(only_independent_fields), default_params)

        fields_from_groups = set(prepared_depends_fields.keys())
        for group in self.one_of_fields_add:
            field = choice(group)
            fields_from_groups = fields_from_groups.difference(prepared_depends_fields[field])
        self.fill_all_fields(fields_from_groups, default_params)
        new_object = None
        for group in self.one_of_fields_add:
            params = self.deepcopy(default_params)
            for field in group:
                """if unique fields"""
                if new_object:
                    self.obj.objects.filter(pk=new_object.pk).delete()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                initial_obj_count = self.obj.objects.count()
                for f in prepared_depends_fields[field]:
                    self.set_empty_value_for_field(params, f)
                self.fill_all_fields((field,), params)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                try:
                    response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                    self.assert_no_form_errors(response)
                    self.assertEqual(response.status_code, self.status_code_success_add,
                                     'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                    self.assert_objects_count_on_add(True, initial_obj_count)
                    new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                    exclude = getattr(self, 'exclude_from_check_add', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except:
                    self.errors_append(text='For filled %s from group %s' % (field, repr(group)))

    @only_with_obj
    def test_add_object_only_required_fields_positive(self):
        """
        @author: Polina Efremova
        @note: Create object: fill only required fields
        """
        initial_obj_count = self.obj.objects.count()
        old_pks = list(self.obj.objects.values_list('pk', flat=True))
        params = self.deepcopy(self.default_params_add)
        required_fields = self.required_fields_add + \
                          self._get_required_from_related(self.required_related_fields_add)
        self.update_params(params)
        new_object = None
        for field in set(params.keys()).difference(required_fields):
            self.set_empty_value_for_field(params, field)
        for field in required_fields:
            params[field] = params[field] if params[field] not in (None, '') else \
                self.get_value_for_field(randint(dict(self.min_fields_length).get(field, 1),
                                                 dict(self.max_fields_length).get(field, 10)), field)
        if self.with_captcha:
            self.client.get(self.get_url(self.url_add), **self.additional_params)
            params.update(get_captcha_codes())
        try:
            response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
            self.assert_no_form_errors(response)
            self.assertEqual(response.status_code, self.status_code_success_add,
                             'Status code %s != %s' % (response.status_code, self.status_code_success_add))
            self.assert_objects_count_on_add(True, initial_obj_count)
            new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
            exclude = getattr(self, 'exclude_from_check_add', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except:
            self.errors_append()

        """если хотя бы одно поле из группы заполнено, объект создается"""
        for group in self.required_related_fields_add:
            _params = self.deepcopy(self.default_params_add)
            for field in group:
                self.set_empty_value_for_field(_params, field)
            for field in group:
                """if unique fields"""
                if new_object:
                    self.obj.objects.filter(pk=new_object.pk).delete()
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(_params)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = params[field] if params[field] not in (None, '') else \
                        self.get_value_for_field(randint(dict(self.min_fields_length).get(field, 1),
                                                 dict(self.max_fields_length).get(field, 10)), field)
                try:
                    response = self.client.post(self.get_url(self.url_add), params, follow=True,
                                                **self.additional_params)
                    self.assert_no_form_errors(response)
                    self.assertEqual(response.status_code, self.status_code_success_add,
                                     'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                    self.assert_objects_count_on_add(True, initial_obj_count)
                    new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                    exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except:
                    self.errors_append(text='For filled field %s from group "%s"' %
                                       (field, str(group)))

    @only_with_obj
    def test_add_object_empty_required_fields_negative(self):
        """
        @author: Polina Efremova
        @note: Try create object: empty required fields
        """
        self.client.get(self.get_url(self.url_add), **self.additional_params)
        message_type = 'required'
        """обязательные поля должны быть заполнены"""
        for field in [f for f in self.required_fields_add if 'FORMS' not in f]:
            initial_obj_count = self.obj.objects.count()
            sp = transaction.savepoint()
            try:
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                self.set_empty_value_for_field(params, field)
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_objects_count_on_add(False, initial_obj_count)
                error_message = self.get_error_message(message_type, field)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty field "%s"' % field)

        """обязательно хотя бы одно поле из группы (все пустые)"""
        for group in self.required_related_fields_add:
            initial_obj_count = self.obj.objects.count()
            sp = transaction.savepoint()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            for field in group:
                self.set_empty_value_for_field(params, field)
            if self.with_captcha:
                self.client.get(self.get_url(self.url_add), **self.additional_params)
                params.update(get_captcha_codes())
            try:
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, group, error_field=self.non_field_error_key)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty group "%s"' % str(group))

    @only_with_obj
    def test_add_object_without_required_fields_negative(self):
        """
        @author: Polina Efremova
        @note: Try create object: required fields are not exists in params
        """
        self.client.get(self.get_url(self.url_add), **self.additional_params)
        message_type = 'required'
        """обязательные поля должны быть заполнены"""
        for field in [f for f in self.required_fields_add if 'FORMS' not in f]:
            initial_obj_count = self.obj.objects.count()
            sp = transaction.savepoint()
            try:
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params.pop(field)
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_objects_count_on_add(False, initial_obj_count)
                error_message = self.get_error_message(message_type, field)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For params without field "%s"' % field)

        """обязательно хотя бы одно поле из группы (все пустые)"""
        for group in self.required_related_fields_add:
            initial_obj_count = self.obj.objects.count()
            sp = transaction.savepoint()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            for field in group:
                params.pop(field)
            if self.with_captcha:
                self.client.get(self.get_url(self.url_add), **self.additional_params)
                params.update(get_captcha_codes())
            try:
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, group, error_field=self.non_field_error_key)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For params without group "%s"' % str(group))

    @only_with_obj
    def test_add_object_max_length_values_positive(self):
        """
        @author: Polina Efremova
        @note: Create object: fill all fields with maximum length values
        """
        new_object = None
        for field, length in [el for el in self.max_fields_length if el[0] in
                              self.all_fields_add and el[0] not in getattr(self, 'digital_fields_add', ())]:
            sp = transaction.savepoint()
            """if unique fields"""
            if new_object:
                self.obj.objects.filter(pk=new_object.pk).delete()
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)

                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = self.get_value_for_field(length, field)
                value = self.get_value_for_error_message(field, params[field])
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_add,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                self.assert_objects_count_on_add(True, initial_obj_count)
                new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' % (field, length, value))

    @only_with_obj
    def test_add_object_values_length_gt_max_negative(self):
        """
        @author: Polina Efremova
        @note: Create object: values length > maximum
        """
        message_type = 'max_length'
        for field, length in [el for el in self.max_fields_length if el[0] in
                              self.all_fields_add and el[0] not in getattr(self, 'digital_fields_add', ())]:
            sp = transaction.savepoint()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            if self.with_captcha:
                self.client.get(self.get_url(self.url_add), **self.additional_params)
                params.update(get_captcha_codes())
            current_length = length + 1
            params[field] = self.get_value_for_field(current_length, field)
            try:
                initial_obj_count = self.obj.objects.count()
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field,)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, current_length, params[field]))

    @only_with_obj
    def test_add_object_values_length_lt_min_negative(self):
        """
        @author: Polina Efremova
        @note: Create object: values length < minimum
        """
        message_type = 'min_length'
        for field, length in [el for el in self.min_fields_length if el[0] in
                              self.all_fields_add and el[0] not in getattr(self, 'digital_fields_add', ())]:
            sp = transaction.savepoint()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            if self.with_captcha:
                self.client.get(self.get_url(self.url_add), **self.additional_params)
                params.update(get_captcha_codes())
            current_length = length - 1
            params[field] = self.get_value_for_field(current_length, field)
            try:
                initial_obj_count = self.obj.objects.count()
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field,)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, current_length, params[field]))

    @only_with_obj
    def test_add_object_with_wrong_choices_negative(self):
        """
        @author: Polina Efremova
        @note: Try create object with choices, that not exists
        """
        message_type = 'wrong_value'
        for field in set(tuple(self.choice_fields_add) + tuple(self.choice_fields_add_with_value_in_error)):
            params = self.deepcopy(self.default_params_add)
            for value in (u'qwe', u'12345678', u'йцу'):
                self.update_params(params)
                initial_obj_count = self.obj.objects.count()
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = value
                try:
                    response = self.client.post(self.get_url(self.url_add), params, **self.additional_params)
                    self.assert_objects_count_on_add(False, initial_obj_count)
                    _locals = {'field': field,
                               'value': value if field in self.choice_fields_add_with_value_in_error else ''}
                    self.get_all_form_errors(response)
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=_locals))
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.errors_append(text='For %s value "%s"' % (field, value.encode('utf-8')))

    @only_with_obj
    @only_with(('multiselect_fields_add',))
    def test_add_object_with_wrong_multiselect_choices_negative(self):
        """
        @author: Polina Efremova
        @note: Try create object with choices in multiselect, that not exists
        """
        message_type = 'wrong_value'
        for field in self.multiselect_fields_add:
            params = self.deepcopy(self.default_params_add)
            for value in (u'12345678',):
                self.update_params(params)
                initial_obj_count = self.obj.objects.count()
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = [value, ]
                try:
                    response = self.client.post(self.get_url(self.url_add), params, **self.additional_params)
                    self.assert_objects_count_on_add(False, initial_obj_count)
                    _locals = {'field': field, 'value': value}
                    self.get_all_form_errors(response)
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=_locals))
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.errors_append(text='For %s value "%s"' % (field, value.encode('utf-8')))

    @only_with_obj
    @only_with(('unique_fields_add',))
    def test_add_object_unique_already_exists_negative(self):
        """
        @author: Polina Efremova
        @note: Try add object with unique field values, that already used in other objects
        """
        message_type = 'unique'
        """values exactly equals"""
        for el in self.unique_fields_add:
            field = self.all_unique[el]
            existing_obj = self.get_existing_obj_with_filled(el)
            sp = transaction.savepoint()
            initial_obj_count = self.obj.objects.count()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            if self.with_captcha:
                self.client.get(self.get_url(self.url_add), **self.additional_params)
                params.update(get_captcha_codes())
            for el_field in el:
                if el_field not in self.all_fields_add:
                    continue
                value = self._get_field_value_by_name(existing_obj, el_field)
                params[el_field] = self.get_params_according_to_type(value, u'')[0]
            try:
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field)

                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' %
                                                             (field, params[field]) for field
                                                             in el if field in params.keys()))

        """values is in uppercase"""
        for el in self.unique_fields_add:
            field = self.all_unique[el]
            existing_obj = self.get_existing_obj_with_filled(el)
            params = self.deepcopy(self.default_params_add)
            if not any([isinstance(params[el_field], (str, unicode)) for el_field in el]):
                continue
            sp = transaction.savepoint()
            initial_obj_count = self.obj.objects.count()
            self.update_params(params)
            if self.with_captcha:
                self.client.get(self.get_url(self.url_add), **self.additional_params)
                params.update(get_captcha_codes())
            for el_field in el:
                if el_field not in self.all_fields_add:
                    continue
                value = self._get_field_value_by_name(existing_obj, el_field)
                params[el_field] = self.get_params_according_to_type(value, u'')[0]
                if isinstance(params[el_field], (str, unicode)):
                    params[el_field] = params[el_field].upper()
            try:
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' %
                                                             (field, params[field]) for field
                                                             in el if field in params.keys()))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_wrong_values_in_digital_negative(self):
        """
        @author: Polina Efremova
        @note: Try add obj with wrong values in digital fields
        """
        for field in [f for f in self.digital_fields_add]:
            message_type = 'wrong_value_int' if field in self.int_fields_add else 'wrong_value_digital'
            for value in ('q', u'й', 'NaN', 'inf', '-inf'):
                initial_obj_count = self.obj.objects.count()
                sp = transaction.savepoint()
                try:
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_add), **self.additional_params)
                        params.update(get_captcha_codes())
                    params[field] = value
                    response = self.client.post(self.get_url(self.url_add), params, follow=True,
                                                **self.additional_params)
                    self.assert_objects_count_on_add(False, initial_obj_count)
                    error_message = self.get_error_message(message_type, field)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value.encode('utf-8'), field))

    @only_with_obj
    @only_with(('email_fields_add',))
    def test_add_object_wrong_values_in_email_negative(self):
        """
        @author: Polina Efremova
        @note: Try add obj with wrong values in email fields
        """
        message_type = 'wrong_value_email'
        for field in [f for f in self.email_fields_add]:
            for value in ('q', u'й', 'qwe@rty', u'qw@йц', '@qwe', 'qwe@'):
                initial_obj_count = self.obj.objects.count()
                sp = transaction.savepoint()
                try:
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_add), **self.additional_params)
                        params.update(get_captcha_codes())
                    params[field] = value
                    response = self.client.post(self.get_url(self.url_add), params, follow=True,
                                                **self.additional_params)
                    self.assert_objects_count_on_add(False, initial_obj_count)
                    error_message = self.get_error_message(message_type, field)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value.encode('utf-8'), field))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_value_max_in_digital_positive(self):
        """
        @author: Polina Efremova
        @note: Add obj with value in digital fields == max
        """
        new_object = None
        for field in [f for f in self.digital_fields_add]:
            max_values = self.get_digital_values_range(field)['max_values']
            if not max_values:
                continue
            value = min(max_values)
            sp = transaction.savepoint()
            """if unique fields"""
            if new_object:
                self.obj.objects.filter(pk=new_object.pk).delete()
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = value
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_add,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                self.assert_objects_count_on_add(True, initial_obj_count)
                new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with value "%s"' % (field, params[field]))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_value_gt_max_in_digital_negative(self):
        """
        @author: Polina Efremova
        @note: Try add obj with value in digital fields > max
        """
        message_type = 'max_length_digital'
        for field in [f for f in self.digital_fields_add]:
            max_value = min(self.get_digital_values_range(field)['max_values'])
            for value in self.get_gt_max_list(field, self.get_digital_values_range(field)['max_values']):
                initial_obj_count = self.obj.objects.count()
                sp = transaction.savepoint()
                try:
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_add), **self.additional_params)
                        params.update(get_captcha_codes())
                    params[field] = value
                    response = self.client.post(self.get_url(self.url_add), params, follow=True,
                                                **self.additional_params)
                    self.assert_objects_count_on_add(False, initial_obj_count)
                    error_message = self.get_error_message(message_type, field)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_value_min_in_digital_positive(self):
        """
        @author: Polina Efremova
        @note: Add obj with value in digital fields == min
        """
        new_object = None
        for field in [f for f in self.digital_fields_add]:
            min_values = self.get_digital_values_range(field)['min_values']
            if not min_values:
                continue
            value = max(min_values)
            sp = transaction.savepoint()
            """if unique fields"""
            if new_object:
                self.obj.objects.filter(pk=new_object.pk).delete()
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = value
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_add,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                self.assert_objects_count_on_add(True, initial_obj_count)
                new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with value "%s"' % (field, params[field]))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_value_lt_min_in_digital_negative(self):
        """
        @author: Polina Efremova
        @note: Try add obj with value in digital fields < min
        """
        message_type = 'min_length_digital'
        for field in [f for f in self.digital_fields_add]:
            min_value = max(self.get_digital_values_range(field)['min_values'])
            for value in self.get_lt_min_list(field, self.get_digital_values_range(field)['min_values']):
                initial_obj_count = self.obj.objects.count()
                sp = transaction.savepoint()
                try:
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_add), **self.additional_params)
                        params.update(get_captcha_codes())
                    params[field] = value
                    response = self.client.post(self.get_url(self.url_add), params, follow=True,
                                                **self.additional_params)
                    self.assert_objects_count_on_add(False, initial_obj_count)
                    error_message = self.get_error_message(message_type, field)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('disabled_fields_add',))
    def test_add_disabled_fields_values_negative(self):
        """
        @author: Polina Efremova
        @note: Try add obj with filled disabled fields
        """
        new_object = None
        for field in self.disabled_fields_add:
            sp = transaction.savepoint()
            if new_object:
                self.obj.objects.filter(pk=new_object.pk).delete()
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = params.get(field, None) or self.get_value_for_field(10, field)
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_add,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                self.assert_objects_count_on_add(True, initial_obj_count)
                new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                self.assertNotEqual(self.get_value_for_compare(new_object, field), params[field])
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, {field: ''}, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s"' % field)

    @only_with_obj
    @only_with(('one_of_fields_add',))
    def test_add_object_one_of_fields_all_filled_negative(self):
        """
        @author: Polina Efremova
        @note: Try add object with all filled fields, that should be filled singly
        """
        message_type = 'one_of'
        for group in self.one_of_fields_add:
            for filled_group in tuple(set([(el, additional_el) for i, el in enumerate(group) for additional_el in
                                           group[i + 1:]]).difference(set(self.one_of_fields_add).difference(group))) + \
                                           (group,):
                sp = transaction.savepoint()
                try:
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_add), **self.additional_params)
                        params.update(get_captcha_codes())
                    self.fill_all_fields(filled_group, params)
                    initial_obj_count = self.obj.objects.count()
                    response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                    self.assert_objects_count_on_add(False, initial_obj_count)
                    error_message = self.get_error_message(message_type, group)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text=u'For filled %s fields from group %s' % (str(filled_group), str(group)))


class FormEditTestMixIn(FormTestMixIn):

    url_edit = ''

    def get_obj_id_for_edit(self):
        if '%' not in self.url_edit and '/' in self.url_edit:
            return int(re.findall(r"/(\d+)/", self.url_edit)[0])
        return self.obj.objects.all()[0].pk

    def get_obj_for_edit(self):
        return self.obj.objects.get(pk=self.get_obj_id_for_edit())

    def get_other_obj_with_filled(self, param_names, other_obj):
        obj = self.get_obj_for_edit()
        if all([self._get_field_value_by_name(obj, field) for field in param_names]) and other_obj.pk != obj.pk:
            return obj
        obj_related_objects = self.get_related_names(self.obj)
        filters = ~Q(pk=other_obj.pk)
        for field in param_names:
            if not re.findall(r'[\w_]+\-\d+\-[\w_]+', field):
                filters &= ~Q(**{'%s__isnull' % field: True})
                field_class = self.get_field_by_name(self.obj, field)[0]
                if not set([c.__name__ for c in field_class.__class__.__mro__])\
                        .intersection(('RelatedField', 'ForeignKey', 'IntegerField', 'DateField')):
                    filters &= ~Q(**{field: ''})
            else:
                related_name = obj_related_objects.get(field.split('-')[0], field.split('-')[0])
                filters &= ~Q(**{'%s__%s__isnull' % (related_name, field.split('-')[-1]): True})
                field_class = self.get_field_by_name(self.obj, field)[0]
                if not set([c.__name__ for c in field_class.__class__.__mro__])\
                        .intersection(('RelatedField', 'ForeignKey', 'IntegerField', 'DateField')):
                    filters &= ~Q(**{'%s__%s' % (related_name, field.split('-')[-1]): ''})
        qs = self.obj.objects.filter(filters)
        if qs.exists():
            return qs[0]
        else:
            return self.create_copy(other_obj)

    @only_with_obj
    def test_edit_page_fields_list_positive(self):
        """
        @author: Polina Efremova
        @note: check that all and only need fields is visible at edit page
        """
        obj_pk = self.get_obj_id_for_edit()
        response = self.client.get(self.get_url(self.url_edit, (obj_pk,)), **self.additional_params)
        form_fields = self.get_fields_list_from_response(response)
        try:
            self.assert_form_equal(form_fields['visible_fields'], self.all_fields_edit)
        except:
            self.errors_append(text='For visible fields')
        if self.disabled_fields_edit is not None:
            try:
                self.assert_form_equal(form_fields['disabled_fields'], self.disabled_fields_edit)
            except:
                self.errors_append(text='For disabled fields')
        if self.hidden_fields_edit is not None:
            try:
                self.assert_form_equal(form_fields['hidden_fields'], self.hidden_fields_edit)
            except:
                self.errors_append(text='For hidden fields')

    @only_with_obj
    def test_edit_object_all_fields_filled_positive(self):
        """
        @author: Polina Efremova
        @note: Edit object: fill all fields
        """
        obj_for_edit = self.get_obj_for_edit()
        params = self.deepcopy(self.default_params_edit)
        prepared_depends_fields = self.prepare_depend_from_one_of(self.one_of_fields_edit) if self.one_of_fields_edit else {}
        only_independent_fields = set(self.all_fields_edit).difference(prepared_depends_fields.keys())
        for field in prepared_depends_fields.keys():
            self.set_empty_value_for_field(params, field)
        self.fill_all_fields(list(only_independent_fields) + self.required_fields_edit +
                             self._get_required_from_related(self.required_related_fields_edit), params)
        self.update_params(params)
        if self.with_captcha:
            self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
            params.update(get_captcha_codes())
        try:
            response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                        params, follow=True, **self.additional_params)
            self.assert_no_form_errors(response)
            self.assertEqual(response.status_code, self.status_code_success_edit,
                             'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
            new_object = self.obj.objects.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except:
            self.errors_append()

    @only_with_obj
    @only_with(('one_of_fields_edit',))
    def test_edit_object_with_group_all_fields_filled_positive(self):
        """
        @author: Polina Efremova
        @note: Edit object: fill all fields
        """
        prepared_depends_fields = self.prepare_depend_from_one_of(self.one_of_fields_edit)
        only_independent_fields = set(self.all_fields_edit).difference(prepared_depends_fields.keys())
        self.get_obj_for_edit()
        default_params = self.deepcopy(self.default_params_edit)
        self.fill_all_fields(only_independent_fields, default_params)
        for field in prepared_depends_fields.keys():
            self.set_empty_value_for_field(default_params, field)

        fields_from_groups = set(prepared_depends_fields.keys())
        for group in self.one_of_fields_edit:
            field = choice(group)
            fields_from_groups = fields_from_groups.difference(prepared_depends_fields[field])
        self.fill_all_fields(fields_from_groups, default_params)
        for group in self.one_of_fields_edit:
            for field in group:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(default_params)
                for f in prepared_depends_fields[field]:
                    self.set_empty_value_for_field(params, f)
                self.fill_all_fields((field,), params)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit), **self.additional_params)
                    params.update(get_captcha_codes())
                try:
                    response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)), params, follow=True, **self.additional_params)
                    self.assert_no_form_errors(response)
                    self.assertEqual(response.status_code, self.status_code_success_edit,
                                     'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                    new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                    exclude = getattr(self, 'exclude_from_check_edit', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except:
                    self.errors_append(text='For filled %s from group %s' % (field, repr(group)))

    @only_with_obj
    def test_edit_object_only_required_fields_positive(self):
        """
        @author: Polina Efremova
        @note: Edit object: fill only required fields
        """
        obj_for_edit = self.get_obj_for_edit()
        params = self.deepcopy(self.default_params_edit)
        if self.with_captcha:
            self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
            params.update(get_captcha_codes())
        required_fields = self.required_fields_edit + self._get_required_from_related(self.required_related_fields_edit)
        self.update_params(params)
        for field in set(params.keys()).difference(required_fields):
            self.set_empty_value_for_field(params, field)
        for field in required_fields:
            params[field] = params[field] if params[field] not in (None, '') else \
                self.get_value_for_field(randint(dict(self.min_fields_length).get(field, 1),
                                                 dict(self.max_fields_length).get(field, 10)), field)
        try:
            response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                        params, follow=True, **self.additional_params)
            self.assert_no_form_errors(response)
            self.assertEqual(response.status_code, self.status_code_success_edit,
                             'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
            new_object = self.obj.objects.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except:
            self.errors_append()

        """если хотя бы одно поле из группы заполнено, объект редактируется"""
        for group in self.required_related_fields_edit:
            obj_for_edit = self.get_obj_for_edit()
            _params = self.deepcopy(self.default_params_edit)
            for field in group:
                self.set_empty_value_for_field(_params, field)
            for field in group:
                params = self.deepcopy(_params)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = params[field] if params[field] not in (None, '') else \
                        self.get_value_for_field(randint(dict(self.min_fields_length).get(field, 1),
                                                         dict(self.max_fields_length).get(field, 10)), field)
                try:
                    response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                                params, follow=True, **self.additional_params)
                    self.assert_no_form_errors(response)
                    self.assertEqual(response.status_code, self.status_code_success_edit,
                                     'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                    new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                    exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except:
                    self.errors_append(text='For filled field %s from group "%s"' %
                                       (field, str(group)))

    @only_with_obj
    def test_edit_object_empty_required_fields_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: empty required fields
        """
        message_type = 'required'
        for field in [f for f in self.required_fields_edit if 'FORMS' not in f]:
            sp = transaction.savepoint()
            test_obj = self.get_obj_for_edit()
            try:
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                self.set_empty_value_for_field(params, field)
                response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                            params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                new_object = self.obj.objects.get(pk=test_obj.pk)
                self.assert_objects_equal(new_object, test_obj)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty field "%s"' % field)

        """обязательно хотя бы одно поле из группы (все пустые)"""
        for group in self.required_related_fields_edit:
            sp = transaction.savepoint()
            test_obj = self.get_obj_for_edit()
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            for field in group:
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                self.set_empty_value_for_field(params, field)
            try:
                response = self.client.post(self.get_url(self.url_edit, (test_obj.id,)),
                                            params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, group, error_field=self.non_field_error_key)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                new_object = self.obj.objects.get(pk=test_obj.pk)
                self.assert_objects_equal(new_object, test_obj)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty group "%s"' % str(group))

    @only_with_obj
    def test_edit_object_without_required_fields_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: required fields are not exists in params
        """
        message_type = 'required'
        for field in [f for f in self.required_fields_edit if 'FORMS' not in f and not re.findall(r'.+?\-\d+\-.+?', f)]:
            sp = transaction.savepoint()
            try:
                test_obj = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                params.pop(field)
                response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                            params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                new_object = self.obj.objects.get(pk=test_obj.pk)
                self.assert_objects_equal(new_object, test_obj)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For params without field "%s"' % field)

        """обязательно хотя бы одно поле из группы (все пустые)"""
        for group in self.required_related_fields_edit:
            test_obj = self.get_obj_for_edit()
            sp = transaction.savepoint()
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            for field in group:
                params.pop(field)
            if self.with_captcha:
                self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                params.update(get_captcha_codes())
            try:
                response = self.client.post(self.get_url(self.url_edit, (test_obj.id,)),
                                            params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, group, error_field=self.non_field_error_key)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                new_object = self.obj.objects.get(pk=test_obj.pk)
                self.assert_objects_equal(new_object, test_obj)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For params without group "%s"' % str(group))

    @only_with_obj
    def test_edit_not_exists_object_negative(self):
        """
        @author: Polina Efremova
        @note: Try open edit page of object with invalid id
        """
        for value in ('9999999', '2147483648', 'qwerty', 'йцу'):
            sp = transaction.savepoint()
            try:
                response = self.client.get(self.get_url_for_negative(self.url_edit, (value,)),
                                           follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 404, 'Status code %s != 404' % response.status_code)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For value %s error' % value)

    @only_with_obj
    def test_edit_object_max_length_values_positive(self):
        """
        @author: Polina Efremova
        @note: Edit object: fill all fields with maximum length values
        """
        for field, length in [el for el in self.max_fields_length if el[0] in
                              self.all_fields_edit and el[0] not in getattr(self, 'digital_fields_edit', ())]:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = self.get_value_for_field(length, field)
                value = self.get_value_for_error_message(field, params[field])
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_edit,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)

                if self.is_file_field(field):
                    obj_for_edit = self.obj.objects.get(pk=obj_for_edit.pk)
                    self.update_params(params)
                    params[field] = ''
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                        params.update(get_captcha_codes())
                    _errors = []
                    try:
                        response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                                    params, follow=True, **self.additional_params)
                        self.assert_no_form_errors(response)
                        self.assertEqual(response.status_code, self.status_code_success_edit,
                                         'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                        new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                        exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                        self.assert_object_fields(new_object, params, exclude=exclude,
                                                  other_values={field: self._get_field_value_by_name(obj_for_edit, field)})
                    except:
                        self.errors_append(_errors, text='Second save with file max length')
                    if _errors:
                        raise Exception(format_errors(_errors))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, length, value))

    @only_with_obj
    def test_edit_object_values_length_gt_max_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: values length > maximum
        """
        message_type = 'max_length'
        for field, length in [el for el in self.max_fields_length if el[0] in
                              self.all_fields_edit and el[0] not in getattr(self, 'digital_fields_edit', ())]:
            sp = transaction.savepoint()
            try:
                test_obj = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                current_length = length + 1
                params[field] = self.get_value_for_field(current_length, field)
                response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                            params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field, length)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                new_object = self.obj.objects.get(pk=test_obj.pk)
                self.assert_objects_equal(new_object, test_obj)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, current_length, params[field]))

    @only_with_obj
    def test_edit_object_values_length_lt_min_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: values length < minimum
        """
        message_type = 'min_length'
        for field, length in [el for el in self.min_fields_length if el[0] in
                              self.all_fields_edit and el[0] not in getattr(self, 'digital_fields_edit', ())]:
            sp = transaction.savepoint()
            try:
                test_obj = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                current_length = length - 1
                params[field] = self.get_value_for_field(current_length, field)
                response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                            params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field, length)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                new_object = self.obj.objects.get(pk=test_obj.pk)
                self.assert_objects_equal(new_object, test_obj)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, current_length, params[field]))

    @only_with_obj
    def test_edit_object_with_wrong_choices_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: choice values to choices, that not exists
        """
        message_type = 'wrong_value'
        for field in set(tuple(self.choice_fields_edit) + tuple(self.choice_fields_edit_with_value_in_error)):
            for value in (u'qwe', u'12345678', u'йцу'):
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                self.update_params(params)
                params[field] = value
                try:
                    response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                                params, follow=True, **self.additional_params)
                    _locals = {'field': field,
                               'value': value if field in self.choice_fields_edit_with_value_in_error else ''}
                    error_message = self.get_error_message(message_type, field, locals=_locals)
                    self.assertEqual(self.get_all_form_errors(response),
                                     error_message)
                    new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                    self.assert_objects_equal(new_object, obj_for_edit)
                    self.assertEqual(response.status_code, self.status_code_error,
                                    'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.errors_append(text='For %s value "%s"' % (field, value.encode('utf-8')))

    @only_with_obj
    @only_with(('multiselect_fields_edit',))
    def test_edit_object_with_wrong_multiselect_choices_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: choice values to multiselect, that not exists
        """
        message_type = 'wrong_value'
        for field in self.multiselect_fields_edit:
            for value in (u'12345678',):
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                self.update_params(params)
                params[field] = [value, ]
                try:
                    response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                                params, follow=True, **self.additional_params)
                    _locals = {'field': field, 'value': value}
                    error_message = self.get_error_message(message_type, field, locals=_locals)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                    self.assert_objects_equal(new_object, obj_for_edit)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.errors_append(text='For %s value "%s"' % (field, value.encode('utf-8')))

    @only_with_obj
    @only_with(('unique_fields_edit',))
    def test_edit_object_unique_already_exists_negative(self):
        """
        @author: Polina Efremova
        @note: Try change object unique field values, to values, that already used in other objects
        """
        message_type = 'unique'
        """values exactly equals"""
        for el in self.unique_fields_edit:
            field = self.all_unique[el]
            obj_for_edit = self.get_obj_for_edit()
            existing_obj = self.get_other_obj_with_filled(el, obj_for_edit)
            sp = transaction.savepoint()
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            if self.with_captcha:
                self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                params.update(get_captcha_codes())
            for el_field in el:
                if el_field not in self.all_fields_edit:
                    """only if user can change this field"""
                    continue
                value = self._get_field_value_by_name(existing_obj, el_field)
                params[el_field] = self.get_params_according_to_type(value, u'')[0]
            try:
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                self.assert_objects_equal(new_object, obj_for_edit)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' %
                                                             (field, params[field]) for field
                                                             in el if field in params.keys()))
        """values is in uppercase"""
        for el in self.unique_fields_edit:
            field = self.all_unique[el]
            obj_for_edit = self.get_obj_for_edit()
            existing_obj = self.get_other_obj_with_filled(el, obj_for_edit)
            params = self.deepcopy(self.default_params_edit)
            if not any([isinstance(params[el_field], (str, unicode)) for el_field in el]):
                continue
            sp = transaction.savepoint()
            self.update_params(params)
            if self.with_captcha:
                self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                params.update(get_captcha_codes())
            for el_field in el:
                if el_field not in self.all_fields_edit:
                    """only if user can change this field"""
                    continue
                value = self._get_field_value_by_name(existing_obj, el_field)
                params[el_field] = self.get_params_according_to_type(value, u'')[0]
                if isinstance(params[el_field], (str, unicode)):
                    params[el_field] = params[el_field].upper()
            try:
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                error_message = self.get_error_message(message_type, field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                self.assert_objects_equal(new_object, obj_for_edit)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' % (field, params[field])
                                                             for field in el if field in params.keys()))

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_wrong_values_in_digital_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: wrong values in digital fields
        """
        for field in self.digital_fields_edit:
            message_type = 'wrong_value_int' if field in self.int_fields_edit else 'wrong_value_digital'
            for value in ('q', u'й', 'NaN', 'inf', '-inf'):
                sp = transaction.savepoint()
                try:
                    test_obj = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                        params.update(get_captcha_codes())
                    params[field] = value
                    response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                                params, follow=True, **self.additional_params)
                    error_message = self.get_error_message(message_type, field)
                    self.assertEqual(self.get_all_form_errors(response),
                                     error_message)
                    new_object = self.obj.objects.get(pk=test_obj.pk)
                    self.assert_objects_equal(new_object, test_obj)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value.encode('utf-8'), field))

    @only_with_obj
    @only_with(('email_fields_edit',))
    def test_edit_object_wrong_values_in_email_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: wrong values in email fields
        """
        message_type = 'wrong_value_email'
        for field in self.email_fields_edit:
            for value in ('q', u'й', 'qwe@rty', u'qw@йц', '@qwe', 'qwe@'):
                sp = transaction.savepoint()
                try:
                    test_obj = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                        params.update(get_captcha_codes())
                    params[field] = value
                    response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                                params, follow=True, **self.additional_params)
                    error_message = self.get_error_message(message_type, field)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    new_object = self.obj.objects.get(pk=test_obj.pk)
                    self.assert_objects_equal(new_object, test_obj)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value.encode('utf-8'), field))

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_value_max_in_digital_positive(self):
        """
        @author: Polina Efremova
        @note: Edit object: value in digital fields == max
        """
        for field in [f for f in self.digital_fields_edit]:
            max_values = self.get_digital_values_range(field)['max_values']
            if not max_values:
                continue
            value = min(max_values)
            sp = transaction.savepoint()
            obj_for_edit = self.get_obj_for_edit()
            try:
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = value
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_edit,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with value "%s"' % (field, params[field]))

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_value_gt_max_in_digital_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: value in digital fields > max
        """
        message_type = 'max_length_digital'
        for field in [f for f in self.digital_fields_edit]:
            max_value = min(self.get_digital_values_range(field)['max_values'])
            for value in self.get_gt_max_list(field, self.get_digital_values_range(field)['max_values']):
                sp = transaction.savepoint()
                try:
                    test_obj = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                        params.update(get_captcha_codes())
                    params[field] = value
                    response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                                params, follow=True, **self.additional_params)
                    error_message = self.get_error_message(message_type, field)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    new_object = self.obj.objects.get(pk=test_obj.pk)
                    self.assert_objects_equal(new_object, test_obj)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_value_min_in_digital_positive(self):
        """
        @author: Polina Efremova
        @note: Edit object: value in digital fields == min
        """
        for field in [f for f in self.digital_fields_edit]:
            min_values = self.get_digital_values_range(field)['min_values']
            if not min_values:
                continue
            value = max(min_values)
            sp = transaction.savepoint()
            obj_for_edit = self.get_obj_for_edit()
            try:
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = value
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_edit,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with value "%s"' % (field, params[field]))

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_value_lt_min_in_digital_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: value in digital fields < min
        """
        message_type = 'min_length_digital'
        for field in [f for f in self.digital_fields_edit]:
            min_value = max(self.get_digital_values_range(field)['min_values'])
            for value in self.get_lt_min_list(field, self.get_digital_values_range(field)['min_values']):
                sp = transaction.savepoint()
                try:
                    test_obj = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                        params.update(get_captcha_codes())
                    params[field] = value
                    response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                                params, follow=True, **self.additional_params)
                    error_message = self.get_error_message(message_type, field)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    new_object = self.obj.objects.get(pk=test_obj.pk)
                    self.assert_objects_equal(new_object, test_obj)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('disabled_fields_edit',))
    def test_edit_disabled_fields_values_negative(self):
        """
        @author: Polina Efremova
        @note: Try change values in disabled fields
        """
        for field in self.disabled_fields_edit:
            sp = transaction.savepoint()
            try:
                test_obj = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = params.get(field, None) or self.get_value_for_field(10, field)
                response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_edit,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                new_object = self.obj.objects.get(pk=test_obj.pk)
                if field not in getattr(self, 'exclude_from_check_edit', []):
                    self.assertEqual(self.get_value_for_compare(new_object, field),
                                     getattr(self, 'other_values_for_check',
                                             {}).get(field, self.get_value_for_compare(test_obj, field)))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s"' % field)

    @only_with_obj
    @only_with(('one_of_fields_edit',))
    def test_edit_object_one_of_fields_all_filled_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit object: fill all fields, that should be filled singly
        """
        message_type = 'one_of'
        for group in self.one_of_fields_edit:
            for filled_group in tuple(set([(el, additional_el) for i, el in enumerate(group) for additional_el in
                                           group[i + 1:]]).difference(set(self.one_of_fields_edit).difference(group))) + \
                                           (group,):
                sp = transaction.savepoint()
                try:
                    test_obj = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    self.fill_all_fields(filled_group, params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_edit, (test_obj.pk,)), **self.additional_params)
                        params.update(get_captcha_codes())
                    response = self.client.post(self.get_url(self.url_edit, (test_obj.pk,)),
                                                params, follow=True, **self.additional_params)
                    error_message = self.get_error_message(message_type, group)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    new_object = self.obj.objects.get(pk=test_obj.pk)
                    self.assert_objects_equal(new_object, test_obj)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text=u'For filled %s fields from group %s' % (str(filled_group), str(group)))


class FormDeleteTestMixIn(FormTestMixIn):

    url_delete = ''

    @only_with_obj
    def test_delete_not_exists_object_negative(self):
        """
        @author: Polina Efremova
        @note: Try delete object with invalid id
        """
        for value in ('9999999', '2147483648', 'qwe', u'йцу'):
            sp = transaction.savepoint()
            try:
                response = self.client.get(self.get_url_for_negative(self.url_delete, (value,)),
                                           follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 404, 'Status code %s != 404' % response.status_code)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For value %s error' % value)

    @only_with_obj
    def test_delete_obj_positive(self):
        """
        @author: Polina Efremova
        @note: Delete object
        """
        if 'get_obj_id_for_edit' in dir(self):
            obj_pk = self.get_obj_id_for_edit()
        else:
            obj_pk = self.obj.objects.all()[0].pk
        initial_obj_count = self.obj.objects.count()

        self.client.post(self.get_url(self.url_delete, (obj_pk,)), {'post': 'yes'}, **self.additional_params)
        self.assertEqual(self.obj.objects.count(), initial_obj_count - 1,
                         u'Objects count after delete = %s (expect %s)' %
                         (self.obj.objects.count(), initial_obj_count - 1))

    @only_with_obj
    @only_with(('url_list',))
    def test_delete_obj_from_list_positive(self):
        """
        @author: Polina Efremova
        @note: Delete objects from objects list
        """
        obj_ids = self.obj.objects.values_list('pk', flat=True)
        initial_obj_count = self.obj.objects.count()
        params = {'_selected_action': obj_ids,
                  'action': 'delete_selected',
                  'post': 'yes'}
        response = self.client.post(self.get_url(self.url_list), params, follow=True, **self.additional_params)
        try:
            self.assertEqual(self.get_all_form_messages(response),
                             [u'Успешно удалены %d %s.' % (len(obj_ids), self.obj._meta.verbose_name)])
            self.assertEqual(self.obj.objects.count(), initial_obj_count - len(obj_ids),
                             u'Objects count after delete = %s (expect %s)' %
                             (self.obj.objects.count(), initial_obj_count - len(obj_ids)))
        except:
            self.errors_append()


class FormRemoveTestMixIn(FormTestMixIn):
    """for objects with is_removed attribute"""

    url_delete = ''
    url_edit_in_trash = ''
    url_recovery = ''

    def __init__(self, *args, **kwargs):
        super(FormRemoveTestMixIn, self).__init__(*args, **kwargs)
        self.url_edit_in_trash = self.url_edit_in_trash or self.url_recovery.replace('trash_restore', 'trash_change')

    def get_is_removed(self, obj):
        is_removed_name = getattr(self, 'is_removed_field', 'is_removed')
        return getattr(obj, is_removed_name)

    def set_is_removed(self, obj, value):
        is_removed_name = getattr(self, 'is_removed_field', 'is_removed')
        setattr(obj, is_removed_name, value)

    @only_with_obj
    def test_delete_obj_positive(self):
        """
        @author: Polina Efremova
        @note: Delete object
        """
        obj_id = self.get_obj_id_for_edit()
        initial_obj_count = self.obj.objects.count()
        try:
            self.client.get(self.get_url(self.url_delete, (obj_id,)), **self.additional_params)
            self.assertEqual(self.obj.objects.count(), initial_obj_count)
            self.assertTrue(self.get_is_removed(self.obj.objects.get(id=obj_id)))
        except:
            self.errors_append()

    @only_with_obj
    def test_recovery_obj_positive(self):
        """
        @author: Polina Efremova
        @note: Recovery deleted object
        """
        obj_for_test = self.get_obj_for_edit()
        self.set_is_removed(obj_for_test, True)
        obj_for_test.save()
        obj_id = obj_for_test.id
        initial_obj_count = self.obj.objects.count()
        additional_params = self.deepcopy(self.additional_params)
        additional_params.update({'HTTP_REFERER': '127.0.0.1'})
        try:
            recovery_url = self.get_url(self.url_recovery, (obj_id,))
            self.client.get(recovery_url, **additional_params)
            self.assertEqual(self.obj.objects.count(), initial_obj_count)
            self.assertFalse(self.get_is_removed(self.obj.objects.get(id=obj_id)))
        except:
            self.errors_append()

    @only_with_obj
    def test_delete_not_exists_object_negative(self):
        """
        @author: Polina Efremova
        @note: Try delete object with invalid id
        """
        for value in ('9999999', '2147483648', 'qwe', u'йцу'):
            try:
                url = self.get_url_for_negative(self.url_delete, (value,))
                response = self.client.get(url, follow=True, **self.additional_params)
                self.assertTrue(response.redirect_chain[0][0].endswith(self.get_url(self.url_list)),
                                'Redirect was %s' % response.redirect_chain[0][0])
                self.assertEqual(response.status_code, 200)
                error_message = self.get_error_message('delete_not_exists', None)
                self.assertEqual(self.get_all_form_messages(response), [error_message])
            except:
                self.errors_append(text='For value "%s" error' % value)

    @only_with_obj
    def test_recovery_not_exists_object_negative(self):
        """
        @author: Polina Efremova
        @note: Try recovery object with invalid id
        """
        additional_params = self.deepcopy(self.additional_params)
        additional_params.update({'HTTP_REFERER': '127.0.0.1'})
        for value in ('9999999', '2147483648',):
            try:
                url = self.get_url_for_negative(self.url_recovery, (value,))
                response = self.client.get(url, follow=True, **additional_params)
                self.assertTrue(response.redirect_chain[0][0].endswith(self.get_url(self.url_trash_list)),
                                'Redirect was %s' % response.redirect_chain[0][0])
                self.assertEqual(response.status_code, 200)
                error_message = self.get_error_message('recovery_not_exists', None)
                self.assertEqual(self.get_all_form_messages(response), [error_message])
            except:
                self.errors_append(text='For value "%s" error' % value)

    @only_with_obj
    def test_edit_in_trash_negative(self):
        """
        @author: Polina Efremova
        @note: Try change object in trash
        """
        obj_for_test = self.get_obj_for_edit()
        self.set_is_removed(obj_for_test, True)
        obj_for_test.save()
        obj_id = obj_for_test.id
        params = self.deepcopy(self.default_params_edit)
        try:
            url = self.get_url_for_negative(self.url_recovery.replace('trash_restore', 'trash_change'), (obj_id,))
            response = self.client.post(url, params, follow=True, **self.additional_params)
            self.assertTrue(response.redirect_chain[0][0].endswith(self.get_url(self.url_trash_list)))
            self.assertEqual(response.status_code, 200)
            error_message = u'Вы не можете изменять объекты в корзине.'
            self.assertEqual(self.get_all_form_messages(response), [error_message])
        except:
            self.errors_append()

    @only_with_obj
    def test_edit_in_trash_by_edit_url_negative(self):
        """
        @author: Polina Efremova
        @note: Try change object in trash
        """
        obj_for_test = self.get_obj_for_edit()
        self.set_is_removed(obj_for_test, True)
        obj_for_test.save()
        obj_id = obj_for_test.id
        params = self.deepcopy(self.default_params_edit)
        try:
            response = self.client.post(self.get_url_for_negative(self.url_edit, (obj_id,)), params, follow=True, **self.additional_params)
            self.assertEqual(response.status_code, 404, 'Status code %s != 404' % response.status_code)
        except:
            self.errors_append()

    @only_with_obj
    @only_with(('others_objects',))
    def test_recovery_other_user_obj_negative(self):
        obj_for_test = self.others_objects[0]
        self.set_is_removed(obj_for_test, True)
        obj_for_test.save()
        initial_obj_count = self.obj.objects.count()
        additional_params = self.deepcopy(self.additional_params)
        additional_params.update({'HTTP_REFERER': '127.0.0.1'})
        try:
            recovery_url = self.get_url_for_negative(self.url_recovery, (obj_for_test.pk,))
            response = self.client.get(recovery_url, follow=True, **additional_params)
            self.assertEqual(self.obj.objects.count(), initial_obj_count)
            self.assertTrue(self.get_is_removed(self.obj.objects.get(id=obj_for_test.pk)))
            self.assertEqual(self.get_all_form_messages(response), [u'Произошла ошибка. Попробуйте позже.'])
        except:
            self.errors_append()

    @only_with_obj
    @only_with(('others_objects',))
    def test_delete_other_user_obj_negative(self):
        obj_for_test = self.others_objects[0]
        self.set_is_removed(obj_for_test, False)
        obj_for_test.save()
        initial_obj_count = self.obj.objects.count()

        try:
            response = self.client.get(self.get_url_for_negative(self.url_delete, (obj_for_test.pk,)), follow=True,
                                       **self.additional_params)
            self.assertEqual(self.obj.objects.count(), initial_obj_count)
            self.assertFalse(self.get_is_removed(self.obj.objects.get(id=obj_for_test.pk)))
            self.assertEqual(self.get_all_form_messages(response), [u'Произошла ошибка. Попробуйте позже.'])
        except:
            self.errors_append()

    @only_with_obj
    @only_with(('url_list',))
    def test_delete_obj_from_list_positive(self):
        """
        @author: Polina Efremova
        @note: Delete objects from objects list
        """
        obj_ids = [self.get_obj_id_for_edit()]
        initial_obj_count = self.obj.objects.count()
        params = {'_selected_action': obj_ids,
                  'action': 'action_remove',
                  'select_across': '0'}
        response = self.client.post(self.get_url(self.url_list), params, follow=True, **self.additional_params)
        try:
            self.assertEqual(self.get_all_form_messages(response),
                             [u'Успешно удалено %d объектов.' % len(obj_ids)])
            self.assertEqual(self.obj.objects.count(), initial_obj_count,
                             u'Objects count after remove (should not be changed) = %s (expect %s)' %
                             (self.obj.objects.count(), initial_obj_count))
            self.assertTrue(all([self.get_is_removed(obj) for obj in self.obj.objects.filter(pk__in=obj_ids)]))
        except:
            self.errors_append()

    @only_with_obj
    def test_recovery_obj_from_list_positive(self):
        """
        @author: Polina Efremova
        @note: Recovery deleted objects from objects list
        """
        self.obj.objects.update(is_removed=True)
        obj_ids = [self.get_obj_id_for_edit()]
        initial_obj_count = self.obj.objects.count()
        params = {'_selected_action': obj_ids,
                  'action': 'action_restore',
                  'select_across': '0'}
        response = self.client.post(self.get_url(self.url_trash_list), params, follow=True, **self.additional_params)
        try:
            self.assertEqual(self.get_all_form_messages(response),
                             [u'Успешно восстановлено %d объектов.' % len(obj_ids)])
            self.assertEqual(self.obj.objects.count(), initial_obj_count,
                             u'Objects count after recovery (should not be changed) = %s (expect %s)' %
                             (self.obj.objects.count(), initial_obj_count))
            self.assertFalse(any(self.obj.objects.filter(pk__in=obj_ids).values_list('is_removed', flat=True)))
        except:
            self.errors_append()


class FileTestMixIn(FormTestMixIn):

    file_fields_params = None
    """{'field_name': {'extensions': ('jpg', 'txt'),
                       'max_count': 3,
                       'one_max_size': '3Mb',
                       'sum_max_size': '9Mb'}}"""
    with_files = True

    def __init__(self, *args, **kwargs):
        super(FileTestMixIn, self).__init__(*args, **kwargs)
        if self.file_fields_params is None:
            self.file_fields_params = {}
        self.FILE_FIELDS = set(list(self.FILE_FIELDS) + self.file_fields_params.keys())

    def humanize_file_size(self, size):
        return filesizeformat(size)


def only_with_files_params(param_names=None):
    if not isinstance(param_names, (tuple, list)):
        param_names = [param_names, ]

    def decorator(fn):
        def tmp(self):
            params_dict_name = 'file_fields_params' + ('_add' if '_add_' in fn.__name__ else '_edit')

            def check_params(field_dict, param_names):
                return all([param_name in field_dict.keys() for param_name in param_names])
            if any([check_params(field_dict, param_names) for field_dict in getattr(self, params_dict_name).values()]):
                if not all([check_params(field_dict, param_names) for field_dict in getattr(self, params_dict_name).values()]):
                    warnings.warn('%s not set for all fields' % str(param_names))
                return fn(self)
            else:
                raise SkipTest("Need all these params: %s" % repr(param_names))

        tmp.__name__ = fn.__name__
        return tmp

    return decorator


def only_with_any_files_params(param_names=None):
    if not isinstance(param_names, (tuple, list)):
        param_names = [param_names, ]

    def decorator(fn):
        def tmp(self):
            params_dict_name = 'file_fields_params' + ('_add' if '_add_' in fn.__name__ else '_edit')

            def check_params(field_dict, param_names):
                return any([param_name in field_dict.keys() for param_name in param_names])
            if any([check_params(field_dict, param_names) for field_dict in getattr(self, params_dict_name).values()]):
                if not all([check_params(field_dict, param_names) for field_dict in getattr(self, params_dict_name).values()]):
                    warnings.warn('%s not set for all fields' % str(param_names))
                return fn(self)
            else:
                raise SkipTest("Need all these params: %s" % repr(param_names))

        tmp.__name__ = fn.__name__
        return tmp

    return decorator


class FormAddFileTestMixIn(FileTestMixIn):

    file_fields_params_add = None

    def __init__(self, *args, **kwargs):
        super(FormAddFileTestMixIn, self).__init__(*args, **kwargs)
        if self.file_fields_params_add is None:
            self.file_fields_params_add = self.deepcopy(self.file_fields_params)

    @only_with_obj
    @only_with_files_params('max_count')
    def test_add_object_many_files_negative(self):
        """
        @author: Polina Efremova
        @note: Try create obj with files count > max files count
        """
        new_objects = None
        message_type = 'max_count_file'
        for field, field_dict in self.file_fields_params_add.iteritems():
            if field_dict.get('max_count', 1) <= 1:
                continue
            sp = transaction.savepoint()
            if new_objects:
                new_objects.delete()
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                max_count = field_dict['max_count']
                filename = '.'.join([s for s in [get_randname(10, 'wrd '),
                                                 choice(field_dict.get('extensions', ('',)))] if s])
                f = get_random_file(filename=filename, **field_dict)
                self.files.append(f)
                params[field] = [f, ] * (max_count + 1)
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                new_object = self.obj.objects.exclude(pk__in=old_pks)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (max_count + 1, field))

    @only_with_obj
    @only_with_files_params('max_count')
    def test_add_object_many_files_positive(self):
        """
        @author: Polina Efremova
        @note: Try create obj with photos count == max files count
        """
        new_object = None
        for field, field_dict in self.file_fields_params_add.iteritems():
            if field_dict.get('max_count', 1) <= 1:
                continue
            sp = transaction.savepoint()
            if new_object:
                self.obj.objects.filter(pk=new_object.pk).delete()
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                max_count = field_dict['max_count']
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = []
                for _ in xrange(max_count):
                    f = get_random_file(**field_dict)
                    self.files.append(f)
                    params[field].append(f)
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_add,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                self.assert_objects_count_on_add(True, initial_obj_count)
                new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (max_count, field))

    @only_with_obj
    @only_with_files_params('one_max_size')
    def test_add_object_big_file_negative(self):
        """
        @author: Polina Efremova
        @note: Try create obj with file size > max one file size
        """
        message_type = 'max_size_file'
        for field, field_dict in self.file_fields_params_add.iteritems():
            sp = transaction.savepoint()
            one_max_size = field_dict.get('one_max_size', None)
            if not one_max_size:
                continue
            try:
                initial_obj_count = self.obj.objects.count()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                size = convert_size_to_bytes(one_max_size)
                max_size = self.humanize_file_size(size)
                filename = '.'.join([s for s in ['big_file', choice(field_dict.get('extensions', ('',)))] if s])
                current_size = size + 100
                f = get_random_file(filename=filename, size=current_size, **field_dict)
                self.files.append(f)
                params[field] = [f, ] if self.is_file_list(field) else f
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For file size %s (%s) in field %s' % (self.humanize_file_size(current_size),
                                                                               current_size, field))
            self.del_files()

    @only_with_obj
    @only_with_files_params('sum_max_size')
    def test_add_object_big_summary_file_size_negative(self):
        """
        @author: Polina Efremova
        @note: Try create obj with summary files size > max summary files size
        """
        message_type = 'max_sum_size_file'
        for field, field_dict in self.file_fields_params_add.iteritems():
            sp = transaction.savepoint()
            sum_max_size = field_dict.get('sum_max_size', None)
            if not sum_max_size:
                continue
            try:
                initial_obj_count = self.obj.objects.count()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                size = convert_size_to_bytes(sum_max_size)
                current_size = size + 100
                max_size = self.humanize_file_size(size)
                one_size = current_size / field_dict['max_count']
                params[field] = []
                for _ in xrange(field_dict['max_count']):
                    f = get_random_file(size=one_size, **field_dict)
                    self.files.append(f)
                    params[field].append(f)
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For summary size %s (%s = %s * %s) in field %s' %
                                   (self.humanize_file_size(current_size), current_size, one_size,
                                    field_dict['max_count'], field))
            self.del_files()

    @only_with_obj
    def test_add_object_big_file_positive(self):
        """
        @author: Polina Efremova
        @note: Create obj with file size == max one file size
        """
        new_object = None
        for field, field_dict in self.file_fields_params_add.iteritems():
            sp = transaction.savepoint()
            if new_object:
                self.obj.objects.filter(pk=new_object.pk).delete()
            one_max_size = field_dict.get('one_max_size', '10M')
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                size = convert_size_to_bytes(one_max_size)
                max_size = self.humanize_file_size(size)
                if self.is_file_list(field):
                    params[field] = []
                    for _ in xrange(1 if field_dict.get('sum_max_size', None) else field_dict['max_count']):
                        f = get_random_file(size=size, **field_dict)
                        self.files.append(f)
                        params[field].append(f)
                else:
                    f = get_random_file(size=size, **field_dict)
                    self.files.append(f)
                    params[field] = f
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_add,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                self.assert_objects_count_on_add(True, initial_obj_count)
                new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For file size %s (%s) in field %s' % (max_size, size, field))
            self.del_files()

    @only_with_obj
    @only_with_files_params('sum_max_size')
    def test_add_object_big_summary_file_size_positive(self):
        """
        @author: Polina Efremova
        @note: Create obj with summary files size == max summary files size
        """
        new_object = None
        for field, field_dict in self.file_fields_params_add.iteritems():
            sp = transaction.savepoint()
            if new_object:
                self.obj.objects.filter(pk=new_object.pk).delete()
            sum_max_size = field_dict.get('sum_max_size', None)
            if not sum_max_size:
                continue
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                size = convert_size_to_bytes(sum_max_size)
                max_size = self.humanize_file_size(size)
                one_size = size / field_dict['max_count']
                params[field] = []
                for _ in xrange(field_dict['max_count']):
                    f = get_random_file(size=one_size, **field_dict)
                    self.files.append(f)
                    params[field].append(f)
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_add,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                self.assert_objects_count_on_add(True, initial_obj_count)
                new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For summary size %s (%s = %s * %s) in field %s' %
                                   (max_size, one_size * field_dict['max_count'], one_size, field_dict['max_count'],
                                    field))
            self.del_files()

    @only_with_obj
    def test_add_object_empty_file_negative(self):
        """
        @author: Polina Efremova
        @note: Try create obj with file size = 0M
        """
        new_objects = None
        message_type = 'empty_file'
        for field, field_dict in self.file_fields_params_add.iteritems():
            sp = transaction.savepoint()
            if new_objects:
                new_objects.delete()
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                filename = '.'.join([s for s in ['big_file', choice(field_dict.get('extensions', ('',)))] if s])
                f = ContentFile('', filename)
                self.files.append(f)
                params[field] = [f, ] if self.is_file_list(field) else f
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_objects_count_on_add(False, initial_obj_count)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                new_objects = self.obj.objects.exclude(pk__in=old_pks)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty file in field %s' % field)

    @only_with_obj
    def test_add_object_some_file_extensions_positive(self):
        """
        @author: Polina Efremova
        @note: Create obj with some available extensions
        """
        new_object = None
        for field, field_dict in self.file_fields_params_add.iteritems():
            extensions = copy(field_dict.get('extensions', ()))
            if not extensions:
                extensions = (get_randname(3, 'wd'), '')
            extensions += tuple([e.upper() for e in extensions if e])
            is_file_list = self.is_file_list(field)
            for ext in extensions:
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                sp = transaction.savepoint()
                if new_object:
                    self.obj.objects.filter(pk=new_object.pk).delete()
                filename = '.'.join([el for el in ['test', ext] if el])
                f = get_random_file(filename=filename, **field_dict)
                self.files.append(f)
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = [f, ] if is_file_list else f
                initial_obj_count = self.obj.objects.count()
                try:
                    response = self.client.post(self.get_url(self.url_add), params, follow=True,
                                                **self.additional_params)
                    self.assert_no_form_errors(response)
                    self.assertEqual(response.status_code, self.status_code_success_add,
                                     'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                    self.assert_objects_count_on_add(True, initial_obj_count)
                    new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                    exclude = getattr(self, 'exclude_from_check_add', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))

    @only_with_obj
    @only_with_files_params('extensions')
    def test_add_object_wrong_file_extensions_negative(self):
        """
        @author: Polina Efremova
        @note: Create obj with wrong extensions
        """
        message_type = 'wrong_extension'
        for field, field_dict in self.file_fields_params_add.iteritems():
            extensions = copy(field_dict.get('extensions', ()))
            if not extensions:
                continue
            ext = get_randname(3, 'wd')
            while ext in extensions:
                ext = get_randname(3, 'wd')
            wrong_extensions = tuple(field_dict.get('wrong_extensions', ())) + ('', ext)
            for ext in wrong_extensions:
                filename = '.'.join([el for el in ['test', ext] if el])
                sp = transaction.savepoint()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                f = get_random_file(filename=filename, **field_dict)
                self.files.append(f)
                params[field] = [f, ] if self.is_file_list(field) else f
                initial_obj_count = self.obj.objects.count()
                try:
                    response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                    self.assert_objects_count_on_add(False, initial_obj_count)
                    self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))

    @only_with_obj
    @only_with_any_files_params(['min_width', 'min_height'])
    def test_add_object_min_image_dimensions_positive(self):
        """
        @author: Polina Efremova
        @note: Create obj with minimum image file dimensions
        """
        new_object = None
        for field, field_dict in self.file_fields_params_add.iteritems():
            sp = transaction.savepoint()
            if new_object:
                self.obj.objects.filter(pk=new_object.pk).delete()
            try:
                initial_obj_count = self.obj.objects.count()
                old_pks = list(self.obj.objects.values_list('pk', flat=True))
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_add), **self.additional_params)
                    params.update(get_captcha_codes())
                width = field_dict.get('min_width', 1)
                height = field_dict.get('min_height', 1)
                f = get_random_file(width=width, height=height, **field_dict)
                self.files.append(f)
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                params[field] = [f, ] if self.is_file_list(field) else f
                response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_add,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_add))
                self.assert_objects_count_on_add(True, initial_obj_count)
                new_object = self.obj.objects.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))

    @only_with_obj
    @only_with_any_files_params(['min_width', 'min_height'])
    def test_add_object_image_dimensions_lt_min_negative(self):
        """
        @author: Polina Efremova
        @note: Create obj with image file dimensions < minimum
        """
        new_objects = None
        message_type = 'min_dimensions'
        for field, field_dict in self.file_fields_params_add.iteritems():
            if new_objects:
                new_objects.delete()
            is_file_list = self.is_file_list(field)
            values = ()
            min_width = field_dict.get('min_width', None)
            if min_width:
                values += ((min_width - 1, field_dict.get('min_height', 1)),)
            min_height = field_dict.get('min_height', None)
            if min_height:
                values += ((field_dict.get('min_width', 1), min_height - 1),)

            for width, height in values:
                sp = transaction.savepoint()
                try:
                    initial_obj_count = self.obj.objects.count()
                    old_pks = list(self.obj.objects.values_list('pk', flat=True))
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    if self.with_captcha:
                        self.client.get(self.get_url(self.url_add), **self.additional_params)
                        params.update(get_captcha_codes())
                    f = get_random_file(width=width, height=height, **field_dict)
                    self.files.append(f)
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    params[field] = [f, ] if is_file_list else f
                    response = self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)
                    self.assert_objects_count_on_add(False, initial_obj_count)
                    self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                    new_objects = self.obj.objects.exclude(pk__in=old_pks)
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))


class FormEditFileTestMixIn(FileTestMixIn):

    file_fields_params_edit = None

    def __init__(self, *args, **kwargs):
        super(FormEditFileTestMixIn, self).__init__(*args, **kwargs)
        if self.file_fields_params_edit is None:
            self.file_fields_params_edit = self.deepcopy(self.file_fields_params)

    @only_with_obj
    @only_with_files_params('max_count')
    def test_edit_object_many_files_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit obj with files count > max files count
        """
        message_type = 'max_count_file'
        for field, field_dict in self.file_fields_params_edit.iteritems():
            if field_dict.get('max_count', 1) <= 1:
                continue
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                max_count = field_dict['max_count']
                filename = '.'.join([s for s in [get_randname(10, 'wrd '),
                                                 choice(field_dict.get('extensions', ('',)))] if s])
                f = get_random_file(filename=filename, **field_dict)
                self.files.append(f)
                params[field] = [f, ] * (max_count + 1)
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                self.assert_objects_equal(new_object, obj_for_edit)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (max_count + 1, field))

    @only_with_obj
    @only_with_files_params('max_count')
    def test_edit_object_many_files_positive(self):
        """
        @author: Polina Efremova
        @note: Try edit obj with photos count == max files count
        """
        for field, field_dict in self.file_fields_params_edit.iteritems():
            if field_dict.get('max_count', 1) <= 1:
                continue
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                max_count = field_dict['max_count']
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = []
                for _ in xrange(max_count):
                    f = get_random_file(**field_dict)
                    self.files.append(f)
                    params[field].append(f)
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_edit,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (max_count, field))

    @only_with_obj
    @only_with_files_params('one_max_size')
    def test_edit_object_big_file_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit obj with file size > max one file size
        """
        message_type = 'max_size_file'
        for field, field_dict in self.file_fields_params_edit.iteritems():
            sp = transaction.savepoint()
            one_max_size = field_dict.get('one_max_size', None)
            if not one_max_size:
                continue
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                size = convert_size_to_bytes(one_max_size)
                max_size = self.humanize_file_size(size)
                filename = '.'.join([s for s in ['big_file', choice(field_dict.get('extensions', ('',)))] if s])
                current_size = size + 100
                f = get_random_file(filename=filename, size=current_size, **field_dict)
                self.files.append(f)
                params[field] = [f, ] if self.is_file_list(field) else f
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                self.assert_objects_equal(new_object, obj_for_edit)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For file size %s (%s) in field %s' % (self.humanize_file_size(current_size),
                                                                               current_size, field))
            self.del_files()

    @only_with_obj
    @only_with_files_params('sum_max_size')
    def test_edit_object_big_summary_file_size_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit obj with summary files size > max summary file size
        """
        message_type = 'max_sum_size_file'
        for field, field_dict in self.file_fields_params_edit.iteritems():
            sp = transaction.savepoint()
            sum_max_size = field_dict.get('sum_max_size', None)
            if not sum_max_size:
                continue
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                size = convert_size_to_bytes(sum_max_size)
                current_size = size + 100
                max_size = self.humanize_file_size(size)
                one_size = current_size / field_dict['max_count']
                params[field] = []
                for _ in xrange(field_dict['max_count']):
                    f = get_random_file(size=one_size, **field_dict)
                    self.files.append(f)
                    params[field].append(f)
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                self.assert_objects_equal(new_object, obj_for_edit)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For summary size %s (%s = %s * %s) in field %s' %
                                   (self.humanize_file_size(current_size), current_size, one_size,
                                    field_dict['max_count'], field))
            self.del_files()

    @only_with_obj
    def test_edit_object_big_file_positive(self):
        """
        @author: Polina Efremova
        @note: Edit obj with file size == max one file size
        """
        for field, field_dict in self.file_fields_params_edit.iteritems():
            sp = transaction.savepoint()
            one_max_size = field_dict.get('one_max_size', '10M')
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                size = convert_size_to_bytes(one_max_size)
                max_size = self.humanize_file_size(size)
                if self.is_file_list(field):
                    params[field] = []
                    for _ in xrange(1 if field_dict.get('sum_max_size', None) else field_dict['max_count']):
                        f = get_random_file(size=size, **field_dict)
                        self.files.append(f)
                        params[field].append(f)
                else:
                    f = get_random_file(size=size, **field_dict)
                    self.files.append(f)
                    params[field] = f
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_edit,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For file size %s (%s) in field %s' % (max_size, size, field))
            self.del_files()

    @only_with_obj
    @only_with_files_params('sum_max_size')
    def test_edit_object_big_summary_file_size_positive(self):
        """
        @author: Polina Efremova
        @note: Edit obj with summary files size == max summary files size
        """
        for field, field_dict in self.file_fields_params_edit.iteritems():
            sp = transaction.savepoint()
            sum_max_size = field_dict.get('sum_max_size', None)
            if not sum_max_size:
                continue
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                size = convert_size_to_bytes(sum_max_size)
                max_size = self.humanize_file_size(size)
                one_size = size / field_dict['max_count']
                params[field] = []
                for _ in xrange(field_dict['max_count']):
                    f = get_random_file(size=one_size, **field_dict)
                    self.files.append(f)
                    params[field].append(f)
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_edit,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For summary size %s (%s = %s * %s) in field %s' %
                                   (max_size, one_size * field_dict['max_count'], one_size, field_dict['max_count'],
                                    field))
            self.del_files()

    @only_with_obj
    def test_edit_object_empty_file_negative(self):
        """
        @author: Polina Efremova
        @note: Try edit obj with file size = 0M
        """
        message_type = 'empty_file'
        for field, field_dict in self.file_fields_params_edit.iteritems():
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                filename = '.'.join([s for s in ['big_file', choice(field_dict.get('extensions', ('',)))] if s])
                f = ContentFile('', filename)
                self.files.append(f)
                params[field] = [f, ] if self.is_file_list(field) else f
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)), params, follow=True,
                                            **self.additional_params)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                self.assert_objects_equal(new_object, obj_for_edit)
                self.assertEqual(response.status_code, self.status_code_error,
                                 'Status code %s != %s' % (response.status_code, self.status_code_error))
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty file in field %s' % field)

    @only_with_obj
    def test_edit_object_some_file_extensions_positive(self):
        """
        @author: Polina Efremova
        @note: Edit obj with some available extensions
        """
        for field, field_dict in self.file_fields_params_edit.iteritems():
            extensions = copy(field_dict.get('extensions', ()))
            if not extensions:
                extensions = (get_randname(3, 'wd'), '')
            extensions += tuple([e.upper() for e in extensions if e])
            is_file_list = self.is_file_list(field)
            for ext in extensions:
                sp = transaction.savepoint()
                filename = '.'.join([el for el in ['test', ext] if el])
                f = get_random_file(filename=filename, **field_dict)
                self.files.append(f)
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                params[field] = [f, ] if is_file_list else f
                try:
                    response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                                params, follow=True, **self.additional_params)
                    self.assert_no_form_errors(response)
                    self.assertEqual(response.status_code, self.status_code_success_edit,
                                     'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                    new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                    exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))

    @only_with_obj
    @only_with_files_params('extensions')
    def test_edit_object_wrong_file_extensions_negative(self):
        """
        @author: Polina Efremova
        @note: Edit obj with wrong extensions
        """
        message_type = 'wrong_extension'
        for field, field_dict in self.file_fields_params_edit.iteritems():
            extensions = copy(field_dict.get('extensions', ()))
            if not extensions:
                continue
            ext = get_randname(3, 'wd')
            while ext in extensions:
                ext = get_randname(3, 'wd')
            wrong_extensions = tuple(field_dict.get('wrong_extensions', ())) + ('', ext)
            for ext in wrong_extensions:
                filename = '.'.join([el for el in ['test', ext] if el])
                sp = transaction.savepoint()
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                f = get_random_file(filename=filename, **field_dict)
                self.files.append(f)
                params[field] = [f, ] if self.is_file_list(field) else f
                try:
                    response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)), params, follow=True,
                                                **self.additional_params)
                    self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                    new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                    self.assert_objects_equal(new_object, obj_for_edit)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))

    @only_with_obj
    @only_with_any_files_params(['min_width', 'min_height'])
    def test_edit_object_min_image_dimensions_positive(self):
        """
        @author: Polina Efremova
        @note: Edit obj with minimum image file dimensions
        """
        for field, field_dict in self.file_fields_params_edit.iteritems():
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                width = field_dict.get('min_width', 1)
                height = field_dict.get('min_height', 1)
                f = get_random_file(width=width, height=height, **field_dict)
                self.files.append(f)
                params[field] = [f, ] if self.is_file_list(field) else f
                response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)),
                                            params, follow=True, **self.additional_params)
                self.assert_no_form_errors(response)
                self.assertEqual(response.status_code, self.status_code_success_edit,
                                 'Status code %s != %s' % (response.status_code, self.status_code_success_edit))
                new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except:
                self.savepoint_rollback(sp)
                self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))

    @only_with_obj
    @only_with_any_files_params(['min_width', 'min_height'])
    def test_edit_object_image_dimensions_lt_min_negative(self):
        """
        @author: Polina Efremova
        @note: Edit obj with image file dimensions < minimum
        """
        message_type = 'min_dimensions'
        for field, field_dict in self.file_fields_params_edit.iteritems():
            is_file_list = self.is_file_list(field)
            values = ()
            min_width = field_dict.get('min_width', None)
            if min_width:
                values += ((min_width - 1, field_dict.get('min_height', 1)),)
            min_height = field_dict.get('min_height', None)
            if min_height:
                values += ((field_dict.get('min_width', 1), min_height - 1),)

            for width, height in values:
                sp = transaction.savepoint()
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                if self.with_captcha:
                    self.client.get(self.get_url(self.url_edit, (obj_for_edit.pk,)), **self.additional_params)
                    params.update(get_captcha_codes())
                f = get_random_file(width=width, height=height, **field_dict)
                self.files.append(f)
                params[field] = [f, ] if is_file_list else f
                try:
                    response = self.client.post(self.get_url(self.url_edit, (obj_for_edit.pk,)), params, follow=True,
                                                **self.additional_params)
                    self.assertEqual(self.get_all_form_errors(response), self.get_error_message(message_type, field))
                    new_object = self.obj.objects.get(pk=obj_for_edit.pk)
                    self.assert_objects_equal(new_object, obj_for_edit)
                    self.assertEqual(response.status_code, self.status_code_error,
                                     'Status code %s != %s' % (response.status_code, self.status_code_error))
                except:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))


class UserPermissionsTestMixIn(GlobalTestMixIn, LoginMixIn):
    allowed_links = ()
    links_400 = ()
    links_401 = ()
    links_403 = ()
    links_404 = ()
    links_405 = ()
    links_redirect = ()
    method = 'GET'
    password = ''
    redirect_to = ''
    urlpatterns = None
    username = ''

    @property
    def get_method(self):
        return getattr(self.client, self.method.lower())

    def get_urls(self):
        # FIXME:
        _urls = set(get_all_urls(self.urlpatterns))
        result = ()
        for aa in _urls:
            res = ''
            try:
                res = resolve(aa)
                if '.' in res.url_name:
                    result += (aa,)
                else:
                    res_kwargs = {k: v if str(v) != '123' else 1 for k, v in res.kwargs.iteritems()}
                    res_args = tuple([v if str(v) != '123' else 1 for v in res.args])
                    result += ((':'.join([el for el in [res.namespace, res.url_name] if el]),
                                res_kwargs or res_args),)
            except:
                result += (aa,)
                print '!!!!!', res, aa
        return result

    def login(self):
        if self.username:
            self.user_login(self.username, self.password)

    def _get_values(self, el):
        args = None
        custom_message = ''
        if isinstance(el, (str, unicode)):
            return el, args, custom_message
        if len(el) == 1:
            url_name = el[0]
        elif len(el) == 2 and isinstance(el[1], (str, unicode)):
            url_name, custom_message = el
        elif len(el) == 2:
            url_name, args = el
        elif len(el) == 3:
            url_name, args, custom_message = el
        custom_message = '; [%s]' % custom_message if custom_message else ''
        return url_name, args, custom_message

    @only_with(('allowed_links',))
    def test_allowed_links(self):
        """
        @author: Polina Efremova
        @note: check allowed links
        """
        for el in self.allowed_links:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = ''
            try:
                url = self.get_url(url_name, args)
                response = self.get_method(url, **self.additional_params)
                self.assertEqual(response.status_code, 200)
            except:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with(('links_redirect',))
    def test_unallowed_links_with_redirect(self):
        """
        @author: Polina Efremova
        @note: check unallowed links, that should redirect to other page
        """
        for el in self.links_redirect:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertRedirects(response, self.get_url(self.redirect_to))
            except:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with(('links_400',))
    def test_unallowed_links_with_400_response(self):
        """
        @author: Polina Efremova
        @note: check unallowed links, that should response 404
        """
        for el in self.links_400:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 400)
            except:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with('links_401')
    def test_unallowed_links_with_401_response(self):
        """
        @author: Polina Efremova
        @note: check unallowed links, that should response 401
        """
        self.login()
        for el in self.links_401:
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(self.get_all_form_errors(response),
                                 {"detail": u'Учетные данные не были предоставлены.'})
            except:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with(('links_403',))
    def test_unallowed_links_with_403_response(self):
        """
        @author: Polina Efremova
        @note: check unallowed links, that should response 403
        """
        for el in self.links_403:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 403)
            except:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with('urlpatterns')
    def test_unallowed_links_with_404_response(self):
        """
        @author: Polina Efremova
        @note: check unallowed links, that should response 404
        """
        links_other = tuple(self.allowed_links) + tuple(self.links_403) + tuple(self.links_redirect) + \
                      tuple(self.links_400) + tuple(self.links_401) + tuple(self.links_405)
        links_other = [self._get_values(el)[0] for el in links_other]
        for el in self.get_urls():
            try:
                url = ''
                url_name, args, custom_message = self._get_values(el)
                if url_name in links_other:
                    continue
                if isinstance(args, tuple):
                    url = self.get_url(url_name, args)
                else:
                    url = self.get_url(url_name, args=(), kwargs=args)
                self.login()
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 404)
            except:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with(('links_405',))
    def test_unallowed_links_with_405_response(self):
        """
        @author: Polina Efremova
        @note: check unallowed links, that should response 404
        """
        for el in self.links_405:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 405)
            except:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))


class CustomTestCase(GlobalTestMixIn, TransactionTestCase):

    multi_db = True
    request_manager = RequestManager

    def _fixture_setup(self):
        if getattr(self, 'multi_db', False):
            databases = connections
        else:
            databases = [DEFAULT_DB_ALIAS]

        if settings.FIRST_DB:
            settings.FIRST_DB = False
            for db in databases:
                call_command('flush', verbosity=0, interactive=False, database=db)

                if getattr(self, 'fixtures', None):
                    # We have to use this slightly awkward syntax due to the fact
                    # that we're using *args and **kwargs together.
                    call_command('loaddata', *self.fixtures,
                                 **{'verbosity': 0, 'database': db})

        for db in databases:
            conn = connections[db]
            db_name = conn.settings_dict['NAME'].strip('_')
            cursor = conn.cursor()
            conn.connection.rollback()
            conn.connection.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            try:
                cursor.execute('CREATE DATABASE "%s" WITH TEMPLATE="%s"' % (db_name + '_', db_name))
            except:
                cursor.execute('DROP DATABASE "%s"' % (db_name + '_'))
                cursor.execute('CREATE DATABASE "%s" WITH TEMPLATE="%s"' % (db_name + '_', db_name))
            conn.close()
            conn.settings_dict['NAME'] = db_name + '_'

    def _fixture_teardown(self):
        if not connections_support_transactions():
            return super(TransactionTestCase, self)._fixture_teardown()

        # If the test case has a multi_db=True flag, teardown all databases.
        # Otherwise, just teardown default.
        if getattr(self, 'multi_db', False):
            databases = connections
        else:
            databases = [DEFAULT_DB_ALIAS]
        for db in databases:
            conn = connections[db]
            db_name = conn.settings_dict['NAME']
            conn.settings_dict['NAME'] = db_name.strip('_')
            conn.close()
            cursor = conn.cursor()
            conn.connection.rollback()
            conn.connection.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            cursor.execute('DROP DATABASE "%s"' % (db_name))

    def _post_teardown(self):
        self.custom_fixture_teardown()
        super(CustomTestCase, self)._post_teardown()
        self.for_post_tear_down()

    def _pre_setup(self):
        if getattr(settings, 'TEST_CASE_NAME', '') != self.__class__.__name__:
            settings.TEST_CASE_NAME = self.__class__.__name__
            settings.FIRST_DB = True
        ContentType.objects.clear_cache()
        self.custom_fixture_setup()
        super(CustomTestCase, self)._pre_setup()
        self.for_pre_setup()

    def custom_fixture_setup(self, **options):
        verbosity = int(options.get('verbosity', 1))
        for db in connections:
            if hasattr(self, 'fixtures_for_custom_db') and settings.FIRST_DB:
                fixtures = [fixture for fixture in self.fixtures_for_custom_db if fixture.endswith(db + '.json')]

                sequence_sql = []
                for fixture in fixtures:
                    data = get_fixtures_data(fixture)
                    sql = generate_sql(data)
                    cursor = connections[db].cursor()
                    try:
                        cursor.execute(sql)
                    except Exception, e:
                        sys.stderr.write("Failed to load fixtures for alias '%s': %s" % (db, str(e)))
                        transaction.rollback_unless_managed(using=db)
                    else:
                        transaction.commit_unless_managed(using=db)

                    for element in data:
                        sequence_sql.append(("SELECT setval(pg_get_serial_sequence('%s','%s'), coalesce(max(%s), 1), "
                                             "max(%s) IS NOT null) FROM %s;") % (element['model'], element['pk'],
                                                                                 element['pk'], element['pk'],
                                                                                 element['model']))
                if sequence_sql:
                    if verbosity >= 2:
                        sys.stdout.write("Resetting sequences\n")
                    for line in sequence_sql:
                        cursor.execute(line)
                transaction.commit(using=db)

    def custom_fixture_teardown(self):
        for db in connections:
            if hasattr(self, 'fixtures_for_custom_db') and db != DEFAULT_DB_ALIAS:
                cursor = connections[db].cursor()
                cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
                tables = cursor.fetchall()
                for table in tables:
                    try:
                        cursor.execute("DELETE FROM %s" % table)
                    except:
                        transaction.rollback_unless_managed(using=db)
                    else:
                        transaction.commit_unless_managed(using=db)

    def get_model(self, table_name, db_name=None):
        if not db_name:
            db_names = [db for db in connections if db != DEFAULT_DB_ALIAS]
            if db_names:
                db_name = db_names[0]
        cursor = connections[db_name].cursor()
        cursor.execute("SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS WHERE table_name=%s", (table_name,))
        column_names = [el[0] for el in cursor.fetchall()]
        cursor.execute("""SELECT kcu.column_name FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                          LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                          ON kcu.table_name = tc.table_name
                                AND kcu.constraint_name = tc.constraint_name
                          WHERE tc.table_name = '%s' AND tc.constraint_type='PRIMARY KEY'""" % (table_name,))
        pk_names = [el[0] for el in cursor.fetchall()]

        class Meta(CustomModel.Meta):
            db_table = table_name

        params = dict([(k, models.Field()) for k in set(column_names).difference(pk_names)])
        params.update(dict([(k, models.Field(primary_key=True, unique=True) if k != 'id'
                             else models.AutoField(primary_key=True,)) for k in pk_names]))
        params.update({'Meta': Meta, '__module__': CustomModel.__module__,
                       'objects': self.request_manager(db_name)})
        C = type(table_name, (CustomModel,), params)
        return C


class CustomTestCaseNew(CustomTestCase):

    """For Django>=1.8"""

    request_manager = RequestManagerNew

    def custom_fixture_setup(self, **options):
        verbosity = int(options.get('verbosity', 1))
        for db in connections:
            if hasattr(self, 'fixtures_for_custom_db') and settings.FIRST_DB:
                fixtures = [fixture for fixture in self.fixtures_for_custom_db if fixture.endswith(db + '.json')]

                sequence_sql = []
                for fixture in fixtures:
                    data = get_fixtures_data(fixture)
                    sql = generate_sql(data)
                    cursor = connections[db].cursor()
                    with transaction.atomic(using=db):
                        try:
                            cursor.execute(sql)
                        except Exception, e:
                            sys.stderr.write("Failed to load fixtures for alias '%s': %s" % (db, str(e)))

                    for element in data:
                        sequence_sql.append(("SELECT setval(pg_get_serial_sequence('%s','%s'), coalesce(max(%s), 1), "
                                             "max(%s) IS NOT null) FROM %s;") % (element['model'], element['pk'],
                                                                                 element['pk'], element['pk'],
                                                                                 element['model']))
                if sequence_sql:
                    if verbosity >= 2:
                        sys.stdout.write("Resetting sequences\n")
                    for line in sequence_sql:
                        cursor.execute(line)
                transaction.commit(using=db)

    def custom_fixture_teardown(self):
        for db in connections:
            if hasattr(self, 'fixtures_for_custom_db') and db != DEFAULT_DB_ALIAS:
                cursor = connections[db].cursor()
                cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
                tables = cursor.fetchall()
                for table in tables:
                    with transaction.atomic(using=db):
                        cursor.execute("DELETE FROM %s" % table)

