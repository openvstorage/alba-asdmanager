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
import copy
from source.tools.configuration import Configuration
from source.tools.logger import Logger
from source.tools.system import System


class ASDConfigurationManager(object):
    """
    Class which maintains the registration of ASD ownership
    This is primarily used in Dual Controller setups
    Functionality:
    - Maintain two configuration entry:
        - NODE-ASD ownership overview: an overview JSON with all node_ids and their asd_ids that they maintain
        - ASD-NODE ownership overview: reverse way of the overview above.
        Used to lookup the owner of an ASD without querying the whole NODE-ASD overview
    """
    LOCK_EXPIRATION = 60
    LOCK_WAIT = 60

    NODE_ASD_OWNERSHIP_LOCATION = '{0}/config/node_ownership'.format(Configuration.ASD_NODE_LOCATION)
    ASD_NODE_OWNER_LOCATION = '{0}/config/asd_ownership'.format(Configuration.ASD_NODE_LOCATION)

    _logger = Logger('asd_configuration')

    @classmethod
    def register_asd_usage(cls, asd_id):
        """
        Register that the current manager is owner of the ASD. Used by the Dual Controller setups
        :param asd_id: ID of ASD to register
        :return: None
        """
        node_id = System.get_my_machine_id()
        node_asd_ownership_location = cls.NODE_ASD_OWNERSHIP_LOCATION.format(node_id)
        asd_node_ownership_location = cls.ASD_NODE_OWNER_LOCATION.format(node_id)
        with cls._get_lock():
            node_asd_overview = Configuration.get(node_asd_ownership_location)
            asd_node_overview = Configuration.get(asd_node_ownership_location)
            old_node_asd_overview = copy.deepcopy(node_asd_overview)
            old_asd_node_overview = copy.deepcopy(asd_node_overview)
            # Search for potential different owners
            owner_node_id = asd_node_overview.get(asd_id)
            if owner_node_id is not None:
                # Filter out the asd
                owner_node_asd_list = node_asd_overview.get(owner_node_id, [])
                new_owner_node_asd_list = [i for i in owner_node_asd_list if i != asd_id]
                node_asd_overview[owner_node_id] = new_owner_node_asd_list
            asd_node_overview[asd_id] = node_id
            try:
                Configuration.set(node_asd_ownership_location, node_asd_overview)
                Configuration.set(asd_node_ownership_location, asd_node_overview)
            except Exception as ex:
                # @todo overlook this. Might be dangerous
                cls._logger.exception('Exception occurred while saving the new ownership of ASD {0}'.format(asd_id))
                for args in [(node_asd_ownership_location, old_node_asd_overview), (asd_node_ownership_location, old_asd_node_overview)]:
                    try:
                        Configuration.set(*args)
                    except:
                        cls._logger.exception('Exception occurred while reverting ownership of ASD {0}'.format(asd_id))
                raise ex

    @classmethod
    def has_ownership(cls, asd_id):
        """
        Check if the current manager has the ownership of the asd
        This does not guarantee that the ownership remains after the method was called!
        :param asd_id: ID of the ASD to check for
        :return: True if the ownership is from this node else False
        """
        node_id = System.get_my_machine_id()
        asd_node_ownership_location = cls.ASD_NODE_OWNER_LOCATION.format(node_id)
        with cls._get_lock():  # Locking as someone else might be writing at this moment
            asd_node_overview = Configuration.get(asd_node_ownership_location)
            return asd_node_overview.get(asd_id) == node_id

    @classmethod
    def _get_lock(cls):
        """
        Retrieve the lock to use
        :return: The Configuration lock
        :rtype from source.tools.configuration.ConfigurationLock
        """
        return Configuration.lock('asd_manager_asd_registration', wait=cls.LOCK_WAIT, expiration=cls.LOCK_EXPIRATION)
