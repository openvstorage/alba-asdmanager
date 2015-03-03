# Copyright 2015 CloudFounders NV
# All rights reserved

"""
API decorators
"""

import json
from flask import request, Response
from source.app import app
from source.app.exceptions import APIException
from source.tools.configuration import Configuration


def post(route):
    """
    POST decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['POST'])(_build_function(f))
    return wrap


def get(route):
    """
    GET decorator
    """
    def wrap(f):
        """
        Wrapper function
        """
        return app.route(route, methods=['GET'])(_build_function(f))
    return wrap


def _build_function(f):
    """
    Wrapping generator
    """
    def new_function(*args, **kwargs):
        """
        Wrapped function
        """
        if not _authorized():
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
                data, status = {'_success': False,
                                '_error': str(ex)}, ex.status_code
            except Exception as ex:
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
