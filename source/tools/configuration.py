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
import os
import json
import random
import string
from ovs_extensions.generic.configuration import Configuration as _Configuration


class Configuration(_Configuration):
    """
    Extends the 'default' configuration class
    """
    CACC_SOURCE = '/opt/OpenvStorage/config/arakoon_cacc.ini'
    CACC_LOCATION = '/opt/asd-manager/config/arakoon_cacc.ini'
    BOOTSTRAP_CONFIG_LOCATION = '/opt/asd-manager/config/framework.json'

    _unittest_data = {}

    def __init__(self):
        """
        Dummy init method
        """
        _ = self

    @classmethod
    def initialize(cls, config):
        """
        Initialize general keys for this host
        :param config: The configuration containing API IP:port, ASD IPs and ASD start port
        :type config: dict
        :return: Node id
        :rtype: str
        """
        node_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        password = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        base_config = {'config/main': {'node_id': node_id,
                                       'password': password,
                                       'username': 'root',
                                       'ip': config['api_ip'],
                                       'port': config['api_port'],
                                       'version': 0},
                       'config/network': {'ips': config['asd_ips'],
                                          'port': config['asd_start_port']}}
        for key, value in base_config.iteritems():
            cls.set(key='/ovs/alba/asdnodes/{0}/{1}'.format(node_id, key),
                    value=value,
                    raw=False)
        return node_id

    @classmethod
    def uninitialize(cls, node_id):
        """
        Remove initially stored values from configuration store
        :param node_id: Un-initialize this node
        :type node_id: str
        :return: None
        :rtype: NoneType
        """
        if cls.dir_exists('/ovs/alba/asdnodes/{0}'.format(node_id)):
            cls.delete('/ovs/alba/asdnodes/{0}'.format(node_id))

    @classmethod
    def get_store_info(cls):
        """
        Retrieve the configuration store method. Currently this can only be 'arakoon'
        :return: A tuple containing the store and params that can be passed to the configuration implementation instance
        :rtype: tuple(str, dict)
        """
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            return 'unittest', None
        with open(cls.BOOTSTRAP_CONFIG_LOCATION) as config_file:
            contents = json.load(config_file)
            return contents['configuration_store'], {'cacc_location': cls.CACC_LOCATION}
