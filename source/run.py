#!/usr/bin/python2
# Copyright 2015 CloudFounders NV
# All rights reserved


from app import app
context = ('server.crt', 'server.key')
app.run(host='0.0.0.0',
        port=8500,
        debug=True,
        ssl_context=context)
