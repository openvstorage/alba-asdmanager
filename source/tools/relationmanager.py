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
from ovs_extensions.generic.configuration.exceptions import ConfigurationNotFoundException


class RelationManager(object):
    """
    Class which maintains the registration of ASD ownership/nodecluster relations
    This is primarily used in Dual Controller setups
    Functionality:
    - Maintain two configuration entry:
        - NODE-ASD ownership overview: an overview JSON with all node_ids and their asd_ids that they maintain
        - ASD-NODE ownership overview: reverse way of the overview above.
        Used to lookup the owner of an ASD without querying the whole NODE-ASD overview
    """
    LOCK_EXPIRATION = 60
    LOCK_WAIT = 60
    MAX_REGISTER_RETRIES = 20

    NODE_ASD_OWNERSHIP_LOCATION = '{0}/config/node_ownership'.format(Configuration.ASD_NODE_LOCATION)
    ASD_NODE_OWNER_LOCATION = '{0}/config/asd_ownership'.format(Configuration.ASD_NODE_LOCATION)

    CLUSTER_NODE_RELATION_LOCATION = '{0}/config/cluster_node_relation'.format(Configuration.ASD_NODE_LOCATION)
    NODE_CLUSTER_RELATION_LOCATION = '{0}/config/node_cluster_relation'.format(Configuration.ASD_NODE_LOCATION)

    _logger = Logger('asd_configuration')

    @classmethod
    def register_asd_usage(cls, asd_id):
        # type: (int) -> None
        """
        Register that the current manager is owner of the ASD. Used by the Dual Controller setups
        :param asd_id: ID of ASD to register
        :type asd_id: int
        :return: None
        """
        # Wrap it in a lambda so it does not get executed here
        Configuration.safely_store(callback=lambda: cls._get_registering_data(asd_id),
                                   max_retries=20)

    @classmethod
    def _get_registering_data(cls, asd_id):
        """
        Gets all data to be saved. Used as callbacks for safely_store
        :param asd_id: ID of ASD to register
        :type asd_id: int
        :return: The callback data
        :rtype: list[tuple[str, dict, none]
        """
        node_id = System.get_my_machine_id()
        node_asd_ownership_location = cls.NODE_ASD_OWNERSHIP_LOCATION.format(node_id)
        asd_node_ownership_location = cls.ASD_NODE_OWNER_LOCATION.format(node_id)

        success = False
        last_exception = None
        tries = 0
        while success is False:
            tries += 1
            if tries > cls.MAX_REGISTER_RETRIES:
                raise last_exception
            try:

                # Unable to use 'default=' as the assertion requires to know if the key was set to {} or not
                node_asd_overview = Configuration.get(node_asd_ownership_location)
                old_node_asd_overview = copy.deepcopy(node_asd_overview)
            except ConfigurationNotFoundException:
                node_asd_overview = {}
                old_node_asd_overview = None
            try:
                asd_node_overview = Configuration.get(asd_node_ownership_location)
                old_asd_node_overview = copy.deepcopy(asd_node_overview)
            except ConfigurationNotFoundException:
                asd_node_overview = {}
                old_asd_node_overview = None
            # Search for potential different owners
            owner_node_id = asd_node_overview.get(asd_id)
            if owner_node_id is not None:
                owner_node_asd_list = node_asd_overview.get(owner_node_id, [])
                if owner_node_id == node_id:  # Nothing changes when the owner is the same
                    if asd_id not in owner_node_asd_list:
                        # In case something messed up the config. This way the file can be rebuilt with this method
                        owner_node_asd_list.append(asd_id)
                    new_owner_node_asd_list = owner_node_asd_list
                else:
                    # Initiate a config cleanup
                    new_owner_node_asd_list = [i for i in owner_node_asd_list if i != asd_id]
                    raise NotImplementedError()
                    # @todo this should be saved in both registers and afterwards the register should happen again
            else:
                new_owner_node_asd_list = [asd_id]
            node_asd_overview[owner_node_id] = new_owner_node_asd_list
            asd_node_overview[asd_id] = node_id
            return [(node_asd_ownership_location, node_asd_overview, old_node_asd_overview),
                    (asd_node_ownership_location, asd_node_overview, old_asd_node_overview)]

    @classmethod
    def has_ownership(cls, asd_id):
        # type: (str) -> bool
        """
        Check if the current manager has the ownership of the asd
        This does not guarantee that the ownership remains after the method was called!
        :param asd_id: ID of the ASD to check for
        :type asd_id: str
        :return: True if the ownership is from this node else False
        :rtype: bool
        """
        node_id = System.get_my_machine_id()
        asd_node_ownership_location = cls.ASD_NODE_OWNER_LOCATION.format(node_id)
        try:
            asd_node_overview = Configuration.get(asd_node_ownership_location, default={})  # type: Dict[str, List[str]]
            return asd_node_overview.get(asd_id) == node_id
        except:
            cls._logger.exception('Exception occurred while reading the ownership overview for ASD {0}'.format(asd_id))
            raise

    @classmethod
    def is_claimable(cls, asd_id):
        # type: (str) -> bool
        """
        Check if the current manager can claim the ownership of the asd
        :param asd_id: ID of the ASD to check for
        :type asd_id: str
        :return: True if the ownership is from this node else False
        :rtype: bool
        """
        node_id = System.get_my_machine_id()
        asd_node_ownership_location = cls.ASD_NODE_OWNER_LOCATION.format(node_id)
        try:
            asd_node_overview = Configuration.get(asd_node_ownership_location, default={})  # type: Dict[str, List[str]]
            return asd_node_overview.get(asd_id) is None
        except:
            cls._logger.exception('Exception occurred while reading the ownership overview for ASD {0}'.format(asd_id))
            raise

    @classmethod
    def is_part_of_cluster(cls):
        node_id = System.get_my_machine_id()
        node_cluster_relation = cls.NODE_CLUSTER_RELATION_LOCATION.format(node_id)
        try:
            node_cluster_overview = Configuration.get(node_cluster_relation, default={})
            return node_cluster_overview.get(node_id) is not None
        except:
            cls._logger.exception('Exception occurred while reading the cluster relation overview for node {0}'.format(node_id))
            raise

    @classmethod
    def _get_lock(cls):
        """
        Retrieve the lock to use
        :return: The Configuration lock
        :rtype from source.tools.configuration.ConfigurationLock
        """
        return Configuration.lock('asd_manager_asd_registration', wait=cls.LOCK_WAIT, expiration=cls.LOCK_EXPIRATION)
