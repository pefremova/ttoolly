# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

from copy import copy, deepcopy
from datetime import datetime, date, time, timedelta
from decimal import Decimal

import inspect
from itertools import cycle
import json
from lxml.html import document_fromstring
import os
import psycopg2.extensions
from random import choice, randint, uniform
import re
from shutil import rmtree
import sys
import tempfile
from unittest import SkipTest
from unittest.util import strclass
import warnings

from builtins import str
from django import VERSION as DJANGO_VERSION
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db import transaction, DEFAULT_DB_ALIAS, connections, models
from django.db.models import Q, Manager, DateTimeField
from django.db.models.fields import FieldDoesNotExist
from django.http import HttpRequest
from django.template.defaultfilters import filesizeformat
from django.test import TransactionTestCase, TestCase
from django.test.testcases import connections_support_transactions
from django.test.utils import override_settings
from django.utils.encoding import force_text, force_bytes
from django.utils.http import urlsafe_base64_encode
from freezegun import freeze_time
from future.utils import viewitems, viewkeys, viewvalues, with_metaclass
from past.builtins import xrange, basestring

from .utils import (format_errors, get_error, get_randname, get_url_for_negative, get_url, get_captcha_codes,
                    get_random_email_value, get_fixtures_data, generate_sql, unicode_to_readable,
                    get_fields_list_from_response, get_real_fields_list_from_response, get_all_form_errors,
                    generate_random_obj, get_field_from_response, get_all_urls, convert_size_to_bytes,
                    get_random_file, get_all_field_names_from_model, FILE_TYPES)

if sys.version[0] == '2':
    from functools32 import wraps, update_wrapper
    from urllib import urlencode
else:
    from functools import wraps, update_wrapper
    from urllib.parse import urlencode

try:
    from django.core.urlresolvers import reverse, resolve
except Exception:
    # Django 2.0
    from django.urls import reverse, resolve


__all__ = ('ChangePasswordMixIn',
           'CustomModel',
           'CustomTestCase',
           'CustomTestCaseNew',
           'EmailLog',
           'FormAddTestMixIn',
           'FormDeleteTestMixIn',
           'FormEditTestMixIn',
           'FormRemoveTestMixIn',
           'FormTestMixIn',
           'GlobalTestMixIn',
           'JsonResponseErrorsMixIn',
           'ListWithDelete',
           'LoginMixIn',
           'LoginTestMixIn',
           'PrettyTuple',
           'ResetPasswordMixIn',
           'Ring',
           'UserPermissionsTestMixIn',
           'only_with',
           'only_with_any_files_params',
           'only_with_files_params',
           'only_with_obj',)


def get_settings_for_move():
    return set(getattr(settings, 'SETTINGS_FOR_MOVE', []))


_redis_settings_by_worker = {}


def new_redis_settings():
    if DJANGO_VERSION < (1, 9):
        _worker_id = 0
    else:
        from django.test.runner import _worker_id

    global _redis_settings_by_worker
    d = _redis_settings_by_worker.get(_worker_id, None)
    if d is not None:
        return d

    def get_new_value(value):
        if isinstance(value, basestring) and value.startswith('redis://'):
            return '/'.join(value.split('/')[:-1] + [str(int(value.split('/')[-1]) + 10 * max(_worker_id, 1))])
        elif isinstance(value, dict):
            new_values_d = {k: get_new_value(v) for k, v in viewitems(value)}
            new_values_d = {k: v for k, v in viewitems(new_values_d) if v}
            if new_values_d:
                new_d = deepcopy(value)
                new_d.update(new_values_d)
                return new_d

    d = {}
    for name, value in viewitems(settings.__dict__):
        value = getattr(settings, name)
        new_value = get_new_value(value)
        if new_value:
            d[name] = new_value
    _redis_settings_by_worker[_worker_id] = d
    return d


class only_with_obj(object):

    skip_text = 'Need "obj"'

    def __init__(self, fn):
        self.fn = fn
        self.fn.decorators = getattr(fn, 'decorators', ()) + (self,)
        update_wrapper(self, fn)

    def __call__(self, cls, *args, **kwargs):
        if self.check(cls):
            return self.fn(cls, *args, **kwargs)
        else:
            raise SkipTest(self.skip_text)

    def check(self, cls):
        return cls.obj


class only_with(object):

    def __init__(self, param_names):
        if not isinstance(param_names, (tuple, list)):
            param_names = (param_names,)
        self.param_names = param_names
        self.skip_text = "Need all these params: %s" % repr(self.param_names)

    def __call__(self, fn, *args, **kwargs):

        @wraps(fn)
        def tmp(cls):
            if self.check(cls):
                return fn(cls, *args, **kwargs)
            else:
                raise SkipTest(self.skip_text)

        tmp.decorators = getattr(fn, 'decorators', ()) + (self,)
        return tmp

    def check(self, cls):
        return all(getattr(cls, param_name, None) for param_name in self.param_names)


class only_with_files_params(object):

    def __init__(self, param_names):
        if not isinstance(param_names, (tuple, list)):
            param_names = (param_names,)
        self.param_names = param_names

    def __call__(self, fn, *args, **kwargs):

        @wraps(fn)
        def tmp(cls):
            if self.check(cls):
                return fn(cls, *args, **kwargs)
            else:
                raise SkipTest(self.skip_text)

        tmp.decorators = getattr(fn, 'decorators', ()) + (self,)
        self.fn = fn
        return tmp

    def check(self, cls):
        params_dict_name = 'file_fields_params' + ('_add' if '_add_' in self.fn.__name__ else '_edit')
        self.skip_text = "Need all these keys in %s: %s" % (params_dict_name, repr(self.param_names))

        def check_params(field_dict, param_names):
            return all([param_name in viewkeys(field_dict) for param_name in param_names])

        to_run = any([check_params(field_dict, self.param_names)
                      for field_dict in getattr(cls, params_dict_name).values()])
        if to_run:
            if not all([check_params(field_dict, self.param_names) for field_dict in
                        getattr(cls, params_dict_name).values()]):
                warnings.warn('%s not set for all fields' % force_text(self.param_names))
        return to_run


class only_with_any_files_params(object):

    def __init__(self, param_names):
        if not isinstance(param_names, (tuple, list)):
            param_names = (param_names,)
        self.param_names = param_names

    def __call__(self, fn, *args, **kwargs):

        @wraps(fn)
        def tmp(cls):
            if self.check(cls):
                return fn(cls, *args, **kwargs)
            else:
                raise SkipTest(self.skip_text)

        tmp.decorators = getattr(fn, 'decorators', ()) + (self,)
        self.fn = fn
        return tmp

    def check(self, cls):
        params_dict_name = 'file_fields_params' + ('_add' if '_add_' in self.fn.__name__ else '_edit')
        self.skip_text = "Need any of these keys in %s: %s" % (params_dict_name, repr(self.param_names))

        def check_params(field_dict, param_names):
            return any([param_name in viewkeys(field_dict) for param_name in param_names])

        to_run = any([check_params(field_dict, self.param_names)
                      for field_dict in getattr(cls, params_dict_name).values()])
        if to_run:
            if not all([check_params(field_dict, self.param_names) for field_dict in getattr(cls, params_dict_name).values()]):
                warnings.warn('%s not set for all fields' % force_text(self.param_names))
        return to_run


class DictToJson(dict):

    def __str__(self):

        def get_value(v):
            if isinstance(v, dict):
                return {kk: get_value(vv) for kk, vv in viewitems(v)}
            if v is None:
                return v
            if isinstance(v, list):
                return [get_value(vv) for vv in v]
            if isinstance(v, bool):
                return v
            return str(v)

        res = json.dumps({k: get_value(v) for k, v in viewitems(self)})
        return res


class PrettyTuple(tuple):

    def __format__(self, format):
        return ', '.join(self)


class ListWithDelete(list):

    def delete(self):
        mail.outbox = list(set(mail.outbox).difference(self))


class EmailLogManager(Manager):
    """
    This class is for use as obj in testcases without real object, with only email send.
    Should redefine assert_object_fields for check email as object
    """

    def values_list(self, *args, **kwargs):
        if args == ('pk',):
            return [hash(m) for m in mail.outbox]
        Manager.values_list(self, *args, **kwargs)

    def exclude(self, *args, **kwargs):
        if 'pk__in' in viewkeys(kwargs):
            res = [m for m in mail.outbox if hash(m) not in kwargs['pk__in']]
            for m in res:
                m.pk = hash(m)
            return ListWithDelete(res)
        Manager.exclude(self, *args, **kwargs)

    def filter(self, *args, **kwargs):
        if 'pk' in viewkeys(kwargs):
            res = [m for m in mail.outbox if hash(m) == kwargs['pk']]
            for m in res:
                m.pk = hash(m)
            return ListWithDelete(res)
        Manager.filter(self, *args, **kwargs)

    def get_query_set(self):
        return ListWithDelete(mail.outbox)

    def all(self):
        return ListWithDelete(mail.outbox)

    def count(self):
        return len(mail.outbox)

    def latest(self, *args, **kwargs):
        return mail.outbox[-1]


class EmailLog(models.Model):
    created_at = DateTimeField(auto_now=True)

    objects = EmailLogManager()


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
        if not 200 <= response.status_code < 300:
            try:
                return json.loads(force_text(response.content))
            except Exception:
                return super(JsonResponseErrorsMixIn, self).get_all_form_errors(response)
        try:
            return json.loads(response.content)['errors']
        except Exception:
            return super(JsonResponseErrorsMixIn, self).get_all_form_errors(response)


class MetaCheckFailures(type):

    def __init__(cls, name, bases, dct):
        def check_errors(fn):
            @wraps(fn)
            def tmp(self):
                fn(self)
                self.formatted_assert_errors()
            decorators = getattr(tmp, 'decorators', ())
            if not 'check_errors' in [getattr(d, '__name__', d.__class__.__name__) for d in decorators]:
                tmp.decorators = decorators + (check_errors,)
            return tmp

        def decorate(cls, bases, dct):
            for attr in cls.__dict__:
                if callable(getattr(cls, attr)) and attr.startswith('test') and \
                        'check_errors' not in [getattr(d, '__name__', d.__class__.__name__)
                                               for d in getattr(getattr(cls, attr), 'decorators', ())]:
                    setattr(cls, attr, check_errors(getattr(cls, attr)))
            bases = cls.__bases__
            for base in bases:
                decorate(base, base.__bases__, base.__dict__)
            return cls

        decorate(cls, bases, dct)
        super(MetaCheckFailures, cls).__init__(name, bases, dct)


class Ring(cycle):

    def turn(self):
        next(self)

    def get_and_turn(self):
        return next(self)


class DictWithPassword(dict):

    def __init__(self, d, password1='password1', password2='password2'):
        self.password1 = password1
        self.password2 = password2
        super(DictWithPassword, self).__init__(d)

    def __setitem__(self, k, v):
        if hasattr(self, 'password1') and k == self.password1 and v:
            self[self.password2] = v

        super(DictWithPassword, self).__setitem__(k, v)

    def update(self, d):
        if self.password1 in viewkeys(d) and not self.password2 in viewkeys(d):
            d[self.password2] = d[self.password1]
        return super(DictWithPassword, self).update(d)


class GlobalTestMixIn(with_metaclass(MetaCheckFailures, object)):
    additional_params = None
    all_unique = None
    choice_fields_values = None
    custom_error_messages = None
    errors = []
    files = []
    longMessage = False
    maxDiff = None
    non_field_error_key = '__all__'
    unique_fields = None
    with_captcha = None

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
        if self.custom_error_messages is None:
            self.custom_error_messages = {}
        super(GlobalTestMixIn, self).__init__(*args, **kwargs)

    def __call__(self, *args, **kwargs):
        if getattr(settings, 'TEST_SPEEDUP_EXPERIMENTAL', False):
            fn = getattr(self, self._testMethodName)

            need_skip = False
            skip_text = ''
            for decorator in reversed(getattr(fn, 'decorators', ())):
                check = getattr(decorator, 'check', None)
                if check:
                    need_skip = not(check(self))
                    if need_skip:
                        skip_text = decorator.skip_text
                        break
            fn.__func__.__unittest_skip__ = need_skip
            if need_skip:
                fn.__func__.__unittest_skip_why__ = skip_text
        super(GlobalTestMixIn, self).__call__(*args, **kwargs)

    def __str__(self):
        return "%s.%s" % (strclass(self.__class__), self._testMethodName)

    def _fixture_setup(self):
        if getattr(settings, 'TEST_CASE_NAME', self.__class__.__name__) != self.__class__.__name__:
            delattr(settings, 'TEST_CASE_NAME')
        super(GlobalTestMixIn, self)._fixture_setup()

    def _post_teardown(self):
        super(GlobalTestMixIn, self)._post_teardown()
        self.for_post_tear_down()

    def _pre_setup(self):
        super(GlobalTestMixIn, self)._pre_setup()
        self.for_pre_setup()

    @property
    def get_obj_manager(self):
        if hasattr(self, 'obj') and self.obj:
            if self.obj == EmailLog:
                return self.obj.objects
            return self.obj._base_manager

    def for_post_tear_down(self):
        self.del_files()
        for name in get_settings_for_move():
            path = getattr(settings, name)
            if path.startswith(tempfile.gettempdir()):
                rmtree(path)
        self._ttoolly_modified_settings.disable()

    def for_pre_setup(self):
        self.errors = []
        d = new_redis_settings()
        d.update({name: tempfile.mkdtemp('_' + name)
                  for name in get_settings_for_move()})
        self._ttoolly_modified_settings = override_settings(**d)
        self._ttoolly_modified_settings.enable()
        for k in [k for k in dir(self) if not k.startswith(('_', 'test_'))
                  and k not in ('files', 'get_obj_manager')]:
            v = getattr(self, k)
            if isinstance(v, (list, dict)) and not isinstance(getattr(type(self), k, None), property):
                setattr(self, k, self.deepcopy(v) if isinstance(v, dict) else copy(v))

    def assertEqual(self, *args, **kwargs):
        with warnings.catch_warnings(record=True) as warn:
            warnings.simplefilter("always")
            try:
                return super(GlobalTestMixIn, self).assertEqual(*args, **kwargs)
            except Exception as e:
                if warn:
                    message = force_text(warn[0].message) + '\n' + force_text(e)
                    e.args = (message,)
                raise e

    def _assert_dict_equal(self, d1, d2, parent_key=''):
        text = []
        parent_key = '[%s]' % parent_key.strip('[]') if parent_key else ''
        not_in_second = set(viewkeys(d1)).difference(viewkeys(d2))
        not_in_first = set(viewkeys(d2)).difference(viewkeys(d1))
        if not_in_first:
            text.append('Not in first dict: %s' % repr(list(not_in_first)))
        if not_in_second:
            text.append('Not in second dict: %s' % repr(list(not_in_second)))
        for key in set(viewkeys(d1)).intersection(viewkeys(d2)):
            errors = []
            if d1[key] != d2[key]:
                if isinstance(d1[key], dict) and isinstance(d2[key], dict):
                    res = self._assert_dict_equal(d1[key], d2[key], parent_key + '[%s]' % key)
                    if res:
                        text.append(parent_key + '[%s]:\n  ' % key + '\n  '.join(res.splitlines()))
                elif isinstance(d1[key], list) and isinstance(d2[key], list):
                    try:
                        self.assert_list_equal(d1[key], d2[key])
                    except Exception:
                        self.errors_append(errors)
                        text.append('%s[%s]:\n%s' % (parent_key if parent_key else '', key, '\n'.join(errors)))
                else:
                    d1_value = d1[key] if ((isinstance(d1[key], str) and isinstance(d2[key], str)) or
                                           (isinstance(d1[key], bytes) and isinstance(d2[key], bytes))) \
                        else repr(d1[key])
                    d1_value = d1_value if isinstance(d1_value, str) else d1_value.decode('utf-8')
                    d2_value = d2[key] if ((isinstance(d1[key], str) and isinstance(d2[key], str)) or
                                           (isinstance(d1[key], bytes) and isinstance(d2[key], bytes))) \
                        else repr(d2[key])
                    d2_value = d2_value if isinstance(d2_value, str) else d2_value.decode('utf-8')
                    text.append('%s[%s]: %s != %s' % (parent_key if parent_key else '', key, d1_value, d2_value))
        res = '\n'.join(text)

        return res

    def assert_dict_equal(self, d1, d2, msg=None):
        msg = msg + ':\n' if msg else ''
        self.assertIsInstance(d1, dict, msg + 'First argument is not a dictionary')
        self.assertIsInstance(d2, dict, msg + 'Second argument is not a dictionary')

        if d1 != d2:
            diff = self._assert_dict_equal(d1, d2)

            error_message = self._truncateMessage(msg, diff)
            self.fail(self._formatMessage(error_message, None))

    def assert_form_equal(self, form_fields, etalon_fields, text=''):
        text = (text + ':\n') if text else ''
        errors = []
        not_present_fields = set(etalon_fields).difference(form_fields)
        if not_present_fields:
            errors.append('Fields %s not at form' % force_text(list(not_present_fields)))
        present_fields = set(form_fields).difference(etalon_fields)
        if present_fields:
            errors.append("Fields %s not need at form" % force_text(list(present_fields)))
        count_dict_form = {k: form_fields.count(k) for k in form_fields}
        count_dict_etalon = {k: etalon_fields.count(k) for k in etalon_fields}
        for field, count_in_etalon in viewitems(count_dict_etalon):
            count_in_form = count_dict_form.get(field, None)
            if count_in_form and count_in_form != count_in_etalon:
                errors.append("Field %s present at form %s time(s) (should be %s)" %
                              (repr(field), count_in_form, count_in_etalon))

        if errors:
            error_message = ';\n'.join(errors)
            if text:
                error_message = text + error_message
            raise AssertionError(error_message)

    def assert_list_equal(self, list1, list2, msg=None):
        msg = msg + ':\n' if msg else ''
        self.assertIsInstance(list1, list, msg + 'First argument is not a list')
        self.assertIsInstance(list2, list, msg + 'Second argument is not a list')

        if list1 != list2:
            diff = self._assert_list_equal(list1, list2)
            error_message = self._truncateMessage(msg, diff)
            self.fail(self._formatMessage(error_message, None))

    def _assert_list_equal(self, list1, list2):
        errors = []
        if all([isinstance(el, dict) for el in list1]) and all([isinstance(el, dict) for el in list2]):
            i = -1
            for i, el in enumerate(list2):
                if i >= len(list1):
                    errors.append('[line %d]: Not in first list' % i)
                else:
                    res = self._assert_dict_equal(list1[i], el)
                    if res:
                        errors.append('[line %d]: ' % i + res)
            for j in xrange(i + 1, len(list1)):
                errors.append('[line %d]: Not in second list' % j)

        elif all([isinstance(el, list) for el in list1]) and all([isinstance(el, list) for el in list2]):
            i = -1
            for i, el in enumerate(list2):
                if i >= len(list1):
                    errors.append('[line %d]: ' % i + 'Not in first list')
                else:
                    res = self._assert_list_equal(list1[i], el)
                    if res:
                        errors.append('[line %d]: ' % i + res)
            for j in xrange(i + 1, len(list1)):
                errors.append('[line %d]: Not in second list' % j)

        else:
            try:
                self.assertEqual(list1, list2)
            except Exception:
                _, v, _ = sys.exc_info()
                errors.append(force_text(v))

        res = '\n'.join(errors)
        if not isinstance(res, str):
            res = res.decode('utf-8')
        return res

    def assert_mail_content(self, m, params):
        default_params = {'from_email': settings.DEFAULT_FROM_EMAIL,
                          'attachments': [],
                          'alternatives': [],
                          'bcc': [],
                          'cc': [],
                          'reply_to': [],
                          'to': [],
                          'subject': '',
                          'body': ''}
        default_params.update(params)
        errors = []
        for field in set(viewkeys(default_params)).difference(('body', 'attachments', 'alternatives')):
            try:
                self.assertEqual(getattr(m, field), default_params[field])
            except Exception:
                self.errors_append(errors, text='[%s]' % field)
        try:
            self.assert_text_equal_by_symbol(m.body, default_params['body'])
        except Exception:
            self.errors_append(errors, text='[body]')

        try:
            self.assertEqual(len(getattr(m, 'alternatives', [])), len(default_params['alternatives']),
                             '%s alternatives in mail, expected %s' % (len(getattr(m, 'alternatives', [])),
                                                                       len(default_params['alternatives'])))
            for n, alternative in enumerate(default_params['alternatives']):
                m_alternative = m.alternative[n]
                self.assert_text_equal_by_symbol(m_alternative[0], alternative[0])
                self.assertEqual(m_alternative[1], alternative[1])
        except Exception:
            self.errors_append(errors, text='[alternatives]')

        try:
            self.assertEqual(len(m.attachments), len(default_params['attachments']),
                             '%s attachments in mail, expected %s' % (len(m.attachments),
                                                                      len(default_params['attachments'])))
            for n, attachment in enumerate(default_params['attachments']):
                m_attachment = m.attachments[n]
                self.assertEqual(m_attachment[0], attachment[0])
                self.assertEqual(hash(m_attachment[1]), hash(attachment[1]),
                                 'Attachment[%s] content and expected value are not equals' % n)
        except Exception:
            self.errors_append(errors, text='[attachments]')

        if getattr(m, 'content_subtype', None) not in ('html', 'text/html') and re.match('<[\w]', m.body):
            errors.append('Not html message type (%s), but contains html tags in body' %
                          getattr(m, 'content_subtype', None))

        for n, alternative in enumerate(getattr(m, 'alternatives', [])):
            if alternative[1] not in ('html', 'text/html') and re.match('<[\w]|/\w>', alternative[0]):
                errors.append(
                    '[alternatives][%d]: Not html message type (%s), but contains html tags in body' %
                    (n, alternative[1]))
        if errors:
            raise AssertionError('\n'.join(errors))

    def assert_mail_count(self, mails=None, count=None):
        error = ''
        mails = mails or mail.outbox
        mails_count = len(mails)
        if mails_count != count:
            error = 'Sent %d mails expect of %d.' % (mails_count, count)
            if mails_count > 0:
                m_to = [force_text(m.to) for m in mails]
                m_to.sort()
                error += ' To %s' % ', '.join(m_to)
        if error:
            self.assertEqual(mails_count, count, error)

    def assert_no_form_errors(self, response):
        form_errors = self.get_all_form_errors(response)
        if form_errors:
            raise AssertionError('There are errors at form: ' + repr(form_errors))

    def assert_objects_count_on_add(self, is_positive, initial_obj_count=0, additional=1):
        if is_positive:
            self.assertEqual(self.get_obj_manager.count(), initial_obj_count + additional,
                             'Objects count after add = %s (expect %s)' %
                             (self.get_obj_manager.count(), initial_obj_count + additional))
        else:
            self.assertEqual(self.get_obj_manager.count(), initial_obj_count,
                             'Objects count after wrong add = %s (expect %s)' %
                             (self.get_obj_manager.count(), initial_obj_count))

    def assert_objects_equal(self, obj1, obj2, exclude=None, other_values=None, changed=None, msg=None):
        other_values = other_values or {}
        changed = list(changed or [])
        exclude = list(set(exclude or []).union(changed))
        if (getattr(self, 'obj', None) and isinstance(obj1, self.obj)) or not getattr(self, 'obj', None):
            exclude.extend(getattr(self, 'exclude_from_check', []))
        local_errors = []

        object_fields = self.get_object_fields(obj1)
        object2_fields = self.get_object_fields(obj2)

        object_fields.extend(object2_fields)
        assert_text = []
        for field in set(object_fields).difference(exclude):
            value1 = self.get_value_for_compare(obj1, field)

            if field in other_values.keys():
                value2 = other_values[field]
                try:
                    self._assert_object_field(value1, value2, field)
                except AssertionError:
                    assert_text.append('[%s]: %r != %r' % (field, value1, value2))
            else:
                value2 = self.get_value_for_compare(obj2, field)
                if value1 != value2:
                    assert_text.append('[%s]: %r != %r' % (field, value1, value2))

        if assert_text:
            local_errors.append('\n'.join(assert_text))

        assert_text = []
        for field in changed:
            value1 = self.get_value_for_compare(obj1, field)
            value2 = self.get_value_for_compare(obj2, field)
            if value1 == value2:
                assert_text.append('[%s]: %r' % (field, value1))
        if assert_text:
            local_errors.append('This values should be changed but not:\n' + '\n'.join(assert_text))

        if local_errors:
            error_message = format_errors(local_errors)
            if msg:
                error_message = msg + ':\n' + error_message
            raise AssertionError(error_message)

    def _assert_object_field(self, value, params_value, field=None):
        self.assertEqual(value, params_value, field)

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
            for k, v in viewitems(other_values_for_check):
                other_values[k] = other_values.get(k, v)
        params.update(other_values)

        local_errors = []
        object_fields = get_all_field_names_from_model(obj)
        fields_map = {name: self.get_field_by_name(obj, name) for name in object_fields}
        object_related_field_names = [name for name in object_fields if
                                      fields_map[name].__class__.__name__ in ('RelatedObject',
                                                                              'ManyToOneRel',
                                                                              'OneToOneField',
                                                                              'OneToOneRel',
                                                                              'ManyToManyField')]

        form_to_field_map = self.get_related_names(obj)
        field_to_form_map = {v: k for k, v in iter(viewitems(form_to_field_map)) if v != k}
        form_related_names = [field_to_form_map.get(name, name) for name in object_related_field_names]

        fields_for_check = set(viewkeys(params)).intersection(object_fields)
        fields_for_check.update([k.split('-')[0] for k in viewkeys(params) if k.split('-')[0]
                                 in form_related_names])
        fields_for_check = fields_for_check.difference(exclude)

        object_one_to_one_field_names = [name for name in object_related_field_names if
                                         fields_map[name].__class__.__name__ == 'OneToOneField' or
                                         getattr(fields_map[name], 'field', None) and
                                         fields_map[name].field.__class__.__name__ == 'OneToOneField']
        form_one_to_one_names = [field_to_form_map.get(name, name) for name in object_one_to_one_field_names]
        form_to_object_map = {field_to_form_map.get(name, name): fields_map[name].get_accessor_name() for name in object_related_field_names if
                              hasattr(fields_map[name], 'get_accessor_name')}

        for field in fields_for_check:
            name_on_form = field
            name_in_field = form_to_field_map.get(field, field)
            name_in_object = form_to_object_map.get(field, field)

            # TODO: refactor me
            if name_on_form in form_one_to_one_names:
                cls = fields_map[name_in_field]
                obj_field_in_related_query = self.get_related_field_name(cls)
                _model = getattr(cls, 'related_model', None) or cls.related.parent_model
                value = _model._base_manager.filter(**{obj_field_in_related_query: obj})
                if value:
                    value = value[0]
                else:
                    value = None
            else:
                value = getattr(obj, name_in_object)
            if (name_on_form in viewkeys(form_to_field_map) or name_in_field in viewkeys(field_to_form_map) and
                (hasattr(params.get(name_on_form, []), '__len__') and  # params value is list or not exists (inline form)
                 (value.__class__.__name__ in ('RelatedManager', 'QuerySet') or
                  set([mr.__name__ for mr in value.__class__.__mro__]).intersection(['Manager', 'Model', 'ModelBase'])))):

                if hasattr(params.get(name_on_form, None), '__len__'):
                    count_for_check = len(params[name_on_form])
                else:
                    count_for_check = params.get('%s-TOTAL_FORMS' % name_on_form, None)

                if value is not None:
                    if count_for_check is not None and value.__class__.__name__ == 'RelatedManager':
                        try:
                            self.assertEqual(value.all().count(), count_for_check)
                        except Exception as e:
                            local_errors.append('[%s]: count ' % (field.encode('utf-8') if isinstance(field, str)
                                                                  else field) + force_text(e))

                    for i, el in enumerate(value.all().order_by('pk')
                                           if value.__class__.__name__ in ('RelatedManager', 'QuerySet')
                                           else [value, ]):
                        _params = dict([(k.replace('%s-%d-' % (name_on_form, i), ''),
                                         params[k]) for k in viewkeys(params) if
                                        k.startswith('%s-%d-' % (name_on_form, i)) and
                                        k not in exclude and re.sub('\-\d+\-', '-_-', k) not in exclude])
                        if (not _params and params.get(name_on_form, None) and isinstance(params[name_on_form], (list, tuple)) and
                                all([isinstance(value_el, FILE_TYPES + (ContentFile,)) for value_el in params[name_on_form]])):
                            """Try check multiple file field.
                            But you should redefine assert_object_fields in test with params like `field-0-file_obj`"""
                            el_file_fields = [f.name for f in el._meta.fields if
                                              set([m.__name__ for m in f.__class__.__mro__]).intersection(['FileField', 'ImageField'])]
                            if len(el_file_fields) == 1:
                                _params = {el_file_fields[0]: params[name_on_form]
                                           [i] if len(params[name_on_form]) > i else ''}
                        try:
                            self.assert_object_fields(el, _params)
                        except Exception as e:
                            local_errors.append('[%s]:%s' % (field.encode('utf-8') if isinstance(field, str)
                                                             else field, '\n  '.join(force_text(e).splitlines())))
                elif count_for_check:
                    local_errors.append('[%s]: expected count %s, but value is None' %
                                        ((field.encode('utf-8') if isinstance(field, str) else field),
                                         count_for_check))

                continue

            params_value = params[name_on_form]
            value, params_value = self.get_params_according_to_type(value, params_value)

            try:
                self._assert_object_field(value, params_value, field)
            except AssertionError:
                if isinstance(value, basestring):
                    value = value if len(str(value)) <= 1000 else str(value)[:1000] + '...'
                if isinstance(params_value, basestring):
                    params_value = params_value if len(str(params_value)) <= 1000 else str(params_value)[:1000] + '...'
                text = '[%s]: %s != %s' % (force_text(field), force_text(repr(value)), force_text(repr(params_value)))
                local_errors.append(text)

        if local_errors:
            raise AssertionError("Values from object != expected values from dict:\n" + "\n".join(local_errors))

    def assert_text_equal_by_symbol(self, first, second, additional=20):
        full_error_text = ''
        if '-v' in sys.argv:
            try:
                self.assertEqual(first, second)
            except AssertionError as e:
                full_error_text = '\n\nFull error message text:\n%s' % unicode_to_readable(force_text(e))
        if first == second:
            return
        first_length = len(first)
        second_length = len(second)
        for n in xrange(max(first_length, second_length)):

            text = ('Not equal in position %d: ' % n +
                    "'%s%s' != '%s%s'" % (first[n: n + additional] if isinstance(first[n: n + additional], str) else repr(first[n: n + additional]),
                                          '...' if (n + additional < first_length) else '',
                                          second[
                                              n: n + additional] if isinstance(second[n: n + additional], str) else repr(second[n: n + additional]),
                                          '...' if (n + additional < second_length) else ''))
            self.assertEqual(first[n:n + 1],
                             second[n:n + 1],
                             text + full_error_text)

    def assert_xpath_count(self, response, path, count=1, status_code=200, msg=None):
        error_message = "Response status code %s != %s" % (response.status_code, status_code)
        if msg:
            error_message = msg + ':\n' + error_message
        self.assertEqual(response.status_code, status_code, error_message)
        if not ('xml' in force_text(response.content) and 'encoding' in force_text(response.content)):
            res = force_text(response.content)
        else:
            res = response.content
        self.assert_xpath_count_in_html(res, path, count)

    def assert_xpath_count_in_html(self, html, path, count, msg=None):
        doc = document_fromstring(html)
        real_count = len(doc.xpath(path))
        error_message = 'Found %s instances of \'%s\' (Should be %s)' % (real_count, path, count)
        if msg:
            error_message = msg + ':\n' + error_message
        self.assertEqual(real_count, count, error_message)

    def deepcopy(self, params):
        tmp_params = {}
        old_params = params
        params = copy(params)
        keys = list(params.keys())
        for k in keys:
            if isinstance(params[k], FILE_TYPES + (ContentFile,)):
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
        text = (force_text(text) + ':\n') if text else ''
        if isinstance(text, bytes):
            text = text.decode('utf-8')
        if getattr(settings, 'COLORIZE_TESTS', False) and text:
            text = "\x1B[38;5;%dm" % color + text + "\x1B[0m"
        result = text + get_error()
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
        if not response.context:
            return None
        try:
            return [ld.message for ld in response.context['messages']._loaded_data]
        except KeyError:
            pass

    def get_all_form_errors(self, response):
        return get_all_form_errors(response)

    def get_error_field(self, message_type, field):
        if isinstance(field, (list, tuple)):
            return self.non_field_error_key
        if message_type in ('inactive_user', 'wrong_login', 'wrong_captcha'):
            return self.non_field_error_key

        error_field = re.sub(r'_(\d|ru)$', '', field)
        if message_type == 'max_length' and self.is_file_field(field):
            message_type = 'max_length_file'
        elif message_type == 'max_block_count':
            error_field = field + '-' + self.non_field_error_key
        messages_dict = self.deepcopy(getattr(settings, 'ERROR_MESSAGES', {}))
        messages_dict.update(getattr(self, 'custom_error_messages', {}))
        error_message = ''
        if field in viewkeys(messages_dict):
            field_dict = messages_dict[field]
            if message_type in ('max_length', 'max_length_file'):
                error_message = field_dict.get('max_length', field_dict.get('max_length_file', ''))
            else:
                error_message = field_dict.get(message_type, error_message)

        if isinstance(error_message, dict):
            error_field = list(error_message.keys())[0]
        return error_field

    def get_error_message(self, message_type, field, *args, **kwargs):
        previous_locals = kwargs.get('locals', {})
        if not previous_locals:
            for frame in inspect.getouterframes(inspect.currentframe()):
                if frame[3].startswith('test'):
                    break
            previous_locals = frame[0].f_locals
        if 'field' not in viewkeys(previous_locals):
            previous_locals['field'] = field
        if message_type == 'max_length' and self.is_file_field(field):
            message_type = 'max_length_file'
        previous_locals['verbose_obj'] = self.obj._meta.verbose_name if getattr(self, 'obj', None) else 'Объект'
        if isinstance(previous_locals['verbose_obj'], bytes):
            previous_locals['verbose_obj'] = previous_locals['verbose_obj'].decode('utf-8')
        previous_locals['verbose_field'] = getattr(self.get_field_by_name(self.obj, field), 'verbose_name', field) if \
            (getattr(self, 'obj', None) and field in get_all_field_names_from_model(self.obj)) else field
        if isinstance(previous_locals['verbose_field'], bytes):
            previous_locals['verbose_field'] = previous_locals['verbose_field'].decode('utf-8')
        previous_locals['verbose_pk'] = self.obj._meta.pk.verbose_name if getattr(self, 'obj', None) else 'id'
        if isinstance(previous_locals['verbose_pk'], bytes):
            previous_locals['verbose_pk'] = previous_locals['verbose_pk'].decode('utf-8')
        ERROR_MESSAGES = {'required': 'Обязательное поле.',
                          'max_length': 'Убедитесь, что это значение содержит не ' +
                                        'более {length} символов (сейчас {current_length}).' if
                          (previous_locals.get('length', None) is None or
                           not isinstance(previous_locals.get('length'), int))
                          else 'Убедитесь, что это значение содержит не ' +
                          'более {length} символов (сейчас {current_length}).'.format(**previous_locals),
                          'max_length_file': 'Убедитесь, что это имя файла содержит не ' +
                          'более {length} символов (сейчас {current_length}).' if
                          (previous_locals.get('length', None) is None or
                           not isinstance(previous_locals.get('length'), int))
                          else 'Убедитесь, что это имя файла содержит не ' +
                          'более {length} символов (сейчас {current_length}).'.format(**previous_locals),
                          'max_length_digital': 'Убедитесь, что это значение меньше либо равно {max_value}.' if
                          (previous_locals.get('max_value', None) is None)
                          else 'Убедитесь, что это значение меньше либо равно {max_value}.'.format(**previous_locals),
                          'min_length': 'Убедитесь, что это значение содержит не ' +
                                        'менее {length} символов (сейчас {current_length}).' if
                          (previous_locals.get('length', None) is None or
                           not isinstance(previous_locals.get('length'), int))
                          else 'Убедитесь, что это значение содержит не ' +
                          'менее {length} символов (сейчас {current_length}).'.format(**previous_locals),
                          'min_length_digital': 'Убедитесь, что это значение больше либо равно {min_value}.' if
                          (previous_locals.get('min_value', None) is None)
                          else 'Убедитесь, что это значение больше либо равно {min_value}.'.format(**previous_locals),
                          'wrong_value': 'Выберите корректный вариант. Вашего ' +
                                         'варианта нет среди допустимых значений.' if
                                         'value' not in previous_locals.keys()
                                         else 'Выберите корректный вариант. {value} '.format(**previous_locals) +
                                         'нет среди допустимых значений.',
                          'wrong_value_int': 'Введите целое число.',
                          'wrong_value_digital': 'Введите число.',
                          'wrong_value_email': 'Введите правильный адрес электронной почты.',
                          'unique': '{verbose_obj} с таким {verbose_field} уже существует.'.format(**previous_locals),
                          'delete_not_exists': 'Произошла ошибка. Попробуйте позже.',
                          'recovery_not_exists': 'Произошла ошибка. Попробуйте позже.',
                          'empty_file': 'Отправленный файл пуст.',
                          'max_count_file': 'Допускается загрузить не более {max_count} файлов.' if
                                    (previous_locals.get('max_count', None) is None)
                                    else 'Допускается загрузить не более {max_count} файлов.'.format(**previous_locals),
                          'max_size_file': 'Размер файла {filename} больше {max_size}.' if
                                    (previous_locals.get('filename', None) is None or
                                     previous_locals.get('max_size', None) is None)
                                    else 'Размер файла {filename} больше {max_size}.'.format(**previous_locals),
                          'wrong_extension': 'Некорректный формат файла {filename}.' if
                                    previous_locals.get('filename', None) is None
                                    else 'Некорректный формат файла {filename}.'.format(**previous_locals),
                          'min_dimensions': 'Минимальный размер изображения {min_width}x{min_height}.' if
                                    (previous_locals.get('min_width', None) is None or
                                     previous_locals.get('min_height', None))
                          else 'Минимальный размер изображения {min_width}x{min_height}.'.format(**previous_locals),
                          'max_dimensions': 'Максимальный размер изображения {max_width}x{max_height}.' if
                                    (previous_locals.get('max_width', None) is None or
                                     previous_locals.get('max_height', None))
                          else 'Максимальный размер изображения {max_width}x{max_height}.'.format(**previous_locals),
                          'max_sum_size_file': 'Суммарный размер изображений не должен превышать {max_size}.' if
                                    previous_locals.get('max_size', None) is None
                                    else 'Суммарный размер изображений не должен превышать {max_size}.'.format(**previous_locals),
                          'one_of': 'Оставьте одно из значений в полях {group}.' if
                                    (previous_locals.get('group', None) is None)
                                    else 'Оставьте одно из значений в полях {group}.'.format(**previous_locals),
                          'max_block_count': 'Пожалуйста, заполните не более {max_count} форм.' if
                                    previous_locals.get('max_count', None) is None
                                    else 'Пожалуйста, заполните не более {max_count} форм.'.format(**previous_locals),
                          'wrong_login': 'Пожалуйста, введите корректные адрес электронной почты и пароль для аккаунта. '
                                         'Оба поля могут быть чувствительны к регистру.',
                          'inactive_user': 'Эта учетная запись отключена.',
                          'wrong_captcha': 'Неверный код',
                          'not_exist': '{verbose_obj} с {verbose_field} "{value}" не существует. Возможно оно было удалено?' if
                                         previous_locals.get('value', '') == '' else
                                         '{verbose_obj} с {verbose_pk} "{value}" не существует. Возможно оно было удалено?'.format(
                                             **previous_locals),
                          'wrong_password_similar': 'Введённый пароль слишком похож на {user_field_name}.' if
                          previous_locals.get('user_field_name', '') == '' else
                          'Введённый пароль слишком похож на {user_field_name}.'.format(**previous_locals),
                          'with_null': 'Данные содержат запрещённый символ: ноль-байт.',
                          }

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
                and 'max_length' in viewkeys(custom_errors) \
                and message_type not in viewkeys(custom_errors):
            custom_errors[message_type] = custom_errors['max_length']

        if message_type in ('min_length_int', 'min_length_digital', 'min_length_file') \
                and 'min_length' in viewkeys(custom_errors) \
                and message_type not in viewkeys(custom_errors):
            custom_errors[message_type] = custom_errors['min_length']

        if message_type in ('without_required', 'empty_required'):
            if 'required' in viewkeys(custom_errors) and message_type not in viewkeys(custom_errors):
                custom_errors[message_type] = custom_errors['required']
            elif message_type not in viewkeys(custom_errors) and message_type not in viewkeys(ERROR_MESSAGES):
                message_type = 'required'

        ERROR_MESSAGES.update(custom_errors)
        error_message = ERROR_MESSAGES.get(message_type, '')
        if field is None:
            return [el.format(**previous_locals) for el in error_message] if isinstance(error_message, list) \
                else error_message.format(**previous_locals)

        if not isinstance(error_message, dict):
            error_field = self.get_error_field(message_type, kwargs.get('error_field', field))
            error_message = {error_field: [error_message] if not isinstance(error_message, list) else error_message}
        else:
            error_message = self.deepcopy(error_message)

        for k, v in viewitems(error_message):
            error_message[k] = [el.format(**previous_locals) for el in v] if isinstance(v, list) \
                else [v.format(**previous_locals)]
        return error_message

    def get_field_by_name(self, model, field):
        if re.findall(r'[\w_]+\-\d+\-[\w_]+', field):
            obj_related_objects = self.get_related_names(model)
            all_names = get_all_field_names_from_model(model)
            field_name = field.split('-')[0]
            field_name = field_name if field_name in all_names else obj_related_objects.get(field_name, field_name)
            related = model._meta.get_field(field_name)
            model = getattr(related, 'related_model', getattr(getattr(related, 'rel', None), 'to', related.model))
            field = field.split('-')[-1]
        return model._meta.get_field(field)

    def get_fields_list_from_response(self, response):
        if getattr(settings, 'TEST_REAL_FORM_FIELDS', False):
            return get_real_fields_list_from_response(response)
        return get_fields_list_from_response(response)

    def get_object_fields(self, obj):
        object_fields = []
        fields = obj._meta.get_fields()
        for field in fields:
            if field.__class__.__name__ in ('RelatedObject', 'ManyToOneRel', 'OneToOneRel'):
                object_fields.append(force_text(field.get_accessor_name()))
            else:
                object_fields.append(force_text(field.name))
        return object_fields

    def get_params_according_to_type(self, value, params_value):
        if type(value) == type(params_value):
            return value, params_value
        if value is None:
            value = ''
        if params_value is None:
            params_value = ''

        if isinstance(value, basestring) and isinstance(params_value, basestring):
            return force_text(value), force_text(params_value)
        if isinstance(value, bool):
            params_value = bool(params_value)
            return value, params_value
        if (isinstance(value, date) or isinstance(value, time)) and not (isinstance(params_value, date) or
                                                                         isinstance(params_value, time)):
            params_value_delimiters = re.findall(r'\d+(.)\d+\1\d+', params_value)

            if isinstance(value, datetime):
                format_str = '%d.%m.%Y %H:%M:%S'
                if params_value_delimiters:
                    date_format_elements = ['%d', '%m', '%Y']
                    date_delimiter = params_value_delimiters[0]
                    if len(params_value.split(date_delimiter)[0]) == 4:
                        date_format_elements.reverse()
                    time_format_elements = ['%H', '%M', '%S']
                    if len(params_value_delimiters) > 1:
                        time_delimiter = params_value_delimiters[1]
                    else:
                        time_delimiter = ':'
                    format_str = date_delimiter.join(
                        date_format_elements) + ' ' + time_delimiter.join(time_format_elements)

                value = value.strftime(format_str)
            elif isinstance(value, date):
                format_str = '%d.%m.%Y'
                if params_value_delimiters:
                    date_format_elements = ['%d', '%m', '%Y']
                    date_delimiter = params_value_delimiters[0]
                    if len(params_value.split(date_delimiter)[0]) == 4:
                        date_format_elements.reverse()
                    format_str = date_delimiter.join(date_format_elements)

                value = value.strftime(format_str)
            elif isinstance(value, time):
                format_str = '%H:%M:%S'
                if params_value_delimiters:
                    time_format_elements = ['%H', '%M', '%S']
                    time_delimiter = params_value_delimiters[0]
                    format_str = time_delimiter.join(time_format_elements)

                value = value.strftime(format_str)
            return value, params_value

        if isinstance(value, models.Model) and not isinstance(params_value, models.Model):
            value = value.pk
            params_value = int(params_value) if params_value else params_value
        elif value.__class__.__name__ in ('ManyRelatedManager', 'GenericRelatedObjectManager'):
            value = [force_text(v) for v in value.values_list('pk', flat=True)]
            value.sort()
            if hasattr(params_value, '__iter__'):
                params_value = [force_text(pv) for pv in params_value]
                params_value.sort()
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(params_value, (int, float, basestring)) and not isinstance(params_value, bool):
                value = force_text(value)
                params_value = force_text(params_value)
        elif isinstance(value, Decimal) and not isinstance(value, bool):
            if isinstance(params_value, (int, Decimal, float, basestring)) and not isinstance(params_value, bool):
                value = value
                if isinstance(params_value, (int, float)):
                    params_value = repr(params_value)
                params_value = Decimal(params_value) if params_value != '' else params_value
        elif (set([m.__name__ for m in value.__class__.__mro__]).intersection(['file', '_IOBase', 'FieldFile',
                                                                               'ImageFieldFile'])
              or isinstance(params_value, FILE_TYPES + (ContentFile,))):
            if value:
                value = value if isinstance(value, basestring) else value.name
                value = re.sub(r'_[a-zA-Z0-9]+(?=$|\.[\w\d]+$)', '', os.path.basename(value))
            else:
                value = ''
            params_value = params_value if isinstance(params_value, basestring) else params_value.name
            params_value = os.path.basename(params_value)

        return value, params_value

    def get_random_file(self, field, length=10, count=1, *args, **kwargs):
        self.with_files = True
        filename = get_randname(length, 'wrd')
        file_dict = self.deepcopy(getattr(self, 'file_fields_params', {}).get(field, {}) or
                                  getattr(self, 'file_fields_params_add', {}).get(field, {}) or
                                  getattr(self, 'file_fields_params_edit', {}).get(field, {}))

        if file_dict.get('extensions', ()):
            ext = choice(file_dict['extensions'])
            filename = filename[:-len(ext) - 1] + '.' + ext
        file_dict['filename'] = filename
        file_dict.update(kwargs)
        if count > 1 or self.is_file_list(field):
            res = []
            for i in xrange(count):
                f = get_random_file(*args, **file_dict)
                self.files.append(f)
                res.append(f)
        else:
            res = get_random_file(*args, **file_dict)
            self.files.append(res)

        return res

    def get_related_names(self, model):

        def get_all_related_objects(model):
            """from django docs"""
            return [f for f in model._meta.get_fields()
                    if (f.one_to_many or f.one_to_one)
                    and f.auto_created and not f.concrete]

        obj_related_objects = dict([(el.get_accessor_name(), getattr(el, 'var_name', el.get_accessor_name())) for el in
                                    get_all_related_objects(model)])

        if not(getattr(self, 'obj', None)) or isinstance(model, self.obj) or model == self.obj:
            obj_related_objects.update(getattr(self, 'related_names', {}))
        return obj_related_objects

    def get_related_field_name(self, field):
        """OneToOneField.related_query_name() или OneToOneRel.remote_field.name или OneToOneRel.field.name"""
        return (field.related_query_name and field.related_query_name() or
                getattr(field, 'remote_field', None) and field.remote_field.name or
                field.field.name)

    def get_value_for_compare(self, obj, field):
        # Because python2 return False on any exception, but python3 only on AttributeError.
        # Django return ValueError if use empty many_to_many field
        try:
            if not hasattr(obj, field):
                return None
        except (AttributeError, ValueError):
            return None

        if getattr(obj, field).__class__.__name__ in ('ManyRelatedManager', 'RelatedManager',
                                                      'GenericRelatedObjectManager'):
            value = [v for v in getattr(obj, field).values_list('pk', flat=True).order_by('pk')]
        else:
            value = getattr(obj, field)
            if 'File' in [m.__name__ for m in getattr(obj, field).__class__.__mro__] and not value:
                value = None
        return value

    def get_value_for_field(self, length, field_name):
        """for fill use name with -0-"""
        field_name = re.sub('\-\d+\-', '-0-', field_name)
        if self.is_email_field(field_name):
            length = length if length is not None else randint(getattr(self, 'min_fields_length', {}).get(field_name, 6),
                                                               getattr(self, 'max_fields_length', {}).get(field_name, 254))
            return get_random_email_value(length)
        if self.is_choice_field(field_name) and getattr(self, 'choice_fields_values', {}).get(field_name, ''):
            return choice(self.choice_fields_values[field_name])
        if self.is_digital_field(field_name):
            if getattr(self, 'obj', None):
                try:
                    if 'ForeignKey' in [b.__name__ for b in
                                        self.get_field_by_name(self.obj, field_name).__class__.__mro__]:
                        return choice(self.get_field_by_name(self.obj, field_name).related_model._base_manager.all()).pk
                except FieldDoesNotExist:
                    pass
            if 'get_digital_values_range' not in dir(self):
                length = length if length is not None else 10
                return get_randname(length, 'd')
            values_range = self.get_digital_values_range(field_name)
            if self.is_int_field(field_name):
                return randint(max(values_range['min_values']), min(values_range['max_values']))
            else:
                value = uniform(max(values_range['min_values']), min(values_range['max_values']))
                if getattr(self, 'max_decimal_places', {}).get(field_name, None):
                    value = round(value, self.max_decimal_places[field_name])
                return value
        if self.is_file_field(field_name):
            if length is None:
                length = max(getattr(self, 'max_fields_length', {}).get(field_name, 1),
                             max([1, ] + [len(ext) for ext in
                                          (getattr(self, 'file_fields_params_add', {}).get(field_name, {}).get('extensions', ()) +
                                           getattr(self, 'file_fields_params_edit', {}).get(field_name, {}).get('extensions', ()))]) + 2  # dot + 1 symbol
                             )
            value = self.get_random_file(field_name, length)
            return value
        if self.is_multiselect_field(field_name) and getattr(self, 'choice_fields_values', {}).get(field_name, []):
            values = self.choice_fields_values[field_name]
            return list(set([choice(values) for _ in xrange(randint(1, len(values)))]))
        if self.is_date_field(field_name):
            if field_name.endswith('1'):
                return datetime.now().strftime('%H:%M')
            elif self.is_datetime_field(field_name):
                return datetime.now().strftime(settings.DATETIME_INPUT_FORMATS[0])
            else:
                return datetime.now().strftime(settings.DATE_INPUT_FORMATS[0])

        length = length if length is not None else randint(getattr(self, 'min_fields_length', {}).get(field_name, 1),
                                                           getattr(self, 'max_fields_length', {}).get(field_name, 100000))
        return get_randname(length, 'w')

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
        field = re.sub('\-\d+\-', '-0-', field)
        return ((field in (getattr(self, 'choice_fields', ()) or ())) or
                (field in (getattr(self, 'choice_fields_add', ()) or ())) or
                (field in (getattr(self, 'choice_fields_edit', ()) or ())) or
                (field in (getattr(self, 'choice_fields_with_value_in_error', ()) or ())) or
                (field in (getattr(self, 'choice_fields_add_with_value_in_error', ()) or ())) or
                (field in (getattr(self, 'choice_fields_edit_with_value_in_error', ()) or ())))

    def is_date_field(self, field):
        field = re.sub('\-\d+\-', '-0-', field)
        return field in getattr(self, 'date_fields', ())

    def is_datetime_field(self, field):
        field = re.sub('\-\d+\-', '-0-', field)
        return field in getattr(self, 'datetime_fields', ())

    def is_digital_field(self, field):
        field = re.sub('\-\d+\-', '-0-', field)
        return ((field in (getattr(self, 'digital_fields', ()) or ())) or
                (field in (getattr(self, 'digital_fields_add', ()) or ())) or
                (field in (getattr(self, 'digital_fields_edit', ()) or ())))

    def is_email_field(self, field):
        field = re.sub('\-\d+\-', '-0-', field)
        return ('email' in field and [getattr(self, 'email_fields', None),
                                      getattr(self, 'email_fields_add', None),
                                      getattr(self, 'email_fields_edit', None)] == [None, None, None]) \
            or ((field in (getattr(self, 'email_fields', ()) or ())) or
                (field in (getattr(self, 'email_fields_add', ()) or ())) or
                (field in (getattr(self, 'email_fields_edit', ()) or ())))

    def is_file_list(self, field):
        field = re.sub('\-\d+\-', '-0-', field)
        if not self.is_file_field(field):
            return False
        for param_name in ('default_params', 'default_params_add', 'default_params_edit'):
            v = getattr(self, param_name, {}).get(field, None)
            if isinstance(v, (list, tuple)):
                return True
        return False

    def is_int_field(self, field):
        field = re.sub('\-\d+\-', '-0-', field)
        return ((field in (getattr(self, 'int_fields', ()) or ())) or
                (field in (getattr(self, 'int_fields_add', ()) or ())) or
                (field in (getattr(self, 'int_fields_edit', ()) or ())))

    def is_file_field(self, field):
        field = re.sub('\-\d+\-', '-0-', field)

        def check_by_params_name(name):
            params = getattr(self, name, None)
            if not params:
                return False
            if isinstance(params.get(field, None), FILE_TYPES + (ContentFile,)):
                return True
            if (isinstance(params.get(field, None), (list, tuple))
                    and params.get(field)
                    and all([isinstance(el, FILE_TYPES + (ContentFile,)) for el in params.get(field)])):
                return True
            return False

        return field not in getattr(self, 'not_file', []) and \
            (field in getattr(self, 'file_fields_params_add', {}).keys() or
             field in getattr(self, 'file_fields_params_edit', {}).keys() or
             re.findall(r'(^|[^a-zA-Z])(file)', field) or
             check_by_params_name('default_params') or
             check_by_params_name('default_params_add') or
             check_by_params_name('default_params_edit'))

    def is_multiselect_field(self, field):
        field = re.sub('\-\d+\-', '-0-', field)
        return ((field in (getattr(self, 'multiselect_fields', ()) or ())) or
                (field in (getattr(self, 'multiselect_fields_add', ()) or ())) or
                (field in (getattr(self, 'multiselect_fields_edit', ()) or ())))

    def pop_field_from_params(self, params, field):
        params.pop(field, None)

    def savepoint_rollback(self, sp):
        if isinstance(self, TestCase):
            transaction.savepoint_rollback(sp)

    def set_empty_value_for_field(self, params, field):
        mro_names = [m.__name__ for m in params[field].__class__.__mro__]
        if 'list' in mro_names or 'tuple' in mro_names or 'QuerySet' in mro_names:
            params[field] = []
        else:
            params[field] = ''

    def update_params(self, params):
        unique_keys = [k for el in viewkeys(self.all_unique) for k in el if not k.endswith(self.non_field_error_key)]
        for key in set(viewkeys(params)).intersection(unique_keys):
            default_value = params[key] or (getattr(self, 'default_params', {}) or
                                            getattr(self, 'default_params_add', {}) or
                                            getattr(self, 'default_params_edit', {}) or {}).get(key, None)
            key_for_get_values = key
            if '-' in key:
                key_for_get_values = '__'.join([key.split('-')[0].replace('_set', ''), key.split('-')[-1]])

            existing_values = [default_value]
            try:
                existing_values = [force_text(el)
                                   for el in self.get_obj_manager.values_list(key_for_get_values, flat=True)]
                # Нельзя использовать exists, т.к. будет падать для некоторых типов, например UUID
            except Exception:
                # FIXME: self.obj does not exists or FieldError
                pass
            n = 0
            if default_value != '' and default_value is not None:
                while n < 3 and force_text(params[key]) in existing_values:
                    n += 1
                    params[key] = self.get_value_for_field(None, key)

        for key, v in viewitems(params):
            if v and self.is_file_field(key):
                if isinstance(v, (list, tuple)):
                    file_value = self.get_value_for_field(None, key)
                    if not isinstance(file_value, list):
                        file_value = [file_value, ]
                    params[key] = file_value
                else:
                    params[key] = self.get_value_for_field(None, key)
        return params

    def update_captcha_params(self, url, params, force=False):
        if self.with_captcha or force:
            self.client.get(url, **self.additional_params)
            params.update(get_captcha_codes())


class LoginMixIn(object):

    def user_login(self, username, password, **kwargs):
        additional_params = kwargs.get('additional_params', getattr(self, 'additional_params', {}))
        url_name = getattr(settings, 'LOGIN_URL_NAME', 'login')
        params = {'username': username, 'password': password,
                  'this_is_the_login_form': 1}
        csrf_cookie = self.client.cookies.get(settings.CSRF_COOKIE_NAME, '')
        if csrf_cookie:
            params['csrfmiddlewaretoken'] = csrf_cookie.value
        else:
            response = self.client.get(reverse(url_name), follow=True, **additional_params)
            params['csrfmiddlewaretoken'] = response.cookies[settings.CSRF_COOKIE_NAME].value
        if hasattr(self, 'update_captcha_params'):
            self.update_captcha_params(reverse(url_name), params, force=True)
        else:
            params.update(get_captcha_codes())
        return self.client.post(reverse(url_name), params, **additional_params)

    def user_logout(self, **kwargs):
        additional_params = kwargs.get('additional_params', getattr(self, 'additional_params', {}))
        url_name = getattr(settings, 'LOGOUT_URL_NAME', 'auth_logout')
        return self.client.get(reverse(url_name), **additional_params)

    def user_relogin(self, username, password, **kwargs):
        self.user_logout(**kwargs)
        self.user_login(username, password, **kwargs)


class FormTestMixIn(GlobalTestMixIn):
    obj = None
    all_fields = None
    all_fields_add = None
    all_fields_edit = None
    check_null = None
    check_null_file_positive = None
    check_null_file_negative = None
    check_null_str_positive = None
    check_null_str_negative = None
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
    datetime_fields = ()
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
    fields_helptext = None
    fields_helptext_add = None
    fields_helptext_edit = None
    filter_params = None
    file_fields_params = None
    """{'field_name': {'extensions': ('jpg', 'txt'),
        'max_count': 3,
        'one_max_size': '3Mb',
        'sum_max_size': '9Mb'}}"""
    file_fields_params_add = None
    file_fields_params_edit = None
    hidden_fields = None
    hidden_fields_add = None
    hidden_fields_edit = None
    int_fields = None
    int_fields_add = None
    int_fields_edit = None
    max_blocks = None
    max_fields_length = {}
    min_fields_length = {}
    multiselect_fields = None
    multiselect_fields_add = None
    multiselect_fields_edit = None
    one_of_fields = None
    one_of_fields_add = None
    one_of_fields_edit = None
    required_fields = None
    required_fields_add = None
    required_fields_edit = None
    status_code_error = 200
    status_code_not_exist = 404
    status_code_success_add = 200
    status_code_success_edit = 200
    unique_with_case = None
    unique_fields_add = None
    unique_fields_edit = None
    url_add = ''

    def __init__(self, *args, **kwargs):
        super(FormTestMixIn, self).__init__(*args, **kwargs)
        if self.default_params is None:
            self.default_params = {}
        if not self.default_params_add:
            self.default_params_add = self.deepcopy(self.default_params)
        if not self.default_params_edit:
            self.default_params_edit = self.deepcopy(self.default_params)
        if self.unique_with_case is None:
            self.unique_with_case = ()

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
            self.with_captcha = ((self.all_fields and 'captcha' in self.all_fields)
                                 or (self.all_fields_add and 'captcha' in self.all_fields_add)
                                 or (self.all_fields_edit and 'captcha' in self.all_fields_edit))

        self._prepare_filter_params()
        self._prepare_date_fields()
        self._prepare_digital_fields()
        self._prepare_email_fields()
        self._prepare_multiselect_fields()
        self._prepare_null()
        self._prepare_one_of_fields()
        self.unique_fields_add = [el for el in viewkeys(self.all_unique) if
                                  any([field in self.all_fields_add for field in el])]
        self.unique_fields_edit = [el for el in viewkeys(self.all_unique) if
                                   any([field in self.all_fields_edit for field in el])]

        self._prepare_file_fields_params()

        if not isinstance(self.min_fields_length, dict):
            warnings.warn('min_fields_length should be dict', FutureWarning)
            self.min_fields_length = dict(self.min_fields_length)
        if not isinstance(self.max_fields_length, dict):
            warnings.warn('max_fields_length should be dict', FutureWarning)
            self.max_fields_length = dict(self.max_fields_length)
        if self.fields_helptext_add is None:
            self.fields_helptext_add = self.deepcopy(self.fields_helptext or {})
        if self.fields_helptext_edit is None:
            self.fields_helptext_edit = self.deepcopy(self.fields_helptext or {})

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
        b = list(default_params.keys())
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
            model_name, index, field_name = field.split('-')
            qs = getattr(obj, model_name).all().order_by('pk')
            if qs.count() > int(index):
                return getattr(qs[int(index)], field_name)
        else:
            return getattr(obj, field)

    def _get_required_from_related(self, fields_list):
        return [choice(l) for l in fields_list]

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
            self.date_fields = [k for k in viewkeys(self.default_params_add) if 'FORMS' not in k and 'date' in k]
            self.date_fields.extend([k for k in self.all_fields_add if 'FORMS' not in k and 'date' in k])
            self.date_fields.extend([k for k in viewkeys(self.default_params_edit) if 'FORMS' not in k and 'date' in k])
            self.date_fields.extend([k for k in self.all_fields_edit if 'FORMS' not in k and 'date' in k])
            self.date_fields = set(self.date_fields)

    def _prepare_digital_fields(self):
        if self.digital_fields_add is None:
            if self.digital_fields is not None:
                self.digital_fields_add = set(copy(self.digital_fields)).intersection(viewkeys(self.default_params_add))
            else:
                self.digital_fields_add = (set([k for k, v in viewitems(self.default_params_add) if
                                                'FORMS' not in k and isinstance(v, (float, int))
                                                and not isinstance(v, bool)])
                                           .difference(self.choice_fields_add)
                                           .difference(self.choice_fields_add_with_value_in_error))
        if self.digital_fields_edit is None:
            if self.digital_fields is not None:
                self.digital_fields_edit = set(copy(self.digital_fields)).intersection(
                    viewkeys(self.default_params_edit))
            else:
                self.digital_fields_edit = (set([k for k, v in viewitems(self.default_params_edit) if
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
                self.email_fields_add = set(copy(self.email_fields)).intersection(viewkeys(self.default_params_add))
            else:
                self.email_fields_add = (set([k for k in viewkeys(self.default_params_add) if
                                              'FORMS' not in k and 'email' in k]))
        if self.email_fields_edit is None:
            if self.email_fields is not None:
                self.email_fields_edit = set(copy(self.email_fields)).intersection(viewkeys(self.default_params_edit))
            else:
                self.email_fields_edit = (set([k for k in viewkeys(self.default_params_edit) if
                                               'FORMS' not in k and 'email' in k]))

    def _prepare_multiselect_fields(self):
        if self.multiselect_fields_add is None:
            if self.multiselect_fields is not None:
                self.multiselect_fields_add = set(copy(self.multiselect_fields)).intersection(
                    viewkeys(self.default_params_add))
            else:
                self.multiselect_fields_add = (set([k for k, v in viewitems(self.default_params_add) if
                                                    'FORMS' not in k and isinstance(v, (list, tuple))]))
        if self.multiselect_fields_edit is None:
            if self.multiselect_fields is not None:
                self.multiselect_fields_edit = set(copy(self.multiselect_fields)).intersection(
                    viewkeys(self.default_params_edit))
            else:
                self.multiselect_fields_edit = (set([k for k, v in viewitems(self.default_params_edit) if
                                                     'FORMS' not in k and isinstance(v, (list, tuple))]))

    def _prepare_null(self):
        if self.check_null:
            if self.check_null_str_positive is None:
                if self.check_null_str_negative is not None:
                    self.check_null_str_positive = not(self.check_null_str_negative)
                else:
                    self.check_null_str_positive = False
            if self.check_null_str_negative is None:
                if self.check_null_str_positive is not None:
                    self.check_null_str_negative = not(self.check_null_str_positive)
                else:
                    self.check_null_str_negative = True

            if self.check_null_file_positive is None:
                if self.check_null_file_negative is not None:
                    self.check_null_file_positive = not(self.check_null_file_negative)
                else:
                    self.check_null_file_positive = False
            if self.check_null_file_negative is None:
                if self.check_null_file_positive is not None:
                    self.check_null_file_negative = not(self.check_null_file_positive)
                else:
                    self.check_null_file_negative = True

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
        if self.filter_params is None or isinstance(self.filter_params, dict):
            return
        _filter_params = {}
        for param in self.filter_params:
            if isinstance(param, (list, tuple)):
                _filter_params[param[0]] = param[1]
            else:
                _filter_params[param] = None
        self.filter_params = self.deepcopy(_filter_params)

    def _prepare_file_fields_params(self):
        if self.file_fields_params is None:
            self.file_fields_params = {k: {} for k in getattr(self, 'FILE_FIELDS', [])}
        if self.file_fields_params_add is None:
            self.file_fields_params_add = self.deepcopy(self.file_fields_params)
            if not self.file_fields_params_add:
                self.file_fields_params_add = {k: {} for k in set(viewkeys(self.default_params_add))
                                               .intersection(('file', 'filename', 'image', 'preview')).difference(getattr(self, 'not_file', []))}
                self.file_fields_params_add.update({k: {'extensions': ('jpg', 'jpeg', 'png')} for k in
                                                    set(viewkeys(self.default_params_add))
                                                    .intersection(('image', 'preview', 'photo')).difference(getattr(self, 'not_file', []))})
        for item in viewvalues(self.file_fields_params_add):
            if item.get('extensions', ()):
                item['extensions'] = PrettyTuple(item['extensions'])
        if self.file_fields_params_edit is None:
            self.file_fields_params_edit = self.deepcopy(self.file_fields_params)
            if not self.file_fields_params_edit:
                self.file_fields_params_edit = {k: {} for k in set(viewkeys(self.default_params_edit))
                                                .intersection(('file', 'filename', 'image', 'preview')).difference(getattr(self, 'not_file', []))}
                self.file_fields_params_edit.update({k: {'extensions': ('jpg', 'jpeg', 'png')} for k in
                                                     set(viewkeys(self.default_params_edit))
                                                     .intersection(('image', 'preview', 'photo')).difference(getattr(self, 'not_file', []))})
        for item in viewvalues(self.file_fields_params_edit):
            if item.get('extensions', ()):
                item['extensions'] = PrettyTuple(item['extensions'])
        if self.file_fields_params_add or self.file_fields_params_edit:
            self.with_files = True

    def _prepare_hidden_fields(self):
        if self.hidden_fields_add is None:
            self.hidden_fields_add = copy(self.hidden_fields)
        if self.hidden_fields_edit is None:
            self.hidden_fields_edit = copy(self.hidden_fields)

    def _prepare_one_of_fields(self):
        if self.one_of_fields_add is None and self.one_of_fields is not None:
            self.one_of_fields_add = [gr for gr in self.one_of_fields if
                                      len(set(gr).intersection(self.all_fields_add)) == len(gr)]
        self._depend_one_of_fields_add = self.prepare_depend_from_one_of(
            self.one_of_fields_add) if self.one_of_fields_add else {}
        if self.one_of_fields_edit is None and self.one_of_fields is not None:
            self.one_of_fields_edit = [gr for gr in self.one_of_fields if
                                       len(set(gr).intersection(self.all_fields_edit)) == len(gr)]
        self._depend_one_of_fields_edit = self.prepare_depend_from_one_of(
            self.one_of_fields_edit) if self.one_of_fields_edit else {}

    def _prepare_required_fields(self):
        if self.required_fields_add is None:
            if self.required_fields is None:
                self.required_fields_add = viewkeys(self.default_params_add)
            else:
                self.required_fields_add = copy(self.required_fields)
        if self.required_fields_edit is None:
            if self.required_fields is None:
                self.required_fields_edit = viewkeys(self.default_params_edit)
            else:
                self.required_fields_edit = copy(self.required_fields)
        self.required_fields_add, self.required_related_fields_add = \
            self._divide_common_and_related_fields(self.required_fields_add)
        self.required_fields_edit, self.required_related_fields_edit = \
            self._divide_common_and_related_fields(self.required_fields_edit)

    def check_on_add_success(self, response, initial_obj_count, _locals):
        self.assert_no_form_errors(response)
        self.assertEqual(response.status_code, self.status_code_success_add,
                         'Status code %s != %s' % (response.status_code, self.status_code_success_add))
        self.assert_objects_count_on_add(True, initial_obj_count)

    def check_on_add_error(self, response, initial_obj_count, _locals):
        self.assert_objects_count_on_add(False, initial_obj_count)
        self.assertEqual(response.status_code, self.status_code_error,
                         'Status code %s != %s' % (response.status_code, self.status_code_error))

    def check_on_edit_success(self, response, _locals):
        self.assert_no_form_errors(response)
        self.assertEqual(response.status_code, self.status_code_success_edit,
                         'Status code %s != %s' % (response.status_code, self.status_code_success_edit))

    def check_on_edit_error(self, response, obj_for_edit, _locals):
        new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
        self.assert_objects_equal(new_object, obj_for_edit)
        self.assertEqual(response.status_code, self.status_code_error,
                         'Status code %s != %s' % (response.status_code, self.status_code_error))

    def create_copy(self, obj_for_edit, fields_for_change=None):
        if fields_for_change is None:
            fields_for_change = set([v for el in viewkeys(self.all_unique) for v in el
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
        for key in viewkeys(inline_models_dict):
            additional[key] = getattr(obj_for_edit, key).all()
        obj = copy(obj_for_edit)
        obj.pk = None
        obj.id = None

        for field in [ff for ff in fields_for_change if not re.findall(r'[\w_]+\-\d+\-[\w_]+', ff)]:
            if field not in self.all_fields_edit:
                """only if user can change this field"""
                continue
            field_class = self.get_field_by_name(obj, field)
            value = self._get_field_value_by_name(obj_for_edit, field)
            n = 0
            if value:
                while n < 3 and value == self._get_field_value_by_name(obj_for_edit, field):
                    n += 1
                    value = self.get_value_for_field(None, field)
                    mro_names = [b.__name__ for b in field_class.__class__.__mro__]
                    if 'DateField' in mro_names:
                        try:
                            value = datetime.strptime(value, '%d.%m.%Y').date()
                        except Exception:
                            pass
                    if 'ForeignKey' in mro_names:
                        value = field_class.related_model._base_manager.get(pk=value)
                obj.__setattr__(field, value)
        obj.save()
        for set_name, values in viewitems(additional):
            for value in values:
                params = {}
                for f_name in self.get_object_fields(value):
                    f = self.get_field_by_name(value, f_name)
                    mro_names = set([m.__name__ for m in f.__class__.__mro__])
                    if 'AutoField' in mro_names:
                        continue
                    if mro_names.intersection(['ForeignKey', ]) and f.related_model == obj.__class__:
                        params[f_name] = obj
                    elif f_name in inline_models_dict[set_name]:
                        if getattr(self, 'choice_fields_values', {}).get(set_name + '-0-' + f_name, ''):
                            params[f_name] = f.related_model._base_manager.get(
                                pk=choice(self.choice_fields_values[set_name + '-0-' + f_name]))
                        else:
                            params[f_name] = choice(f.related_model._base_manager.all()) if mro_names.intersection(['ForeignKey', ]) \
                                else self.get_value_for_field(None, f_name)
                    else:
                        params[f_name] = getattr(value, f_name)
                getattr(obj, set_name).add(value.__class__(**params))
        obj.save()
        return obj

    def fill_all_block_fields(self, block_name, max_count, params, all_fields_list):
        simple_names = set([re.findall('^{}\-\d+\-(.+$)'.format(block_name), field)[0]
                            for field in all_fields_list if re.search('^{}\-\d+\-'.format(block_name), field)])
        full_fields_list = ['%s-%d-%s' % (block_name, i, field) for i in xrange(max_count) for field in simple_names]
        self.fill_all_fields(full_fields_list, params)
        params[block_name + '-TOTAL_FORMS'] = max_count

    def fill_all_fields(self, fields, params):
        fields = set(fields)
        for field in [f for f in fields if not f.endswith('-DELETE')]:
            existing_value = params.get(field, None)
            if existing_value in (None, '', [], ()):
                if self.is_date_field(field):
                    l = [re.findall('%s_\d' % field, k) for k in viewkeys(params)]
                    subfields = [item for sublist in l for item in sublist]
                    if subfields:
                        for subfield in subfields:
                            existing_value = params.get(subfield, None)
                            if existing_value in (None, '', [], ()):
                                params[field] = self.get_value_for_field(None, field)
                    else:
                        if self.get_field_by_name(self.obj, field).__class__.__name__ == 'DateTimeField':
                            params[field + '_0'] = self.get_value_for_field(None, field + '_0')
                            params[field + '_1'] = self.get_value_for_field(None, field + '_1')
                        params[field] = self.get_value_for_field(None, field)
                else:
                    params[field] = self.get_value_for_field(None, field)

    def get_digital_values_range(self, field):
        """use name with -0-"""
        field = re.sub('\-\d+\-', '-0-', field)
        class_name = self.get_field_by_name(self.obj, field).__class__.__name__
        max_value_from_params = getattr(self, 'max_fields_length', {}).get(field, None)
        max_values = [max_value_from_params] if max_value_from_params is not None else []
        min_value_from_params = getattr(self, 'min_fields_length', {}).get(field, None)
        min_values = [min_value_from_params] if min_value_from_params is not None else []
        if 'SmallInteger' in class_name:
            max_values.append(32767)
            if 'Positive' in class_name:
                min_values.append(0)
            else:
                min_values.append(-32767 - 1)
        elif 'Integer' in class_name:
            max_values.extend([2147483647, sys.maxsize])
            if 'Positive' in class_name:
                min_values.append(0)
            else:
                min_values.extend([-2147483647 - 1, -sys.maxsize - 1])
        elif 'Float' in class_name or 'Decimal' in class_name:
            max_values.append(sys.float_info.max)
            min_values.append(-sys.float_info.max)
        return {'max_values': set(max_values), 'min_values': set(min_values)}

    def get_existing_obj(self):
        if '_get_obj_for_edit' in dir(self):
            return self._get_obj_for_edit()
        return choice(self.get_obj_manager.all())

    def get_existing_obj_with_filled(self, param_names):
        obj = self.get_existing_obj()
        if all([self._get_field_value_by_name(obj, field) for field in param_names]):
            return obj
        filters = Q()
        obj_related_objects = self.get_related_names(self.obj)
        for field in param_names:
            if not re.findall(r'[\w_]+\-\d+\-[\w_]+', field):
                filters &= ~Q(**{'%s__isnull' % field: True})
                field_class = self.get_field_by_name(self.obj, field)
                if field_class.empty_strings_allowed:
                    filters &= ~Q(**{field: ''})
            else:
                related_name = obj_related_objects.get(field.split('-')[0], field.split('-')[0])
                filters &= ~Q(**{'%s__%s__isnull' % (related_name, field.split('-')[-1]): True})
                field_class = self.get_field_by_name(self.obj, field)
                if field_class.empty_strings_allowed:
                    filters &= ~Q(**{'%s__%s' % (related_name, field.split('-')[-1]): ''})
        qs = self.get_obj_manager.filter(filters)
        if qs.exists():
            obj = choice(qs)
        return obj

    def get_gt_max(self, field, value):
        if ('Integer' in self.get_field_by_name(self.obj, field).__class__.__name__) or \
                (isinstance(value, int) and value < 1.0e+10):
            return value + 1
        elif value < 1.0e+10:
            digits_count = len(force_text(value).split('.')[1])
            return value + round(0.1 ** digits_count, digits_count)
        else:
            value = value * 10
            if value == float('inf'):
                return None
            return value

    def get_gt_max_list(self, field, values_list):
        return [value for value in [self.get_gt_max(field, v) for v in values_list] if value is not None]

    def get_lt_min(self, field, value):
        if ('Integer' in self.get_field_by_name(self.obj, field).__class__.__name__) or \
                (isinstance(value, int) and value > -1.0e+10):
            return value - 1
        elif value > -1.0e+10:
            digits_count = len(force_text(value).split('.')[1])
            return value - round(0.1 ** digits_count, digits_count)
        else:
            value = value * 10
            if value == float('-inf'):
                return None
            return value

    def get_lt_min_list(self, field, values_list):
        return [value for value in [self.get_lt_min(field, v) for v in values_list] if value is not None]

    def humanize_file_size(self, size):
        return filesizeformat(size)

    def check_and_create_objects_for_filter(self, filter_name):
        if filter_name.endswith('exact'):
            filter_name = filter_name.replace('__exact', '')
        else:
            return
        next_obj = self.obj
        existing_values = None
        for i, name in enumerate(filter_name.split('__')):
            field = self.get_field_by_name(next_obj, name)
            field_class_name = field.__class__.__name__
            if field_class_name == 'ForeignKey':
                next_obj = field.related_model
            elif field_class_name == 'RelatedObject':
                next_obj = getattr(field, 'related_model', field.model)
            else:
                existing_values = set((self.get_obj_manager if next_obj ==
                                       self.obj else next_obj._base_manager).all().values_list(name, flat=True))
                break
        if existing_values is None:
            existing_values = (self.get_obj_manager if next_obj == self.obj else next_obj._base_manager).all()
        if len(existing_values) > 1:
            return
        else:
            self.generate_random_obj(next_obj)

    def prepare_depend_from_one_of(self, one_of):
        res = {}
        for gr in one_of:
            for f in gr:
                values = res.get(f, [])
                values.extend(set(gr).difference((f,)))
                res[f] = list(set(values))
        return self.deepcopy(res)

    def send_list_action_request(self, params):
        return self.client.post(self.get_url(self.url_list), params,
                                follow=True, **self.additional_params)

    @only_with_obj
    @only_with(('url_list', 'filter_params'))
    def test_view_list_with_filter_positive(self):
        """
        View list with filter positive
        """
        for field, value in viewitems(self.filter_params):
            value = value if value else ''
            try:
                response = self.client.get(self.get_url(self.url_list), {field: value},
                                           follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 200)
            except Exception:
                self.errors_append(text='For filter %s=%s' % (field, value))

    @only_with_obj
    @only_with(('url_list', 'filter_params'))
    def test_view_list_with_filter_negative(self):
        """
        View list with filter negative
        """
        for field in viewkeys(self.filter_params):
            self.check_and_create_objects_for_filter(field)
            for value in ('qwe', '1', '0', 'йцу'):
                try:
                    response = self.client.get(self.get_url(self.url_list), {field: value}, follow=True,
                                               **self.additional_params)
                    self.assertEqual(response.status_code, 200)
                except Exception:
                    self.errors_append(text='For filter %s=%s' % (field, value))


class FormAddTestMixIn(FormTestMixIn):

    def clean_depend_fields_add(self, params, field):
        for field_for_clean in self._depend_one_of_fields_add.get(field, ()):
            self.set_empty_value_for_field(params, field_for_clean)

    def prepare_for_add(self):
        pass

    def send_add_request(self, params):
        return self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)

    @only_with_obj
    def test_add_page_fields_list_positive(self):
        """
        check that all and only need fields is visible at add page
        """
        self.prepare_for_add()
        response = self.client.get(self.get_url(self.url_add), follow=True, **self.additional_params)
        form_fields = self.get_fields_list_from_response(response)
        try:
            """not set because of one field can be on form many times"""
            self.assert_form_equal(form_fields['visible_fields'],
                                   [el for el in self.all_fields_add if el not in (self.hidden_fields_add or ())])
        except Exception:
            self.errors_append(text='For visible fields')
        if self.disabled_fields_add is not None:
            try:
                self.assert_form_equal(form_fields['disabled_fields'], self.disabled_fields_add)
            except Exception:
                self.errors_append(text='For disabled fields')
        if self.hidden_fields_add is not None:
            try:
                self.assert_form_equal(form_fields['hidden_fields'], self.hidden_fields_add)
            except Exception:
                self.errors_append(text='For hidden fields')

        fields_helptext = getattr(self, 'fields_helptext_add', {})
        for field_name, text in viewitems(fields_helptext):
            if field_name not in self.all_fields_add:
                continue
            try:
                field = get_field_from_response(response, field_name)
                self.assertEqual(field.help_text, text)
            except Exception:
                self.errors_append(text='Helptext for field %s' % field_name)

    @only_with_obj
    def test_add_object_all_fields_filled_positive(self):
        """
        Create object: fill all fields
        """
        self.prepare_for_add()
        params = self.deepcopy(self.default_params_add)
        prepared_depends_fields = self.prepare_depend_from_one_of(
            self.one_of_fields_add) if self.one_of_fields_add else {}
        only_independent_fields = set(self.all_fields_add).difference(viewkeys(prepared_depends_fields))
        for field in viewkeys(prepared_depends_fields):
            self.set_empty_value_for_field(params, field)
        self.fill_all_fields(list(only_independent_fields) + self.required_fields_add +
                             self._get_required_from_related(self.required_related_fields_add), params)
        self.update_params(params)
        self.update_captcha_params(self.get_url(self.url_add), params)
        initial_obj_count = self.get_obj_manager.count()
        old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
        try:
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = getattr(self, 'exclude_from_check_add', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()

    @only_with_obj
    @only_with(('one_of_fields_add',))
    def test_add_object_with_group_all_fields_filled_positive(self):
        """
        Create object: fill all fields
        """
        prepared_depends_fields = self.prepare_depend_from_one_of(self.one_of_fields_add)
        only_independent_fields = set(self.all_fields_add).difference(viewkeys(prepared_depends_fields))
        default_params = self.deepcopy(self.default_params_add)
        for field in viewkeys(prepared_depends_fields):
            self.set_empty_value_for_field(default_params, field)
        self.fill_all_fields(list(only_independent_fields), default_params)
        fields_from_groups = set(viewkeys(prepared_depends_fields))
        for group in self.one_of_fields_add:
            field = choice(group)
            fields_from_groups = fields_from_groups.difference(prepared_depends_fields[field])
        self.fill_all_fields(fields_from_groups, default_params)
        for group in self.one_of_fields_add:
            for field in group:
                self.prepare_for_add()
                params = self.deepcopy(default_params)
                mail.outbox = []
                for f in prepared_depends_fields[field]:
                    self.set_empty_value_for_field(params, f)
                self.fill_all_fields((field,), params)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_success(response, initial_obj_count, locals())
                    new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                    exclude = getattr(self, 'exclude_from_check_add', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.errors_append(text='For filled %s from group %s' % (field, repr(group)))

    @only_with_obj
    def test_add_object_only_required_fields_positive(self):
        """
        Create object: fill only required fields
        """
        self.prepare_for_add()
        params = self.deepcopy(self.default_params_add)
        required_fields = self.required_fields_add + \
            self._get_required_from_related(self.required_related_fields_add)
        self.update_params(params)
        for field in set(viewkeys(params)).difference(required_fields):
            self.set_empty_value_for_field(params, field)
        for field in required_fields:
            self.fill_all_fields(required_fields, params)
        self.update_captcha_params(self.get_url(self.url_add), params)
        initial_obj_count = self.get_obj_manager.count()
        old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
        try:
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = getattr(self, 'exclude_from_check_add', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()

        """если хотя бы одно поле из группы заполнено, объект создается"""
        for group in self.required_related_fields_add:
            for field in group:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                for field in group:
                    self.set_empty_value_for_field(params, field)
                """if unique fields"""
                mail.outbox = []
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.fill_all_fields((field,), params)
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_success(response, initial_obj_count, locals())
                    new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                    exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.errors_append(text='For filled field %s from group "%s"' %
                                       (field, force_text(group)))

    @only_with_obj
    def test_add_object_without_not_required_fields_positive(self):
        """
        Create object: send only required fields
        """
        self.prepare_for_add()
        params = self.deepcopy(self.default_params_add)
        required_fields = self.required_fields_add + \
            self._get_required_from_related(self.required_related_fields_add)
        self.update_params(params)
        for field in set(viewkeys(params)).difference(required_fields):
            self.pop_field_from_params(params, field)
        for field in required_fields:
            self.fill_all_fields(required_fields, params)
        self.update_captcha_params(self.get_url(self.url_add), params)
        initial_obj_count = self.get_obj_manager.count()
        old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
        try:
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = getattr(self, 'exclude_from_check_add', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()

        """если хотя бы одно поле из группы заполнено, объект создается"""
        for group in self.required_related_fields_add:
            for field in group:
                """if unique fields"""
                mail.outbox = []
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                for field in group:
                    self.pop_field_from_params(params, field)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.fill_all_fields((field,), params)
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_success(response, initial_obj_count, locals())
                    new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                    exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.errors_append(text='For filled field %s from group "%s"' %
                                       (field, force_text(group)))

    @only_with_obj
    def test_add_object_empty_required_fields_negative(self):
        """
        Try create object: empty required fields
        """
        message_type = 'empty_required'
        """обязательные поля должны быть заполнены"""
        for field in [f for f in self.required_fields_add if 'FORMS' not in f]:
            sp = transaction.savepoint()
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.set_empty_value_for_field(params, field)
                initial_obj_count = self.get_obj_manager.count()
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty field "%s"' % field)

        """обязательно хотя бы одно поле из группы (все пустые)"""
        for group in self.required_related_fields_add:
            sp = transaction.savepoint()
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            for field in group:
                self.set_empty_value_for_field(params, field)
            self.update_captcha_params(self.get_url(self.url_add), params)
            initial_obj_count = self.get_obj_manager.count()
            try:
                response = self.send_add_request(params)
                error_message = self.get_error_message(message_type, group,
                                                       error_field=self.non_field_error_key,
                                                       locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_add_error(response, initial_obj_count, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty group "%s"' % force_text(group))

    @only_with_obj
    def test_add_object_without_required_fields_negative(self):
        """
        Try create object: required fields are not exists in params
        """
        message_type = 'without_required'
        """обязательные поля должны быть заполнены"""
        for field in [f for f in self.required_fields_add if 'FORMS' not in f]:
            sp = transaction.savepoint()
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.pop_field_from_params(params, field)
                initial_obj_count = self.get_obj_manager.count()
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For params without field "%s"' % field)

        """обязательно хотя бы одно поле из группы (все пустые)"""
        for group in self.required_related_fields_add:
            sp = transaction.savepoint()
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            for field in group:
                self.pop_field_from_params(params, field)
            self.update_captcha_params(self.get_url(self.url_add), params)
            initial_obj_count = self.get_obj_manager.count()
            try:
                response = self.send_add_request(params)
                error_message = self.get_error_message(
                    message_type, group, error_field=self.non_field_error_key, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_add_error(response, initial_obj_count, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For params without group "%s"' % force_text(group))

    @only_with_obj
    def test_add_object_max_length_values_positive(self):
        """
        Create object: fill all fields with maximum length values
        """
        other_fields = []
        for field_type_name in ('digital_fields_add', 'date_fields', 'datetime_fields', 'choice_fields_add',
                                'choice_fields_add_with_value_in_error', 'disabled_fields_add', 'hidden_fields_add',
                                'int_fields_add', 'multiselect_fields_add', 'not_str_fields'):
            other_fields.extend(getattr(self, field_type_name, []) or [])

        fields_for_check = [(k, self.max_fields_length.get(re.sub('\-\d+\-', '-0-', k), 100000))
                            for k in self.all_fields_add if re.sub('\-\d+\-', '-0-', k) not in other_fields]
        if not fields_for_check:
            self.skipTest('No any string fields')
        max_length_params = {}
        prepared_depends_fields = self.prepare_depend_from_one_of(
            self.one_of_fields_add) if self.one_of_fields_add else {}
        fields_for_clean = []
        for field, length in fields_for_check:
            max_length_params[field] = self.get_value_for_field(length, field)
            if field in viewkeys(prepared_depends_fields):
                fields_for_clean.extend(prepared_depends_fields[field])

        sp = transaction.savepoint()
        try:
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            params.update(max_length_params)
            for depended_field in fields_for_clean:
                self.set_empty_value_for_field(params, depended_field)
            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = set(getattr(self, 'exclude_from_check_add', [])).difference(list(max_length_params.keys()))
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text="For max values in all fields\n%s" %
                                    '\n\n'.join(['  %s with length %d\n(value %s)' %
                                                 (field, length, max_length_params[field] if len(str(max_length_params[field])) <= 1000
                                                  else str(max_length_params[field])[:1000] + '...')
                                                 for field, length in fields_for_check]))

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors and not set([el[0] for el in fields_for_check]).intersection(viewkeys(prepared_depends_fields)):
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field, length in fields_for_check:
            sp = transaction.savepoint()
            """if unique fields"""
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                for depended_field in prepared_depends_fields.get(field, []):
                    self.set_empty_value_for_field(params, depended_field)
                params[field] = max_length_params[field]
                if self.is_file_field(field):
                    if self.is_file_list(field):
                        for f in params[field]:
                            f.seek(0)
                    else:
                        params[field].seek(0)
                value = self.get_value_for_error_message(field, params[field])
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, length, value if len(str(value)) <= 1000 else str(value)[:1000] + '...'))

    @only_with_obj
    @only_with('max_fields_length')
    def test_add_object_values_length_gt_max_negative(self):
        """
        Create object: values length > maximum
        """
        message_type = 'max_length'
        other_fields = list(getattr(self, 'digital_fields_add', [])) + list(getattr(self, 'date_fields', []))
        for field, length in [(k, v) for k, v in viewitems(self.max_fields_length) if k in
                              self.all_fields_add and k not in other_fields]:
            sp = transaction.savepoint()
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            self.clean_depend_fields_add(params, field)
            current_length = length + 1
            params[field] = self.get_value_for_field(current_length, field)
            initial_obj_count = self.get_obj_manager.count()
            try:
                response = self.send_add_request(params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_add_error(response, initial_obj_count, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, current_length, params[field] if len(str(params[field])) <= 1000
                                    else str(params[field])[:1000] + '...'))

    @only_with_obj
    @only_with('min_fields_length')
    def test_add_object_values_length_lt_min_negative(self):
        """
        Create object: values length < minimum
        """
        message_type = 'min_length'
        other_fields = list(getattr(self, 'digital_fields_add', [])) + list(getattr(self, 'date_fields', []))
        for field, length in [(k, v) for k, v in viewitems(self.min_fields_length) if k in
                              self.all_fields_add and k not in other_fields]:
            sp = transaction.savepoint()
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            self.clean_depend_fields_add(params, field)
            current_length = length - 1
            params[field] = self.get_value_for_field(current_length, field)
            initial_obj_count = self.get_obj_manager.count()
            try:
                response = self.send_add_request(params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_add_error(response, initial_obj_count, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, current_length, params[field]))

    @only_with_obj
    def test_add_object_with_wrong_choices_negative(self):
        """
        Try create object with choices, that not exists
        """
        message_type = 'wrong_value'
        for field in set(tuple(self.choice_fields_add) + tuple(self.choice_fields_add_with_value_in_error)):
            for value in ('qwe', '12345678', 'йцу'):
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                params[field] = value
                initial_obj_count = self.get_obj_manager.count()
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    _locals = {'field': field, }
                    if field in self.choice_fields_add_with_value_in_error:
                        _locals['value'] = value
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=_locals))
                except Exception:
                    self.errors_append(text='For %s value "%s"' % (field, value))

    @only_with_obj
    @only_with(('multiselect_fields_add',))
    def test_add_object_with_wrong_multiselect_choices_negative(self):
        """
        Try create object with choices in multiselect, that not exists
        """
        message_type = 'wrong_value'
        for field in self.multiselect_fields_add:
            for value in ('12345678',):
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                params[field] = [value, ]
                initial_obj_count = self.get_obj_manager.count()
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    _locals = {'field': field, 'value': value}
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=_locals))
                except Exception:
                    self.errors_append(text='For %s value "%s"' % (field, value))

    @only_with_obj
    @only_with(('unique_fields_add',))
    def test_add_object_unique_already_exists_negative(self):
        """
        Try add object with unique field values, that already used in other objects
        """
        message_type = 'unique'
        """values exactly equals"""
        for el in self.unique_fields_add:
            self.prepare_for_add()
            field = self.all_unique[el]
            existing_obj = self.get_existing_obj_with_filled(el)
            sp = transaction.savepoint()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            for el_field in el:
                if el_field not in self.all_fields_add:
                    continue
                self.clean_depend_fields_add(params, el_field)
                value = self._get_field_value_by_name(existing_obj, el_field)
                params[el_field] = self.get_params_according_to_type(value, '')[0]
            initial_obj_count = self.get_obj_manager.count()
            try:
                response = self.send_add_request(params)
                error_message = self.get_error_message(message_type,
                                                       field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field,
                                                       locals=locals())

                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_add_error(response, initial_obj_count, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' %
                                                             (field, params[field]) for field
                                                             in el if field in viewkeys(params)))

        """values is in other case"""
        for el in self.unique_fields_add:
            self.prepare_for_add()
            field = self.all_unique[el]
            existing_obj = self.get_existing_obj_with_filled(el)
            params = self.deepcopy(self.default_params_add)
            if not any([isinstance(params[el_field], basestring) and el_field not in self.unique_with_case for el_field in el]):
                continue
            sp = transaction.savepoint()
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            for el_field in el:
                if el_field not in self.all_fields_add:
                    continue
                self.clean_depend_fields_add(params, el_field)
                value = self._get_field_value_by_name(existing_obj, el_field)
                params[el_field] = self.get_params_according_to_type(value, '')[0]
                if isinstance(params[el_field], basestring):
                    params[el_field] = params[el_field].swapcase()
            initial_obj_count = self.get_obj_manager.count()
            try:
                response = self.send_add_request(params)
                error_message = self.get_error_message(message_type,
                                                       field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field,
                                                       locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_add_error(response, initial_obj_count, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' %
                                                             (field, params[field]) for field
                                                             in el if field in viewkeys(params)))

    @only_with_obj
    @only_with(('unique_fields_add', 'unique_with_case',))
    def test_add_object_unique_alredy_exists_in_other_case_positive(self):
        """
        Add object with unique field values, to values, that already used in other objects but in other case
        """
        for el in self.unique_fields_edit:
            if not set(self.unique_with_case).intersection(el):
                continue
            for existing_command, new_command in (('lower', 'upper'),
                                                  ('upper', 'lower')):
                sp = transaction.savepoint()
                """if unique fields"""
                mail.outbox = []
                self.prepare_for_add()
                existing_obj = self.get_existing_obj_with_filled(el)
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                for el_field in el:
                    if el_field not in self.all_fields_add:
                        """only if user can fill this field"""
                        continue
                    self.clean_depend_fields_add(params, el_field)
                    value = self._get_field_value_by_name(existing_obj, el_field)
                    params[el_field] = self.get_params_according_to_type(value, '')[0]
                    if el_field in self.unique_with_case:
                        self.get_obj_manager.filter(pk=existing_obj.pk).update(
                            **{el_field: getattr(value, existing_command)()})
                        params[el_field] = getattr(params[el_field], new_command)()
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_success(response, initial_obj_count, locals())
                    new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                    exclude = getattr(self, 'exclude_from_check_add', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For existing values:\n%s\nnew params:\n%s' %
                                       (', '.join('field "%s" with value "%s"\n' %
                                                  (field,
                                                   self._get_field_value_by_name(existing_obj, el_field))
                                                  for field in el),
                                        ', '.join('field "%s" with value "%s"\n' % (field, params[field])
                                                  for field in el if field in viewkeys(params))))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_wrong_values_in_digital_negative(self):
        """
        Try add obj with wrong values in digital fields
        """
        for field in [f for f in self.digital_fields_add]:
            message_type = 'wrong_value_int' if field in self.int_fields_add else 'wrong_value_digital'
            for value in ('q', 'й', 'NaN', 'inf', '-inf'):
                sp = transaction.savepoint()
                try:
                    self.prepare_for_add()
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url(self.url_add), params)
                    self.clean_depend_fields_add(params, field)
                    params[field] = value
                    initial_obj_count = self.get_obj_manager.count()
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('email_fields_add',))
    def test_add_object_wrong_values_in_email_negative(self):
        """
        Try add obj with wrong values in email fields
        """
        message_type = 'wrong_value_email'
        for field in [f for f in self.email_fields_add]:
            for value in ('q', 'й', 'qwe@rty', 'qw@йц', '@qwe', 'qwe@'):
                sp = transaction.savepoint()
                try:
                    self.prepare_for_add()
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url(self.url_add), params)
                    self.clean_depend_fields_add(params, field)
                    params[field] = value
                    initial_obj_count = self.get_obj_manager.count()
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_value_max_in_digital_positive(self):
        """
        Add obj with value in digital fields == max
        """
        fields_for_check = []

        max_value_params = {}
        for field in self.digital_fields_add:
            max_values = self.get_digital_values_range(field)['max_values']
            if not max_values:
                continue
            fields_for_check.append(field)
            max_value_params[field] = min(max_values)

        sp = transaction.savepoint()
        try:
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            params.update(max_value_params)
            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = set(getattr(self, 'exclude_from_check_add', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text="For max values in all digital fields\n%s" %
                                    '\n\n'.join(['  %s with value %s' %
                                                 (field, max_value_params[field])
                                                 for field in fields_for_check]))

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field in fields_for_check:
            value = max_value_params[field]
            """if unique fields"""
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                params[field] = value
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with value "%s"' % (field, value))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_value_gt_max_in_digital_negative(self):
        """
        Try add obj with value in digital fields > max
        """
        message_type = 'max_length_digital'
        for field in [f for f in self.digital_fields_add]:
            max_value = min(self.get_digital_values_range(field)['max_values'])
            for value in self.get_gt_max_list(field, self.get_digital_values_range(field)['max_values']):
                sp = transaction.savepoint()
                try:
                    self.prepare_for_add()
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url(self.url_add), params)
                    self.clean_depend_fields_add(params, field)
                    params[field] = value
                    initial_obj_count = self.get_obj_manager.count()
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_value_min_in_digital_positive(self):
        """
        Add obj with value in digital fields == min
        """
        fields_for_check = []

        min_value_params = {}
        for field in self.digital_fields_add:
            min_values = self.get_digital_values_range(field)['min_values']
            if not min_values:
                continue
            fields_for_check.append(field)
            min_value_params[field] = max(min_values)

        sp = transaction.savepoint()
        try:
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            params.update(min_value_params)
            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = set(getattr(self, 'exclude_from_check_add', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text="For min values in all digital fields\n%s" %
                                    '\n\n'.join(['  %s with value %s' %
                                                 (field, min_value_params[field])
                                                 for field in fields_for_check]))

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field in fields_for_check:
            value = min_value_params[field]
            sp = transaction.savepoint()
            """if unique fields"""
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                params[field] = value
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with value "%s"' % (field, value))

    @only_with_obj
    @only_with(('digital_fields_add',))
    def test_add_object_value_lt_min_in_digital_negative(self):
        """
        Try add obj with value in digital fields < min
        """
        message_type = 'min_length_digital'
        for field in [f for f in self.digital_fields_add]:
            min_value = max(self.get_digital_values_range(field)['min_values'])
            for value in self.get_lt_min_list(field, self.get_digital_values_range(field)['min_values']):
                sp = transaction.savepoint()
                try:
                    self.prepare_for_add()
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url(self.url_add), params)
                    self.clean_depend_fields_add(params, field)
                    params[field] = value
                    initial_obj_count = self.get_obj_manager.count()
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('disabled_fields_add',))
    def test_add_object_disabled_fields_values_negative(self):
        """
        Try add obj with filled disabled fields
        """
        for field in self.disabled_fields_add:
            sp = transaction.savepoint()
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                params[field] = params.get(field, None) or self.get_value_for_field(None, field)
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                self.assertNotEqual(self.get_value_for_compare(new_object, field), params[field])
                params[field] = ''
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s"' % field)

    @only_with_obj
    @only_with(('one_of_fields_add',))
    def test_add_object_one_of_fields_all_filled_negative(self):
        """
        Try add object with all filled fields, that should be filled singly
        """
        message_type = 'one_of'
        for group in self.one_of_fields_add:
            for filled_group in tuple(set([(el, additional_el) for i, el in enumerate(group) for additional_el in
                                           group[i + 1:]]).difference(set(self.one_of_fields_add).difference(group))) + \
                    (group,):
                sp = transaction.savepoint()
                try:
                    self.prepare_for_add()
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url(self.url_add), params)
                    self.fill_all_fields(filled_group, params)
                    initial_obj_count = self.get_obj_manager.count()
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    error_message = self.get_error_message(message_type, group,
                                                           locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For filled %s fields from group %s' %
                                       (force_text(filled_group), force_text(group)))

    @only_with_obj
    @only_with('max_blocks')
    def test_add_object_max_inline_blocks_count_positive(self):
        """
        Test max number of lines in inline block
        """
        self.prepare_for_add()
        params = self.deepcopy(self.default_params_add)
        self.update_params(params)
        self.update_captcha_params(self.get_url(self.url_add), params)
        for name, max_count in viewitems(self.max_blocks):
            self.fill_all_block_fields(name, max_count, params,
                                       set(tuple(self.all_fields_add) + tuple(self.hidden_fields_add or ())))
        sp = transaction.savepoint()
        initial_obj_count = self.get_obj_manager.count()
        old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
        try:
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = getattr(self, 'exclude_from_check_add', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text="Max count in all (%s) blocks" % ', '.join('%s in %s' % (k, v) for k, v in
                                                                               viewitems(self.max_blocks)))
        finally:
            mail.outbox = []

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(self.max_blocks.keys()) == 1:
            self.formatted_assert_errors()

        for name, max_count in viewitems(self.max_blocks):
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            self.fill_all_block_fields(name, max_count, params,
                                       set(tuple(self.all_fields_add) + tuple(self.hidden_fields_add or ())))
            sp = transaction.savepoint()
            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            try:
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text="Max block count (%s) in %s" % (max_count, name))
            finally:
                mail.outbox = []

    @only_with_obj
    @only_with('max_blocks')
    def test_add_object_inline_blocks_count_gt_max_negative(self):
        """
        Test max + 1 number of lines in inline blocks
        """
        message_type = 'max_block_count'
        for name, max_count in viewitems(self.max_blocks):
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            gt_max_count = max_count + 1
            self.fill_all_block_fields(name, gt_max_count, params,
                                       set(tuple(self.all_fields_add) + tuple(self.hidden_fields_add or ())))
            sp = transaction.savepoint()
            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            try:
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                error_message = self.get_error_message(message_type, name, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text="Count great than max (%s) in block %s" % (gt_max_count, name))
            finally:
                mail.outbox = []

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_files_params('max_count')
    def test_add_object_many_files_negative(self):
        """
        Try create obj with files count > max files count
        """
        message_type = 'max_count_file'
        for field, field_dict in viewitems(self.file_fields_params_add):
            if field_dict.get('max_count', 1) <= 1:
                continue
            max_count = field_dict['max_count']
            current_count = max_count + 1
            sp = transaction.savepoint()
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                filename = '.'.join([s for s in [get_randname(10, 'wrd '),
                                                 choice(field_dict.get('extensions', ('',)))] if s])
                params[field] = self.get_random_file(field, filename=filename, count=current_count)
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (current_count, field))

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_files_params('max_count')
    def test_add_object_many_files_positive(self):
        """
        Try create obj with photos count == max files count
        """
        fields_for_check = []
        max_count_params = {}
        for field, field_dict in viewitems(self.file_fields_params_add):
            if field_dict.get('max_count', 1) <= 1:
                continue
            fields_for_check.append(field)
            max_count_params[field] = []
            max_count = field_dict['max_count']
            max_count_params[field] = self.get_random_file(field, count=max_count)

        sp = transaction.savepoint()
        try:
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            params.update(max_count_params)
            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = set(getattr(self, 'exclude_from_check_add', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text='For max count files in all fields\n%s' %
                                    '\n'.join(['%s: %d' % (field, len(params[field])) for field in fields_for_check]))

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field in fields_for_check:
            sp = transaction.savepoint()
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                params[field] = max_count_params[field]
                for f in params[field]:
                    f.seek(0)
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (len(params[field]), field))

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_files_params('one_max_size')
    def test_add_object_big_file_negative(self):
        """
        Try create obj with file size > max one file size
        """
        message_type = 'max_size_file'
        for field, field_dict in viewitems(self.file_fields_params_add):
            sp = transaction.savepoint()
            one_max_size = field_dict.get('one_max_size', None)
            if not one_max_size:
                continue
            size = convert_size_to_bytes(one_max_size)
            max_size = self.humanize_file_size(size)
            current_size = size + 100
            human_current_size = self.humanize_file_size(current_size)
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                f = self.get_random_file(field, size=current_size)
                filename = f[0].name if isinstance(f, (list, tuple)) else f.name
                params[field] = f
                initial_obj_count = self.get_obj_manager.count()
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For file size %s (%s) in field %s' % (self.humanize_file_size(current_size),
                                                                               current_size, field))
            finally:
                self.del_files()

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_files_params('sum_max_size')
    def test_add_object_big_summary_file_size_negative(self):
        """
        Try create obj with summary files size > max summary files size
        """
        message_type = 'max_sum_size_file'
        for field, field_dict in viewitems(self.file_fields_params_add):
            sp = transaction.savepoint()
            sum_max_size = field_dict.get('sum_max_size', None)
            if not sum_max_size:
                continue
            size = convert_size_to_bytes(sum_max_size)
            current_size = size + 100
            max_size = self.humanize_file_size(size)
            one_size = current_size / field_dict['max_count']
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                f = self.get_random_file(field, size=one_size, count=field_dict['max_count'])
                params[field] = f
                initial_obj_count = self.get_obj_manager.count()
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For summary size %s (%s = %s * %s) in field %s' %
                                        (self.humanize_file_size(current_size), current_size, one_size,
                                         field_dict['max_count'], field))
            finally:
                self.del_files()

    @only_with_obj
    @only_with('file_fields_params_add')
    def test_add_object_big_file_positive(self):
        """
        Create obj with file size == max one file size
        """
        fields_for_check = list(self.file_fields_params_add.keys())
        max_size_params = {}
        for field in fields_for_check:
            field_dict = self.file_fields_params_add[field]
            size = convert_size_to_bytes(field_dict.get('one_max_size', '10M'))
            if field_dict.get('sum_max_size', None):
                count = 1
            else:
                count = field_dict.get('max_count', 1)
            max_size_params[field] = self.get_random_file(field, size=size, count=count)

        sp = transaction.savepoint()
        try:
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            params.update(max_size_params)
            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = set(getattr(self, 'exclude_from_check_add', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text='For max size files in all fields\n%s' %
                                    '\n'.join(['%s: %s (%s)' %
                                               (field,
                                                convert_size_to_bytes(
                                                    self.file_fields_params_add[field].get('one_max_size', '10M')),
                                                self.humanize_file_size(
                                                    convert_size_to_bytes(
                                                        self.file_fields_params_add[field].get('one_max_size', '10M'))))
                                               for field in fields_for_check]))

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field, field_dict in viewitems(self.file_fields_params_add):
            sp = transaction.savepoint()
            mail.outbox = []
            one_max_size = field_dict.get('one_max_size', '10M')
            size = convert_size_to_bytes(one_max_size)
            max_size = self.humanize_file_size(size)
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                params[field] = max_size_params[field]
                if self.is_file_list(field):
                    for f in params[field]:
                        f.seek(0)
                else:
                    params[field].seek(0)
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For file size %s (%s) in field %s' % (max_size, size, field))
            finally:
                self.del_files()

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_files_params('sum_max_size')
    def test_add_object_big_summary_file_size_positive(self):
        """
        Create obj with summary files size == max summary files size
        """
        for field, field_dict in viewitems(self.file_fields_params_add):
            sp = transaction.savepoint()
            mail.outbox = []
            sum_max_size = field_dict.get('sum_max_size', None)
            if not sum_max_size:
                continue
            size = convert_size_to_bytes(sum_max_size)
            max_size = self.humanize_file_size(size)
            one_size = size / field_dict['max_count']
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                params[field] = self.get_random_file(field, size=one_size, count=field_dict['max_count'])
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For summary size %s (%s = %s * %s) in field %s' %
                                   (max_size, one_size * field_dict['max_count'], one_size,
                                    field_dict['max_count'], field))
            finally:
                self.del_files()

    @only_with_obj
    @only_with('file_fields_params_add')
    def test_add_object_empty_file_negative(self):
        """
        Try create obj with file size = 0M
        """
        message_type = 'empty_file'
        for field, field_dict in viewitems(self.file_fields_params_add):
            sp = transaction.savepoint()
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                f = self.get_random_file(field, size=0)
                filename = f[0].name if isinstance(f, (list, tuple)) else f.name
                params[field] = f
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty file in field %s' % field)

    @only_with_obj
    @only_with('file_fields_params_add')
    def test_add_object_some_file_extensions_positive(self):
        """
        Create obj with some available extensions
        """
        for field, field_dict in viewitems(self.file_fields_params_add):
            extensions = copy(field_dict.get('extensions', ()))
            if not extensions:
                extensions = (get_randname(3, 'wd'), '')
            extensions += tuple([e.upper() for e in extensions if e])
            for ext in extensions:
                sp = transaction.savepoint()
                mail.outbox = []
                filename = '.'.join([el for el in ['test', ext] if el])
                self.prepare_for_add()
                f = self.get_random_file(field, filename=filename)
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                params[field] = f
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_success(response, initial_obj_count, locals())
                    new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                    exclude = getattr(self, 'exclude_from_check_add', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_files_params('extensions')
    def test_add_object_wrong_file_extensions_negative(self):
        """
        Create obj with wrong extensions
        """
        message_type = 'wrong_extension'
        for field, field_dict in viewitems(self.file_fields_params_add):
            extensions = copy(field_dict.get('extensions', ()))
            if not extensions:
                continue
            ext = get_randname(3, 'wd')
            while ext.lower() in extensions:
                ext = get_randname(3, 'wd')
            wrong_extensions = tuple(field_dict.get('wrong_extensions', ())) + ('', ext)
            for ext in wrong_extensions:
                filename = '.'.join([el for el in ['test', ext] if el])
                sp = transaction.savepoint()
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                f = self.get_random_file(field, filename=filename)
                params[field] = f
                initial_obj_count = self.get_obj_manager.count()
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=locals()))
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_any_files_params(['min_width', 'min_height', 'max_width', 'max_height'])
    def test_add_object_min_image_dimensions_positive(self):
        """
        Create obj with minimum image file dimensions
        """
        for field, field_dict in viewitems(self.file_fields_params_add):
            width = field_dict.get('min_width', 1)
            height = field_dict.get('min_height', 1)
            sp = transaction.savepoint()
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                f = self.get_random_file(field, width=width, height=height)
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                params[field] = f
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_any_files_params(['min_width', 'min_height'])
    def test_add_object_image_dimensions_lt_min_negative(self):
        """
        Create obj with image file dimensions < minimum
        """
        message_type = 'min_dimensions'
        for field, field_dict in viewitems(self.file_fields_params_add):
            mail.outbox = []
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
                    self.prepare_for_add()
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url(self.url_add), params)
                    self.clean_depend_fields_add(params, field)
                    f = self.get_random_file(field, width=width, height=height)
                    filename = f[0].name if isinstance(f, (list, tuple)) else f.name
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    params[field] = f
                    initial_obj_count = self.get_obj_manager.count()
                    old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=locals()))
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_any_files_params(['max_width', 'max_height', 'min_width', 'min_height'])
    def test_add_object_max_image_dimensions_positive(self):
        """
        Create obj with maximum image file dimensions
        """
        for field, field_dict in viewitems(self.file_fields_params_add):
            width = field_dict.get('max_width', 10000)
            height = field_dict.get('max_height', 10000)
            sp = transaction.savepoint()
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
                f = self.get_random_file(field, width=width, height=height)
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                params[field] = f
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))

    @only_with_obj
    @only_with('file_fields_params_add')
    @only_with_any_files_params(['max_width', 'max_height'])
    def test_add_object_image_dimensions_gt_max_negative(self):
        """
        Create obj with image file dimensions > maximum
        """
        message_type = 'max_dimensions'
        for field, field_dict in viewitems(self.file_fields_params_add):
            mail.outbox = []
            values = ()
            max_width = field_dict.get('max_width', None)
            if max_width:
                values += ((max_width + 1, field_dict.get('max_height', field_dict.get('min_height', 1))),)
            max_height = field_dict.get('max_height', None)
            if max_height:
                values += ((field_dict.get('max_width', field_dict.get('min_width', 1)), max_height + 1),)

            for width, height in values:
                sp = transaction.savepoint()
                try:
                    self.prepare_for_add()
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url(self.url_add), params)
                    self.clean_depend_fields_add(params, field)
                    f = self.get_random_file(field, width=width, height=height)
                    filename = f[0].name if isinstance(f, (list, tuple)) else f.name
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    params[field] = f
                    initial_obj_count = self.get_obj_manager.count()
                    old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=locals()))
                    new_objects = self.get_obj_manager.exclude(pk__in=old_pks)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))

    @only_with_obj
    @only_with(('check_null', 'check_null_str_negative'))
    def test_add_object_str_with_null_negative(self):
        """
        Create object with \\x00 in str fields
        """
        message_type = 'with_null'
        other_fields = ['captcha', 'captcha_0', 'captcha_1']
        for field_type_name in ('digital_fields_add', 'date_fields', 'datetime_fields', 'choice_fields_add',
                                'choice_fields_add_with_value_in_error', 'disabled_fields_add', 'hidden_fields_add',
                                'int_fields_add', 'multiselect_fields_add', 'not_str_fields',):
            other_fields.extend(getattr(self, field_type_name, []) or [])
        other_fields.extend(list(getattr(self, 'file_fields_params_add', {}).keys()))

        fields_for_check = [k for k in self.all_fields_add if re.sub('\-\d+\-', '-0-', k) not in other_fields]
        if not fields_for_check:
            self.skipTest('No any string fields')
        test_params = {}
        for field in fields_for_check:
            test_params[field] = '\x00' + self.get_value_for_field(None, field)[1:]

        for field in fields_for_check:
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                params[field] = test_params[field]
                initial_obj_count = self.get_obj_manager.count()
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.errors_append(text='\\x00 value in field %s' % field)

    @only_with_obj
    @only_with(('check_null', 'check_null_str_positive'))
    def test_add_object_str_with_null_positive(self):
        """
        Create object with \\x00 in str fields
        """
        other_fields = ['captcha', 'captcha_0', 'captcha_1']
        for field_type_name in ('digital_fields_add', 'date_fields', 'datetime_fields', 'choice_fields_add',
                                'choice_fields_add_with_value_in_error', 'disabled_fields_add', 'hidden_fields_add',
                                'int_fields_add', 'multiselect_fields_add', 'not_str_fields',):
            other_fields.extend(getattr(self, field_type_name, []) or [])
        other_fields.extend(list(getattr(self, 'file_fields_params_add', {}).keys()))

        fields_for_check = [k for k in self.all_fields_add if re.sub('\-\d+\-', '-0-', k) not in other_fields]
        if not fields_for_check:
            self.skipTest('No any string fields')

        test_params = {}
        prepared_depends_fields = self.prepare_depend_from_one_of(
            self.one_of_fields_add) if self.one_of_fields_add else {}
        fields_for_clean = []
        for field in fields_for_check:
            test_params[field] = '\x00' + self.get_value_for_field(None, field)[1:]
            if field in viewkeys(prepared_depends_fields):
                fields_for_clean.extend(prepared_depends_fields[field])

        try:
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            params.update(test_params)
            for depended_field in fields_for_clean:
                self.set_empty_value_for_field(params, depended_field)
            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = set(getattr(self, 'exclude_from_check_add', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude, other_values={
                                      field: test_params[field].name.replace('\x00', '') for
                                      field in fields_for_check})
        except Exception:
            self.errors_append(text='\\x00 value in fields %s' % fields_for_check)

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors and not set([el[0] for el in fields_for_check]).intersection(viewkeys(prepared_depends_fields)):
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field in fields_for_check:
            """if unique fields"""
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                for depended_field in prepared_depends_fields.get(field, []):
                    self.set_empty_value_for_field(params, depended_field)
                params[field] = test_params[field]
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = set(getattr(self, 'exclude_from_check_add', [])).difference(fields_for_check)
                self.assert_object_fields(new_object, params, exclude=exclude,
                                          other_values={field: test_params[field].replace('\x00', '')})
            except Exception:
                self.errors_append(text='\\x00 value in field %s' % field)

    @only_with_obj
    @only_with(('check_null', 'file_fields_params_add', 'check_null_file_negative'))
    def test_add_object_with_null_in_file_negative(self):
        """
        Add object with \\x00 in filenames
        """
        message_type = 'with_null'
        for field, field_dict in viewitems(self.file_fields_params_add):
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)

            f = self.get_random_file(field, filename='qwe\x00' + get_randname(10, 'wrd') + '.' +
                                     choice(field_dict.get('extensions', ['', ])))
            params[field] = f
            initial_obj_count = self.get_obj_manager.count()
            try:
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.errors_append(text='\\x00 value in field %s' % field)

    @only_with_obj
    @only_with(('check_null', 'file_fields_params_add', 'check_null_file_positive'))
    def test_add_object_with_null_in_file_positive(self):
        """
        Add object with \\x00 in filenames
        """
        fields_for_check = list(self.file_fields_params_add.keys())
        test_params = {}
        for field in fields_for_check:
            field_dict = self.file_fields_params_add[field]
            f = self.get_random_file(field, filename='qwe\x00' + get_randname(10, 'wrd') + '.' +
                                     choice(field_dict.get('extensions', ['', ])))
            test_params[field] = f

        try:
            self.prepare_for_add()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)
            params.update(test_params)
            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
            exclude = set(getattr(self, 'exclude_from_check_add', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude, other_values={
                                      field: test_params[field].name.replace('\x00', '') for
                                      field in fields_for_check})
        except Exception:
            self.errors_append(text='\\x00 value in fields %s' % fields_for_check)

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field, field_dict in fields_for_check:
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                params[field] = test_params[field]
                if self.is_file_list(field):
                    for f in params[field]:
                        f.seek(0)
                else:
                    params[field].seek(0)
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = set(getattr(self, 'exclude_from_check_add', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude,
                                          other_values={field: test_params[field].name.replace('\x00', '')})
            except Exception:
                self.errors_append(text='\\x00 value in field %s' % field)

    @only_with_obj
    @only_with('with_captcha')
    def test_add_object_with_null_in_captcha_negative(self):
        """
        Add object with \\x00 in captcha fields
        """
        message_type = 'with_null'
        for field in ('captcha_0', 'captcha_1'):
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_captcha_params('', params)
                params[field] = 'te\x00st'
                response = self.send_add_request(params)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.errors_append(text='\\x00 value in field %s' % field)


class FormEditTestMixIn(FormTestMixIn):

    url_edit = ''

    def clean_depend_fields_edit(self, params, field):
        for field_for_clean in self._depend_one_of_fields_edit.get(field, ()):
            self.set_empty_value_for_field(params, field_for_clean)

    def get_obj_id_for_edit(self):
        if '%' not in self.url_edit and '/' in self.url_edit:
            return int(re.findall(r"/(\d+)/", self.url_edit)[0])
        return choice(self.get_obj_manager.all()).pk

    def _get_obj_for_edit(self):
        return self.get_obj_manager.get(pk=self.get_obj_id_for_edit())

    def get_obj_for_edit(self):
        obj = self._get_obj_for_edit()
        self.update_params_for_obj(obj)
        return obj

    def get_other_obj_with_filled(self, param_names, other_obj):
        obj = self._get_obj_for_edit()
        if all([self._get_field_value_by_name(obj, field) for field in param_names]) and other_obj.pk != obj.pk:
            return obj
        obj_related_objects = self.get_related_names(self.obj)
        filters = ~Q(pk=other_obj.pk)
        for field in param_names:
            if not re.findall(r'[\w_]+\-\d+\-[\w_]+', field):
                filters &= ~Q(**{'%s__isnull' % field: True})
                field_class = self.get_field_by_name(self.obj, field)
                if field_class.empty_strings_allowed:
                    filters &= ~Q(**{field: ''})
            else:
                related_name = obj_related_objects.get(field.split('-')[0], field.split('-')[0])
                filters &= ~Q(**{'%s__%s__isnull' % (related_name, field.split('-')[-1]): True})
                field_class = self.get_field_by_name(self.obj, field)
                if field_class.empty_strings_allowed:
                    filters &= ~Q(**{'%s__%s' % (related_name, field.split('-')[-1]): ''})
        qs = self.get_obj_manager.filter(filters)

        if qs.exists():
            return choice(qs)
        else:
            return self.create_copy(other_obj, param_names)

    def send_edit_request(self, obj_pk, params):
        return self.client.post(self.get_url_for_negative(self.url_edit, (obj_pk,)),
                                params, follow=True, **self.additional_params)

    def update_params_for_obj(self, obj):
        pass

    @only_with_obj
    def test_edit_page_fields_list_positive(self):
        """
        check that all and only need fields is visible at edit page
        """
        obj_pk = self.get_obj_id_for_edit()
        response = self.client.get(self.get_url_for_negative(self.url_edit, (obj_pk,)),
                                   follow=True, **self.additional_params)
        form_fields = self.get_fields_list_from_response(response)
        try:
            """not set because of one field can be on form many times"""
            self.assert_form_equal(form_fields['visible_fields'],
                                   [el for el in self.all_fields_edit if el not in (self.hidden_fields_edit or ())])
        except Exception:
            self.errors_append(text='For visible fields')

        if self.disabled_fields_edit is not None:
            try:
                self.assert_form_equal(form_fields['disabled_fields'], self.disabled_fields_edit)
            except Exception:
                self.errors_append(text='For disabled fields')
        if self.hidden_fields_edit is not None:
            try:
                self.assert_form_equal(form_fields['hidden_fields'], self.hidden_fields_edit)
            except Exception:
                self.errors_append(text='For hidden fields')

        fields_helptext = getattr(self, 'fields_helptext_edit', {})
        for field_name, text in viewitems(fields_helptext):
            if field_name not in self.all_fields_add:
                continue
            try:
                field = get_field_from_response(response, field_name)
                self.assertEqual(field.help_text, text)
            except Exception:
                self.errors_append(text='Helptext for field %s' % field_name)

    @only_with_obj
    def test_edit_object_all_fields_filled_positive(self):
        """
        Edit object: fill all fields
        """
        obj_for_edit = self.get_obj_for_edit()
        params = self.deepcopy(self.default_params_edit)
        prepared_depends_fields = self.prepare_depend_from_one_of(
            self.one_of_fields_edit) if self.one_of_fields_edit else {}
        only_independent_fields = set(self.all_fields_edit).difference(viewkeys(prepared_depends_fields))
        for field in viewkeys(prepared_depends_fields):
            self.set_empty_value_for_field(params, field)

        self.fill_all_fields(list(only_independent_fields) + self.required_fields_edit +
                             self._get_required_from_related(self.required_related_fields_edit), params)
        self.update_params(params)
        self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)

        try:
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()

    @only_with_obj
    @only_with(('one_of_fields_edit',))
    def test_edit_object_with_group_all_fields_filled_positive(self):
        """
        Edit object: fill all fields
        """
        prepared_depends_fields = self.prepare_depend_from_one_of(self.one_of_fields_edit)
        only_independent_fields = set(self.all_fields_edit).difference(viewkeys(prepared_depends_fields))

        fields_from_groups = set(viewkeys(prepared_depends_fields))
        for group in self.one_of_fields_edit:
            field = choice(group)
            fields_from_groups = fields_from_groups.difference(prepared_depends_fields[field])

        for group in self.one_of_fields_edit:
            for field in group:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                for f in viewkeys(prepared_depends_fields):
                    self.set_empty_value_for_field(params, f)
                self.fill_all_fields(only_independent_fields, params)
                self.fill_all_fields(fields_from_groups, params)
                for f in prepared_depends_fields[field]:
                    self.set_empty_value_for_field(params, f)
                self.fill_all_fields((field,), params)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.check_on_edit_success(response, locals())
                    new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    exclude = getattr(self, 'exclude_from_check_edit', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.errors_append(text='For filled %s from group %s' % (field, repr(group)))
                finally:
                    mail.outbox = []

    @only_with_obj
    def test_edit_object_only_required_fields_positive(self):
        """
        Edit object: fill only required fields
        """
        obj_for_edit = self.get_obj_for_edit()
        params = self.deepcopy(self.default_params_edit)
        self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
        required_fields = self.required_fields_edit + self._get_required_from_related(self.required_related_fields_edit)
        self.update_params(params)
        for field in set(viewkeys(params)).difference(required_fields):
            self.set_empty_value_for_field(params, field)
        for field in required_fields:
            self.fill_all_fields(required_fields, params)
        try:
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()
        finally:
            mail.outbox = []

        """если хотя бы одно поле из группы заполнено, объект редактируется"""
        for group in self.required_related_fields_edit:
            for field in group:
                obj_for_edit = self.get_obj_for_edit()
                self.update_params(params)
                params = self.deepcopy(self.default_params_edit)
                for f in group:
                    self.set_empty_value_for_field(params, f)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.fill_all_fields((field,), params)
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.check_on_edit_success(response, locals())
                    new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.errors_append(text='For filled field %s from group "%s"' %
                                       (field, force_text(group)))
                finally:
                    mail.outbox = []

    @only_with_obj
    def test_edit_object_without_not_required_fields_positive(self):
        """
        Edit object: send only required fields
        """
        obj_for_edit = self.get_obj_for_edit()
        params = self.deepcopy(self.default_params_edit)
        self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
        required_fields = self.required_fields_edit + self._get_required_from_related(self.required_related_fields_edit)
        self.update_params(params)
        for field in set(viewkeys(params)).difference(required_fields):
            self.pop_field_from_params(params, field)

        for field in required_fields:
            self.fill_all_fields(required_fields, params)
        try:
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()
        finally:
            mail.outbox = []

        """если хотя бы одно поле из группы заполнено, объект редактируется"""
        for group in self.required_related_fields_edit:
            for field in group:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                for f in group:
                    self.pop_field_from_params(params, f)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.fill_all_fields((field,), params)
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.check_on_edit_success(response, locals())
                    new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.errors_append(text='For filled field %s from group "%s"' %
                                       (field, force_text(group)))
                finally:
                    mail.outbox = []

    @only_with_obj
    def test_edit_object_empty_required_fields_negative(self):
        """
        Try edit object: empty required fields
        """
        message_type = 'empty_required'
        for field in [f for f in self.required_fields_edit if 'FORMS' not in f]:
            sp = transaction.savepoint()
            obj_for_edit = self.get_obj_for_edit()
            try:
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.set_empty_value_for_field(params, field)
                obj_for_edit.refresh_from_db()
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty field "%s"' % field)

        """обязательно хотя бы одно поле из группы (все пустые)"""
        for group in self.required_related_fields_edit:
            sp = transaction.savepoint()
            obj_for_edit = self.get_obj_for_edit()
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            for field in group:
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.set_empty_value_for_field(params, field)
            obj_for_edit.refresh_from_db()
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(
                    message_type, group, error_field=self.non_field_error_key, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty group "%s"' % force_text(group))

    @only_with_obj
    def test_edit_object_without_required_fields_negative(self):
        """
        Try edit object: required fields are not exists in params
        """
        message_type = 'without_required'
        for field in [f for f in self.required_fields_edit if 'FORMS' not in f and not re.findall(r'.+?\-\d+\-.+?', f)]:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.pop_field_from_params(params, field)
                obj_for_edit.refresh_from_db()
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For params without field "%s"' % field)

        """обязательно хотя бы одно поле из группы (все пустые)"""
        for group in self.required_related_fields_edit:
            obj_for_edit = self.get_obj_for_edit()
            sp = transaction.savepoint()
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            for field in group:
                self.pop_field_from_params(params, field)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            obj_for_edit.refresh_from_db()
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(
                    message_type, group, error_field=self.non_field_error_key, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For params without group "%s"' % force_text(group))

    @only_with_obj
    def test_edit_not_exists_object_negative(self):
        """
        Try open edit page of object with invalid id
        """
        for value in ('9999999', '2147483648', 'qwerty', 'йцу'):
            sp = transaction.savepoint()
            try:
                response = self.client.get(self.get_url_for_negative(self.url_edit, (value,)),
                                           follow=True, **self.additional_params)
                self.assertEqual(response.status_code, self.status_code_not_exist,
                                 'Status code %s != %s' % (response.status_code, self.status_code_not_exist))
                if self.status_code_not_exist == 200:
                    """for Django 1.11 admin"""
                    self.assertEqual(self.get_all_form_messages(response), self.get_error_message('not_exist', '')[''])
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='GET request. For value %s' % value)

        params = self.deepcopy(self.default_params_edit)
        for value in ('9999999', '2147483648', 'qwerty', 'йцу'):
            sp = transaction.savepoint()
            try:
                response = self.send_edit_request(value, params)
                self.assertEqual(response.status_code, self.status_code_not_exist,
                                 'Status code %s != %s' % (response.status_code, self.status_code_not_exist))
                if self.status_code_not_exist == 200:
                    """for Django 1.11 admin"""
                    self.assertEqual(self.get_all_form_messages(response), self.get_error_message('not_exist', '')[''])
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='POST request. For value %s' % value)

    @only_with_obj
    def test_edit_object_max_length_values_positive(self):
        """
        Edit object: fill all fields with maximum length values
        """
        obj_for_edit = self.get_obj_for_edit()
        other_fields = []
        for field_type_name in ('digital_fields_edit', 'date_fields', 'datetime_fields', 'choice_fields_edit',
                                'choice_fields_edit_with_value_in_error', 'disabled_fields_edit', 'hidden_fields_edit',
                                'int_fields_edit', 'multiselect_fields_edit', 'not_str_fields'):
            other_fields.extend(getattr(self, field_type_name, []) or [])

        fields_for_check = [(k, self.max_fields_length.get(re.sub('\-\d+\-', '-0-', k), 100000))
                            for k in self.all_fields_edit if re.sub('\-\d+\-', '-0-', k) not in other_fields]
        if not fields_for_check:
            self.skipTest('No any string fields')

        max_length_params = {}
        file_fields = []

        prepared_depends_fields = self.prepare_depend_from_one_of(
            self.one_of_fields_edit) if self.one_of_fields_edit else {}
        fields_for_clean = []
        for field, length in fields_for_check:
            max_length_params[field] = self.get_value_for_field(length, field)
            if self.is_file_field(field):
                file_fields.append(field)
            if field in viewkeys(prepared_depends_fields):
                fields_for_clean.extend(prepared_depends_fields[field])

        sp = transaction.savepoint()
        try:
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            params.update(max_length_params)
            for depended_field in fields_for_clean:
                self.set_empty_value_for_field(params, depended_field)
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)

            if file_fields:
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                self.update_params(params)
                for depended_field in fields_for_clean:
                    self.set_empty_value_for_field(params, depended_field)
                for ff in file_fields:
                    self.set_empty_value_for_field(params, ff)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                _errors = []
                other_values = {ff: self._get_field_value_by_name(obj_for_edit, ff) for ff in file_fields}
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.check_on_edit_success(response, locals())
                    new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference(
                        list(max_length_params.keys()))
                    self.assert_object_fields(new_object, params, exclude=exclude,
                                              other_values=other_values)
                except Exception:
                    self.errors_append(_errors, text='Second save for check max file length')
                if _errors:
                    raise Exception(format_errors(_errors))
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text="For max values in all fields\n%s" %
                                    '\n\n'.join(['  %s with length %d\n(value %s)' %
                                                 (field, length, max_length_params[field] if len(str(max_length_params[field])) <= 1000
                                                  else str(max_length_params[field])[:1000] + '...')
                                                 for field, length in fields_for_check]))
        finally:
            mail.outbox = []

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors and not set([el[0] for el in fields_for_check]).intersection(viewkeys(prepared_depends_fields)):
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field, length in fields_for_check:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                params[field] = max_length_params[field]
                for depended_field in prepared_depends_fields.get(field, []):
                    self.set_empty_value_for_field(params, depended_field)
                if field in file_fields:
                    if self.is_file_list(field):
                        for f in params[field]:
                            f.seek(0)
                    else:
                        params[field].seek(0)
                value = self.get_value_for_error_message(field, params[field])
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)

                if self.is_file_field(field):
                    obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    self.update_params(params)
                    params[field] = ''
                    self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                    _errors = []
                    other_values = {field: self._get_field_value_by_name(obj_for_edit, field)}
                    try:
                        response = self.send_edit_request(obj_for_edit.pk, params)
                        self.check_on_edit_success(response, locals())
                        new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                        exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                        self.assert_object_fields(new_object, params, exclude=exclude,
                                                  other_values=other_values)
                    except Exception:
                        self.errors_append(_errors, text='Second save with file max length')
                    if _errors:
                        raise Exception(format_errors(_errors))
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, length, value if len(str(value)) <= 1000 else str(value)[:1000] + '...'))
            finally:
                mail.outbox = []

    @only_with_obj
    @only_with('max_fields_length')
    def test_edit_object_values_length_gt_max_negative(self):
        """
        Try edit object: values length > maximum
        """
        message_type = 'max_length'
        other_fields = list(getattr(self, 'digital_fields_edit', [])) + list(getattr(self, 'date_fields', []))
        for field, length in [(k, v) for k, v in viewitems(self.max_fields_length) if k in
                              self.all_fields_edit and k not in other_fields]:
            current_length = length + 1
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                params[field] = self.get_value_for_field(current_length, field)
                obj_for_edit.refresh_from_db()
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, current_length, params[field] if len(str(params[field])) <= 1000 else str(params[field])[:1000] + '...'))

    @only_with_obj
    @only_with('min_fields_length')
    def test_edit_object_values_length_lt_min_negative(self):
        """
        Try edit object: values length < minimum
        """
        message_type = 'min_length'
        other_fields = list(getattr(self, 'digital_fields_edit', [])) + list(getattr(self, 'date_fields', []))
        for field, length in [(k, v) for k, v in viewitems(self.min_fields_length) if k in
                              self.all_fields_edit and k not in other_fields]:
            current_length = length - 1
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                params[field] = self.get_value_for_field(current_length, field)
                obj_for_edit.refresh_from_db()
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with length %d\n(value "%s")' %
                                   (field, current_length, params[field]))

    @only_with_obj
    def test_edit_object_with_wrong_choices_negative(self):
        """
        Try edit object: choice values to choices, that not exists
        """
        message_type = 'wrong_value'
        for field in set(tuple(self.choice_fields_edit) + tuple(self.choice_fields_edit_with_value_in_error)):
            for value in ('qwe', '12345678', 'йцу'):
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.update_params(params)
                self.clean_depend_fields_edit(params, field)
                params[field] = value
                obj_for_edit.refresh_from_db()
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    _locals = {'field': field}
                    if field in self.choice_fields_edit_with_value_in_error:
                        _locals['value'] = value
                    error_message = self.get_error_message(message_type, field, locals=_locals)
                    self.assertEqual(self.get_all_form_errors(response),
                                     error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.errors_append(text='For %s value "%s"' % (field, value))

    @only_with_obj
    @only_with(('multiselect_fields_edit',))
    def test_edit_object_with_wrong_multiselect_choices_negative(self):
        """
        Try edit object: choice values to multiselect, that not exists
        """
        message_type = 'wrong_value'
        for field in self.multiselect_fields_edit:
            for value in ('12345678',):
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.update_params(params)
                self.clean_depend_fields_edit(params, field)
                params[field] = [value, ]
                obj_for_edit.refresh_from_db()
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    _locals = {'field': field, 'value': value}
                    error_message = self.get_error_message(message_type, field, locals=_locals)
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.errors_append(text='For %s value "%s"' % (field, value))

    @only_with_obj
    @only_with(('unique_fields_edit',))
    def test_edit_object_unique_already_exists_negative(self):
        """
        Try change object unique field values, to values, that already used in other objects
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
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            for el_field in el:
                if el_field not in self.all_fields_edit:
                    """only if user can change this field"""
                    continue
                self.clean_depend_fields_edit(params, el_field)
                value = self._get_field_value_by_name(existing_obj, el_field)
                params[el_field] = self.get_params_according_to_type(value, '')[0]
            obj_for_edit.refresh_from_db()

            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' %
                                                             (field, params[field]) for field
                                                             in el if field in viewkeys(params)))
        """values is in other case"""
        for el in self.unique_fields_edit:
            field = self.all_unique[el]
            obj_for_edit = self.get_obj_for_edit()
            existing_obj = self.get_other_obj_with_filled(el, obj_for_edit)
            params = self.deepcopy(self.default_params_edit)
            if not any([isinstance(params[el_field], basestring) and el_field not in self.unique_with_case for el_field in el]):
                continue
            sp = transaction.savepoint()
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            for el_field in el:
                if el_field not in self.all_fields_edit:
                    """only if user can change this field"""
                    continue
                self.clean_depend_fields_edit(params, el_field)
                value = self._get_field_value_by_name(existing_obj, el_field)
                params[el_field] = self.get_params_according_to_type(value, '')[0]
                if isinstance(params[el_field], basestring):
                    params[el_field] = params[el_field].swapcase()
            obj_for_edit.refresh_from_db()
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field)
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' % (field, params[field])
                                                             for field in el if field in viewkeys(params)))

    @only_with_obj
    @only_with(('unique_fields_edit', 'unique_with_case',))
    def test_edit_object_unique_alredy_exists_in_other_case_positive(self):
        """
        Change object unique field values, to values, that already used in other objects but in other case
        """
        for el in self.unique_fields_edit:
            if not set(self.unique_with_case).intersection(el):
                continue
            for existing_command, new_command in (('lower', 'upper'),
                                                  ('upper', 'lower')):
                obj_for_edit = self.get_obj_for_edit()
                sp = transaction.savepoint()
                existing_obj = self.get_other_obj_with_filled(el, obj_for_edit)
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                for el_field in el:
                    if el_field not in self.all_fields_edit:
                        """only if user can change this field"""
                        continue
                    value = self.get_value_for_field(None, el_field)
                    params[el_field] = self.get_params_according_to_type(value, '')[0]
                    if el_field in self.unique_with_case:
                        self.get_obj_manager.filter(pk=existing_obj.pk).update(
                            **{el_field: getattr(value, existing_command)()})
                        params[el_field] = getattr(params[el_field], new_command)()
                existing_obj.refresh_from_db()
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.check_on_edit_success(response, locals())
                    new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    exclude = getattr(self, 'exclude_from_check_edit', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For existing values:\n%s\nnew params:\n%s' %
                                       (', '.join('field "%s" with value "%s"\n' % (field,
                                                                                    self._get_field_value_by_name(existing_obj, el_field))
                                                  for field in el),
                                        ', '.join('field "%s" with value "%s"\n' % (field, params[field])
                                                  for field in el if field in viewkeys(params))))
                finally:
                    mail.outbox = []

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_wrong_values_in_digital_negative(self):
        """
        Try edit object: wrong values in digital fields
        """
        for field in self.digital_fields_edit:
            message_type = 'wrong_value_int' if field in self.int_fields_edit else 'wrong_value_digital'
            for value in ('q', 'й', 'NaN', 'inf', '-inf'):
                sp = transaction.savepoint()
                try:
                    obj_for_edit = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                    self.clean_depend_fields_edit(params, field)
                    params[field] = value
                    obj_for_edit.refresh_from_db()
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response),
                                     error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('email_fields_edit',))
    def test_edit_object_wrong_values_in_email_negative(self):
        """
        Try edit object: wrong values in email fields
        """
        message_type = 'wrong_value_email'
        for field in self.email_fields_edit:
            for value in ('q', 'й', 'qwe@rty', 'qw@йц', '@qwe', 'qwe@'):
                sp = transaction.savepoint()
                try:
                    obj_for_edit = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                    self.clean_depend_fields_edit(params, field)
                    params[field] = value
                    obj_for_edit.refresh_from_db()
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_value_max_in_digital_positive(self):
        """
        Edit object: value in digital fields == max
        """
        obj_for_edit = self.get_obj_for_edit()
        fields_for_check = []
        max_value_params = {}
        for field in self.digital_fields_edit:
            max_values = self.get_digital_values_range(field)['max_values']
            if not max_values:
                continue
            fields_for_check.append(field)
            max_value_params[field] = min(max_values)

        sp = transaction.savepoint()
        try:
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            params.update(max_value_params)
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text="For max values in all digital fields\n%s" %
                                    '\n\n'.join(['  %s with value %s' %
                                                 (field, max_value_params[field])
                                                 for field in fields_for_check]))
        finally:
            mail.outbox = []

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field in fields_for_check:
            value = max_value_params[field]
            sp = transaction.savepoint()
            obj_for_edit = self.get_obj_for_edit()
            try:
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                params[field] = value
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with value "%s"' % (field, value))
            finally:
                mail.outbox = []

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_value_gt_max_in_digital_negative(self):
        """
        Try edit object: value in digital fields > max
        """
        message_type = 'max_length_digital'
        for field in [f for f in self.digital_fields_edit]:
            max_value = min(self.get_digital_values_range(field)['max_values'])
            for value in self.get_gt_max_list(field, self.get_digital_values_range(field)['max_values']):
                sp = transaction.savepoint()
                try:
                    obj_for_edit = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                    self.clean_depend_fields_edit(params, field)
                    params[field] = value
                    obj_for_edit.refresh_from_db()
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_value_min_in_digital_positive(self):
        """
        Edit object: value in digital fields == min
        """
        obj_for_edit = self.get_obj_for_edit()
        fields_for_check = []
        min_value_params = {}
        for field in self.digital_fields_edit:
            min_values = self.get_digital_values_range(field)['min_values']
            if not min_values:
                continue
            fields_for_check.append(field)
            min_value_params[field] = max(min_values)

        sp = transaction.savepoint()
        try:
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            params.update(min_value_params)
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text="For min values in all digital fields\n%s" %
                                    '\n\n'.join(['  %s with value %s' %
                                                 (field, min_value_params[field])
                                                 for field in fields_for_check]))
        finally:
            mail.outbox = []

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field in fields_for_check:
            value = min_value_params[field]
            sp = transaction.savepoint()
            obj_for_edit = self.get_obj_for_edit()
            try:
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                params[field] = value
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s" with value "%s"' % (field, value))
            finally:
                mail.outbox = []

    @only_with_obj
    @only_with(('digital_fields_edit',))
    def test_edit_object_value_lt_min_in_digital_negative(self):
        """
        Try edit object: value in digital fields < min
        """
        message_type = 'min_length_digital'
        for field in [f for f in self.digital_fields_edit]:
            min_value = max(self.get_digital_values_range(field)['min_values'])
            for value in self.get_lt_min_list(field, self.get_digital_values_range(field)['min_values']):
                sp = transaction.savepoint()
                try:
                    obj_for_edit = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                    self.clean_depend_fields_edit(params, field)
                    params[field] = value
                    obj_for_edit.refresh_from_db()
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

    @only_with_obj
    @only_with(('disabled_fields_edit',))
    def test_edit_object_disabled_fields_values_negative(self):
        """
        Try change values in disabled fields
        """
        for field in self.disabled_fields_edit:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                params[field] = params.get(field, None) or self.get_value_for_field(None, field)
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                if field not in getattr(self, 'exclude_from_check_edit', []):
                    self.assertEqual(self.get_value_for_compare(new_object, field),
                                     getattr(self, 'other_values_for_check',
                                             {}).get(field, self.get_value_for_compare(obj_for_edit, field)))
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For field "%s"' % field)

    @only_with_obj
    @only_with(('one_of_fields_edit',))
    def test_edit_object_one_of_fields_all_filled_negative(self):
        """
        Try edit object: fill all fields, that should be filled singly
        """
        message_type = 'one_of'
        for group in self.one_of_fields_edit:
            for filled_group in tuple(set([(el, additional_el) for i, el in enumerate(group) for additional_el in
                                           group[i + 1:]]).difference(set(self.one_of_fields_edit).difference(group))) + \
                    (group,):
                sp = transaction.savepoint()
                try:
                    obj_for_edit = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    self.fill_all_fields(filled_group, params)
                    self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                    obj_for_edit.refresh_from_db()
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, group, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For filled %s fields from group %s' %
                                       (force_text(filled_group), force_text(group)))

    @only_with_obj
    @only_with('max_blocks')
    def test_edit_object_max_inline_blocks_count_positive(self):
        """
        Test max number of line in inline blocks
        """
        obj_for_edit = self.get_obj_for_edit()
        params = self.deepcopy(self.default_params_edit)
        self.update_params(params)
        self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
        for name, max_count in viewitems(self.max_blocks):
            self.fill_all_block_fields(name, max_count, params,
                                       set(tuple(self.all_fields_edit) + tuple(self.hidden_fields_edit or ())))
        sp = transaction.savepoint()
        try:
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text="Max count in all (%s) blocks" % ', '.join('%s in %s' % (k, v) for k, v in
                                                                               viewitems(self.max_blocks)))
        finally:
            mail.outbox = []

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(self.max_blocks.keys()) == 1:
            self.formatted_assert_errors()

        for name, max_count in viewitems(self.max_blocks):
            obj_for_edit = self.get_obj_for_edit()
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            self.fill_all_block_fields(name, max_count, params,
                                       set(tuple(self.all_fields_edit) + tuple(self.hidden_fields_edit or ())))
            sp = transaction.savepoint()
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = getattr(self, 'exclude_from_check_edit', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text="Max block count (%s) in %s" % (max_count, name))
            finally:
                mail.outbox = []

    @only_with_obj
    @only_with('max_blocks')
    def test_edit_object_inline_blocks_count_gt_max_negative(self):
        """
        Test max + 1 number of lines in inline blocks
        """
        message_type = 'max_block_count'
        for name, max_count in viewitems(self.max_blocks):
            obj_for_edit = self.get_obj_for_edit()
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            gt_max_count = max_count + 1
            self.fill_all_block_fields(name, gt_max_count, params,
                                       set(tuple(self.all_fields_edit) + tuple(self.hidden_fields_edit or ())))
            sp = transaction.savepoint()
            obj_for_edit.refresh_from_db()
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, name, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text="Count great than max (%s) in block %s" % (gt_max_count, name))

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_files_params('max_count')
    def test_edit_object_many_files_negative(self):
        """
        Try edit obj with files count > max files count
        """
        message_type = 'max_count_file'
        fields_for_check = [field for field, field_dict in viewitems(self.file_fields_params_edit) if
                            field_dict.get('max_count', 1) > 1]
        for field in fields_for_check:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                field_dict = self.file_fields_params_edit[field]
                max_count = field_dict['max_count']
                current_count = max_count + 1
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                filename = '.'.join([s for s in [get_randname(10, 'wrd '),
                                                 choice(field_dict.get('extensions', ('',)))] if s])
                f = self.get_random_file(field, filename=filename, count=current_count)
                params[field] = f
                obj_for_edit.refresh_from_db()
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (current_count, field))

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_files_params('max_count')
    def test_edit_object_many_files_positive(self):
        """
        Try edit obj with photos count == max files count
        """
        obj_for_edit = self.get_obj_for_edit()
        fields_for_check = []
        max_count_params = {}
        for field, field_dict in viewitems(self.file_fields_params_edit):
            if field_dict.get('max_count', 1) <= 1:
                continue
            fields_for_check.append(field)
            max_count_params[field] = []
            max_count = field_dict['max_count']
            f = self.get_random_file(field, count=max_count)
            max_count_params[field] = f

        sp = transaction.savepoint()
        try:
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            params.update(max_count_params)
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text='For max count files in all fields\n%s' %
                                    '\n'.join(['%s: %d' % (field, len(params[field])) for field in fields_for_check]))
        finally:
            mail.outbox = []

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field in fields_for_check:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                params[field] = max_count_params[field]
                for f in params[field]:
                    f.seek(0)
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (len(params[field]), field))
            finally:
                mail.outbox = []

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_files_params('one_max_size')
    def test_edit_object_big_file_negative(self):
        """
        Try edit obj with file size > max one file size
        """
        message_type = 'max_size_file'
        fields_for_check = [field for field, field_dict in viewitems(self.file_fields_params_edit) if
                            field_dict.get('one_max_size', None)]
        for field in fields_for_check:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                field_dict = self.file_fields_params_edit[field]
                one_max_size = field_dict['one_max_size']
                size = convert_size_to_bytes(one_max_size)
                max_size = self.humanize_file_size(size)
                current_size = size + 100
                human_current_size = self.humanize_file_size(current_size)
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                f = self.get_random_file(field, size=current_size)
                filename = f[0].name if isinstance(f, (list, tuple)) else f.name
                params[field] = f
                obj_for_edit.refresh_from_db()
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For file size %s (%s) in field %s' % (self.humanize_file_size(current_size),
                                                                               current_size, field))
            finally:
                self.del_files()

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_files_params('sum_max_size')
    def test_edit_object_big_summary_file_size_negative(self):
        """
        Try edit obj with summary files size > max summary file size
        """
        message_type = 'max_sum_size_file'
        fields_for_check = [field for field, field_dict in viewitems(self.file_fields_params_edit) if
                            field_dict.get('sum_max_size', None)]
        for field in fields_for_check:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                field_dict = self.file_fields_params_edit[field]
                sum_max_size = field_dict['sum_max_size']
                size = convert_size_to_bytes(sum_max_size)
                current_size = size + 100
                max_size = self.humanize_file_size(size)
                one_size = current_size / field_dict['max_count']
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                params[field] = []
                f = self.get_random_file(field, count=field_dict['max_count'], size=one_size)
                params[field] = f
                obj_for_edit.refresh_from_db()
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For summary size %s (%s = %s * %s) in field %s' %
                                   (self.humanize_file_size(current_size), current_size, one_size,
                                    field_dict['max_count'], field))
            finally:
                self.del_files()

    @only_with_obj
    @only_with('file_fields_params_edit')
    def test_edit_object_big_file_positive(self):
        """
        Edit obj with file size == max one file size
        """
        obj_for_edit = self.get_obj_for_edit()
        fields_for_check = list(self.file_fields_params_edit.keys())
        max_size_params = {}
        for field in fields_for_check:
            field_dict = self.file_fields_params_edit[field]
            one_max_size = field_dict.get('one_max_size', '10M')
            size = convert_size_to_bytes(one_max_size)
            if field_dict.get('sum_max_size', None):
                count = 1
            else:
                count = field_dict.get('max_count', 1)
            f = self.get_random_file(field, size=size, count=count)
            max_size_params[field] = f

        sp = transaction.savepoint()
        try:
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            params.update(max_size_params)
            response = self.send_edit_request(obj_for_edit.pk, params)

            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference(fields_for_check)
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.savepoint_rollback(sp)
            self.errors_append(text='For max size files in all fields\n%s' %
                                    '\n'.join(['%s: %s (%s)' %
                                               (field,
                                                convert_size_to_bytes(
                                                    self.file_fields_params_edit[field].get('one_max_size', '10M')),
                                                self.humanize_file_size(
                                                    convert_size_to_bytes(
                                                        self.file_fields_params_edit[field].get('one_max_size', '10M'))))
                                               for field in fields_for_check]))
        finally:
            mail.outbox = []

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors:
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for field in fields_for_check:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                field_dict = self.file_fields_params[field]
                one_max_size = field_dict.get('one_max_size', '10M')
                size = convert_size_to_bytes(one_max_size)
                max_size = self.humanize_file_size(size)
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                params[field] = max_size_params[field]
                if self.is_file_list(field):
                    for f in params[field]:
                        f.seek(0)
                else:
                    params[field].seek(0)
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For file size %s (%s) in field %s' % (max_size, size, field))
            finally:
                self.del_files()
                mail.outbox = []

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_files_params('sum_max_size')
    def test_edit_object_big_summary_file_size_positive(self):
        """
        Edit obj with summary files size == max summary files size
        """
        fields_for_check = [field for field, field_dict in viewitems(self.file_fields_params_edit) if
                            field_dict.get('sum_max_size', None)]
        for field in fields_for_check:
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                field_dict = self.file_fields_params_edit[field]
                sum_max_size = field_dict['sum_max_size']
                size = convert_size_to_bytes(sum_max_size)
                max_size = self.humanize_file_size(size)
                one_size = size / field_dict['max_count']
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                params[field] = []
                f = self.get_random_file(field, size=one_size, count=field_dict['max_count'])
                params[field] = f
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For summary size %s (%s = %s * %s) in field %s' %
                                   (max_size, one_size * field_dict['max_count'], one_size, field_dict['max_count'],
                                    field))
            finally:
                self.del_files()
                mail.outbox = []

    @only_with_obj
    @only_with('file_fields_params_edit')
    def test_edit_object_empty_file_negative(self):
        """
        Try edit obj with file size = 0M
        """
        message_type = 'empty_file'
        for field in list(self.file_fields_params_edit.keys()):
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                f = self.get_random_file(field, size=0)
                filename = f[0].name if isinstance(f, (list, tuple)) else f.name
                params[field] = f
                obj_for_edit.refresh_from_db()
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message(message_type, field, locals=locals()))
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty file in field %s' % field)

    @only_with_obj
    @only_with('file_fields_params_edit')
    def test_edit_object_some_file_extensions_positive(self):
        """
        Edit obj with some available extensions
        """
        for field in list(self.file_fields_params_edit.keys()):
            field_dict = self.file_fields_params_edit[field]
            extensions = copy(field_dict.get('extensions', ()))
            if not extensions:
                extensions = (get_randname(3, 'wd'), '')
            extensions += tuple([e.upper() for e in extensions if e])
            for ext in extensions:
                sp = transaction.savepoint()
                filename = '.'.join([el for el in ['test', ext] if el])
                f = self.get_random_file(field, filename=filename)
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                params[field] = f
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.check_on_edit_success(response, locals())
                    new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception as e:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))
                finally:
                    mail.outbox = []

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_files_params('extensions')
    def test_edit_object_wrong_file_extensions_negative(self):
        """
        Edit obj with wrong extensions
        """
        message_type = 'wrong_extension'
        for field in list(self.file_fields_params_edit.keys()):
            field_dict = self.file_fields_params_edit[field]
            extensions = copy(field_dict.get('extensions', ()))
            if not extensions:
                continue
            ext = get_randname(3, 'wd')
            while ext.lower() in extensions:
                ext = get_randname(3, 'wd')
            wrong_extensions = tuple(field_dict.get('wrong_extensions', ())) + ('', ext)
            for ext in wrong_extensions:
                filename = '.'.join([el for el in ['test', ext] if el])
                sp = transaction.savepoint()
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                f = self.get_random_file(field, filename=filename)
                params[field] = f
                obj_for_edit.refresh_from_db()
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=locals()))
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_any_files_params(['min_width', 'min_height'])
    def test_edit_object_min_image_dimensions_positive(self):
        """
        Edit obj with minimum image file dimensions
        """
        for field in list(self.file_fields_params_edit.keys()):
            field_dict = self.file_fields_params_edit[field]
            width = field_dict.get('min_width', 1)
            height = field_dict.get('min_height', 1)
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                f = self.get_random_file(field, width=width, height=height)
                params[field] = f
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))
            finally:
                mail.outbox = []

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_any_files_params(['min_width', 'min_height'])
    def test_edit_object_image_dimensions_lt_min_negative(self):
        """
        Edit obj with image file dimensions < minimum
        """
        message_type = 'min_dimensions'
        for field in list(self.file_fields_params_edit.keys()):
            field_dict = self.file_fields_params_edit[field]
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
                    obj_for_edit = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                    f = self.get_random_file(field, width=width, height=height)
                    filename = f[0].name if isinstance(f, (list, tuple)) else f.name
                    self.clean_depend_fields_edit(params, field)
                    params[field] = f
                    obj_for_edit.refresh_from_db()
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=locals()))
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_any_files_params(['max_width', 'max_height', 'min_width', 'min_height'])
    def test_edit_object_max_image_dimensions_positive(self):
        """
        Edit obj with maximum image file dimensions
        """
        for field in list(self.file_fields_params_edit.keys()):
            field_dict = self.file_fields_params_edit[field]
            width = field_dict.get('max_width', 10000)
            height = field_dict.get('max_height', 10000)
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                f = self.get_random_file(field, width=width, height=height)
                self.clean_depend_fields_edit(params, field)
                params[field] = f
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = set(getattr(self, 'exclude_from_check_edit', [])).difference([field, ])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))
            finally:
                mail.outbox = []

    @only_with_obj
    @only_with('file_fields_params_edit')
    @only_with_any_files_params(['max_width', 'max_height'])
    def test_edit_object_image_dimensions_gt_max_negative(self):
        """
        Edit obj with image file dimensions > maximum
        """
        message_type = 'max_dimensions'
        for field in list(self.file_fields_params_edit.keys()):
            field_dict = self.file_fields_params_edit[field]
            values = ()
            max_width = field_dict.get('max_width', None)
            if max_width:
                values += ((max_width + 1, field_dict.get('max_height', field_dict.get('min_height', 1))),)
            max_height = field_dict.get('max_height', None)
            if max_height:
                values += ((field_dict.get('max_width', field_dict.get('min_width', 1)), max_height + 1),)

            for width, height in values:
                sp = transaction.savepoint()
                try:
                    obj_for_edit = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                    self.clean_depend_fields_edit(params, field)
                    f = self.get_random_file(field, width=width, height=height)
                    filename = f[0].name if isinstance(f, (list, tuple)) else f.name
                    params[field] = f
                    obj_for_edit.refresh_from_db()
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message(message_type, field, locals=locals()))
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))


class FormDeleteTestMixIn(FormTestMixIn):

    url_delete = ''

    def send_delete_request(self, obj_pk):
        return self.client.post(self.get_url_for_negative(self.url_delete, (obj_pk,)), {'post': 'yes'},
                                follow=True, **self.additional_params)

    @only_with_obj
    def test_delete_not_exists_object_negative(self):
        """
        Try delete object with invalid id
        """
        for value in ('9999999', '2147483648', 'qwe', 'йцу'):
            sp = transaction.savepoint()
            try:
                response = self.send_delete_request(value)
                self.assertEqual(response.status_code, self.status_code_not_exist,
                                 'Status code %s != %s' % (response.status_code, self.status_code_not_exist))
                if self.status_code_not_exist == 200:
                    """for Django 1.11 admin"""
                    self.assertEqual(self.get_all_form_messages(response), self.get_error_message('not_exist', '')[''])
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For value %s error' % value)

    @only_with_obj
    def test_delete_obj_positive(self):
        """
        Delete object
        """
        if 'get_obj_id_for_edit' in dir(self):
            obj_pk = self.get_obj_id_for_edit()
        else:
            obj_pk = choice(self.get_obj_manager.all()).pk
        initial_obj_count = self.get_obj_manager.count()
        self.send_delete_request(obj_pk)
        self.assertEqual(self.get_obj_manager.count(), initial_obj_count - 1,
                         'Objects count after delete = %s (expect %s)' %
                         (self.get_obj_manager.count(), initial_obj_count - 1))

    @only_with_obj
    @only_with(('url_list',))
    def test_delete_obj_from_list_positive(self):
        """
        Delete objects from objects list
        """
        obj_ids = self.get_obj_manager.values_list('pk', flat=True)
        initial_obj_count = self.get_obj_manager.count()
        params = {'_selected_action': obj_ids,
                  'action': 'delete_selected',
                  'post': 'yes'}
        response = self.send_list_action_request(params)
        try:
            self.assertEqual(self.get_all_form_messages(response),
                             ['Успешно удалены %d %s.' % (len(obj_ids), self.obj._meta.verbose_name if len(obj_ids) == 1
                                                          else self.obj._meta.verbose_name_plural)])
            self.assertEqual(self.get_obj_manager.count(), initial_obj_count - len(obj_ids),
                             'Objects count after delete = %s (expect %s)' %
                             (self.get_obj_manager.count(), initial_obj_count - len(obj_ids)))
        except Exception:
            self.errors_append()


class FormRemoveTestMixIn(FormTestMixIn):
    """for objects with is_removed attribute"""

    url_delete = ''
    url_edit_in_trash = ''
    url_recovery = ''

    def __init__(self, *args, **kwargs):
        super(FormRemoveTestMixIn, self).__init__(*args, **kwargs)
        self.url_edit_in_trash = self.url_edit_in_trash or self.url_recovery.replace('trash_restore', 'trash_change')

    def send_delete_request(self, obj_pk):
        return self.client.post(self.get_url_for_negative(self.url_delete, (obj_pk,)),
                                follow=True, **self.additional_params)

    def send_recovery_request(self, obj_pk):
        return self.client.post(self.get_url_for_negative(self.url_recovery, (obj_pk,)),
                                follow=True, **self.additional_params)

    def send_trash_list_action_request(self, params):
        return self.client.post(self.get_url(self.url_trash_list), params,
                                follow=True, **self.additional_params)

    def get_is_removed(self, obj):
        is_removed_name = getattr(self, 'is_removed_field', 'is_removed')
        return getattr(obj, is_removed_name)

    def set_is_removed(self, obj, value):
        is_removed_name = getattr(self, 'is_removed_field', 'is_removed')
        setattr(obj, is_removed_name, value)

    @only_with_obj
    def test_delete_obj_positive(self):
        """
        Delete object
        """
        obj_id = self.get_obj_id_for_edit()
        initial_obj_count = self.get_obj_manager.count()
        try:
            self.send_delete_request(obj_id)
            self.assertEqual(self.get_obj_manager.count(), initial_obj_count)
            self.assertTrue(self.get_is_removed(self.get_obj_manager.get(id=obj_id)))
        except Exception:
            self.errors_append()

    @only_with_obj
    def test_recovery_obj_positive(self):
        """
        Recovery deleted object
        """
        obj_for_test = self.get_obj_for_edit()
        self.set_is_removed(obj_for_test, True)
        obj_for_test.save()
        obj_id = obj_for_test.id
        try:
            initial_obj_count = self.get_obj_manager.count()
            self.send_recovery_request(obj_id)
            self.assertEqual(self.get_obj_manager.count(), initial_obj_count)
            self.assertFalse(self.get_is_removed(self.get_obj_manager.get(id=obj_id)))
        except Exception:
            self.errors_append()

    @only_with_obj
    def test_delete_not_exists_object_negative(self):
        """
        Try delete object with invalid id
        """
        for value in ('9999999', '2147483648', 'qwe', 'йцу'):
            try:
                response = self.send_delete_request(value)
                self.assertTrue(response.redirect_chain[0][0].endswith(self.get_url(self.url_list)),
                                'Redirect was %s' % response.redirect_chain[0][0])
                self.assertEqual(response.status_code, 200)
                error_message = self.get_error_message('delete_not_exists', None)
                self.assertEqual(self.get_all_form_messages(response), [error_message])
            except Exception:
                self.errors_append(text='For value "%s" error' % value)

    @only_with_obj
    def test_recovery_not_exists_object_negative(self):
        """
        Try recovery object with invalid id
        """
        for value in ('9999999', '2147483648',):
            try:
                response = self.send_recovery_request(value)
                self.assertTrue(response.redirect_chain[0][0].endswith(self.get_url(self.url_trash_list)),
                                'Redirect was %s' % response.redirect_chain[0][0])
                self.assertEqual(response.status_code, 200)
                error_message = self.get_error_message('recovery_not_exists', None)
                self.assertEqual(self.get_all_form_messages(response), [error_message])
            except Exception:
                self.errors_append(text='For value "%s" error' % value)

    @only_with_obj
    def test_edit_in_trash_negative(self):
        """
        Try change object in trash
        """
        obj_for_test = self.get_obj_for_edit()
        self.set_is_removed(obj_for_test, True)
        obj_for_test.save()
        obj_id = obj_for_test.id
        params = self.deepcopy(self.default_params_edit)
        try:
            url = self.get_url_for_negative(self.url_edit_in_trash, (obj_id,))
            response = self.client.post(url, params, follow=True, **self.additional_params)
            self.assertTrue(response.redirect_chain[0][0].endswith(self.get_url(self.url_trash_list)))
            self.assertEqual(response.status_code, 200)
            error_message = 'Вы не можете изменять объекты в корзине.'
            self.assertEqual(self.get_all_form_messages(response), [error_message])
        except Exception:
            self.errors_append()

    @only_with_obj
    @only_with(('url_edit',))
    def test_edit_in_trash_by_edit_url_negative(self):
        """
        Try change object in trash
        """
        obj_for_test = self.get_obj_for_edit()
        self.set_is_removed(obj_for_test, True)
        obj_for_test.save()
        value = obj_for_test.id
        params = self.deepcopy(self.default_params_edit)
        try:
            response = self.send_edit_request(value, params)
            self.assertEqual(response.status_code, self.status_code_not_exist,
                             'Status code %s != %s' % (response.status_code, self.status_code_not_exist))
            if self.status_code_not_exist == 200:
                """for Django 1.11 admin"""
                self.assertEqual(self.get_all_form_messages(response), self.get_error_message('not_exist', '')[''])
        except Exception:
            self.errors_append()

    @only_with_obj
    @only_with(('others_objects',))
    def test_recovery_other_user_obj_negative(self):
        obj_for_test = choice(self.others_objects)
        self.set_is_removed(obj_for_test, True)
        obj_for_test.save()
        try:
            initial_obj_count = self.get_obj_manager.count()
            response = self.send_recovery_request(obj_for_test.pk)
            self.assertEqual(self.get_obj_manager.count(), initial_obj_count)
            self.assertTrue(self.get_is_removed(self.get_obj_manager.get(id=obj_for_test.pk)))
            self.assertEqual(self.get_all_form_messages(response), ['Произошла ошибка. Попробуйте позже.'])
        except Exception:
            self.errors_append()

    @only_with_obj
    @only_with(('others_objects',))
    def test_delete_other_user_obj_negative(self):
        obj_for_test = choice(self.others_objects)
        self.set_is_removed(obj_for_test, False)
        obj_for_test.save()
        initial_obj_count = self.get_obj_manager.count()
        try:
            response = self.send_delete_request(obj_for_test.pk)
            self.assertEqual(self.get_obj_manager.count(), initial_obj_count)
            self.assertFalse(self.get_is_removed(self.get_obj_manager.get(id=obj_for_test.pk)))
            self.assertEqual(self.get_all_form_messages(response), ['Произошла ошибка. Попробуйте позже.'])
        except Exception:
            self.errors_append()

    @only_with_obj
    @only_with(('url_list',))
    def test_delete_obj_from_list_positive(self):
        """
        Delete objects from objects list
        """
        obj_ids = [self.get_obj_id_for_edit()]
        initial_obj_count = self.get_obj_manager.count()
        params = {'_selected_action': obj_ids,
                  'action': 'action_remove',
                  'select_across': '0'}
        response = self.send_list_action_request(params)
        try:
            self.assertEqual(self.get_all_form_messages(response),
                             ['Успешно удалено %d объектов.' % len(obj_ids)])
            self.assertEqual(self.get_obj_manager.count(), initial_obj_count,
                             'Objects count after remove (should not be changed) = %s (expect %s)' %
                             (self.get_obj_manager.count(), initial_obj_count))
            self.assertTrue(all([self.get_is_removed(obj) for obj in self.get_obj_manager.filter(pk__in=obj_ids)]))
        except Exception:
            self.errors_append()

    @only_with_obj
    def test_recovery_obj_from_list_positive(self):
        """
        Recovery deleted objects from objects list
        """
        self.get_obj_manager.update(is_removed=True)
        obj_ids = [self.get_obj_id_for_edit()]
        initial_obj_count = self.get_obj_manager.count()
        params = {'_selected_action': obj_ids,
                  'action': 'action_restore',
                  'select_across': '0'}
        response = self.send_trash_list_action_request(params)
        try:
            self.assertEqual(self.get_all_form_messages(response),
                             ['Успешно восстановлено %d объектов.' % len(obj_ids)])
            self.assertEqual(self.get_obj_manager.count(), initial_obj_count,
                             'Objects count after recovery (should not be changed) = %s (expect %s)' %
                             (self.get_obj_manager.count(), initial_obj_count))
            self.assertFalse(any(self.get_obj_manager.filter(pk__in=obj_ids).values_list('is_removed', flat=True)))
        except Exception:
            self.errors_append()


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
                    res_kwargs = {k: v if force_text(v) != '123' else 1 for k, v in viewitems(res.kwargs)}
                    res_args = tuple([v if force_text(v) != '123' else 1 for v in res.args])
                    result += ((':'.join([el for el in [res.namespace, res.url_name] if el]),
                                res_kwargs or res_args),)
            except Exception:
                result += (aa,)
                print('!!!!!', res, aa)
        return result

    def login(self):
        if self.username:
            self.user_login(self.username, self.password)

    def _get_values(self, el):
        args = None
        custom_message = ''
        if isinstance(el, basestring):
            return el, args, custom_message
        if len(el) == 1:
            url_name = el[0]
        elif len(el) == 2 and isinstance(el[1], basestring):
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
        check allowed links
        """
        for el in self.allowed_links:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = ''
            try:
                url = self.get_url(url_name, args)
                response = self.get_method(url, **self.additional_params)
                self.assertEqual(response.status_code, 200)
            except Exception:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with(('links_redirect',))
    def test_unallowed_links_with_redirect(self):
        """
        check unallowed links, that should redirect to other page
        """
        for el in self.links_redirect:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertRedirects(response, self.get_url(self.redirect_to))
            except Exception:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with(('links_400',))
    def test_unallowed_links_with_400_response(self):
        """
        check unallowed links, that should response 404
        """
        for el in self.links_400:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 400)
            except Exception:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with('links_401')
    def test_unallowed_links_with_401_response(self):
        """
        check unallowed links, that should response 401
        """
        self.login()
        for el in self.links_401:
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(self.get_all_form_errors(response),
                                 {"detail": 'Учетные данные не были предоставлены.'})
            except Exception:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with(('links_403',))
    def test_unallowed_links_with_403_response(self):
        """
        check unallowed links, that should response 403
        """
        for el in self.links_403:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 403)
            except Exception:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with('urlpatterns')
    def test_unallowed_links_with_404_response(self):
        """
        check unallowed links, that should response 404
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
            except Exception:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))

    @only_with(('links_405',))
    def test_unallowed_links_with_405_response(self):
        """
        check unallowed links, that should response 404
        """
        for el in self.links_405:
            self.login()
            url_name, args, custom_message = self._get_values(el)
            url = self.get_url(url_name, args)
            try:
                response = self.get_method(url, follow=True, **self.additional_params)
                self.assertEqual(response.status_code, 405)
            except Exception:
                self.errors_append(text='For page %s (%s)%s' % (url, url_name, custom_message))


class ChangePasswordMixIn(GlobalTestMixIn, LoginMixIn):

    all_fields = None
    current_password = 'qwerty'
    disabled_fields = ()
    field_old_password = None
    field_password = None
    field_password_repeat = None
    hidden_fields = ()
    password_max_length = 128
    password_min_length = 6
    password_params = {}
    obj = None
    password_positive_values = [get_randname(10, 'w') + str(randint(0, 9)),
                                str(randint(0, 9)) + get_randname(10, 'w'),
                                get_randname(10, 'w').upper() + str(randint(0, 9)), ]
    url_change_password = ''
    with_captcha = False
    password_wrong_values = ['йцукенг', ]

    def __init__(self, *args, **kwargs):
        super(ChangePasswordMixIn, self).__init__(*args, **kwargs)
        if self.all_fields is None:
            self.all_fields = [
                el for el in [self.field_old_password, self.field_password, self.field_password_repeat] if el]
        """for get_value_for_field"""
        self.max_fields_length = getattr(self, 'max_fields_length', {})
        if self.password_max_length:
            self.max_fields_length['password'] = self.max_fields_length.get('password', self.password_max_length)
        self.min_fields_length = getattr(self, 'min_fields_length', {})
        self.min_fields_length['password'] = self.min_fields_length.get('password', self.password_min_length)
        value = self.get_value_for_field(None, 'password')
        self.password_params = (self.password_params
                                or self.deepcopy(getattr(self, 'default_params', {}))
                                or {k: v for k, v in {self.field_old_password: self.current_password,
                                                      self.field_password: value,
                                                      self.field_password_repeat: value}.items() if k})
        for k, v in {self.field_old_password: self.current_password,
                     self.field_password: value,
                     self.field_password_repeat: value}.items():
            if k:
                self.password_params[k] = self.password_params.get(k, v) or v

    def check_positive(self, user, params):
        new_user = self.get_obj_manager.get(pk=user.pk)
        self.assertFalse(new_user.check_password(params.get(self.field_old_password or '', '') or self.current_password),
                         'Password not changed')
        self.assertTrue(new_user.check_password(params[self.field_password]),
                        'Password not changed to "%s"' % params[self.field_password])

    def check_negative(self, user, params, response):
        new_user = self.get_obj_manager.get(pk=user.pk)
        self.assert_objects_equal(new_user, user)

    def get_obj_for_edit(self):
        user = choice(self.get_obj_manager.all())
        self.user_relogin(user.email, self.current_password)
        user.refresh_from_db()
        return user

    def get_login_name(self, user):
        return user.email

    def send_change_password_request(self, user_pk, params):
        return self.client.post(self.get_url_for_negative(self.url_change_password, (user_pk,)),
                                params, **self.additional_params)

    @only_with_obj
    def test_change_password_page_fields_list(self):
        """
        Check fields list on change password form
        """
        user = self.get_obj_for_edit()
        response = self.client.get(self.get_url_for_negative(self.url_change_password, (user.pk,)),
                                   follow=True, **self.additional_params)
        form_fields = self.get_fields_list_from_response(response)
        try:
            self.assert_form_equal(form_fields['visible_fields'], self.all_fields)
        except Exception:
            self.errors_append(text='For visible fields')

        try:
            self.assert_form_equal(form_fields['disabled_fields'], self.disabled_fields)
        except Exception:
            self.errors_append(text='For disabled fields')

        try:
            self.assert_form_equal(form_fields['hidden_fields'], self.hidden_fields)
        except Exception:
            self.errors_append(text='For hidden fields')

    @only_with_obj
    def test_change_password_positive(self):
        """
        Change password
        """
        for value in self.password_positive_values or [self.password_params[self.field_password], ]:
            user = self.get_obj_for_edit()
            params = self.deepcopy(self.password_params)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
            params[self.field_password] = value
            params[self.field_password_repeat] = value
            try:
                response = self.send_change_password_request(user.pk, params)
                self.assert_no_form_errors(response)
                self.check_positive(user, params)
            except Exception:
                self.errors_append(text='New password "%s"' % params[self.field_password])

    @only_with_obj
    def test_change_password_empty_required_fields_negative(self):
        """
        Try change password: empty required fields
        """
        message_type = 'empty_required'
        for field in filter(None, [self.field_old_password, self.field_password, self.field_password_repeat]):
            user = self.get_obj_for_edit()
            try:
                params = self.deepcopy(self.password_params)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
                self.set_empty_value_for_field(params, field)
                user.refresh_from_db()
                response = self.send_change_password_request(user.pk, params)
                self.check_negative(user, params, response)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
            except Exception:
                self.errors_append(text='Empty field "%s"' % field)

    @only_with_obj
    def test_change_password_without_required_fields_negative(self):
        """
        Try change password: without required fields
        """
        message_type = 'without_required'
        for field in filter(None, [self.field_old_password, self.field_password, self.field_password_repeat]):
            user = self.get_obj_for_edit()
            try:
                params = self.deepcopy(self.password_params)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)),
                                           params)
                self.pop_field_from_params(params, field)
                user.refresh_from_db()
                response = self.send_change_password_request(user.pk, params)
                self.check_negative(user, params, response)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assertEqual(self.get_all_form_errors(response), error_message)
            except Exception:
                self.errors_append(text='Without field "%s"' % field)

    @only_with_obj
    def test_change_password_different_new_passwords_negative(self):
        """
        Try change password: different password and repeat password values
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        self.update_params(params)
        self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)),
                                   params)
        params.update({self.field_password: self.get_value_for_field(None, 'password'),
                       self.field_password_repeat: self.get_value_for_field(None, 'password')})
        user.refresh_from_db()
        try:
            response = self.send_change_password_request(user.pk, params)
            self.check_negative(user, params, response)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('wrong_password_repeat', self.field_password_repeat))
        except Exception:
            self.errors_append(text='New passwords "%s", "%s"' %
                               (params[self.field_password], params[self.field_password_repeat]))

    @only_with_obj
    @only_with('password_min_length')
    def test_change_password_length_lt_min_negative(self):
        """
        Try change password with length < password_min_length
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        self.update_params(params)
        self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)),
                                   params)
        length = self.password_min_length
        current_length = length - 1
        value = self.get_value_for_field(current_length, 'password')
        params.update({self.field_password: value,
                       self.field_password_repeat: value})
        user.refresh_from_db()
        try:
            response = self.send_change_password_request(user.pk, params)
            self.check_negative(user, params, response)
            error_message = self.get_error_message('min_length', self.field_password,)
            self.assertEqual(self.get_all_form_errors(response), error_message)
        except Exception:
            self.errors_append(text='New password "%s"' % params[self.field_password])

    @only_with_obj
    @only_with('password_min_length')
    def test_change_password_min_length_positive(self):
        """
        Change password with length = password_min_length
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        self.update_params(params)
        self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
        params[self.field_password] = self.get_value_for_field(self.password_min_length, 'password')
        params[self.field_password_repeat] = params[self.field_password]

        try:
            response = self.send_change_password_request(user.pk, params)
            self.assert_no_form_errors(response)
            self.check_positive(user, params)
        except Exception:
            self.errors_append(text='New password "%s"' % params[self.field_password])

    @only_with_obj
    @only_with('password_max_length')
    def test_change_password_max_length_positive(self):
        """
        Change password with length = password_max_length
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        self.update_params(params)
        self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
        params[self.field_password] = self.get_value_for_field(self.password_max_length, 'password')
        params[self.field_password_repeat] = params[self.field_password]

        try:
            response = self.send_change_password_request(user.pk, params)
            self.assert_no_form_errors(response)
            self.check_positive(user, params)
        except Exception:
            self.errors_append(text='New password "%s"' % params[self.field_password])

    @only_with_obj
    @only_with('password_max_length')
    def test_change_password_length_gt_max_negative(self):
        """
        Try change self password with length > password_max_length
        """
        user = self.get_obj_for_edit()
        length = self.password_max_length
        params = self.deepcopy(self.password_params)
        self.update_params(params)
        self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
        current_length = length + 1
        params[self.field_password] = self.get_value_for_field(current_length, 'password')
        params[self.field_password_repeat] = params[self.field_password]
        user.refresh_from_db()
        try:
            response = self.send_change_password_request(user.pk, params)
            self.check_negative(user, params, response)
            error_message = self.get_error_message('max_length', self.field_password,)
            self.assertEqual(self.get_all_form_errors(response), error_message)
        except Exception:
            self.errors_append(text='New password "%s"' % params[self.field_password])

    @only_with_obj
    @only_with('password_wrong_values')
    def test_change_password_wrong_value_negative(self):
        """
        Try change password to wrong value
        """
        for value in self.password_wrong_values:
            user = self.get_obj_for_edit()
            params = self.deepcopy(self.password_params)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
            params.update({self.field_password: value,
                           self.field_password_repeat: value})
            user.refresh_from_db()
            try:
                response = self.send_change_password_request(user.pk, params)
                self.check_negative(user, params, response)
                error_message = self.get_error_message('wrong_value', self.field_password,)
                self.assertEqual(self.get_all_form_errors(response), error_message)
            except Exception:
                self.errors_append(text='New password value "%s"' % value)

    @only_with_obj
    @only_with('field_old_password')
    def test_change_password_wrong_old_negative(self):
        """
        Try change password: wrong old password
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        self.update_params(params)
        self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
        value = self.field_old_password + get_randname(1, 'w')
        params[self.field_old_password] = value
        user.refresh_from_db()
        try:
            response = self.send_change_password_request(user.pk, params)
            self.check_negative(user, params, response)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('wrong_old_password', self.field_old_password))
        except Exception:
            self.errors_append()

    @only_with_obj
    @only_with('field_old_password')
    def test_change_password_invalid_old_value_positive(self):
        """
        Change password: old password value not valid now
        """
        wrong_values = list(self.password_wrong_values or [])
        if self.password_min_length:
            wrong_values.append(self.get_value_for_field(self.password_min_length - 1, 'password'))
        if self.password_max_length:
            wrong_values.append(self.get_value_for_field(self.password_max_length + 1, 'password'))
        for old_password in wrong_values:
            user = self.get_obj_for_edit()
            user.set_password(old_password)
            user.save()
            self.user_relogin(self.get_login_name(user), old_password, **self.additional_params)
            user.refresh_from_db()
            params = self.deepcopy(self.password_params)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
            value = self.get_value_for_field(None, 'password')
            params.update({self.field_old_password: old_password,
                           self.field_password: value,
                           self.field_password_repeat: value})
            try:
                response = self.send_change_password_request(user.pk, params)
                self.assert_no_form_errors(response)
                self.check_positive(user, params)
            except Exception:
                self.errors_append(text='Old password value "%s"' % old_password)

    @only_with('password_similar_fields')
    def test_change_password_value_similar_to_user_field_negative(self):
        """
        Try change password to value similar to field from object
        """

        def new_value(value, change_type):
            if change_type == '':
                return value
            if change_type == 'swapcase':
                return value.swapcase()
            if change_type == 'add_before':
                return get_randname(1, 'w') + value
            if change_type == 'add_after':
                return value + get_randname(1, 'w')

        for field in self.password_similar_fields:
            user_field_name = getattr(self.get_field_by_name(self.obj, field), 'verbose_name', field)
            for change_type in ('', 'swapcase', 'add_before', 'add_after'):
                user = self.get_obj_for_edit()
                value = self.get_value_for_field(self.password_min_length, field)
                self.get_obj_manager.filter(pk=user.pk).update(**{field: value})
                user.refresh_from_db()
                password_value = new_value(value, change_type)
                params = self.deepcopy(self.password_params)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
                params.update({self.field_password: password_value,
                               self.field_password_repeat: password_value})
                user.refresh_from_db()
                try:
                    response = self.send_change_password_request(user.pk, params)
                    self.check_negative(user, params, response)
                    error_message = self.get_error_message(
                        'wrong_password_similar', self.field_password, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                except Exception:
                    self.errors_append(text='New password value "%s" is similar to user.%s = "%s"' %
                                       (password_value, field, value))


class ResetPasswordMixIn(GlobalTestMixIn):

    code_lifedays = None
    current_password = 'qwerty'
    field_username = None
    field_password = None
    field_password_repeat = None
    mail_subject = ''
    mail_body = ''
    mail_from = None
    password_max_length = 128
    password_min_length = 6
    password_params = None
    request_password_params = None
    request_fields = None
    change_fields = None
    obj = None
    password_positive_values = [get_randname(10, 'w') + str(randint(0, 9)),
                                str(randint(0, 9)) + get_randname(10, 'w'),
                                get_randname(10, 'w').upper() + str(randint(0, 9)), ]
    url_reset_password_request = ''
    url_reset_password = ''
    username = None
    username_is_email = True
    with_captcha = True
    password_wrong_values = ['йцукенг', ]

    def __init__(self, *args, **kwargs):
        super(ResetPasswordMixIn, self).__init__(*args, **kwargs)
        if self.request_fields is None:
            self.request_fields = [self.field_username, ] if self.field_username else []
        if self.change_fields is None:
            self.change_fields = [el for el in [self.field_password, self.field_password_repeat] if el]
        if self.request_password_params is None:
            self.request_password_params = {self.field_username: self.username}
        if self.password_params is None:
            value = self.get_value_for_field(None, 'password')
            self.password_params = {self.field_password: value,
                                    self.field_password_repeat: value}

    def assert_request_password_change_mail(self, params):
        self.assert_mail_count(mail.outbox, 1)
        m = mail.outbox[0]
        user = params['user']
        codes = self.get_codes(user)
        params['url_reset_password'] = self.get_url(self.url_reset_password, codes)
        self.assert_mail_content(m, {'to': [user.email],
                                     'subject': self.mail_subject,
                                     'body': self.mail_body.format(**params),
                                     'from_email': self.mail_from or settings.DEFAULT_FROM_EMAIL})

    def check_after_password_change_request(self, params):
        pass

    def check_after_password_change(self, params):
        pass

    def check_after_second_change(self, params):
        pass

    def get_codes(self, user):
        return (urlsafe_base64_encode(force_bytes(user.pk)),
                default_token_generator.make_token(user),)

    def get_login_name(self, user):
        return user.email

    def get_obj_for_edit(self):
        user = choice(self.get_obj_manager.all())
        self.username = self.get_login_name(user)
        return user

    def send_reset_password_request(self, params):
        return self.client.post(self.get_url(self.url_reset_password_request), params,
                                follow=True, **self.additional_params)

    def send_change_after_reset_password_request(self, codes, params):
        return self.client.post(self.get_url_for_negative(self.url_reset_password, codes),
                                params, follow=True, **self.additional_params)

    def test_request_reset_password_positive(self):
        """
        Request password change code
        """
        user = self.get_obj_for_edit()
        user.email = 'te~st@test.test'
        user.save()
        mail.outbox = []
        params = self.deepcopy(self.request_password_params)
        self.update_captcha_params(self.get_url(self.url_reset_password_request), params)
        params[self.field_username] = self.get_login_name(user)
        try:
            response = self.send_reset_password_request(params)
            self.assert_request_password_change_mail(locals())
            user.refresh_from_db()
            self.assertTrue(user.check_password(self.current_password), 'Password was changed after request code')
            self.check_after_password_change_request(locals())
        except Exception:
            self.errors_append()

    def test_request_reset_password_empty_required_negative(self):
        """
        Request password change code with empty required fields
        """
        for field in self.request_fields:
            params = self.deepcopy(self.request_password_params)
            self.update_captcha_params(self.get_url(self.url_reset_password_request), params)
            self.set_empty_value_for_field(params, field)
            try:
                response = self.send_reset_password_request(params)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message('required', field))
            except Exception:
                self.errors_append(text='For empty field %s' % field)

    def test_request_reset_password_without_required_negative(self):
        """
        Request password change code without required fields
        """
        for field in self.request_fields:
            params = self.deepcopy(self.request_password_params)
            self.update_captcha_params(self.get_url(self.url_reset_password_request), params)
            self.pop_field_from_params(params, field)
            try:
                response = self.send_reset_password_request(params)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message('required', field))
            except Exception:
                self.errors_append(text='Without field %s' % field)

    @only_with('username_is_email')
    def test_request_reset_password_negative(self):
        """
        Try reset password with wrong email value
        """
        for value in ('q', 'й', 'qwe@rty', 'qw@йц', '@qwe', 'qwe@'):
            params = self.deepcopy(self.request_password_params)
            self.update_captcha_params(self.get_url(self.url_reset_password_request), params)
            params[self.field_username] = value
            try:
                response = self.send_reset_password_request(params)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message('wrong_value_email', self.field_username))
            except Exception:
                self.errors_append(text='For email %s' % value)

    def test_request_reset_password_username_not_exists_wo_captcha_negative(self):
        """
        Try reset password by username that not exists. No any error messages in secure purposes
        """
        if self.with_captcha:
            self.skipTest('Other test for form with captcha')
        username = get_random_email_value(10)
        params = self.deepcopy(self.request_password_params)
        params[self.field_username] = username
        try:
            response = self.send_reset_password_request(params)
            self.assert_no_form_errors(response)
            self.assert_mail_count(mail.outbox, 0)
        except Exception:
            self.errors_append()

    @only_with('with_captcha')
    def test_request_reset_password_username_not_exists_with_captcha_negative(self):
        """
        Try reset password by username that not exists.
        """
        username = get_random_email_value(10)
        params = self.deepcopy(self.request_password_params)
        self.update_captcha_params(self.get_url(self.url_reset_password_request), params)
        params[self.field_username] = username
        try:
            response = self.send_reset_password_request(params)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('user_not_exists', self.field_username))
            self.assert_mail_count(mail.outbox, 0)
        except Exception:
            self.errors_append()

    def test_request_reset_password_inactive_user_wo_captcha_negative(self):
        """
        Try reset password as inactive user. No any error messages in secure purposes
        """
        if self.with_captcha:
            self.skipTest('Other test for form with captcha')
        user = self.get_obj_for_edit()
        user.is_active = False
        user.save()
        params = self.deepcopy(self.request_password_params)
        params[self.field_username] = self.get_login_name(user)
        try:
            response = self.send_reset_password_request(params)
            self.assert_no_form_errors(response)
            self.assert_mail_count(mail.outbox, 0)
        except Exception:
            self.errors_append()

    @only_with('with_captcha')
    def test_request_reset_password_inactive_user_with_captcha_negative(self):
        """
        Try reset password as inactive user.
        """
        user = self.get_obj_for_edit()
        user.is_active = False
        user.save()
        params = self.deepcopy(self.request_password_params)
        self.update_captcha_params(self.get_url(self.url_reset_password_request), params)
        params[self.field_username] = self.get_login_name(user)
        try:
            response = self.send_reset_password_request(params)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('inactive_user', self.field_username))
            self.assert_mail_count(mail.outbox, 0)
        except Exception:
            self.errors_append()

    @only_with('with_captcha')
    def test_request_reset_password_wrong_captcha_negative(self):
        """
        Try reset password with wrong captcha value
        """
        for field in ('captcha_0', 'captcha_1'):
            for value in (u'йцу', u'\r', u'\n', u' ', ':'):
                user = self.get_obj_for_edit()
                mail.outbox = []
                params = self.deepcopy(self.request_password_params)
                self.update_captcha_params(self.get_url(self.url_reset_password_request), params)
                params[field] = value
                params[self.field_username] = self.get_login_name(user)
                try:
                    response = self.send_reset_password_request(params)
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message('wrong_captcha', 'captcha'))
                    self.assert_mail_count(mail.outbox, 0)
                except Exception:
                    self.errors_append()

    def test_reset_password_positive(self):
        """
        Reset password by link
        """
        for value in self.password_positive_values:
            user = self.get_obj_for_edit()
            params = self.deepcopy(self.password_params)
            params.update({self.field_password: value,
                           self.field_password_repeat: value})
            codes = self.get_codes(user)
            try:
                response = self.send_change_after_reset_password_request(codes, params)
                self.assert_no_form_errors(response)
                self.assert_mail_count(mail.outbox, 0)
                user.refresh_from_db()
                self.assertTrue(user.check_password(params[self.field_password]),
                                'Password not changed to "%s"' % params[self.field_password])
                self.check_after_password_change(locals())
            except Exception:
                self.errors_append(text='New password value "%s"' % value)

    def test_reset_password_twice_negative(self):
        """
        Try reset password twice by one link
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        value1 = self.get_value_for_field(None, 'password')
        params.update({self.field_password: value1,
                       self.field_password_repeat: value1})
        codes = self.get_codes(user)

        try:
            response = self.send_change_after_reset_password_request(codes, params)
            self.assert_no_form_errors(response)
            value2 = self.get_value_for_field(None, 'password')
            params.update({self.field_password: value2,
                           self.field_password_repeat: value2})

            response = self.send_change_after_reset_password_request(codes, params)
            self.assertFalse(self.get_obj_manager.get(pk=user.pk).check_password(value2),
                             'Password was changed twice by one link')
            self.check_after_second_change(locals())
        except Exception:
            self.errors_append()

    def test_reset_password_empty_required_negative(self):
        """
        Try change password with empty required fields
        """
        for field in self.change_fields:
            user = self.get_obj_for_edit()
            user.set_password(self.current_password)
            user.save()
            params = self.deepcopy(self.password_params)
            self.set_empty_value_for_field(params, field)
            codes = self.get_codes(user)
            user.refresh_from_db()
            try:
                response = self.send_change_after_reset_password_request(codes, params)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message('required', field))
                new_user = self.get_obj_manager.get(pk=user.pk)
                self.assert_objects_equal(new_user, user)
            except Exception:
                self.errors_append(text='For empty field %s' % field)

    def test_reset_password_without_required_negative(self):
        """
        Try change password without required fields
        """
        for field in self.change_fields:
            user = self.get_obj_for_edit()
            user.set_password(self.current_password)
            user.save()
            params = self.deepcopy(self.password_params)
            self.pop_field_from_params(params, field)
            codes = self.get_codes(user)
            user.refresh_from_db()
            try:
                response = self.send_change_after_reset_password_request(codes, params)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message('required', field))
                new_user = self.get_obj_manager.get(pk=user.pk)
                self.assert_objects_equal(new_user, user)
            except Exception:
                self.errors_append(text='For empty field %s' % field)

    def test_reset_password_different_new_passwords_negative(self):
        """
        Try change password: different password and repeat password values
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        params.update({self.field_password: self.get_value_for_field(None, 'password'),
                       self.field_password_repeat: self.get_value_for_field(9, 'password'), })
        codes = self.get_codes(user)
        user.refresh_from_db()
        try:
            response = self.send_change_after_reset_password_request(codes, params)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assert_objects_equal(new_user, user)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('wrong_password_repeat', self.field_password_repeat))
        except Exception:
            self.errors_append(text='New passwords "%s", "%s"' %
                               (params[self.field_password], params[self.field_password_repeat]))

    @only_with('password_min_length')
    def test_reset_password_length_lt_min_negative(self):
        """
        Try change password with length < password_min_length
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        length = self.password_min_length
        current_length = length - 1
        value = self.get_value_for_field(current_length, 'password')
        params.update({self.field_password: value,
                       self.field_password_repeat: value})
        codes = self.get_codes(user)
        user.refresh_from_db()
        try:
            response = self.send_change_after_reset_password_request(codes, params)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assert_objects_equal(new_user, user)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('min_length', self.field_password))
        except Exception:
            self.errors_append(text='New password "%s"' % params[self.field_password])

    @only_with('password_min_length')
    def test_reset_password_min_length_positive(self):
        """
        Change password with length = password_min_length
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        value = self.get_value_for_field(self.password_min_length, 'password')
        params.update({self.field_password: value,
                       self.field_password_repeat: value})
        codes = self.get_codes(user)
        try:
            response = self.send_change_after_reset_password_request(codes, params)
            self.assert_no_form_errors(response)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assertFalse(new_user.check_password(self.current_password), 'Password not changed')
            self.assertTrue(new_user.check_password(params[self.field_password]),
                            'Password not changed to "%s"' % params[self.field_password])
            self.check_after_password_change(locals())
        except Exception:
            self.errors_append(text='New password "%s"' % params[self.field_password])

    @only_with('password_max_length')
    def test_reset_password_length_gt_max_negative(self):
        """
        Try change password with length > password_max_length
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        length = self.password_max_length
        current_length = length + 1
        value = self.get_value_for_field(current_length, 'password')
        params.update({self.field_password: value,
                       self.field_password_repeat: value})
        codes = self.get_codes(user)
        user.refresh_from_db()
        try:
            response = self.send_change_after_reset_password_request(codes, params)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assert_objects_equal(new_user, user)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('max_length', self.field_password))
        except Exception:
            self.errors_append(text='New password "%s"' % params[self.field_password])

    @only_with('password_max_length')
    def test_reset_password_max_length_positive(self):
        """
        Change password with length = password_max_length
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        value = self.get_value_for_field(self.password_max_length, 'password')
        params.update({self.field_password: value,
                       self.field_password_repeat: value})
        codes = self.get_codes(user)
        try:
            response = self.send_change_after_reset_password_request(codes, params)
            self.assert_no_form_errors(response)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assertFalse(new_user.check_password(self.current_password), 'Password not changed')
            self.assertTrue(new_user.check_password(params[self.field_password]),
                            'Password not changed to "%s"' % params[self.field_password])
            self.check_after_password_change(locals())
        except Exception:
            self.errors_append(text='New password "%s"' % params[self.field_password])

    @only_with('password_wrong_values')
    def test_reset_password_wrong_value_negative(self):
        """
        Try change password to wrong value
        """
        for value in self.password_wrong_values:
            user = self.get_obj_for_edit()
            params = self.deepcopy(self.password_params)
            params.update({self.field_password: value,
                           self.field_password_repeat: value})
            codes = self.get_codes(user)
            user.refresh_from_db()
            try:
                response = self.send_change_after_reset_password_request(codes, params)
                new_user = self.get_obj_manager.get(pk=user.pk)
                self.assert_objects_equal(new_user, user)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message('wrong_value', self.field_password))
            except Exception:
                self.errors_append(text='New password "%s"' % value)

    def test_reset_password_by_get_positive(self):
        """
        Check password changes only after POST, not GET request
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        codes = self.get_codes(user)
        user.refresh_from_db()
        try:
            response = self.client.get(self.get_url(self.url_reset_password, codes),
                                       params, follow=True, **self.additional_params)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assert_objects_equal(new_user, user)
        except Exception:
            self.errors_append()

    def test_reset_password_inactive_user_negative(self):
        """
        Try reset password as inactive user
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        user.is_active = False
        user.save()
        codes = self.get_codes(user)
        user.refresh_from_db()
        try:
            response = self.send_change_after_reset_password_request(codes, params)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assert_objects_equal(new_user, user)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('inactive_user', self.field_password))
        except Exception:
            self.errors_append()

    @only_with('code_lifedays')
    def test_reset_password_expired_code_negative(self):
        """
        Try reset password by old link
        """
        user = self.get_obj_for_edit()
        old_date = datetime.now() - timedelta(days=self.code_lifedays + 1)
        with freeze_time(old_date):
            codes = self.get_codes(user)
        try:
            response = self.send_change_after_reset_password_request(codes, self.password_params)
            self.assertEqual(response.status_code, 404)
        except Exception:
            self.errors_append()

    @only_with('code_lifedays')
    def test_reset_password_last_day_code_life_positive(self):
        """
        Reset password before code expired
        """
        user = self.get_obj_for_edit()
        now = datetime.now()
        old_date = datetime.now() - timedelta(days=self.code_lifedays)
        params = self.deepcopy(self.password_params)
        with freeze_time(old_date):
            codes = self.get_codes(user)
        try:
            with freeze_time(now):
                response = self.send_change_after_reset_password_request(codes, params)
            self.assert_no_form_errors(response)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assertFalse(new_user.check_password(self.current_password), 'Password not changed')
            self.assertTrue(new_user.check_password(params[self.field_password]),
                            'Password not changed to "%s"' % params[self.field_password])
            self.check_after_password_change(locals())
        except Exception:
            self.errors_append()

    @only_with('password_similar_fields')
    def test_reset_password_value_similar_to_user_field_negative(self):
        """
        Try reset password to value similar to field from object
        """

        def new_value(value, change_type):
            if change_type == '':
                return value
            if change_type == 'swapcase':
                return value.swapcase()
            if change_type == 'add_before':
                return get_randname(1, 'w') + value
            if change_type == 'add_after':
                return value + get_randname(1, 'w')

        for field in self.password_similar_fields:
            user_field_name = getattr(self.get_field_by_name(self.obj, field), 'verbose_name', field)
            for change_type in ('', 'swapcase', 'add_before', 'add_after'):
                user = self.get_obj_for_edit()
                value = self.get_value_for_field(self.password_min_length, field)
                self.get_obj_manager.filter(pk=user.pk).update(**{field: value})
                password_value = new_value(value, change_type)
                user.refresh_from_db()
                params = self.deepcopy(self.password_params)

                self.update_params(params)
                params.update({self.field_password: password_value,
                               self.field_password_repeat: password_value})
                codes = self.get_codes(user)
                user.refresh_from_db()
                try:
                    response = self.send_change_after_reset_password_request(codes, params)
                    new_user = self.get_obj_manager.get(pk=user.pk)
                    self.assert_objects_equal(new_user, user)
                    error_message = self.get_error_message(
                        'wrong_password_similar', self.field_password, locals=locals())
                    self.assertEqual(self.get_all_form_errors(response), error_message)
                except Exception:
                    self.errors_append(text='New password value "%s" is similar to user.%s = "%s"' %
                                       (password_value, field, value))


class LoginTestMixIn(object):

    blacklist_model = None
    login_retries = None
    default_params = None
    field_password = 'password'
    field_username = 'username'
    password = 'qwerty'
    passwords_for_check = []
    obj = None
    username = None
    url_login = ''
    url_redirect_to = ''
    urls_for_redirect = ['/', ]

    def __init__(self, *args, **kwargs):
        super(LoginTestMixIn, self).__init__(*args, **kwargs)
        if self.default_params is None:
            self.default_params = {self.field_username: self.username,
                                   self.field_password: self.password}
        self.passwords_for_check = self.passwords_for_check or [self.password, ]
        if self.login_retries and self.login_retries < 2:
            self.login_retries = None

    def add_csrf(self, params):
        response = self.client.get(self.get_url(self.url_login), follow=True, **self.additional_params)
        params['csrfmiddlewaretoken'] = response.cookies[settings.CSRF_COOKIE_NAME].value

    def check_blacklist_on_positive(self):
        if self.blacklist_model:
            self.assertEqual(self.blacklist_model.objects.filter(host='127.0.0.1').count(), 0,
                             '%s blacklist objects created after valid login' % self.blacklist_model.objects.filter(host='127.0.0.1').count())

    def check_blacklist_on_negative(self, response, captcha_on_form=True):
        # TODO: login_retries
        if self.blacklist_model:
            self.assertEqual(self.blacklist_model.objects.filter(host='127.0.0.1').count(), 1,
                             '%s blacklist objects created after invalid login, expected 1' %
                             self.blacklist_model.objects.filter(host='127.0.0.1').count())
            fields = self.get_fields_list_from_response(response)['all_fields']
            if captcha_on_form:
                self.assertTrue('captcha' in fields, 'No captcha fields on form')
            else:
                self.assertFalse('captcha' in fields, 'Captcha fields on form')

    def check_is_authenticated(self):
        request = HttpRequest()
        request.session = self.client.session
        if callable(get_user(request).is_authenticated):
            self.assertTrue(get_user(request).is_authenticated())
        else:
            self.assertTrue(get_user(request).is_authenticated)

    def check_is_not_authenticated(self):
        request = HttpRequest()
        request.session = self.client.session
        if callable(get_user(request).is_authenticated):
            self.assertFalse(get_user(request).is_authenticated())
        else:
            self.assertFalse(get_user(request).is_authenticated)

    def check_response_on_positive(self, response):
        if self.url_redirect_to:
            urls_redirect_to = self.url_redirect_to
            if not isinstance(self.url_redirect_to, (list, tuple)):
                urls_redirect_to = [self.url_redirect_to, ]

            expected_redirects = [(self.get_domain() + self.get_url(url), 302) for url in urls_redirect_to]
            self.assertEqual(response.redirect_chain, expected_redirects,
                             'Recieved redirects:\n%s\n\nExpected redirects:\n%s' %
                             ('\n'.join(['%s (status %s)' % el for el in response.redirect_chain]),
                              '\n'.join(['%s (status %s)' % el for el in expected_redirects])))
            self.assertEqual(response.status_code, 200, "Final response code was %d (expected 200)" %
                             response.status_code)
        else:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.redirect_chain, [])

    def check_response_on_negative(self, response):
        pass

    def clean_blacklist(self):
        if self.blacklist_model:
            self.blacklist_model.objects.all().delete()

    def get_domain(self):
        return 'http://%s' % self.additional_params.get('HTTP_HOST', 'testserver')

    def get_user(self, username=None):
        username = username or self.username
        return self.get_obj_manager.get(email=username)

    def send_login_request(self, params, get_params=None):
        get_params = urlencode(get_params or {})
        if get_params:
            get_params = '?' + get_params
        return self.client.post(self.get_url(self.url_login) + get_params, params,
                                follow=True, **self.additional_params)

    def set_host_blacklist(self, host, count=None):
        if count is None:
            count = self.login_retries or 1
        if count > 1:
            self.blacklist_model.objects.create(host=host, count=count)
        elif count == 1:
            self.blacklist_model.objects.create(host=host)

    def set_host_pre_blacklist(self, host):
        if self.login_retries:
            self.set_host_blacklist(host=host, count=self.login_retries - 1)

    def set_user_inactive(self, user):
        user.is_active = False
        user.save()

    def update_captcha_params(self, url, params, *args, **kwargs):
        self.client.get(url, **self.additional_params)
        params.update(get_captcha_codes())

    def test_login_positive(self):
        """
        login with valid login and password
        """
        for value in self.passwords_for_check:
            self.client = self.client_class()
            user = self.get_user()
            user.set_password(value)
            user.save()
            params = self.deepcopy(self.default_params)
            params[self.field_password] = value
            self.add_csrf(params)
            self.clean_blacklist()
            try:
                response = self.send_login_request(params)
                self.assert_no_form_errors(response)
                self.check_is_authenticated()
                self.check_response_on_positive(response)
                self.check_blacklist_on_positive()
            except Exception:
                self.errors_append(text='User with password "%s"' % value)

    def test_login_wrong_password_negative(self):
        """
        login with invalid password
        """
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        params[self.field_password] = self.password + 'q'
        self.set_host_pre_blacklist(host='127.0.0.1')
        try:
            response = self.send_login_request(params)
            message = self.get_error_message('wrong_login', self.field_username)
            self.assertEqual(self.get_all_form_errors(response), message)
            self.check_is_not_authenticated()
            self.check_response_on_negative(response)
            self.check_blacklist_on_negative(response)
        except Exception:
            self.errors_append()

    def test_login_wrong_login_negative(self):
        """
        login as not existing user
        """
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        params[self.field_username] = self.username + 'q'
        self.set_host_pre_blacklist(host='127.0.0.1')
        try:
            response = self.send_login_request(params)
            message = self.get_error_message('wrong_login', self.field_username)
            self.assertEqual(self.get_all_form_errors(response), message)
            self.check_response_on_negative(response)
            self.check_blacklist_on_negative(response)
        except Exception:
            self.errors_append()

    @only_with('login_retries')
    def test_login_wrong_login_not_max_retries_negative(self):
        """
        login as not existing user. No captcha field: not max retries
        """
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        params[self.field_username] = self.username + 'q'
        self.clean_blacklist()
        self.set_host_blacklist(host='127.0.0.1', count=self.login_retries - 2)
        try:
            response = self.send_login_request(params)
            message = self.get_error_message('wrong_login', self.field_username)
            self.assertEqual(self.get_all_form_errors(response), message)
            self.check_response_on_negative(response)
            self.check_blacklist_on_negative(response, False)
        except Exception:
            self.errors_append()

    @only_with('blacklist_model')
    def test_login_blacklist_user_positive(self):
        """
        login as user from blacklist with correct data
        """
        self.set_host_blacklist(host='127.0.0.1')
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        try:
            response = self.client.get(self.get_url(self.url_login), follow=True, **self.additional_params)
            fields = self.get_fields_list_from_response(response)['all_fields']
            self.assertTrue('captcha' in fields)
            self.update_captcha_params(self.get_url(self.url_login), params)
            response = self.send_login_request(params)
            self.check_is_authenticated()
            self.check_response_on_positive(response)
            self.assertEqual(self.blacklist_model.objects.filter(host='127.0.0.1').count(), 0,
                             'Blacklist object not deleted after successful login')
        except Exception:
            self.errors_append()

    @only_with('blacklist_model')
    def test_login_blacklist_user_empty_captcha_negative(self):
        """
        login as user from blacklist with empty captcha
        """
        self.set_host_blacklist(host='127.0.0.1')
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        try:
            self.update_captcha_params(self.get_url(self.url_login), params)
            params['captcha_1'] = ''
            response = self.send_login_request(params)

            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('empty_required', 'captcha'))
            self.check_is_not_authenticated()
            self.check_response_on_negative(response)
            self.check_blacklist_on_negative(response)
        except Exception:
            self.errors_append()

    @only_with('blacklist_model')
    def test_login_blacklist_user_wrong_captcha_negative(self):
        """
        login as user from blacklist with wrong captcha
        """
        for field in ('captcha_0', 'captcha_1'):
            for value in (u'йцу', u'\r', u'\n', u' ', ':'):
                self.client = self.client_class()
                self.clean_blacklist()
                self.set_host_blacklist(host='127.0.0.1')
                params = self.deepcopy(self.default_params)
                self.add_csrf(params)
                self.update_captcha_params(self.get_url(self.url_login), params)
                params[field] = value
                try:
                    response = self.send_login_request(params)
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message('wrong_captcha', 'captcha'))
                    self.check_is_not_authenticated()
                    self.check_response_on_negative(response)
                    self.check_blacklist_on_negative(response)
                except Exception:
                    self.errors_append(text='For field %s value %s' % (field, repr(value)))

    def test_login_inactive_user_negative(self):
        """
        login as inactive user
        """
        user = self.get_user()
        self.set_user_inactive(user)
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        try:
            response = self.send_login_request(params)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('inactive_user', self.field_username))
            self.check_is_not_authenticated()
            self.check_response_on_negative(response)
            self.check_blacklist_on_positive()
        except Exception:
            self.errors_append()

    def test_login_wrong_password_inactive_user_negative(self):
        """
        login as inactive user with invalid password
        """
        user = self.get_user()
        self.set_user_inactive(user)
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        params[self.field_password] = self.password + 'q'
        self.set_host_pre_blacklist(host='127.0.0.1')
        try:
            response = self.send_login_request(params)
            message = self.get_error_message('wrong_login', self.field_username)
            self.assertEqual(self.get_all_form_errors(response), message)
            self.check_is_not_authenticated()
            self.check_response_on_negative(response)
            self.check_blacklist_on_negative(response)
        except Exception:
            self.errors_append()

    def test_login_empty_fields_negative(self):
        """
        login with empty fields
        """
        _params = self.deepcopy(self.default_params)
        for field in (self.field_password, self.field_username):
            self.client = self.client_class()
            params = self.deepcopy(_params)
            self.add_csrf(params)
            self.set_empty_value_for_field(params, field)
            self.clean_blacklist()
            self.set_host_pre_blacklist(host='127.0.0.1')
            try:
                response = self.send_login_request(params)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message('empty_required', field))
                self.check_is_not_authenticated()
                self.check_response_on_negative(response)
                self.check_blacklist_on_negative(response)
            except Exception:
                self.errors_append(text="For empty field %s" % field)

    def test_login_without_fields_negative(self):
        """
        login without required fields
        """
        _params = self.deepcopy(self.default_params)
        for field in (self.field_password, self.field_username):
            self.client = self.client_class()
            params = self.deepcopy(_params)
            self.add_csrf(params)
            self.pop_field_from_params(params, field)
            self.clean_blacklist()
            self.set_host_pre_blacklist(host='127.0.0.1')
            try:
                response = self.send_login_request(params)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message('without_required', field))
                self.check_is_not_authenticated()
                self.check_response_on_negative(response)
                self.check_blacklist_on_negative(response)
            except Exception:
                self.errors_append(text="For empty field %s" % field)

    @only_with('urls_for_redirect')
    def test_login_with_redirect_positive(self):
        """
        login with next GET param
        """
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        next_url = self.get_url(choice(self.urls_for_redirect))
        try:
            response = self.send_login_request(params, {'next': next_url})
            self.check_is_authenticated()
            self.assertRedirects(response, self.get_domain() + next_url)
            self.check_blacklist_on_positive()
        except Exception:
            self.errors_append()

    @only_with('urls_for_redirect')
    def test_login_with_redirect_with_host_positive(self):
        """
        login with next GET param
        """
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        next_url = self.get_url(choice(self.urls_for_redirect))
        try:
            redirect_url = self.get_domain() + next_url
            response = response = self.send_login_request(params, {'next': redirect_url})
            self.check_is_authenticated()
            self.assertRedirects(response, redirect_url)
            self.check_blacklist_on_positive()
        except Exception:
            self.errors_append()

    def test_login_with_redirect_with_host_negative(self):
        """
        login with next GET param (redirect to other host)
        """
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        urls_redirect_to = self.url_redirect_to
        if not isinstance(self.url_redirect_to, (list, tuple)):
            urls_redirect_to = [self.url_redirect_to, ]
        expected_redirects = [(self.get_domain() + self.get_url(url), 302) for url in urls_redirect_to]
        try:
            redirect_url = 'http://google.com'
            response = response = self.send_login_request(params, {'next': redirect_url})
            self.check_is_authenticated()
            self.check_blacklist_on_positive()
            self.assertEqual(response.redirect_chain, expected_redirects)
        except Exception:
            self.errors_append()

    def test_open_login_page_already_logged_positive(self):
        """
        redirect from login page if already authenticated
        """
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        self.client.post(self.get_url(self.url_login), params, follow=True, **self.additional_params)
        try:
            response = self.client.get(self.get_url(self.url_login), follow=True, **self.additional_params)
            self.check_is_authenticated()
            self.check_blacklist_on_positive()
            self.check_response_on_positive(response)
        except Exception:
            self.errors_append()


base_db_initialized = False


class CustomTestCase(GlobalTestMixIn, TransactionTestCase):

    multi_db = True
    request_manager = RequestManager

    def _fixture_setup(self):

        databases = self._databases_names(include_mirrors=False)
        global base_db_initialized
        if not base_db_initialized:
            base_db_initialized = True
            for db in databases:
                call_command('flush', verbosity=0, interactive=False, database=db)

                if getattr(self, 'fixtures', None):
                    # We have to use this slightly awkward syntax due to the fact
                    # that we're using *args and **kwargs together.
                    call_command('loaddata', *self.fixtures,
                                 **{'verbosity': 0, 'database': db})

        databases = self._databases_names(include_mirrors=True)
        for db in databases:
            conn = connections[db]
            db_name = conn.settings_dict['NAME'].strip('_')
            if not conn.settings_dict.get('TEST', {}).get('MIRROR', False):
                cursor = conn.cursor()
                conn.connection.rollback()
                conn.connection.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                try:
                    cursor.execute('CREATE DATABASE "%s" WITH TEMPLATE="%s"' % (db_name + '_', db_name))
                except Exception:
                    cursor.execute('DROP DATABASE "%s"' % (db_name + '_'))
                    cursor.execute('CREATE DATABASE "%s" WITH TEMPLATE="%s"' % (db_name + '_', db_name))
            conn.close()
            conn.settings_dict['NAME'] = db_name + '_'

    def _fixture_teardown(self):
        if not connections_support_transactions():
            return super(TransactionTestCase, self)._fixture_teardown()

        for db in self._databases_names(include_mirrors=True):
            conn = connections[db]
            db_name = conn.settings_dict['NAME']
            conn.settings_dict['NAME'] = db_name.strip('_')
            conn.close()

        for db in self._databases_names(include_mirrors=False):
            conn = connections[db]
            db_name = conn.settings_dict['NAME']
            cursor = conn.cursor()
            conn.connection.rollback()
            conn.connection.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            is_old_postgres = cursor.connection.server_version < 90200  # < 9.2.0
            pid_name = 'procpid' if is_old_postgres else 'pid'
            disconnect_sql = '''SELECT pg_terminate_backend(pg_stat_activity.{0})
                            FROM pg_stat_activity
                            WHERE pg_stat_activity.datname = %s
                              AND {0} <> pg_backend_pid();'''.format(pid_name)
            cursor.execute(disconnect_sql, (db_name + '_',))
            cursor.execute('DROP DATABASE "%s";' % (db_name + '_',))

    def _post_teardown(self):
        self.custom_fixture_teardown()
        super(CustomTestCase, self)._post_teardown()

    def _pre_setup(self):
        if getattr(settings, 'TEST_CASE_NAME', '') != self.__class__.__name__:
            settings.TEST_CASE_NAME = self.__class__.__name__
            global base_db_initialized
            base_db_initialized = False
        ContentType.objects.clear_cache()
        self.custom_fixture_setup()
        super(CustomTestCase, self)._pre_setup()

    def custom_fixture_setup(self, **options):
        verbosity = int(options.get('verbosity', 1))
        for db in self._databases_names(include_mirrors=False):
            if hasattr(self, 'fixtures_for_custom_db') and not base_db_initialized:
                fixtures = [fixture for fixture in self.fixtures_for_custom_db if fixture.endswith(db + '.json')]

                sequence_sql = []
                for fixture in fixtures:
                    data = get_fixtures_data(fixture)
                    sql = generate_sql(data)
                    cursor = connections[db].cursor()
                    try:
                        cursor.execute(sql)
                    except Exception as e:
                        sys.stderr.write("Failed to load fixtures for alias '%s': %s" % (db, force_text(e)))
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
        for db in self._databases_names(include_mirrors=False):
            if hasattr(self, 'fixtures_for_custom_db') and db != DEFAULT_DB_ALIAS:
                cursor = connections[db].cursor()
                cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
                tables = cursor.fetchall()
                for table in tables:
                    try:
                        cursor.execute("DELETE FROM %s" % table)
                    except Exception:
                        transaction.rollback_unless_managed(using=db)
                    else:
                        transaction.commit_unless_managed(using=db)

    def get_model(self, table_name, db_name=None):
        if not db_name:
            db_names = [db for db in connections if db != DEFAULT_DB_ALIAS]
            if db_names:
                db_name = db_names[0]
        cursor = connections[db_name].cursor()
        cursor.execute("SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS WHERE table_name=%s", [table_name])
        column_names = [el[0] for el in cursor.fetchall()]
        cursor.execute("""SELECT kcu.column_name FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                          LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                          ON kcu.table_name = tc.table_name
                                AND kcu.constraint_name = tc.constraint_name
                          WHERE tc.table_name = %s AND tc.constraint_type='PRIMARY KEY'""", [table_name])
        pk_names = [el[0] for el in cursor.fetchall()]

        model = apps.get_app_config('ttoolly').models.get(table_name)
        if model:
            return model

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

    @classmethod
    def tearDownClass(cls):
        """TransactionTestCase._fixture_teardown"""
        for db_name in cls._databases_names(include_mirrors=False):
            # Flush the database
            call_command('flush', verbosity=0, interactive=False,
                         database=db_name, reset_sequences=False,
                         allow_cascade=cls.available_apps is not None,
                         inhibit_post_migrate=cls.available_apps is not None)
        cls.custom_fixture_teardown()
        super(CustomTestCaseNew, cls).tearDownClass()

    @classmethod
    def setUpClass(cls):
        super(CustomTestCaseNew, cls).setUpClass()

        """Version sensitive import"""
        from django.apps import apps

        """load fixtures to main database once"""

        for db in cls._databases_names(include_mirrors=False):
            if cls.reset_sequences:
                cls._reset_sequences(db)

            # If we need to provide replica initial data from migrated apps,
            # then do so.
            if cls.serialized_rollback and hasattr(connections[db], "_test_serialized_contents"):
                if cls.available_apps is not None:
                    apps.unset_available_apps()
                connections[db].creation.deserialize_db_from_string(
                    connections[db]._test_serialized_contents
                )
                if cls.available_apps is not None:
                    apps.set_available_apps(cls.available_apps)

            if cls.fixtures:
                # Django loadddata with multi_db fails on deserialize objects with natural keys for not default fixture
                fixtures = [fixture for fixture in cls.fixtures if db == DEFAULT_DB_ALIAS or ('.' + db) in fixture]
                if fixtures:
                    call_command('loaddata', *fixtures, **{'verbosity': 0, 'database': db})

        cls.custom_fixture_setup()

    def _fixture_setup(self):
        """only copy from main database"""
        databases = self._databases_names(include_mirrors=True)

        for db in databases:
            conn = connections[db]
            db_name = conn.settings_dict['NAME'].strip('_')
            if not conn.settings_dict.get('TEST', {}).get('MIRROR', False):
                cursor = conn.cursor()
                conn.connection.rollback()
                conn.connection.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                try:
                    cursor.execute('CREATE DATABASE "%s" WITH TEMPLATE="%s"' % (db_name + '_', db_name))
                except Exception:
                    cursor.execute('DROP DATABASE "%s"' % (db_name + '_'))
                    cursor.execute('CREATE DATABASE "%s" WITH TEMPLATE="%s"' % (db_name + '_', db_name))
            conn.close()
            conn.settings_dict['NAME'] = db_name + '_'

    def _post_teardown(self):
        super(CustomTestCase, self)._post_teardown()

    def _pre_setup(self):
        super(CustomTestCase, self)._pre_setup()

    @classmethod
    def custom_fixture_setup(cls, **options):
        verbosity = int(options.get('verbosity', 1))
        for db in cls._databases_names(include_mirrors=False):
            if hasattr(cls, 'fixtures_for_custom_db'):
                fixtures = [fixture for fixture in cls.fixtures_for_custom_db if fixture.endswith(db + '.json')]

                sequence_sql = []
                for fixture in fixtures:
                    data = get_fixtures_data(fixture)
                    sql = generate_sql(data)
                    cursor = connections[db].cursor()
                    with transaction.atomic(using=db):
                        try:
                            cursor.execute(sql)
                        except Exception as e:
                            sys.stderr.write("Failed to load fixtures for alias '%s': %s" % (db, force_text(e)))

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

    @classmethod
    def custom_fixture_teardown(cls):

        if hasattr(cls, 'fixtures_for_custom_db'):
            for db in cls._databases_names(include_mirrors=False):
                fixtures = [fixture for fixture in cls.fixtures_for_custom_db if fixture.endswith(db + '.json')]
                if fixtures:
                    cursor = connections[db].cursor()
                    cursor.execute("SELECT table_name FROM information_schema.tables "
                                   "WHERE table_schema='public' and table_name != 'django_migrations'")
                    tables = cursor.fetchall()
                    for table in tables:
                        with transaction.atomic(using=db):
                            cursor.execute("DELETE FROM %s" % table)
