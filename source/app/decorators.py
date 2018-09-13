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

import json
from flask import request
from ovs_extensions.api.decorators.flask_requests import HTTPRequestFlaskDecorators
from ovs_extensions.api.decorators.generic_requests import HTTPRequestGenericDecorators
from source.app import app
from source.asdmanager import BOOTSTRAP_FILE
from source.constants.asd import ASD_NODE_CONFIG_MAIN_LOCATION
from source.dal.lists.settinglist import SettingList
from source.tools.configuration import Configuration
from source.tools.logger import Logger


class HTTPRequestDecorators(HTTPRequestFlaskDecorators, HTTPRequestGenericDecorators):
    """
    Class with decorator functionality for HTTP requests
    """
    app = app
    logger = Logger('flask')
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
        # For backwards compatibility we first try to retrieve the node ID by using the bootstrap file
        try:
            with open(BOOTSTRAP_FILE) as bstr_file:
                node_id = json.load(bstr_file)['node_id']
        except:
            node_id = SettingList.get_setting_by_code(code='node_id').value

        node_config = Configuration.get(ASD_NODE_CONFIG_MAIN_LOCATION.format(node_id))
        username = node_config['username']
        password = node_config['password']
        auth = request.authorization
        return auth and auth.username == username and auth.password == password
