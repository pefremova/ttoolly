# -*- coding: utf-8 -*-
from distutils.core import setup
from setuptools import find_packages

setup(name='ttoolly',
      version='0.16.3',
      description="Django test tools",
      include_package_data=True,
      packages=find_packages(exclude=["tests", "test_project"]),
      install_requires=['django>=1.8', 'psycopg2', 'lxml', 'chardet', 'Pillow', 'rstr', 'future', 'freezegun'])
