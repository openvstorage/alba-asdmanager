# Copyright 2015 Open vStorage NV
# All rights reserved

"""
API decorators
"""

import json
import traceback
import subprocess
from flask import request, Response
from source.app import app
from source.app.exceptions import APIException
from source.tools.configuration import Configuration
from source.tools.filemutex import FileMutex


def post(route, authenticate=True):
    """
    POST decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['POST'])(_build_function(f, authenticate))
    return wrap


def get(route, authenticate=True):
    """
    GET decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['GET'])(_build_function(f, authenticate))
    return wrap


def _build_function(f, authenticate):
    """
    Wrapping generator
    """
    def new_function(*args, **kwargs):
        """
        Wrapped function
        """
        if authenticate is True and not _authorized():
            data, status = {'_success': False,
                            '_error': 'Invalid credentials'}, 401
        else:
            try:
                return_data = f(*args, **kwargs)
                if return_data is None:
                    return_data = {}
                if isinstance(return_data, tuple):
                    data, status = return_data[0], return_data[1]
                else:
                    data, status = return_data, 200
                data['_success'] = True
                data['_error'] = ''
            except APIException as ex:
                print traceback.print_exc()
                data, status = {'_success': False,
                                '_error': str(ex)}, ex.status_code
            except subprocess.CalledProcessError as ex:
                print traceback.print_exc()
                data, status = {'_success': False,
                                '_error': ex.output}, 500
            except Exception as ex:
                print traceback.print_exc()
                data, status = {'_success': False,
                                '_error': str(ex)}, 500
        data['_version'] = 1

        return Response(json.dumps(data), content_type='application/json', status=status)

    new_function.__name__ = f.__name__
    new_function.__module__ = f.__module__
    return new_function


def _authorized():
    """
    Indicates whether a call is authenticated
    """
    config = Configuration()
    auth = request.authorization
    return auth and auth.username == config.data['main']['username'] and auth.password == config.data['main']['password']
