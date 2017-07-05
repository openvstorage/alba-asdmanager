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
This is the ASD's module
"""

import json
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
    _dynamics = ['service_name', 'config_key', 'has_config', 'alba_info']

    def _service_name(self):
        return ASD.ASD_SERVICE_PREFIX.format(self.asd_id)

    def _config_key(self):
        return ASD.ASD_CONFIG.format(self.asd_id)

    def _has_config(self):
        return Configuration.exists(self.config_key)

    def _alba_info(self):
        host = self.hosts[0] if len(self.hosts) > 0 else '127.0.0.1'
        info = {'loaded': False,
                'result': None}
        try:
            output = json.loads(ASD._local_client.run(allow_nonzero=True,
                                                      command=['alba', 'get-osd-claimed-by', '--host={0}'.format(host), '--port={0}'.format(self.port), '--to-json']))
            if output.get('success') is True:
                info['loaded'] = True
                info['result'] = output.get('result')
            else:
                info['result'] = 'Failed to retrieve ALBA info for ASD {0}:{1}'.format(host, self.port)
        except ValueError:
            info['result'] = 'Could not json parse ALBA output for ASD {0}:{1}'.format(host, self.port)
        return info

    def export(self):
        """
        Exports this ASD's information to a dict structure
        :return: Representation of the ASD as dict
        :rtype: dict
        """
        if not self.has_config:
            raise RuntimeError('No configuration found for ASD {0}'.format(self.asd_id))
        data = Configuration.get(self.config_key)
        data['claimed_by'] = self.alba_info['result'] if self.alba_info['loaded'] is True else None
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
                if ASD._service_manager.get_service_status(self.service_name, ASD._local_client) != 'active':
                    data.update({'state': 'error',
                                 'state_detail': 'service_failure'})
                else:
                    data.update({'state': 'ok'})
            else:
                data.update({'state': 'error',
                             'state_detail': 'service_failure'})
        return data
