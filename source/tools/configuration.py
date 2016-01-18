# Copyright 2015 iNuron NV
#
# Licensed under the Open vStorage Modified Apache License (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.openvstorage.org/license
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Generic module for managing configuration in Etcd
"""

import json
import etcd
import random
import string


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
    def exists(key):
        """
        Check if key exists in etcd
        :param key: Key to check
        :return: True if exists
        """
        try:
            _ = EtcdConfiguration.get(key)
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
    def _dir_exists(key):
        try:
            client = EtcdConfiguration._get_client()
            return client.get(key).dir
        except (KeyError, etcd.EtcdKeyNotFound):
            return False

    @staticmethod
    def _list(key):
        client = EtcdConfiguration._get_client()
        for child in client.get(key).children:
            yield child.key.replace('{0}/'.format(key), '')

    @staticmethod
    def _delete(key, recursive):
        client = EtcdConfiguration._get_client()
        client.delete(key, recursive=recursive)

    @staticmethod
    def _get(key, raw):
        client = EtcdConfiguration._get_client()
        data = client.read(key).value
        if raw is True:
            return data
        return json.loads(data)

    @staticmethod
    def _set(key, value, raw):
        client = EtcdConfiguration._get_client()
        data = value
        if raw is False:
            data = json.dumps(value)
        client.write(key, data)

    @staticmethod
    def _get_client():
        return etcd.Client(port=2379, use_proxies=True)
