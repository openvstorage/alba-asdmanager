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
API decorators
"""

import os
import json
import time
import subprocess
from flask import request, Response
from ovs_extensions.api.exceptions import HttpBadRequestException
from source.app import app
from source.tools.configuration import Configuration
from source.tools.log_handler import LogHandler

NODE_ID = os.environ['ASD_NODE_ID']
_logger = LogHandler.get('asd-manager', name='api')


def post(route, authenticate=True):
    """
    POST decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['POST'])(_build_function(f, authenticate, route, 'POST'))
    return wrap


def get(route, authenticate=True):
    """
    GET decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['GET'])(_build_function(f, authenticate, route, 'GET'))
    return wrap


def delete(route, authenticate=True):
    """
    DELETE decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['DELETE'])(_build_function(f, authenticate, route, 'DELETE'))
    return wrap


def patch(route, authenticate=True):
    """
    PATCH decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['PATCH'])(_build_function(f, authenticate, route, 'PATCH'))
    return wrap


def _build_function(f, authenticate, route, method):
    """
    Wrapping generator
    """
    def new_function(*args, **kwargs):
        """
        Wrapped function
        """
        start = time.time()
        if authenticate is True and not _authorized():
            data = {'_success': False, '_error': 'Invalid credentials'}
            status = 401
        else:
            try:
                if args or kwargs:
                    _logger.info('{0} {1} - Entering with {2} {3}'.format(method, route, json.dumps(args), json.dumps(kwargs)))
                else:
                    _logger.info('{0} {1} - Entering'.format(method, route))
                return_data = f(*args, **kwargs)
                _logger.debug('{0} {1} - Leaving'.format(method, route))
                if return_data is None:
                    return_data = {}
                if isinstance(return_data, tuple):
                    data = return_data[0]
                    status = return_data[1]
                else:
                    data = return_data
                    status = 200
                data['_success'] = True
                data['_error'] = ''
            except HttpBadRequestException as ex:
                _logger.exception('API exception')
                data = {'_success': False, '_error': str(ex)}
                status = ex.status_code
            except subprocess.CalledProcessError as ex:
                _logger.exception('CPE exception')
                data = {'_success': False, '_error': ex.output if ex.output != '' else str(ex)}
                status = 500
            except Exception as ex:
                _logger.exception('Unexpected exception')
                data = {'_success': False, '_error': str(ex)}
                status = 500
        data['_version'] = 3
        data['_duration'] = time.time() - start
        return Response(json.dumps(data), content_type='application/json', status=status)

    new_function.original = f
    new_function.__name__ = f.__name__
    new_function.__module__ = f.__module__
    return new_function


def _authorized():
    """
    Indicates whether a call is authenticated
    """
    username = Configuration.get('/ovs/alba/asdnodes/{0}/config/main|username'.format(NODE_ID))
    password = Configuration.get('/ovs/alba/asdnodes/{0}/config/main|password'.format(NODE_ID))
    auth = request.authorization
    return auth and auth.username == username and auth.password == password
