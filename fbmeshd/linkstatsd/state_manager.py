#!/usr/bin/env python3
"""
Copyright (c) 2004-present, Facebook, Inc.
All rights reserved.
"""

import asyncio
import hashlib
import json
import logging
import os.path
import pathlib
import re
import time
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from typing import Dict, Generator, List, Tuple

from magma.common.sdwatchdog import SDWatchdogTask
from magma.magmad.check.network_check import ping
from marconi.lib import meshquery, partitions
from prometheus_client import Gauge
from wifi.protos.mconfig.wifi_mconfigs_pb2 import Linkstatsd as LinkstatsMconfig


STATE_ELAPSED_TIME = Gauge(
    "update_state_duration",
    "seconds to calculate state. Bad if greater than 60 seconds",
)

STATE_ERRORS = Gauge(
    "update_state_errors",
    "errors during the state parsing loop. Needs investigating if above 0!",
)

VALIDATION_TESTS_RUNNING = Gauge(
    "testfs_validation_running",
    "whether validation tests from an upgrader -t run are going",
)

WATCHDOG_TESTS = Gauge(
    "watchdog_tests", "whether a watchdog test is passing or not", ["test"]
)

OUT_OF_BAND = Gauge(
    "out_of_band", "whether the device is getting connectivity through out-of-band"
)

IS_GATEWAY = Gauge("is_gateway", "1 if this AP is a gateway")


class NetworkStateManager(SDWatchdogTask):
    """
    Keeps the semi-static state of the network in a dict
    The state information can be queried by calling get_state(),
    which is intended to be called with a low frequency
    """

    UPDATE_PERIOD = 60  # second

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        config: Dict[str, str],
        mconfig: LinkstatsMconfig,
    ) -> None:
        super().__init__(self.UPDATE_PERIOD, loop)

        self.config = config
        self.mconfig = mconfig
        self._state: Dict[str, str] = {}
        # protects _frozen_state
        self._lock = RLock()
        self._frozen_state: Dict[str, str] = {}
        self._ping_params: ping.PingCommandParams = []

        # ping parameters
        if self.mconfig.ping_host_list:
            self._ping_params = [
                ping.PingCommandParams(
                    host, self.mconfig.ping_num_packets, self.mconfig.ping_timeout_secs
                )
                for host in self.mconfig.ping_host_list
            ]

    @contextmanager
    def write_to_state(self) -> Generator[None, None, None]:
        self._state.clear()
        start = time.time()
        yield
        to_write = deepcopy(self._state)
        # In cpython, we don't really even need this lock, since the assign
        # is atomic, but best to be explicit
        with self._lock:
            self._frozen_state = to_write
        STATE_ELAPSED_TIME.set(time.time() - start)

    def get_state(self) -> Dict[str, str]:
        with self._lock:
            return self._frozen_state

    async def _run(self) -> None:
        with self.write_to_state():
            await self.update_state()

    def _parse_iw_output(self, out_str: str) -> None:
        for line in out_str.split("\n"):
            fields = line.strip().split(" ", 1)
            if len(fields) < 2:
                continue
            elif fields[0] == "addr":
                self._state["mesh0_hw_addr"] = fields[1]
            elif fields[0] == "channel":
                self._state["mesh0_channel"] = fields[1]

    def _parse_iw_wlan_soma_info(self, s: str) -> None:
        for line in s.split("\n"):
            fields = line.strip().split(" ", 1)
            if len(fields) < 2:
                continue
            elif fields[0] == "ssid":
                self._state["wlan_soma_ssid"] = fields[1]
            elif fields[0] == "channel":
                self._state["wlan_soma_channel"] = fields[1]
            elif fields[0] == "addr":
                self._state["wlan_soma_hw_addr"] = fields[1]

    def __parse_iw_line_update_state(self, s: str, keyPrepend: str) -> Tuple[str, str]:
        """
        Given iw dump property line, update state variable with keyPrepend
        Returns (key, value)
        e.g.:
        Given:
           keyPrepend = "mesh_aabbcc"
           s = "inactive time:    680 ms"
        Add key, value to _state:
           _state["mesh_aabbcc_inactive_time"] = "680 ms"
        """
        fields = s.split(":")
        if len(fields) < 2:
            return "", ""
        key = "%s_%s" % (keyPrepend, fields[0].lower().replace(" ", "_"))
        val = fields[1].strip()
        self._state[key] = val
        return key, val

    def __parse_station_dump(self, s: str, prefix: str, includeStations: bool) -> None:
        stations = []
        currentStation = None
        meshPlinkEstabCount = 0  # count number of mesh plink: ESTAB we see
        clientAuthorizedCount = 0  # count number of authorized: yes we see
        for line in s.split("\n"):
            line = line.strip()
            if len(line) == 0:
                continue
            if line.startswith("Station"):
                fields = line.split()
                if len(fields) < 2:
                    continue
                currentStation = fields[1].lower()
                stations.append(currentStation)
            elif currentStation is None:
                # on properly formed input, this should never happen
                continue
            else:
                k, v = self.__parse_iw_line_update_state(
                    line, "%s_%s" % (prefix, currentStation)
                )
                if k.endswith("_mesh_plink") and v == "ESTAB":
                    meshPlinkEstabCount += 1
                if k.endswith("_authorized") and v == "yes":
                    clientAuthorizedCount += 1
        self._state["%s_num_stations" % prefix] = str(len(stations))
        if includeStations and stations:
            self._state["%s_stations" % prefix] = ",".join(sorted(stations))
        if meshPlinkEstabCount:  # only include this if non-zero
            self._state["%s_num_stations_estab" % prefix] = str(meshPlinkEstabCount)
        if clientAuthorizedCount:  # only include this if non-zero
            self._state["%s_num_stations_authorized" % prefix] = str(
                clientAuthorizedCount
            )

    def _parse_wlan_station_dump(self, s: str) -> None:
        self.__parse_station_dump(s, "wlan_soma", includeStations=False)

    def _parse_mesh0_station_dump(self, s: str) -> None:
        self.__parse_station_dump(s, "mesh0", includeStations=True)

    def _parse_eth0_ip_addr_list(self, s: str) -> None:
        self._state["eth0_ip"] = s.replace("\n", ",")

    def _parse_bridge0_ip_addr_list(self, s: str) -> None:
        self._state["bridge0_ip"] = s.replace("\n", ",")

    def _parse_mesh0_ip_addr_list(self, s: str) -> None:
        self._state["mesh0_ip"] = s.replace("\n", ",")

    def _parse_lo_ip_addr_list(self, s: str) -> None:
        self._state["lo_ip"] = s.replace("\n", ",")

    def _parse_tun_vpn_ip_addr_list(self, s: str) -> None:
        ips = s.replace("\n", ",")
        if ips:
            self._state["tun_vpn_ip"] = ips

    def _parse_tun0_ip_addr_list(self, s: str) -> None:
        ips = s.replace("\n", ",")
        if ips:
            self._state["tun0_ip"] = ips

    def _parse_metadata(self, s: str) -> None:
        """Add the contents of the /METADATA file"""
        parsed = parse_metadata(s)
        for k in ("commit-hash", "config-overlay", "fbpkg"):  # whitelist of info
            if k in parsed:
                self._state["metadata_%s" % k] = parsed[k]

    def _parse_uptime(self, s: str) -> None:
        """
        if s == "02:57:45 up 2:19, load average: 0.32, 0.31, 0.28"
        updates states:
            "uptime" = "02:57:45 up 2:19",
            "load_average" = "0.32, 0.31, 0.28"
        """
        sp = s.split(",", 1)
        self._state["uptime"] = sp[0].split(" ", 2)[-1].strip()
        if len(sp) < 2:
            return
        self._state["load_average"] = sp[1].split(":")[-1].strip()

    def _parse_staged_update(self, s: str) -> None:
        """
        's' is looks like json but it's totally not
        get "version" and put in state "staged_update"
        """
        if len(s.strip()) == 0:
            return
        for line in s.split("\n"):
            line = line.strip()
            if "version" in line:
                key_val = line.split(":", 1)
                if len(key_val) != 2:
                    continue
                self._state["staged_update"] = key_val[1].lstrip('"').rstrip('",')
                return
        # fall through
        self._state["staged_update"] = s

    def _parse_mpath_dump(self, s: str) -> None:
        """
        parse mpath dump
        DEST ADDR   NEXT HOP   IFACE  SN  METRIC  QLEN  EXPTIME  DTIM  DRET    FLAGS
        60:31:97:3e:82:56 60:31:97:3e:82:56 mesh0   844 16  0   2480    100 0   0x5
        """
        if len(s.strip()) == 0:
            return
        for line in s.split("\n"):
            fields = line.strip().split()
            if len(fields) < 10 or "DEST" in fields:
                continue
            destAddr = fields[0]
            nextHop = fields[1]
            sn = fields[3]
            metric = fields[4]
            exptime = fields[6]

            self._state["mesh0_%s_nexthop" % destAddr] = nextHop
            self._state["mesh0_%s_sn" % destAddr] = sn
            self._state["mesh0_%s_metric" % destAddr] = metric
            self._state["mesh0_%s_exptime" % destAddr] = exptime

    def _parse_chilli_query_list(self, s: str) -> None:
        """
        04-69-F8-EB-7C-E7 0.0.0.0 none 151093737600000002 0 - 0/0 0/0 0/0 0/0 0 0 0/0 0/0 -
        40-4E-36-25-7A-B5 10.0.18.3 dnat [xwf(Q0,in:0/0B,out:0/0B)] 151093730200000001 1 40-4E-36-25-7A-B5 1510/0 1/0 0/0 24705/0 0 0 0%/0 0%/0 -
        """
        if s == "":
            logging.warning(
                "Failed to parse chilli_query -json results because chilli_query could"
                " not connect; is chilli running?"
            )
            return

        try:
            query_results = json.loads(s)
        except Exception:
            logging.exception(
                "Failed parsing `chilli_query -json list` results: '" + s + "'"
            )
            return

        count_total = 0
        count_authorized = 0
        count_unauthorized = 0
        count_no_ip = 0

        for session in query_results["sessions"]:
            client_authorized = session.get("clientState", "")
            client_ip = session.get("ipAddress", "")
            client_mac = session.get("macAddress", "")
            if client_authorized == "" or client_ip == "" or client_mac == "":
                logging.error(
                    "Malformed client json entry in `chilli_query -json list`: missing"
                    " at least one of ip address=%s, mac address=%s, client state=%s."
                    % (client_authorized, client_ip, client_mac)
                )
                continue

            count_total += 1

            if client_authorized == 1:
                count_authorized += 1
            else:
                count_unauthorized += 1

            if client_ip == "0.0.0.0":
                count_no_ip += 1

        self._state["xwf_clients_total"] = str(count_total)
        self._state["xwf_clients_authorized"] = str(count_authorized)
        self._state["xwf_clients_unauthorized"] = str(count_unauthorized)
        self._state["xwf_clients_no_ip"] = str(count_no_ip)

    def _parse_validation_tests_passed(self, s: str) -> None:
        self._state["validation_tests_passed"] = s.replace("\n", ",")

    def _parse_validation_tests_failed(self, s: str) -> None:
        self._state["validation_tests_failed"] = s.replace("\n", ",")

    def _parse_watchdog_tests(self, s: str) -> None:
        passing: List[str] = []
        failing: List[str] = []
        for line in s.strip().splitlines():
            parts = line.split()
            if len(parts) == 2:
                test, result = parts
                passed = result == "pass"
                WATCHDOG_TESTS.labels(test).set(int(passed))
                (passing if passed else failing).append(test)
        self._state["validation_watchdog_tests_passed"] = ",".join(passing)
        self._state["validation_watchdog_tests_failed"] = ",".join(failing)

    def _parse_public_ip(self, s: str) -> None:
        for line in s.strip().splitlines():
            parts = line.partition(":")
            if parts[0].lower() == "IP address (trusted)".lower():
                self._state["public_ip"] = parts[2]
            if parts[0].lower() == "Carrier for (trusted) IP address".lower():
                self._state["carrier_detected"] = parts[2]
        try:
            with open("/persistent/swf_conf.json", "r") as config_file:
                swf = json.load(config_file)
                if "id" in swf:
                    self._state[
                        "carrier_detected"
                    ] = f'{self._state["carrier_detected"]}, swf gw_id: {swf["id"]}'
        except (KeyError, FileNotFoundError, json.decoder.JSONDecodeError):
            pass

    def _parse_rootfs_current(self, s: str) -> None:
        """
        parse:
        " board=NBG6817 root=/dev/mmcblk0p11 rootfstype=ext4 rw rootwait" ...
        """
        m = re.match(r".*(^|\s)root=/dev/(\S+).*", s)
        if m:
            self._state["sys_rootfs_current"] = m.group(2)

    def _parse_rootfs_env(self, s: str) -> None:
        """
        parse: "soma_rootfs=mmcblk0p11"
        parse: "soma_testfs=mmcblk0p11"
        """
        data = s.strip().split("=", 1)
        if len(data) != 2:
            return
        if data[0] == "soma_rootfs":
            self._state["sys_rootfs"] = data[1]
        elif data[0] == "soma_testfs":
            self._state["sys_testfs"] = data[1]

    def parse_is_gateway(self, s: str) -> None:
        self._state["is_gateway"] = s
        IS_GATEWAY.set(int(s == "true"))

    def _parse_validation_status(self, s: str) -> None:
        self._state["validation_status"] = s
        VALIDATION_TESTS_RUNNING.set(int(s.strip() == "running"))

    async def _get_dump_mpath(self) -> Dict[str, str]:
        def u64NBOtoMac(mac: int) -> str:
            mac_str = "{:016x}".format(mac & 0xFFFFFFFFFFFF0000)
            return "".join(list(map("".join, zip(*[iter(mac_str)] * 2)))[:6][::-1])

        def u64NBOtoIPv6(mac: int) -> str:
            mac_str = "{:016x}".format(mac & 0xFFFFFFFFFFFF0000)
            mac_hex = list(map("".join, zip(*[iter(mac_str)] * 2)))[:6][::-1]

            parts = mac_hex[0:3] + ["ff", "fe"] + mac_hex[3:6]
            parts[0] = "{:02x}".format(int(parts[0], 16) ^ 2)

            ipv6Parts = []
            for i in range(0, len(parts), 2):
                ipv6Parts.append("".join(parts[i : i + 2]).lstrip("0"))  # noqa: E203

            ipv6 = "fe80::{}".format(":".join(ipv6Parts))
            return ipv6

        state = {}
        neighbors: List[str] = []
        mpaths = meshquery.dump_mpaths()
        for mpath in mpaths:
            mac = u64NBOtoMac(mpath.nextHop)
            ipv6 = u64NBOtoIPv6(mpath.nextHop)
            if mac not in neighbors:
                state[f"openr_{mac}_ipv6"] = ipv6
                state[f"openr_{mac}_metric"] = str(mpath.nextHopMetric)
                neighbors.append(mac)

        state["openr_neighbors"] = ",".join(neighbors)
        return state

    async def update_state(self) -> None:
        # arbitrary command outputs to collect
        metacmds: List[Tuple] = [
            # (label, cmd, parser)
            ("iw_mesh0", "iw dev mesh0 info", self._parse_iw_output),
            (
                "iw_wlan_soma_info",
                "iw dev wlan_soma info",
                self._parse_iw_wlan_soma_info,
            ),
            ("date", "date"),
            ("version", "cat /etc/version"),
            ("metadata", "cat /METADATA", self._parse_metadata),
            ("uptime", "uptime", self._parse_uptime),
            ("uptime_s", "awk '{print $1}' /proc/uptime"),
            ("boot_id", "cat /proc/sys/kernel/random/boot_id"),
            (
                "staged_update",
                "/tmp/soma-update-nbg6817.bin -m",
                self._parse_staged_update,
            ),
            (
                "eth0_ip",
                "ip addr list eth0 | grep inet | awk '{print $2}'",
                self._parse_eth0_ip_addr_list,
            ),
            (
                "mesh0_ip",
                "ip addr list mesh0 | grep inet | awk '{print $2}'",
                self._parse_mesh0_ip_addr_list,
            ),
            (
                "bridge0_ip",
                "ip addr list bridge0 | grep inet | awk '{print $2}'",
                self._parse_bridge0_ip_addr_list,
            ),
            (
                "lo_ip",
                "ip addr list lo | grep inet | awk '{print $2}'",
                self._parse_lo_ip_addr_list,
            ),
            # vpn
            (
                "tun_vpn_ip",
                "ip addr list tun_vpn | grep inet | awk '{print $2}'",
                self._parse_tun_vpn_ip_addr_list,
            ),
            # chilli
            (
                "tun0_ip",
                "ip addr list tun0 | grep inet | awk '{print $2}'",
                self._parse_tun0_ip_addr_list,
            ),
            (
                "is_gateway",
                "ip -4 route list exact default | grep -qs 'metric 1024' && echo true || echo false",
                self.parse_is_gateway,
            ),
            ("mesh_path", "iw dev mesh0 mpath dump", self._parse_mpath_dump),
            (
                "mesh_gateway_path",  # blank if gateway, "direct to X" if mesh to gw, "hop via X" if multihop
                'iw dev mesh0 mpath dump | egrep "^$('
                r"ip n show | egrep \"^172.16.0.1\s\" | awk '{print $5}'"
                ') " | awk \'{ print ($1 == $2) ? "direct to " $2 : "hop via " $2 }\'',
            ),
            # note that there could be multiple paths for default route (rare)
            (
                "default_route",
                'if [ -n "$(ip route show dev mesh0 0.0.0.0/0)" ] || [ -n "$(ip route show dev eth0 0.0.0.0/0)" ]; then '
                "echo $(ip route show 0.0.0.0/0 | awk '/ dev / { print $5 \",\" $3 }') | tr ' ' ';'; "
                "else "
                "echo $(ip -6 route show fd00:ffff::/96 | awk '/ dev / { print $5 \",\" $3 }') | tr ' ' ';'; "
                "fi",
            ),
            (
                "default_route_v6",
                "echo $(ip -6 route show ::/0 | awk '/ dev / { print $5 \",\" $3 }') | tr ' ' ';'",
            ),
            (
                "wlan_soma_station_dump",
                "iw dev wlan_soma station dump | "
                'egrep "(^Station)|(expected throughput:)|(signal:)|(inactive time:)|([rt]x bytes:)|(authorized:)"',
                self._parse_wlan_station_dump,
            ),
            (
                "mesh_station_dump",
                "iw dev mesh0 station dump | "
                'egrep "(^Station)|(expected throughput:)|(signal:)|(inactive time:)|([rt]x bytes:)|(mesh plink:)|(rx bitrate:)"',
                self._parse_mesh0_station_dump,
            ),
            (
                "connected_clients",
                "chilli_query -json list",
                self._parse_chilli_query_list,
            ),
            (
                "validation_status",
                "cat /var/run/validate-image/status",
                self._parse_validation_status,
            ),
            ("validation_run_count", "cat /var/run/validate-image/run_count"),
            (
                "validation_tests_passed",
                "cat /var/run/validate-image/results | "
                "awk '$2==\"pass\" { print $1 }'",
                self._parse_validation_tests_passed,
            ),
            (
                "validation_tests_failed",
                "cat /var/run/validate-image/results | "
                "awk '$2!=\"pass\" { print $1 }'",
                self._parse_validation_tests_failed,
            ),
            ("validation_decision", "cat /var/run/validate-image/decision"),
            (
                "validation_testfs",
                r"grep -q '\<testfs\>' /proc/cmdline && echo true || echo false",
            ),
            (
                "validation_watchdog_run_count",
                "cat /var/run/validate-image/watchdog_run_count",
            ),
            (
                "validation_watchdog_tests_",
                "cat /var/run/validate-image/watchdog_results",
                self._parse_watchdog_tests,
            ),
            (
                "validation_watchdog_last_check_time",
                "cat /var/run/validate-image/watchdog_last_check_time",
            ),
            (
                "validation_watchdog_last_passed_time",
                "cat /var/run/validate-image/watchdog_last_passed_time",
            ),
            ("sys_rootfs_current", "cat /proc/cmdline", self._parse_rootfs_current),
            ("sys_rootfs", "fw_printenv soma_rootfs", self._parse_rootfs_env),
            ("sys_testfs", "fw_printenv soma_testfs", self._parse_rootfs_env),
            (
                "public_ip",
                "curl -4 --connect-timeout 5 http://h.facebook.com/diagnostics",
                self._parse_public_ip,
            ),
        ]

        cmdoutputs = []
        for metacmd in metacmds:
            label = metacmd[0]
            cmd = metacmd[1]
            parser = None if len(metacmd) <= 2 else metacmd[2]

            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            stdout, stderr = await proc.communicate()
            # Could have parsers return Dict[str, str] and then just merge that
            # into state under lock
            cmdoutputs.append((label, stdout, parser))

        additional_stats = await asyncio.gather(
            get_partition_state(),
            self._get_dump_mpath(),
            get_out_of_band(),
            get_wifiprops_versions(),
            return_exceptions=True,  # This essentially squelches exceptions
        )

        errors = 0

        for label, stdout, parser in cmdoutputs:
            # removes incompatible bytes like the systemctl colors
            stdoutBytes = bytes([c for c in stdout if c < 128])
            stdoutClean = stdoutBytes.decode("utf-8", errors="ignore").strip()
            if parser:
                try:
                    parser(stdoutClean)
                except Exception:
                    errors += 1
                    logging.exception("Exception when parsing stat '%s'", label)
                continue
            if len(stdoutClean) == 0:  # skip empty fields
                continue
            self._state[label] = stdoutClean

        if self.mconfig.ping_host_list:
            await self._collect_ping_stats()
        for stat in additional_stats:
            if isinstance(stat, Exception):
                errors += 1
                logging.error("Error parsing additional_stats: %s", stat)
            else:
                self._state.update(stat)
        STATE_ERRORS.set(errors)

    async def _collect_ping_stats(self) -> None:
        ping_results = await ping.ping_async(self._ping_params)
        ping_results_list = list(ping_results)

        for param, result in zip(self._ping_params, ping_results_list):
            if result.error:
                logging.debug(
                    "Failed to ping %s with error: %s", param.host_or_ip, result.error
                )
            else:
                host = param.host_or_ip
                key = "ping:" + host
                value = result.stats.rtt_avg
                with self._lock:
                    self._state[key] = "%.2f" % value

                logging.debug(
                    "Pinged %s with %d packet(s). Average RTT ms: %s",
                    result.host_or_ip,
                    result.num_packets,
                    result.stats.rtt_avg,
                )


def parse_metadata(s: str) -> Dict[str, str]:
    """
    Parses a METADATA or alternate_METADATA file and returns fields as a dict.

    Example:

    Wi-Fi soma-image-1.0 (nbg6817) Rootfs Build Information

    build-user: alanw
    build-host: devvm886.prn3.facebook.com
    build-time: Thu May  3 14:38:49 PDT 2018
    build-time-epoch: 1525383529
    commit-hash: 8592d04fcbfd5a844d98f3c761aeb6cbb32a6ea5
    config-overlay: mpkdogfood
    fbpkg: soma.image-mpkdogfood:5ff4882155f54506a6066a293f2ef2c4

    Returned:
    {
        "commit-hash": "8592d04fcbfd5a844d98f3c761aeb6cbb32a6ea5",
        "config-overlay": "mpkdogfood",
        "fbpkg": "soma.image-mpkdogfood:5ff4882155f54506a6066a293f2ef2c4",
    }
    """
    parsed: Dict[str, str] = {}
    for line in s.split("\n"):
        key, found, value = line.partition(": ")
        if found and " " not in key:
            parsed[key] = value.strip()
    return parsed


async def get_partition_state() -> Dict[str, str]:
    """Record which partitions exist and if they have versions on them"""
    curr_partition = partitions.get_current_partition()
    alt_partition = partitions.get_alt_partition()
    partition_map = {}
    for partition in (curr_partition, alt_partition):
        if not partition:
            continue
        partition_info = {"active": partition == curr_partition}

        info = partitions.get_partition_info(partition)
        if "version" in info:
            partition_info["version"] = info["version"]

        partition_map[partition] = partition_info
    return {"partitions": json.dumps(partition_map)}


async def get_out_of_band() -> Dict[str, str]:
    oob_enabled = os.path.exists("/var/run/oob_enabled")
    OUT_OF_BAND.set(int(oob_enabled))
    return {"out_of_band": "1" if oob_enabled else "0"}


async def get_wifiprops_versions() -> Dict[str, str]:
    """Get version of wifiprops visible"""

    def sha256(path: pathlib.Path) -> str:
        if not path.exists():
            return ""
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()[:6]
        except FileNotFoundError:
            return ""

    state_dir = pathlib.Path("/run/checksystemdrestart/")

    service_versions = {}
    for version_file in state_dir.glob("*.wifiproperties.json"):
        version = sha256(version_file)
        if version:
            service_versions[
                version_file.name[: -len(".wifiproperties.json")]
            ] = version

    return {
        "wifiprops_version": sha256(pathlib.Path("/run/wifiproperties.json")),
        "wifiprops_service_versions": json.dumps(service_versions),
    }
