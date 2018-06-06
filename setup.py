#!/usr/bin/env python
#
# Copyright 2016 Sangoma Technologies Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
from setuptools import setup


with open('README.rst') as f:
    readme = f.read()


setup(
    name="sandswitches",
    version='0.1.1',
    description='A Python API that makes configuring FreeSWITCH a lunch break',
    long_description=readme,
    license='Mozilla',
    author='Sangoma Technologies',
    author_email='qa@eng.sangoma.com',
    maintainer='Tyler Goodlet',
    maintainer_email='tgoodlet@sangoma.com',
    url='https://github.com/sangoma/sandswitches',
    platforms=['linux'],
    packages=[
        'sandswitches',
    ],
    entry_points={
        'console_scripts': []
    },
    install_requires=[
        'lxml',
        'plumbum',
        'paramiko',
    ],
    tests_require=['pytest'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.5',
        'Intended Audience :: Telecommunications Industry',
        'Intended Audience :: Developers',
        'Topic :: Communications :: Telephony',
        'Environment :: Console',
    ],
)
