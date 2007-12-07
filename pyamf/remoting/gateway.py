# -*- encoding: utf8 -*-
#
# Copyright (c) 2007 The PyAMF Project. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""
Server implementations.

@author: U{Thijs Triemstra<mailto:info@collab.nl>}
@author: U{Nick Joyce<mailto:nick@boxdesign.co.uk>}

@since: 0.1.0
"""

import sys, traceback, types

import pyamf
from pyamf import remoting

#: AMF mimetype.
CONTENT_TYPE = 'application/x-amf'

fault_alias = pyamf.get_class_alias(remoting.ErrorFault)

class BaseServiceError(Exception, remoting.ErrorFault):
    pass

class UnknownServiceError(BaseServiceError):
    _amf_code = 'Service.ResourceNotFound'

pyamf.register_class(UnknownServiceError, attrs=fault_alias.attrs)

class UnknownServiceMethodError(BaseServiceError):
    _amf_code = 'Service.MethodNotFound'

pyamf.register_class(UnknownServiceMethodError, attrs=fault_alias.attrs)

class InvalidServiceMethodError(BaseServiceError):
    _amf_code = 'Service.MethodInvalid'

pyamf.register_class(InvalidServiceMethodError, attrs=fault_alias.attrs)

del fault_alias

class ServiceWrapper(object):
    """
    Wraps a supplied service with extra functionality.

    @ivar service: The original service.
    @type service: C{callable}

    @ivar authenticator: Will be called before the service is called to check
        that the supplied credentials (if any) can access the service.
    @type authenticator: callable with two args, username and password. Returns
        a C{bool} based on the success of authentication.

    @ivar description: A description of the service.
    @type description: C{str}

    @raise NameError: Calls to private methods are not allowed.
    @raise NameError: Unknown method.
    @raise TypeError: Service method must be callable.
    @raise TypeError: Service must be callable.
    """

    def __init__(self, service, authenticator=None, description=None):
        self.service = service
        self.authenticator = authenticator
        self.description = description

    def __cmp__(self, other):
        if isinstance(other, ServiceWrapper):
            return cmp(self.__dict__, other.__dict__)

        return cmp(self.service, other)

    def _get_service_func(self, method, params):
        service = None

        if isinstance(self.service, (type, types.ClassType)):
            service = self.service()
        else:
            service = self.service

        if method is not None:
            method = str(method)

            if method.startswith('_'):
                raise InvalidServiceMethodError, "Calls to private methods are not allowed"

            try:
                func = getattr(service, method)
            except AttributeError:
                raise UnknownServiceMethodError, "Unknown method %s" % str(method)

            if not callable(func):
                raise InvalidServiceMethodError, "Service method %s must be callable" % str(method)

            return func

        if not callable(service):
            raise UnknownServiceMethodError, "Unknown method %s" % str(self.service)

        return service

    def __call__(self, method, params):
        """
        Executes the service.

        If the service is a class, it will be instantiated.

        @param method: The method to call on the service.
        @type method: C{None} or C{mixed}
        @param params: The params to pass to the service.
        @type params: C{list} or C{tuple}
        @return: The result of the execution.
        @rtype: C{mixed}
        """
        func = self._get_service_func(method, params)

        return func(*params)

class ServiceRequest(object):
    """
    Remoting service request.

    @ivar request: The request to service.
    @type request: L{Envelope<pyamf.remoting.Envelope>}
    @ivar service: Facilitates the request.
    @type service: L{ServiceWrapper}
    @ivar method: The method to call on the service. A value of C{None}
        means that the service will be called directly.
    @type method: C{None} or C{str}
    """

    def __init__(self, request, service, method):
        self.request = request
        self.service = service
        self.method = method

    def __call__(self, *args):
        return self.service(self.method, args)

    def authenticate(self, username, password):
        """
        Authenticates the supplied credentials for the service.

        The default is to allow anything through.

        @return: Boolean determining whether the supplied credentials can
            access the service.
        @rtype: C{bool}
        """
        if self.service.authenticator is None:
            # The default is to allow anything through
            return True

        return self.service.authenticator(username, password)

class ServiceCollection(dict):
    """
    I hold a collection of services, mapping names to objects.
    """

    def __contains__(self, value):
        if isinstance(value, basestring):
            return value in self.keys()

        return value in self.values()

class BaseGateway(object):
    """
    Generic Remoting gateway.

    @ivar services: A map of service names to callables.
    @type services: L{ServiceCollection}
    """

    _request_class = ServiceRequest

    def __init__(self, services={}):
        """
        @param services: Initial services.
        @type services: C{dict}
        @raise TypeError: C{dict} type required for C{services}.
        """
        self.services = ServiceCollection()

        if not hasattr(services, 'iteritems'):
            raise TypeError, "dict type required for services"

        for name, service in services.iteritems():
            self.addService(service, name)

    def addService(self, service, name=None, authenticator=None, description=None):
        """
        Adds a service to the gateway.

        @param service: The service to add to the gateway.
        @type service: callable, class instance, or a module
        @param name: The name of the service.
        @type name: C{str}
        @param authenticator: A callable that will check the credentials of
            the request before allowing access to the service.
        @type authenticator: C{Callable}

        @raise RemotingError: Service already exists.
        @raise TypeError: C{service} must be callable or a module.
        """
        if isinstance(service, (int, long, float, basestring)):
            raise TypeError, "service cannot be a scalar value"

        allowed_types = (types.ModuleType, types.FunctionType, types.DictType,
            types.MethodType, types.InstanceType, types.ObjectType)

        if not callable(service) and not isinstance(service, allowed_types):
            raise TypeError, "service must be callable, a module, or an object"

        if name is None:
            # TODO: include the module in the name
            if isinstance(service, (type, types.ClassType)):
                name = service.__name__
            elif isinstance(service, (types.FunctionType)):
                name = service.func_name
            elif isinstance(service, (types.ModuleType)):
                name = service.__name__
            else:
                name = str(service)

        if name in self.services:
            raise remoting.RemotingError, "Service %s already exists" % name

        self.services[name] = ServiceWrapper(service, authenticator,
            description)

    def removeService(self, service):
        """
        Removes a service from the gateway.

        @param service: The service to remove from the gateway.
        @type service: callable or a class instance
        @raise NameError: Service not found.
        """
        if service not in self.services:
            raise NameError, "Service %s not found" % str(service)

        for name, wrapper in self.services.iteritems():
            if isinstance(service, basestring) and service == name:
                del self.services[name]

                return
            elif isinstance(service, ServiceWrapper) and wrapper == service:
                del self.services[name]

                return
            elif isinstance(service, (type, types.ClassType,
                types.FunctionType)) and wrapper.service == service:
                del self.services[name]

                return

        # shouldn't ever get here
        raise RuntimeError, "Something went wrong ..."

    def getServiceRequest(self, message):
        """
        Returns a service based on the message.

        @raise RemotingError: Unknown service.
        @param message: The AMF message.
        @type message: L{Message<remoting.Message>}
        @rtype: L{ServiceRequest}
        """
        target = message.target

        try:
            return self._request_class(
                message.envelope, self.services[target], None)
        except KeyError:
            pass

        try:
            name, meth = target.rsplit('.', 1)
            return self._request_class(
                message.envelope, self.services[name], meth)
        except (ValueError, KeyError):
            pass

        # All methods exhausted
        raise NameError, "Unknown service %s" % target

    def getProcessor(self, request):
        """
        @param request:
        @type request:
        """
        if 'DescribeService' in request.headers:
            return NotImplementedError

        return self.processRequest

    def authenticateRequest(self, service_request, request):
        """
        Authenticates the request against the service.

        @param service_request:
        @type service_request:
        
        @param request:
        @type request:
        
        @raise RemotingError: Invalid credentials object.
        """ 
        username = password = None

        if 'Credentials' in request.headers:
            cred = request.headers['Credentials']

            try:
                username = cred['userid']
                password = cred['password']
            except KeyError:
                raise remoting.RemotingError, "Invalid credentials object"

        return service_request.authenticate(username, password)

    def processRequest(self, request):
        """
        Processes a request.

        @param request: The request to be processed.
        @type request: L{Message<remoting.Message>}
        
        @return: The response to the request.
        @rtype: L{Message<remoting.Message>}
        """
        response = remoting.Response(None)

        try:
            service_request = self.getServiceRequest(request)
        except NameError, e:
            response.status = remoting.STATUS_ERROR
            response.body = build_fault()

            return response

        # we have a valid service, now attempt authentication
        try:
            authd = self.authenticateRequest(service_request, request)
        except (SystemExit, KeyboardInterrupt):
            raise
        except:
            response.status = remoting.STATUS_ERROR
            response.body = build_fault()

            return response

        if not authd:
            # authentication failed
            response.status = remoting.STATUS_ERROR
            response.body = Fault(code='AuthenticationError',
                description='Authentication failed')

            return response

        # process the request
        try:
            response.body = service_request(*request.body)
        except (SystemExit, KeyboardInterrupt):
            raise
        except:
            response.body = build_fault()
            response.status = remoting.STATUS_ERROR

        return response

    def getResponse(self, request):
        """
        Returns the response to the request.

        Any implementing gateway must define this function.

        @param request: The AMF request.
        @type request: L{Envelope<remoting.Envelope>}

        @return: The AMF response.
        @rtype: L{Envelope<remoting.Envelope>}
        """
        raise NotImplementedError

def build_fault():
    """
    Builds a L{remoting.ErrorFault} object based on the last exception raised.
    """
    cls, e, tb = sys.exc_info()

    if hasattr(cls, '_amf_code'):
        code = cls._amf_code
    else:
        code = cls.__name__

    return remoting.ErrorFault(code=code, description=str(e),
        details=traceback.format_exception(cls, e, tb))