#!/usr/bin/env python2
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
Watcher module for config cluster
"""

import os
import sys
import time
import uuid
import logging
from ConfigParser import RawConfigParser
from StringIO import StringIO
from source.tools.log_handler import LogHandler


class Watcher(object):
    """
    Watcher class
    """

    LOG_CONTENTS = None
    INTERNAL_CONFIG_KEY = '__ovs_config'

    def __init__(self):
        """
        Dummy init method
        """
        self._logger = LogHandler.get('extensions', name='watcher')

    def log_message(self, log_target, entry, level):
        """
        Logs an entry
        """
        if level > 0:  # 0 = debug, 1 = info, 2 = error
            self._logger.debug('[{0}] {1}'.format(log_target, entry))

    def services_running(self, target):
        """
        Check all services are running
        :param target: Target to check
        :return: Boolean
        """
        try:
            if target == 'config':
                self.log_message(target, 'Testing configuration store...', 0)
                from source.tools.configuration.configuration import Configuration
                try:
                    Configuration.list('/')
                except Exception as ex:
                    self.log_message(target, '  Error during configuration store test: {0}'.format(ex), 2)
                    return False
                if Configuration.get_store() == 'arakoon':
                    from source.tools.configuration.arakoon_config import ArakoonConfiguration
                    from source.tools.pyrakoon.pyrakoon.compat import NoGuarantee
                    client = ArakoonConfiguration.get_client()
                    contents = client.get(Watcher.INTERNAL_CONFIG_KEY, consistency=NoGuarantee())
                    if Watcher.LOG_CONTENTS != contents:
                        try:
                            # Validate whether the contents are not corrupt
                            parser = RawConfigParser()
                            parser.readfp(StringIO(contents))
                        except Exception as ex:
                            self.log_message(target, '  Configuration stored in configuration store seems to be corrupt: {0}'.format(ex), 2)
                            return False
                        temp_filename = '{0}~'.format(ArakoonConfiguration.CACC_LOCATION)
                        with open(temp_filename, 'w') as config_file:
                            config_file.write(contents)
                            config_file.flush()
                            os.fsync(config_file)
                        os.rename(temp_filename, ArakoonConfiguration.CACC_LOCATION)
                        Watcher.LOG_CONTENTS = contents
                self.log_message(target, '  Configuration store OK', 0)
                return True
        except Exception as ex:
            self.log_message(target, 'Unexpected exception: {0}'.format(ex), 2)
            return False

if __name__ == '__main__':
    given_target = sys.argv[1]
    mode = sys.argv[2]
    watcher = Watcher()
    watcher.log_message(given_target, 'Starting service', 1)
    if mode == 'wait':
        watcher.log_message(given_target, 'Waiting for master services', 1)
        while True:
            if watcher.services_running(given_target):
                watcher.log_message(given_target, 'Master services available', 1)
                sys.exit(0)
            time.sleep(5)
    if mode == 'check':
        watcher.log_message(given_target, 'Checking master services', 1)
        while True:
            if not watcher.services_running(given_target):
                watcher.log_message(given_target, 'One of the master services is unavailable', 1)
                sys.exit(1)
            time.sleep(5)
    watcher.log_message(given_target, 'Invalid parameter', 1)
    time.sleep(60)
    sys.exit(1)
