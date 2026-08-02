# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
from pathlib import Path
import sys
import tomllib

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

with (PROJECT_ROOT / 'pyproject.toml').open('rb') as pyproject_file:
    release =  '0.2.0'

project = 'sclog_lite'
copyright = '2026, gjh'
author = 'gjh'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',  # 可以在文档中直接查看源码链接
    'sphinx.ext.napoleon',  # 支持更美观的 docstring 风格
    'sphinx.ext.githubpages',  # 必须添加，用于兼容 GitHub Pages
    'sphinx_copybutton',  # 代码块一键复制按钮
]

napoleon_use_ivar = True

templates_path = ['_templates']
exclude_patterns = []

language = 'zh_CN'

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'furo'
html_static_path = ['_static']
