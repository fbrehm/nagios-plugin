#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
@author: Frank Brehm
@contact: frank.brehm@profitbricks.com
@copyright: © 2010 - 2013 by Frank Brehm, Berlin
@summary: Module for CheckProcsPlugin class
"""

# Standard modules
import os
import sys
import logging
import textwrap
import pwd
import re
import signal
import subprocess

from numbers import Number

# Third party modules

# Own modules

import nagios
from nagios import BaseNagiosError

from nagios.common import pp, caller_search_path

from nagios.plugin import NagiosPluginError

from nagios.plugin.range import NagiosRange

from nagios.plugins import ExtNagiosPluginError
from nagios.plugins import ExecutionTimeoutError
from nagios.plugins import CommandNotFoundError
from nagios.plugins import ExtNagiosPlugin

#---------------------------------------------
# Some module variables

__version__ = '0.2.0'

log = logging.getLogger(__name__)

PS_CMD = os.sep + os.path.join('bin', 'ps')

valid_metrics = ['PROCS', 'VSZ', 'RSS', 'CPU', 'ELAPSED']

# Valid process state codes, taken from the ps-manpage
process_state = {
        'D':    'uninterruptible sleep',
        'R':    'running or runnable',
        'S':    'interruptible sleep',
        'T':    'stopped or being traced',
        'W':    'paging',
        'X':    'dead',
        'Z':    'defunct ("zombie") process',
        '<':    'high-priority',
        'N':    'low-priority',
        'L':    'has pages locked into memory',
        's':    'is a session leader',
        'l':    'is multi-threaded',
        '+':    'is in the foreground process group',
}

re_integer = re.compile(r'^\s*(\d+)\s*$')

# Contstructing the regex for parsing the output of ps command
match_ps_line = r'^\s*(?P<user>\S+)'
match_ps_line += r'\s+(?P<pid>\d+)'
match_ps_line += r'\s+(?P<ppid>\d+)'
match_ps_line += r'\s+(?P<state>\S+)'
match_ps_line += r'\s+(?P<pcpu>-|\d+(?:\.\d*)?)'
match_ps_line += r'\s+(?P<vsz>\d+)'
match_ps_line += r'\s+(?P<rss>\d+)'
match_ps_line += r'\s+(?P<time>(?:(?:\d+-)?\d+:)?\d+:\d+)'
match_ps_line += r'\s+(?P<comm>\S+)'
match_ps_line += r'\s+(?P<args>.*)'
match_ps_line += r'\s*$'

re_ps_line = re.compile(match_ps_line)

#==============================================================================
class ProcessInfo(object):
    """
    A class capsulating process informations.
    """

    #--------------------------------------------------------------------------
    def __init__(self,
            user, pid, ppid, state, pcpu, vsz, rss, time, comm, args):
        """
        Constructor.

        @param user: effective user name
        @type user: str
        @param pid:i process ID number of the process
        @type pid: int
        @param ppid: parent process ID
        @type ppid: int
        @param state: state of the process as a multicharacter identifier
        @type state: str
        @param pcpu: cpu utilization of the process
        @type pcpu: float
        @param vsz: virtual memory size of the process in KiB
        @type vsz: int
        @param rss: resident set size in kiloBytes
        @type rss: int
        @param time: cumulative CPU time in "[DD-]HH:MM:SS" format.
        @type time: str
        @param comm: command name (only the executable name)
        @type comm: str
        @param args: command with all its arguments
        @type args: str

        """

        self._user = None
        self._uid = None
        self.user = user

    #------------------------------------------------------------
    @property
    def user(self):
        """The effective user name."""
        return self._user

    @user.setter
    def user(self, value):
        match = re_integer.search(value)
        if match:
            self._user = match.group(1)
            self._uid = int(self._user)
        else:
            usr = value.strip()
            uid = -1
            try:
                uid = pwd.getpwnam(usr).pw_uid
            except KeyError, e:
                log.warn("Invalid user name %r.", usr)
                uid = -1
            self._user = usr
            self._uid = uid

    #------------------------------------------------------------
    @property
    def uid(self):
        """The UID of the effective user."""
        return self._uid

    #--------------------------------------------------------------------------
    def as_dict(self):
        """Transforms the elements of the object into a dict."""

        d = {}
        d['__class_name__'] = self.__class__.__name__
        d['user'] = self.user
        d['uid'] = self.uid

        return d

    #--------------------------------------------------------------------------
    def __str__(self):
        """
        Typecasting function for translating object structure into a string.
        """

        return pp(self.as_dict())

    #--------------------------------------------------------------------------
    def __repr__(self):
        """Typecasting into a string for reproduction."""

        out = "<%s(" % (self.__class__.__name__)

        fields = []
        fields.append("user=%r" % (self.user))

        out += ", ".join(fields) + ")>"

        return out


#==============================================================================
class CheckProcsPlugin(ExtNagiosPlugin):
    """
    A special NagiosPlugin class for checking a running process.
    """

    #--------------------------------------------------------------------------
    def __init__(self):
        """
        Constructor of the CheckProcsPlugin class.
        """

        usage = """\
        %(prog)s [-v] [-t <timeout>] [-c <critical_threshold>] [-w <warning_threshold>]
                   [-m <metric>] [-s <statusflags>] [--ps-cmd <command>]
                   [--ppid <parent_pid>] [--rss <value>] [--pcpu <value>] [--vsz <value>]
                   [--user <user_id>] [-a <args>] [-C <command>] [--init]
        %(prog)s --usage
        %(prog)s --help
        """
        usage = textwrap.dedent(usage).strip()

        blurb = """\
        Copyright (c) 2013 Frank Brehm, Berlin.

        Checks all processes and generates WARNING or CRITICAL states if the specified
        metric is outside the required threshold ranges. The metric defaults to number
        of processes.  Search filters can be applied to limit the processes to check.
        """
        blurb = textwrap.dedent(blurb).strip()

        super(CheckProcsPlugin, self).__init__(
                usage = usage, version = __version__, blurb = blurb,
        )

        self._ps_cmd = PS_CMD
        """
        @ivar: the underlaying 'ps' command
        @type: str
        """
        if not os.path.exists(self.ps_cmd) or not os.access(
                self.ps_cmd, os.X_OK):
            self._ps_cmd = self.get_command('ps')

        self._user = None
        """
        @ivar: Only scan for processes with user name or ID indicated.
        @type: str
        """

        self._add_args()

    #------------------------------------------------------------
    @property
    def ps_cmd(self):
        """The absolute path to the OS command 'ps'."""
        return self._ps_cmd

    #------------------------------------------------------------
    @property
    def user(self):
        """Only scan for processes with user name or ID indicated."""
        return self._user

    @user.setter
    def user(self, value):

        uid = None
        user = None
        if isinstance(value, Number):
            uid = int(value)
        else:
            match = re_integer.search(value)
            if match:
                uid = int(match.group(1))
            else:
                user = str(value).strip()

        if uid is not None:
            try:
                user = pwd.getpwuid(uid).pw_name
            except KeyError, e:
                log.warn("Invalid UID %d.", uid)
                return
        else:
            try:
                uid = pwd.getpwnam(user).pw_uid
            except KeyError, e:
                log.warn("Invalid user name %r.", user)
                return

        self._user = user

    #--------------------------------------------------------------------------
    def as_dict(self):
        """
        Typecasting into a dictionary.

        @return: structure as dict
        @rtype:  dict

        """

        d = super(CheckProcsPlugin, self).as_dict()

        d['ps_cmd'] = self.ps_cmd
        d['user'] = self.user

        return d

    #--------------------------------------------------------------------------
    def _add_args(self):
        """
        Adding all necessary arguments zo the commandline argument parser.
        """

        self.add_arg(
                '-w', '--warning',
                type = NagiosRange,
                metavar = 'RANGE',
                dest = 'warning',
                required = True,
                help = 'Generate warning state if metric is outside this range',
        )

        self.add_arg(
                '-c', '--critical',
                type = NagiosRange,
                metavar = 'RANGE',
                dest = 'critical',
                required = True,
                help = 'Generate critical state if metric is outside this range',
        )

        self.add_arg(
                '-m', '--metric',
                choices = valid_metrics,
                dest = 'metric',
                required = True,
                default = 'PROCS',
                help = "Check thresholds against metric (default: %(default)s).",
        )

        default_ps = PS_CMD
        if self.ps_cmd:
            default_ps = self.ps_cmd
        self.add_arg(
                '--ps-cmd',
                dest = 'ps_cmd',
                required = True,
                default = default_ps,
                help = "The ps-command (default: %(default)r).",
        )

        state_help = """\
        Only scan for processes that have, in the output of 'ps', one or
        more of the status flags you specify (for example R, Z, S, RS,
        RSZDT, plus others based on the output of your 'ps' command).
        """
        state_help = textwrap.dedent(state_help).strip()

        self.add_arg(
                '-s', '--state',
                metavar = 'STATE',
                dest = 'state',
                help = state_help
        )

        self.add_arg(
                '-p', '--ppid',
                type = int,
                metavar = 'PID',
                dest = 'ppid',
                help = 'Only scan for children of the parent process ID indicated.',
        )

        self.add_arg(
                '-z', '--vsz',
                type = int,
                dest = 'vsz',
                help = 'Only scan for processes with virtual size higher than indicated.',
        )

        self.add_arg(
                '-r', '--rss',
                type = int,
                dest = 'rss',
                help = 'Only scan for processes with rss higher than indicated.',
        )

        self.add_arg(
                '-P', '--pcpu',
                type = int,
                dest = 'pcpu',
                help = 'Only scan for processes with pcpu higher than indicated.',
        )

        self.add_arg(
                '-u', '--user',
                dest = 'user',
                help = 'Only scan for processes with user name or UID indicated.',
        )

        self.add_arg(
                '-a', '--args',
                metavar = 'STRING',
                dest = 'args',
                help = 'Only scan for processes with args that contain STRING.',
        )

        self.add_arg(
                '-C', '--command',
                metavar = 'STRING',
                dest = 'command',
                help = 'Only scan for exact matches of STRING (without path).',
        )

        self.add_arg(
                '-i', '--init',
                action = 'store_true',
                dest = 'init',
                help = 'Only scan for processes, they are direct childs of init.',
        )

    #--------------------------------------------------------------------------
    def __call__(self):
        """
        Method to call the plugin directly.
        """

        self.parse_args()
        self.init_root_logger()

        ps_cmd = PS_CMD
        if self.argparser.args.ps_cmd:
            self._ps_cmd = self.get_command(self.argparser.args.ps_cmd)
            ps_cmd = self.argparser.args.ps_cmd
        if not self.ps_cmd:
            msg = "Command %r not found." % (ps_cmd)
            self.die(msg)

        if self.argparser.args.user:
            self.user = self.argparser.args.user
            if self.user is None:
                msg = "Invalid user name or UID %r given." % (
                        self.argparser.args.user)
                self.die(msg)

        self.set_thresholds(
                warning = self.argparser.args.warning,
                critical = self.argparser.args.critical,
        )

        if self.verbose > 2:
            log.debug("Current object:\n%s", pp(self.as_dict()))

        self.collect_processes()

        self.exit(nagios.state.ok, "The sun is shining happily :-D")

    #--------------------------------------------------------------------------
    def collect_processes(self):
        """The main routine of this plugin."""

        fields = ('user', 'pid', 'ppid', 'stat', 'pcpu', 'vsz', 'rss', 'time',
                'comm', 'args')

        cmd = [self.ps_cmd, '-e', '-o', ','.join(fields)]
        cmd_str = ' '.join(cmd)
        timeout = abs(int(self.argparser.args.timeout))

        cmd_obj = None
        stdoutdata = ''
        stderrdata = ''

        def exec_alarm_caller(signum, sigframe):
            raise ExecutionTimeoutError(timeout, cmd_str)

        if self.verbose > 1:
            log.debug("Executing %r ...", cmd_str)

        signal.signal(signal.SIGALRM, exec_alarm_caller)
        signal.alarm(timeout)

        try:
            cmd_obj = subprocess.Popen(
                    cmd,
                    stderr = subprocess.PIPE,
                    stdout = subprocess.PIPE,
                    bufsize = 0,
                    close_fds = False,
            )
            (stdoutdata, stderrdata) = cmd_obj.communicate()
        except ExecutionTimeoutError, e:
            self.die(str(e))

        signal.alarm(0)

        if self.verbose > 2:
            log.debug("Got from STDOUT:\n%s", stdoutdata)
            log.debug("Got from STDERR:\n%s", stderrdata)

        lines = stdoutdata.splitlines()

        for line in lines[1:]:

            pinfo = self._parse_process_line(line)

    #--------------------------------------------------------------------------
    def _parse_process_line(self, line):
        """Parsing a line how given back from the ps command."""

        match = re_ps_line.search(line)
        if not match:
            log.warn("Could not parse output line of ps: %r", line)
            return None

        kwords = match.groupdict()

        pinfo = ProcessInfo(**kwords)
        if self.verbose > 2:
            log.debug("Got process info: %s", pinfo)

        return pinfo

#==============================================================================

if __name__ == "__main__":

    pass

#==============================================================================

# vim: fileencoding=utf-8 filetype=python ts=4
