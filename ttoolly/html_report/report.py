from datetime import datetime
import os
import traceback
from unittest.runner import TextTestResult

from django.utils.encoding import force_text
import jinja2
from pyunitreport.result import HtmlTestResult, _TestInfo, render_html
from ttoolly.utils import to_bytes, unicode_to_readable


class CustomInfoClass(_TestInfo):

    def __init__(self, test_result, test_method, outcome=_TestInfo.SUCCESS,
                 err=None, subTest=None):
        self.test_method = test_method
        super(CustomInfoClass, self).__init__(test_result, test_method, outcome=outcome,
                                              err=err, subTest=subTest)


class CustomHtmlTestResult(HtmlTestResult):

    def __init__(self, *args, **kwargs):
        super(CustomHtmlTestResult, self).__init__(*args, **kwargs)
        self.infoclass = CustomInfoClass

    def _get_report_attributes(self, tests, start_time, time_taken):
        """ Setup the header info for the report. """

        failures = errors = skips = success = 0
        for test in tests:
            outcome = test.outcome
            if outcome == test.ERROR:
                errors += 1
            elif outcome == test.FAILURE:
                failures += 1
            elif outcome == test.SKIP:
                skips += 1
            elif outcome == test.SUCCESS:
                success += 1
        status = []

        if success:
            status.append('Pass: {}'.format(success))
        if failures:
            status.append('Fail: {}'.format(failures))
        if errors:
            status.append('Error: {}'.format(errors))
        if skips:
            status.append('Skip: {}'.format(skips))
        result = ', '.join(status)

        start_time = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')
        hearders = {
            "start_time": start_time,
            "duration": time_taken,
            "status": result,
            'success': success,
            'skips': skips,
            'errors': errors,
            'failures': failures
        }
        total_runned_test = success + skips + errors + failures
        return hearders, total_runned_test

    def generate_index(self, reports_path_list, testRunner):
        report_save_dir = os.path.join(os.getcwd(), 'reports')
        index_file_fullpath = os.path.join(report_save_dir, 'index.html')

        report_content = render_html(
            os.path.join(os.path.dirname(__file__), "templates", "_index.html"),
            title=str(datetime.now()),
            headers={},
            tests_list=sorted(reports_path_list, key=lambda el: el[1])
        )
        with open(index_file_fullpath, 'wb') as report_file:
            report_file.write(report_content.encode('utf-8'))

    def generate_reports(self, testRunner):
        """ Generate report for all given runned test object. """
        all_results = self._get_info_by_testcase()
        reports_path_list = []
        for_index_data = []
        for testcase_class_name, all_tests in all_results.items():
            testRunner.report_name = testcase_class_name
            path_file = self._generate_html_file(testRunner, all_tests)

            headers, tests_count = self._get_report_attributes(all_tests, testRunner.startTime, testRunner.timeTaken)
            reports_path_list.append(path_file)
            for_index_data.append([path_file.replace(os.getcwd() + '/reports/', ''), testRunner.report_name, tests_count, headers])

        self.generate_index(for_index_data, testRunner)
        return reports_path_list

    def _report_testcase(self, testCase, test_cases_list):
        """ Return a list with test name or desciption, status and error
            msg if fail or skip. """
        full_name = testCase.test_id
        class_doc = testCase.test_method.__class__.__doc__
        if class_doc:
            full_name += '<br>'.join([line.strip() for line in
                                      to_bytes(class_doc).decode('utf-8').strip('<br> ').splitlines()])
        doc = getattr(testCase.test_method, '_testMethodDoc', '')
        if doc:
            full_name += '<br>  ' + '<br>  '.join([line.strip() for line in
                                                   to_bytes(doc).decode('utf-8').replace('@note: ', '').strip('\n').splitlines()])

        status = ('success', 'danger', 'warning', 'info')[testCase.outcome - 1]

        error_type = ""
        if testCase.outcome != testCase.SKIP and testCase.outcome != testCase.SUCCESS:
            error_type = testCase.err[0].__name__
            etype, value, tb = testCase.err
            error_message = ''.join([force_text(el) for el in traceback.format_exception(etype, value, tb, limit=None)])
            error_message = unicode_to_readable(error_message)
        else:
            error_message = testCase.err
        error_message = jinja2.filters.do_mark_safe('<pre>%s</pre>' % error_message)

        test_cases_list.append([full_name, status, error_type, error_message])

    def getDescription(self, *args, **kwargs):
        return TextTestResult.getDescription(self, *args, **kwargs)
