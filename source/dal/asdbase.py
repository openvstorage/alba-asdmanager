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
This package contains the DAL object's base class.
"""

from ovs_extensions.dal.base import Base


class ASDBase(Base):
    """
    Base object that is inherited by all DAL objects. It contains base logic like save, delete, ...
    """
    NAME = 'asd'
    SOURCE_FOLDER = '/opt/asd-manager/source'
    DATABASE_FOLDER = '/opt/asd-manager/db'
