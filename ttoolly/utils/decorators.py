# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import sys
from unittest import SkipTest
import warnings

from django.utils.encoding import force_text

from future.utils import viewkeys


if sys.version[0] == '2':
    from functools32 import wraps, update_wrapper
else:
    from functools import wraps, update_wrapper


class only_with_obj(object):

    skip_text = 'Need "obj"'

    def __init__(self, fn):
        self.fn = fn
        self.fn.decorators = getattr(fn, 'decorators', ()) + (self,)
        update_wrapper(self, fn)

    def __call__(self, cls, *args, **kwargs):
        if self.check(cls):
            return self.fn(cls, *args, **kwargs)
        else:
            raise SkipTest(self.skip_text)

    def check(self, cls):
        return cls.obj


class only_with(object):

    def __init__(self, param_names):
        if not isinstance(param_names, (tuple, list)):
            param_names = (param_names,)
        self.param_names = param_names
        self.skip_text = "Need all these params: %s" % repr(self.param_names)

    def __call__(self, fn, *args, **kwargs):

        @wraps(fn)
        def tmp(cls):
            if self.check(cls):
                return fn(cls, *args, **kwargs)
            else:
                raise SkipTest(self.skip_text)

        tmp.decorators = getattr(fn, 'decorators', ()) + (self,)
        return tmp

    def check(self, cls):
        return all(getattr(cls, param_name, None) for param_name in self.param_names)


class only_with_files_params(object):

    def __init__(self, param_names):
        if not isinstance(param_names, (tuple, list)):
            param_names = (param_names,)
        self.param_names = param_names

    def __call__(self, fn, *args, **kwargs):

        @wraps(fn)
        def tmp(cls):
            if self.check(cls):
                return fn(cls, *args, **kwargs)
            else:
                raise SkipTest(self.skip_text)

        tmp.decorators = getattr(fn, 'decorators', ()) + (self,)
        self.fn = fn
        return tmp

    def check(self, cls):
        params_dict_name = 'file_fields_params' + ('_add' if '_add_' in self.fn.__name__ else '_edit')
        self.skip_text = "Need all these keys in %s: %s" % (params_dict_name, repr(self.param_names))

        def check_params(field_dict, param_names):
            return all([param_name in viewkeys(field_dict) for param_name in param_names])

        to_run = any([check_params(field_dict, self.param_names)
                      for field_dict in getattr(cls, params_dict_name).values()])
        if to_run:
            if not all([check_params(field_dict, self.param_names) for field_dict in
                        getattr(cls, params_dict_name).values()]):
                warnings.warn('%s not set for all fields' % force_text(self.param_names))
        return to_run


class only_with_any_files_params(object):

    def __init__(self, param_names):
        if not isinstance(param_names, (tuple, list)):
            param_names = (param_names,)
        self.param_names = param_names

    def __call__(self, fn, *args, **kwargs):

        @wraps(fn)
        def tmp(cls):
            if self.check(cls):
                return fn(cls, *args, **kwargs)
            else:
                raise SkipTest(self.skip_text)

        tmp.decorators = getattr(fn, 'decorators', ()) + (self,)
        self.fn = fn
        return tmp

    def check(self, cls):
        params_dict_name = 'file_fields_params' + ('_add' if '_add_' in self.fn.__name__ else '_edit')
        self.skip_text = "Need any of these keys in %s: %s" % (params_dict_name, repr(self.param_names))

        def check_params(field_dict, param_names):
            return any([param_name in viewkeys(field_dict) for param_name in param_names])

        to_run = any([check_params(field_dict, self.param_names)
                      for field_dict in getattr(cls, params_dict_name).values()])
        if to_run:
            if not all([check_params(field_dict, self.param_names) for field_dict in getattr(cls, params_dict_name).values()]):
                warnings.warn('%s not set for all fields' % force_text(self.param_names))
        return to_run


def use_in_all_tests(decorator):
    def decorate(cls, child=None):
        if child is None:
            child = cls

        for attr in cls.__dict__:
            if callable(getattr(cls, attr)) and attr.startswith('test_'):
                fn = getattr(child, attr, getattr(cls, attr))
                if fn and decorator not in getattr(fn, 'decorators', ()):
                    decorated = decorator(fn)
                    decorated.__name__ = fn.__name__
                    decorated.decorators = tuple(set(getattr(fn, 'decorators', ()))) + (decorator,)
                    setattr(child, attr, decorated)
        bases = cls.__bases__
        for base in bases:
            decorate(base, child)
        return cls

    return decorate
