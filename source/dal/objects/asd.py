# Copyright (C) 2017 iNuron NV
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
This is the ASD module
"""

from ovs_extensions.dal.structures import Property
from ovs_extensions.generic.sshclient import SSHClient
from source.dal.asdbase import ASDBase
from source.dal.objects.disk import Disk
from source.tools.configuration import Configuration
from source.tools.servicefactory import ServiceFactory


class ASD(ASDBase):
    """
    Represents an ASD that has been deployed.
    """

    ASD_CONFIG = '/ovs/alba/asds/{0}/config'
    ASD_SERVICE_PREFIX = 'alba-asd-{0}'
    _local_client = SSHClient(endpoint='127.0.0.1', username='root')
    _service_manager = ServiceFactory.get_manager()

    _table = 'asd'
    _properties = [Property(name='port', property_type=int, unique=True, mandatory=True),
                   Property(name='hosts', property_type=list, unique=False, mandatory=True),
                   Property(name='asd_id', property_type=str, unique=True, mandatory=True),
                   Property(name='folder', property_type=str, unique=False, mandatory=False)]
    _relations = [['disk', Disk, 'asds']]
    _dynamics = ['service_name', 'config_key', 'has_config']

    def _service_name(self):
        return ASD.ASD_SERVICE_PREFIX.format(self.asd_id)

    def _config_key(self):
        return ASD.ASD_CONFIG.format(self.asd_id)

    def _has_config(self):
        return Configuration.exists(self.config_key)

    def export(self):
        """
        Exports the ASD information to a dict structure
        :return: Representation of the ASD as dict
        :rtype: dict
        """
        if not self.has_config:
            raise RuntimeError('No configuration found for ASD {0}'.format(self.asd_id))
        data = Configuration.get(self.config_key)
        for prop in self._properties:
            if prop.name == 'hosts':
                data['ips'] = getattr(self, prop.name)
            else:
                data[prop.name] = getattr(self, prop.name)
        if self.disk.state == 'MISSING':
            data.update({'state': 'error',
                         'state_detail': 'missing'})
        else:
            output, error = ASD._local_client.run(['ls', '{0}/{1}/'.format(self.disk.mountpoint, self.folder)],
                                                  allow_nonzero=True, return_stderr=True)
            output += error
            if 'Input/output error' in output:
                data.update({'state': 'error',
                             'state_detail': 'io_error'})
            elif ASD._service_manager.has_service(self.service_name, ASD._local_client):
                service_state = ASD._service_manager.get_service_status(self.service_name, ASD._local_client)
                if service_state == 'activating':
                    data.update({'state': 'warning',
                                 'state_detail': 'service_starting'})
                elif service_state == 'active':
                    data.update({'state': 'ok',
                                 'state_detail': None})
                else:
                    data.update({'state': 'error',
                                 'state_detail': 'service_failure'})
            else:
                data.update({'state': 'error',
                             'state_detail': 'service_failure'})
        return data
