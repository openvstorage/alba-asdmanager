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
Arakoon store module, using pyrakoon
"""

import os
import time
import uuid
import random
from threading import Lock, current_thread
from source.tools.pyrakoon.pyrakoon.compat import ArakoonClient, ArakoonClientConfig
from source.tools.pyrakoon.pyrakoon.compat import ArakoonNotFound, ArakoonSockNotReadable, ArakoonSockReadNoBytes, ArakoonSockSendError, ArakoonAssertionFailed
from source.tools.log_handler import LogHandler


def locked():
    """
    Locking decorator.
    """
    def wrap(f):
        """
        Returns a wrapped function
        """
        def new_function(self, *args, **kw):
            """
            Executes the decorated function in a locked context
            """
            with self._lock:
                return f(self, *args, **kw)
        return new_function
    return wrap


class PyrakoonClient(object):
    """
    Arakoon client wrapper:
    * Uses json serialisation
    * Raises generic exception
    """
    _logger = LogHandler.get('extensions', name='pyrakoon_client')

    def __init__(self, cluster, nodes):
        """
        Initializes the client
        """
        cleaned_nodes = {}
        for node, info in nodes.iteritems():
            cleaned_nodes[str(node)] = ([str(entry) for entry in info[0]], int(info[1]))
        self._config = ArakoonClientConfig(str(cluster), cleaned_nodes)
        self._client = ArakoonClient(self._config)
        self._identifier = int(round(random.random() * 10000000))
        self._lock = Lock()
        self._batch_size = 500
        self._sequences = {}

    @locked()
    def get(self, key):
        """
        Retrieves a certain value for a given key
        """
        return PyrakoonClient._try(self._identifier, self._client.get, key)

    @locked()
    def get_multi(self, keys):
        """
        Get multiple keys at once
        """
        for item in PyrakoonClient._try(self._identifier, self._client.multiGet, keys):
            yield item

    @locked()
    def set(self, key, value, transaction=None):
        """
        Sets the value for a key to a given value
        """
        if transaction is not None:
            return self._sequences[transaction].addSet(key, value)
        return PyrakoonClient._try(self._identifier, self._client.set, key, value,)

    @locked()
    def prefix(self, prefix):
        """
        Lists all keys starting with the given prefix
        """
        next_prefix = PyrakoonClient._next_key(prefix)
        batch = None
        while batch is None or len(batch) > 0:
            batch = PyrakoonClient._try(self._identifier,
                                        self._client.range,
                                        beginKey=prefix if batch is None else batch[-1],
                                        beginKeyIncluded=batch is None,
                                        endKey=next_prefix,
                                        endKeyIncluded=False,
                                        maxElements=self._batch_size)
            for item in batch:
                yield item

    @locked()
    def prefix_entries(self, prefix):
        """
        Lists all keys starting with the given prefix
        """
        next_prefix = PyrakoonClient._next_key(prefix)
        batch = None
        while batch is None or len(batch) > 0:
            batch = PyrakoonClient._try(self._identifier,
                                        self._client.range_entries,
                                        beginKey=prefix if batch is None else batch[-1][0],
                                        beginKeyIncluded=batch is None,
                                        endKey=next_prefix,
                                        endKeyIncluded=False,
                                        maxElements=self._batch_size)
            for item in batch:
                yield item

    @locked()
    def delete(self, key, must_exist=True, transaction=None):
        """
        Deletes a given key from the store
        """
        if transaction is not None:
            if must_exist is True:
                return self._sequences[transaction].addDelete(key)
            else:
                return self._sequences[transaction].addReplace(key, None)
        if must_exist is True:
            return PyrakoonClient._try(self._identifier, self._client.delete, key)
        else:
            return PyrakoonClient._try(self._identifier, self._client.replace, key, None)

    @locked()
    def delete_prefix(self, prefix):
        """
        Removes a given prefix from the store
        """
        return PyrakoonClient._try(self._identifier, self._client.deletePrefix, prefix)

    @locked()
    def nop(self):
        """
        Executes a nop command
        """
        return PyrakoonClient._try(self._identifier, self._client.nop)

    @locked()
    def exists(self, key):
        """
        Check if key exists
        """
        return PyrakoonClient._try(self._identifier, self._client.exists, key)

    @locked()
    def assert_value(self, key, value, transaction=None):
        """
        Asserts a key-value pair
        """
        if transaction is not None:
            return self._sequences[transaction].addAssert(key, value)
        return PyrakoonClient._try(self._identifier, self._client.aSSert, key, value)

    @locked()
    def assert_exists(self, key, transaction=None):
        """
        Asserts that a given key exists
        """
        if transaction is not None:
            return self._sequences[transaction].addAssertExists(key)
        return PyrakoonClient._try(self._identifier, self._client.aSSert_exists, key)

    def begin_transaction(self):
        """
        Creates a transaction (wrapper around Arakoon sequences)
        """
        key = str(uuid.uuid4())
        self._sequences[key] = self._client.makeSequence()
        return key

    def apply_transaction(self, transaction):
        """
        Applies a transaction
        """
        return PyrakoonClient._try(self._identifier, self._client.sequence, self._sequences[transaction])

    @staticmethod
    def _try(identifier, method, *args, **kwargs):
        """
        Tries to call a given method, retry-ing if Arakoon is temporary unavailable
        """
        try:
            start = time.time()
            try:
                return_value = method(*args, **kwargs)
            except (ArakoonSockNotReadable, ArakoonSockReadNoBytes, ArakoonSockSendError):
                PyrakoonClient._logger.debug('Error during arakoon call {0}, retry'.format(method.__name__))
                time.sleep(1)
                return_value = method(*args, **kwargs)
            duration = time.time() - start
            if duration > 0.5:
                PyrakoonClient._logger.warning('Arakoon call {0} took {1}s'.format(method.__name__, round(duration, 2)))
            return return_value
        except (ArakoonNotFound, ArakoonAssertionFailed):
            # No extra logging for some errors
            raise
        except Exception:
            PyrakoonClient._logger.error('Error during {0}. Process {1}, thread {2}, clientid {3}'.format(
                method.__name__, os.getpid(), current_thread().ident, identifier
            ))
            raise

    @staticmethod
    def _next_key(key):
        """
        Calculates the next key (to be used in range queries)
        """
        encoding = 'ascii'  # For future python 3 compatibility
        array = bytearray(str(key), encoding)
        for index in range(len(array) - 1, -1, -1):
            array[index] += 1
            if array[index] < 128:
                while array[-1] == 0:
                    array = array[:-1]
                return str(array.decode(encoding))
            array[index] = 0
        return '\xff'
