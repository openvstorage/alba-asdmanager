# Copyright (C) 2018 iNuron NV
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
Constants involved in config management
"""

CACC_LOCATION_OLD = '/opt/asd-manager/config/arakoon_cacc.ini'  # Used for post-update.py
ASD_NODE_LOCATION = '/ovs/alba/asdnodes/{0}'
CONFIG_STORE_LOCATION = '/opt/asd-manager/config/framework.json'
ASD_NODE_CONFIG_LOCATION = '{0}/config'.format(ASD_NODE_LOCATION)                   #/ovs/alba/asdnodes/{0}/config
ASD_NODE_CONFIG_MAIN_LOCATION = '{0}/config/main'.format(ASD_NODE_LOCATION)         #/ovs/alba/asdnodes/{0}/config/main
ASD_NODE_CONFIG_MAIN_LOCATION_S3 = '{0}/config/main|s3'.format(ASD_NODE_LOCATION)   #/ovs/alba/asdnodes/{0}/config/main|s3
ASD_NODE_CONFIG_IPMI_LOCATION = '{0}/config/ipmi'.format(ASD_NODE_LOCATION)         #/ovs/alba/asdnodes/{0}/config/ipmi|ipmi
ASD_NODE_CONFIG_NETWORK_LOCATION = '{0}/config/network'.format(ASD_NODE_LOCATION)   #/ovs/alba/asdnodes/{0}/config/network