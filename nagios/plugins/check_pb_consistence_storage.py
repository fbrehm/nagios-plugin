#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
@author: Frank Brehm
@contact: frank.brehm@profitbricks.com
@copyright: © 2010 - 2014 by Frank Brehm, Berlin
@summary: Module for CheckPbConsistenceStoragePlugin class for checking
          consistence of storage volumes against the target state
          of the provisioning database
"""

# Standard modules
import os
import sys
import re
import logging
import socket
import textwrap
import time
import socket

from numbers import Number

# Third party modules

# Own modules

import nagios
from nagios import BaseNagiosError

from nagios.common import pp, caller_search_path

from nagios.plugin import NagiosPluginError

from nagios.plugin.range import NagiosRange

from nagios.plugin.threshold import NagiosThreshold

from nagios.plugin.extended import ExtNagiosPluginError
from nagios.plugin.extended import ExecutionTimeoutError
from nagios.plugin.extended import CommandNotFoundError
from nagios.plugin.extended import ExtNagiosPlugin

from nagios.plugin.config import NoConfigfileFound
from nagios.plugin.config import NagiosPluginConfig

from dcmanagerclient.client import RestApi

#---------------------------------------------
# Some module variables

__version__ = '0.0.1'
__copyright__ = 'Copyright (c) 2014 Frank Brehm, Berlin.'

DEFAULT_TIMEOUT = 30
DEFAULT_API_URL = 'https://dcmanager.pb.local/dc/api'
DEFAULT_API_AUTHTOKEN = '604a3b5f6db67e5a3a48650313ddfb2e8bcf211b'

log = logging.getLogger(__name__)

#==============================================================================
class CheckPbConsistenceStoragePlugin(ExtNagiosPlugin):
    """
    A special /Nagios/Icinga plugin to check the existent volumes on a storage
    server against the target state from provisioning database.
    The target volumes from database are get via REST API calls.
    """

    #--------------------------------------------------------------------------
    def __init__(self):
        """
        Constructor of the CheckPbConsistenceStoragePlugin class.
        """

        usage = """\
                %(prog)s [options] [-H <server_name>] [-c <critical_volume_errors>] [-w <warning_volume_errors>]
                """
        usage = textwrap.dedent(usage).strip()
        usage += '\n       %(prog)s --usage'
        usage += '\n       %(prog)s --help'

        blurb = __copyright__ + "\n\n"
        blurb += ("Checks the existent volumes on a storage server against " +
                    "the target state from provisioning database.")

        super(CheckPbConsistenceStoragePlugin, self).__init__(
                shortname = 'PB_CONSIST_STORAGE',
                usage = usage, blurb = blurb,
                version = __version__, timeout = DEFAULT_TIMEOUT,
        )

        self._hostname = socket.gethostname()
        """
        @ivar: the hostname of the current storage server
        @type: str
        """

        self._api_url = None
        """
        @ivar: the URL of the Dc-Manager REST API
        @type: str
        """

        self._api_authtoken = None
        """
        @ivar: the authentication token for the DC-Manager REST API.
        @type: str
        """

        self._add_args()

    #------------------------------------------------------------
    @property
    def hostname(self):
        """The hostname of the current storage server."""
        return self._hostname

    #------------------------------------------------------------
    @property
    def api_url(self):
        """The URL of the Dc-Manager REST API."""
        return self._api_url

    #------------------------------------------------------------
    @property
    def api_authtoken(self):
        """The authentication token for the DC-Manager REST API."""
        return self._api_authtoken

    #--------------------------------------------------------------------------
    def as_dict(self):
        """
        Typecasting into a dictionary.

        @return: structure as dict
        @rtype:  dict

        """

        d = super(CheckPbConsistenceStoragePlugin, self).as_dict()

        d['hostname'] = self.hostname
        d['api_url'] = self.api_url
        d['api_authtoken'] = self.api_authtoken

        return d

    #--------------------------------------------------------------------------
    def _add_args(self):
        """
        Adding all necessary arguments to the commandline argument parser.
        """

        self.add_arg(
                '-H', '--hostname', '--host',
                metavar = 'NAME',
                dest = 'hostname',
                help = (("The hostname of the current storage server " +
                        "(Default: %r).") % (self.hostname)),
        )

        self.add_arg(
                '--api-url',
                metavar = 'URL',
                dest = 'api_url',
                help = ("The URL of the Dc-Manager REST API (Default: %r)." % (
                        DEFAULT_API_URL)),
        )

        self.add_arg(
                '--api-authtoken',
                metavar = 'TOKEN',
                dest = 'api_authtoken',
                help = ("The authentication token of the Dc-Manager REST API."),
        )

    #--------------------------------------------------------------------------
    def parse_args(self, args = None):
        """
        Executes self.argparser.parse_args().

        @param args: the argument strings to parse. If not given, they are
                     taken from sys.argv.
        @type args: list of str or None

        """

        super(CheckPbConsistenceStoragePlugin, self).parse_args(args)

    #--------------------------------------------------------------------------
    def parse_args_second(self):
        """
        Evaluates comand line parameters after evaluating the configuration.
        """

        hn = self.argparser.args.hostname
        if hn:
            hn = hn.strip()
        if hn:
            self._hostname = hn.lower()

        if self.argparser.args.api_url:
            self._api_url = self.argparser.args.api_url

        if self.argparser.args.api_authtoken:
            self._api_authtoken = self.argparser.args.api_authtoken

    #--------------------------------------------------------------------------
    def read_config(self):
        """
        Read configuration from an optional configuration file.
        """

        cfg = NagiosPluginConfig()
        try:
            configs = cfg.read()
            log.debug("Read configuration files:\n%s", pp(configs))
        except NoConfigfileFound as e:
            log.debug("Could not read NagiosPluginConfig: %s", e)
            return

        hostname = None
        if cfg.has_section('general') and cfg.has_option('general', 'hostname'):
            hostname = cfg.get('general', 'hostname')
        if hostname:
            hostname = hostname.strip()
        if hostname:
            if self.verbose > 1:
                log.debug("Got a hostname from config: %r", hostname)
            self._hostname = hostname

        if cfg.has_section('dcmanager_rest_api'):

            cfg_api_url = None
            if cfg.has_option('dcmanager_rest_api', 'url'):
                cfg_api_url = cfg.get('dcmanager_rest_api', 'url')
            if cfg_api_url:
                cfg_api_url = cfg_api_url.strip()
            if cfg_api_url:
                if self.verbose > 1:
                    log.debug("Got a REST API URL from config: %r", cfg_api_url)
                self._api_url = cfg_api_url

            cfg_api_authtoken = None
            if cfg.has_option('dcmanager_rest_api', 'authtoken'):
                cfg_api_authtoken = cfg.get('dcmanager_rest_api', 'authtoken')
            if cfg_api_authtoken:
                if self.verbose > 3:
                    log.debug("Got a REST API authentication token from config: %r",
                            cfg_api_authtoken)
                self._api_authtoken = cfg_api_authtoken

    #--------------------------------------------------------------------------
    def __call__(self):
        """
        Method to call the plugin directly.
        """

        self.parse_args()
        self.init_root_logger()

        self.read_config()

        self.parse_args_second()

        state = nagios.state.ok
        out = "Storage volumes on %r seems to be okay." % (
                self.hostname)

        if self.verbose > 2:
            log.debug("Current object:\n%s", pp(self.as_dict()))

        self.exit(state, out)

#==============================================================================

if __name__ == "__main__":

    pass

#==============================================================================

# vim: fileencoding=utf-8 filetype=python ts=4 et sw=4
