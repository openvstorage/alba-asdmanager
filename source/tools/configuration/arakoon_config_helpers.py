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
ArakoonNodeConfig class
ArakoonClusterConfig class
"""

from ConfigParser import RawConfigParser
from source.tools.configuration.configuration import Configuration
from source.tools.localclient import LocalClient
from StringIO import StringIO


class ArakoonNodeConfig(object):
    """
    cluster node config parameters
    """
    def __init__(self, name, ip, client_port, messaging_port, log_sinks, crash_log_sinks, home, tlog_dir, preferred_master=False, fsync=True, log_level='info', tlog_compression='snappy'):
        """
        Initializes a new Config entry for a single Node
        """
        self.ip = ip
        self.home = home
        self.name = name
        self.fsync = fsync
        self.tlog_dir = tlog_dir
        self.log_level = log_level
        self.log_sinks = log_sinks
        self.client_port = client_port
        self.messaging_port = messaging_port
        self.crash_log_sinks = crash_log_sinks
        self.tlog_compression = tlog_compression
        self.preferred_master = preferred_master

    def __hash__(self):
        """
        Defines a hashing equivalent for a given ArakoonNodeConfig
        """
        return hash(self.name)

    def __eq__(self, other):
        """
        Checks whether two objects are the same.
        """
        if not isinstance(other, ArakoonNodeConfig):
            return False
        return self.__hash__() == other.__hash__()

    def __ne__(self, other):
        """
        Checks whether two objects are not the same.
        """
        if not isinstance(other, ArakoonNodeConfig):
            return True
        return not self.__eq__(other)


class ArakoonClusterConfig(object):
    """
    contains cluster config parameters
    """
    CONFIG_ROOT = '/ovs/arakoon'
    CONFIG_KEY = CONFIG_ROOT + '/{0}/config'
    CONFIG_FILE = '/opt/asd-manager/config/arakoon_{0}.ini'

    def __init__(self, cluster_id, load_config=True, source_ip=None, plugins=None):
        """
        Initializes an empty Cluster Config
        """
        self._plugins = []
        self._extra_globals = {'tlog_max_entries': 5000}
        if isinstance(plugins, list):
            self._plugins = plugins
        elif isinstance(plugins, basestring):
            self._plugins.append(plugins)

        self.nodes = []
        self.source_ip = source_ip
        self.cluster_id = cluster_id
        if self.source_ip is None:
            self.internal_config_path = ArakoonClusterConfig.CONFIG_KEY.format(cluster_id)
            self.external_config_path = Configuration.get_configuration_path(self.internal_config_path)
        else:
            self.internal_config_path = ArakoonClusterConfig.CONFIG_FILE.format(cluster_id)
            self.external_config_path = self.internal_config_path

        if load_config is True:
            self.read_config(ip=self.source_ip)

    def load_client(self, ip):
        """
        Create a LocalClient instance to the IP provided
        :param ip: IP for the LocalClient
        :type ip: str
        :return: A LocalClient instance
        :rtype: source.tools.localclient.LocalClient
        """
        if self.source_ip is not None:
            if ip is None:
                raise RuntimeError('An IP should be passed for filesystem configuration')
            return LocalClient(ip, username='root')

    def read_config(self, ip=None):
        """
        Constructs a configuration object from config contents
        :param ip: IP on which the configuration file resides (Only for filesystem Arakoon clusters)
        :type ip: str
        :return: None
        :rtype: NoneType
        """
        if ip is None:
            contents = Configuration.get(self.internal_config_path, raw=True)
        else:
            client = self.load_client(ip)
            contents = client.file_read(self.internal_config_path)

        parser = RawConfigParser()
        parser.readfp(StringIO(contents))
        self.nodes = []
        self._extra_globals = {}
        preferred_masters = []
        for key in parser.options('global'):
            if key == 'plugins':
                self._plugins = [plugin.strip() for plugin in parser.get('global', 'plugins').split(',')]
            elif key == 'cluster_id':
                self.cluster_id = parser.get('global', 'cluster_id')
            elif key == 'cluster':
                pass  # Ignore these
            elif key == 'preferred_masters':
                preferred_masters = parser.get('global', key).split(',')
            else:
                self._extra_globals[key] = parser.get('global', key)
        for node in parser.get('global', 'cluster').split(','):
            node = node.strip()
            self.nodes.append(ArakoonNodeConfig(ip=parser.get(node, 'ip'),
                                                name=node,
                                                home=parser.get(node, 'home'),
                                                fsync=parser.getboolean(node, 'fsync'),
                                                tlog_dir=parser.get(node, 'tlog_dir'),
                                                log_sinks=parser.get(node, 'log_sinks'),
                                                log_level=parser.get(node, 'log_level'),
                                                client_port=parser.getint(node, 'client_port'),
                                                messaging_port=parser.getint(node, 'messaging_port'),
                                                crash_log_sinks=parser.get(node, 'crash_log_sinks'),
                                                tlog_compression=parser.get(node, 'tlog_compression'),
                                                preferred_master=node in preferred_masters))

    def write_config(self, ip=None):
        """
        Writes the configuration down to in the format expected by Arakoon
        """
        contents = self.export_ini()
        if self.source_ip is None:
            Configuration.set(self.internal_config_path, contents, raw=True)
        else:
            client = self.load_client(ip)
            client.file_write(self.internal_config_path, contents)

    def delete_config(self, ip=None):
        """
        Deletes a configuration file
        :return: None
        :rtype: NoneType
        """
        if self.source_ip is None:
            key = self.internal_config_path
            if Configuration.exists(key, raw=True):
                Configuration.delete(key, raw=True)
        else:
            client = self.load_client(ip)
            client.file_delete(self.internal_config_path)

    def export_dict(self):
        """
        Exports the current configuration to a python dict
        :return: Data available in the Arakoon configuration
        :rtype: dict
        """
        data = {'global': {'cluster_id': self.cluster_id,
                           'cluster': ','.join(sorted(node.name for node in self.nodes)),
                           'plugins': ','.join(sorted(self._plugins))}}
        preferred_masters = [node.name for node in self.nodes if node.preferred_master is True]
        if len(preferred_masters) > 0:
            data['global']['preferred_masters'] = ','.join(preferred_masters)
        for key, value in self._extra_globals.iteritems():
            data['global'][key] = value
        for node in self.nodes:
            data[node.name] = {'ip': node.ip,
                               'home': node.home,
                               'name': node.name,
                               'fsync': 'true' if node.fsync else 'false',
                               'tlog_dir': node.tlog_dir,
                               'log_level': node.log_level,
                               'log_sinks': node.log_sinks,
                               'client_port': node.client_port,
                               'messaging_port': node.messaging_port,
                               'crash_log_sinks': node.crash_log_sinks,
                               'tlog_compression': node.tlog_compression}
        return data

    def export_ini(self):
        """
        Exports the current configuration to an ini file format
        :return: Arakoon configuration in string format
        :rtype: str
        """
        contents = RawConfigParser()
        data = self.export_dict()
        sections = data.keys()
        sections.remove('global')
        for section in ['global'] + sorted(sections):
            contents.add_section(section)
            for item in sorted(data[section]):
                contents.set(section, item, data[section][item])
        config_io = StringIO()
        contents.write(config_io)
        return str(config_io.getvalue())

    def import_config(self, config):
        """
        Imports a configuration into the ArakoonClusterConfig instance
        :return: None
        :rtype: NoneType
        """
        config = ArakoonClusterConfig.convert_config_to(config=config, return_type='DICT')
        new_sections = sorted(config.keys())
        old_sections = sorted([node.name for node in self.nodes] + ['global'])
        if old_sections != new_sections:
            raise ValueError('To add/remove sections, please use extend_cluster/shrink_cluster')

        for section, info in config.iteritems():
            if section == 'global':
                continue
            if info['name'] != section:
                raise ValueError('Names cannot be updated')

        self.nodes = []
        self._extra_globals = {}
        preferred_masters = []
        for key, value in config['global'].iteritems():
            if key == 'plugins':
                self._plugins = [plugin.strip() for plugin in value.split(',')]
            elif key == 'cluster_id':
                self.cluster_id = value
            elif key == 'cluster':
                pass
            elif key == 'preferred_masters':
                preferred_masters = value.split(',')
            else:
                self._extra_globals[key] = value
        del config['global']
        for node_name, node_info in config.iteritems():
            self.nodes.append(ArakoonNodeConfig(ip=node_info['ip'],
                                                name=node_name,
                                                home=node_info['home'],
                                                fsync=node_info['fsync'] == 'true',
                                                tlog_dir=node_info['tlog_dir'],
                                                log_level=node_info['log_level'],
                                                log_sinks=node_info['log_sinks'],
                                                client_port=int(node_info['client_port']),
                                                messaging_port=int(node_info['messaging_port']),
                                                crash_log_sinks=node_info['crash_log_sinks'],
                                                tlog_compression=node_info['tlog_compression'],
                                                preferred_master=node_name in preferred_masters))

    @staticmethod
    def get_cluster_name(internal_name):
        """
        Retrieve the name of the cluster
        :param internal_name: Name as known by the framework
        :type internal_name: str
        :return: Name known by user
        :rtype: str
        """
        config_key = '/ovs/framework/arakoon_clusters'
        if Configuration.exists(config_key):
            cluster_info = Configuration.get(config_key)
            if internal_name in cluster_info:
                return cluster_info[internal_name]
        if internal_name not in ['ovsdb', 'voldrv']:
            return internal_name

    @staticmethod
    def convert_config_to(config, return_type):
        """
        Convert an Arakoon Cluster Config to another format (JSON or INI)
        :param config: Arakoon Cluster Config representation
        :type config: dict|str
        :param return_type: Type in which the config needs to be returned (JSON or INI)
        :type return_type: str
        :return: If config is JSON, INI format is returned
        """
        if return_type not in ['JSON', 'INI']:
            raise ValueError('Unsupported return_type specified')
        if not isinstance(config, dict) and not isinstance(config, basestring):
            raise ValueError('Config should be a dict or basestring representation of an Arakoon cluster config')

        if (isinstance(config, dict) and return_type == 'JSON') or (isinstance(config, basestring) and return_type == 'INI'):
            return config

        # JSON --> INI
        if isinstance(config, dict):
            rcp = RawConfigParser()
            for section in config:
                rcp.add_section(section)
                for key, value in config[section].iteritems():
                    rcp.set(section, key, value)
            config_io = StringIO()
            rcp.write(config_io)
            return str(config_io.getvalue())

        # INI --> JSON
        if isinstance(config, basestring):
            converted = {}
            rcp = RawConfigParser()
            rcp.readfp(StringIO(config))
            for section in rcp.sections():
                converted[section] = {}
                for option in rcp.options(section):
                    if option in ['client_port', 'messaging_port']:
                        converted[section][option] = rcp.getint(section, option)
                    else:
                        converted[section][option] = rcp.get(section, option)
            return converted
