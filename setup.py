# -*- coding: utf-8 -*-
from distutils.core import setup

setup(name='ttoolly',
      version='0.7.22',
      description="Django test tools",
      include_package_data=True,
      install_requires=['django', 'psycopg2', 'lxml', 'chardet', 'Pillow', 'rstr'])
