# -*- coding: utf-8 -*-
from datetime import datetime, date, time
from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.urlresolvers import reverse, resolve, Resolver404, NoReverseMatch
from django.template.context import Context
from django.test import Client
from shutil import copyfile, rmtree
from time import mktime
import rstr

import chardet
import io
import json
import os
import random
import re
import string
import struct
import sys
import traceback
from xml.etree import ElementTree as et


def convert_size_to_bytes(size):
    SYMBOLS = ['', 'K', 'M', ]
    size, symbol = re.findall(r'([\d\.]+)(\w{0,1})', str(size))[0]
    size = float(size) * 1024 ** SYMBOLS.index(symbol if symbol in SYMBOLS else '')
    return int(size)


def fill_all_obj_fields(obj, fields=(), save=True):
    if not fields:
        fields = [f.name for f in obj.__class__._meta.fields]
    for field_name in fields:
        if getattr(obj, field_name):
            continue
        f = obj.__class__._meta.get_field_by_name(field_name)[0]
        if f.auto_created:
            continue
        if f.null and f.blank:
            if random.randint(0, 1):
                continue
        value = get_value_for_obj_field(f)
        if value:
            setattr(obj, field_name, value)
    if save:
        obj.save()
    return obj


def format_errors(errors, space_count=0):
    joined_errors = '\n\n'.join(errors)
    if not isinstance(joined_errors, unicode):
        if chardet.detect(joined_errors)['encoding'] == 'utf-8':
            joined_errors = joined_errors.decode('utf-8')
    if not joined_errors:
        return ''
    if space_count > 0:
        spaces = ' ' * space_count
        joined_errors = spaces + ('\n' + spaces).join(joined_errors.splitlines())
    return (u'\n%s' % joined_errors).encode('utf-8')


def generate_random_obj(obj_model, additional_params=None, filename=None):
    if additional_params is None:
        additional_params = {}
    fields = obj_model._meta.fields
    params = {}
    for f in fields:
        if f.auto_created or f.name in additional_params.keys():
            continue
        if f.null and f.blank:
            if random.randint(0, 1):
                continue
        params[f.name] = get_value_for_obj_field(f, filename)

    params.update(additional_params)
    return obj_model.objects.create(**params)


def generate_sql(data):
    sql = ''
    for element in data:
        table_name = '_'.join(element['model'].split('.'))
        pk = element['pk']
        columns = [pk, ]
        values = [element[pk], ]
        additional_sql = ''
        for key, value in element['fields'].iteritems():
            if not isinstance(value, list):
                columns.append(key)
                if value is None:
                    value = 'null'
                elif isinstance(value, bool):
                    value = str(value)
                else:
                    value = u"'%s'" % value
                values.append(value)
            else:
                additional_sql += u"INSERT INTO %s (%s) VALUES (%s);\n" % \
                                  ('_'.join([table_name, key]),
                                   ', '.join([element['model'].split('.')[1], key + '_id']),
                                   ', '.join([pk, value]))

        columns = ', '.join(columns)
        values = ', '.join(values)
        sql += u"INSERT INTO %s (%s) VALUES (%s);\n" % (table_name, columns, values)
        sql += additional_sql
    return sql


def get_all_form_errors(response):

    def get_errors(form):
        errors = form._errors
        if not errors:
            errors = {}
        if form.prefix:
            errors = {'%s-%s' % (form.prefix, k): v for k, v in errors.iteritems()}
        return errors
    if not response.context:
        return None
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
        forms.extend([form for form in response.context['forms'].itervalues()])
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
                form_errors.update({'%s-__all__' % re.sub(r'-(\d+)$', '', fs.prefix): non_form_errors})
            errors = fs._errors
            if errors:
                form_errors.update({'%s-%s' % (fs.prefix, key): value for key, value in errors.iteritems()})
    except KeyError:
        pass
    try:
        for fs in response.context['inline_admin_formsets']:
            non_form_errors = fs.formset._non_form_errors
            if non_form_errors:
                form_errors.update({'%s-__all__' % fs.formset.prefix: non_form_errors})
            errors = fs.formset._errors
            if errors:
                for n, el in enumerate(errors):
                    for key, value in el.iteritems():
                        form_errors.update({'%s-%d-%s' % (fs.formset.prefix, n, key): value})
    except KeyError:
        pass

    all_keys = []

    for subcontext in response.context:
        all_keys.extend(get_keys_from_context(subcontext))
    all_keys = set(all_keys)
    fs_keys = []
    for key in all_keys:
        value = response.context[key]
        mro_names = [cn.__name__ for cn in getattr(value.__class__, '__mro__', [])]
        if 'BaseFormSet' in mro_names:
            fs_keys.append(key)
        elif 'BaseForm' in mro_names:
            forms.append(value)

    for form in set(forms):
        if form:
            form_errors.update(get_errors(form))
    for fs_key in fs_keys:
        formset = response.context[fs_key]
        if not formset:
            continue
        non_form_errors = formset._non_form_errors
        if non_form_errors:
            form_errors.update({'%s-__all__' % formset.prefix: non_form_errors})
        for form in getattr(formset, 'forms', formset):
            if not form:
                continue
            errors = form._errors
            if errors:
                for key, value in errors.iteritems():
                    form_errors.update({'%s-%s' % (form.prefix, key): value})
    return form_errors


def get_all_urls(urllist, depth=0, prefix='', result=None):
    if result is None:
        result = []
    for entry in urllist:
        url = prefix + entry.regex.pattern.strip('^$')
        if hasattr(entry, 'url_patterns'):
            get_all_urls(entry.url_patterns, depth + 1,
                         prefix=(prefix if type(entry).__class__.__name__ == 'RegexURLResolver' else '') + url,
                         result=result)
        else:
            if not url.startswith('/'):
                url = '/' + url
            # TODO: переписать регулярку. Должны находиться значения и с вложенными скобками "(/(\w+)/)" и без
            fres = re.findall(r'\(.+?\)+', url)
            for fr in fres:
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
    if any([etype, value, tb]):
        err = ''.join(traceback.format_exception(etype, value, tb, limit=tr_limit))
        result = unicode_to_readable(err)
    else:
        result = ''
    return result


def get_fields_list_from_response(response):
    def get_form_fields(form):
        fields = form.fields.keys()
        visible_fields = set(fields).intersection([f.name for f in form.visible_fields()])
        hidden_fields = [f.name for f in form.hidden_fields()]
        disabled_fields = [k for k, v in form.fields.iteritems() if v.widget.attrs.get('readonly', False)]
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
        forms.extend([form for form in response.context['forms'].itervalues()])
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

    all_keys = []
    for subcontext in response.context:
        all_keys.extend(get_keys_from_context(subcontext))
    all_keys = set(all_keys)
    fs_keys = []
    for key in all_keys:
        value = response.context[key]
        mro_names = [cn.__name__ for cn in getattr(value.__class__, '__mro__', [])]
        if 'BaseFormSet' in mro_names:
            fs_keys.append(key)
        elif 'BaseForm' in mro_names:
            forms.append(value)

    for fs_key in fs_keys:
        formset = response.context[fs_key]
        for form in getattr(formset, 'forms', formset):
            forms.append(form)

    for form in set(forms):
        _fields = get_form_fields(form)
        fields.extend(_fields['fields'])
        visible_fields.extend(_fields['visible_fields'])
        hidden_fields.extend(_fields['hidden_fields'])
        disabled_fields.extend(_fields['disabled_fields'])
    try:
        for fs in response.context['inline_admin_formsets']:
            fs_name = fs.formset.prefix
            for number, form in enumerate(fs.formset.forms):
                _fields = [fs_name + '-%d-' % number + f for f in form.fields.iterkeys()]
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


def get_fixtures_data(filename):
    f = open(filename)
    data = json.loads(f.read())
    f.close()
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
                        'w': string.letters,
                        'r': u'абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',
                        'p': string.punctuation,
                        's': string.whitespace}
        for t in _type:
            text += letters_dict.get(t, t)

    count_of_chunks = l / length_of_chunk
    n = ''.join([random.choice(text) for _ in xrange(length_of_chunk)]) * count_of_chunks + \
        ''.join([random.choice(text) for _ in xrange(l % length_of_chunk)])
    return n


def get_randname_from_file(filename, l=100):
    f = open(filename)
    text = f.read().decode('utf-8')
    text = text.split(' ')
    f.close()
    result = random.choice(text)
    while len(result) < l:
        result = u' '.join([result, random.choice(text)])
    return result[:l]


def get_random_date_value(date_from=date.today().replace(month=1, day=1), date_to=date.today()):
    return date.fromordinal(random.randint(date_from.toordinal(), date_to.toordinal()))


def get_random_datetime_value(datetime_from=datetime.combine(datetime.today().replace(month=1, day=1), time(0, 0)),
                              datetime_to=date.today()):
    return datetime.fromtimestamp(random.randint(mktime(datetime_from.timetuple()), mktime(datetime_to.timetuple())))


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
    elif mro_names.intersection(['TextField', 'CharField']) and not f._choices:
        length = random.randint(0 if f.blank else 1, int(f.max_length) if f.max_length else 500)
        if filename:
            return get_randname_from_file(filename, length)
        else:
            return get_randname(length)
    elif 'DateTimeField' in mro_names:
        return datetime.now()
    elif 'DateField' in mro_names:
        return date.today()
    elif mro_names.intersection(['PositiveIntegerField', 'IntegerField', 'SmallIntegerField']) and not f._choices:
        return random.randint(0, 1000)
    elif mro_names.intersection(['ForeignKey', 'OneToOneField']):
        related_model = getattr(f.related, 'parent_model', f.related.model)
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
        return value
    elif 'ArrayField' in mro_names:
        if f._choices:
            return [random.choice(f._choices)[0] for _ in xrange(random.randint(0 if f.blank else 1,
                                                                                len(f._choices)))]
        elif 'IntegerArrayField' in mro_names:
            return [random.randint(0, 1000) for _ in xrange(random.randint(0 if f.blank else 1, 10))]
    elif f._choices:
        return random.choice(f._choices)[0]
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
        name = get_randname(length) + '.jpg'
        return ContentFile(content, name=name)


def generate_random_file_with_size(*args, **kwargs):
    raise DeprecationWarning('use get_random_file')


def get_file_with_name(filename):
    raise DeprecationWarning('use get_random_file with return_opened=True')


def generate_random_contentfile(*args, **kwargs):
    raise DeprecationWarning('use get_random_contentfile')


def get_random_contentfile(size=10, filename=None):
    if not filename:
        filename = get_randname(10, 'wd')
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
    if os.path.splitext(filename)[1].lower() in ('.tiff', '.jpg', '.jpeg', '.png', '.gif', '.svg') and size > 0:
        return get_random_image(path=path, size=size, rewrite=rewrite, return_opened=return_opened, filename=filename,
                                **kwargs)
    content = get_randname(size)
    if not path and return_opened:
        return ContentFile(content, filename)

    f = open(path, 'a')
    f.write(content)
    f.close()
    if return_opened:
        f = open(path, 'r')
    return f


def generate_random_image_with_size(*args, **kwargs):
    raise DeprecationWarning('use get_random_image')


def get_random_image(path='', size=10, width=None, height=None, rewrite=False, return_opened=True, filename=None,
                     **kwargs):
    """
    generate image file with size
    """
    size = convert_size_to_bytes(size)
    if path:
        filename = os.path.basename(path)
        if os.path.exists(path) and not rewrite:
            if abs(os.stat(path).st_size - size) / (size or 1) > 0.01:
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
                                        max(kwargs.get('max_width', 100),
                                            kwargs.get('min_width', 0) + 100))
        height = height or random.randint(kwargs.get('min_height', 1),
                                          max(kwargs.get('max_height', 100),
                                              kwargs.get('min_height', 0) + 100))
        if os.path.splitext(filename)[1] in ('.gif',):
            content = get_random_gif_content(size, width, height)
        elif os.path.splitext(filename)[1] in ('.svg',):
            content = get_random_svg_content(size, width, height)
        else:
            content = get_random_jpg_content(size, width, height)
    if not path and return_opened:
        return ContentFile(content, filename)
    f = open(path, 'ab')
    f.write(content)
    f.close()
    if return_opened:
        f = open(path, 'r')
    return f


def generate_random_image_content(*args, **kwargs):
    raise DeprecationWarning('use get_random_jpg_content')


def generate_random_image_contentfile(*args, **kwargs):
    raise DeprecationWarning('use get_random_image_contentfile')


def get_random_image_contentfile(size=10, width=1, height=1, filename=None):
    data = get_random_jpg_content(size, width, height)
    if not filename:
        filename = get_randname(10, 'wd')
    return ContentFile(data, filename)


def get_random_img_content(_format, size=10, width=1, height=1):
    try:
        import Image
    except ImportError:
        from PIL import Image
    size = convert_size_to_bytes(size)
    image = Image.new('RGB', (width, height), "#%06x" % random.randint(0, 0xFFFFFF))
    if getattr(Image, 'PILLOW_VERSION', getattr(Image, 'VERSION', '2.')).split('.')[0] == '1':
        from StringIO import StringIO
        output = StringIO()
    else:
        output = io.BytesIO()
    image.save(output, format=_format)
    content = output.getvalue()
    size -= len(content)
    if size > 0:
        content += bytearray(size)
    return content


def get_random_gif_content(size=10, width=1, height=1):
    return get_random_img_content('GIF', size, width, height)


def get_random_jpg_content(size=10, width=1, height=1):
    return get_random_img_content('JPEG', size, width, height)


def generate_random_bmp_image_with_size(*args, **kwargs):
    raise DeprecationWarning('use get_random_bmp_content or get_random_image')


def get_random_bmp_content(size=10,):
    """
    generate bmp content
    """
    size = convert_size_to_bytes(size)

    content = 'BM\x00\x00\x00\x00\x00\x00\x00\x006\x00\x00\x00(\x00\x00\x00'
    height = int((size / 3) ** 0.5 / 2) or 1
    width = int(size / 3 / height) + 1
    content += struct.pack('<L', width) + struct.pack('<L', height)
    content += '\x00\x00\x18\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    line = ''
    for column in range(width):
        line += struct.pack('<BBB', random.randint(1, 255), random.randint(1, 255), random.randint(1, 255))
    for row in range(height - 1, -1, -1):
        content += line
        row_mod = (width * 24 / 8) % 4
        if row_mod == 0:
            padding = 0
        else:
            padding = (4 - row_mod)
        padbytes = ''
        for _ in range(padding):
            x = struct.pack('<B', 0)
            padbytes = padbytes + x
        content += padbytes
    return content


def get_random_svg_content(size=10, width=1, height=1):
    """
    generates svg content
    """
    from StringIO import StringIO
    size = convert_size_to_bytes(size)
    doc = et.Element('svg', width=str(width), height=str(height), version='1.1', xmlns='http://www.w3.org/2000/svg')
    et.SubElement(doc, 'rect', width=str(width), height=str(height),
                  fill='rgb(%s, %s, %s)' % (random.randint(1, 255), random.randint(1, 255), random.randint(1, 255)))
    output = StringIO()
    header = '<?xml version=\"1.0\" standalone=\"no\"?>\n'\
             '<!DOCTYPE svg PUBLIC \"-//W3C//DTD SVG 1.1//EN\" \"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd\">\n'
    output.write(header)
    output.write(et.tostring(doc))
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
        l_args = ['/%s/' % a for a in args]
        for m in re.finditer(r'/\d+/', url):
            l.append(url[start:m.start()])
            start = m.end()
        l.append(url[start:])
        while len(l_args) < len(l):
            l_args.append(l_args[-1])
        return ''.join([item for tup in zip(l, l_args) for item in tup][:-1])
    try:
        res = resolve(url)
        if res.url_name:
            url = get_url(':'.join([res.namespace, res.url_name]), args=args)
        else:
            url = repl(url, args)
    except Resolver404:
        try:
            url = get_url(url, args)
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
    mro_names = [m.__name__ for m in model_name._meta.get_field_by_name(field)[0].__class__.__mro__]
    for obj in model_name.objects.all():
        file_from_obj = getattr(obj, field, None)
        if file_from_obj:
            full_path = os.path.join(settings.MEDIA_ROOT, file_from_obj.path)
            if os.path.exists(full_path):
                continue
            if verbosity > 2:
                print 'Generate file for path %s' % full_path
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
    text = text.encode('utf-8') if isinstance(text, unicode) else text
    words = [el.strip() for el in re.findall(r'\\+u[\\u0-9a-f ]{4,}', text) if len(el.strip()) > 5]
    unicode_symbol_path_regexp = r'\\+$|\\+u[0-9a-f]{0,3}$'
    while words:
        for el in words:
            if re.findall(unicode_symbol_path_regexp, el):
                _el = el[:-len(re.findall(unicode_symbol_path_regexp, el)[0])]
            else:
                _el = el
            text = text.replace(_el, _el.decode('unicode-escape').encode('utf-8'))
        words = [el.strip() for el in re.findall(r'\\+u[\\u0-9a-f ]{4,}', text) if len(el.strip()) > 5]
    text = re.sub(r'\\{2,}x', '\\x', text)
    return text


def use_in_all_tests(decorator):
    def decorate(cls):
        for attr in cls.__dict__:
            if callable(getattr(cls, attr)) and attr.startswith('test_'):
                setattr(cls, attr, decorator(getattr(cls, attr)))
        bases = cls.__bases__
        for base in bases:
            decorate(base)
        return cls
    return decorate
