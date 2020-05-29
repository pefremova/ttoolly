# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

from copy import copy
from datetime import datetime, timedelta
from random import choice
import re

from django.conf import settings
from django.core import mail
from django.db import transaction
from django.db.models import Q
from django.utils.encoding import force_text

from builtins import str
from freezegun import freeze_time
from future.utils import viewitems, viewkeys
from past.builtins import basestring

from .utils import (format_errors, get_randname, get_random_email_value,
                    get_field_from_response, convert_size_to_bytes)
from .utils.decorators import (only_with, only_with_obj, only_with_files_params,
                               only_with_any_files_params)


class ListPositiveCases(object):

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
                self.assert_status_code(response.status_code, 200)
            except Exception:
                self.errors_append(text='For filter %s=%s' % (field, value))


class ListNegativeCases(object):

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
                    self.assert_status_code(response.status_code, 200)
                except Exception:
                    self.errors_append(text='For filter %s=%s' % (field, value))


class AddPositiveCases(object):

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
        Create object: fill all fields. Check with any filled field from one_of_fields groups
        """
        for group in self.one_of_fields_add:
            for field in group:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                only_independent_fields = set(self.all_fields_add).difference(viewkeys(self._depend_one_of_fields_add))

                fields_from_groups = set(viewkeys(self._depend_one_of_fields_add)
                                         ).difference(self._depend_one_of_fields_add[field])
                for group in self.one_of_fields_add:
                    _field = choice(group)
                    fields_from_groups = fields_from_groups.difference(self._depend_one_of_fields_add[_field])
                for f in set(viewkeys(self._depend_one_of_fields_add)).difference(fields_from_groups):
                    self.set_empty_value_for_field(params, f)
                self.fill_all_fields(tuple(only_independent_fields) + tuple(fields_from_groups), params)
                self.clean_depend_fields_add(params, field)
                self.fill_all_fields((field,), params)

                mail.outbox = []
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
    def test_add_object_max_length_values_positive(self):
        """
        Create object: fill all fields with maximum length values
        """
        other_fields = self.get_all_not_str_fields('add')

        fields_for_check = {k: self.max_fields_length.get(re.sub('\-\d+\-', '-0-', k), 100000)
                            for k in self.all_fields_add if re.sub('\-\d+\-', '-0-', k) not in other_fields}
        if not fields_for_check:
            self.skipTest('No any string fields')
        max_length_params = {}
        fields_for_clean = []
        for field, length in viewitems(fields_for_check):
            self.clean_depend_fields_add(max_length_params, field)
            max_length_params[field] = self.get_value_for_field(length, field)

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
                                                 for field, length in viewitems(fields_for_check)]))

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors and not set(viewkeys(fields_for_check)).intersection(viewkeys(self._depend_one_of_fields_add)):
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for k in set(viewkeys(max_length_params)).intersection((k for el in viewkeys(self.all_unique) for k in el)):
            max_length_params[k] = self.get_value_for_field(fields_for_check[k], field)

        for field, length in viewitems(fields_for_check):
            sp = transaction.savepoint()
            """if unique fields"""
            mail.outbox = []
            try:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.clean_depend_fields_add(params, field)
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
    def test_add_object_different_unique_values_positive(self):
        """
        Create object: only unique fields are different, other values are equal to existing object fields
        """
        already_in_check = {k: [] for k in self.unique_fields_add}
        checks_list = []
        for el in self.unique_fields_add:
            for el_field in set(el).difference(already_in_check[el]):
                fields_for_change = [el_field, ]
                already_in_check[el].append(el_field)
                for other_group in [g for g in self.unique_fields_add if g != el]:
                    other_group_fields = set(other_group).difference(
                        set(el).difference((el_field,))).difference(already_in_check[other_group])
                    if not other_group_fields:
                        if el_field in other_group:
                            other_group_fields = [el_field, ]
                        else:
                            other_group_fields = set(other_group).difference(set(el).difference((el_field,)))
                    other_group_field = list(other_group_fields)[0]
                    fields_for_change.append(other_group_field)
                    already_in_check[other_group].append(other_group_field)
                checks_list.append(list(set(fields_for_change)))

        checks_list = checks_list or ((),)
        for fields_for_change in checks_list:
            self.prepare_for_add()
            existing_obj = self.get_existing_obj()
            params = self.deepcopy(self.default_params_add)
            self.update_params(params)
            self.update_captcha_params(self.get_url(self.url_add), params)

            for field in fields_for_change:
                self.clean_depend_fields_add(params, el_field)
                value = params.get(field, None)
                n = 0
                existing_filters = Q(**{f: params[f] for f in fields_for_change[:fields_for_change.index(field)]})
                for el in self.unique_fields_add:
                    if field in el:
                        existing_filters |= Q(**{f: getattr(existing_obj, f) for f in el if f not in fields_for_change})
                existing_objs = self.get_obj_manager.filter(existing_filters)
                while n < 3 and (not value or existing_objs.filter(**{field: value}).exists()):
                    n += 1
                    value = self.get_value_for_field(None, field)
                if existing_objs.filter(**{field: value}).exists():
                    raise Exception(
                        "Can't generate value for field \"%s\" that not exists. Now is \"%s\"" % (field, value))

                params[field] = value

            self.fill_fields_from_obj(params, existing_obj,
                                      set([f for f in self.all_fields_add if f not in
                                           (self.hidden_fields_add or ())]).difference(fields_for_change))

            initial_obj_count = self.get_obj_manager.count()
            old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
            try:
                response = self.send_add_request(params)
                self.check_on_add_success(response, initial_obj_count, locals())
                new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                exclude = getattr(self, 'exclude_from_check_add', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.errors_append(text='Values in (%s) was changed, others equals to fields of existing object'
                                   '\nExisting values:\n%s\n\nNew params:\n%s' %
                                   (', '.join(fields_for_change),
                                    ',\n'.join('field "%s" with value "%s"' %
                                               (field,
                                                self.get_params_according_to_type(
                                                    self._get_field_value_by_name(existing_obj, field), '')[0])
                                               for field in fields_for_change),
                                    ',\n'.join('field "%s" with value "%s"' % (field, params[field])
                                               for field in fields_for_change if field in viewkeys(params))))

    @only_with_obj
    @only_with(('unique_fields_add', 'unique_with_case',))
    def test_add_object_unique_alredy_exists_in_other_case_positive(self):
        """
        Add object with unique field values, to values, that already used in other objects but in other case
        """
        for el in self.unique_fields_add:
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
                    if el_field in self.unique_with_case:
                        value = self.get_value_for_field(None, el_field)
                    else:
                        value = self._get_field_value_by_name(existing_obj, el_field)
                    params[el_field] = self.get_params_according_to_type(value, '')[0]
                    if el_field in self.unique_with_case:
                        self.get_obj_manager.filter(pk=existing_obj.pk).update(
                            **{el_field: getattr(value, existing_command)()})
                        params[el_field] = getattr(params[el_field], new_command)()
                existing_obj = self.get_obj_manager.get(pk=existing_obj.pk)
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
                                       (',\n'.join('field "%s" with value "%s"' %
                                                   (field,
                                                    self.get_params_according_to_type(
                                                        self._get_field_value_by_name(existing_obj, field), '')[0])
                                                   for field in el),
                                        ',\n'.join('field "%s" with value "%s"' % (field, params[field])
                                                   for field in el if field in viewkeys(params))))

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
            self.clean_depend_fields_add(max_value_params, field)
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
                self.clean_depend_fields_add(params, field)
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
            self.clean_depend_fields_add(min_value_params, field)
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
                self.clean_depend_fields_add(params, field)
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
            self.clean_depend_fields_add(max_count_params, field)
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
                self.clean_depend_fields_add(params, field)
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
            self.clean_depend_fields_add(max_size_params, field)
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
                self.clean_depend_fields_add(params, field)
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
    @only_with(('check_null', 'check_null_str_positive'))
    def test_add_object_str_with_null_positive(self):
        """
        Create object with \\x00 in str fields
        """
        other_fields = ['captcha', 'captcha_0', 'captcha_1'] + self.get_all_not_str_fields('add')
        other_fields.extend(list(getattr(self, 'file_fields_params_add', {}).keys()))

        fields_for_check = [k for k in self.all_fields_add if re.sub('\-\d+\-', '-0-', k) not in other_fields]
        if not fields_for_check:
            self.skipTest('No any string fields')

        test_params = {}
        fields_for_clean = []
        for field in fields_for_check:
            self.clean_depend_fields_add(test_params, field)
            test_params[field] = '\x00' + self.get_value_for_field(None, field)[1:]

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
        if not self.errors and not set([el[0] for el in fields_for_check]).intersection(viewkeys(self._depend_one_of_fields_add)):
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
                self.clean_depend_fields_add(params, field)
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
            self.clean_depend_fields_add(test_params, field)
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
                self.clean_depend_fields_add(params, field)
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
    @only_with('intervals')
    def test_add_object_some_intervals_positive(self):
        """
        Some intervals checks
        """
        for start_field, end_field, comparsion in self.intervals:
            if self.is_datetime_field(start_field) and self.is_datetime_field(end_field):
                values = ((0, 1),
                          (1, 0),
                          (1, -1),
                          (1, 1))
                if comparsion == '>=':
                    values += ((0, 0),)
            elif self.is_datetime_field(start_field) and self.is_date_field(end_field):
                values = ((1, None),)
                if comparsion == '>=':
                    values += ((0, None),)
            elif self.is_date_field(start_field) and self.is_datetime_field(end_field):
                values = ((0, 1),
                          (1, 0),
                          (1, 1))
                if comparsion == '>=':
                    values += ((0, 0),)
            elif self.is_date_field(start_field) and self.is_date_field(end_field):
                values = ((1, None),)
                if comparsion == '>=':
                    values += ((0, None),)
            if end_field not in self.required_fields_add and end_field + '_0' not in self.required_fields_add:
                values += ((None, None),)

            for date_diff, time_diff in values:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                start_value = self.get_value_for_field(None, start_field)
                if self.is_datetime_field(start_field):
                    start_value = datetime.strptime(start_value, getattr(settings, 'TEST_DATETIME_INPUT_FORMAT',
                                                                         settings.DATETIME_INPUT_FORMATS[0]))
                    if start_value.minute < 1:
                        start_value.replace(minute=1)
                elif self.is_date_field(start_field):
                    start_value = datetime.strptime(start_value, getattr(settings, 'TEST_DATE_INPUT_FORMAT',
                                                                         settings.DATE_INPUT_FORMATS[0])).date()
                self.fill_field(params, start_field, start_value)
                if date_diff is None:
                    end_value = None
                    self.set_empty_value_for_field(params, end_field)
                else:
                    end_value = start_value + timedelta(days=date_diff)
                    if time_diff is not None:
                        if not isinstance(end_value, datetime):
                            end_value = datetime.combine(end_value, datetime.min.time())
                        end_value += timedelta(minutes=time_diff)
                    elif isinstance(end_value, datetime):
                        end_value = end_value.date()
                    self.fill_field(params, end_field, end_value)
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_success(response, initial_obj_count, locals())
                    new_object = self.get_obj_manager.exclude(pk__in=old_pks)[0]
                    exclude = getattr(self, 'exclude_from_check_add', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.errors_append(text="Interval %s: %s - %s: %s" %
                                       (start_field, start_value, end_field, end_value))
                finally:
                    mail.outbox = []

    @only_with_obj
    @only_with('required_if_add')
    def test_add_object_related_required_fields_all_empty_positive(self):
        """
        Проверка зависимых обязательных полей: поля-инициаторы не заполнены, зависимые поля не заполнены
        """
        self.prepare_for_add()
        params = self.deepcopy(self.default_params_add)
        self.update_params(params)

        required_if = self.get_all_required_if_fields(self.required_if_add)

        for field in (required_if['lead'] + required_if['dependent'] + required_if['related']):
            self.set_empty_value_for_field(params, field)
        self.update_captcha_params(self.get_url(self.url_add), params)
        new_object = None
        initial_obj_count = self.get_obj_manager.count()
        old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
        try:
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks).last()
            exclude = getattr(self, 'exclude_from_check_add', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()

    @only_with_obj
    @only_with('required_if_add')
    def test_add_object_related_required_fields_lead_empty_dependent_filled_positive(self):
        """
        Проверка зависимых обязательных полей: поля-инициаторы не заполнены, зависимые поля заполнены
        """
        self.prepare_for_add()
        params = self.deepcopy(self.default_params_add)
        self.update_params(params)

        required_if = self.get_all_required_if_fields(self.required_if_add)

        for field in required_if['lead']:
            self.set_empty_value_for_field(params, field)

        self.fill_all_fields(required_if['dependent'] + required_if['related'], params)

        self.update_captcha_params(self.get_url(self.url_add), params)
        new_object = None
        initial_obj_count = self.get_obj_manager.count()
        old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
        try:
            response = self.send_add_request(params)
            self.check_on_add_success(response, initial_obj_count, locals())
            new_object = self.get_obj_manager.exclude(pk__in=old_pks).last()
            exclude = getattr(self, 'exclude_from_check_add', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()


class AddNegativeCases(object):

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
                self.assert_errors(response, error_message)
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
                self.assert_errors(response, error_message)
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
                self.assert_errors(response, error_message)
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
                self.assert_errors(response, error_message)
                self.check_on_add_error(response, initial_obj_count, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For params without group "%s"' % force_text(group))

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
                self.assert_errors(response, error_message)
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
                self.assert_errors(response, error_message)
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
                    self.assert_errors(response, self.get_error_message(message_type, field, locals=_locals))
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
                    self.assert_errors(response,
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

                self.assert_errors(response, error_message)
                self.check_on_add_error(response, initial_obj_count, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' %
                                                             (field, params[field]) for field
                                                             in el if field in viewkeys(params)))

        """values is in other case"""
        for el in self.unique_fields_add:
            self.prepare_for_add()
            other_fields = self.get_all_not_str_fields('add')
            if not set(el).difference(other_fields):
                continue
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
                if not el_field in other_fields and not el_field in self.unique_with_case:
                    params[el_field] = params[el_field].swapcase()
            initial_obj_count = self.get_obj_manager.count()
            try:
                response = self.send_add_request(params)
                error_message = self.get_error_message(message_type,
                                                       field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field,
                                                       locals=locals())
                self.assert_errors(response, error_message)
                self.check_on_add_error(response, initial_obj_count, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' %
                                                             (field, params[field]) for field
                                                             in el if field in viewkeys(params)))

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
                    self.assert_errors(response, error_message)
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
                    self.assert_errors(response, error_message)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

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
                    self.assert_errors(response, error_message)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

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
                    self.assert_errors(response, error_message)
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
                    self.assert_errors(response, error_message)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For filled %s fields from group %s' %
                                       (force_text(filled_group), force_text(group)))

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
                self.assert_errors(response, error_message)
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
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (current_count, field))

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
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
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
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For summary size %s (%s = %s * %s) in field %s' %
                                        (self.humanize_file_size(current_size), current_size, one_size,
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
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty file in field %s' % field)

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
                    self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))

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
                    self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
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
                    params[field] = f
                    initial_obj_count = self.get_obj_manager.count()
                    old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
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
        other_fields = ['captcha', 'captcha_0', 'captcha_1'] + self.get_all_not_str_fields('add')
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
                self.clean_depend_fields_add(params, field)
                params[field] = test_params[field]
                initial_obj_count = self.get_obj_manager.count()
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
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
            self.clean_depend_fields_add(params, field)
            f = self.get_random_file(field, filename='qwe\x00' + get_randname(10, 'wrd') + '.' +
                                     choice(field_dict.get('extensions', ['', ])))
            params[field] = f
            initial_obj_count = self.get_obj_manager.count()
            try:
                response = self.send_add_request(params)
                self.check_on_add_error(response, initial_obj_count, locals())
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
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
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
            except Exception:
                self.errors_append(text='\\x00 value in field %s' % field)

    @only_with_obj
    @only_with('intervals')
    def test_add_object_some_intervals_negative(self):
        """
        Wrong intervals checks
        """
        for start_field, end_field, comparsion in self.intervals:
            if self.is_datetime_field(start_field) and self.is_datetime_field(end_field):
                values = ((0, -1),
                          (-1, 0),
                          (-1, 1),
                          (-1, -1))
                if comparsion == '>':
                    values += ((0, 0),)
            elif self.is_datetime_field(start_field) and self.is_date_field(end_field):
                values = ((-1, None),)
                if comparsion == '>':
                    values += ((0, None),)
            elif self.is_date_field(start_field) and self.is_datetime_field(end_field):
                values = ((-1, 0),
                          (-1, 1),
                          (-1, -1))
                if comparsion == '>':
                    values += ((0, 0),)
            elif self.is_date_field(start_field) and self.is_date_field(end_field):
                values = ((-1, None),)
                if comparsion == '>':
                    values += ((0, None),)

            for date_diff, time_diff in values:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                start_value = self.get_value_for_field(None, start_field)
                if self.is_datetime_field(start_field):
                    start_value = datetime.strptime(start_value, getattr(settings, 'TEST_DATETIME_INPUT_FORMAT',
                                                                         settings.DATETIME_INPUT_FORMATS[0]))
                    if start_value.minute < 1:
                        start_value.replace(minute=1)
                elif self.is_date_field(start_field):
                    start_value = datetime.strptime(start_value, getattr(settings, 'TEST_DATE_INPUT_FORMAT',
                                                                         settings.DATE_INPUT_FORMATS[0])).date()
                self.fill_field(params, start_field, start_value)
                end_value = start_value + timedelta(days=date_diff)
                if time_diff is not None:
                    if not isinstance(end_value, datetime):
                        end_value = datetime.combine(end_value, datetime.min.time())
                    end_value += timedelta(minutes=time_diff)
                elif isinstance(end_value, datetime):
                    end_value = end_value.date()
                self.fill_field(params, end_field, end_value)
                initial_obj_count = self.get_obj_manager.count()
                old_pks = list(self.get_obj_manager.values_list('pk', flat=True))
                try:
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message('wrong_interval', end_field, locals=locals()))
                except Exception:
                    self.errors_append(text="Interval %s: %s - %s: %s" %
                                       (start_field, start_value, end_field, end_value))
                finally:
                    mail.outbox = []

    @only_with_obj
    @only_with('required_if_add')
    def test_add_object_empty_related_required_negative(self):
        """
        Проверка зависимых обязательных полей: поля-инициаторы заполнены, зависимые поля не заполнены
        """
        message_type = 'empty_required'
        related = self.get_all_required_if_fields(self.required_if_add)['related']

        for lead, dependent in viewitems(self.required_if_add):
            """только одиночные поля"""
            for field in [f for f in (dependent if isinstance(dependent, (list, tuple)) else (dependent,)) if not isinstance(f, (list, tuple))]:
                try:
                    self.prepare_for_add()
                    params = self.deepcopy(self.default_params_add)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url(self.url_add), params)
                    self.fill_all_fields((lead if isinstance(lead, (list, tuple)) else (lead,)) + related, params)
                    self.set_empty_value_for_field(params, field)
                    initial_obj_count = self.get_obj_manager.count()
                    response = self.send_add_request(params)
                    self.check_on_add_error(response, initial_obj_count, locals())
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assert_errors(response, error_message)
                except Exception:
                    self.errors_append(text='For filled "%s", empty field "%s"' % (lead, field))

            """обязательно хотя бы одно поле из группы (все пустые)"""
            for group in [f for f in (dependent if isinstance(dependent, (list, tuple)) else (dependent,)) if isinstance(f, (list, tuple))]:
                self.prepare_for_add()
                params = self.deepcopy(self.default_params_add)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_add), params)
                self.fill_all_fields((lead if isinstance(lead, (list, tuple)) else (lead,)) + related, params)
                for field in group:
                    if re.match('^(%s)-\d+-.+?' % ('|'.join(getattr(self, 'inline_params', {}).keys())), field):
                        self.fill_all_fields(('%s-TOTAL_FORMS' % field.split('-')[0],), params)
                    self.set_empty_value_for_field(params, field)
                initial_obj_count = self.get_obj_manager.count()
                try:
                    response = self.send_add_request(params)
                    error_message = self.get_error_message(message_type, group, error_field=self.non_field_error_key,
                                                           locals=locals())
                    self.assert_errors(response, error_message)
                    self.check_on_add_error(response, initial_obj_count, locals())
                except Exception:
                    self.errors_append(text='For filled "%s", empty group "%s"' % (lead, group))


class EditPositiveCases(object):

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
        self.update_params(params)
        self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
        prepared_depends_fields = self.prepare_depend_from_one_of(
            self.one_of_fields_edit) if self.one_of_fields_edit else {}
        only_independent_fields = set(self.all_fields_edit).difference(viewkeys(prepared_depends_fields))
        for field in viewkeys(prepared_depends_fields):
            self.set_empty_value_for_field(params, field)
        self.fill_all_fields(list(only_independent_fields) + self.required_fields_edit +
                             self._get_required_from_related(self.required_related_fields_edit), params)
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
        Edit object: fill all fields. Check for any filled field from one_of_fields
        """
        for group in self.one_of_fields_edit:
            for field in group:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                only_independent_fields = set(self.all_fields_edit).difference(
                    viewkeys(self._depend_one_of_fields_edit))
                fields_from_groups = set(viewkeys(self._depend_one_of_fields_edit)
                                         ).difference(self._depend_one_of_fields_edit[field])
                for group in self.one_of_fields_edit:
                    _field = choice(group)
                    fields_from_groups = fields_from_groups.difference(self._depend_one_of_fields_edit[_field])
                for f in set(viewkeys(self._depend_one_of_fields_edit)).difference(fields_from_groups):
                    self.set_empty_value_for_field(params, f)
                self.fill_all_fields(tuple(only_independent_fields) + tuple(fields_from_groups), params)
                self.clean_depend_fields_edit(params, field)
                self.fill_all_fields((field,), params)
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
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
    def test_edit_object_max_length_values_positive(self):
        """
        Edit object: fill all fields with maximum length values
        """
        obj_for_edit = self.get_obj_for_edit()
        other_fields = self.get_all_not_str_fields('edit')

        fields_for_check = {k: self.max_fields_length.get(re.sub('\-\d+\-', '-0-', k), 100000)
                            for k in self.all_fields_edit if re.sub('\-\d+\-', '-0-', k) not in other_fields}
        if not fields_for_check:
            self.skipTest('No any string fields')

        max_length_params = {}
        file_fields = []

        fields_for_clean = []
        for field, length in viewitems(fields_for_check):
            self.clean_depend_fields_edit(max_length_params, field)
            max_length_params[field] = self.get_value_for_field(length, field)
            if self.is_file_field(field):
                file_fields.append(field)

        sp = transaction.savepoint()
        try:
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
            params.update(max_length_params)
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)

            if self.second_save_available and file_fields:
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                self.update_params(params)
                params.update(max_length_params)
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
                                                 for field, length in viewitems(fields_for_check)]))
        finally:
            mail.outbox = []

        """Дальнейшие отдельные проверки только если не прошла совместная и полей много"""
        if not self.errors and not set(viewkeys(fields_for_check)).intersection(viewkeys(self._depend_one_of_fields_edit)):
            return
        if len(fields_for_check) == 1:
            self.formatted_assert_errors()

        for k in set(viewkeys(max_length_params)).intersection((k for el in viewkeys(self.all_unique) for k in el)):
            max_length_params[k] = self.get_value_for_field(fields_for_check[k], field)

        for field, length in viewitems(fields_for_check):
            sp = transaction.savepoint()
            try:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)
                self.clean_depend_fields_edit(params, field)
                params[field] = max_length_params[field]
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

                if self.second_save_available and self.is_file_field(field):
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
    def test_edit_object_different_unique_values_positive(self):
        """
        Change object: only unique fields are different, other values are equal to existing object fields
        """
        already_in_check = {k: [] for k in self.unique_fields_edit}
        checks_list = []
        for el in self.unique_fields_edit:
            for el_field in set(el).difference(already_in_check[el]):
                fields_for_change = [el_field, ]
                already_in_check[el].append(el_field)
                for other_group in [g for g in self.unique_fields_add if g != el]:
                    other_group_fields = set(other_group).difference(
                        set(el).difference((el_field,))).difference(already_in_check[other_group])
                    if not other_group_fields:
                        if el_field in other_group:
                            other_group_fields = [el_field, ]
                        else:
                            other_group_fields = set(other_group).difference(set(el).difference((el_field,)))
                    other_group_field = list(other_group_fields)[0]
                    fields_for_change.append(other_group_field)
                    already_in_check[other_group].append(other_group_field)
                checks_list.append(list(set(fields_for_change)))

        checks_list = checks_list or ((),)
        for fields_for_change in checks_list:
            obj_for_edit = self.get_obj_for_edit()
            existing_obj = self.get_other_obj_with_filled(fields_for_change, obj_for_edit)
            params = self.deepcopy(self.default_params_edit)
            self.update_params(params)
            self.update_captcha_params(self.get_url_for_negative(self.url_edit, (obj_for_edit.pk,)), params)

            for field in fields_for_change:
                self.clean_depend_fields_edit(params, el_field)
                value = params.get(field, None)
                n = 0
                existing_filters = Q(**{f: params[f] for f in fields_for_change[:fields_for_change.index(field)]})
                for el in self.unique_fields_edit:
                    if field in el:
                        existing_filters |= Q(**{f: getattr(existing_obj, f) for f in el if f not in fields_for_change})
                existing_objs = self.get_obj_manager.exclude(pk=obj_for_edit.pk).filter(existing_filters)
                while n < 3 and (not value or existing_objs.filter(**{field: value}).exists()):
                    n += 1
                    value = self.get_value_for_field(None, field)
                if existing_objs.filter(**{field: value}).exists():
                    raise Exception(
                        "Can't generate value for field \"%s\" that not exists. Now is \"%s\"" % (field, value))
                params[field] = value

            self.fill_fields_from_obj(params, existing_obj,
                                      set([f for f in self.all_fields_edit if f not in
                                           (self.hidden_fields_edit or ())]).difference(fields_for_change))
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.check_on_edit_success(response, locals())
                new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                exclude = getattr(self, 'exclude_from_check_edit', [])
                self.assert_object_fields(new_object, params, exclude=exclude)
            except Exception:
                self.errors_append(text='Values in (%s) was changed, others equals to fields of existing object'
                                   '\nExisting values:\n%s\n\nNew params:\n%s' %
                                   (', '.join(fields_for_change),
                                    ',\n'.join('field "%s" with value "%s"' %
                                               (field,
                                                self.get_params_according_to_type(
                                                    self._get_field_value_by_name(existing_obj, field), '')[0])
                                               for field in fields_for_change),
                                    ',\n'.join('field "%s" with value "%s"' % (field, params[field])
                                               for field in fields_for_change if field in viewkeys(params))))

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
                    self.clean_depend_fields_edit(params, el_field)

                    if el_field in self.unique_with_case:
                        value = self.get_value_for_field(None, el_field)
                    else:
                        value = self._get_field_value_by_name(existing_obj, el_field)
                    params[el_field] = self.get_params_according_to_type(value, '')[0]
                    if el_field in self.unique_with_case:
                        self.get_obj_manager.filter(pk=existing_obj.pk).update(
                            **{el_field: getattr(value, existing_command)()})
                        params[el_field] = getattr(params[el_field], new_command)()
                existing_obj = self.get_obj_manager.get(pk=existing_obj.pk)
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.check_on_edit_success(response, locals())
                    new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    exclude = getattr(self, 'exclude_from_check_edit', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For existing values:\n%s\nnew params:\n%s' %
                                       (',\n'.join('field "%s" with value "%s"' %
                                                   (field,
                                                    self.get_params_according_to_type(
                                                        self._get_field_value_by_name(existing_obj, field), '')[0])
                                                   for field in el),
                                        ',\n'.join('field "%s" with value "%s"' % (field, params[field])
                                                   for field in el if field in viewkeys(params))))
                finally:
                    mail.outbox = []

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
            self.clean_depend_fields_edit(min_value_params, field)
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
                self.clean_depend_fields_edit(params, field)
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
            self.clean_depend_fields_edit(max_value_params, field)
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
                self.clean_depend_fields_edit(params, field)
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
            self.clean_depend_fields_edit(max_count_params, field)
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
                self.clean_depend_fields_edit(params, field)
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
            self.clean_depend_fields_edit(max_size_params, field)
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
                self.clean_depend_fields_edit(params, field)
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
    @only_with('intervals')
    def test_edit_object_some_intervals_positive(self):
        """
        Some intervals checks
        """
        for start_field, end_field, comparsion in self.intervals:
            if self.is_datetime_field(start_field) and self.is_datetime_field(end_field):
                values = ((0, 1),
                          (1, 0),
                          (1, -1),
                          (1, 1))
                if comparsion == '>=':
                    values += ((0, 0),)
            elif self.is_datetime_field(start_field) and self.is_date_field(end_field):
                values = ((1, None),)
                if comparsion == '>=':
                    values += ((0, None),)
            elif self.is_date_field(start_field) and self.is_datetime_field(end_field):
                values = ((0, 1),
                          (1, 0),
                          (1, 1))
                if comparsion == '>=':
                    values += ((0, 0),)
            elif self.is_date_field(start_field) and self.is_date_field(end_field):
                values = ((1, None),)
                if comparsion == '>=':
                    values += ((0, None),)
            if end_field not in self.required_fields_edit and end_field + '_0' not in self.required_fields_edit:
                values += ((None, None),)

            for date_diff, time_diff in values:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_edit, (obj_for_edit.pk,)), params)
                start_value = self.get_value_for_field(None, start_field)
                if self.is_datetime_field(start_field):
                    start_value = datetime.strptime(start_value, getattr(settings, 'TEST_DATETIME_INPUT_FORMAT',
                                                                         settings.DATETIME_INPUT_FORMATS[0]))
                    if start_value.minute < 1:
                        start_value.replace(minute=1)
                elif self.is_date_field(start_field):
                    start_value = datetime.strptime(start_value, getattr(settings, 'TEST_DATE_INPUT_FORMAT',
                                                                         settings.DATE_INPUT_FORMATS[0])).date()
                self.fill_field(params, start_field, start_value)
                if date_diff is None:
                    end_value = None
                    self.set_empty_value_for_field(params, end_field)
                else:
                    end_value = start_value + timedelta(days=date_diff)
                    if time_diff is not None:
                        if not isinstance(end_value, datetime):
                            end_value = datetime.combine(end_value, datetime.min.time())
                        end_value += timedelta(minutes=time_diff)
                    elif isinstance(end_value, datetime):
                        end_value = end_value.date()
                    self.fill_field(params, end_field, end_value)
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.check_on_edit_success(response, locals())
                    new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    exclude = getattr(self, 'exclude_from_check_edit', [])
                    self.assert_object_fields(new_object, params, exclude=exclude)
                except Exception:
                    self.errors_append(text="Interval %s: %s - %s: %s" %
                                       (start_field, start_value, end_field, end_value))
                finally:
                    mail.outbox = []

    @only_with_obj
    @only_with('required_if_edit')
    def test_edit_object_related_required_fields_all_empty_positive(self):
        """
        Dependent required fields: main and dependent fields are empty
        """
        obj_for_edit = self.get_obj_for_edit()
        params = self.deepcopy(self.default_params_edit)
        self.update_params(params)

        required_if = self.get_all_required_if_fields(self.required_if_edit)
        for field in (required_if['lead'] + required_if['dependent'] + required_if['related']):
            self.set_empty_value_for_field(params, field)
        self.update_captcha_params(self.get_url(self.url_edit, (obj_for_edit.pk,)), params)
        try:
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()

    @only_with_obj
    @only_with('required_if_edit')
    def test_edit_object_related_required_fields_lead_empty_dependent_filled_positive(self):
        """
        Dependent required fields: empty main fields, filled dependent fields
        """
        obj_for_edit = self.get_obj_for_edit()
        params = self.deepcopy(self.default_params_edit)
        self.update_params(params)

        required_if = self.get_all_required_if_fields(self.required_if_edit)

        for field in required_if['lead']:
            self.set_empty_value_for_field(params, field)
        self.fill_all_fields(required_if['dependent'] + required_if['related'], params)

        self.update_captcha_params(self.get_url(self.url_edit, (obj_for_edit.pk,)), params)
        new_object = None
        try:
            response = self.send_edit_request(obj_for_edit.pk, params)
            self.check_on_edit_success(response, locals())
            new_object = self.get_obj_manager.get(pk=obj_for_edit.pk)
            exclude = getattr(self, 'exclude_from_check_edit', [])
            self.assert_object_fields(new_object, params, exclude=exclude)
        except Exception:
            self.errors_append()


class EditNegativeCases(object):

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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assert_errors(response, error_message)
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
            obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(
                    message_type, group, error_field=self.non_field_error_key, locals=locals())
                self.assert_errors(response, error_message)
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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assert_errors(response, error_message)
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
            obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(
                    message_type, group, error_field=self.non_field_error_key, locals=locals())
                self.assert_errors(response, error_message)
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
                self.assert_status_code(response.status_code, self.status_code_not_exist)
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
                self.assert_status_code(response.status_code, self.status_code_not_exist)
                if self.status_code_not_exist == 200:
                    """for Django 1.11 admin"""
                    self.assertEqual(self.get_all_form_messages(response), self.get_error_message('not_exist', '')[''])
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='POST request. For value %s' % value)

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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assert_errors(response, error_message)
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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assert_errors(response, error_message)
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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    _locals = {'field': field, 'value': value}
                    error_message = self.get_error_message(message_type, field, locals=_locals)
                    self.assert_errors(response, error_message)
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
            obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)

            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field)
                self.assert_errors(response, error_message)
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
            other_fields = self.get_all_not_str_fields('edit')
            if not set(el).difference(other_fields):
                continue
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
                if not el_field in other_fields and not el_field in self.unique_with_case:
                    params[el_field] = params[el_field].swapcase()
            obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, field if not field.endswith(self.non_field_error_key) else el,
                                                       error_field=field)
                self.assert_errors(response, error_message)
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s' % ', '.join('field "%s" with value "%s"' % (field, params[field])
                                                             for field in el if field in viewkeys(params)))

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
                    obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
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
                    obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assert_errors(response, error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

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
                    obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assert_errors(response, error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For value "%s" in field "%s"' % (value, field))

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
                    obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assert_errors(response, error_message)
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
                value = params.get(field, None)
                old_value = self.get_params_according_to_type(self._get_field_value_by_name(obj_for_edit, field), '')[0]
                n = 0
                while n < 3 and (not value or value == old_value):
                    n += 1
                    value = self.get_value_for_field(None, field)
                params[field] = value
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
                    obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, group, locals=locals())
                    self.assert_errors(response, error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For filled %s fields from group %s' %
                                       (force_text(filled_group), force_text(group)))

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
            obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
            try:
                response = self.send_edit_request(obj_for_edit.pk, params)
                error_message = self.get_error_message(message_type, name, locals=locals())
                self.assert_errors(response, error_message)
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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For %s files in field %s' % (current_count, field))

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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                response = self.send_edit_request(obj_for_edit.pk, params)
                self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
                self.check_on_edit_error(response, obj_for_edit, locals())
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For empty file in field %s' % field)

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
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For field %s filename %s' % (field, filename))

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
                    obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))

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
                    obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.assert_errors(response, self.get_error_message(message_type, field, locals=locals()))
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.savepoint_rollback(sp)
                    self.errors_append(text='For image width %s, height %s in field %s' % (width, height, field))

    @only_with_obj
    @only_with('intervals')
    def test_edit_object_some_intervals_negative(self):
        """
        Wrong intervals checks
        """
        for start_field, end_field, comparsion in self.intervals:
            if self.is_datetime_field(start_field) and self.is_datetime_field(end_field):
                values = ((0, -1),
                          (-1, 0),
                          (-1, 1),
                          (-1, -1))
                if comparsion == '>':
                    values += ((0, 0),)
            elif self.is_datetime_field(start_field) and self.is_date_field(end_field):
                values = ((-1, None),)
                if comparsion == '>':
                    values += ((0, None),)
            elif self.is_date_field(start_field) and self.is_datetime_field(end_field):
                values = ((-1, 0),
                          (-1, 1),
                          (-1, -1))
                if comparsion == '>':
                    values += ((0, 0),)
            elif self.is_date_field(start_field) and self.is_date_field(end_field):
                values = ((-1, None),)
                if comparsion == '>':
                    values += ((0, None),)

            for date_diff, time_diff in values:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_edit, (obj_for_edit.pk,)), params)
                start_value = self.get_value_for_field(None, start_field)
                if self.is_datetime_field(start_field):
                    start_value = datetime.strptime(start_value, getattr(settings, 'TEST_DATETIME_INPUT_FORMAT',
                                                                         settings.DATETIME_INPUT_FORMATS[0]))
                    if start_value.minute < 1:
                        start_value.replace(minute=1)
                elif self.is_date_field(start_field):
                    start_value = datetime.strptime(start_value, getattr(settings, 'TEST_DATE_INPUT_FORMAT',
                                                                         settings.DATE_INPUT_FORMATS[0])).date()
                self.fill_field(params, start_field, start_value)
                end_value = start_value + timedelta(days=date_diff)
                if time_diff is not None:
                    if not isinstance(end_value, datetime):
                        end_value = datetime.combine(end_value, datetime.min.time())
                    end_value += timedelta(minutes=time_diff)
                elif isinstance(end_value, datetime):
                    end_value = end_value.date()
                self.fill_field(params, end_field, end_value)
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    self.assertEqual(self.get_all_form_errors(response),
                                     self.get_error_message('wrong_interval', end_field, locals=locals()))
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.errors_append(text="Interval %s: %s - %s: %s" %
                                       (start_field, start_value, end_field, end_value))
                finally:
                    mail.outbox = []

    @only_with_obj
    @only_with('required_if_edit')
    def test_edit_object_empty_related_required_negative(self):
        """
        Dependent required fields: filled main fields, not filled dependent fields
        """
        message_type = 'empty_required'
        related = self.get_all_required_if_fields(self.required_if_edit)['related']

        for lead, dependent in viewitems(self.required_if_edit):

            """only simple fields"""
            for field in [f for f in (dependent if isinstance(dependent, (list, tuple)) else (dependent,)) if not isinstance(f, (list, tuple))]:
                try:
                    obj_for_edit = self.get_obj_for_edit()
                    params = self.deepcopy(self.default_params_edit)
                    self.update_params(params)
                    self.update_captcha_params(self.get_url(self.url_edit, (obj_for_edit.pk,)), params)
                    self.fill_all_fields((lead if isinstance(lead, (list, tuple)) else (lead,)) + related, params)
                    self.set_empty_value_for_field(params, field)
                    obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assert_errors(response, error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.errors_append(text='For filled "%s", empty field "%s"' % (lead, field))

            """group fields (all are empty)"""
            for group in [f for f in (dependent if isinstance(dependent, (list, tuple)) else (dependent,)) if isinstance(f, (list, tuple))]:
                obj_for_edit = self.get_obj_for_edit()
                params = self.deepcopy(self.default_params_edit)
                self.update_params(params)
                self.update_captcha_params(self.get_url(self.url_edit, (obj_for_edit.pk,)), params)
                self.fill_all_fields((lead if isinstance(lead, (list, tuple)) else (lead,)) + related, params)
                for field in group:
                    self.set_empty_value_for_field(params, field)
                obj_for_edit = self.get_obj_manager.get(pk=obj_for_edit.pk)
                try:
                    response = self.send_edit_request(obj_for_edit.pk, params)
                    error_message = self.get_error_message(message_type, field, locals=locals())
                    self.assert_errors(response, error_message)
                    self.check_on_edit_error(response, obj_for_edit, locals())
                except Exception:
                    self.errors_append(text='For filled "%s", empty group "%s"' % (lead, group))


class DeletePositiveCases(object):

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


class DeleteNegativeCases(object):

    @only_with_obj
    def test_delete_not_exists_object_negative(self):
        """
        Try delete object with invalid id
        """
        for value in ('9999999', '2147483648', 'qwe', 'йцу'):
            sp = transaction.savepoint()
            try:
                response = self.send_delete_request(value)
                self.assert_status_code(response.status_code, self.status_code_not_exist)
                if self.status_code_not_exist == 200:
                    """for Django 1.11 admin"""
                    self.assertEqual(self.get_all_form_messages(response), self.get_error_message('not_exist', '')[''])
            except Exception:
                self.savepoint_rollback(sp)
                self.errors_append(text='For value %s error' % value)


class RemovePositiveCases(object):

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


class RemoveNegativeCases(object):

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
                self.assert_status_code(response.status_code, 200)
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
                self.assert_status_code(response.status_code, 200)
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
            self.assert_status_code(response.status_code, 200)
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
            self.assert_status_code(response.status_code, self.status_code_not_exist)
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


class ChangePasswordPositiveCases(object):

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
            user = self.get_obj_manager.get(pk=user.pk)
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


class ChangePasswordNegativeCases(object):

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
                user = self.get_obj_manager.get(pk=user.pk)
                response = self.send_change_password_request(user.pk, params)
                self.check_negative(user, params, response)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assert_errors(response, error_message)
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
                user = self.get_obj_manager.get(pk=user.pk)
                response = self.send_change_password_request(user.pk, params)
                self.check_negative(user, params, response)
                error_message = self.get_error_message(message_type, field, locals=locals())
                self.assert_errors(response, error_message)
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
        user = self.get_obj_manager.get(pk=user.pk)
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
        user = self.get_obj_manager.get(pk=user.pk)
        try:
            response = self.send_change_password_request(user.pk, params)
            self.check_negative(user, params, response)
            error_message = self.get_error_message('min_length', self.field_password,)
            self.assert_errors(response, error_message)
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
        user = self.get_obj_manager.get(pk=user.pk)
        try:
            response = self.send_change_password_request(user.pk, params)
            self.check_negative(user, params, response)
            error_message = self.get_error_message('max_length', self.field_password,)
            self.assert_errors(response, error_message)
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
            user = self.get_obj_manager.get(pk=user.pk)
            try:
                response = self.send_change_password_request(user.pk, params)
                self.check_negative(user, params, response)
                error_message = self.get_error_message('wrong_value', self.field_password,)
                self.assert_errors(response, error_message)
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
        user = self.get_obj_manager.get(pk=user.pk)
        try:
            response = self.send_change_password_request(user.pk, params)
            self.check_negative(user, params, response)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('wrong_old_password', self.field_old_password))
        except Exception:
            self.errors_append()

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
                user = self.get_obj_manager.get(pk=user.pk)
                password_value = new_value(value, change_type)
                params = self.deepcopy(self.password_params)
                self.update_params(params)
                self.update_captcha_params(self.get_url_for_negative(self.url_change_password, (user.pk,)), params)
                params.update({self.field_password: password_value,
                               self.field_password_repeat: password_value})
                user = self.get_obj_manager.get(pk=user.pk)
                try:
                    response = self.send_change_password_request(user.pk, params)
                    self.check_negative(user, params, response)
                    error_message = self.get_error_message(
                        'wrong_password_similar', self.field_password, locals=locals())
                    self.assert_errors(response, error_message)
                except Exception:
                    self.errors_append(text='New password value "%s" is similar to user.%s = "%s"' %
                                       (password_value, field, value))


class ResetPasswordPositiveCases(object):

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
            user = self.get_obj_manager.get(pk=user.pk)
            self.assertTrue(user.check_password(self.current_password), 'Password was changed after request code')
            self.check_after_password_change_request(locals())
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
                user = self.get_obj_manager.get(pk=user.pk)
                self.assertTrue(user.check_password(params[self.field_password]),
                                'Password not changed to "%s"' % params[self.field_password])
                self.check_after_password_change(locals())
            except Exception:
                self.errors_append(text='New password value "%s"' % value)

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

    def test_reset_password_page_positive(self):
        """
        Check password change page fields
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        codes = self.get_codes(user)
        user = self.get_obj_manager.get(pk=user.pk)
        try:
            response = self.client.get(self.get_url(self.url_reset_password, codes),
                                       params, follow=True, **self.additional_params)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assert_objects_equal(new_user, user)
            form_fields = self.get_fields_list_from_response(response)
            try:
                """not set because of one field can be on form many times"""
                self.assert_form_equal(form_fields['visible_fields'], self.change_fields)
            except Exception:
                self.errors_append(text='For visible fields')

            fields_helptext = getattr(self, 'fields_helptext_add', {})
            for field_name, text in viewitems(fields_helptext):
                if field_name not in self.change_fields:
                    continue
                try:
                    field = get_field_from_response(response, field_name)
                    self.assertEqual(field.help_text, text)
                except Exception:
                    self.errors_append(text='Helptext for field %s' % field_name)
        except Exception:
            self.errors_append()


class ResetPasswordNegativeCases(object):

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

    @only_with('request_reset_retries')
    def test_request_reset_password_not_max_retries_negative(self):
        """
        Try reset password. No captcha field: not max retries
        """
        params = self.deepcopy(self.request_password_params)
        self.update_captcha_params(self.get_url(self.url_reset_password_request), params)
        params[self.field_username] += 'q'
        self.clean_blacklist()
        self.set_host_blacklist(host='127.0.0.1', count=self.request_reset_retries - 2)
        try:
            response = self.send_reset_password_request(params)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('wrong_value_email', self.field_username))
            self.check_blacklist_on_negative(response, False)
        except Exception:
            self.errors_append()

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
        self.set_user_inactive(user)
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
        self.set_user_inactive(user)
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
                self.clean_blacklist()
                self.set_host_blacklist(host='127.0.0.1', count=self.request_reset_retries or 1)
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
            user = self.get_obj_manager.get(pk=user.pk)
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
            user = self.get_obj_manager.get(pk=user.pk)
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
        user = self.get_obj_manager.get(pk=user.pk)
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
        user = self.get_obj_manager.get(pk=user.pk)
        try:
            response = self.send_change_after_reset_password_request(codes, params)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assert_objects_equal(new_user, user)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('min_length', self.field_password))
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
        user = self.get_obj_manager.get(pk=user.pk)
        try:
            response = self.send_change_after_reset_password_request(codes, params)
            new_user = self.get_obj_manager.get(pk=user.pk)
            self.assert_objects_equal(new_user, user)
            self.assertEqual(self.get_all_form_errors(response),
                             self.get_error_message('max_length', self.field_password))
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
            user = self.get_obj_manager.get(pk=user.pk)
            try:
                response = self.send_change_after_reset_password_request(codes, params)
                new_user = self.get_obj_manager.get(pk=user.pk)
                self.assert_objects_equal(new_user, user)
                self.assertEqual(self.get_all_form_errors(response),
                                 self.get_error_message('wrong_value', self.field_password))
            except Exception:
                self.errors_append(text='New password "%s"' % value)

    def test_reset_password_inactive_user_negative(self):
        """
        Try reset password as inactive user
        """
        user = self.get_obj_for_edit()
        params = self.deepcopy(self.password_params)
        self.set_user_inactive(user)
        codes = self.get_codes(user)
        user = self.get_obj_manager.get(pk=user.pk)
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
            self.assert_status_code(response.status_code, 404)
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
                user = self.get_obj_manager.get(pk=user.pk)
                params = self.deepcopy(self.password_params)
                self.update_params(params)
                params.update({self.field_password: password_value,
                               self.field_password_repeat: password_value})
                codes = self.get_codes(user)
                user = self.get_obj_manager.get(pk=user.pk)
                try:
                    response = self.send_change_after_reset_password_request(codes, params)
                    new_user = self.get_obj_manager.get(pk=user.pk)
                    self.assert_objects_equal(new_user, user)
                    error_message = self.get_error_message(
                        'wrong_password_similar', self.field_password, locals=locals())
                    self.assert_errors(response, error_message)
                except Exception:
                    self.errors_append(text='New password value "%s" is similar to user.%s = "%s"' %
                                       (password_value, field, value))


class LoginPositiveCases(object):

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

    @only_with('blacklist_model')
    def test_login_blacklist_user_positive(self):
        """
        login as user from blacklist with correct data
        """
        self.set_host_blacklist(host='127.0.0.1', count=self.login_retries or 1)
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


class LoginNegativeCases(object):

    def test_login_wrong_password_negative(self):
        """
        login with invalid password
        """
        params = self.deepcopy(self.default_params)
        self.add_csrf(params)
        params[self.field_password] = self.password + 'q'
        self.set_host_pre_blacklist_login(host='127.0.0.1')
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
        self.set_host_pre_blacklist_login(host='127.0.0.1')
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
    def test_login_blacklist_user_empty_captcha_negative(self):
        """
        login as user from blacklist with empty captcha
        """
        self.set_host_blacklist(host='127.0.0.1', count=self.login_retries or 1)
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
                self.set_host_blacklist(host='127.0.0.1', count=self.login_retries or 1)
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
        self.set_host_pre_blacklist_login(host='127.0.0.1')
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
            self.set_host_pre_blacklist_login(host='127.0.0.1')
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
            self.set_host_pre_blacklist_login(host='127.0.0.1')
            try:
                response = self.send_login_request(params)
                self.assertEqual(self.get_all_form_errors(response), self.get_error_message('without_required', field))
                self.check_is_not_authenticated()
                self.check_response_on_negative(response)
                self.check_blacklist_on_negative(response)
            except Exception:
                self.errors_append(text="For empty field %s" % field)

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
