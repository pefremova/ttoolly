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


if getattr(settings, 'TEST_RUNNER_PARENT', '') == 'xmlrunner.extra.djangotestrunner.XMLTestRunner':
    from xmlrunner.result import _XMLTestResult, safe_unicode, _TestInfo
    from xmlrunner.runner import XMLTestRunner

    original_report_testcase = _XMLTestResult._report_testcase

    @staticmethod
    def _report_testcase(test_result, xml_testsuite, xml_document):
        original_report_testcase(test_result, xml_testsuite, xml_document)
        testcase = xml_testsuite.childNodes[-1]
        description = xml_document.createElement('description')
        testcase.appendChild(description)
        description_text = safe_unicode(test_result.test_description)
        _XMLTestResult._createCDATAsections(xml_document, description, description_text)
        tags = xml_document.createElement('tags')
        for tag_name in test_result.tags:
            tag = xml_document.createElement('tag')
            tag.appendChild(xml_document.createTextNode(tag_name))
            tags.appendChild(tag)
        testcase.appendChild(tags)

    _XMLTestResult._report_testcase = _report_testcase

    class XMLInfoClass(_TestInfo):

        def __init__(self, test_result, test_method, *args, **kwargs):
            super().__init__(test_result, test_method, *args, **kwargs)
            tags = set(getattr(test_method, 'tags', set()))
            test_fn_name = getattr(test_method, '_testMethodName', str(test_method))
            test_fn = getattr(test_method, test_fn_name, test_method)
            test_fn_tags = set(getattr(test_fn, 'tags', set()))
            self.tags = tags.union(test_fn_tags)

    class CustomXMLTestRunner(XMLTestRunner):

        def _make_result(self):
            return self.resultclass(self.stream, self.descriptions, self.verbosity, self.elapsed_times,
                                    infoclass=XMLInfoClass)


def get_runner():
    test_runner_class = getattr(settings, 'TEST_RUNNER_PARENT', None)
    if not test_runner_class:
        return DiscoverRunner

    test_path = test_runner_class.split('.')
    test_module = __import__('.'.join(test_path[:-1]), {}, {}, str(test_path[-1]))
    test_runner = getattr(test_module, test_path[-1])
    return test_runner


ParentRunner = get_runner()


def filter_suite_by_decorators(suite, verbosity=1):
    new_suite = unittest.TestSuite()
    for el in suite:
        need_skip = False
        fn = getattr(el, el._testMethodName)
        if getattr(fn, '__unittest_skip__', False):
            need_skip = True
            skip_text = fn.__unittest_skip_why__
        else:
            for decorator in reversed(getattr(fn, 'decorators', ())):
                check = getattr(decorator, 'check', None)
                if check:
                    need_skip = not(check(el))
                    if need_skip:
                        skip_text = decorator.skip_text
                        break
        if not need_skip:
            new_suite.addTest(el)
        elif verbosity > 1:
            st = unittest.runner._WritelnDecorator(sys.stderr)
            st.write('Skip {test_name}: {skip_text}\n'.format(test_name='.'.join([el.__class__.__module__,
                                                                                  el.__class__.__name__,
                                                                                  el._testMethodName]),
                                                              skip_text=skip_text))
    return new_suite


class RegexpTestSuiteRunner(ParentRunner):

    parallel = 1

    def get_test_runner(self):
        if WITH_HTML_REPORT:
            return HTMLTestRunner
        if getattr(settings, 'TEST_RUNNER_PARENT', '') == 'xmlrunner.extra.djangotestrunner.XMLTestRunner':
            return CustomXMLTestRunner
        return ParentRunner.test_runner

    mro_names = [m.__name__ for m in ParentRunner.__mro__]

    def __init__(self, *args, **kwargs):
        super(RegexpTestSuiteRunner, self).__init__(*args, **kwargs)
        self.tags_rule = kwargs['tags_rule']
        if self.tags_rule:
            self.tags = []
            self.exclude_tags = []
        self.parallelism = [int(el) for el in kwargs['parallelism'].split('/')] if kwargs['parallelism'] else None
        self.test_runner = self.get_test_runner()

    @classmethod
    def add_arguments(cls, parser):
        super(RegexpTestSuiteRunner, cls).add_arguments(parser)
        parser.add_argument(
            '--tags', action='store', dest='tags_rule',
            help='Tags boolean rule. Example: "low AND middle AND NOT high"',
        )
        parser.add_argument(
            '--parallelism', dest='parallelism', default=None,
            help='Part of tests (if parallel by ci). For example 2/5 - second part of five. Will be ignored if parallel > 1',
        )

    def convert_by_parallel(self, suite):
        if self.parallel > 1 or not self.parallelism or self.parallelism[1] == 1:
            return suite

        def get_chunk(count, chunk_n):
            if chunk_n >= count:
                return []
            length = len(suite._tests)
            chunk_len, additional = divmod(length, count)
            return suite._tests[chunk_n * chunk_len:(chunk_n + 1) * chunk_len + (additional if chunk_n == count - 1 else 0)]

        return unittest.TestSuite(get_chunk(self.parallelism[1], self.parallelism[0] - 1))

    def get_resultclass(self):
        if WITH_HTML_REPORT:
            return CustomHtmlTestResult
        return super(RegexpTestSuiteRunner, self).get_resultclass()

    def build_suite(self, test_labels, extra_tests=None, **kwargs):
        real_parallel = self.parallel
        self.parallel = 1

        labels_for_suite = []
        for label in test_labels:
            if re.findall(r'(^[\w\d_]+(?:\.[\w\d_]+)*$)', label) == [label]:
                labels_for_suite.append(label)
            else:
                while label:
                    label = '.'.join(label.split('.')[:-1])
                    if re.findall(r'(^[\w\d_]+(?:\.[\w\d_]+)*$)', label) == [label]:
                        labels_for_suite.append(label)
                        break

        full_suite = super(RegexpTestSuiteRunner, self).build_suite(labels_for_suite, extra_tests=None, **kwargs)
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
        else:
            my_suite = full_suite
        if labels_for_suite:
            my_suite.addTests(ParentRunner.build_suite(self, labels_for_suite, extra_tests=None, **kwargs))

        if self.tags_rule:
            from .for_runner import algebra
            parsed = algebra.parse(self.tags_rule).simplify()
            my_suite = filter_tests_by_tags_rule(my_suite, parsed)

        if getattr(settings, 'TEST_SKIP_SILENT', False):
            my_suite = filter_suite_by_decorators(my_suite, self.verbosity)

        suite = reorder_suite(my_suite, (unittest.TestCase,))

        self.parallel = real_parallel
        if self.parallel > 1:
            parallel_suite = self.parallel_test_suite(suite, self.parallel, self.failfast)

            # Since tests are distributed across processes on a per-TestCase
            # basis, there's no need for more processes than TestCases.
            parallel_units = len(parallel_suite.subsuites)
            if self.parallel > parallel_units:
                self.parallel = parallel_units

            # If there's only one TestCase, parallelization isn't needed.
            if self.parallel > 1:
                suite = parallel_suite

        return self.convert_by_parallel(suite)

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
                 result.errors + result.failures if hasattr(test, '_testMethodName')]) + '\n\n')
            st.write('*' * 70 + '\n\n')
        return result


def filter_tests_by_tags_rule(suite, parsed_rule):
    suite_class = type(suite)
    filtered_suite = suite_class()

    for test in suite:
        if isinstance(test, suite_class):
            filtered_suite.addTests(filter_tests_by_tags_rule(test, parsed_rule))
        else:
            test_tags = set(getattr(test, 'tags', set()))
            test_fn_name = getattr(test, '_testMethodName', str(test))
            test_fn = getattr(test, test_fn_name, test)
            test_fn_tags = set(getattr(test_fn, 'tags', set()))
            all_tags = test_tags.union(test_fn_tags)
            if parsed_rule.__bool__(all_tags):
                filtered_suite.addTest(test)

    return filtered_suite
