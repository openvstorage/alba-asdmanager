# Copyright 2015 CloudFounders NV
# All rights reserved

"""
Flask main module
"""

from flask import Flask
app = Flask(__name__)

from api import API
