# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from unittest import TextTestResult

from django.conf import settings
from future.utils import PY2
from ttoolly.utils import unicode_to_readable, to_bytes


def _getDescription(self, test):
    doc_first_line = test.shortDescription()
    full_text = str(test)
    if getattr(settings, 'COLORIZE_TESTS', False):
        full_text = "\033[38;5;230m" + full_text + "\033[0m"
    class_doc = test.__class__.__doc__
    if class_doc:
        full_text += '\n~~~~~~~~~~\n' + '\n'.join([line.strip() for line in
                                                   to_bytes(class_doc).decode('utf-8').strip('\n ').splitlines()]) + '\n~~~~~~~~~~'
    doc = getattr(test, '_testMethodDoc', '')
    if doc:
        full_text += '\n  ' + '\n  '.join([line.strip() for line in
                                           to_bytes(doc).decode('utf-8').replace('@note: ', '').strip('\n').splitlines()])
    elif self.descriptions and doc_first_line:
        full_text += '\n' + to_bytes(doc_first_line).decode('utf-8')
    return full_text


TextTestResult.getDescription = _getDescription

if PY2:
    def _printErrorList(self, flavour, errors):
        for test, err in errors:
            self.stream.writeln(self.separator1)
            self.stream.writeln("%s: %s" % (flavour, self.getDescription(test)))
            self.stream.writeln(self.separator2)
            self.stream.writeln("%s" % unicode_to_readable(err))

    TextTestResult.printErrorList = _printErrorList

settings.FILE_UPLOAD_HANDLERS = ['ttoolly.utils.FakeSizeMemoryFileUploadHandler'] + list(settings.FILE_UPLOAD_HANDLERS)
