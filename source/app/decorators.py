# Copyright (C) 2016 iNuron NV
#
# This file is part of Open vStorage Open Source Edition (OSE),
# as available from
#
#      http://www.openvstorage.org and
#      http://www.openvstorage.com.
#
# This file is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
# as published by the Free Software Foundation, in version 3 as it comes
# in the LICENSE.txt file of the Open vStorage OSE distribution.
#
# Open vStorage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY of any kind.

"""
API decorators
"""

import os
from flask import request
from ovs_extensions.api.decorators import HTTPRequestDecorators as _HTTPRequestDecorators
from source.app import app
from source.tools.configuration import Configuration
from source.tools.log_handler import LogHandler


class HTTPRequestDecorators(_HTTPRequestDecorators):
    """
    Class with decorator functionality for HTTP requests 
    """
    app = app
    logger = LogHandler.get('asd-manager', name='api')
    version = 3

    def __init__(self):
        """
        Dummy init method
        """

    @classmethod
    def authorized(cls):
        """
        Indicates whether a call is authenticated
        """
        node_id = os.environ['ASD_NODE_ID']
        username = Configuration.get('/ovs/alba/asdnodes/{0}/config/main|username'.format(node_id))
        password = Configuration.get('/ovs/alba/asdnodes/{0}/config/main|password'.format(node_id))
        auth = request.authorization
        return auth and auth.username == username and auth.password == password
