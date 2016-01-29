# -*- coding: utf-8 -*-
import os
import os.path
import re
import unittest
from datetime import date, datetime, time
from shutil import rmtree

from django.conf import settings
from django.core.files.base import File
from django.http import HttpResponse
from django.test import TestCase

from models import OtherModel, SomeModel
from ttoolly.models import TEMP_DIR, FormTestMixIn, GlobalTestMixIn
from ttoolly.utils import generate_sql, get_fixtures_data, get_random_domain_value, get_random_email_value


class TestGlobalTestMixInMethods(unittest.TestCase):

    maxDiff = None

    def setUp(self):
        class GlobalTestCase(GlobalTestMixIn, TestCase):
            pass
        self.btc = GlobalTestCase

        def _runTest():
            pass
        self.btc.runTest = _runTest
        self.btc = self.btc()
        if not os.path.exists(TEMP_DIR):
            os.mkdir(TEMP_DIR)

    def tearDown(self):
        rmtree(TEMP_DIR)

    def test_assert_form_equal_positive(self):
        fields_list_1 = ['test1', 'test2']
        fields_list_2 = ['test2', 'test1']
        try:
            self.btc.assert_form_equal(fields_list_1, fields_list_2)
        except:
            self.assertTrue(False, 'With raise')

    def test_assert_form_equal_not_need(self):
        fields_list_1 = ['test1', 'test2']
        fields_list_2 = ['test2', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2)
        msg = "Fields ['test1'] not need at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_not_need_2(self):
        fields_list_1 = ['test1', 'test2']
        fields_list_2 = []
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2)
        msg = "Fields ['test1', 'test2'] not need at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_not_at_form(self):
        fields_list_1 = ['test1']
        fields_list_2 = ['test1', 'test2', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2)
        msg = "Fields ['test2'] not at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_not_at_form_2(self):
        fields_list_1 = []
        fields_list_2 = ['test1', 'test2', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2)
        msg = "Fields ['test1', 'test2'] not at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_duplicate(self):
        fields_list_1 = ['test1', 'test2', 'test2']
        fields_list_2 = ['test1', 'test2', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2)
        msg = "Field 'test2' present at form 2 time(s) (should be 1)"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_not_need_and_not_at_form(self):
        fields_list_1 = ['test1', 'test2']
        fields_list_2 = ['test1', 'test3', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2)
        msg = "Fields ['test3'] not at form;\nFields ['test2'] not need at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_positive_with_custom_message(self):
        fields_list_1 = ['test1', 'test2']
        fields_list_2 = ['test2', 'test1']
        try:
            self.btc.assert_form_equal(fields_list_1, fields_list_2, u'тест')
        except:
            self.assertTrue(False, 'With raise')

    def test_assert_form_equal_not_need_with_custom_message(self):
        fields_list_1 = ['test1', 'test2']
        fields_list_2 = ['test2', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2, u'тест')
        msg = u"тест:\nFields ['test1'] not need at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_not_need_with_custom_message_2(self):
        fields_list_1 = ['test1', 'test2']
        fields_list_2 = []
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2, u'тест')
        msg = u"тест:\nFields ['test1', 'test2'] not need at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_not_at_form_with_custom_message(self):
        fields_list_1 = ['test1']
        fields_list_2 = ['test1', 'test2', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2, u'тест')
        msg = u"тест:\nFields ['test2'] not at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_not_at_form_with_custom_message_2(self):
        fields_list_1 = []
        fields_list_2 = ['test1', 'test2', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2, u'тест')
        msg = u"тест:\nFields ['test1', 'test2'] not at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_duplicate_with_custom_message(self):
        fields_list_1 = ['test1', 'test2', 'test2']
        fields_list_2 = ['test1', 'test2', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2, u'тест')
        msg = u"тест:\nField 'test2' present at form 2 time(s) (should be 1)"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_form_equal_not_need_and_not_at_form_with_custom_message(self):
        fields_list_1 = ['test1', 'test2']
        fields_list_2 = ['test1', 'test3', ]
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_form_equal(fields_list_1, fields_list_2, u'тест')
        msg = u"тест:\nFields ['test3'] not at form;\nFields ['test2'] not need at form"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_dict_equal(self):
        for dict1, dict2, message in (('q', {}, 'First argument is not a dictionary'),
                                      (1, {}, 'First argument is not a dictionary'),
                                      ((), {}, 'First argument is not a dictionary'),
                                      ([], {}, 'First argument is not a dictionary'),
                                      ({}, 'q', 'Second argument is not a dictionary'),
                                      ({}, 1, 'Second argument is not a dictionary'),
                                      ({}, (), 'Second argument is not a dictionary'),
                                      ({}, [], 'Second argument is not a dictionary'),
                                      ({'qwe': 123}, {'qwe': {'a': 1, }}, "[qwe]: 123 != {'a': 1}"),
                                      ({'qwe': {'a': 1, }}, {'qwe': 123}, "[qwe]: {'a': 1} != 123"),
                                      ({'qwe': {'a': 1, }}, {'qwe': {'a': 1, 'b': 1}}, "[qwe]:\n  Not in first dict: ['b']"),
                                      ({'qwe': {'a': 1, 'b': 1}}, {'qwe': {'a': 1}}, "[qwe]:\n  Not in second dict: ['b']"),
                                      ({'qwe': {'a': 1, 'b': 2}}, {'qwe': {'a': 2, 'b': 1}}, "[qwe]:\n  [qwe][a]: 1 != 2\n  [qwe][b]: 2 != 1"),
                                      ({'qwe': 'q', 'z': ''}, {'qwe': 1, }, "Not in second dict: ['z']\n[qwe]: 'q' != 1"),
                                      ({'qwe': u'й'}, {'qwe': u'йцу'}, u"[qwe]: й != йцу"),
                                      ({'qwe': 'й'}, {'qwe': 'йцу'}, u"[qwe]: й != йцу"),
                                      ({'qwe': u'й'}, {'qwe': 'йцу'}, u"[qwe]: %s != %s" % (repr(u'й'), repr('йцу'))),
                                      ({'qwe': 'й'}, {'qwe': u'йцу'}, u"[qwe]: %s != %s" % (repr('й'), repr(u'йцу'))),
                                      ({'qwe': ''}, {}, "Not in second dict: ['qwe']"),
                                      ({}, {'qwe': ''}, "Not in first dict: ['qwe']")):
            with self.assertRaises(AssertionError) as ar:
                self.btc.assert_dict_equal(dict1, dict2)
            self.assertEqual(ar.exception.__unicode__(), message)

    def test_assert_dict_equal_with_custom_message(self):
        for dict1, dict2, message in (('q', {}, 'First argument is not a dictionary'),
                                      (1, {}, 'First argument is not a dictionary'),
                                      ((), {}, 'First argument is not a dictionary'),
                                      ([], {}, 'First argument is not a dictionary'),
                                      ({}, 'q', 'Second argument is not a dictionary'),
                                      ({}, 1, 'Second argument is not a dictionary'),
                                      ({}, (), 'Second argument is not a dictionary'),
                                      ({}, [], 'Second argument is not a dictionary'),
                                      ({'qwe': 123}, {'qwe': {'a': 1, }}, "[qwe]: 123 != {'a': 1}"),
                                      ({'qwe': {'a': 1, }}, {'qwe': 123}, "[qwe]: {'a': 1} != 123"),
                                      ({'qwe': {'a': 1, }}, {'qwe': {'a': 1, 'b': 1}}, "[qwe]:\n  Not in first dict: ['b']"),
                                      ({'qwe': {'a': 1, 'b': 1}}, {'qwe': {'a': 1}}, "[qwe]:\n  Not in second dict: ['b']"),
                                      ({'qwe': {'a': 1, 'b': 2}}, {'qwe': {'a': 2, 'b': 1}}, "[qwe]:\n  [qwe][a]: 1 != 2\n  [qwe][b]: 2 != 1"),
                                      ({'qwe': 'q', 'z': ''}, {'qwe': 1, }, "Not in second dict: ['z']\n[qwe]: 'q' != 1"),
                                      ({'qwe': u'й'}, {'qwe': u'йцу'}, u"[qwe]: й != йцу"),
                                      ({'qwe': 'й'}, {'qwe': 'йцу'}, u"[qwe]: й != йцу"),
                                      ({'qwe': u'й'}, {'qwe': 'йцу'}, u"[qwe]: %s != %s" % (repr(u'й'), repr('йцу'))),
                                      ({'qwe': 'й'}, {'qwe': u'йцу'}, u"[qwe]: %s != %s" % (repr('й'), repr(u'йцу'))),
                                      ({'qwe': ''}, {}, "Not in second dict: ['qwe']"),
                                      ({}, {'qwe': ''}, "Not in first dict: ['qwe']")):
            with self.assertRaises(AssertionError) as ar:
                self.btc.assert_dict_equal(dict1, dict2, u'тест')
            self.assertEqual(ar.exception.__unicode__(), u'тест:\n' + message)

    def test_get_random_file(self):
        self.btc.with_files = False
        res = self.btc.get_random_file('some_file_field', 20)
        self.assertTrue(isinstance(res, File))
        self.assertEqual(len(os.path.basename(res.name)), 20)
        self.assertEqual(res.name.split('.'), [res.name])
        self.assertTrue(self.btc.with_files)

    def test_get_random_file_class_with_sefault_params(self):
        self.btc.with_files = False
        self.btc.default_params = {}
        res = self.btc.get_random_file('some_file_field', 20)
        self.assertTrue(isinstance(res, File))
        self.assertEqual(len(os.path.basename(res.name)), 20)
        self.assertEqual(res.name.split('.'), [res.name])
        self.assertTrue(self.btc.with_files)

    def test_get_random_file_image_field(self):
        """
        IMAGE_FIELDS
        """
        self.btc.with_files = False
        self.btc.IMAGE_FIELDS = ['test', 'some_image_field']
        res = self.btc.get_random_file('some_image_field', 20)
        self.assertTrue(isinstance(res, File))
        self.assertEqual(len(os.path.basename(res.name)), 20)
        self.assertEqual(os.path.splitext(os.path.basename(res.name))[1], '.jpg')
        self.assertTrue(self.btc.with_files)

    def test_is_file_field(self):
        self.assertFalse(self.btc.is_file_field('some_test'))
        self.assertTrue(self.btc.is_file_field('some_file'))
        self.btc.FILE_FIELDS = ['some_test', 'other']
        self.assertTrue(self.btc.is_file_field('some_test'))

    def test_is_file_field_with_default_params(self):
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'a')
        f.close()
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'r')
        self.btc.default_params = {'some_test': f}
        self.assertTrue(self.btc.is_file_field('some_test'))

    def test_is_file_field_with_default_params_add(self):
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'a')
        f.close()
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'r')
        self.btc.default_params_add = {'some_test': f}
        self.assertTrue(self.btc.is_file_field('some_test'))

    def test_is_file_field_with_default_params_edit(self):
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'a')
        f.close()
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'r')
        self.btc.default_params_edit = {'some_test': f}
        self.assertTrue(self.btc.is_file_field('some_test'))

    def test_is_file_field_with_not_file_param(self):
        self.btc.not_file = ['file', 'some_test']
        self.assertFalse(self.btc.is_file_field('file'))
        self.btc.FILE_FIELDS = ['some_test', 'other']
        self.assertFalse(self.btc.is_file_field('some_test'))

    def test_is_file_field_with_default_params_with_not_file_param(self):
        self.btc.not_file = ['some_test', ]
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'a')
        f.close()
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'r')
        self.btc.default_params = {'some_test': f}
        self.assertFalse(self.btc.is_file_field('some_test'))

    def test_is_file_field_with_default_params_add_with_not_file_param(self):
        self.btc.not_file = ['some_test', ]
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'a')
        f.close()
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'r')
        self.btc.default_params_add = {'some_test': f}
        self.assertFalse(self.btc.is_file_field('some_test'))

    def test_is_file_field_with_default_params_edit_with_not_file_param(self):
        self.btc.not_file = ['some_test', ]
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'a')
        f.close()
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'r')
        self.btc.default_params_edit = {'some_test': f}
        self.assertFalse(self.btc.is_file_field('some_test'))

    def test_get_params_according_to_type(self):
        el_1 = SomeModel(id=1)

        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'a')
        f.close()
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'r')
        el_2 = SomeModel(id=2, file_field=f)
        self.assertEqual(self.btc.get_params_according_to_type(f, f), (f, f))
        self.assertEqual(self.btc.get_params_according_to_type(el_1, el_2), (el_1, el_2))
        self.assertEqual(self.btc.get_params_according_to_type(datetime(2012, 3, 4, 3, 5), datetime(2015, 2, 5)),
                                                              (datetime(2012, 3, 4, 3, 5), datetime(2015, 2, 5)))
        self.assertEqual(self.btc.get_params_according_to_type(date(2012, 3, 4), date(2015, 2, 5)),
                                                              (date(2012, 3, 4), date(2015, 2, 5)))
        self.assertEqual(self.btc.get_params_according_to_type(time(12, 23, 4), time(3, 35, 29)),
                                                              (time(12, 23, 4), time(3, 35, 29)))
        self.assertEqual(self.btc.get_params_according_to_type(1, 2), (1, 2))
        self.assertEqual(self.btc.get_params_according_to_type(True, False), (True, False))
        self.assertEqual(self.btc.get_params_according_to_type(None, None), (None, None))
        self.assertEqual(self.btc.get_params_according_to_type('текст1', 'текст2'), ('текст1', 'текст2'))
        self.assertEqual(self.btc.get_params_according_to_type(u'текст1', u'текст2'), (u'текст1', u'текст2'))
        self.assertEqual(self.btc.get_params_according_to_type(u'текст1', 'текст2'), ('текст1', 'текст2'))
        self.assertEqual(self.btc.get_params_according_to_type('текст1', u'текст2'), ('текст1', 'текст2'))

        self.assertEqual(self.btc.get_params_according_to_type('текст1', 'on'), ('текст1', 'on'))
        self.assertEqual(self.btc.get_params_according_to_type(True, 'on'), (True, True))
        self.assertEqual(self.btc.get_params_according_to_type(True, ''), (True, False))
        self.assertEqual(self.btc.get_params_according_to_type(True, 'test'), (True, True))

        self.assertEqual(self.btc.get_params_according_to_type(datetime(2012, 3, 4, 3, 5), ''),
                                                              ('04.03.2012 03:05:00', ''))
        self.assertEqual(self.btc.get_params_according_to_type('', datetime(2012, 3, 4, 3, 5)),
                                                              ('', datetime(2012, 3, 4, 3, 5)))
        self.assertEqual(self.btc.get_params_according_to_type(date(2012, 3, 4), ''), ('04.03.2012', ''))
        self.assertEqual(self.btc.get_params_according_to_type('', date(2012, 3, 4)), ('', date(2012, 3, 4)))
        self.assertEqual(self.btc.get_params_according_to_type(time(12, 23, 4), ''), ('12:23:04', ''))
        self.assertEqual(self.btc.get_params_according_to_type('', time(12, 23, 4)), ('', time(12, 23, 4)))

        self.assertEqual(self.btc.get_params_according_to_type('1', 2), ('1', 2))
        self.assertEqual(self.btc.get_params_according_to_type(1, '2'), ('1', '2'))
        self.assertEqual(self.btc.get_params_according_to_type(None, ''), ('', ''))
        self.assertEqual(self.btc.get_params_according_to_type('', None), ('', ''))
        self.assertEqual(self.btc.get_params_according_to_type(1, None), ('1', ''))
        self.assertEqual(self.btc.get_params_according_to_type(None, 1), ('', 1))

        self.assertEqual(self.btc.get_params_according_to_type(el_1, 2), (el_1.id, 2))
        self.assertEqual(self.btc.get_params_according_to_type(el_1, '2'), (el_1.id, 2))

        self.assertEqual(self.btc.get_params_according_to_type(f, 'text'), ('file_for.ext', 'text'))
        self.assertEqual(self.btc.get_params_according_to_type('text', f), ('text', 'file_for_test.ext'))
        self.assertEqual(self.btc.get_params_according_to_type(el_1.file_field, 'text'), ('', 'text'))
        self.assertEqual(self.btc.get_params_according_to_type(el_2.file_field, 'text'), ('file_for.ext', 'text'))

    def test_update_params_not_need_update(self):
        self.btc.not_file = ('file',)
        params = {'test': 'qwe',
                  'file': 'test',
                  'qwe': [1, 2, 3]}
        self.btc.update_params(params)
        self.assertEqual(params, {'test': 'qwe',
                                  'file': 'test',
                                  'qwe': [1, 2, 3]})

    def test_update_params_with_file(self):
        self.btc.FILE_FIELDS = ('test',)
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'a')
        f.write('qwerty')
        f.close()
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'r')
        params = {'test': f}
        params['test'].seek(5)
        self.btc.update_params(params)
        self.assertEqual(params['test'].tell(), 0)

    def test_update_params_with_files_list(self):
        self.btc.FILE_FIELDS = ('test',)
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'a')
        f.write('qwerty')
        f.close()
        f = open(os.path.join(TEMP_DIR, 'file_for_test.ext'), 'r')
        f2 = open(os.path.join(TEMP_DIR, 'file_for_test2.ext'), 'a')
        f2.write('qwertyqwerty')
        f2.close()
        f2 = open(os.path.join(TEMP_DIR, 'file_for_test2.ext'), 'r')
        params = {'test': [f, f2]}
        params['test'][0].seek(5)
        params['test'][1].seek(10)
        self.btc.update_params(params)
        self.assertEqual(len(params), 1)
        self.assertEqual(params['test'][0].tell(), 0)

    def test_update_params_with_unique(self):
        self.btc.all_unique = {('test_field',): 'test_field'}
        self.btc.default_params = {'test_field': 'qwe'}
        params = {'test_field': 'qwe'}
        self.btc.update_params(params)
        self.assertNotEqual(params['test_field'], 'qwe')
        self.assertEqual(type(params['test_field']), unicode)

    def test_update_params_with_unique_not_change(self):
        self.btc.all_unique = {('test_field',): 'test_field'}
        self.btc.default_params = {'test_field': ''}
        params = {'test_field': ''}
        self.btc.update_params(params)
        self.assertEqual(params['test_field'], '')

    def test_assert_text_equal_by_symbol_at_start(self):
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_text_equal_by_symbol('qqwerty', 'qwerty')
        msg = "Not equal in position 1: 'qwerty' != 'werty'"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_text_equal_by_symbol_at_end(self):
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_text_equal_by_symbol('qwertyy', 'qwerty')
        msg = "Not equal in position 6: 'y' != ''"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_text_equal_by_symbol_at_end_2(self):
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_text_equal_by_symbol('qwerty', 'qwertyy')
        msg = "Not equal in position 6: '' != 'y'"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_text_equal_by_symbol_with_count(self):
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_text_equal_by_symbol(u'текст для !сравнения', u'текст для сравнения', 3)
        msg = u"Not equal in position 10: '!ср...' != 'сра...'"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_mail_count_positive(self):
        class M():
            def __init__(self, to):
                self.to = to
        try:
            self.btc.assert_mail_count([M(to='test@test.test'), M(to='test2@test.test')], 2)
        except Exception, e:
            self.assertTrue(False, 'With raise: %s' % str(e))

    def test_assert_mail_count_negative(self):
        class M():
            def __init__(self, to):
                self.to = to
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_mail_count([M(to='test@test.test')], 2)
        msg = u"Sent 1 mails expect of 2. To test@test.test"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_mail_count_many_mails_negative(self):
        class M():
            def __init__(self, to):
                self.to = to
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_mail_count([M(to='test@test.test'), M(to='second_test@test.test')], 1)
        msg = u"Sent 2 mails expect of 1. To second_test@test.test, test@test.test"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_get_value_for_field(self):
        res = self.btc.get_value_for_field(15, 'some_field_name')
        self.assertEqual(type(res), unicode)
        self.assertEqual(len(res), 15)

    def test_get_value_for_email_field(self):
        res = self.btc.get_value_for_field(25, 'email_field_name')
        self.assertEqual(type(res), str)
        self.assertIn('@', res)
        self.assertEqual(len(res), 25)

    def test_get_value_for_file_field(self):
        res = self.btc.get_value_for_field(25, 'file_field_name')
        self.assertTrue(isinstance(res, File))
        self.assertEqual(len(os.path.basename(res.name)), 25)

    def test_get_value_for_digital_field(self):
        self.btc.digital_fields = ('some_field_name',)
        res = self.btc.get_value_for_field(5, 'some_field_name')
        self.assertEqual(type(res), str)
        self.assertEqual(len(res), 5)
        self.assertTrue(int(res))

    def test_set_empty_value_for_field(self):
        from django.db.models.query import ValuesListQuerySet
        params = {'str_field': 'test',
                  'int_field': 1,
                  'list_field': [1, 2, 3],
                  'tuple_field': ('q', 'w'),
                  'query_set_field': ValuesListQuerySet([1, 2, 3])}
        for field in ('str_field', 'int_field'):
            _params = params.copy()
            self.btc.set_empty_value_for_field(_params, field)
            self.assertEqual(_params[field], '')
        for field in ('list_field', 'tuple_field', 'query_set_field'):
            _params = params.copy()
            self.btc.set_empty_value_for_field(_params, field)
            self.assertNotIn(field, _params.keys())

    def test_assert_xpath_count_positive(self):
        response = HttpResponse('<html><a href="/qwe">тест</a><a href="test">тест2</a></html>')
        try:
            self.btc.assert_xpath_count(response, '//a[@href="/qwe"]', 1)
        except Exception, e:
            self.assertTrue(False, 'With raise: %s' % str(e))

    def test_assert_xpath_count_wrong_status(self):
        response = HttpResponse('<html><a href="/qwe">тест</a><a href="test">тест2</a></html>', status=404)
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_xpath_count(response, '//a[@href="/qwe"]', 1)
        msg = u"Response status code 404 != 200"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_xpath_count_wrong_status_2(self):
        response = HttpResponse('<html><a href="/qwe">тест</a><a href="test">тест2</a></html>')
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_xpath_count(response, '//a[@href="/qwe"]', 1, 404)
        msg = u"Response status code 200 != 404"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_xpath_count_negative(self):
        response = HttpResponse('<html><a href="/qwe">тест</a><a href="test">тест2</a></html>')
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_xpath_count(response, '//a', 1)
        msg = u"Found 2 instances of '//a' (Should be 1)"
        self.assertEqual(ar.exception.__unicode__(), msg)

    def test_assert_xpath_count_xml_positive(self):
        response = HttpResponse('<?xml version="1.0"?><content><el><link>qwe</link><text>тест</text></el>'
                                              '<el><link>test</link><text>тест2</text></el></content>',
                                              content_type='application/xml')
        try:
            self.btc.assert_xpath_count(response, '//el/link', 2)
        except Exception, e:
            self.assertTrue(False, 'With raise: %s' % repr(e))

    def test_assert_xpath_count_xml_with_encode_positive(self):
        response = HttpResponse('<?xml version="1.0" encoding="utf-8"?><content><el><link>qwe</link><text>тест</text></el>'
                                              '<el><link>test</link><text>тест2</text></el></content>',
                                              content_type='application/xml')
        try:
            self.btc.assert_xpath_count(response, '//el/link', 2)
        except Exception, e:
            self.assertTrue(False, 'With raise: %s' % repr(e))

    def test_assert_object_fields(self):
        el_1 = SomeModel(text_field='текст 1')
        try:
            self.btc.assert_object_fields(el_1, {'text_field': 'текст 1'})
        except Exception, e:
            self.assertFalse(True, 'With exception: ' + str(e))

    def test_assert_object_fields_with_difference(self):
        el_1 = SomeModel(text_field='text')
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_object_fields(el_1, {'text_field': 'other text'})
        self.assertEqual(ar.exception.__unicode__(), "Values from object != expected values from dict:\n[text_field]: 'text' != 'other text'")

    def test_assert_object_fields_with_exclude(self):
        el_1 = SomeModel(text_field='текст 1')
        try:
            self.btc.assert_object_fields(el_1, {'text_field': 'текст 1'}, exclude=('text_field',))
        except Exception, e:
            self.assertFalse(True, 'With exception: ' + str(e))

    def test_assert_object_fields_with_exclude_in_class(self):
        el_1 = SomeModel(text_field='текст 1')
        self.btc.exclude_from_check = ('text_field',)
        try:
            self.btc.assert_object_fields(el_1, {'text_field': 'текст 1'})
        except Exception, e:
            self.assertFalse(True, 'With exception: ' + str(e))

    def test_assert_object_fields_with_difference_with_other_values(self):
        el_1 = SomeModel(text_field='text')
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_object_fields(el_1, {'text_field': 'text'},
                                          other_values={'file_field': 'test.test'})
        self.assertEqual(ar.exception.__unicode__(), "Values from object != expected values from dict:\n[file_field]: '' != 'test.test'", )

    def test_assert_object_fields_with_difference_with_other_values_in_class(self):
        el_1 = SomeModel(text_field='text')
        self.btc.other_values_for_check = {'file_field': 'test.test'}
        with self.assertRaises(AssertionError) as ar:
            self.btc.assert_object_fields(el_1, {'text_field': 'text'},)
        self.assertEqual(ar.exception.__unicode__(), "Values from object != expected values from dict:\n[file_field]: '' != 'test.test'")

    def test_assert_object_fields_with_not_existing_other_values(self):
        el_1 = SomeModel(text_field='текст 1')
        try:
            self.btc.assert_object_fields(el_1, {'text_field': 'текст 1'}, other_values={'qwe': 123})
        except Exception, e:
            self.assertFalse(True, 'With exception: ' + str(e))

    def test_assert_object_fields_with_not_existing_other_values_in_class(self):
        el_1 = SomeModel(text_field='текст 1')
        self.btc.other_values_for_check = {'qwe': 123}
        try:
            self.btc.assert_object_fields(el_1, {'text_field': 'текст 1'},)
        except Exception, e:
            self.assertFalse(True, 'With exception: ' + str(e))

    def test_errors_append(self):
        self.btc.errors = []
        try:
            int('q')
        except:
            self.btc.errors_append()
        self.assertEqual(len(self.btc.errors), 1)
        self.assertIn(u"int('q')\nValueError: invalid literal for int() with base 10: 'q'\n", self.btc.errors[0])

    def test_errors_append_empty(self):
        self.btc.errors = []
        self.btc.errors_append()
        self.assertEqual(self.btc.errors, [])

    def test_errors_append_with_text(self):
        self.btc.errors = []
        settings.COLORIZE_TESTS = False
        try:
            int('q')
        except:
            self.btc.errors_append(text='Тестовый текст')
        self.assertEqual(len(self.btc.errors), 1)
        self.assertIn(u"int('q')\nValueError: invalid literal for int() with base 10: 'q'\n", self.btc.errors[0])
        self.assertTrue(self.btc.errors[0].startswith(u'Тестовый текст:\n'))

    def test_errors_append_with_text_and_colorize(self):
        self.btc.errors = []
        settings.COLORIZE_TESTS = True
        try:
            int('q')
        except:
            self.btc.errors_append(text='Test text')
        self.assertEqual(len(self.btc.errors), 1)
        self.assertIn(u"int('q')\nValueError: invalid literal for int() with base 10: 'q'\n", self.btc.errors[0])
        self.assertTrue(self.btc.errors[0].startswith(u'\x1B[38;5;231mTest text:\n\x1B[0m'))

    def test_errors_append_with_text_and_colorize_and_color(self):
        self.btc.errors = []
        settings.COLORIZE_TESTS = True
        try:
            int('q')
        except:
            self.btc.errors_append(text='Test text', color=11)
        self.assertEqual(len(self.btc.errors), 1)
        self.assertIn(u"int('q')\nValueError: invalid literal for int() with base 10: 'q'\n", self.btc.errors[0])
        self.assertTrue(self.btc.errors[0].startswith(u'\x1B[38;5;11mTest text:\n\x1B[0m'))

    def test_custom_errors_append(self):
        self.btc.errors = []
        some_errors = []
        try:
            int('q')
        except:
            self.btc.errors_append(some_errors)
        self.assertEqual(self.btc.errors, [])
        self.assertEqual(len(some_errors), 1)
        self.assertIn(u"int('q')\nValueError: invalid literal for int() with base 10: 'q'\n", some_errors[0])

    def test_custom_errors_append_empty(self):
        self.btc.errors = []
        some_errors = []
        self.btc.errors_append(some_errors)
        self.assertEqual(self.btc.errors, [])
        self.assertEqual(some_errors, [])

    def test_custom_errors_append_with_text(self):
        self.btc.errors = []
        some_errors = []
        settings.COLORIZE_TESTS = False
        try:
            int('q')
        except:
            self.btc.errors_append(some_errors, text='Тестовый текст')
        self.assertEqual(len(some_errors), 1)
        self.assertEqual(self.btc.errors, [])
        self.assertIn(u"int('q')\nValueError: invalid literal for int() with base 10: 'q'\n", some_errors[0])
        self.assertTrue(some_errors[0].startswith(u'Тестовый текст:\n'))

    def test_custom_errors_append_with_text_and_colorize(self):
        self.btc.errors = []
        some_errors = []
        settings.COLORIZE_TESTS = True
        try:
            int('q')
        except:
            self.btc.errors_append(some_errors, text='Test text')
        self.assertEqual(len(some_errors), 1)
        self.assertEqual(self.btc.errors, [])
        self.assertIn(u"int('q')\nValueError: invalid literal for int() with base 10: 'q'\n", some_errors[0])
        self.assertTrue(some_errors[0].startswith(u'\x1B[38;5;231mTest text:\n\x1B[0m'))

    def test_custom_errors_append_with_text_and_colorize_and_color(self):
        self.btc.errors = []
        some_errors = []
        settings.COLORIZE_TESTS = True
        try:
            int('q')
        except:
            self.btc.errors_append(some_errors, text='Test text', color=11)
        self.assertEqual(len(some_errors), 1)
        self.assertEqual(self.btc.errors, [])
        self.assertIn(u"int('q')\nValueError: invalid literal for int() with base 10: 'q'\n", some_errors[0])
        self.assertTrue(some_errors[0].startswith(u'\x1B[38;5;11mTest text:\n\x1B[0m'))

    def test_formatted_assert_errors(self):
        self.btc.errors = []
        try:
            self.btc.formatted_assert_errors()
        except Exception, e:
            print str(e)
            self.assertTrue(False, 'With raise')

    def test_formatted_assert_errors_with_errors(self):
        self.btc.errors = ['some error text']
        with self.assertRaises(AssertionError) as ar:
            self.btc.formatted_assert_errors()
        self.assertEqual(ar.exception.__unicode__(), '\nsome error text')
        self.assertEqual(self.btc.errors, [])

    def test_formatted_assert_errors_with_many_errors(self):
        self.btc.errors = ['some error text', 'other error']
        with self.assertRaises(AssertionError) as ar:
            self.btc.formatted_assert_errors()
        self.assertEqual(ar.exception.__unicode__(), '\nsome error text\n\nother error')
        self.assertEqual(self.btc.errors, [])


class TestFormTestMixInMethods(unittest.TestCase):

    maxDiff = None

    def setUp(self):
        class FormTestCase(FormTestMixIn, TestCase): pass
        self.ftc = FormTestCase
        def _runTest():
            pass
        self.ftc.runTest = _runTest
        self.ftc = self.ftc()
        if not os.path.exists(TEMP_DIR):
            os.mkdir(TEMP_DIR)

    def tearDown(self):
        rmtree(TEMP_DIR)

    def test_get_error_message_for_max_length(self):
        self.assertEqual(self.ftc.get_error_message('max_length', 'text_field',
                                                    locals={'length': 20, 'current_length': 21}),
                         {'text_field': [u'Убедитесь, что это значение содержит не более 20 символов (сейчас 21).']})

    def test_get_error_message_for_max_file_filed_length(self):
        self.assertEqual(self.ftc.get_error_message('max_length', 'file_field',
                                                    locals={'length': 20, 'current_length': 21}),
                         {'file_field': [u'Убедитесь, что это имя файла содержит не более 20 символов (сейчас 21).']})

    def test_get_error_message_for_max_length_file(self):
        self.assertEqual(self.ftc.get_error_message('max_length_file', 'some_field',
                                                    locals={'length': 20, 'current_length': 21}),
                         {'some_field': [u'Убедитесь, что это имя файла содержит не более 20 символов (сейчас 21).']})

    def test_get_error_message_for_max_length_digital(self):
        self.assertEqual(self.ftc.get_error_message('max_length_digital', 'digital_field',
                                                    locals={'max_value': 20}),
                         {'digital_field': [u'Убедитесь, что это значение меньше либо равно 20.']})

    def test_get_error_message_for_min_length_digital(self):
        self.assertEqual(self.ftc.get_error_message('min_length_digital', 'digital_field',
                                                    locals={'min_value': 20}),
                         {'digital_field': [u'Убедитесь, что это значение больше либо равно 20.']})

    def test_get_error_message_for_wrong_value(self):
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field',),
                         {'some_field': [u'Выберите корректный вариант. Вашего варианта нет среди допустимых значений.']})
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field', locals={'value': 'qwe'}),
                         {'some_field': [u'Выберите корректный вариант. qwe нет среди допустимых значений.']})

    def test_get_error_message_for_wrong_value_int(self):
        self.assertEqual(self.ftc.get_error_message('wrong_value_int', 'int_field'),
                         {'int_field': [u'Введите целое число.']})

    def test_get_error_message_for_wrong_value_digital(self):
        self.assertEqual(self.ftc.get_error_message('wrong_value_digital', 'digital_field'),
                         {'digital_field': [u'Введите число.']})

    def test_get_error_message_for_unique_field(self):
        self.assertEqual(self.ftc.get_error_message('unique', 'some_field'),
                         {'some_field': [u'Объект с таким some_field уже существует.']})

    def test_get_error_message_for_max_length_with_custom(self):
        self.ftc.custom_error_messages = {'text_field': {'max_length': u'Тестовое сообщение об ошибке'}}
        self.assertEqual(self.ftc.get_error_message('max_length', 'text_field',),
                         {'text_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('max_length', 'text_field',
                                                    locals={'length': 20, 'current_length': 21}),
                         {'text_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('max_length', 'text_field', u'й'),
                         {'text_field': [u'Тестовое сообщение об ошибке']})
        self.ftc.custom_error_messages = {'text_field': {'max_length':
                                                         u'Тестовое сообщение об ошибке {length}, {current_length}'}}
        self.assertEqual(self.ftc.get_error_message('max_length', 'text_field',
                                                    locals={'length': 20, 'current_length': 21}),
                         {'text_field': [u'Тестовое сообщение об ошибке 20, 21']})

    def test_get_error_message_for_max_file_field_length_with_custom(self):
        self.ftc.custom_error_messages = {'file_field': {'max_length_file': u'Тестовое сообщение об ошибке'}}
        self.assertEqual(self.ftc.get_error_message('max_length', 'file_field',),
                         {'file_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('max_length', 'file_field',
                                                    locals={'length': 20, 'current_length': 21}),
                         {'file_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('max_length', 'file_field', u'й'),
                         {'file_field': [u'Тестовое сообщение об ошибке']})
        self.ftc.custom_error_messages = {'file_field': {'max_length_file':
                                                         u'Тестовое сообщение об ошибке {length}, {current_length}'}}
        self.assertEqual(self.ftc.get_error_message('max_length', 'file_field',
                                                    locals={'length': 20, 'current_length': 21}),
                         {'file_field': [u'Тестовое сообщение об ошибке 20, 21']})

        self.ftc.custom_error_messages = {'file_field': {'max_length': u'Тестовое сообщение об ошибке'}}
        self.assertEqual(self.ftc.get_error_message('max_length', 'file_field',),
                         {'file_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('max_length', 'file_field',
                                                    locals={'length': 20, 'current_length': 21}),
                         {'file_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('max_length', 'file_field', u'й'),
                         {'file_field': [u'Тестовое сообщение об ошибке']})
        self.ftc.custom_error_messages = {'file_field': {'max_length':
                                                         u'Тестовое сообщение об ошибке {length}, {current_length}'}}
        self.assertEqual(self.ftc.get_error_message('max_length', 'file_field',
                                                    locals={'length': 20, 'current_length': 21}),
                         {'file_field': [u'Тестовое сообщение об ошибке 20, 21']})

    def test_get_error_message_for_max_length_digital_with_custom(self):
        self.ftc.custom_error_messages = {
            'digital_field': {
                'max_length_digital': u'Тестовое сообщение об ошибке'
            }
        }
        self.assertEqual(self.ftc.get_error_message('max_length_digital', 'digital_field',),
                         {'digital_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('max_length_digital', 'digital_field',
                                                    locals={'max_value': 20}),
                         {'digital_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('max_length_digital', 'digital_field', u'й'),
                         {'digital_field': [u'Тестовое сообщение об ошибке']})

        self.ftc.custom_error_messages = {
            'digital_field': {
                'max_length_digital': u'Тестовое сообщение об ошибке {max_value}'
            }
        }
        self.assertEqual(self.ftc.get_error_message('max_length_digital', 'digital_field',
                                                    locals={'max_value': 20}),
                         {'digital_field': [u'Тестовое сообщение об ошибке 20']})

    def test_get_error_message_for_min_length_digital_with_custom(self):
        self.ftc.custom_error_messages = {
            'digital_field': {
                'min_length_digital': u'Тестовое сообщение об ошибке'
            }
        }
        self.assertEqual(self.ftc.get_error_message('min_length_digital', 'digital_field',),
                         {'digital_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('min_length_digital', 'digital_field',
                                                    locals={'min_value': 20}),
                         {'digital_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('min_length_digital', 'digital_field', u'й'),
                         {'digital_field': [u'Тестовое сообщение об ошибке']})

        self.ftc.custom_error_messages = {
            'digital_field': {
                'min_length_digital': u'Тестовое сообщение об ошибке {min_value}'
            }
        }
        self.assertEqual(self.ftc.get_error_message('min_length_digital', 'digital_field',
                                                    locals={'min_value': 20}),
                         {'digital_field': [u'Тестовое сообщение об ошибке 20']})

    def test_get_error_message_for_wrong_value_with_custom(self):
        self.ftc.custom_error_messages = {'some_field': {'wrong_value': u'Тестовое сообщение об ошибке'}}
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field',),
                         {'some_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field', 'qwe'),
                         {'some_field': [u'Тестовое сообщение об ошибке']})

        self.ftc.custom_error_messages = {'some_field': {'wrong_value': u'Тестовое сообщение об ошибке {test_value}'}}
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field', locals={'test_value': 'qwe'}),
                         {'some_field': [u'Тестовое сообщение об ошибке qwe']})

    def test_get_error_message_for_wrong_value_int_with_custom(self):
        self.ftc.custom_error_messages = {'int_field': {'wrong_value_int': u'Тестовое сообщение об ошибке'}}
        self.assertEqual(self.ftc.get_error_message('wrong_value_int', 'int_field',),
                         {'int_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('wrong_value_int', 'int_field', 'qwe'),
                         {'int_field': [u'Тестовое сообщение об ошибке']})

    def test_get_error_message_for_wrong_value_digital_with_custom(self):
        self.ftc.custom_error_messages = {'digital_field': {'wrong_value_digital': u'Тестовое сообщение об ошибке'}}
        self.assertEqual(self.ftc.get_error_message('wrong_value_digital', 'digital_field',),
                         {'digital_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('wrong_value_digital', 'digital_field', 'qwe'),
                         {'digital_field': [u'Тестовое сообщение об ошибке']})

    def test_get_error_message_for_unique_field_with_custom(self):
        self.ftc.custom_error_messages = {'some_field': {'unique': u'Тестовое сообщение об ошибке'}}
        self.assertEqual(self.ftc.get_error_message('unique', 'some_field',),
                        {'some_field': [u'Тестовое сообщение об ошибке']})
        self.assertEqual(self.ftc.get_error_message('unique', 'some_field', locals={'test_value': 'qwe'}),
                         {'some_field': [u'Тестовое сообщение об ошибке']})

        self.ftc.custom_error_messages = {'some_field': {'unique': u'Тестовое сообщение об ошибке {test_value}'}}
        self.assertEqual(self.ftc.get_error_message('unique', 'some_field', locals={'test_value': 'qwe'}),
                          {'some_field': [u'Тестовое сообщение об ошибке qwe']})

    def test_get_error_message_for_required_field_with_custom_error_field(self):
        self.assertEqual(self.ftc.get_error_message('required', 'some_field', error_field='other_field'),
                        {'other_field': [u'Обязательное поле.']})
        self.assertEqual(self.ftc.get_error_message('required', ('some_field_1', 'some_field_2'), error_field='other_field'),
                        {'other_field': [u'Обязательное поле.']})

    def test_get_error_message_for_required_field_with_multiple_field(self):
        self.assertEqual(self.ftc.get_error_message('required', ('some_field_1', 'some_field_2'),),
                        {'__all__': [u'Обязательное поле.']})

    def test_get_error_message_for_wrong_value_with_custom_in_list(self):
        self.ftc.custom_error_messages = {'some_field': {'wrong_value': [u'Тестовое сообщение об ошибке',
                                                                         u'Второе сообщение']}}
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field',),
                         {'some_field': [u'Тестовое сообщение об ошибке', u'Второе сообщение']})
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field', 'qwe'),
                         {'some_field': [u'Тестовое сообщение об ошибке', u'Второе сообщение']})

        self.ftc.custom_error_messages = {'some_field': {'wrong_value': [u'Тестовое сообщение об ошибке {test_value}',
                                                                         u'Второе сообщение']}}
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field', locals={'test_value': 'qwe'}),
                         {'some_field': [u'Тестовое сообщение об ошибке qwe', u'Второе сообщение']})

    def test_get_error_message_for_wrong_value_with_custom_in_dict(self):
        self.ftc.custom_error_messages = {'some_field': {'wrong_value': {'field1': u'Тестовое сообщение об ошибке',
                                                                         'field2': u'Второе сообщение'}}}
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field',),
                         {'field1': [u'Тестовое сообщение об ошибке'], 'field2': [u'Второе сообщение']})
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field', 'qwe'),
                         {'field1': [u'Тестовое сообщение об ошибке'], 'field2': [u'Второе сообщение']})

        self.ftc.custom_error_messages = {'some_field': {'wrong_value':
                                                         {'field1': u'Тестовое сообщение об ошибке {test_value}',
                                                          'field2': u'Второе сообщение'}}}
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field', locals={'test_value': 'qwe'}),
                         {'field1': [u'Тестовое сообщение об ошибке qwe'], 'field2': [u'Второе сообщение']})

    def test_get_error_message_for_wrong_value_with_custom_in_dict_with_list(self):
        self.ftc.custom_error_messages = {'some_field': {'wrong_value': {'field1': [u'Тестовое сообщение об ошибке'],
                                                                         'field2': u'Второе сообщение'}}}
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field',),
                         {'field1': [u'Тестовое сообщение об ошибке'], 'field2': [u'Второе сообщение']})
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field', 'qwe'),
                         {'field1': [u'Тестовое сообщение об ошибке'], 'field2': [u'Второе сообщение']})

        self.ftc.custom_error_messages = {'some_field': {'wrong_value':
                                                         {'field1': [u'Тестовое сообщение об ошибке {test_value}'],
                                                          'field2': u'Второе сообщение'}}}
        self.assertEqual(self.ftc.get_error_message('wrong_value', 'some_field', locals={'test_value': 'qwe'}),
                         {'field1': [u'Тестовое сообщение об ошибке qwe'], 'field2': [u'Второе сообщение']})

    def test_get_object_fields(self):
        some_element = SomeModel()
        other_element = OtherModel()
        self.assertEqual(sorted(self.ftc.get_object_fields(some_element)),
                         ['char_field', 'digital_field', 'email_field', 'file_field', 'id', 'int_field',
                          'many_related_field', 'text_field', 'unique_int_field'])
        self.assertEqual(sorted(self.ftc.get_object_fields(other_element)), ['id', 'related_name'])

    def test_assert_objects_equal(self):
        el_1 = SomeModel(text_field='текст')
        el_2 = SomeModel(text_field='текст')
        try:
            self.ftc.assert_objects_equal(el_1, el_2)
        except Exception, e:
            self.assertFalse(True, 'With exception: ' + str(e))

    def test_assert_objects_equal_with_difference(self):
        el_1 = SomeModel(text_field='text')
        el_2 = SomeModel(text_field='other text')
        with self.assertRaises(AssertionError) as ar:
            self.ftc.assert_objects_equal(el_1, el_2)
        self.assertIn('"text_field":\n', ar.exception.__unicode__())
        self.assertIn("AssertionError: 'text' != 'other text'", ar.exception.__unicode__())

    def test_assert_objects_equal_with_exclude(self):
        el_1 = SomeModel(text_field='текст 1')
        el_2 = SomeModel(text_field='текст 2')
        try:
            self.ftc.assert_objects_equal(el_1, el_2, exclude=('text_field',))
        except Exception, e:
            self.assertFalse(True, 'With exception: ' + str(e))

    def test_assert_objects_equal_with_exclude_from_check(self):
        el_1 = SomeModel(text_field='текст 1')
        el_2 = SomeModel(text_field='текст 2')
        self.ftc.exclude_from_check = ('text_field',)
        try:
            self.ftc.assert_objects_equal(el_1, el_2,)
        except Exception, e:
            self.assertFalse(True, 'With exception: ' + str(e))

    def test_get_all_fields_from_default_params(self):
        params = {'qwe': 1, 'pass_0': '', 'pass_1': '', 'photos-TOTAL_FORMS': 0,
                  'photos-INITIAL_FORMS': '', 'phptos-0-id': '', 'field_1': ''}
        self.assertEqual(self.ftc._get_all_fields_from_default_params(params),
                         ['field_1', 'pass', 'phptos-0-id', 'qwe'])


class TestUtils(unittest.TestCase):

    def setUp(self):
        if not os.path.exists(TEMP_DIR):
            os.mkdir(TEMP_DIR)

    def tearDown(self):
        rmtree(TEMP_DIR)

    def test_get_fixtures_data(self):
        f = open(os.path.join(TEMP_DIR, 'test.json'), 'a')
        f.write('''[
                    {"test_id": "1",
                    "model": "testmodel",
                    "fields": {
                            "field_text": "text",
                            "field_int": 2,
                            "field_bool": false,
                            "field_none": null,
                            "field_many": [1, 2, 3]}}
                  ]''')
        f.close()
        self.assertEqual(get_fixtures_data(os.path.join(TEMP_DIR, 'test.json')),
                         [{'fields': {'field_bool': False,
                                      'field_text': 'text',
                                      'field_int': 2,
                                      "field_none": None,
                                      "field_many": [1, 2, 3]},
                           'test_id': '1',
                           "model": "testmodel",
                           'pk': 'test_id'}])

    def test_get_fixtures_data_many_objects(self):
        f = open(os.path.join(TEMP_DIR, 'test.json'), 'a')
        f.write('''[
                    {"id": "1",
                    "model": "testmodel",
                    "fields": {"field": 1}},
                    {"id": "2",
                    "model": "testmodel",
                    "fields": {"field": 2}},
                    {"id": "1",
                    "model": "testmodel2",
                    "fields": {"field": 1}}
                  ]''')
        f.close()
        self.assertEqual(get_fixtures_data(os.path.join(TEMP_DIR, 'test.json')),
                         [{'fields': {'field': 1}, 'id': '1', "model": "testmodel", 'pk': 'id'},
                          {'fields': {'field': 2}, 'id': '2', "model": "testmodel", 'pk': 'id'},
                          {'fields': {'field': 1}, 'id': '1', "model": "testmodel2", 'pk': 'id'}])

    def test_generate_sql(self):
        data = [{'fields': {'field_bool': False,
                                      'field_text': 'text',
                                      'field_int': 2,
                                      "field_none": None},
                           'test_id': '1',
                           "model": "testmodel",
                           'pk': 'test_id'}]
        self.assertEqual(generate_sql(data),
                         'INSERT INTO testmodel (test_id, field_bool, field_none, field_text, field_int) ' + \
                         'VALUES (1, False, null, \'text\', \'2\');\n')

    def test_generate_sql_many_objects(self):
        data = [{'fields': {'field': 1}, 'id': '1', "model": "testmodel", 'pk': 'id'},
                          {'fields': {'field': 2}, 'id': '2', "model": "testmodel", 'pk': 'id'},
                          {'fields': {'field': 1}, 'id': '1', "model": "testmodel2", 'pk': 'id'}]
        self.assertEqual(generate_sql(data),
                         'INSERT INTO testmodel (id, field) VALUES (1, \'1\');\n' + \
                         'INSERT INTO testmodel (id, field) VALUES (2, \'2\');\n' + \
                         'INSERT INTO testmodel2 (id, field) VALUES (1, \'1\');\n')

    def test_get_random_domain_value(self):
        domain_re = re.compile(r"((?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?$)", re.IGNORECASE)

        for i in xrange(100):
            for n in xrange(200, 3, -1):
                res = get_random_domain_value(n)
                self.assertEqual(len(res), n, 'Wrong length of %s (%s != %s)' % (res, len(res), n))
                self.assertTrue(domain_re.search(res), 'Bad domain %s' % res)

    def test_get_random_email_value(self):
        email_re = re.compile(
            r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"  # dot-atom
            # quoted-string, see also http://tools.ietf.org/html/rfc2822#section-3.2.5
            r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-\011\013\014\016-\177])*"'
            r')@((?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?$)'  # domain
            r'|\[(25[0-5]|2[0-4]\d|[0-1]?\d?\d)(\.(25[0-5]|2[0-4]\d|[0-1]?\d?\d)){3}\]$', re.IGNORECASE)
        for i in xrange(100):
            for n in xrange(200, 5, -1):
                res = get_random_email_value(n)
                self.assertEqual(len(res), n, 'Wrong length of %s (%s != %s)' % (res, len(res), n))
                self.assertTrue(email_re.search(res), 'Bad email %s' % res)


if __name__ == '__main__':
    unittest.main()
