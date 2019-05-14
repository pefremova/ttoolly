# -*- coding: utf-8 -*-
from distutils.core import setup
from setuptools import find_packages
import sys


def readme():
    with open('README.rst', 'rb') as f:
        return f.read().decode('utf-8')


install_requires = ['django>=1.8', 'psycopg2-binary', 'lxml', 'chardet', 'Pillow', 'rstr', 'future',
                    'freezegun', 'boolean.py>=3.6']
if sys.version[0] == '2':
    install_requires.append('functools32')

setup(name='ttoolly',
      version='0.31.1',
      description="Django test tools",
      long_description=readme(),
      author="Polina Efremova",
      author_email="pefremova@gmail.com",
      keywords=["django", "testing", "test tool"],
      include_package_data=True,
      packages=find_packages(exclude=["tests", "test_project"]),
      install_requires=install_requires,
      classifiers=(
          "Framework :: Django",
          "Framework :: Django :: 1.10",
          "Framework :: Django :: 1.11",
          "Framework :: Django :: 1.8",
          "Framework :: Django :: 1.9",
          "Framework :: Django :: 2.0",
          "Programming Language :: Python :: 2.7",
          "Programming Language :: Python :: 3.5",
          "Programming Language :: Python :: 3.6"
      ),)
