# -*- coding: utf-8 -*-
from distutils.core import setup
from setuptools import find_packages


def readme():
    with open('README.md', 'rb') as f:
        return f.read().decode('utf-8')


setup(name='ttoolly',
      version='0.25.0',
      description="Django test tools",
      long_description=readme(),
      author="Polina Efremova",
      author_email="pefremova@gmail.com",
      keywords=["django", "testing", "test tool"],
      include_package_data=True,
      packages=find_packages(exclude=["tests", "test_project"]),
      install_requires=['django>=1.8', ' psycopg2-binary', 'lxml', 'chardet', 'Pillow', 'rstr', 'future', 'freezegun'],
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
