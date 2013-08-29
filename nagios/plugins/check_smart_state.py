#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
@author: Frank Brehm
@contact: frank.brehm@profitbricks.com
@copyright: © 2010 - 2013 by Frank Brehm, Berlin
@summary: Module for CheckSmartStatePlugin class
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
import locale
import stat

from numbers import Number
from subprocess import CalledProcessError

# Third party modules

# Own modules

import nagios
from nagios import BaseNagiosError

from nagios.common import pp, caller_search_path

from nagios.plugin import NagiosPluginError

from nagios.plugin.range import NagiosRange

from nagios.plugin.threshold import NagiosThreshold

from nagios.plugin.argparser import default_timeout

from nagios.plugins import ExtNagiosPluginError
from nagios.plugins import ExecutionTimeoutError
from nagios.plugins import CommandNotFoundError
from nagios.plugins import ExtNagiosPlugin

#---------------------------------------------
# Some module variables

__version__ = '0.2.0'

log = logging.getLogger(__name__)

DEFAULT_MEGARAID_PATH = '/opt/MegaRAID/MegaCli'
DEFAULT_WARN_SECTORS = 4
DEFAULT_CRIT_SECTORS = 10

#==============================================================================
class MegaCliExecTimeoutError(ExtNagiosPluginError, IOError):
    """
    Special error class indicating a timout error on
    executing MegaCli.
    """

    #--------------------------------------------------------------------------
    def __init__(self, timeout, cmdline):
        """
        Constructor.

        @param timeout: the timout in seconds leading to the error
        @type timeout: float
        @param filename: the commandline leading to the error
        @type filename: str

        """

        t_o = None
        try:
            t_o = float(timeout)
        except ValueError:
            pass
        self.timeout = t_o

        self.cmdline = cmdline

    #--------------------------------------------------------------------------
    def __str__(self):

        msg = "Error executing: %s (timeout after %0.1f secs)" % (
                self.cmdline, self.timeout)

        return msg

#==============================================================================
class CheckSmartStatePlugin(ExtNagiosPlugin):
    """
    A special NagiosPlugin class for checking the SMART state of a physical
    hard drive.
    """

    #--------------------------------------------------------------------------
    def __init__(self):
        """
        Constructor of the CheckSmartStatePlugin class.
        """

        usage = """\
        %(prog)s [-v] [-m] -c <critical grown sectors> -w <warn grown sectors> <HD device>
        """
        usage = textwrap.dedent(usage).strip()
        usage += '\n       %(prog)s --usage'
        usage += '\n       %(prog)s --help'

        blurb = "Copyright (c) 2013 Frank Brehm, Berlin.\n\n"
        blurb += "Checks the SMART state of a physical hard drive."

        super(CheckSmartStatePlugin, self).__init__(
                usage = usage, blurb = blurb,
                append_searchpath = [DEFAULT_MEGARAID_PATH],
        )

        self._smartctl_cmd = self.get_command('smartctl')
        """
        @ivar: the underlaying 'smartctl' command
        @type: str
        """
        if not self.smartctl_cmd:
            msg = "Command %r not found." % ('smartctl')
            self.die(msg)

        self._megacli_cmd = None
        """
        @ivar: the 'MegaCLI' command for detecting Device Id from an enclosure:slot data
        @type: str
        """

        self._megaraid = False
        """
        @ivar: Is the given device a PhysicalDrive on a MegaRaid adapter
        @type: bool
        """

        self._timeout = default_timeout
        """
        @ivar: the timeout on execution of commands in seconds
        @type: int
        """

        self._warn_sectors = NagiosRange(end = DEFAULT_WARN_SECTORS)
        """
        @ivar: number of grown defect sectors leading to a warning
        @type: NagiosRange
        """

        self._crit_sectors = NagiosRange(end = DEFAULT_CRIT_SECTORS)
        """
        @ivar: number of grown defect sectors leading to a critical message
        @type: NagiosRange
        """

        self._device = None
        """
        @ivar: the device to check
        @type: str
        """

        self._device_id = None
        """
        @ivar: the MegaRaid Device Id of the PD on the MegaRAID controller.
        @type: int
        """

        self._megaraid_slot = None
        """
        @ivar: the MegaRaid enclusure-Id/slot-Id pair to check
        @type: tuple of two int
        """

        self._adapter_nr = 0
        """
        @ivar: the number of the MegaRaid adapter (e.g. 0)
        @type: str
        """

        self._init_megacli_cmd()

        self._add_args()

    #------------------------------------------------------------
    @property
    def smartctl_cmd(self):
        """The absolute path to the OS command 'smartctl'."""
        return self._smartctl_cmd

    #------------------------------------------------------------
    @property
    def megacli_cmd(self):
        """The absolute path to the OS command 'MegaCli'."""
        return self._megacli_cmd

    #------------------------------------------------------------
    @property
    def megaraid(self):
        """Is the given device a PhysicalDrive on a MegaRaid adapter."""
        return self._megaraid

    @megaraid.setter
    def megaraid(self, value):
        self._megaraid = bool(value)

    #------------------------------------------------------------
    @property
    def warn_sectors(self):
        """The number of grown defect sectors leading to a warning."""
        return self._warn_sectors

    #------------------------------------------------------------
    @property
    def crit_sectors(self):
        """The number of grown defect sectors leading to a critical message."""
        return self._crit_sectors

    #------------------------------------------------------------
    @property
    def device(self):
        """The device to check."""
        return self._device

    #------------------------------------------------------------
    @property
    def device_id(self):
        """The MegaRaid Device Id of the PD on the MegaRAID controller."""
        return self._device_id

    #------------------------------------------------------------
    @property
    def megaraid_slot(self):
        """The MegaRaid enclusure-Id/slot-Id pair to check."""
        return self._megaraid_slot

    #------------------------------------------------------------
    @property
    def adapter_nr(self):
        """The number of the MegaRaid adapter (e.g. 0)."""
        return self._adapter_nr

    #------------------------------------------------------------
    @property
    def timeout(self):
        """The timeout on execution of commands in seconds."""
        return self._timeout

    #--------------------------------------------------------------------------
    def as_dict(self):
        """
        Typecasting into a dictionary.

        @return: structure as dict
        @rtype:  dict

        """

        d = super(CheckSmartStatePlugin, self).as_dict()

        d['adapter_nr'] = self.adapter_nr
        d['smartctl_cmd'] = self.smartctl_cmd
        d['megacli_cmd'] = self.megacli_cmd
        d['megaraid'] = self.megaraid
        d['warn_sectors'] = self.warn_sectors
        d['crit_sectors'] = self.crit_sectors
        d['device'] = self.device
        d['device_id'] = self.device_id
        d['megaraid_slot'] = self.megaraid_slot
        d['timeout'] = self.timeout

        return d

    #--------------------------------------------------------------------------
    def _init_megacli_cmd(self):
        """
        Initializes self.megacli_cmd.
        """

        self._megacli_cmd = self._get_megacli_cmd()

    #--------------------------------------------------------------------------
    def _get_megacli_cmd(self, given_path = None):
        """
        Finding the executable 'MegaCli64', 'MegaCli' or 'megacli' under the
        search path or the given path.

        @param given_path: a possibly given path to MegaCli
        @type given_path: str

        @return: the found path to the megacli executable.
        @rtype: str or None

        """

        exe_names = ('MegaCli', 'megacli')
        arch = os.uname()[4]
        if arch == 'x86_64':
            exe_names = ('MegaCli64', 'MegaCli', 'megacli')

        if given_path:
            # Normalize the given path, if it exists.
            if os.path.isabs(given_path):
                if not is_exe(given_path):
                    return None
                return os.path.realpath(given_path)
            exe_names = (given_path,)

        for exe_name in exe_names:
            log.debug("Searching for %r ...", exe_name)
            exe_file = self.get_command(exe_name, quiet = True)
            if exe_file:
                return exe_file

        return None

    #--------------------------------------------------------------------------
    def _add_args(self):
        """
        Adding all necessary arguments to the commandline argument parser.
        """

        arg_help = ('The number of grown defect sectors leading to a ' +
                    'warning (Default: %d).') % (DEFAULT_WARN_SECTORS)
        self.add_arg(
                '-w', '--warning',
                metavar = 'SECTORS',
                dest = 'warning',
                required = True,
                type = int,
                default = DEFAULT_WARN_SECTORS,
                help = arg_help,
        )

        arg_help = ('The number of grown defect sectors leading to a ' +
                    'critical message (Default: %d).') % (DEFAULT_CRIT_SECTORS)
        self.add_arg(
                '-c', '--critical',
                metavar = 'SECTORS',
                dest = 'critical',
                required = True,
                type = int,
                default = DEFAULT_CRIT_SECTORS,
                help = arg_help,
        )

        self.add_arg(
                '-m', '--megaraid',
                metavar = 'DEVICE_ID',
                dest = 'megaraid',
                help = ('If given, check the device DEVICE_ID on a MegaRAID ' +
                        'controller. The DEVICE_ID might be given as a single ' +
                        'Device Id (integer) or as an <enclosure-id:slot-id> ' +
                        'pair of the MegaRaid adapter.'),
        )

        self.add_arg(
                'device',
                dest = 'device',
                nargs = '?',
                help = ("The device to check (given as 'sdX' or '/dev/sdX', " +
                        "must exists)."),
        )

    #--------------------------------------------------------------------------
    def parse_args(self, args = None):
        """
        Executes self.argparser.parse_args().

        @param args: the argument strings to parse. If not given, they are
                     taken from sys.argv.
        @type args: list of str or None

        """

        super(CheckSmartStatePlugin, self).parse_args(args)

        self.init_root_logger()

        self._warn_sectors = NagiosRange(end = self.argparser.args.warning)
        self._crit_sectors = NagiosRange(end = self.argparser.args.critical)

        self.set_thresholds(
                warning = self.warn_sectors,
                critical = self.crit_sectors,
        )

        if self.argparser.args.timeout:
            self._timeout = self.argparser.args.timeout

        if not self.argparser.args.device:
            self.die("No device to check given.")

        dev = os.path.basename(self.argparser.args.device)
        dev_dev = os.sep + os.path.join('dev', dev)
        sys_dev = os.sep + os.path.join('sys', 'block', dev)

        if not os.path.isdir(sys_dev):
            self.die("Device %r is not a block device." % (dev))

        if not os.path.exists(dev_dev):
            self.die("Device %r doesn't exists." % (dev_dev))

        dev_stat = os.stat(dev_dev)
        dev_mode = dev_stat.st_mode
        if not stat.S_ISBLK(dev_mode):
            self.die("%r is not a block device." % (dev_dev))

        self._device = dev_dev

        if self.argparser.args.megaraid:
            self._init_megacli_dev(self.argparser.args.megaraid)


    #--------------------------------------------------------------------------
    def _init_megacli_dev(self, dev):
        """
        Initializes self.device_id and self.megaraid_slot in case of checking
        smartctl on a device on a MagaRaid adpter.
        """

        self._device_id = None
        self._megaraid_slot = None

        re_device_id = re.compile(r'^\s*(\d+)\s*$')
        re_slot = re.compile(r'^\s*(?:\[(\d+:\d+)\]|(\d+:\d+))\s*$')
        re_enc_slot = re.compile(r'^(\d+):(\d+)$')

        # A single Device Id was given
        match = re_device_id.search(dev)
        if match:
            self._device_id = int(match.group(1))
            return

        # A pair of Enclosure-Id : Sot-Id was given
        match = re_slot.search(dev)
        if not match:
            self.die("Invalid MegaRaid descriptor %r given." % (dev))

        pair = match.group(1)
        if pair is None:
            pair = match.group(2)

        match = re_enc_slot.search(pair)
        if not match:
            self.die("Ooops, pair %r didn't match pattern %r???" % (
                    pair, re_enc_slot.pattern))

        self._megaraid_slot = (int(match.group(1)), int(match.group(2)))

        return self._init_megaraid_device_id()

    #--------------------------------------------------------------------------
    def _init_megaraid_device_id(self):
        """
        Evaluates the Magaraid Device Id from the given Enclosure Id and
        Slot Id.
        """

        if not self._megaraid_slot:
            self.die("Ooops, need Enclosure Id and Slot Id to evaluate " +
                    "the Magaraid Device Id.")

        if not self.megacli_cmd:
            self.die("Didn't found to MegaCli command to evaluate the " +
                    "Magaraid Device Id.")

        pd = '-PhysDrv[%d:%d]' % self._megaraid_slot

        cmd_list = [
                self.megacli_cmd,
                '-pdInfo',
                ('-PhysDrv[%d:%d]' % self._megaraid_slot),
                '-a', '0',
                '-NoLog',
        ]
        cmd_str = self.megacli_cmd
        for arg in cmd_list[1:]:
            cmd_str += ' ' + ("%r" % (arg))
        if self.verbose > 1:
            log.debug("Executing: %s", cmd_str)

        stdoutdata = ''
        stderrdata = ''
        ret = None
        timeout = abs(int(self.timeout))

        def exec_alarm_caller(signum, sigframe):
            '''
            This nested function will be called in event of a timeout

            @param signum:   the signal number (POSIX) which happend
            @type signum:    int
            @param sigframe: the frame of the signal
            @type sigframe:  object
            '''

            raise MegaCliExecTimeoutError(timeout, cmd_str)

        signal.signal(signal.SIGALRM, exec_alarm_caller)
        signal.alarm(timeout)

        # And execute it ...
        try:
            cmd_obj = subprocess.Popen(
                    cmd_list,
                    close_fds = False,
                    stderr = subprocess.PIPE,
                    stdout = subprocess.PIPE,
            )

            (stdoutdata, stderrdata) = cmd_obj.communicate()
            ret = cmd_obj.wait()

        except MegaCliExecTimeoutError, e:
            self.die(str(e))

        finally:
            signal.alarm(0)

        if self.verbose > 1:
            log.debug("Returncode: %s" % (ret))
        if stderrdata:
            msg = "Output on StdErr: %r." % (stderrdata.strip())
            log.debug(msg)

        re_no_adapter = re.compile(r'^\s*User\s+specified\s+controller\s+is\s+not\s+present',
                re.IGNORECASE)
        re_exit_code = re.compile(r'^\s*Exit\s*Code\s*:\s+0x([0-9a-f]+)', re.IGNORECASE)
        # Adapter 0: Device at Enclosure - 1, Slot - 22 is not found.
        re_not_found = re.compile(r'Device\s+at.*not\s+found\.', re.IGNORECASE)

        exit_code = ret
        no_adapter_found = False
        if stdoutdata:
            for line in stdoutdata.splitlines():

                if re_no_adapter.search(line):
                    self.die('The specified controller %d is not present.' % (
                            self.adapter_nr))

                if re_not_found.search(line):
                        self.die(line.strip())

                match = re_exit_code.search(line)
                if match:
                    exit_code = int(match.group(1), 16)
                    continue

        if not stdoutdata:
            self.die('No ouput from: %s' % (cmd_str))

        # Device Id: 38
        re_dev_id = re.compile(r'^\s*Device\s+Id\s*:\s*(\d+)', re.IGNORECASE)
        dev_id = None

        for line in stdoutdata.splitlines():
            match = re_dev_id.search(line)
            if match:
                dev_id = int(match.group(1))
                break

        if dev_id is None:
            self.die("No device Id found for PhysDrv [%d:%d] on the megaraid adapter." % 
                self._megaraid_slot)

        self._device_id = dev_id
        return

    #--------------------------------------------------------------------------
    def __call__(self):
        """
        Method to call the plugin directly.
        """

        self.parse_args()

        if self.verbose > 2:
            log.debug("Current object:\n%s", pp(self.as_dict()))

        state = nagios.state.ok
        out = "All seems to be ok."

        self.exit(state, out)

#==============================================================================

if __name__ == "__main__":

    pass

#==============================================================================

# vim: fileencoding=utf-8 filetype=python ts=4 expandtab shiftwidth=4 softtabstop=4
