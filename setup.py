# -*- coding: utf-8 -*-
from distutils.core import setup

setup(name='ttoolly',
      version='0.8.2',
      description="Django test tools",
      include_package_data=True,
      install_requires=['django', 'psycopg2', 'lxml', 'chardet', 'Pillow', 'rstr'])
