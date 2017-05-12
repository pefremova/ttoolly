# -*- coding=utf-8 -*-
import re
import sys
import unittest

from django.conf import settings
from django.test.runner import reorder_suite, DiscoverRunner


def get_runner():
    test_runner_class = getattr(settings, 'TEST_RUNNER_PARENT', None)
    if not test_runner_class:
        return DiscoverRunner

    test_path = test_runner_class.split('.')
    test_module = __import__('.'.join(test_path[:-1]), {}, {}, str(test_path[-1]))
    test_runner = getattr(test_module, test_path[-1])
    return test_runner


ParentRunner = get_runner()


class RegexpTestSuiteRunner(ParentRunner):

    mro_names = [m.__name__ for m in ParentRunner.__mro__]

    def build_suite(self, test_labels, extra_tests=None, **kwargs):
        full_suite = ParentRunner.build_suite(self, None, extra_tests=None, **kwargs)

        my_suite = unittest.TestSuite()
        labels_for_suite = []
        if test_labels:
            full_re = []
            for label in test_labels:
                if re.findall(r'(^[\w\d_]+(?:\.[\w\d_]+)*$)', label) == [label]:
                    labels_for_suite.append(label)
                    continue
                text_for_re = label.replace('.', '\.').replace('*', '[^\.]+?')
                if 'DjangoTestSuiteRunner' in self.mro_names:
                    if len(label.split('.')) > 2:
                        text_for_re += '$'
                    else:
                        text_for_re += '\..+$'
                    app = get_app(label.split('.')[0])
                    text_for_re = text_for_re.replace(label.split('.')[0], app.__name__.split('.models')[0])
                elif 'DiscoverRunner' in self.mro_names:
                    if len(label.split('.')) > 3:
                        text_for_re += '$'
                    else:
                        text_for_re += '\..+$'
                full_re.append(text_for_re)
            full_re = '(^' + ')|(^'.join(full_re) + ')' if full_re else ''
            if 'DjangoTestSuiteRunner' in self.mro_names:
                apps = [app.__name__.split('.models')[0] for app in get_apps()]
            for el in full_suite._tests:
                module_name = el.__module__
                if 'DjangoTestSuiteRunner' in self.mro_names:
                    while module_name and module_name not in apps:
                        module_name = '.'.join(module_name.split('.')[:-1])
                full_name = [module_name, el.__class__.__name__, el._testMethodName]
                full_name = '.'.join(full_name)
                if (full_re and re.findall(r'%s' % full_re, full_name)):
                    my_suite.addTest(el)
        if labels_for_suite:
            my_suite.addTests(ParentRunner.build_suite(self, labels_for_suite, extra_tests=None, **kwargs))
        return reorder_suite(my_suite, (unittest.TestCase,))

    def run_suite(self, *args, **kwargs):
        result = super(RegexpTestSuiteRunner, self).run_suite(*args, **kwargs)
        if self.verbosity > 2 and (result.errors or result.failures):
            st = unittest.runner._WritelnDecorator(sys.stderr)
            st.write('\n' + '*' * 29 + ' Run failed ' + '*' * 29 + '\n\n')
            st.write('python manage.py test %s' % ' '.join(
                ['.'.join([test.__class__.__module__, test.__class__.__name__, test._testMethodName]) for test, _ in
                 result.errors + result.failures]) + '\n\n')
            st.write('*' * 70 + '\n\n')
        return result
