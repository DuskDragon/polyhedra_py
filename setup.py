from setuptools import setup
import os

version = '0.0.1'

long_description = open('README.rst').read()

def clean_lines(filename):
    with open(filename) as fd:
        return [line.strip() for line in fd.readlines()]

requirements = clean_lines('requirements.txt')
test_requirements = clean_lines('requirements-test.txt')

setup(name='polyhedra',
      version=version,
      description="IdleISS Discord Interface",
      long_description=long_description,
      classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Programming Language :: Python :: 3.10.4',
        ],
      author='DuskDragon',
      author_email='',
      url='https://github.com/DuskDragon/IdleISS/',
      packages=['polyhedra'],
      package_dir={'polyhedra': './polyhedra'},
      namespace_packages=[],
      include_package_data=True,
      zip_safe=False,
      install_requires=requirements,
      tests_require=test_requirements,
      extras_require={'dev': [test_requirements]},
      entry_points={
          'console_scripts': [
              'polyhedra = polyhedra.main:run',
          ],
      },
)
