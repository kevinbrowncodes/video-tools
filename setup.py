from setuptools import setup

APP = ['video_tools.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': True,
    'packages': ['customtkinter', 'PIL', 'py2app'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
