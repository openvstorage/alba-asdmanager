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
from ovs_extensions.dal.base import ObjectNotFoundException
from ovs_extensions.generic.configuration import Configuration as _Configuration
from source.constants.asd import CONFIG_STORE_LOCATION, ASD_NODE_CONFIG_MAIN_LOCATION, ASD_NODE_CONFIG_NETWORK_LOCATION, ASD_NODE_CONFIG_IPMI_LOCATION, ASD_NODE_LOCATION
from source.dal.lists.settinglist import SettingList
from source.tools.system import System


class Configuration(_Configuration):
    """
    Extends the 'default' configuration class
    """
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
        with open('/etc/openvstorage_sdm_id', 'r') as sdm_id_file:
            node_id = sdm_id_file.read().strip()

        cls.set(key=ASD_NODE_CONFIG_MAIN_LOCATION.format(node_id),
                value={'ip': config['api_ip'],
                       'port': config['api_port'],
                       'node_id': node_id,
                       'version': 0,
                       'password': ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32)),
                       'username': 'root'})
        cls.set(key=ASD_NODE_CONFIG_NETWORK_LOCATION.format(node_id),
                value={'ips': config['asd_ips'],
                       'port': config['asd_start_port']})

        ipmi = {'ip': config.get('ipmi', {}).get('ip'),
                'username': config.get('ipmi', {}).get('username'),
                'password': config.get('ipmi', {}).get('pwd')}
        cls.set(key=ASD_NODE_CONFIG_IPMI_LOCATION.format(node_id), value=ipmi)

        cls.set(key='/ovs/alba/logging',
                value={'target': 'console', 'level': 'DEBUG'},
                raw=False)
        cls.register_usage(System.get_component_identifier())
        return node_id

    @classmethod
    def uninitialize(cls):
        # type: () -> List[str]
        """
        Remove initially stored values from configuration store
        :return: The currently registered users
        :rtype: List[str]
        """
        try:
            node_id = SettingList.get_setting_by_code(code='node_id').value
        except ObjectNotFoundException:
            return
        if cls.dir_exists(ASD_NODE_LOCATION.format(node_id)):
            cls.delete(ASD_NODE_LOCATION.format(node_id))
        return cls.unregister_usage(System.get_component_identifier())

    @classmethod
    def get_store_info(cls):
        """
        Retrieve the configuration store method. Currently this can only be 'arakoon'
        :return: The store method
        :rtype: str
        """
        with open(CONFIG_STORE_LOCATION) as config_file:
            contents = json.load(config_file)
            return contents['configuration_store']
