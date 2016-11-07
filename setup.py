# -*- coding: utf-8 -*-
from distutils.core import setup
from setuptools import find_packages

setup(name='ttoolly',
      version='0.11.10',
      description="Django test tools",
      include_package_data=True,
      packages=find_packages(),
      install_requires=['django', 'psycopg2', 'lxml', 'chardet', 'Pillow', 'rstr'])
