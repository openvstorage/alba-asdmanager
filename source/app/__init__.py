# Copyright 2015 CloudFounders NV
# All rights reserved

"""
API module
"""

from source.tools.disks import Disks
from flask import Flask
app = Flask(__name__)

Disks.scan_controllers()

from api import API
