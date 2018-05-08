# -*- coding=utf-8 -*-
import re
import sys
import unittest

from django.conf import settings
from django.test.runner import reorder_suite, DiscoverRunner
from datetime import datetime


WITH_HTML_REPORT = getattr(settings, 'TEST_HTML_REPORT', False)
if WITH_HTML_REPORT:
    try:
        from pyunitreport import HTMLTestRunner
        from ttoolly.html_report.report import CustomHtmlTestResult
    except ImportError:
        raise Exception('For html reports you should install pyunitreport:\n    pip install PyUnitReport')


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
    test_runner = HTMLTestRunner if WITH_HTML_REPORT else ParentRunner.test_runner

    mro_names = [m.__name__ for m in ParentRunner.__mro__]

    def get_resultclass(self):
        if WITH_HTML_REPORT:
            return CustomHtmlTestResult
        return super(RegexpTestSuiteRunner, self).get_resultclass()

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
                if 'DiscoverRunner' in self.mro_names:
                    if len(label.split('.')) > 3:
                        text_for_re += '$'
                    else:
                        text_for_re += '\..+$'
                full_re.append(text_for_re)
            full_re = '(^' + ')|(^'.join(full_re) + ')' if full_re else ''
            for el in full_suite._tests:
                module_name = el.__module__

                full_name = [module_name, el.__class__.__name__, el._testMethodName]
                full_name = '.'.join(full_name)
                if (full_re and re.findall(r'%s' % full_re, full_name)):
                    my_suite.addTest(el)
        if labels_for_suite:
            my_suite.addTests(ParentRunner.build_suite(self, labels_for_suite, extra_tests=None, **kwargs))
        return reorder_suite(my_suite, (unittest.TestCase,))

    def run_suite(self, suite, **kwargs):
        if WITH_HTML_REPORT:
            resultclass = self.get_resultclass()
            result = self.test_runner(
                output=getattr(settings, 'TEST_REPORT_OUTPUT_DIR', datetime.now().strftime('%Y-%m-%d %H-%M-%S')),
                verbosity=self.verbosity,
                failfast=self.failfast,
                resultclass=resultclass,
            ).run(suite)
        else:
            result = super(RegexpTestSuiteRunner, self).run_suite(suite, **kwargs)
        if self.verbosity > 2 and (result.errors or result.failures):
            st = unittest.runner._WritelnDecorator(sys.stderr)
            st.write('\n' + '*' * 29 + ' Run failed ' + '*' * 29 + '\n\n')
            st.write('python manage.py test %s' % ' '.join(
                ['.'.join([test.__class__.__module__, test.__class__.__name__, test._testMethodName]) for test, _ in
                 result.errors + result.failures]) + '\n\n')
            st.write('*' * 70 + '\n\n')
        return result
