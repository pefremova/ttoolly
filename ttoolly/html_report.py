from unittest.runner import TextTestResult

import jinja2
from pyunitreport.result import HtmlTestResult, _TestInfo
from ttoolly.utils import to_bytes


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

    def generate_reports(self, testRunner):
        """ Generate report for all given runned test object. """
        all_results = self._get_info_by_testcase()
        reports_path_list = []
        for testcase_class_name, all_tests in all_results.items():
            testRunner.report_name = testcase_class_name
            path_file = self._generate_html_file(testRunner, all_tests)
            reports_path_list.append(path_file)

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
            error_message = testCase.err[1].message
        else:
            error_message = testCase.err
        error_message = jinja2.filters.do_mark_safe('<pre>%s</pre>' % error_message)

        test_cases_list.append([full_name, status, error_type, error_message])

    def getDescription(self, *args, **kwargs):
        return TextTestResult.getDescription(self, *args, **kwargs)
