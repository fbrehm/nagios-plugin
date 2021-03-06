#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
@author: Frank Brehm
@contact: frank.brehm@profitbricks.com
@copyright: © 2010 - 2015 by Frank Brehm, Berlin
@summary: Module for CheckSoftwareRaidPlugin class
"""

# Standard modules
import os
import logging
import textwrap
import re
import stat
import glob
import errno

# Third party modules

# Own modules

import nagios

from nagios.common import pp

from nagios.plugin import NPReadTimeoutError

from nagios.plugin.functions import max_state, to_bool

from nagios.plugin.extended import ExtNagiosPlugin

# --------------------------------------------
# Some module variables

__version__ = '0.3.6'

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 3
"""
Default timeout for all reading operations.
"""

re_sync_completed = re.compile(r'(\d+)\s*/\s*(\d+)')


# =============================================================================
class RaidState(object):
    """
    Encapsulation class for the state of an MD device.
    """

    # -------------------------------------------------------------------------
    def __init__(self, device):

        self.device = device

        self.array_state = None
        self.degraded = None
        self.nr_raid_disks = None
        self.raid_level = None
        self.suspended = None
        self.sync_action = None
        self.sectors_total = None
        self.sectors_synced = None
        self.sync_completed = None
        self.slaves = []
        self.raid_devices = {}
        self.failed_devices = {}
        self.spare_devices = {}

    # -------------------------------------------------------------------------
    def as_dict(self):

        d = {}
        for key in self.__dict__:
            if key in ('failed_devices', 'raid_devices', 'spare_devices'):
                continue
            val = self.__dict__[key]
            d[key] = val

        d['failed_devices'] = {}
        d['raid_devices'] = {}
        d['spare_devices'] = {}

        for sid in self.failed_devices:
            if not self.failed_devices[sid]:
                d['failed_devices'][sid] = None
            else:
                d['failed_devices'][sid] = self.failed_devices[sid].as_dict()

        for sid in self.raid_devices:
            if not self.raid_devices[sid]:
                d['raid_devices'][sid] = None
            else:
                d['raid_devices'][sid] = self.raid_devices[sid].as_dict()

        for sid in self.spare_devices:
            if not self.spare_devices[sid]:
                d['spare_devices'][sid] = None
            else:
                d['spare_devices'][sid] = self.spare_devices[sid].as_dict()

        return d


# =============================================================================
class SlaveState(object):
    """
    Encapsulation class for the state of a slave device of a RAID device.
    """

    # -------------------------------------------------------------------------
    def __init__(self, nr, path):

        self.nr = nr
        self.path = path
        self.block_device = None
        self.state = None
        self.rdlink = None
        self.rdlink_exists = None

    # -------------------------------------------------------------------------
    def as_dict(self):

        d = {}
        for key in self.__dict__:
            val = self.__dict__[key]
            d[key] = val

        return d


# =============================================================================
class CheckSoftwareRaidPlugin(ExtNagiosPlugin):
    """
    A special NagiosPlugin class for checking the state of one or all  Linux
    software RAID devices (MD devices).
    """

    # -------------------------------------------------------------------------
    def __init__(self):
        """
        Constructor of the CheckSoftwareRaidPlugin class.
        """

        usage = """\
        %(prog)s [-v] [<MD device>]
        """
        usage = textwrap.dedent(usage).strip()
        usage += '\n       %(prog)s --usage'
        usage += '\n       %(prog)s --help'

        blurb = "Copyright (c) 2015 Frank Brehm, Berlin.\n\n"
        blurb += "Checks the state of one or all  Linux software RAID devices."

        super(CheckSoftwareRaidPlugin, self).__init__(
            usage=usage, blurb=blurb, timeout=DEFAULT_TIMEOUT,
        )

        self.devices = []
        """
        @ivar: all MD devices to check
        @type: list of str
        """

        self.check_all = False
        """
        @ivar: flag to check all available MD devices
        @type: bool
        """

        self.good_ones = []
        """
        @ivar: all messages after checking with OK state
        @type: list of str
        """

        self.bad_ones = []
        """
        @ivar: all messages after checking with WARNING state
        @type: list of str
        """

        self.ugly_ones = []
        """
        @ivar: all messages after checking with CRITICAL state
        @type: list of str
        """

        self.checked_devices = 0
        """
        @ivar: the total number of checked devices
        @type: int
        """

        self.spare_ok = True
        """
        @ivar: flag, whether existing spare devices are OK or
               should be noticed as a warning
        @type: bool
        """

        self._add_args()

    # -------------------------------------------------------------------------
    def as_dict(self):
        """
        Typecasting into a dictionary.

        @return: structure as dict
        @rtype:  dict

        """

        d = super(CheckSoftwareRaidPlugin, self).as_dict()

        d['devices'] = self.devices
        d['check_all'] = self.check_all
        d['good_ones'] = self.good_ones
        d['bad_ones'] = self.bad_ones
        d['ugly_ones'] = self.ugly_ones
        d['checked_devices'] = self.checked_devices
        d['spare_ok'] = self.spare_ok

        return d

    # -------------------------------------------------------------------------
    def _add_args(self):
        """
        Adding all necessary arguments to the commandline argument parser.
        """

        msg = (
            "Existence of spare devices leads to a warning. Overrides a possible entry "
            "'spare_ok' in section [softwareraid] in file '/etc/nagios/plugins.ini'.")
        self.add_arg(
            '--no-spare',
            dest='no_spare',
            action='store_true',
            help=msg,
        )

        self.add_arg(
            'device',
            dest='device',
            nargs='?',
            help=(
                "The device to check (given as 'mdX' or '/dev/mdX' "
                "or /sys/block/mdX, must exists)."),
        )

    # -------------------------------------------------------------------------
    def parse_args(self, args=None):
        """
        Executes self.argparser.parse_args().

        @param args: the argument strings to parse. If not given, they are
                     taken from sys.argv.
        @type args: list of str or None

        """

        super(CheckSoftwareRaidPlugin, self).parse_args(args)

        self.init_root_logger()

        ini_opts = self.argparser._load_config_section('softwareraid')
        log.debug("Got options from ini-Parser: %s", pp(ini_opts))
        if ini_opts and 'spare_ok' in ini_opts:
            self.spare_ok = to_bool(ini_opts['spare_ok'])

        if self.argparser.args.no_spare:
            self.spare_ok = False

        re_dev = re.compile(r'^(?:/dev/|/sys/block/)?(md\d+)$')

        if self.argparser.args.device:
            if self.argparser.args.device.lower() == 'all':
                self.check_all = True
            else:
                match = re_dev.search(self.argparser.args.device)
                if not match:
                    self.die("Device %r is not a valid MD device." % (
                        self.argparser.args.device))
                self.devices.append(match.group(1))
        else:
            self.check_all = True

        if self.check_all:
            return

        dev = self.devices[0]
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

    # -------------------------------------------------------------------------
    def collect_devices(self):
        """
        Method to collect all MD devices and to store them in self.devices.
        """

        mddev_pattern = os.sep + os.path.join('sys', 'block', 'md*')
        log.debug("Collecting all MD devices with %r ...", mddev_pattern)

        dirs = glob.glob(mddev_pattern)
        if not dirs:
            return

        for md_dir in dirs:
            if not os.path.isdir(md_dir):
                if self.verbose:
                    log.warn("Strange - %r is not a directory.", md_dir)
                continue
            dev = os.path.basename(md_dir)
            self.devices.append(dev)

        return

    # -------------------------------------------------------------------------
    def check_mddev(self, dev):
        """
        Underlying method to check the state of a MD device.

        @raise NPReadTimeoutError: on timeout reading a particular file
                                   in sys filesystem
        @raise IOError: if a sysfilesystem file disappears sinc start of
                        this script

        @param dev: the name of the MD device to check (e.g. 'md0', 'md400')
        @type dev: str

        @return: a tuple of two values:
                    * the numeric (Nagios) state
                    * a textual description of the state
        @rtype: tuple of str and int

        """

        log.debug("Checking device %r ...", dev)

        # Define directories and files in sysfs
        # /sys/block/mdX
        base_dir = os.sep + os.path.join('sys', 'block', dev)
        # /sys/block/mdX/md
        base_mddir = os.path.join(base_dir, 'md')
        # /sys/block/mdX/md/array_state
        array_state_file = os.path.join(base_mddir, 'array_state')
        # /sys/block/mdX/md/degraded
        degraded_file = os.path.join(base_mddir, 'degraded')
        # /sys/block/mdX/md/raid_disks
        raid_disks_file = os.path.join(base_mddir, 'raid_disks')
        # /sys/block/mdX/md/level
        raid_level_file = os.path.join(base_mddir, 'level')
        # /sys/block/mdX/md/degraded
        degraded_file = os.path.join(base_mddir, 'degraded')
        # /sys/block/mdX/md/suspended
        suspended_file = os.path.join(base_mddir, 'suspended')
        # /sys/block/mdX/md/sync_action
        sync_action_file = os.path.join(base_mddir, 'sync_action')
        # /sys/block/mdX/md/sync_completed
        sync_completed_file = os.path.join(base_mddir, 'sync_completed')
        # /sys/block/mdX/md/dev-*
        slavedir_pattern = os.path.join(base_mddir, 'dev-*')

        for sys_dir in (base_dir, base_mddir):
            if not os.path.isdir(sys_dir):
                raise IOError(errno.ENOENT, "Directory doesn't exists.", sys_dir)

        state = RaidState(dev)

        # Array status
        state.array_state = self.read_file(array_state_file).strip()
        # RAID level
        state.raid_level = self.read_file(raid_level_file).strip()
        # degraded state, if available
        if os.path.exists(degraded_file):
            state.degraded = bool(int(self.read_file(degraded_file)))
        # number of raid disks
        state.nr_raid_disks = int(self.read_file(raid_disks_file))
        # suspended state, if available
        if os.path.exists(suspended_file):
            state.suspended = bool(int(self.read_file(suspended_file)))
        # state of synchronisation, if available
        if os.path.exists(sync_action_file):
            state.sync_action = self.read_file(sync_action_file).strip()

        # state of synchronisation process, if available
        if os.path.exists(sync_completed_file):
            sync_state = self.read_file(sync_completed_file).strip()
            match = re_sync_completed.search(sync_state)
            if match:
                state.sectors_synced = int(match.group(1))
                state.sectors_total = int(match.group(2))
                if state.sectors_total:
                    state.sync_completed = (
                        float(state.sectors_synced) / float(state.sectors_total))

        i = 0
        while i < state.nr_raid_disks:
            state.raid_devices[i] = None
            i += 1

        if self.verbose > 3:
            log.debug(
                "Searching for slave dirs with pattern %r ...", slavedir_pattern)
        slavedirs = glob.glob(slavedir_pattern)
        if self.verbose > 2:
            log.debug("Found slave dirs: %r", slavedirs)

        for slave_dir in slavedirs:

            if self.verbose > 3:
                log.debug("Checking slave dir %r ...", slave_dir)

            # Defining some sysfs files
            # /sys/block/mdX/md/dev-XYZ/state
            slave_state_file = os.path.join(slave_dir, 'state')
            # /sys/block/mdX/md/dev-XYZ/slot
            slave_slot_file = os.path.join(slave_dir, 'slot')
            # /sys/block/mdX/md/dev-XYZ/block
            slave_block_file = os.path.join(slave_dir, 'block')

            is_spare = False

            # Reading some status files
            try:
                slave_slot = int(self.read_file(slave_slot_file))
            except ValueError:
                slave_slot = None
            slave_state = self.read_file(slave_state_file).strip()
            if slave_state == 'spare':
                is_spare = True

            rd_link = None
            if slave_slot is not None:
                rd_link = os.path.join(base_mddir, 'rd%d' % (slave_slot))

            # Retreiving the slave block device
            block_target = os.readlink(slave_block_file)
            slave_block_device = os.path.normpath(os.path.join(
                os.path.dirname(slave_block_file), block_target))
            slave_bd_basename = os.path.basename(slave_block_device)
            slave_block_device = os.sep + os.path.join('dev', slave_bd_basename)

            slave = SlaveState(slave_slot, slave_dir)
            slave.block_device = slave_block_device
            slave.state = slave_state

            # Check existense of the rdX link
            slave.rdlink = rd_link
            if rd_link is not None and os.path.exists(rd_link):
                slave.rdlink_exists = True
            else:
                slave.rdlink_exists = False

            # Assigne slave as a raid or a spare device
            state.slaves.append(slave_bd_basename)
            if is_spare:
                state.spare_devices[slave_bd_basename] = slave
            elif rd_link is None or slave_state == 'faulty':
                state.failed_devices[slave_bd_basename] = slave
            else:
                state.raid_devices[slave_slot] = slave

        if self.verbose > 2:
            log.debug("Status results for %r:\n%s", dev, pp(state.as_dict()))

        # And evaluate the results ....
        state_id = nagios.state.ok

        # Check the array state
        state_msg = "%s - %s" % (dev, state.array_state)
        if state.array_state not in (
                'readonly', 'read-auto', 'clean', 'active', 'active-idle'):
            if state.array_state == 'write-pending':
                state_id = nagios.state.warning
            elif state.array_state in ('clear', 'inactive', 'readonly'):
                state_id = nagios.state.critical
            else:
                state_id = nagios.state.unknown

        if not self.spare_ok:
            # Check for existing spare devices
            if state.spare_devices.keys():
                state_msg += ", has spares %r" % (state.spare_devices.keys())
                state_id = max_state(state_id, nagios.state.warning)

        # Check degraded and synchronisation state
        if state.degraded:

            state_msg += ", degraded"

            if state.sync_action is None:
                state_id = max_state(state_id, nagios.state.critical)
                state_msg += ", unknown sync action"
            elif state.sync_action == 'idle':
                state_id = max_state(state_id, nagios.state.critical)
                state_msg += ", idle"
            elif state.sync_action in ('resync', 'recover', 'check', 'repair'):
                state_id = max_state(state_id, nagios.state.warning)
                state_msg += ", " + state.sync_action
            else:
                state_id = max_state(state_id, nagios.state.unknown)
                state_msg += ", sync " + state.sync_action

            # Add percentage of sync completed to output
            if state.sync_completed is not None:
                state_msg += " %.1f%%" % ((state.sync_completed * 100))

        # Check state of slave devices
        for i in state.raid_devices:
            log.debug("Evaluating state of raid_device[%r]", i)
            if state.raid_devices[i] is None:
                if state.sync_action in ('resync', 'recover', 'check', 'repair'):
                    state_id = max_state(state_id, nagios.state.warning)
                else:
                    state_id = max_state(state_id, nagios.state.critical)
                state_msg += ", raid_device[%r] fails" % (i)
                continue
            raid_device = state.raid_devices[i]
            if raid_device.state in ('in_sync', 'writemostly'):
                continue
            bd = os.path.basename(raid_device.block_device)
            state_msg += ", raid_device[%r]=%s %s" % (i, bd, raid_device.state)
            if not raid_device.rdlink_exists:
                state_msg += " failed"
                state_id = max_state(state_id, nagios.state.critical)

        if state.failed_devices.keys():
            state_msg += ", failed %r" % (state.failed_devices.keys())
            state_id = max_state(state_id, nagios.state.critical)

        return (state_id, state_msg)

    # -------------------------------------------------------------------------
    def __call__(self):
        """
        Method to call the plugin directly.
        """

        self.parse_args()
        if self.check_all:
            self.collect_devices()
            if not self.devices:
                self.exit(nagios.state.ok, "No MD devices to check found.")

        if self.verbose > 2:
            log.debug("Current object:\n%s", pp(self.as_dict()))
        log.debug("MD devices to check: %r", self.devices)

        state = nagios.state.ok
        out = "MD devices seems to be ok."

        for dev in sorted(self.devices, key=lambda x: int(x.replace('md', ''))):
            result = None
            try:
                result = self.check_mddev(dev)
            except NPReadTimeoutError:
                msg = "%s - timeout on getting information" % (dev)
                self.ugly_ones.append(msg)
            except IOError as e:
                msg = "MD device %r disappeared during this script: %s" % (
                    dev, e)
                log.debug(msg)
                continue
            except Exception as e:
                msg = "Error on getting information about %r: %s" % (dev, e)
                self.handle_error(msg, e.__class__.__name__, True)
                self.die("Unknown %r error on getting information about %r: %s" % (
                    e.__class__.__name__, dev, e))
            if result is None:
                continue

            self.checked_devices += 1
            (state, output) = result
            if state == nagios.state.ok:
                self.good_ones.append(output)
            elif state == nagios.state.warning:
                self.bad_ones.append(output)
            else:
                self.ugly_ones.append(output)

        if not self.checked_devices:
            self.exit(nagios.state.ok, "No MD devices to check found.")

        if self.verbose > 2:
            log.debug("Ugly states: %s", pp(self.ugly_ones))
            log.debug("Bad states: %s", pp(self.bad_ones))
            log.debug("Good states: %s", pp(self.good_ones))

        msgs = []
        if self.bad_ones or self.ugly_ones:
            for m in self.ugly_ones:
                msgs.append(m)
            for m in self.bad_ones:
                msgs.append(m)
        else:
            msgs = self.good_ones[:]

        out = '; '.join(msgs)
        if self.ugly_ones:
            state = nagios.state.critical
        elif self.bad_ones:
            state = nagios.state.warning

        self.exit(state, out)

# =============================================================================

if __name__ == "__main__":

    pass

# =============================================================================

# vim: fileencoding=utf-8 filetype=python ts=4 expandtab shiftwidth=4 softtabstop=4
