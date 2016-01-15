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
Configuration related code
"""

from ovs.extensions.db.etcd.configuration import EtcdConfiguration
from source.tools.filemutex import FileMutex


class Configuration(object):
    """
    Configuration class for the ASD manager
    """
    def __init__(self):
        self.mutex = FileMutex('config')

    def __enter__(self):
        self.mutex.acquire()
        return self

    def __exit__(self, *args, **kwargs):
        _ = args, kwargs
        self.mutex.release()

    def migrate(self, node_id):
        """
        Bump version
        :param node_id: ID of the ALBA node
        :return: None
        """
        try:
            self.__enter__()
            version = 0
            if EtcdConfiguration.exists('/ovs/alba/asdnodes/{0}/config/main|version'.format(node_id)):
                version = EtcdConfiguration.get('/ovs/alba/asdnodes/{0}/config/main|version'.format(node_id))

            if version < 1:
                # No migrations in the initial version
                print 'Migrating configuration to version 1'
                version = 1
            if version < 2:
                # print 'Migrating configuration to version 2'
                # @TODO: in the future, here is where upgrades to the configuration file should be located
                # version = 2
                pass
            EtcdConfiguration.set('/ovs/alba/asdnodes/{0}/config/main|version'.format(node_id), version)
        finally:
            self.__exit__()
