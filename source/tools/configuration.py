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
Generic module for managing configuration somewhere
"""

import json
import random
import string
from ovs_extensions.generic.configuration import Configuration as _Configuration
from source.dal.lists.settinglist import SettingList


class Configuration(_Configuration):
    """
    Extends the 'default' configuration class
    """
    CACC_SOURCE = '/opt/OpenvStorage/config/arakoon_cacc.ini'
    CACC_LOCATION = '/opt/asd-manager/config/arakoon_cacc.ini'
    ASD_NODE_LOCATION = '/ovs/alba/asdnodes/{0}'
    CONFIG_STORE_LOCATION = '/opt/asd-manager/config/framework.json'
    ASD_NODE_CONFIG_LOCATION = '{0}/config'.format(ASD_NODE_LOCATION)
    ASD_NODE_CONFIG_MAIN_LOCATION = '{0}/config/main'.format(ASD_NODE_LOCATION)
    ASD_NODE_CONFIG_NETWORK_LOCATION = '{0}/config/network'.format(ASD_NODE_LOCATION)

    _unittest_data = {}

    def __init__(self):
        """
        Dummy init method
        """
        _ = self

    @classmethod
    def initialize(cls, config):
        """
        Initialize general keys for this ASD Manager
        :param config: The configuration containing API IP:port, ASD IPs and ASD start port
        :type config: dict
        :return: Node ID
        :rtype: str
        """
        with open('/etc/openvstorage_sdm_id', 'r') as the_file:
            node_id = the_file.read().strip()
            cls.set(key=Configuration.ASD_NODE_CONFIG_MAIN_LOCATION.format(node_id),
                    value={'ip': config['api_ip'],
                           'port': config['api_port'],
                           'node_id': node_id,
                           'version': 0,
                           'password': ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32)),
                           'username': 'root'})
            cls.set(key=Configuration.ASD_NODE_CONFIG_NETWORK_LOCATION.format(node_id),
                    value={'ips': config['asd_ips'],
                           'port': config['asd_start_port']})
        cls.set(key='/ovs/alba/logging',
                value={'target': 'console', 'level': 'DEBUG'},
                raw=False)
        return node_id

    @classmethod
    def uninitialize(cls):
        """
        Remove initially stored values from configuration store
        :return: None
        :rtype: NoneType
        """
        node_id = SettingList.get_setting_by_code(code='node_id').value
        if node_id is not None and cls.dir_exists(Configuration.ASD_NODE_LOCATION.format(node_id)):
            cls.delete(Configuration.ASD_NODE_LOCATION.format(node_id))

    @classmethod
    def get_store_info(cls):
        """
        Retrieve the configuration store method. Currently this can only be 'arakoon'
        :return: The store method
        :rtype: str
        """
        with open(cls.CONFIG_STORE_LOCATION) as config_file:
            contents = json.load(config_file)
            return contents['configuration_store'], None  # For update we need to return a tuple
