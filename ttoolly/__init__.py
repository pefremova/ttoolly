# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from future.utils import PY2

from django.conf import settings

from ttoolly.utils import unicode_to_readable

if getattr(settings, 'COLORIZE_TESTS', False):
    from unittest import TextTestResult

    def _getDescription(self, test):
        doc_first_line = test.shortDescription()
        if self.descriptions and doc_first_line:
            return '\n'.join((str(test), doc_first_line))
        else:
            return "\x1B[38;5;230m" + str(test) + "\x1B[0m"

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
