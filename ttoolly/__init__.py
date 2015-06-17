from django.conf import settings
if getattr(settings, 'COLORIZE_TESTS', False):
    from django.utils.unittest import TextTestResult

    def _getDescription(self, test):
        doc_first_line = test.shortDescription()
        if self.descriptions and doc_first_line:
            return '\n'.join((str(test), doc_first_line))
        else:
            return "\x1B[38;5;230m" + str(test) + "\x1B[0m"

    TextTestResult.getDescription = _getDescription
