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

import os
import json
from ConfigParser import RawConfigParser
from source.tools.configuration.configuration import Configuration
from source.tools.localclient import CalledProcessError, LocalClient
from source.tools.log_handler import LogHandler
from StringIO import StringIO


class ArakoonNodeConfig(object):
    """
    cluster node config parameters
    """
    def __init__(self, name, ip, client_port, messaging_port, log_sinks, crash_log_sinks, home, tlog_dir):
        """
        Initializes a new Config entry for a single Node
        """
        self.name = name
        self.ip = ip
        self.client_port = int(client_port)
        self.messaging_port = int(messaging_port)
        self.tlog_compression = 'snappy'
        self.log_level = 'info'
        self.log_sinks = log_sinks
        self.crash_log_sinks = crash_log_sinks
        self.home = home
        self.tlog_dir = tlog_dir
        self.fsync = True

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
    CONFIG_KEY = '/ovs/arakoon/{0}/config'
    CONFIG_FILE = '/opt/asd-manager/config/arakoon_{0}.ini'

    def __init__(self, cluster_id, filesystem, plugins=None):
        """
        Initializes an empty Cluster Config
        """
        self.filesystem = filesystem
        self.cluster_id = cluster_id
        self._extra_globals = {'tlog_max_entries': 5000}
        self.nodes = []
        self._plugins = []
        if isinstance(plugins, list):
            self._plugins = plugins
        elif isinstance(plugins, basestring):
            self._plugins.append(plugins)

    @property
    def config_path(self):
        """
        Retrieve the configuration path
        :return: Configuration path
        """
        if self.filesystem is False:
            return ArakoonClusterConfig.CONFIG_KEY.format(self.cluster_id)
        return ArakoonClusterConfig.CONFIG_FILE.format(self.cluster_id)

    def _load_client(self, ip):
        if self.filesystem is True:
            if ip is None:
                raise RuntimeError('An IP should be passed for filesystem configuration')
            return LocalClient(ip, username='root')

    def load_config(self, ip=None):
        """
        Reads a configuration from reality
        """
        if self.filesystem is False:
            contents = Configuration.get(self.config_path, raw=True)
        else:
            client = self._load_client(ip)
            contents = client.file_read(self.config_path)

        parser = RawConfigParser()
        parser.readfp(StringIO(contents))

        self.nodes = []
        self._extra_globals = {}
        for key in parser.options('global'):
            if key == 'plugins':
                self._plugins = [plugin.strip() for plugin in parser.get('global', 'plugins').split(',')]
            elif key == 'cluster_id':
                self.cluster_id = parser.get('global', 'cluster_id')
            elif key == 'cluster':
                pass  # Ignore these
            else:
                self._extra_globals[key] = parser.get('global', key)
        for node in parser.get('global', 'cluster').split(','):
            node = node.strip()
            self.nodes.append(ArakoonNodeConfig(name=node,
                                                ip=parser.get(node, 'ip'),
                                                client_port=parser.get(node, 'client_port'),
                                                messaging_port=parser.get(node, 'messaging_port'),
                                                log_sinks=parser.get(node, 'log_sinks'),
                                                crash_log_sinks=parser.get(node, 'crash_log_sinks'),
                                                home=parser.get(node, 'home'),
                                                tlog_dir=parser.get(node, 'tlog_dir')))

    def export(self):
        """
        Exports the current configuration to a python dict
        """
        data = {'global': {'cluster_id': self.cluster_id,
                           'cluster': ','.join(sorted(node.name for node in self.nodes)),
                           'plugins': ','.join(sorted(self._plugins))}}
        for key, value in self._extra_globals.iteritems():
            data['global'][key] = value
        for node in self.nodes:
            data[node.name] = {'name': node.name,
                               'ip': node.ip,
                               'client_port': node.client_port,
                               'messaging_port': node.messaging_port,
                               'tlog_compression': node.tlog_compression,
                               'log_level': node.log_level,
                               'log_sinks': node.log_sinks,
                               'crash_log_sinks': node.crash_log_sinks,
                               'home': node.home,
                               'tlog_dir': node.tlog_dir,
                               'fsync': 'true' if node.fsync else 'false'}
        return data

    def export_ini(self):
        """
        Exports the current configuration to an ini file format
        """
        contents = RawConfigParser()
        data = self.export()
        for section in data:
            contents.add_section(section)
            for item in data[section]:
                contents.set(section, item, data[section][item])
        config_io = StringIO()
        contents.write(config_io)
        return config_io.getvalue()

    def write_config(self, ip=None):
        """
        Writes the configuration down to in the format expected by Arakoon
        """
        contents = self.export_ini()
        if self.filesystem is False:
            Configuration.set(self.config_path, contents, raw=True)
        else:
            client = self._load_client(ip)
            client.file_write(self.config_path, contents)

    def delete_config(self, ip=None):
        """
        Deletes a configuration file
        """
        if self.filesystem is False:
            key = self.config_path
            if Configuration.exists(key, raw=True):
                Configuration.delete(key, raw=True)
        else:
            client = self._load_client(ip)
            client.file_delete(self.config_path)
