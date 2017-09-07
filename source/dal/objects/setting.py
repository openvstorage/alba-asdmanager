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
Setting module
"""

from ovs_extensions.dal.structures import Property
from source.dal.asdbase import ASDBase


class Setting(ASDBase):
    """
    Represents a global Setting for the ALBA ASD manager
    """
    _table = 'setting'
    _properties = [Property(name='code', property_type=str, unique=True, mandatory=True),
                   Property(name='value', property_type=None, unique=False, mandatory=True)]
    _relations = []
    _dynamics = []
