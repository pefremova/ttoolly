# -*- coding: utf-8 -*-
from distutils.core import setup
from setuptools import find_packages
import sys


def readme():
    with open('README.rst', 'rb') as f:
        return f.read().decode('utf-8')


install_requires = [
    'lxml',
    'chardet',
    'Pillow',
    'rstr',
    'future',
    'freezegun',
    'pytz',
    'boolean.py>=3.6',
    'functools32;python_version<"3"',
]
if sys.version[0] == '2':
    install_requires.append('functools32')

setup(
    name='ttoolly',
    version='0.37.18',
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
        "Programming Language :: Python",
    ),
)
