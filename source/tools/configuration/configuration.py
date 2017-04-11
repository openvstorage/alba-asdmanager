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


class NotFoundException(Exception):
    """Not found exception."""
    pass


class ConnectionException(Exception):
    """Connection exception."""
    pass


class Configuration(object):
    """
    Configuration wrapper.

    Uses a special key format to specify the path within the configuration store, and specify a path inside the json data
    object that might be stored inside the key.
    key  = <main path>[|<json path>]
    main path = slash-delimited path
    json path = dot-delimited path

    Examples:
        > Configuration.set('/foo', 1)
        > print Configuration.get('/foo')
        < 1
        > Configuration.set('/foo', {'bar': 1})
        > print Configuration.get('/foo')
        < {u'bar': 1}
        > print Configuration.get('/foo|bar')
        < 1
        > Configuration.set('/bar|a.b', 'test')
        > print Configuration.get('/bar')
        < {u'a': {u'b': u'test'}}
    """

    _unittest_data = {}
    _store = None
    BOOTSTRAP_CONFIG_LOCATION = '/opt/asd-manager/config/framework.json'

    def __init__(self):
        """
        Dummy init method
        """
        _ = self

    @staticmethod
    def get_configuration_path(key):
        """
        Retrieve the configuration path
        For arakoon: 'arakoon:///opt/OpenvStorage/config/arakoon_cacc.ini:{0}'.format(key)
        :param key: Key to retrieve the full configuration path for
        :type key: str
        :return: Configuration path
        :rtype: str
        """
        # _ = Configuration.get(key)
        return Configuration._passthrough(method='get_configuration_path',
                                          key=key)

    @staticmethod
    def get(key, raw=False):
        """
        Get value from the configuration store
        :param key: Key to get
        :param raw: Raw data if True else json format
        :return: Value for key
        """
        key_entries = key.split('|')
        data = Configuration._get(key_entries[0], raw)
        if len(key_entries) == 1:
            return data
        try:
            temp_data = data
            for entry in key_entries[1].split('.'):
                temp_data = temp_data[entry]
            return temp_data
        except KeyError as ex:
            raise NotFoundException(ex.message)

    @staticmethod
    def set(key, value, raw=False):
        """
        Set value in the configuration store
        :param key: Key to store
        :param value: Value to store
        :param raw: Raw data if True else json format
        :return: None
        """
        key_entries = key.split('|')
        if len(key_entries) == 1:
            Configuration._set(key_entries[0], value, raw)
            return
        try:
            data = Configuration._get(key_entries[0], raw)
        except NotFoundException:
            data = {}
        temp_config = data
        entries = key_entries[1].split('.')
        for entry in entries[:-1]:
            if entry in temp_config:
                temp_config = temp_config[entry]
            else:
                temp_config[entry] = {}
                temp_config = temp_config[entry]
        temp_config[entries[-1]] = value
        Configuration._set(key_entries[0], data, raw)

    @staticmethod
    def delete(key, remove_root=False, raw=False):
        """
        Delete key - value from the configuration store
        :param key: Key to delete
        :param remove_root: Remove root
        :param raw: Raw data if True else json format
        :return: None
        """
        key_entries = key.split('|')
        if len(key_entries) == 1:
            Configuration._delete(key_entries[0], recursive=True)
            return
        data = Configuration._get(key_entries[0], raw)
        temp_config = data
        entries = key_entries[1].split('.')
        if len(entries) > 1:
            for entry in entries[:-1]:
                if entry in temp_config:
                    temp_config = temp_config[entry]
                else:
                    temp_config[entry] = {}
                    temp_config = temp_config[entry]
            del temp_config[entries[-1]]
        if len(entries) == 1 and remove_root is True:
            del data[entries[0]]
        Configuration._set(key_entries[0], data, raw)

    @staticmethod
    def exists(key, raw=False):
        """
        Check if key exists in the configuration store
        :param key: Key to check
        :param raw: Process raw data
        :return: True if exists
        """
        try:
            Configuration.get(key, raw)
            return True
        except NotFoundException:
            return False

    @staticmethod
    def dir_exists(key):
        """
        Check if directory exists in the configuration store
        :param key: Directory to check
        :return: True if exists
        """
        return Configuration._dir_exists(key)

    @staticmethod
    def list(key):
        """
        List all keys in tree in the configuration store
        :param key: Key to list
        :return: Generator object
        """
        return Configuration._list(key)

    @staticmethod
    def initialize(api_ip, api_port, asd_ips, asd_starter_port):
        """
        Initialize general keys for all hosts in cluster
        :param api_ip: The IP address on which the API should be contacted
        :param api_port: The port on which the API should be contacted
        :param asd_ips: The IP addresses on which the asds should listen
        :param asd_starter_port: The 1st port in range on which the asds should listen
        :return: Node id
        """
        node_id = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        password = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))
        base_config = {'config/main': {'node_id': node_id,
                                       'password': password,
                                       'username': 'root',
                                       'ip': api_ip,
                                       'port': api_port,
                                       'version': 0},
                       'config/network': {'ips': asd_ips,
                                          'port': asd_starter_port}}
        for key, value in base_config.iteritems():
            Configuration._set('/ovs/alba/asdnodes/{0}/{1}'.format(node_id, key), value, raw=False)
        return node_id

    @staticmethod
    def uninitialize(node_id):
        """
        Remove initially stored values from configuration store
        :param node_id: Un-initialize this node
        """
        if Configuration.dir_exists('/ovs/alba/asdnodes/{0}'.format(node_id)):
            Configuration.delete('/ovs/alba/asdnodes/{0}'.format(node_id))

    @staticmethod
    def _dir_exists(key):
        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            stripped_key = key.strip('/')
            current_dict = Configuration._unittest_data
            for part in stripped_key.split('/'):
                if part not in current_dict or not isinstance(current_dict[part], dict):
                    return False
                current_dict = current_dict[part]
            return True
        # Forward call to used configuration store
        return Configuration._passthrough(method='dir_exists',
                                          key=key)

    @staticmethod
    def _list(key):
        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            entries = []
            data = Configuration._unittest_data
            ends_with_dash = key.endswith('/')
            starts_with_dash = key.startswith('/')
            stripped_key = key.strip('/')
            for part in stripped_key.split('/'):
                if part not in data:
                    raise NotFoundException(key)
                data = data[part]
            if data:
                for sub_key in data:
                    if ends_with_dash is True:
                        entries.append('/{0}/{1}'.format(stripped_key, sub_key))
                    else:
                        entries.append(sub_key if starts_with_dash is True else '/{0}'.format(sub_key))
            elif starts_with_dash is False or ends_with_dash is True:
                entries.append('/{0}'.format(stripped_key))
            return entries
        # Forward call to used configuration store
        return Configuration._passthrough(method='list',
                                          key=key)

    @staticmethod
    def _delete(key, recursive):
        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            stripped_key = key.strip('/')
            data = Configuration._unittest_data
            for part in stripped_key.split('/')[:-1]:
                if part not in data:
                    raise NotFoundException(key)
                data = data[part]
            key_to_remove = stripped_key.split('/')[-1]
            if key_to_remove in data:
                del data[key_to_remove]
            return
        # Forward call to used configuration store
        return Configuration._passthrough(method='delete',
                                          key=key, recursive=recursive)

    @staticmethod
    def _get(key, raw):
        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            if key in ['', '/']:
                return
            stripped_key = key.strip('/')
            data = Configuration._unittest_data
            for part in stripped_key.split('/')[:-1]:
                if part not in data:
                    raise NotFoundException(key)
                data = data[part]
            last_part = stripped_key.split('/')[-1]
            if last_part not in data:
                raise NotFoundException(key)
            data = data[last_part]
            if isinstance(data, dict):
                data = None
        else:
            # Forward call to used configuration store
            data = Configuration._passthrough(method='get',
                                              key=key)
        if raw is True:
            return data
        return json.loads(data)

    @staticmethod
    def _set(key, value, raw):
        data = value
        if raw is False:
            data = json.dumps(value, indent=4, sort_keys=True)
        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            stripped_key = key.strip('/')
            ut_data = Configuration._unittest_data
            for part in stripped_key.split('/')[:-1]:
                if part not in ut_data:
                    ut_data[part] = {}
                ut_data = ut_data[part]

            ut_data[stripped_key.split('/')[-1]] = data
            return
        # Forward call to used configuration store
        return Configuration._passthrough(method='set',
                                          key=key,
                                          value=data)

    @staticmethod
    def _passthrough(method, *args, **kwargs):
        store = Configuration.get_store()
        if store == 'arakoon':
            from source.tools.configuration.arakoon_config import ArakoonConfiguration
            from source.tools.pyrakoon.pyrakoon.compat import ArakoonNotFound
            try:
                return getattr(ArakoonConfiguration, method)(*args, **kwargs)
            except ArakoonNotFound as ex:
                raise NotFoundException(ex.message)
        raise NotImplementedError('Store {0} is not implemented'.format(store))

    @staticmethod
    def get_store():
        """
        Retrieve the configuration store method. This can currently only be 'arakoon'
        :return: Store method
        :rtype: str
        """
        if Configuration._store is None:
            with open(Configuration.BOOTSTRAP_CONFIG_LOCATION) as config_file:
                contents = json.load(config_file)
                Configuration._store = contents['configuration_store']
        return Configuration._store
