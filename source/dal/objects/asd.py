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

from source.dal.base import Base
from source.dal.objects.disk import Disk
from source.tools.configuration.configuration import Configuration
from source.tools.localclient import LocalClient
from source.tools.services.service import ServiceManager


class ASD(Base):
    """
    Represents an ASD that has been deployed.
    """

    ASD_CONFIG = '/ovs/alba/asds/{0}/config'
    ASD_SERVICE_PREFIX = 'alba-asd-{0}'
    _local_client = LocalClient()

    _table = 'asd'
    _properties = [['asd_id', str],
                   ['folder', str]]
    _relations = [['disk', Disk, 'asds']]
    _dynamics = ['service_name', 'config_key', 'has_config']

    def _service_name(self):
        return ASD.ASD_SERVICE_PREFIX.format(self.asd_id)

    def _config_key(self):
        return ASD.ASD_CONFIG.format(self.asd_id)

    def _has_config(self):
        return Configuration.exists(self.config_key)

    def export(self):
        if not self.has_config:
            raise RuntimeError('No configuration found for ASD {0}'.format(self.asd_id))
        data = Configuration.get(self.config_key)
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
            elif ServiceManager.has_service(self.service_name, ASD._local_client):
                if ServiceManager.get_service_status(self.service_name, ASD._local_client)[0] is False:
                    data.update({'state': 'error',
                                 'state_detail': 'service_failure'})
                else:
                    data.update({'state': 'ok'})
            else:
                data.update({'state': 'error',
                             'state_detail': 'service_failure'})
        return data
