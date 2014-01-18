### Author: Taisuke Yamada <tai$rakugaki.org>
"""
Monitors traffic going on IB/RDMA interfaces.

Usage:
  // specify interface using DSTAT_IB envvar.
  $ DSTAT_IB="-i ib0,ib1" dstat --ib ...

  // special keywords total/ib/ipoib are also supported.
  $ DSTAT_IB="-i total,ib" dstat --ib ...

  // default is same as "-i total"
  $ dstat --ib ...
"""

# These are already imported by dstat.py anyway
import sys, os, os.path
import re
import glob

# FIXME
# - Need to check how dstat plugin should manage namespace.
#   Scattering "global" everywhere doesn't sound right.
import optparse
global optparse
import subprocess
global subprocess

######################################################################
# helper functions
######################################################################
global find_active_ib
def find_active_ib():
    gid = []
    for i in glob.glob("/sys/class/infiniband/*/ports/*"):
        with open(i + "/state") as f:
            if f.readline().find("ACTIVE") < 0: continue
        with open(i + "/gids/0") as f:
            gid.append(f.readline().strip().replace(":", ""));

    found = []
    for i in glob.glob("/sys/class/net/*"):
        with open(i + "/address") as f:
            mac = f.readline().strip().replace(":", "")[8:]
            if mac in gid:
                found.append(os.path.basename(i))
    found.sort()

    return found

global find_active_ipoib
def find_active_ipoib():
    ifglob = glob.glob("/sys/class/net/*")

    found = []
    for ifbase in ifglob:
        with open("%s/operstate" % ifbase) as f:
            if f.readline().strip() != "up": continue
        if os.path.exists("%s/device/infiniband" % ifbase):
            found.append(os.path.basename(ifbase))
    found.sort()

    return found

global ipoib2ib
def ipoib2ib(ifname):
    macaddr = None
    with open("/sys/class/net/%s/address" % ifname) as f:
        macaddr = f.readline().strip().replace(":", "")[8:]
  
    pattern = "/sys/class/net/\w+/device/infiniband/(\w+)/ports/(\d+)/gids/0"
    gidglob = "/sys/class/net/%s/device/infiniband/*/ports/*/gids/0" % ifname
    for gidpath in glob.glob(gidglob):
        gidaddr = None
        with open(gidpath) as f:
            gidaddr = f.readline().strip().replace(":", "")
        if gidaddr == macaddr:
            mg = re.match(pattern, gidpath)
            return { "ca": mg.group(1), "port": mg.group(2) }
    return None

global run_perfquery
def run_perfquery(ifname):
    DV_FACTOR = 4 # from perfquery(8): "... indicate octets divided by 4"

    ca_info = ipoib2ib(ifname)
    command = "perfquery -r -C %(ca)s -P %(port)s" % ca_info

    stat = {}
    for line in subprocess.check_output(command.split()).split():
        if re.match("^#", line):
            continue

        mg = re.match("^(\w+):\.+(\d+)", line)
        if not mg: continue

        key = mg.group(1)
        val = mg.group(2)
        if re.match("^(XmtData|RcvData)$", key):
            stat[key] = int(val) * DV_FACTOR
        else:
            stat[key] = int(val)

    return stat

######################################################################
# dstat plugin interface
######################################################################
class dstat_plugin(dstat):
    """
    Bytes transferred per Infiniband HCA port (specified by IPoIB interface).

    Displays bandwidth used for each specified port.
    """

    def __init__(self):
        ib_opt = os.getenv('DSTAT_IB')
        if not ib_opt:
            ib_opt = "-i total"

        op = optparse.OptionParser()
        op.add_option("-i", "--ifname", dest="ifname",
                      help="specify interface to watch", metavar="IF")
        opt, args  = op.parse_args(ib_opt.split())

        self.iflist = find_active_ib()
        self.vars = []
        for i in opt.ifname.split(","):
            if i == "ib":
                self.vars += find_active_ib()
            elif i == "ipoib":
                self.vars += find_active_ipoib()
            else:
                self.vars.append(i)

        self.name  = ["ib/" + name for name in self.vars]
        self.nick  = ('send', 'recv')
        self.type  = 'f'
        self.width = 5
        self.scale = 1024
        self.cols  = 2

    def check(self):
        if not os.path.isdir("/sys/class/net"):
            raise Exception, 'Only Linux with sysfs is supported.'

    def extract(self):
        perf = {}
        if "total" in self.vars:
            for ifname in self.iflist:
                perf[ifname] = run_perfquery(ifname)

        for ifname in self.vars:
            tx = rx = 0
            if ifname == "total":
                for i in self.iflist:
                    stat = perf[i]
                    tx += stat["XmtData"]
                    rx += stat["RcvData"]
            else:
                if not perf.has_key(ifname):
                    perf[ifname] = run_perfquery(ifname)
                stat = perf[ifname]
                tx = stat["XmtData"]
                rx = stat["RcvData"]

            self.val[ifname] = (tx, rx)
