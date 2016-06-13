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
Generic module for managing configuration in Etcd
"""
import os
import etcd
import json
import random
import string
from itertools import groupby
try:
    from requests.packages.urllib3 import disable_warnings
except ImportError:
    import requests
    try:
        reload(requests)  # Required for 2.6 > 2.7 upgrade (new requests.packages module)
    except ImportError:
        pass  # So, this reload fails because of some FileNodeWarning that can't be found. But it did reload. Yay.
    from requests.packages.urllib3 import disable_warnings
from requests.packages.urllib3.exceptions import InsecurePlatformWarning
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from requests.packages.urllib3.exceptions import SNIMissingWarning


class EtcdConfiguration(object):
    """
    Configuration class using Etcd.

    Uses a special key format to specify the path within etcd, and specify a path inside the json data
    object that might be stored inside the etcd key.
    key  = <etcd path>[|<json path>]
    etcd path = slash-delimited path
    json path = dot-delimited path

    Examples:
        > EtcdConfiguration.set('/foo', 1)
        > print EtcdConfiguration.get('/foo')
        < 1
        > EtcdConfiguration.set('/foo', {'bar': 1})
        > print EtcdConfiguration.get('/foo')
        < {u'bar': 1}
        > print EtcdConfiguration.get('/foo|bar')
        < 1
        > EtcdConfiguration.set('/bar|a.b', 'test')
        > print EtcdConfiguration.get('/bar')
        < {u'a': {u'b': u'test'}}
    """
    _unittest_data = {}

    disable_warnings(InsecurePlatformWarning)
    disable_warnings(InsecureRequestWarning)
    disable_warnings(SNIMissingWarning)

    def __init__(self):
        """
        Dummy init method
        """
        _ = self

    @staticmethod
    def get(key, raw=False):
        """
        Get value from etcd
        :param key: Key to get
        :param raw: Raw data if True else json format
        :return: Value for key
        """
        key_entries = key.split('|')
        data = EtcdConfiguration._get(key_entries[0], raw)
        if len(key_entries) == 1:
            return data
        temp_data = data
        for entry in key_entries[1].split('.'):
            temp_data = temp_data[entry]
        return temp_data

    @staticmethod
    def set(key, value, raw=False):
        """
        Set value in etcd
        :param key: Key to store
        :param value: Value to store
        :param raw: Raw data if True else json format
        :return: None
        """
        key_entries = key.split('|')
        if len(key_entries) == 1:
            EtcdConfiguration._set(key_entries[0], value, raw)
            return
        try:
            data = EtcdConfiguration._get(key_entries[0], raw)
        except etcd.EtcdKeyNotFound:
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
        EtcdConfiguration._set(key_entries[0], data, raw)

    @staticmethod
    def delete(key, remove_root=False, raw=False):
        """
        Delete key - value from etcd
        :param key: Key to delete
        :param remove_root: Remove root
        :param raw: Raw data if True else json format
        :return: None
        """
        key_entries = key.split('|')
        if len(key_entries) == 1:
            EtcdConfiguration._delete(key_entries[0], recursive=True)
            return
        data = EtcdConfiguration._get(key_entries[0], raw)
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
        EtcdConfiguration._set(key_entries[0], data, raw)

    @staticmethod
    def exists(key, raw=False):
        """
        Check if key exists in etcd
        :param key: Key to check
        :param raw: Process raw data
        :return: True if exists
        """
        try:
            EtcdConfiguration.get(key, raw)
            return True
        except (KeyError, etcd.EtcdKeyNotFound):
            return False

    @staticmethod
    def dir_exists(key):
        """
        Check if directory exists in etcd
        :param key: Directory to check
        :return: True if exists
        """
        return EtcdConfiguration._dir_exists(key)

    @staticmethod
    def list(key):
        """
        List all keys in tree
        :param key: Key to list
        :return: Generator object
        """
        return EtcdConfiguration._list(key)

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
        base_config = {'/config/main': {'node_id': node_id,
                                        'password': password,
                                        'username': 'root',
                                        'ip': api_ip,
                                        'port': api_port,
                                        'version': 0},
                       '/config/network': {'ips': asd_ips,
                                           'port': asd_starter_port}}
        for key, value in base_config.iteritems():
            EtcdConfiguration._set('/ovs/alba/asdnodes/{0}/{1}'.format(node_id, key), value, raw=False)
        return node_id

    @staticmethod
    def uninitialize(node_id):
        """
        Remove initially stored values from etcd
        :param node_id: Un-initialize this node
        """
        if EtcdConfiguration.dir_exists('/ovs/alba/asdnodes/{0}'.format(node_id)):
            EtcdConfiguration.delete('/ovs/alba/asdnodes/{0}'.format(node_id))

    @staticmethod
    def _dir_exists(key):
        key = EtcdConfiguration._coalesce_dashes(key=key)

        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            stripped_key = key.strip('/')
            current_dict = EtcdConfiguration._unittest_data
            for part in stripped_key.split('/'):
                if part not in current_dict or not isinstance(current_dict[part], dict):
                    return False
                current_dict = current_dict[part]
            return True

        # Real implementation
        try:
            client = EtcdConfiguration._get_client()
            return client.get(key).dir
        except (KeyError, etcd.EtcdKeyNotFound):
            return False

    @staticmethod
    def _list(key):
        key = EtcdConfiguration._coalesce_dashes(key=key)

        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            data = EtcdConfiguration._unittest_data
            ends_with_dash = key.endswith('/')
            starts_with_dash = key.startswith('/')
            stripped_key = key.strip('/')
            for part in stripped_key.split('/'):
                if part not in data:
                    raise etcd.EtcdKeyNotFound('Key not found: {0}'.format(key))
                data = data[part]
            if data:
                for sub_key in data:
                    if ends_with_dash is True:
                        yield '/{0}/{1}'.format(stripped_key, sub_key)
                    else:
                        yield sub_key if starts_with_dash is True else '/{0}'.format(sub_key)
            elif starts_with_dash is False or ends_with_dash is True:
                yield '/{0}'.format(stripped_key)
            return

        # Real implementation
        client = EtcdConfiguration._get_client()
        for child in client.get(key).children:
            if child.key is not None and child.key != key:
                yield child.key.replace('{0}/'.format(key), '')

    @staticmethod
    def _delete(key, recursive):
        key = EtcdConfiguration._coalesce_dashes(key=key)

        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            stripped_key = key.strip('/')
            data = EtcdConfiguration._unittest_data
            for part in stripped_key.split('/')[:-1]:
                if part not in data:
                    raise etcd.EtcdKeyNotFound('Key not found : {0}'.format(key))
                data = data[part]
            key_to_remove = stripped_key.split('/')[-1]
            if key_to_remove in data:
                del data[key_to_remove]
            return

        # Real implementation
        client = EtcdConfiguration._get_client()
        client.delete(key, recursive=recursive)

    @staticmethod
    def _get(key, raw):
        key = EtcdConfiguration._coalesce_dashes(key=key)

        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            if key in ['', '/']:
                return
            stripped_key = key.strip('/')
            data = EtcdConfiguration._unittest_data
            for part in stripped_key.split('/')[:-1]:
                if part not in data:
                    raise etcd.EtcdKeyNotFound('Key not found : {0}'.format(key))
                data = data[part]
            last_part = stripped_key.split('/')[-1]
            if last_part not in data:
                raise etcd.EtcdKeyNotFound('Key not found : {0}'.format(key))
            data = data[last_part]
            if isinstance(data, dict):
                data = None
        else:
            # Real implementation
            client = EtcdConfiguration._get_client()
            data = client.read(key).value

        if raw is True:
            return data
        return json.loads(data)

    @staticmethod
    def _set(key, value, raw):
        key = EtcdConfiguration._coalesce_dashes(key=key)
        data = value
        if raw is False:
            data = json.dumps(value)

        # Unittests
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            stripped_key = key.strip('/')
            ut_data = EtcdConfiguration._unittest_data
            for part in stripped_key.split('/')[:-1]:
                if part not in ut_data:
                    ut_data[part] = {}
                ut_data = ut_data[part]

            ut_data[stripped_key.split('/')[-1]] = data
            return

        # Real implementation
        client = EtcdConfiguration._get_client()
        client.write(key, data)

    @staticmethod
    def _get_client():
        return etcd.Client(port=2379, use_proxies=True)

    @staticmethod
    def _coalesce_dashes(key):
        """
        Remove multiple dashes, eg: //ovs//framework/ becomes /ovs/framework/
        :param key: Key to convert
        :type key: str

        :return: Key without multiple dashes after one another
        :rtype: str
        """
        return ''.join(k if k == '/' else ''.join(group) for k, group in groupby(key))
