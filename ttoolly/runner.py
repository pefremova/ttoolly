from django.test.simple import DjangoTestSuiteRunner, build_suite, build_test, get_app, get_apps
try:
    from django.test.simple import reorder_suite
    class DjRunner(DjangoTestSuiteRunner):
        pass
except:
    # django>=1.6
    from django.test.runner import reorder_suite, DiscoverRunner
    class DjRunner(DiscoverRunner):
        pass
from django.utils import unittest
import re


class RegexpTestSuiteRunner(DjRunner):

    mro_names = [m.__name__ for m in DjRunner.__mro__]

    def build_suite(self, test_labels, extra_tests=None, **kwargs):
        full_suite = DjRunner.build_suite(self, None, extra_tests=None, **kwargs)
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
                    app = get_app(label.split('.')[0])
                    text_for_re = text_for_re.replace(label.split('.')[0], app.__name__.split('.models')[0])
                elif 'DiscoverRunner' in self.mro_names:
                    if len(label.split('.')) > 3:
                        text_for_re += '$'
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
            my_suite.addTests(DjRunner.build_suite(self, labels_for_suite, extra_tests=None, **kwargs))
        return reorder_suite(my_suite, (unittest.TestCase,))
