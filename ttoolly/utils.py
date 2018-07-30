# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

from datetime import datetime, date, time
from io import StringIO
from shutil import copyfile, rmtree
from time import mktime
from xml.etree import ElementTree as et
import decimal
import io
import json
import os
import random
import re
import string
import sys
import traceback

from builtins import str
from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadhandler import MemoryFileUploadHandler
from decimal import Decimal
from random import uniform
from lxml.html import document_fromstring
try:
    from django.core.urlresolvers import reverse, resolve, Resolver404, NoReverseMatch
except:
    # Django 2.0
    from django.urls import reverse, resolve, Resolver404, NoReverseMatch
from django.forms.forms import NON_FIELD_ERRORS
from django.template.context import Context
from django.test import Client
from django.utils.encoding import force_text
from future.utils import viewvalues, viewitems, viewkeys
from past.builtins import xrange, basestring
import rstr

__all__ = ('convert_size_to_bytes',
           'fill_all_obj_fields',
           'format_errors',
           'generate_random_obj',
           'generate_sql',
           'get_all_field_names_from_model',
           'get_all_form_errors',
           'get_all_urls',
           'get_captcha_codes',
           'get_captcha_codes_simplecaptcha',
           'get_captcha_codes_supercaptcha',
           'get_error',
           'get_field_from_response',
           'get_fields_list_from_response',
           'get_real_fields_list_from_response',
           'get_fixtures_data',
           'get_keys_from_context',
           'get_randname',
           'get_randname_from_file',
           'get_random_bmp_content',
           'get_random_contentfile',
           'get_random_date_value',
           'get_random_datetime_value',
           'get_random_decimal',
           'get_random_domain_value',
           'get_random_email_value',
           'get_random_file',
           'get_random_gif_content',
           'get_random_image',
           'get_random_image_contentfile',
           'get_random_img_content',
           'get_random_inn',
           'get_random_jpg_content',
           'get_random_png_content',
           'get_random_svg_content',
           'get_random_url_value',
           'get_url',
           'get_url_for_negative',
           'get_value_for_obj_field',
           'move_dir',
           'prepare_custom_file_for_tests',
           'prepare_file_for_tests',
           'to_bytes',
           'unicode_to_readable',
           'use_in_all_tests',)


try:
    FILE_TYPES = (file, io.IOBase)
except NameError:
    FILE_TYPES = (io.IOBase,)


def convert_size_to_bytes(size):
    SYMBOLS = ['', 'K', 'M', 'G']
    size, symbol = re.findall(r'([\d\.]+)(\w?)', force_text(size))[0]
    size = float(size) * 1024 ** SYMBOLS.index(symbol if symbol in SYMBOLS else '')
    return int(size)


def fill_all_obj_fields(obj, fields=(), save=True):
    required_fields = fields
    if not fields:
        fields = [f.name for f in obj.__class__._meta.fields]
    for field_name in fields:
        if getattr(obj, field_name):
            continue
        f = obj.__class__._meta.get_field(field_name)
        if f.auto_created:
            continue
        if field_name not in required_fields and f.null and f.blank:
            if random.randint(0, 1):
                continue
        value = None
        i = 0
        while not value and i < 3:
            value = get_value_for_obj_field(f)
            if isinstance(value, basestring):
                value = value.strip()
            i += 1
        if value:
            setattr(obj, field_name, value)
    if save:
        obj.save()
    return obj


def format_errors(errors, space_count=0):
    joined_errors = '\n\n'.join(errors)
    if space_count > 0:
        spaces = ' ' * space_count
        joined_errors = spaces + ('\n' + spaces).join(joined_errors.splitlines())
    return '\n%s' % joined_errors


def generate_random_obj(obj_model, additional_params=None, filename=None, with_save=True):
    additional_params = additional_params or {}
    params = {}
    for f in obj_model._meta.fields:
        if f.auto_created or f.name in additional_params.keys():
            continue
        if f.null and f.blank and random.randint(0, 1):
            continue
        params[f.name] = get_value_for_obj_field(f, filename)
    params.update(additional_params)
    if with_save:
        return obj_model.objects.create(**params)
    return obj_model(**params)


def generate_sql(data):
    sql = ''
    for element in data:
        table_name = '_'.join(element['model'].split('.'))
        pk = element['pk']
        columns = [pk, ]
        values = [element[pk], ]
        additional_sql = ''
        for key, value in viewitems(element['fields']):
            if not isinstance(value, list):
                columns.append(key)
                if value is None:
                    value = 'null'
                elif isinstance(value, bool):
                    value = force_text(value)
                else:
                    value = "'%s'" % value
                values.append(value)
            else:
                additional_sql += "INSERT INTO %s (%s) VALUES (%s);\n" % \
                                  ('_'.join([table_name, key]),
                                   ', '.join([element['model'].split('.')[1], key + '_id']),
                                   ', '.join([pk, value]))

        columns = ', '.join(columns)
        values = ', '.join(values)
        sql += "INSERT INTO %s (%s) VALUES (%s);\n" % (table_name, columns, values)
        sql += additional_sql
    return sql


def get_all_field_names_from_model(model_name):
    """from django docs"""
    from itertools import chain
    return list(set(chain.from_iterable(
        (field.name, field.attname) if hasattr(field, 'attname') else (field.name,)
        for field in model_name._meta.get_fields()
        # For complete backwards compatibility, you may want to exclude
        # GenericForeignKey from the results.
        if not (field.many_to_one and field.related_model is None)
    )))


def get_all_form_errors(response):
    if not response.context:
        return None

    def get_errors(form):
        """simple form"""
        errors = form._errors
        if not errors:
            return {}
        if form.prefix:
            if isinstance(errors, list):
                _errors = {}
                for n, el in enumerate(errors):
                    _errors.update({'%s-%s-%s' % (form.prefix, n, k): v for k, v in viewitems(el)})
            else:
                _errors = {'%s-%s' % (form.prefix, k): v for k, v in viewitems(errors)}
            errors = _errors

        """form with formsets"""
        form_formsets = getattr(form, 'formsets', {})
        if form_formsets:
            for fs_name, fs in viewitems(form_formsets):
                errors.pop('-'.join(filter(None, [form.prefix, fs_name])), None)
                errors.update(get_formset_errors(fs))

        return errors

    def get_formset_errors(formset):
        formset_errors = {}
        non_form_errors = formset._non_form_errors
        if non_form_errors:
            formset_errors.update({'-'.join([formset.prefix, NON_FIELD_ERRORS]): non_form_errors})
        for form in getattr(formset, 'forms', formset):
            if not form:
                continue
            formset_errors.update(get_errors(form))
        return formset_errors

    form_errors = {}
    forms = []
    try:
        forms.append(response.context['wizard']['form'])
    except KeyError:
        pass
    try:
        forms.append(response.context['form'])
    except KeyError:
        pass
    try:
        forms.extend([form for form in viewvalues(response.context['forms'])])
    except KeyError:
        pass
    try:
        forms.append(response.context['adminform'].form)
    except KeyError:
        pass

    try:
        for fs in response.context['form_set']:
            non_form_errors = fs._non_field_errors()
            if non_form_errors:
                form_errors.update({'-'.join([re.sub(r'-(\d+)$', '', fs.prefix), NON_FIELD_ERRORS]): non_form_errors})
            errors = fs._errors
            if errors:
                form_errors.update({'%s-%s' % (fs.prefix, key): value for key, value in viewitems(errors)})
    except KeyError:
        pass
    try:
        for fs in response.context['inline_admin_formsets']:
            non_form_errors = fs.formset._non_form_errors
            if non_form_errors:
                form_errors.update({'-'.join([fs.formset.prefix, NON_FIELD_ERRORS]): non_form_errors})
            errors = fs.formset._errors
            if errors:
                for n, el in enumerate(errors):
                    for key, value in viewitems(el):
                        form_errors.update({'%s-%d-%s' % (fs.formset.prefix, n, key): value})
    except KeyError:
        pass

    for subcontext in response.context:
        for key in get_keys_from_context(subcontext):
            value = subcontext[key]
            value = value if isinstance(value, list) else [value]
            for v in value:
                mro_names = [cn.__name__ for cn in getattr(v.__class__, '__mro__', [])]
                if 'BaseFormSet' in mro_names:
                    form_errors.update(get_formset_errors(v))
                elif 'BaseForm' in mro_names:
                    forms.append(v)

    for form in set(forms):
        if form:
            form_errors.update(get_errors(form))

    return form_errors


def get_all_urls(urllist, depth=0, prefix='', result=None):
    if result is None:
        result = []
    for entry in urllist:
        url = prefix + getattr(entry, 'pattern', entry).regex.pattern.strip('^$')
        if hasattr(entry, 'url_patterns'):
            get_all_urls(entry.url_patterns, depth + 1, prefix=url, result=result)
        else:
            if not url.startswith('/'):
                url = '/' + url
            # Значения и с вложенными скобками "(/(\w+)/)", и без
            regexp = '((\([^\(\)]*?)?' \
                     '\([^\(\)]+\)' \
                     '(?(2)[^\(\)]*\)|))'
            # открывающая скобка и текст без скобок
            # значение в скобках. Например (?P<pk>\d+)
            # если есть первая открывающая скобка, нужно взять строку до закрывающей
            fres = re.findall(regexp, url)
            for fr in fres:
                fr = fr[0]
                value_for_replace = '123'
                if (re.findall('>(.+?)\)', fr) and
                        not set(re.findall('>(.+?)\)', fr)).intersection(['.*', '\d+', '.+', '[^/.]+'])):
                    value_for_replace = rstr.xeger(fr)
                url = url.replace(fr, value_for_replace)
            result.append(url)
    result.sort()
    return result


def get_captcha_codes_supercaptcha():
    import supercaptcha
    CAPTCHA_PREFIX = supercaptcha.settings.settings.CAPTCHA_CACHE_PREFIX
    client = Client()
    code = supercaptcha.get_current_code()
    client.get('/captcha/%s/' % code)
    captcha_text = cache.get('%s-%s' % (CAPTCHA_PREFIX, code))
    captcha_form_prefix = getattr(settings, 'TEST_CAPTCHA_FORM_PREFIX', '')
    if captcha_form_prefix:
        captcha_form_prefix += '-'
    return {captcha_form_prefix + 'captcha_0': code, captcha_form_prefix + 'captcha_1': captcha_text}


def get_captcha_codes_simplecaptcha():
    from captcha.models import CaptchaStore
    captchas = CaptchaStore.objects.all()
    if captchas:
        captcha = captchas[0]
        captcha_form_prefix = getattr(settings, 'TEST_CAPTCHA_FORM_PREFIX', '')
        if captcha_form_prefix:
            captcha_form_prefix += '-'
        return {captcha_form_prefix + 'captcha_0': captcha.hashkey, captcha_form_prefix + 'captcha_1': captcha.response}
    else:
        return {}


def get_captcha_codes():
    CAPTCHA_TYPE = getattr(settings, 'CAPTCHA_TYPE', 'simplecaptcha')
    if CAPTCHA_TYPE == 'supercaptcha':
        return get_captcha_codes_supercaptcha()
    elif CAPTCHA_TYPE == 'simplecaptcha':
        return get_captcha_codes_simplecaptcha()
    return {}


def get_error(tr_limit=getattr(settings, 'TEST_TRACEBACK_LIMIT', None)):
    etype, value, tb = sys.exc_info()
    result = ''
    if any([etype, value, tb]):
        err = ''.join([force_text(el) for el in traceback.format_exception(etype, value, tb, limit=tr_limit)])
        result = unicode_to_readable(err)
    return result


def get_field_from_response(response, field_name):
    def get_form_fields(form):
        fields = dict(form.fields)
        if form.prefix:
            fields = {'%s-%s' % (form.prefix, k): v for k, v in fields.items()}
        return fields

    fields = {}
    forms = []
    try:
        forms.append(response.context['wizard']['form'])
    except KeyError:
        pass
    try:
        forms.append(response.context['form'])
    except KeyError:
        pass
    try:
        forms.extend([form for form in viewvalues(response.context['forms'])])
    except KeyError:
        pass
    try:
        forms.extend(response.context['form_set'])
    except KeyError:
        pass

    try:
        form = response.context['adminform'].form
        forms.append(form)
    except KeyError:
        pass

    for subcontext in response.context:
        for key in get_keys_from_context(subcontext):
            value = subcontext[key]
            value = value if isinstance(value, list) else [value]
            for v in value:
                mro_names = [cn.__name__ for cn in getattr(v.__class__, '__mro__', [])]
                if 'BaseFormSet' in mro_names:
                    formset = v
                    for form in getattr(formset, 'forms', formset):
                        forms.append(form)
                elif 'BaseForm' in mro_names:
                    forms.append(v)

    forms = list(set(forms))
    n = 0
    while n < len(forms):
        _forms = getattr(forms[n], 'forms', [])
        _formsets = getattr(forms[n], 'formsets', {})
        if _formsets:
            for fs_name, fs in viewitems(_formsets):
                forms.extend(getattr(fs, 'forms', fs))
        if _forms:
            forms.pop(n)
            if isinstance(_forms, dict):
                forms.extend(_forms.values())
            else:
                forms.extend(_forms)
        else:
            n += 1

    for form in filter(None, set(forms)):
        fields.update(get_form_fields(form))
    try:
        for fs in response.context['inline_admin_formsets']:
            fs_name = fs.formset.prefix
            for number, form in enumerate(fs.formset.forms):
                _fields = {fs_name + '-%d-' % number + f: v for f, v in form.fields.items()}
                fields.update(_fields)
    except KeyError:
        pass

    return fields[field_name]


def get_fields_list_from_response(response, only_success=True):
    if only_success and response.status_code != 200:
        raise Exception('Response status code %s (expect 200 for getting fields list)' % response.status_code)

    def get_form_fields(form):
        fields = list(form.fields.keys())
        visible_fields = set(fields).intersection([f.name for f in form.visible_fields()])
        hidden_fields = [f.name for f in form.hidden_fields()]
        disabled_fields = [k for k, v in viewitems(form.fields) if v.widget.attrs.get('readonly', False)]
        visible_fields = visible_fields.difference(disabled_fields)
        if form.prefix:
            fields = ['%s-%s' % (form.prefix, field) for field in fields]
            visible_fields = ['%s-%s' % (form.prefix, field) for field in visible_fields]
            hidden_fields = ['%s-%s' % (form.prefix, field) for field in hidden_fields]
            disabled_fields = ['%s-%s' % (form.prefix, field) for field in disabled_fields]
        return dict(fields=fields,
                    visible_fields=visible_fields,
                    hidden_fields=hidden_fields,
                    disabled_fields=disabled_fields)

    fields = []
    visible_fields = []
    hidden_fields = []
    disabled_fields = []
    forms = []
    try:
        forms.append(response.context['wizard']['form'])
    except KeyError:
        pass
    try:
        forms.append(response.context['form'])
    except KeyError:
        pass
    try:
        forms.extend([form for form in viewvalues(response.context['forms'])])
    except KeyError:
        pass
    try:
        forms.extend(response.context['form_set'])
    except KeyError:
        pass

    try:
        form = response.context['adminform'].form
        _fields = []

        for f in response.context['adminform'].fieldsets:
            for ff in f[1]['fields']:
                if type(ff) in (list, tuple):
                    _fields.extend(ff)
                else:
                    _fields.append(ff)
        fields.extend(_fields)
        _visible_fields = [f.name for f in form.visible_fields()]
        visible_fields.extend(set(_fields).intersection(_visible_fields))
        _hidden_fields = [f.name for f in form.hidden_fields()]
        hidden_fields.extend(_hidden_fields)
        disabled_fields.extend(set(_fields).difference(_visible_fields).difference(_hidden_fields))
    except KeyError:
        pass

    for subcontext in response.context:
        for key in get_keys_from_context(subcontext):
            value = subcontext[key]
            value = value if isinstance(value, list) else [value]
            for v in value:
                mro_names = [cn.__name__ for cn in getattr(v.__class__, '__mro__', [])]
                if 'BaseFormSet' in mro_names:
                    formset = v
                    for form in getattr(formset, 'forms', formset):
                        forms.append(form)
                elif 'BaseForm' in mro_names:
                    forms.append(v)

    forms = list(set(forms))
    n = 0
    while n < len(forms):
        _forms = getattr(forms[n], 'forms', [])
        _formsets = getattr(forms[n], 'formsets', {})
        if _formsets:
            for fs_name, fs in viewitems(_formsets):
                forms.extend(getattr(fs, 'forms', fs))
        if _forms:
            forms.pop(n)
            if isinstance(_forms, dict):
                forms.extend(_forms.values())
            else:
                forms.extend(_forms)
        else:
            n += 1

    for form in filter(None, set(forms)):
        _fields = get_form_fields(form)
        fields.extend(_fields['fields'])
        visible_fields.extend(_fields['visible_fields'])
        hidden_fields.extend(_fields['hidden_fields'])
        disabled_fields.extend(_fields['disabled_fields'])
    try:
        for fs in response.context['inline_admin_formsets']:
            fs_name = fs.formset.prefix
            for number, form in enumerate(fs.formset.forms):
                _fields = [fs_name + '-%d-' % number + f for f in viewkeys(form.fields)]
                _visible_fields = [fs_name + '-%d-' % number + f.name for f in form.visible_fields()]
                _hidden_fields = [fs_name + '-%d-' % number + f.name for f in form.hidden_fields()]
                fields.extend(_fields)
                visible_fields.extend(set(_fields).intersection(_visible_fields))
                disabled_fields.extend(set(_fields).difference(_visible_fields).difference(_hidden_fields))
                hidden_fields.extend(_hidden_fields)
    except KeyError:
        pass

    return dict(all_fields=fields,
                visible_fields=visible_fields,
                hidden_fields=hidden_fields,
                disabled_fields=disabled_fields)


def get_real_fields_list_from_response(response, only_success=True):
    """Not use django response.context"""
    if only_success and response.status_code != 200:
        raise Exception('Response status code %s (expect 200 for getting fields list)' % response.status_code)

    doc = document_fromstring(response.content.decode('utf-8'))
    fields = []
    visible_fields = []
    hidden_fields = []
    disabled_fields = []
    for field in doc.xpath('//form//*[@name and not(@type="submit")]'):
        if field.attrib.get('type', '') == 'radio' and field.name in visible_fields and field.name in fields:
            continue
        else:
            field_name = {'captcha_1': 'captcha',
                          'captcha_0': 'captcha'}.get(field.attrib['name'], field.attrib['name'])
            if field_name == 'csrfmiddlewaretoken':
                continue
            fields.append(field_name)
            if field.attrib.get('type', '') == 'hidden':
                hidden_fields.append(field_name)
            elif field.attrib.get('disabled', '') == 'disabled':
                disabled_fields.append(field_name)
            else:
                visible_fields.append(field_name)
    return dict(all_fields=fields,
                visible_fields=visible_fields,
                hidden_fields=hidden_fields,
                disabled_fields=disabled_fields)


def get_fixtures_data(filename):
    with open(filename) as f:
        data = json.loads(f.read())
    for element in data:
        element['pk'] = [k for k in element.keys() if k not in ('model', 'fields')][0]
    return data


def get_keys_from_context(subcontext):
    context_list = [subcontext]
    all_keys = []
    while context_list:
        subcontext = context_list.pop(0)
        for d in getattr(subcontext, 'dicts', []) or [subcontext]:
            if isinstance(d, Context):
                context_list.append(d)
            else:
                all_keys.extend(d.keys())
    return all_keys


def get_randname(l=10, _type='a', length_of_chunk=10):
    """
    a - all
    d - digits
    w - letters
    r - russian letters
    p - punctuation
    s - whitespace
    """
    if 'a' == _type:
        text = string.printable
    else:
        text = ''
        letters_dict = {'d': string.digits,
                        'w': string.ascii_letters,
                        'r': 'абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',
                        'p': string.punctuation,
                        's': string.whitespace}
        for t in _type:
            text += letters_dict.get(t, t)

    count_of_chunks = l // length_of_chunk
    n = ''.join([random.choice(text) for _ in xrange(length_of_chunk)]) * count_of_chunks + \
        ''.join([random.choice(text) for _ in xrange(l % length_of_chunk)])
    return n


def get_randname_from_file(filename, l=100):
    with open(filename, 'rb') as f:
        text = f.read().decode('utf-8')
    text = text.split(' ')
    result = random.choice(text)
    while len(result) < l:
        result = ' '.join([result, random.choice(text)])
    return result[:l]


def get_random_date_value(date_from=date.today().replace(month=1, day=1), date_to=date.today()):
    return date.fromordinal(random.randint(date_from.toordinal(), date_to.toordinal()))


def get_random_datetime_value(datetime_from=datetime.combine(datetime.today().replace(month=1, day=1), time(0, 0)),
                              datetime_to=date.today()):
    return datetime.fromtimestamp(random.randint(mktime(datetime_from.timetuple()), mktime(datetime_to.timetuple())))


def get_random_decimal(value_from, value_to, places=10):
    return Decimal(uniform(float(value_from), float(value_to))).quantize(Decimal('0.1')**places)


def get_random_domain_value(length):
    end_length = random.randint(2, min(length - 2, 6))
    domain_length = random.randint(1, min(length - end_length - 1, 62))
    subdomain_length = length - end_length - 1 - domain_length - 1
    if subdomain_length <= 1:
        subdomain = ''
        if subdomain_length >= 0:
            domain_length += 1 + subdomain_length
    else:
        subdomain = '%s%s.' % (get_randname(1, 'w'), get_randname(subdomain_length - 1, 'wd.-'))
        while any([len(el) > 62 for el in subdomain.split('.')]):
            subdomain = '.'.join([(el if len(el) <= 62 else el[:61] + '.' + el[62:]) for el in subdomain.split('.')])
        subdomain = re.sub(r'\.[\.\-]', '.%s' % get_randname(1, 'w'), subdomain)
        subdomain = re.sub(r'\-\.', '%s.' % get_randname(1, 'w'), subdomain)
    if domain_length < 3:
        domain = get_randname(domain_length, 'wd')
    else:
        domain = '%s%s%s' % (get_randname(1, 'w'),
                             get_randname(domain_length - 2, 'wd-'),
                             get_randname(1, 'w'))
        domain = re.sub(r'\-\-', '%s-' % get_randname(1, 'w'), domain)

    return '%s%s.%s' % (subdomain, domain, get_randname(end_length, 'w'))


def get_random_email_value(length):
    MAX_DOMAIN_LENGTH = 62
    min_length_without_name = 1 + 1 + 3  # @.\.ru
    max_length_without_name = MAX_DOMAIN_LENGTH + 1 + 3  # @ .ru
    name_length = random.randint(max(1, length - max_length_without_name),
                                 length - min_length_without_name)
    domain_length = length - name_length - 1  # @ .ru
    symbols_for_generate = 'wd'
    symbols_with_escaping = ''
    if not getattr(settings, 'SIMPLE_TEST_EMAIL', False):
        symbols_for_generate += '!#$%&\'*+-/=?^_`{|}~.'
        # symbols_with_escaping = '\\"(),:;<>@[]' # TODO: добавлено 09-06-2014
        symbols_for_generate += symbols_with_escaping
    username = get_randname(name_length, symbols_for_generate)
    while '..' in username:
        username = username.replace('..', get_randname(1, 'wd') + '.')
    username = re.sub(r'(\.$)|(^\.)', get_randname(1, 'wd'), username)
    for s in symbols_with_escaping:
        username = username.replace(s, '\%s' % s)
    return '%s@%s' % (username.lower(),
                      get_random_domain_value(domain_length).lower())


def get_value_for_obj_field(f, filename=None):
    mro_names = set([m.__name__ for m in f.__class__.__mro__])
    if 'AutoField' in mro_names:
        return None
    if 'EmailField' in mro_names:
        length = random.randint(10, f.max_length)
        return get_random_email_value(length)
    elif mro_names.intersection(['TextField', 'CharField']) and not (getattr(f, '_choices', None) or f.choices):
        length = random.randint(0 if f.blank else 1, int(f.max_length) if f.max_length else 500)
        if filename:
            return get_randname_from_file(filename, length)
        else:
            return get_randname(length)
    elif 'DateTimeField' in mro_names:
        return datetime.now()
    elif 'DateField' in mro_names:
        return date.today()
    elif mro_names.intersection(['PositiveIntegerField', 'IntegerField', 'SmallIntegerField']) and \
            not (getattr(f, '_choices', None) or f.choices):
        return random.randint(0, 1000)
    elif mro_names.intersection(['ForeignKey', 'OneToOneField']):
        related_model = f.related_model
        if related_model == f.model:
            # fix recursion
            return None
        objects = related_model.objects.all()
        if objects.count() > 0:
            return objects[random.randint(0, objects.count() - 1)] if objects.count() > 1 else objects[0]
        else:
            return generate_random_obj(related_model, filename=filename)
    elif 'BooleanField' in mro_names:
        return random.randint(0, 1)
    elif mro_names.intersection(['FloatField', 'DecimalField']):
        max_value = 90 if f.name in ('latitude', 'longitude') else (10 ** (f.max_digits - f.decimal_places) - 1 if
                                                                    (getattr(f, 'max_digits', None) and
                                                                     getattr(f, 'decimal_places', None)) else 1000)
        value = random.uniform(0, max_value)
        if getattr(f, 'decimal_places', None):
            value = round(value, f.decimal_places)
        if mro_names.intersection(['DecimalField', ]):
            value = decimal.Decimal(force_text(value))
        return value
    elif 'ArrayField' in mro_names:
        if getattr(f, '_choices', None) or f.choices:
            choices = list(getattr(f, '_choices', None) or f.choices)
            return [random.choice(choices)[0] for _ in xrange(random.randint(0 if f.blank else 1,
                                                                             len(choices)))]
        elif 'IntegerArrayField' in mro_names:
            return [random.randint(0, 1000) for _ in xrange(random.randint(0 if f.blank else 1, 10))]
    elif getattr(f, '_choices', None) or f.choices:
        return random.choice(list(getattr(f, '_choices', None) or f.choices))[0]
    elif mro_names.intersection(['FileField', 'ImageField']):
        if 'ImageField' in mro_names:
            content = get_random_jpg_content()
        else:
            content = get_randname(10)
        if not callable(f.upload_to):
            dir_path_length = len(f.upload_to)
        else:
            dir_path_length = 0
        length = random.randint(1, f.max_length - 4 - dir_path_length - 1)
        name = get_randname(length, 'wrd ') + '.jpg'
        return ContentFile(content, name=name)
    elif mro_names.intersection(['JSONField']):
        return {get_randname(10, 'wd'): get_randname(10) for i in xrange(random.randint(0, 5))}


def get_random_contentfile(size=10, filename=None):
    if not filename:
        filename = get_randname(10, 'wrd ')
    size = convert_size_to_bytes(size)
    return ContentFile(get_randname(size), filename)


def get_random_file(path=None, size=10, rewrite=False, return_opened=True, filename=None, **kwargs):
    if path:
        filename = os.path.basename(path)
        if os.path.exists(path):
            if not rewrite:
                if return_opened:
                    return open(path, 'r')
                return
            else:
                os.remove(path)
    if not filename:
        filename = get_randname(10, 'wrd ')
        extensions = kwargs.get('extensions', ())
        if extensions:
            filename = '.'.join([filename, random.choice(extensions)])
    size = convert_size_to_bytes(size)
    if not getattr(settings, 'TEST_GENERATE_REAL_SIZE_FILE', True) and size != 10:  # not default value
        size_text = '_size_%d_' % size
        size = 10
        filename = os.path.splitext(filename)[0][:-len(size_text)] + size_text + os.path.splitext(filename)[1]

    img_extensions = ('tiff', 'jpg', 'jpeg', 'png', 'gif', 'svg', 'bmp')
    if size > 0 and os.path.splitext(filename)[1].lower() == '.pdf':
        content = get_random_pdf_content(size)
    elif size > 0 and (os.path.splitext(filename)[1].lower().strip('.') in img_extensions or
                       set(img_extensions).intersection(kwargs.get('extensions', ()))):
        return get_random_image(path=path, size=size, rewrite=rewrite, return_opened=return_opened, filename=filename,
                                **kwargs)
    else:
        content = get_randname(size)
    if not path and return_opened:
        return ContentFile(content, filename)

    with open(path, 'a') as f:
        f.write(content)
    if return_opened:
        f = open(path, 'r')
    return f


def get_random_image(path='', size=10, width=None, height=None, rewrite=False, return_opened=True, filename=None,
                     **kwargs):
    """
    generate image file with size
    """
    size = convert_size_to_bytes(size)
    if path:
        filename = os.path.basename(path)
        if os.path.exists(path) and not rewrite:
            if abs(os.stat(path).st_size - size) // (size or 1) > 0.01:
                rewrite = True
            if not rewrite:
                if return_opened:
                    return open(path, 'r')
                return
        elif os.path.exists(path) and rewrite:
            os.remove(path)
    if not filename:
        filename = get_randname(10, 'wrd ')
        extensions = kwargs.get('extensions', ())
        if extensions:
            filename = '.'.join([filename, random.choice(extensions)])
    if os.path.splitext(filename)[1] in ('.bmp',):
        content = get_random_bmp_content(size)
    else:
        width = width or random.randint(kwargs.get('min_width', 1),
                                        kwargs.get('max_width', kwargs.get('min_width', 0) + 100))
        height = height or random.randint(kwargs.get('min_height', 1),
                                          kwargs.get('max_height', kwargs.get('min_height', 0) + 100))
        content = {'.gif': get_random_gif_content,
                   '.svg': get_random_svg_content,
                   '.png': get_random_png_content}.get(os.path.splitext(filename)[1].lower(),
                                                       get_random_jpg_content)(size, width, height)
    if not path and return_opened:
        return ContentFile(content, filename)
    with open(path, 'ab') as f:
        f.write(content)
    if return_opened:
        f = open(path, 'r')
    return f


def get_random_image_contentfile(size=10, width=1, height=1, filename=None):
    data = get_random_jpg_content(size, width, height)
    if not filename:
        filename = get_randname(10, 'wrd ')
    return ContentFile(data, filename)


def get_random_img_content(_format, size=10, width=1, height=1):
    try:
        import Image
    except ImportError:
        from PIL import Image
    size = convert_size_to_bytes(size)
    image = Image.new('RGB', (width, height), "#%06x" % random.randint(0, 0xFFFFFF))
    if getattr(Image, 'PILLOW_VERSION', getattr(Image, 'VERSION', '2.')).split('.')[0] == '1':
        output = StringIO()
    else:
        output = io.BytesIO()
    image.save(output, format=_format)
    content = output.getvalue()
    size -= len(content)
    if size > 0:
        content += bytearray(size)
    return content


def get_random_inn(length):
    if length in (10, None):
        value = get_randname(9, 'd')
        return value + str(sum(int(el[0]) * el[1] for el in zip(value, (2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10)
    if length == 12:
        value = get_randname(10, 'd')
        value = value + str(sum(int(el[0]) * el[1] for el in zip(value, (7, 2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10)
        return value + str(sum(int(el[0]) * el[1] for el in zip(value, (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8))) % 11 % 10)
    else:
        return get_randname(length, 'd')


def get_random_bmp_content(size=10, width=1, height=1):
    return get_random_img_content('BMP', size, width, height)


def get_random_gif_content(size=10, width=1, height=1):
    return get_random_img_content('GIF', size, width, height)


def get_random_jpg_content(size=10, width=1, height=1):
    return get_random_img_content('JPEG', size, width, height)


def get_random_pdf_content(size=10,):
    content = """%PDF-1.5
%\B5\ED\AE\FB
6 0 obj
<< /Type /Page
>>
endobj
{}
1 0 obj
<< /Type /Pages
   /Kids [ 6 0 R ]
   /Count 1
>>
endobj
13 0 obj
<< /Type /Catalog
   /Pages 1 0 R
>>
endobj
trailer
<< /Root 13 0 R
>>
%%EOF"""
    size = convert_size_to_bytes(size)
    size -= len(content.format(''))
    additional_content = ''
    if size > 0:
        additional_content = bytearray(size).decode()
    return content.format(additional_content)


def get_random_png_content(size=10, width=1, height=1):
    return get_random_img_content('PNG', size, width, height)


def get_random_svg_content(size=10, width=1, height=1):
    """
    generates svg content
    """
    size = convert_size_to_bytes(size)
    doc = et.Element('svg', width=force_text(width), height=force_text(
        height), version='1.1', xmlns='http://www.w3.org/2000/svg')
    et.SubElement(doc, 'rect', width=force_text(width), height=force_text(height),
                  fill='rgb(%s, %s, %s)' % (random.randint(1, 255), random.randint(1, 255), random.randint(1, 255)))
    output = StringIO()
    header = '<?xml version=\"1.0\" standalone=\"no\"?>\n' \
             '<!DOCTYPE svg PUBLIC \"-//W3C//DTD SVG 1.1//EN\" \"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd\">\n'
    output.write(header)
    output.write(et.tostring(doc).decode())
    content = output.getvalue()
    size -= len(content)
    if size > 0:
        content += '<!-- %s -->' % ('a' * (size - 9))
    output.close()
    return content


def get_random_url_value(length):
    MAX_DOMAIN_LENGTH = 62
    domain_length = length - 1
    while domain_length == length - 1:
        domain_length = random.randint(4, min(length, MAX_DOMAIN_LENGTH))
    append_length = length - domain_length - 1
    append = get_randname(append_length, 'wd-_/') if append_length > 0 else ''
    return get_random_domain_value(domain_length) + '/' + append


def get_url(url, args=(), **kwargs):
    if '%' in url:
        return url % args
    if '/' in url:
        return url
    if isinstance(args, dict):
        return reverse(url, kwargs=args, **kwargs)
    return reverse(url, args=args, **kwargs)


def get_url_for_negative(url, args=()):
    def repl(url, args):
        if not re.findall(r'/\d+/', url) and ':' in url:
            try:
                url = get_url(url, (1,) * len(args))
            except NoReverseMatch:
                pass
        start = 0
        l = []
        l_args = ['/%s/' % force_text(a) for a in args]
        for m in re.finditer(r'/\d+/', url):
            l.append(url[start:m.start()])
            start = m.end()
        l.append(url[start:])
        while len(l_args) < len(l):
            l_args.append(l_args[-1])
        return ''.join([force_text(item) for tup in zip(l, l_args) for item in tup][:-1])

    try:
        res = resolve(url)
        if res.url_name:
            url = get_url(':'.join([res.namespace, res.url_name]), args=args)
        else:
            url = repl(url, args)
    except Resolver404:
        try:
            prev_url = url
            url = get_url(url, args)
            if url == prev_url:
                url = repl(url, args)
        except NoReverseMatch:
            url = repl(url, args)
    except NoReverseMatch:
        url = repl(url, args)
    return url


def move_dir(path_to_dir):
    path_to_dir = os.path.normpath(path_to_dir)
    basename = os.path.basename(path_to_dir)
    tmp_path = os.path.join(os.path.split(path_to_dir)[0], '_%s' % basename)
    if os.path.exists(tmp_path):
        rmtree(path_to_dir)
        os.rename(tmp_path, path_to_dir)
    else:
        if os.path.exists(path_to_dir):
            os.rename(path_to_dir, tmp_path)
        else:
            os.makedirs(tmp_path)
        os.makedirs(path_to_dir)


def prepare_custom_file_for_tests(file_path, filename=''):
    directory = os.path.dirname(file_path)
    if not os.path.exists(directory):
        os.makedirs(directory)
    if filename:
        copyfile(filename, file_path)
        return
    elif os.path.splitext(file_path)[1].lower() in ('.jpg', '.jpeg', 'png', '.bmp', '.gif'):
        get_random_image(path=file_path, return_opened=False)
        return
    else:
        get_random_file(path=file_path, return_opened=False)
        return


def prepare_file_for_tests(model_name, field, filename='', verbosity=0):

    mro_names = [m.__name__ for m in model_name._meta.get_field(field).__class__.__mro__]
    for obj in model_name.objects.all():
        file_from_obj = getattr(obj, field, None)
        if file_from_obj:
            full_path = os.path.join(settings.MEDIA_ROOT, file_from_obj.path)
            if os.path.exists(full_path):
                continue
            if verbosity > 2:
                print('Generate file for path %s' % full_path)
            directory = os.path.dirname(full_path)
            if not os.path.exists(directory):
                os.makedirs(directory)
            if filename:
                copyfile(filename, full_path)
                continue
            elif 'ImageField' in mro_names:
                get_random_image(path=full_path, return_opened=False)
                continue
            else:
                get_random_file(path=full_path, return_opened=False)
                continue


def unicode_to_readable(text):
    def unescape_one_match(match_obj):
        return match_obj.group(0).encode('utf-8').decode('unicode_escape')
    return re.sub(r"\\u[0-9a-fA-F]{4}", unescape_one_match, force_text(text))


def use_in_all_tests(decorator):
    def decorate(cls, child=None):
        if child is None:
            child = cls

        for attr in cls.__dict__:
            if callable(getattr(cls, attr)) and attr.startswith('test_'):
                fn = getattr(child, attr, getattr(cls, attr))
                if fn and decorator not in getattr(fn, 'decorators', ()):
                    decorated = decorator(fn)
                    decorated.__name__ = fn.__name__
                    decorated.decorators = tuple(set(getattr(fn, 'decorators', ()))) + (decorator,)
                    setattr(child, attr, decorated)
        bases = cls.__bases__
        for base in bases:
            decorate(base, child)
        return cls

    return decorate


class FakeSizeMemoryFileUploadHandler(MemoryFileUploadHandler):

    def file_complete(self, file_size):
        if getattr(settings, 'TEST_GENERATE_REAL_SIZE_FILE', True):
            return super(FakeSizeMemoryFileUploadHandler, self).file_complete(file_size)
        re_size = re.match(r'^.*_size_(\d+)_.*', self.file_name, re.I)
        if re_size:
            file_size = int(re_size.group(1))
        return super(FakeSizeMemoryFileUploadHandler, self).file_complete(file_size)


def to_bytes(s):
    if isinstance(s, str):
        return s.encode('utf-8')
    return s
