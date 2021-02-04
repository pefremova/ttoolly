# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

from copy import copy, deepcopy
from datetime import datetime, date, time
from decimal import Decimal
import inspect
import json
import os
from random import choice, randint, uniform
import re
from shutil import rmtree
import sys
import tempfile
from unittest.util import strclass
import warnings

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
from django.http import HttpRequest
from django.template.defaultfilters import filesizeformat
from django.test import TransactionTestCase, TestCase
from django.test.testcases import connections_support_transactions
from django.test.utils import override_settings
from django.utils.encoding import force_text, force_bytes
from django.utils.http import urlsafe_base64_encode
from lxml.html import document_fromstring
import psycopg2.extensions

from builtins import str
from freezegun import freeze_time
from future.utils import viewitems, viewkeys, viewvalues, with_metaclass
from past.builtins import xrange, basestring
from uuid import UUID

from .testcases import (AddNegativeCases, AddPositiveCases, EditPositiveCases, EditNegativeCases,
                        ListNegativeCases, ListPositiveCases,
                        DeletePositiveCases, DeleteNegativeCases, RemovePositiveCases,
                        RemoveNegativeCases, ResetPasswordPositiveCases,
                        ResetPasswordNegativeCases,
                        ChangePasswordPositiveCases,
                        ChangePasswordNegativeCases, LoginPositiveCases,
                        LoginNegativeCases)
from .utils import (format_errors, get_error, get_randname, get_url_for_negative, get_url, get_captcha_codes,
                    get_random_email_value, get_fixtures_data, generate_sql, unicode_to_readable,
                    get_fields_list_from_response, get_real_fields_list_from_response, get_all_form_errors,
                    generate_random_obj, get_all_urls, prepare_custom_file_for_tests,
                    get_random_file, get_all_field_names_from_model, FILE_TYPES)
from .utils.decorators import only_with, only_with_obj, only_with_any_files_params, only_with_files_params


if sys.version[0] == '2':
    from functools32 import wraps
    from urllib import urlencode
else:
    from functools import wraps
    from urllib.parse import urlencode

try:
    from django.core.urlresolvers import reverse, resolve
except ImportError:
    # Django 2.0
    from django.urls import reverse, resolve

try:
    from django.db.models.fields import FieldDoesNotExist
except ImportError:
    # Django 3.1+
    from django.core.exceptions import FieldDoesNotExist


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

    TEST_USE_REAL_SETTINGS = getattr(settings, 'TEST_USE_REAL_SETTINGS', False)

    def get_new_value(value):
        if isinstance(value, basestring) and value.startswith('redis://'):
            if TEST_USE_REAL_SETTINGS and _worker_id == 0:
                return value
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
            def tmp(self, *args, **kwargs):
                fn(self, *args, **kwargs)
                self.formatted_assert_errors()
            decorators = getattr(tmp, 'decorators', ())
            if not 'check_errors' in [getattr(d, '__name__', d.__class__.__name__) for d in decorators]:
                tmp.decorators = decorators + (check_errors,)
            return tmp

        def decorate(cls, bases, dct):
            for attr in cls.__dict__:
                if attr.startswith('test') and callable(getattr(cls, attr)) and \
                        'check_errors' not in [getattr(d, '__name__', d.__class__.__name__)
                                               for d in getattr(getattr(cls, attr), 'decorators', ())]:
                    setattr(cls, attr, check_errors(getattr(cls, attr)))
            bases = cls.__bases__
            for base in bases:
                decorate(base, base.__bases__, base.__dict__)
            return cls

        decorate(cls, bases, dct)
        super(MetaCheckFailures, cls).__init__(name, bases, dct)


class Ring(list):

    def __init__(self, l=None):
        self.__n = -1
        l = l or []
        super().__init__(l)

    def turn(self):
        self.__n = (self.__n + 1) if self.__n + 1 < len(self) else 0

    def get_and_turn(self):
        self.turn()
        return self[self.__n]


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
    unique_with_case = None
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
        if self.unique_with_case is None:
            self.unique_with_case = ()
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
        obj = getattr(self, 'obj', None)
        if obj == EmailLog:
            return obj.objects
        if obj:
            return obj._base_manager

    def for_post_tear_down(self):
        self.del_files()

        def get_settings_value(name, value=None):
            if name.isdigit():
                name = int(name)
            if not '.' in name:
                return value and value[name] or getattr(settings, name)
            else:
                name, others = name.split('.', 1)
                if name.isdigit():
                    name = int(name)
                if value:
                    value = value[name]
                else:
                    value = getattr(settings, name)
                return get_settings_value(others, value)

        for name in get_settings_for_move():
            path = get_settings_value(name)
            if path.startswith(tempfile.gettempdir()):
                filename, ext = os.path.splitext(os.path.basename(path))
                if ext:
                    path = os.path.dirname(path)
                rmtree(path)
        modified_settings = getattr(self, '_ttoolly_modified_settings', None)
        if modified_settings:
            modified_settings.disable()

    def for_pre_setup(self):
        self.errors = []
        d = new_redis_settings()

        def update_path(d, name):
            if not '.' in name:
                current = getattr(settings, name, '')
                filename, ext = os.path.splitext(os.path.basename(current))
                if ext:
                    d[name] = os.path.join(tempfile.mkdtemp('_' + name), filename + ext)
                else:
                    d[name] = tempfile.mkdtemp('_' + name)
            else:
                name, others = name.split('.', 1)
                if name.isdigit():
                    name = int(name)
                d[name] = d.get(name, None) or self.deepcopy(getattr(settings, name))
                update_path(d[name], others)

        if not getattr(settings, 'TEST_USE_REAL_SETTINGS', False):
            for name in get_settings_for_move():
                update_path(d, name)

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

    def assert_errors(self, response, error_message):
        self.assertEqual(self.get_all_form_errors(response), error_message)

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
            if getattr(m, 'content_subtype', None) in ('html', 'text/html'):
                self.assertHTMLEqual(m.body, default_params['body'])
            else:
                self.assert_text_equal_by_symbol(m.body, default_params['body'])
        except Exception:
            self.errors_append(errors, text='[body]')

        try:
            self.assertEqual(len(getattr(m, 'alternatives', [])), len(default_params['alternatives']),
                             '%s alternatives in mail, expected %s' %
                             (len(getattr(m, 'alternatives', [])),
                              len(default_params['alternatives'])))
            for n, alternative in enumerate(default_params['alternatives']):
                m_alternative = m.alternatives[n]
                if m_alternative[1] in ('html', 'text/html') and m.alternatives[n][1] in ('html', 'text/html'):
                    self.assertHTMLEqual(m_alternative[0], alternative[0])
                else:
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
        if mails is None:
            mails = mail.outbox
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
        object_fields = sum([[name, name + '_0', name + '_1']
                             if fields_map[name].__class__.__name__ == 'DateTimeField'
                             else [name, ] for name in object_fields], [])

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
                value = _model._base_manager.filter(**{obj_field_in_related_query + '__pk': obj.pk})
                if value:
                    value = value[0]
                else:
                    value = None
            else:
                value = self._get_field_value_by_name(obj, name_in_object)
            if (name_on_form in viewkeys(form_to_field_map) or name_in_field in viewkeys(field_to_form_map) and
                (hasattr(params.get(name_on_form, []), '__len__') and  # params value is list or not exists (inline form)
                 (value.__class__.__name__ in ('RelatedManager', 'QuerySet') or
                  set([mr.__name__ for mr in value.__class__.__mro__]).intersection(['Manager', 'Model', 'ModelBase'])))):

                if hasattr(params.get(name_on_form, None), '__len__'):
                    count_for_check = len(params[name_on_form])
                else:
                    count_for_check = params.get('%s-TOTAL_FORMS' % name_on_form, None)

                if value is not None:
                    if count_for_check is not None and value.__class__.__name__ in ('RelatedManager',
                                                                                    'ManyRelatedManager'):
                        try:
                            self.assertEqual(value.all().count(), count_for_check)
                        except Exception as e:
                            local_errors.append('[%s]: count ' % (field.encode('utf-8') if isinstance(field, str)
                                                                  else field) + force_text(e))

                    for i, el in enumerate(value.all().order_by('pk')
                                           if value.__class__.__name__ in ('RelatedManager', 'QuerySet',
                                                                           'ManyRelatedManager')
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
                            local_errors.append('[%s][%d]:%s' % (field.encode('utf-8') if isinstance(field, str)
                                                                 else field, i, '\n  '.join(force_text(e).splitlines())))
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

    def assert_status_code(self, response_status_code, expected_status_code):
        self.assertEqual(response_status_code, expected_status_code,
                         'Status code %s != %s' % (response_status_code, expected_status_code))

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

    def _get_field_value_by_name(self, obj, field):
        related_names_map = self.get_related_names(obj)
        field = related_names_map.get(re.sub('\-\d+\-', '-0-', field), field)

        if re.findall(r'[\w_]+\-\d+\-[\w_]+', field):
            model_name, index, field_name = field.split('-')
            qs = getattr(obj, related_names_map.get(model_name, model_name)).all().order_by('pk')
            if qs.count() > int(index):
                return getattr(qs[int(index)], field_name)
        else:
            if re.match('.+?_[01]$', field):
                value = getattr(obj, re.sub('_[01]$', '', field))
                if isinstance(value, datetime):
                    if field.endswith('_0'):
                        return value.astimezone().date()
                    if field.endswith('_1'):
                        return value.astimezone().time()
                return value
            return getattr(obj, field)

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
        if ((isinstance(value, date) or isinstance(value, time)) and
                not (isinstance(params_value, date) or isinstance(params_value, time))):

            if isinstance(value, datetime):
                format_str = getattr(settings, 'TEST_DATETIME_INPUT_FORMAT', settings.DATETIME_INPUT_FORMATS[0])
                value = value.strftime(format_str)
            elif isinstance(value, date):
                format_str = getattr(settings, 'TEST_DATE_INPUT_FORMAT', settings.DATE_INPUT_FORMATS[0])
                value = value.strftime(format_str)
            elif isinstance(value, time):
                format_str = getattr(settings, 'TEST_TIME_INPUT_FORMAT', settings.TIME_INPUT_FORMATS[0])
                value = value.strftime(format_str)
            return value, params_value

        if isinstance(value, models.Model) and not isinstance(params_value, models.Model):
            value = value.pk
            params_value = int(params_value) if (params_value and
                                                 isinstance(params_value, (str, bytes)) and
                                                 params_value.isdigit()) else params_value
        elif value.__class__.__name__ in ('ManyRelatedManager', 'GenericRelatedObjectManager'):
            value = [force_text(v) for v in value.values_list('pk', flat=True)]
            value.sort()
            value_iterator = getattr(params_value, '__iter__', None)
            if value_iterator:
                params_value = [force_text(pv) for pv in value_iterator()]
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

        if isinstance(value, UUID) and isinstance(params_value, (str, bytes)):
            value = force_text(value)

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
            value = getattr(obj, field)
        except (AttributeError, ValueError):
            return None

        if value.__class__.__name__ in ('ManyRelatedManager', 'RelatedManager',
                                        'GenericRelatedObjectManager'):
            value = [v for v in value.values_list('pk', flat=True).order_by('pk')]
        else:
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
            if field_name.endswith('_1'):
                return datetime.now().strftime(getattr(settings, 'TEST_TIME_INPUT_FORMAT',
                                                       settings.TIME_INPUT_FORMATS[0]))
            elif self.is_datetime_field(field_name):
                return datetime.now().strftime(getattr(settings, 'TEST_DATETIME_INPUT_FORMAT',
                                                       settings.DATETIME_INPUT_FORMATS[0]))
            else:
                return datetime.now().strftime(getattr(settings, 'TEST_DATE_INPUT_FORMAT',
                                                       settings.DATE_INPUT_FORMATS[0]))

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
            if key not in self.unique_with_case:
                existing_values = [el.lower() for el in existing_values]

            if default_value != '' and default_value is not None:
                while n < 3 and (force_text(params[key]).lower() if key not in
                                 self.unique_with_case else force_text(params[key])) in existing_values:
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
        update_captcha_params = getattr(self, 'update_captcha_params', None)
        if update_captcha_params:
            update_captcha_params(reverse(url_name), params, force=True)
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


class FormCommonMixIn(object):
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
    intervals = None  # ((field1, field2[, '>'|'>=']),)
    max_blocks = None
    max_fields_length = {}
    min_fields_length = {}
    multiselect_fields = None
    multiselect_fields_add = None
    multiselect_fields_edit = None
    one_of_fields = None
    one_of_fields_add = None
    one_of_fields_edit = None
    only_if_value = None
    required_fields = None
    required_fields_add = None
    required_fields_edit = None
    required_if = None
    required_if_add = None
    required_if_edit = None
    required_if_value = None
    status_code_error = 200
    status_code_not_exist = 404
    status_code_success_add = 200
    status_code_success_edit = 200
    unique_fields_add = None
    unique_fields_edit = None
    url_add = ''

    def __init__(self, *args, **kwargs):
        super(FormCommonMixIn, self).__init__(*args, **kwargs)
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
            self.with_captcha = ((self.all_fields and 'captcha' in self.all_fields)
                                 or (self.all_fields_add and 'captcha' in self.all_fields_add)
                                 or (self.all_fields_edit and 'captcha' in self.all_fields_edit))

        self._prepare_filter_params()
        self._prepare_date_fields()
        self._prepare_digital_fields()
        self._prepare_email_fields()
        self._prepare_intervals()
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
        self.date_fields = set(tuple(self.date_fields) + tuple(self.datetime_fields or ()))

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

    def _prepare_intervals(self):
        def prepare(interval):
            if len(interval) == 3:
                return interval
            return tuple(interval) + ('>',)

        if self.intervals is not None:
            self.intervals = (prepare(interval) for interval in self.intervals)

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

        if self.required_if_add is None:
            self.required_if_add = self.deepcopy(self.required_if or {})
        if self.required_if_edit is None:
            self.required_if_edit = self.deepcopy(self.required_if or {})

    def check_on_add_success(self, response, initial_obj_count, _locals):
        self.assert_no_form_errors(response)
        self.assert_status_code(response.status_code, self.status_code_success_add)
        self.assert_objects_count_on_add(True, initial_obj_count)

    def check_on_add_error(self, response, initial_obj_count, _locals):
        self.assert_objects_count_on_add(False, initial_obj_count)
        self.assert_status_code(response.status_code, self.status_code_error)

    def check_on_edit_success(self, response, _locals):
        self.assert_no_form_errors(response)
        self.assert_status_code(response.status_code, self.status_code_success_edit)

    def check_on_edit_error(self, response, obj_for_edit, _locals):
        new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
        self.assert_objects_equal(new_object, obj_for_edit)
        self.assert_status_code(response.status_code, self.status_code_error)

    def create_copy(self, obj_for_edit, fields_for_change=None):
        fields_for_change = fields_for_change or []
        fields_for_change = set(list(fields_for_change) +
                                [v for el in viewkeys(self.all_unique) for v in el
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
            while n < 3 and value == self._get_field_value_by_name(obj_for_edit, field):
                n += 1
                value = self.get_value_for_field(None, field)
                mro_names = [b.__name__ for b in field_class.__class__.__mro__]
                if 'DateField' in mro_names:
                    try:
                        value = datetime.strptime(value, getattr(settings, 'TEST_DATE_INPUT_FORMAT',
                                                                 settings.DATE_INPUT_FORMATS[0])).date()
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
                        params[field] = self.get_value_for_field(None, field)
                else:
                    params[field] = self.get_value_for_field(None, field)

    def fill_fields_from_obj(self, params, obj, fields):
        for field in [f for f in fields if not f.endswith('-DELETE')]:
            value = self._get_field_value_by_name(obj, field)
            if self.is_file_field(field) and value:
                if not os.path.exists(value.path):
                    prepare_custom_file_for_tests(value.path)
                params[field] = ContentFile(value.file.read(), os.path.basename(value.name))
            elif self.is_date_field(field):
                l = [re.findall('^%s_\d' % field, k) for k in viewkeys(params)]
                subfields = [item for sublist in l for item in sublist]
                if subfields:
                    for subfield in subfields:
                        params[subfield] = self.get_params_according_to_type(
                            self._get_field_value_by_name(obj, subfield), '')[0]
                else:
                    params[field] = self.get_params_according_to_type(value, '')[0]
            else:
                params[field] = self.get_params_according_to_type(value, '')[0]

    def fill_field(self, params, field_name, value):
        if self.is_datetime_field(field_name) and isinstance(value, datetime):
            params[
                field_name + '_0'] = value.strftime(getattr(settings, 'TEST_DATE_INPUT_FORMAT', settings.DATE_INPUT_FORMATS[0]))
            params[
                field_name + '_1'] = value.strftime(getattr(settings, 'TEST_TIME_INPUT_FORMAT', settings.TIME_INPUT_FORMATS[0]))
        else:
            param, _ = self.get_params_according_to_type(value, '')
            params[field_name] = value

    def fill_with_related(self, params, field, value):
        params[field] = value
        test_name = self.id()
        test_type = ''
        if 'test_add_' in test_name:
            test_type = '_add'
        elif 'test_edit_' in test_name:
            test_type = '_edit'

        related = (getattr(self, 'required_if' + test_type) or {}).get(field, ())
        for related_field in related if isinstance(related, (list, tuple)) else (related,):
            if params.get(related_field, None) in (None, ''):
                self.fill_with_related(params, related_field, self.get_value_for_field(None, related_field))

        getattr(self, 'clean_depend_fields' + test_type)(params, field)

        for related_field, lead_params in viewitems(self.only_if_value or {}):
            if (field in viewkeys(lead_params) and
                    lead_params != {k: v for k, v in viewitems(params) if k in viewkeys(lead_params)}):
                self.set_empty_value_for_field(params, related_field)

        for related_field, lead_params in viewitems(self.required_if_value or {}):
            if (field in viewkeys(lead_params) and
                    lead_params == {k: v for k, v in viewitems(params) if k in viewkeys(lead_params)}
                    and params.get(related_field, None) in (None, '')):
                self.fill_with_related(params, related_field,
                                       self.get_value_for_field(None, related_field))

        params.update((self.only_if_value or {}).get(field, {}))

    def get_all_not_str_fields(self, additional=''):
        other_fields = []
        additional = '_' + additional if additional else ''
        for field_type_name in ('digital_fields%s' % additional, 'date_fields', 'datetime_fields',
                                'choice_fields%s' % additional, 'choice_fields%s_with_value_in_error' % additional,
                                'disabled_fields%s' % additional, 'hidden_fields%s' % additional,
                                'int_fields%s' % additional, 'multiselect_fields%s' % additional,
                                'not_str_fields'):
            other_fields.extend(getattr(self, field_type_name, []) or [])
        return other_fields

    def get_all_required_if_fields(self, required_if):
        all_lead = ()
        all_dependent = ()
        related = ()
        for k, v in viewitems(required_if):
            if isinstance(k, (list, tuple)):
                all_lead += tuple(k)
            else:
                all_lead += (k,)

            for vv in (v if isinstance(v, (list, tuple)) else (v,)):
                if isinstance(vv, (list, tuple)):
                    related += tuple(vv)
                else:
                    all_dependent += (vv,)
        return {'lead': all_lead,
                'dependent': all_dependent,
                'related': related}

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
        return self.get_obj_manager.order_by('?').first()

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
            obj = qs.order_by('?').first()

        """Next block is like in create_copy"""
        inline_models_dict = {}
        for field in [ff for ff in param_names if re.findall(r'[\w_]+\-\d+\-[\w_]+', ff)]:
            if field not in self.all_fields_add:
                """only if user can change this field"""
                continue
            set_name = field.split('-')[0]
            inline_models_dict[set_name] = inline_models_dict.get(set_name, ()) + (field.split('-')[-1],)

        additional = {}
        for key in viewkeys(inline_models_dict):
            additional[key] = getattr(obj, key).all()

        for field in param_names:
            value = self._get_field_value_by_name(obj, field)
            if not value:
                field_class = self.get_field_by_name(obj, field)
                value = ''
                n = 0
                while n < 3 and not value:
                    n += 1
                    value = self.get_value_for_field(None, field)
                    mro_names = [b.__name__ for b in field_class.__class__.__mro__]
                    if 'DateField' in mro_names:
                        try:
                            value = datetime.strptime(value, getattr(settings, 'TEST_DATE_INPUT_FORMAT',
                                                                     settings.DATE_INPUT_FORMATS[0])).date()
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


class FormTestMixIn(FormCommonMixIn,
                    GlobalTestMixIn,
                    ListPositiveCases,
                    ListNegativeCases):
    pass


class AddCommonMixIn(object):

    def clean_depend_fields_add(self, params, field):
        for field_for_clean in self._depend_one_of_fields_add.get(field, ()):
            self.set_empty_value_for_field(params, field_for_clean)

    def prepare_for_add(self):
        pass

    def send_add_request(self, params):
        return self.client.post(self.get_url(self.url_add), params, follow=True, **self.additional_params)


class FormAddTestMixIn(AddCommonMixIn,
                       FormTestMixIn,
                       AddPositiveCases,
                       AddNegativeCases):
    pass


class EditCommonMixIn(object):
    second_save_available = True
    url_edit = ''

    def clean_depend_fields_edit(self, params, field):
        for field_for_clean in self._depend_one_of_fields_edit.get(field, ()):
            self.set_empty_value_for_field(params, field_for_clean)

    def get_obj_id_for_edit(self):
        if '%' not in self.url_edit and '/' in self.url_edit:
            return int(re.findall(r"/(\d+)/", self.url_edit)[0])
        return self.get_obj_manager.order_by('?').values_list('pk', flat=True).first()

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
            return qs.order_by('?').first()
        else:
            return self.create_copy(other_obj, param_names)

    def send_edit_request(self, obj_pk, params):
        return self.client.post(self.get_url_for_negative(self.url_edit, (obj_pk,)),
                                params, follow=True, **self.additional_params)

    def update_params_for_obj(self, obj):
        pass


class FormEditTestMixIn(EditCommonMixIn,
                        FormTestMixIn,
                        EditPositiveCases,
                        EditNegativeCases):
    pass


class DeleteCommonMixIn(object):
    url_delete = ''

    def send_delete_request(self, obj_pk):
        return self.client.post(self.get_url_for_negative(self.url_delete, (obj_pk,)), {'post': 'yes'},
                                follow=True, **self.additional_params)


class FormDeleteTestMixIn(DeleteCommonMixIn,
                          FormTestMixIn,
                          DeletePositiveCases,
                          DeleteNegativeCases):
    pass


class RemoveCommonMixIn(object):

    url_delete = ''
    url_edit_in_trash = ''
    url_recovery = ''

    def __init__(self, *args, **kwargs):
        super(RemoveCommonMixIn, self).__init__(*args, **kwargs)
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


class FormRemoveTestMixIn(RemoveCommonMixIn,
                          FormTestMixIn,
                          RemovePositiveCases,
                          RemoveNegativeCases):
    """for objects with is_removed attribute"""
    pass


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


class ChangePasswordCommonMixIn(object):
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
        super(ChangePasswordCommonMixIn, self).__init__(*args, **kwargs)
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

    def _get_obj_for_edit(self):
        user = self.get_obj_manager.order_by('?').first()
        self.user_relogin(user.email, self.current_password)
        user = self.get_obj_manager.get(pk=user.pk)
        return user

    def get_obj_for_edit(self):
        obj = self._get_obj_for_edit()
        self.update_params_for_obj(obj)
        return obj

    def get_login_name(self, user):
        return user.email

    def send_change_password_request(self, user_pk, params):
        return self.client.post(self.get_url_for_negative(self.url_change_password, (user_pk,)),
                                params, **self.additional_params)

    def update_params_for_obj(self, obj):
        pass


class ChangePasswordMixIn(ChangePasswordCommonMixIn,
                          GlobalTestMixIn,
                          ChangePasswordPositiveCases,
                          ChangePasswordNegativeCases,
                          LoginMixIn):
    pass


class BlacklistMixIn(object):
    blacklist_model = None

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

    def clean_blacklist(self):
        if self.blacklist_model:
            self.blacklist_model.objects.all().delete()

    def set_host_blacklist(self, host, count):
        if not self.blacklist_model:
            return None
        if count > 1:
            self.blacklist_model.objects.create(host=host, count=count)
        elif count == 1:
            self.blacklist_model.objects.create(host=host)


class ResetPasswordCommonMixIn(BlacklistMixIn):
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
    request_reset_retries = None
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
        super(ResetPasswordCommonMixIn, self).__init__(*args, **kwargs)
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
        if self.request_reset_retries and self.request_reset_retries < 2:
            self.request_reset_retries = None

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

    def _get_obj_for_edit(self):
        user = self.get_obj_manager.order_by('?').first()
        self.username = self.get_login_name(user)
        return user

    def get_obj_for_edit(self):
        obj = self._get_obj_for_edit()
        self.update_params_for_obj(obj)
        return obj

    def send_reset_password_request(self, params):
        return self.client.post(self.get_url(self.url_reset_password_request), params,
                                follow=True, **self.additional_params)

    def send_change_after_reset_password_request(self, codes, params):
        return self.client.post(self.get_url_for_negative(self.url_reset_password, codes),
                                params, follow=True, **self.additional_params)

    def set_host_pre_blacklist_reset(self, host):
        if not self.blacklist_model:
            return None
        if self.request_reset_retries:
            self.set_host_blacklist(host=host, count=self.login_retries - 1)

    def set_user_inactive(self, user):
        user.is_active = False
        user.save()

    def update_params_for_obj(self, obj):
        pass


class ResetPasswordMixIn(ResetPasswordCommonMixIn,
                         GlobalTestMixIn,
                         ResetPasswordPositiveCases,
                         ResetPasswordNegativeCases):

    pass


class LoginCommonMixIn(BlacklistMixIn):

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
        super(LoginCommonMixIn, self).__init__(*args, **kwargs)
        if self.default_params is None:
            self.default_params = {self.field_username: self.username,
                                   self.field_password: self.password}
        self.passwords_for_check = self.passwords_for_check or [self.password, ]
        if self.login_retries and self.login_retries < 2:
            self.login_retries = None

    def add_csrf(self, params):
        response = self.client.get(self.get_url(self.url_login), follow=True, **self.additional_params)
        params['csrfmiddlewaretoken'] = response.cookies[settings.CSRF_COOKIE_NAME].value

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
            self.assert_status_code(response.status_code, 200)
            self.assertEqual(response.redirect_chain, [])

    def check_response_on_negative(self, response):
        pass

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

    def set_host_pre_blacklist_login(self, host):
        if not self.blacklist_model:
            return None
        if self.login_retries:
            self.set_host_blacklist(host=host, count=self.login_retries - 1)

    def set_user_inactive(self, user):
        user.is_active = False
        user.save()

    def update_captcha_params(self, url, params, *args, **kwargs):
        self.client.get(url, **self.additional_params)
        params.update(get_captcha_codes())


class LoginTestMixIn(LoginCommonMixIn,
                     LoginPositiveCases,
                     LoginNegativeCases):

    pass


base_db_initialized = False


class CustomTestCase(GlobalTestMixIn, TransactionTestCase):

    multi_db = True
    databases = '__all__'
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

        """load fixtures to main database once"""
        for db in cls._databases_names(include_mirrors=False):
            if cls.reset_sequences:
                """Code from TransactionTestCase._reset_sequences>>>"""
                conn = connections[db]
                from django.core.management.color import no_style
                if conn.features.supports_sequence_reset:
                    sql_list = conn.ops.sequence_reset_by_name_sql(
                        no_style(), conn.introspection.sequence_list())
                    if sql_list:
                        with transaction.atomic(using=db):
                            cursor = conn.cursor()
                            for sql in sql_list:
                                cursor.execute(sql)
                """<<<Code from TransactionTestCase._reset_sequences"""

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
                    ContentType.objects.clear_cache()
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
