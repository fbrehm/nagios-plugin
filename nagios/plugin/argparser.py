#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
@author: Frank Brehm
@contact: frank.brehm@profitbricks.com
@copyright: © 2010 - 2015 by Frank Brehm, Berlin
@summary: Module for a NagiosPluginArgparse class, a class providing a
          standardised argument processing for Nagios plugins
"""

# Standard modules
import os
import sys
import logging
import pprint
import textwrap
import re

import argparse

from argparse import Namespace

# Third party modules

# Own modules

import nagios
from nagios import BaseNagiosError

from nagios.plugin.functions import nagios_die, nagios_exit

from nagios.plugin.config import NoConfigfileFound
from nagios.plugin.config import NagiosPluginConfig

# --------------------------------------------
# Some module variables

__version__ = '0.5.4'

log = logging.getLogger(__name__)

lgpl3_licence_text = """
This nagios plugin is free software, and comes with ABSOLUTELY
NO WARRANTY. It may be used, redistributed and/or modified under
the terms of the GNU Lesser General Public License (LGPL), Version 3 (see
http://www.gnu.org/licenses/lgpl).
""".strip()

default_timeout = 15
default_verbose = 0


# =============================================================================
class NagiosPluginArgparseError(BaseNagiosError):
    """Special exceptions, which are raised in this module."""

    pass


# =============================================================================
class NagiosPluginArgparseAction(argparse.Action):
    """Base class for self defined argparse actions."""

    # -------------------------------------------------------------------------
    def np_exit(self, parser, messages, state=nagios.state.ok):
        """
        Method to exit as a result of the actions.

        @param messages: messages to emit to stderr on exit.
        @type messages: str or list of str
        @param state: the Nagios state value on exit of the application
        @type state: int

        """

        msgs = messages
        if isinstance(messages, str):
            msgs = [msgs]
        msg = "\n".join(msgs)
        # log.debug(
        #    "Exiting with return value %d and a message %r.", state, msg)
        parser.exit(state, msg)


# =============================================================================
class NpUsageAction(NagiosPluginArgparseAction):
    """Action class to react on the --usage parameter"""

    # -------------------------------------------------------------------------
    def __call__(self, parser, namespace, values, option_string=None):

        # log.debug('Namespace: %r,  Values: %r, Option string: %r' % (
        #        namespace, values, option_string))

        self.np_exit(parser, parser.format_usage())


# =============================================================================
class NpHelpAction(NagiosPluginArgparseAction):
    """Action class to react on the --help parameter"""

    # -------------------------------------------------------------------------
    def __call__(self, parser, namespace, values, option_string=None):

        # log.debug('Namespace: %r,  Values: %r, Option string: %r' % (
        #        namespace, values, option_string))

        self.np_exit(parser, parser.format_help())


# =============================================================================
class NpArgParser(argparse.ArgumentParser):
    """
    Wrapper class to argparse.ArgumentParser to modify the error() and
    the exit() method.
    """

    # -------------------------------------------------------------------------
    def error(self, message):
        """
        Prints a usage message incorporating the message to stderr and exits.

        @param message: the message to emit on exit.
        @type message: str

        """

        try:
            super(NpArgParser, self).error(message)
        except SystemExit:
            nagios_die('', no_status_line=True)

    # -------------------------------------------------------------------------
    def exit(self, status=0, message=None):
        """
        Prints a usage message incorporating the message to stderr
        and exits with the given return value.

        @param status: the return value, which should given back
                       to the operating system
        @type status: int
        @param message: the message to emit on exit.
        @type message: str

        """

        try:
            super(NpArgParser, self).exit(status, message)
        except SystemExit:
            nagios_exit(status, '', no_status_line=True)


# =============================================================================
class NagiosPluginArgparse(object):
    """
    A class providing a standardised argument processing for Nagios plugins.
    """

    pass

    # -------------------------------------------------------------------------
    def __init__(
        self, usage, version=nagios.__version__, url=None,
            blurb=None, licence=lgpl3_licence_text, extra=None,
            plugin=None, timeout=default_timeout):
        """
        Constructor of the NagiosPluginArgparse class.

        Instantiate object::

            from nagios.plugin.argparser import NagiosPluginArgparse

            # Minimum arguments:
            na = NagiosPluginArgparse(
                usage = 'Usage: %(prog)s --hello',
                version = '0.0.1',
            )

        @param usage: Short usage message used with --usage/-? and with missing
                      required arguments, and included in the longer --help
                      output. Can include %(prog)s placeholder which will be
                      replaced with the plugin name, e.g.::

                          usage = 'Usage: %(prog)s -H <hostname> -p <ports> [-v]'

        @type usage: str
        @param version: Plugin version number, included in the --version/-V
                        output, and in the longer --help output. e.g.::

                            $ ./check_tcp_range --version
                            check_tcp_range 0.2 [http://www.openfusion.com.au/labs/nagios/]
        @type version: str
        @param url: URL for info about this plugin, included in the
                    --version/-V output, and in the longer --help output.
                    Maybe omitted.
        @type url: str or None
        @param blurb: Short plugin description, included in the longer
                      --help output. Maybe omitted.
        @type blurb: str or None
        @param licence: License text, included in the longer --help output. By
                        default, this is set to the standard nagios plugins
                        LGPLv3 licence text.
        @type licence: str or None
        @param extra: Extra text to be appended at the end of the longer --help
                      output, maybe omitted.
        @type extra: str or None
        @param plugin: Plugin name. This defaults to the basename of your plugin.
        @type plugin: str or None
        @param timeout: Timeout period in seconds, overriding the standard
                        timeout default (15 seconds).
        @type timeout: int

        """

        self._usage = str(usage).strip()
        """
        @ivar: Short usage message
        @type: str
        """

        self._version = str(version).strip()
        """
        @ivar: Plugin version number.
        @type: str
        """

        self._url = url
        """
        @ivar: URL for info about this plugin
        @type: str or None
        """
        if self._url:
            self._url = self._url.strip()

        self._blurb = blurb
        """
        @ivar: Short plugin description
        @type: str or None
        """
        if self._blurb:
            self._blurb = self._blurb.strip()

        self._licence = str(licence).strip()
        """
        @ivar: License text.
        @type: str
        """

        self._extra = extra
        """
        @ivar: Extra text to be appended at the end of the --help output.
        @type: str or None
        """
        if self._extra:
            self._extra = self._extra.strip()

        default_pluginname = sys.argv[0]
        if 'NAGIOS_PLUGIN' in os.environ:
            default_pluginname = os.environ['NAGIOS_PLUGIN']
        default_pluginname = os.path.basename(default_pluginname)
        self._plugin = default_pluginname
        """
        @ivar: Plugin name. This defaults to the basename of your plugin.
        @type: str
        """
        if plugin:
            p = str(plugin).strip()
            if p:
                self._plugin = p

        self._timeout = default_timeout
        """
        @ivar: Timeout period in seconds.
        @type: int
        """
        if timeout:
            to = int(timeout)
            if to > 0:
                self._timeout = to
            else:
                raise ValueError(
                    "Wrong timout %r given, must be > 0." % (timeout))

        self.args = Namespace()
        """
        @ivar: the arguments after parsing the command line
        @type: Namespace
        """

        self.arguments = []
        """
        @ivar: a list of all appended arguments
        @type: list of Argument
        """

        self._used_arg_dests = [
            'usage', 'help', 'version', 'extra_opts', 'timeout', 'verbose'
        ]
        """
        @ivar: all currently used argument destinations.
        @type: list of str
        """

        self._has_parsed = False
        """
        @ivar: flag indicating, that the method parse_args() was even called.
        @type: bool
        """

    # -----------------------------------------------------------
    @property
    def usage(self):
        """Short usage message."""
        return self._usage

    # -----------------------------------------------------------
    @property
    def version(self):
        """Plugin version number."""
        return self._version

    # -----------------------------------------------------------
    @property
    def url(self):
        """URL for info about this plugin."""
        return self._url

    # -----------------------------------------------------------
    @property
    def blurb(self):
        """Short plugin description."""
        return self._blurb

    # -----------------------------------------------------------
    @property
    def licence(self):
        """The licence text."""
        return self._licence

    # -----------------------------------------------------------
    @property
    def extra(self):
        """Extra text to be appended at the end of the --help output."""
        return self._extra

    # -----------------------------------------------------------
    @property
    def plugin(self):
        """The name of the plugin."""
        return self._plugin

    # -----------------------------------------------------------
    @property
    def timeout(self):
        """The timeout period in seconds."""
        return self._timeout

    # -----------------------------------------------------------
    @property
    def has_parsed(self):
        """A flag indicating, that the method parse_args() was even called."""
        return self._has_parsed

    # -------------------------------------------------------------------------
    def _exit(self, status, messages):

        msgs = messages
        if isinstance(messages, str):
            msgs = [msgs]
        msg = "\n".join(msgs)
        nagios_exit(status, msg, no_status_line=True)

    # -------------------------------------------------------------------------
    def _die(self, messages=None):

        if not messages:
            messages = []
        self._exit(nagios.state.unknown, messages)

    # -------------------------------------------------------------------------
    def _finish(self, messages=None):

        if not messages:
            messages = []
        self._exit(nagios.state.ok, messages)

    # -------------------------------------------------------------------------
    def as_dict(self):
        """
        Typecasting into a dictionary.

        @return: structure as dict
        @rtype:  dict

        """

        d = {
            '__class__': self.__class__.__name__,
            'usage': self.usage,
            'version': self.version,
            'url': self.url,
            'blurb': self.blurb,
            'licence': self.licence,
            'extra': self.extra,
            'plugin': self.plugin,
            'timeout': self.timeout,
            'args': self.args,
            'arguments': self.arguments,
            'has_parsed': self.has_parsed,
            '_used_arg_dests': self._used_arg_dests,
        }

        return d

    # -------------------------------------------------------------------------
    def __str__(self):
        """
        Typecasting function for translating object structure into a string.

        @return: structure as string
        @rtype:  str

        """

        pretty_printer = pprint.PrettyPrinter(indent=4)
        return pretty_printer.pformat(self.as_dict())

    # -------------------------------------------------------------------------
    def _get_version_str(self):

        out = "%s %s" % (self.plugin, self.version)
        if self.url:
            out += " [%s]" % (self.url)
        return out

    # -------------------------------------------------------------------------
    def __repr__(self):
        """Typecasting into a string for reproduction."""

        out = "<%s(" % (self.__class__.__name__)

        fields = []
        fields.append("usage=%r" % (self.usage))
        fields.append("version=%r" % (self.version))
        fields.append("url=%r" % (self.url))
        fields.append("blurb=%r" % (self.blurb))
        fields.append("licence=%r" % (self.licence))
        fields.append("extra=%r" % (self.extra))
        fields.append("plugin=%r" % (self.plugin))
        fields.append("timeout=%r" % (self.timeout))
        fields.append("args=%r" % (self.args))
        fields.append("arguments=%r" % (self.arguments))
        fields.append("has_parsed=%r" % (self.has_parsed))
        fields.append("_used_arg_dests=%r" % (self._used_arg_dests))

        out += ", ".join(fields) + ")>"
        return out

    # -------------------------------------------------------------------------
    def parse_args(self, args=None):
        """
        Provides the main parsing functionality. Convert argument strings to
        objects and assign them as attributes of self.args.

        @param args: the argument strings to parse.
        @type args: list of str or None

        """

        width = 0
        try:
            width = int(os.environ['COLUMNS'])
        except (KeyError, ValueError):
            width = 80
        width -= 2

        wrapper = textwrap.TextWrapper(
            width=width,
            replace_whitespace=False,
            fix_sentence_endings=False,
            break_long_words=False,
        )
        re_ws = re.compile(r'\s+')

        desc = wrapper.fill(re_ws.sub(' ', self.blurb))

        epilog = self._get_version_str() + "\n\n"
        if self.extra:
            epilog += self.extra.strip() + "\n\n"
        if self.licence:
            epilog += wrapper.fill(re_ws.sub(' ', self.licence))

        parser = NpArgParser(
            prog=self.plugin,
            usage=self.usage,
            description=desc,
            epilog=epilog,
            add_help=False,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

        self._add_plugin_args(parser)
        self._add_std_args(parser)

        # log.debug("NpArgParser object: %r", parser)

        self.args = parser.parse_args(args)

        # log.debug("Got first commandline arguments: %r", self.args)

        if self.args.extra_opts:
            new_args = self._process_extra_opts(args, self.args.extra_opts)
            # log.debug("Got new commandline parameters %r.", new_args)
            if new_args != args:
                # log.debug("Reevaluate commandline options ...")
                self.args = parser.parse_args(new_args)
                # log.debug("Got next commandline arguments: %r", self.args)

        for arg in self.arguments:

            dest = arg['names'][0]
            if 'dest' in arg['kwargs']:
                dest = arg['kwargs']['dest']
            if 'required' in arg['kwargs']:
                required = arg['kwargs']['required']
                if required:
                    # val = getattr(self.args, dest, None)
                    # log.debug(
                    #     "Checking for required argument %r, current value is %r.", dest, val)
                    if not hasattr(self.args, dest) or getattr(self.args, dest, None) is None:
                        arg_str = '/'.join(arg['names'])
                        msg = "Argument %r is a required argument." % (arg_str)
                        msg += "\n\n" + parser.format_usage()
                        self._die(msg)

        self._has_parsed = True

    # -------------------------------------------------------------------------
    def _process_extra_opts(self, args, extra_opts):
        """
        Process and load extra-opts sections.

        """

        if not extra_opts:
            return args

        re_extopt = re.compile(r'^(\w*)@(.*?)\s*$')

        s_args = []
        for ext_opt in extra_opts:

            if not ext_opt:
                ext_opt = self.plugin

            section = ext_opt
            cfg_file = None

            match = re_extopt.search(ext_opt)
            if match:
                section = match.group(1)
                cfg_file = match.group(2)

            ini_opts = self._load_config_section(section, cfg_file)
            # log.debug("Read extra opts from %r: %r", cfg_file, ini_opts)
            n_args = self._cmdline(ini_opts)
            # log.debug("Resulting commandline options: %r", n_args)

            s_args += n_args

        nargs = args
        if args is None:
            nargs = []
        elif isinstance(args, str):
            nargs = [args]
        else:
            nargs = args[:]

        return s_args + nargs

    # -------------------------------------------------------------------------
    def _cmdline(self, ini_opts):
        """
        Helper method to format key/values in ini_opts in a quasi-commandline format
        """

        args = []
        re_underscore = re.compile(r'^_')
        re_any_us = re.compile(r'_')
        re_valid_key = re.compile(
            r'^[a-z0-9](?:[a-z0-9\-_]*[a-z0-9_])?$', re.IGNORECASE)

        for key in ini_opts:

            lkey = re_any_us.sub('-', key.lower())
            if re_underscore.search(key):
                continue

            if lkey in (
                    'usage', '?', 'help', 'h', 'version', 'v', 'extra-opts',
                    'timeout', 't', 'verbose'):
                continue

            val = ini_opts[key]
            if val is None:
                continue

            if not re_valid_key.search(key):
                # log.warn(
                #     "Invalid key %r for usage as commandline parameter found.", key)
                continue

            if len(key) > 1:
                args.append("--%s" % (key))
            else:
                args.append("-%s" % (key))

            args.append(val)

        return args

    # -------------------------------------------------------------------------
    def _load_config_section(self, section, cfg_file=None):
        """Loads the given section from the given ini-file or from the first
            found default ini-file."""

        if not section:
            section = self.plugin

        # log.debug(
        #     "Trying to load extra options from section %r of file %r.", section, cfg_file)

        cfg = NagiosPluginConfig()
        configs = []
        try:
            configs = cfg.read(cfg_file)
        except NoConfigfileFound:
            return {}

        configs_str = str(configs)
        if len(configs):
            configs_str = ', '.join(["'" + x + "'" for x in configs])
        else:
            configs_str = '<None>'

        if section not in cfg.sections():
            if False:
                log.debug(
                    "Section %r not found in ini-files %s.", section, configs_str)
            return {}

        ini_opts = {}
        for option in cfg.options(section):

            val = cfg.get(section, option)
            ini_opts[option] = val

        return ini_opts

    # -------------------------------------------------------------------------
    def add_arg(self, *names, **kwargs):
        """
        Adds a new plugin argument to the parser.

        @param names: Either a name or a list of option strings,
                      e.g. foo or -f, --foo.
        @type names: str or list of str
        @param kwargs: all keyword arguments, which should be used to define
                       the argument, they are used 1:1 to the method
                       ArgumentParser.add_argument(), see
                       http://docs.python.org/2/library/argparse.html#the-add-argument-method
                       which keyword arguments can be used.
        @type kwargs: dict

        """

        if not names:
            msg = "No names or tags defined for this argument."
            raise NagiosPluginArgparseError(msg)

        valid_kwargs = (
            'action', 'nargs', 'const', 'default', 'type', 'choices', 'required',
            'help', 'metavar', 'dest',
        )

        if 'dest' not in kwargs:
            msg = (
                "The keyword 'dest' is a required argument in calling add_arg().")
            raise NagiosPluginArgparseError(msg)

        dest = kwargs['dest']
        if dest in self._used_arg_dests:
            msg = ("The destination %r is allready used.") % (dest)
            raise NagiosPluginArgparseError(msg)
        self._used_arg_dests.append(dest)

        if dest in names:
            del kwargs['dest']

        for kword in kwargs:
            if kword not in valid_kwargs:
                msg = (
                    "Invalid keyword argument %r on calling add_arg() used.") % (kword)
                raise NagiosPluginArgparseError(msg)

        arg = {}
        arg['names'] = names
        arg['kwargs'] = kwargs

        self.arguments.append(arg)

    # -------------------------------------------------------------------------
    def _add_plugin_args(self, parser):

        for arg in self.arguments:

            names = arg['names']
            kwargs = arg['kwargs']

            o_req = None
            if 'required' in kwargs:
                o_req = kwargs['required']
                kwargs['required'] = False

            parser.add_argument(*names, **kwargs)

            if o_req is not None:
                kwargs['required'] = o_req

    # -------------------------------------------------------------------------
    def _add_std_args(self, parser):

        std_group = parser.add_argument_group('General options')

        std_group.add_argument(
            '--usage', '-?',
            action=NpUsageAction,
            nargs='?',
            dest='usage',
            help='Print usage information',
        )

        std_group.add_argument(
            '--help', '-h',
            action=NpHelpAction,
            nargs='?',
            dest='help',
            help='Print detailed help screen',
        )

        std_group.add_argument(
            '--version', '-V',
            action='version',
            version=self._get_version_str(),
            dest='version',
            help='Print version information',
        )

        std_group.add_argument(
            '--extra-opts',
            action='append',
            dest='extra_opts',
            nargs='?',
            metavar='[section][@file]',
            help=(
                'Read options from an ini file. See http://nagiosplugins.org/extra-opts '
                'for usage and examples.')
        )

        std_group.add_argument(
            '--timeout', '-t',
            type=int,
            dest='timeout',
            default=self.timeout,
            help='Seconds before plugin times out (default: %(default)s)',
        )

        std_group.add_argument(
            '--verbose', '-v',
            action='count',
            dest='verbose',
            default=default_verbose,
            help=('Show details for command-line debugging (can repeat up to 3 times)'),
        )

# =============================================================================

if __name__ == "__main__":

    from nagios.plugin.functions import get_shortname
    from nagios.color_syslog import ColoredFormatter

    verbose = 0
    if '-v' in sys.argv:
        verbose = 1
        verbose = sys.argv.count('-v')

    shortname = get_shortname()

    root_log = logging.getLogger()
    root_log.setLevel(logging.INFO)
    if verbose:
        root_log.setLevel(logging.DEBUG)

    format_str = shortname + ': '
    if verbose:
        if verbose > 1:
            format_str += '%(name)s(%(lineno)d) %(funcName)s() '
        else:
            format_str += '%(name)s '
    format_str += '%(levelname)s - %(message)s'
    formatter = None
    if verbose:
        formatter = ColoredFormatter(format_str)
    else:
        formatter = logging.Formatter(format_str)

    # create log handler for console output
    lh_console = logging.StreamHandler(sys.stderr)
    if verbose > 1:
        lh_console.setLevel(logging.DEBUG)
    else:
        lh_console.setLevel(logging.INFO)
    lh_console.setFormatter(formatter)

    root_log.addHandler(lh_console)

    na = NagiosPluginArgparse(
        usage='%(prog)s --hello',
        url='http://www.profitbricks.com',
        blurb='Senseless sample Nagios plugin.',
        extra='Bla blub',
    )

    na.add_arg(
        '-H', '--hello', action='store_true',
        dest='hello', help="Prints out 'Hello world!'")

    log.debug("NagiosPluginArgparse object: %r", na)
    log.debug("NagiosPluginArgparse object: %s", str(na))

    na.parse_args()
    if na.args.hello:
        print("Hello world!")
    sys.exit(0)

# =============================================================================

# vim: fileencoding=utf-8 filetype=python ts=4 et
