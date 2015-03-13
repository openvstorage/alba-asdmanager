# Copyright 2015 CloudFounders NV
# All rights reserved

"""
Flask main module
"""

from source.tools.disks import Disks
from flask import Flask
app = Flask(__name__)

Disks.scan_controllers()

from api import API
