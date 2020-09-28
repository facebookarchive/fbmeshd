#!/usr/bin/env python3
# Copyright (c) 2004-present, Facebook, Inc.
# All rights reserved.

import asyncio
import json
import logging
import os
import random
import re
import time
import typing
from collections import defaultdict
from datetime import MINYEAR, datetime, timedelta
from distutils.util import strtobool
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

import psutil
from magma.common.sdwatchdog import SDWatchdogTask
from magma.magmad.check.network_check import ping
from marconi.lib import meshquery, wifiproperties
from prometheus_client import REGISTRY, Gauge
from thrift.transport.TTransport import TTransportException
from wifi.protos.mconfig.wifi_mconfigs_pb2 import Linkstatsd as LinkstatsMconfig


TX_BYTES = Gauge("tx_bytes", "bytes sent on the link", ["link"])
RX_BYTES = Gauge("rx_bytes", "bytes received on the link", ["link"])
TX_RETRIED = Gauge("tx_retried_packets", "packets retried", ["link"])
TX_FAILED = Gauge("tx_failed_packets", "packets failed", ["link"])
RX_PACKETS = Gauge("rx_packets", "packets received on the link", ["link"])
RX_DROP_MISC = Gauge("rx_drop_misc", "dropped rx packets", ["link"])
RX_DROP_MISC_PCT = Gauge("rx_drop_misc_pct", "dropped rx packets percentage", ["link"])
TX_LAST_BITRATE = Gauge("tx_last_bitrate", "last tx frame bitrate (Mbps)", ["link"])
RX_LAST_BITRATE = Gauge("rx_last_bitrate", "last rx frame bitrate (Mbps)", ["link"])
EXPECTED_THROUGHPUT = Gauge(
    "expected_throughput", "expected throughput (Mbps)", ["link"]
)
FAIL_AVERAGE = Gauge("fail_average", "tx fail average (pct)", ["link"])
FCS_ERRORS = Gauge("fcs_errors", "mpdus with frame check errors", ["dev"])
RX_MPDUS = Gauge("rx_mpdus", "mpdus received on this device", ["dev"])
INACTIVE_TIME = Gauge("inactive_time", "link inactive time (ms)", ["link"])
SIGNAL = Gauge("signal", "link signal power (dbm)", ["link"])
PING_STATS = Gauge("ping", "ping metrics", ["host", "metric"])
TMPFS_KBS = Gauge("tmpfs_kbs", "tmpfs filesystem size")

ETH0_TX_BYTES = Gauge("eth0_tx_bytes", "bytes sent on eth0")
ETH0_RX_BYTES = Gauge("eth0_rx_bytes", "bytes received on eth0")

WLAN_TX_BYTES = Gauge("wlan_tx_bytes", "total bytes sent on wlan_soma")
WLAN_RX_BYTES = Gauge("wlan_rx_bytes", "total bytes received on wlan_soma")
WLAN_CLIENTS = Gauge("wlan_clients", "total number of clients on wlan_soma")
WLAN_DHCP_LEASES = Gauge("wlan_dhcp_leases", "total number of dhcp leases on wlan_soma")

PEER_COUNT = Gauge("peer_count", "number of mesh0 peers")
PEER_ESTAB_COUNT = Gauge("peer_estab_count", "number of mesh0 peers in estab")

FREQUENCY = Gauge("frequency", "frequency (hz) in use", ["dev"])

RSSI_THRESHOLD = Gauge("rssi_threshold", "RSSI threshold for new peers")

CHANNEL_ACTIVE_TIME = Gauge(
    "channel_active_time", "channel active time (ms) since last read", ["dev"]
)

CHANNEL_BUSY_TIME = Gauge(
    "channel_busy_time", "channel busy time (ms) since last read", ["dev"]
)

CHANNEL_TRANSMIT_TIME = Gauge(
    "channel_transmit_time", "channel transmit time (ms) since last read", ["dev"]
)

CHANNEL_RECEIVE_TIME = Gauge(
    "channel_receive_time", "channel receive time (ms) since last read", ["dev"]
)

CHANNEL_NOISE_LEVEL = Gauge("channel_noise_level", "channel noise level (dBm)", ["dev"])

AIRTIME_METRIC = Gauge("airtime_metric", "802.11s metric to nexthop", ["link"])

TX_QUEUE_BUSY_RATE = Gauge(
    "txq_busy_rate", "Fraction of time that firmware tx queues are non-empty", ["dev"]
)

IMAGE_BUILD_TIME = Gauge("image_build_time", "image build time (epoch)")

IMAGE_METADATA_FILE = "/METADATA"

DROPPED_FRAMES_CONG = Gauge(
    "kernel_dropped_frames_congestion",
    "kernel debug: dropped frames (congestion) on mesh0",
)

DROPPED_FRAMES_NOROUTE = Gauge(
    "kernel_dropped_frames_no_route", "kernel debug: dropped frames( no-route) on mesh0"
)

DROPPED_FRAMES_TTL = Gauge(
    "kernel_dropped_frames_ttl", "kernel debug: dropped frames (ttl) on mesh0"
)

FWDED_MCAST = Gauge(
    "kernel_fwded_mcast", "kernel debug: forwarded multicast frames on mesh0"
)

FWDED_UNICAST = Gauge(
    "kernel_fwded_unicast", "kernel debug: forwarded unicast frames on mesh0"
)

HOPS_TO_GATEWAY = Gauge("ap_hops_to_gateway", "number of hops to gateway")

HOPS_FROM_GATEWAY = Gauge("ap_hops_from_gateway", "number of hops from gateway")

ASYMMETRIC_ROUTE = Gauge(
    "asymmetric_route", "first/last hop to/from gateway is different"
)

METRIC_TO_GATEWAY = Gauge(
    "metric_to_gateway_11s", "a11s shortest path metric to gateway"
)

IPERF_TO_GATE_TRAFFIC = Gauge(
    "iperf_to_gate", "iperf traffic results to gate right now"
)

IPERF_TO_GATE_RESULT = Gauge(
    "iperf_to_gate_result",
    "iperf throughput results to gate, runs from last 24 hours",
    ["agg"],
)

UPTIME = Gauge("uptime", "uptime of the device")

TX_QUEUE_SIZE = Gauge("tx_queue_size", "frames in tx queue", ["queue"])

PERSISTENT_FREE = Gauge("persistent_free_bytes", "free bytes in /persistent")

SERVICE_COUNTERS = Gauge(
    "service_counters",
    "number or systemd service starts in the last sampling period",
    ["starts"],
)

IS_SYSTEM_DEGRADED = Gauge(
    "is_system_degraded", "returns 0 if system is up and running, 1 otherwise"
)

DNS_REQUESTS = Gauge(
    "dns_requests", "number of DNS requests in the last sampling period", ["source"]
)

PROCESS_MEMORY_RSS = Gauge("process_memory_rss", "process RSS", ["process"])

OVERHEAD_PACKETS = Gauge(
    "overhead_packets",
    "Overheads per service (i.e. source of overhead) in packets",
    ["source"],
)

OVERHEAD_BYTES = Gauge(
    "overhead_bytes",
    "Overheads per service (i.e. source of overhead) in bytes",
    ["source"],
)

TTL_EXCEEDED = Gauge(
    "ttl_exceeded", "TTL exceeded messages (minus traceroute and LLMNR)"
)

MESH_HISTOGRAM_PACKETS = Gauge(
    "mesh_packets", "Histogram of packet sizes on the mesh", ["len"]
)

MESH_HISTOGRAM_BYTES = Gauge(
    "mesh_bytes", "Histogram of total bytes per packet size", ["len"]
)

MESH_QOS_PACKETS = Gauge("mesh_qos_packets", "Packet counts per IP QOS level", ["prio"])

MESH_QOS_BYTES = Gauge("mesh_qos_bytes", "Total bytes per IP QOS level", ["prio"])

MESH_PROTOCOL_PACKETS = Gauge(
    "mesh_proto_packets", "Packet counts per protocol", ["proto"]
)

MESH_PROTOCOL_BYTES = Gauge("mesh_proto_bytes", "Total bytes per protocol", ["proto"])

PROCESS_UPTIME = Gauge("process_uptime", "process uptime", ["process"])

GATE_PING_AVG = Gauge("gate_ping_avg", "Gate ping average (ms)", ["prio"])

GATE_PING_P50 = Gauge("gate_ping_p50", "Gate ping median (ms)", ["prio"])

GATE_PING_P90 = Gauge("gate_ping_p90", "Gate ping 90 pctile (ms)", ["prio"])

GATE_PING_P99 = Gauge("gate_ping_p99", "Gate ping 99 pctile (ms)", ["prio"])

GATE_PING_LOSS = Gauge("gate_ping_loss", "Gate ping loss rate", ["prio"])

MESH_STABILITY = Gauge(
    "mesh_stability", "Counts the number of route/peer changes", ["type"]
)

RATE_LIMITING_MSG_CT = Gauge(
    "rate_limiting_message_count", "Rate limiting messages in past 120 seconds"
)

AVG_SIGNAL = Gauge(
    "avg_signal", "signal averaged over samples collected every sec", ["link"]
)

AVG_TX_BITRATE = Gauge(
    "avg_tx_bitrate", "tx_bitrate averaged over samples collected every sec", ["link"]
)

AVG_HIRES_IN_SPEED = Gauge(
    "avg_hires_in_speed", "input speed in B/s averaged across all active sessions"
)

AVG_HIRES_OUT_SPEED = Gauge(
    "avg_hires_out_speed", "output speed in B/s averaged across all active sessions"
)

MIN_HIRES_IN_SPEED = Gauge(
    "min_hires_in_speed", "minimum input speed in B/s across all active sessions"
)

MIN_HIRES_OUT_SPEED = Gauge(
    "min_hires_out_speed", "minimum output speed in B/s across all active sessions"
)

TCP_PKT_RETR_PCT = Gauge(
    "tcp_pkt_retr_pct",
    "percent of sampled TCP packets retransmitted across all connected sessions",
)

TCP_PKT_RETR_PCT_P10 = Gauge(
    "tcp_pkt_retr_pct_p10", "percent of sampled TCP packets retransmitted 10th pctile"
)

TCP_PKT_RETR_PCT_P50 = Gauge(
    "tcp_pkt_retr_pct_p50", "percent of sampled TCP packets retransmitted 50th pctile"
)

TCP_PKT_RETR_PCT_P90 = Gauge(
    "tcp_pkt_retr_pct_p90", "percent of sampled TCP packets retransmitted 90th pctile"
)

TCP_PKT_RETR_PCT_P99 = Gauge(
    "tcp_pkt_retr_pct_p99", "percent of sampled TCP packets retransmitted 99th pctile"
)

COREDUMPS = Gauge("coredumps", "Number of coredumps on a device")

DROP_MONITOR_ACTION = Gauge(
    "drop_monitor_action", "Rate of neighbor drops by the drop-monitor"
)

DROP_MONITOR_PING_FAIL = Gauge(
    "drop_monitor_ping_fail", "Rate of ping fails on nexthop links"
)

DROP_MONITOR_NO_PEER = Gauge(
    "drop_monitor_no_peer", "Rate of non-existent peers on nexthop links"
)

FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_ROUTE_DAMPENER_DEFAULT_ROUTE_DAMPENED_AVG = Gauge(
    "fbmeshd_gateway_connectivity_monitor_route_dampener_default_route_dampened_avg",
    "Default route dampened average over time (s)",
    ["period"],
)

FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_ROUTE_DAMPENER_DEFAULT_ROUTE_HISTORY_AVG = Gauge(
    "fbmeshd_gateway_connectivity_monitor_route_dampener_default_route_history_avg",
    "Default route dampened average over time (s)",
    ["period"],
)

FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_SUCCESS_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_success_sum",
    "Probe WAN connectivity success sum over time (s)",
    ["period"],
)

FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_IN_USE_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_in_use_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_SOCKET_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_socket_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_SETSOCKOPT_REUSEADDR_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_setsockopt_reuseaddr_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_FCNTL_GETFL_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_fcntl_getfl_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_FCNTL_SETFL_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_fcntl_setfl_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_SETSOCKOPT_BINDTODEVICE_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_setsockopt_bindtodevice_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_NOT_EINPROGRESS_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_not_einprogress_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_TIMEOUT_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_timeout_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_GETSOCKOPT_ERROR_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_getsockopt_error_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_ERR_NON_ZERO_SUM = Gauge(
    "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_err_non_zero_sum",
    "Probe WAN connectivity failure sum over time (s)",
    ["period"],
)
CPU_AVG_USAGE_PCT = Gauge(
    "cpu_avg_percent", "System-wide average CPU utilization as a percentage"
)

# Assuming all SoMA internal mesh addresses are in the 172.16.0.0/24 subnet
MESH_PREFIX = "172.16.0"

IPERF_RESULT_PATH = Path("/persistent/last_iperf_result")


class LinkstatsCollector(SDWatchdogTask):
    """
    Periodically polls mesh interfaces for link/network stats
    And if enable_ping flag is set in the config, periodically pings
    list of hosts (set in the config)
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        config: Dict[str, str],
        mconfig: LinkstatsMconfig,
    ) -> None:
        super().__init__(int(config["sampling_period"]), loop)

        self.config = config
        self.mconfig = mconfig

        self.mesh0_hw_addr = ""
        self.mesh0_ipv4 = ""

        # Ping parameters
        self.gateway = ""
        self.gateway_hop_count = 0
        self.external_ping_params = [
            ping.PingCommandParams(
                host, self.mconfig.ping_num_packets, self.mconfig.ping_timeout_secs
            )
            for host in self.mconfig.ping_host_list
        ]

        self._cpu_usage_prev = None
        self._cpu_time_prev = 0.0

        # For each way of determining the nexthop, store
        # MAC address of nexthop on default route, without colons
        self._nexthop_mac_sources: Dict[str, str] = {}

        # Absolute metrics
        # Values of these metrics are set to the values of their corresponding
        # stats
        self._abs_metrics = {
            "tx bitrate": TX_LAST_BITRATE,
            "rx bitrate": RX_LAST_BITRATE,
            "expected throughput": EXPECTED_THROUGHPUT,
            "fail_avg": FAIL_AVERAGE,
            "inactive time": INACTIVE_TIME,
            "signal": SIGNAL,
            "wlan clients": WLAN_CLIENTS,
            "wlan dhcp leases": WLAN_DHCP_LEASES,
            "frequency": FREQUENCY,
            "channel active time": CHANNEL_ACTIVE_TIME,
            "channel busy time": CHANNEL_BUSY_TIME,
            "channel receive time": CHANNEL_RECEIVE_TIME,
            "channel transmit time": CHANNEL_TRANSMIT_TIME,
            "noise": CHANNEL_NOISE_LEVEL,
            "tx queue size": TX_QUEUE_SIZE,
            "rssi_threshold": RSSI_THRESHOLD,
            "is_system_degraded": IS_SYSTEM_DEGRADED,
            "VmRSS": PROCESS_MEMORY_RSS,
            "process_uptime": PROCESS_UPTIME,
            "gate_ping_avg": GATE_PING_AVG,
            "gate_ping_p50": GATE_PING_P50,
            "gate_ping_p90": GATE_PING_P90,
            "gate_ping_p99": GATE_PING_P99,
            "gate_ping_loss": GATE_PING_LOSS,
            "avg_tx_bitrate": AVG_TX_BITRATE,
            "avg_signal": AVG_SIGNAL,
            "rx drop misc pct": RX_DROP_MISC_PCT,
            "tmpfs_kbs": TMPFS_KBS,
            "fbmeshd_gateway_connectivity_monitor_route_dampener_default_route_dampened_avg": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_ROUTE_DAMPENER_DEFAULT_ROUTE_DAMPENED_AVG,
            "fbmeshd_gateway_connectivity_monitor_route_dampener_default_route_history_avg": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_ROUTE_DAMPENER_DEFAULT_ROUTE_HISTORY_AVG,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_success_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_SUCCESS_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_in_use_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_IN_USE_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_socket_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_SOCKET_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_setsockopt_reuseaddr_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_SETSOCKOPT_REUSEADDR_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_fcntl_getfl_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_FCNTL_GETFL_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_fcntl_setfl_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_FCNTL_SETFL_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_setsockopt_bindtodevice_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_SETSOCKOPT_BINDTODEVICE_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_not_einprogress_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_NOT_EINPROGRESS_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_timeout_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_TIMEOUT_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_getsockopt_error_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_GETSOCKOPT_ERROR_SUM,
            "fbmeshd_gateway_connectivity_monitor_probe_wan_connectivity_failed_err_non_zero_sum": FBMESHD_GATEWAY_CONNECTIVITY_MONITOR_PROBE_WAN_CONNECTIVITY_FAILED_ERR_NON_ZERO_SUM,
        }

        # Delta metrics
        # Values of these metrics are set to the differences of consecutive
        # samples' values
        self._delta_metrics = {
            "rx bytes": [RX_BYTES, {}],
            "tx bytes": [TX_BYTES, {}],
            "tx retries": [TX_RETRIED, {}],
            "tx failed": [TX_FAILED, {}],
            "rx packets": [RX_PACKETS, {}],
            "rx drop misc": [RX_DROP_MISC, {}],
            "eth0 tx bytes": [ETH0_TX_BYTES, {}],
            "eth0 rx bytes": [ETH0_RX_BYTES, {}],
            "wlan_soma tx bytes": [WLAN_TX_BYTES, {}],
            "wlan_soma rx bytes": [WLAN_RX_BYTES, {}],
            "txq_busy_rate": [TX_QUEUE_BUSY_RATE, {}],
            "MPDUs delivered to HTT": [RX_MPDUS, {}],
            "MPDU errors (FCS, MIC, ENC)": [FCS_ERRORS, {}],
            "service_counters": [SERVICE_COUNTERS, {}],
            "dns_requests": [DNS_REQUESTS, {}],
            "dropped_frames_congestion": [DROPPED_FRAMES_CONG, {}],
            "dropped_frames_no_route": [DROPPED_FRAMES_NOROUTE, {}],
            "dropped_frames_ttl": [DROPPED_FRAMES_TTL, {}],
            "fwded_unicast": [FWDED_UNICAST, {}],
            "fwded_mcast": [FWDED_MCAST, {}],
            "overhead_packets": [OVERHEAD_PACKETS, {}],
            "overhead_bytes": [OVERHEAD_BYTES, {}],
            "ttl_exceeded": [TTL_EXCEEDED, {}],
            "mesh_packets": [MESH_HISTOGRAM_PACKETS, {}],
            "mesh_bytes": [MESH_HISTOGRAM_BYTES, {}],
            "mesh_qos_packets": [MESH_QOS_PACKETS, {}],
            "mesh_qos_bytes": [MESH_QOS_BYTES, {}],
            "mesh_protocol_packets": [MESH_PROTOCOL_PACKETS, {}],
            "mesh_protocol_bytes": [MESH_PROTOCOL_BYTES, {}],
            "mesh_stability": [MESH_STABILITY, {}],
            "coredumps": [COREDUMPS, {}],
            "drop_monitor_action": [DROP_MONITOR_ACTION, {}],
            "drop_monitor_ping_fail": [DROP_MONITOR_PING_FAIL, {}],
            "drop_monitor_no_peer": [DROP_MONITOR_NO_PEER, {}],
        }

        self._next_iperf = datetime(MINYEAR, 1, 1)
        self._iperf_schedule: List[Tuple[int, int]] = []
        self._iperf_enabled = False

    def _set_nexthop_mac(self, nexthop_mac: str, source_name: str) -> None:
        """
        Save the current value of the nexthop mac address, with no colons.
        Permits multiple ways of determining the nexthop, identified by a name.
        """
        if not nexthop_mac:
            self._nexthop_mac_sources.pop(source_name, None)
            return

        self._nexthop_mac_sources[source_name] = nexthop_mac

    def _get_nexthop_mac(self) -> str:
        """
        If all of the ways of determining the nexthop agree,
        or there is exactly one way of determining the nexthop,
        return the single nexthop mac.

        Otherwise, return an empty string.
        """
        nexthop_values = list(set(self._nexthop_mac_sources.values()))
        if len(nexthop_values) != 1:
            return ""

        return nexthop_values[0]

    def start_collector(self) -> None:
        logging.info("Starting linkstats collector...")

        # List of async stats-collecting functions to be called
        self.function_list = [
            ("_find_gateway", []),
            ("_collect_iw_stats", ["mesh0"]),
            ("_collect_iw_stats", ["wlan_soma"]),
            ("_collect_ifconfig_stats", ["eth0"]),
            ("_collect_ifconfig_stats", ["wlan_soma"]),
            ("_collect_mpath_stats", ["mesh0"]),
            ("_collect_channel_stats", ["wlan_soma"]),
            ("_collect_channel_stats", ["mesh0"]),
            ("_collect_ping_stats", []),
            ("_collect_iperf_stats", []),
            ("_collect_uptime", []),
            ("_collect_queue_stats", []),
            ("_collect_chilli_query_stats", []),
            ("_collect_persistent_stats", []),
            ("_collect_kernel_meshconf_stats", []),
            ("_collect_ath10k_queue_stats", ["mesh0"]),
            ("_collect_ath10k_queue_stats", ["wlan_soma"]),
            ("_collect_ath10k_fw_stats", ["mesh0"]),
            ("_collect_ath10k_fw_stats", ["wlan_soma"]),
            ("_collect_debugfs_sta_stats", []),
            ("_collect_service_counters", []),
            ("_collect_is_system_running", []),
            ("_collect_dns_requests", []),
            ("_collect_process_stats", ["ap_id"]),
            ("_collect_process_stats", ["fbmeshd"]),
            ("_collect_process_stats", ["linkstatsd"]),
            ("_collect_process_stats", ["logtailer"]),
            ("_collect_process_stats", ["magmad"]),
            ("_collect_process_stats", ["mesh_monitor"]),
            ("_collect_process_stats", ["overhead_analyzer"]),
            ("_collect_process_stats", ["ping_stats"]),
            ("_collect_process_stats", ["radius_http_proxy"]),
            ("_collect_process_stats", ["validate-image"]),
            ("_collect_overhead_stats", []),
            ("_collect_traffic_stats", []),
            ("_export_iperf_results", []),
            ("_collect_gate_ping_stats", []),
            ("_collect_rate_limit_ct", []),
            ("_collect_high_res_stats", []),
            ("_collect_coredumps_stats", []),
            ("_collect_drop_monitor_stats", []),
            ("_collect_fbmeshd_stats", []),
            ("_collect_user_experience_stats", []),
            ("_collect_tmpfs_stats", []),
            ("_collect_cpu_stats", []),
        ]
        self.set_image_build_time()
        self.start()

    async def _run(self) -> None:
        # Get mesh0 interface ip/mac addresses
        # It can change during runtime, so reparse every loop
        self.mesh0_hw_addr, self.mesh0_ipv4 = await self._get_iface_info("mesh0")
        self._collect_kernel_mesh_stats()
        await asyncio.wait(
            [getattr(self, name)(*arg) for name, arg in self.function_list]
        )
        # TODO - this changes the sampling rate based on how long it takes
        # to do stats, should record duration here

    async def run_command(self, cmd: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8")

    async def _get_iface_info(self, iface: str) -> Tuple[str, str]:
        stdout = await self.run_command("ip addr show " + iface)
        hw_addr, ipv4 = "", ""
        for line in stdout.split("\n"):
            line = line.lstrip()
            if line.startswith("link/ether"):
                hw_addr = line.split()[1]
            elif line.startswith("inet "):
                ipv4 = line.split()[1].split("/")[0]

        return hw_addr, ipv4

    def set_image_build_time(self) -> None:
        with open(IMAGE_METADATA_FILE) as metadata:
            for line in metadata:
                if line.startswith("build-time-epoch"):
                    IMAGE_BUILD_TIME.set(line.split()[1])
                    return
        logging.warning("cannot find image build time from config")
        IMAGE_BUILD_TIME.set(0)

    def _parse_mesh0_station_dump(self, out_str: str) -> None:
        """
        link stats are collected by running the command
        iw dev mesh0 station dump

        output is a list of existing stations' info, formatted as below:
        (some fields are omitted in this example)

        Station 42:00:00:00:01:00 (on mesh0)
        inactive time:  891 ms
        rx bytes:   388367
        rx packets: 5235
        tx bytes:   6441
        tx packets: 46
        tx retries: 0
        tx failed:  0
        signal:     -33 dBm
        Toffset:    0 us
        tx bitrate: 26.0 MBit/s MCS 3
        rx bitrate: 54.0 MBit/s MCS 3 40MHz
        expected throughput:    81.250Mbps
        fail average: 0
        authorized: yes
        authenticated:  yes
        preamble:   long
        connected time: 2637 seconds

        Records number of stations, number of estab stations,
        and the above statistics for the nexthop
        """
        rx_pkt_rate = {}
        rx_drop_rate = {}
        stats, station_count, estab_count = _build_mesh0_stats_map(out_str)
        agg_stats: DefaultDict[str, List[float]] = defaultdict(list)
        for metric_name, link_stats in stats.items():
            for link, metric_value in link_stats.items():
                res = self._update_metrics(metric_name, metric_value, link, True)
                if res:
                    agg_stats[metric_name].append(res)
                    if metric_name == "rx packets":
                        rx_pkt_rate[link] = res
                    elif metric_name == "rx drop misc":
                        rx_drop_rate[link] = res
            self._update_nexthop_metric(metric_name, link_stats)

        metric_name = "rx drop misc pct"
        rx_drop_rate_pct = {}
        for link in rx_pkt_rate:
            metric_value = 0
            if rx_pkt_rate[link] > 10 and link in rx_drop_rate:
                metric_value = rx_drop_rate[link] / rx_pkt_rate[link]
            res = self._update_metrics(metric_name, metric_value, link, True)
            if res:
                rx_drop_rate_pct[link] = res
                agg_stats[metric_name].append(res)
        self._update_nexthop_metric(metric_name, rx_drop_rate_pct)

        PEER_COUNT.set(station_count)
        PEER_ESTAB_COUNT.set(estab_count)

        for key, vals in agg_stats.items():
            self._update_aggregate_metrics(key, sum(vals), "sum")
            self._update_aggregate_metrics(key, sum(vals) / len(vals), "avg")
            self._update_aggregate_metrics(key, max(vals), "max")
            self._update_aggregate_metrics(key, min(vals), "min")

    def _update_nexthop_metric(
        self, metric_name: str, link_stats: Dict[str, float]
    ) -> None:
        """
        Update given link metric, by name, if the nexthop exists
        and the stat is valid. Otherwise, delete the metrics

        link_stats is a map {device_mac: metric_value}
        """
        nexthop_mac = self._get_nexthop_mac()
        if nexthop_mac and nexthop_mac in link_stats:
            self._update_metrics(metric_name, link_stats[nexthop_mac], "nexthop")
            return

        self._delete_metrics(metric_name, "nexthop")

    def _set_nexthop_metric(self, metric: Any, link_stats: Dict[str, float]) -> None:
        """
        Update the given link metric (a Gauge) if the nexthop exists
        and the stat is valid. Otherwise, delete the metrics

        link_stats is a map {device_mac: metric_value}
        """
        nexthop_mac = self._get_nexthop_mac()
        if nexthop_mac and nexthop_mac in link_stats:
            metric.labels("nexthop").set(link_stats[nexthop_mac])
            return

        try:
            metric.remove("nexthop")
        except KeyError:
            # Suppress the label does not exist error
            pass

    def _parse_wlan_soma_station_dump(self, out_str: str) -> None:
        stations = 0
        for station in out_str.split("Station"):
            if not station:
                continue
            stations += 1
        self._abs_metrics["wlan clients"].set(stations)

    def _parse_chilli_query_dhcp_list(self, s: str) -> None:
        """
        a8:a1:98:a8:e8:1e 172.16.120.200 tc_based 12/600
        58:c5:83:e9:49:1c 172.16.120.199 tc_based 28/600
        00:99:f4:97:98:af 172.16.120.193 tc_based 159/600
        08:86:20:e2:58:83 172.16.120.190 tc_based 1/600
        """
        if len(s.strip()) == 0:
            return

        count = 0

        for line in s.split("\n"):
            line = line.strip()
            if line == "":
                continue
            fields = line.split()

            if len(fields) == 4:
                count += 1

        self._abs_metrics["wlan dhcp leases"].set(count)

    def _parse_survey_dump(self, out_str: str, dev: str) -> None:
        """
        iw dev mesh0 survey dump
        Survey data from mesh0
            frequency:          5785 MHz
        Survey data from mesh0
            frequency:          5805 MHz [in use]
            noise:              -107 dBm
            channel active time:        1000 ms
            channel busy time:      124 ms
            channel receive time:       5 ms
            channel transmit time:      0 ms
        """
        for survey in out_str.split("Survey data from " + dev):
            if "in use" not in survey:
                continue
            for line in survey.split("\n"):
                fields = line.lstrip().split(":")
                if len(fields) < 2:
                    continue
                key = fields[0]
                value = fields[1].split()[0]
                if value:
                    self._update_metrics(key, float(value), dev)
            # Only one frequency should be in use.
            # so if we're here, we're done.

            return

    def _update_aggregate_metrics(self, key: str, value: float, agg: str) -> None:
        if key in self._abs_metrics.keys():
            self._abs_metrics[key].labels(agg).set(value)
        elif key in self._delta_metrics.keys():
            self._delta_metrics[key][0].labels(agg).set(value)

    def _update_metrics(
        self, key: str, value: float, label: str = "", hidden: bool = False
    ) -> Optional[float]:
        """
        Updates the given metric and returns the exported value
        (or None if no value is exported)
        """
        if key in self._abs_metrics.keys():
            if not hidden:
                if label:
                    self._abs_metrics[key].labels(label).set(value)
                else:
                    self._abs_metrics[key].set(value)
            return value
        elif key in self._delta_metrics.keys():
            current_time = time.monotonic()
            prev_time = self._delta_metrics[key][1].get(label + "_time", current_time)
            self._delta_metrics[key][1][label + "_time"] = current_time
            prev_value = self._delta_metrics[key][1].get(label + "_value", value)
            self._delta_metrics[key][1][label + "_value"] = value
            value_diff = value - prev_value
            time_diff = current_time - prev_time
            if time_diff <= 0 or value_diff < 0:
                return None
            rate: float = value_diff / time_diff
            if not hidden:
                if label:
                    self._delta_metrics[key][0].labels(label).set(rate)
                else:
                    self._delta_metrics[key][0].set(rate)
            return rate
        return None

    def _delete_metrics(self, key: str, label: str) -> None:
        """
        Deletes the metric so it is not reported to ODS. Only works with metrics
        that have labels.
        """
        if not label:
            logging.error("Cannot delete a metric without a label")
            return
        try:
            if key in self._abs_metrics.keys():
                self._abs_metrics[key].remove(label)
            elif key in self._delta_metrics.keys():
                self._delta_metrics[key][0].remove(label)
        except KeyError:
            # Suppress the label does not exist error
            pass

    def _parse_mpath_dump(self, out_str: str) -> None:
        """
        Path information is obtained by running the command
        iw dev mesh0 mpath dump

        DEST ADDR          NEXT HOP           IFACE   SN  METRIC
        60:31:97:33:a2:fa  60:31:97:33:a2:fa  mesh0   10  22
        """
        # Reset existing path_metric values
        for metric in REGISTRY.collect():
            if metric.name == "airtime_metric":
                for sample in metric.samples:
                    AIRTIME_METRIC.labels(sample[1]["link"]).set(0)

        link_stats: Dict[str, float] = {}
        # Set new path_metric values
        for line in out_str.split("\n"):
            fields = line.split()
            if len(fields) < 5 or fields[2] != "mesh0":
                continue
            dst = fields[0].replace(":", "")
            nexthop = fields[1].replace(":", "")
            # We set ttl to 1, so dst should be the same as nexthop
            if dst != nexthop:
                logging.warning(
                    "802.11s dst %s and nexthop %s don't match", dst, nexthop
                )
                continue
            metric_value = int(fields[4])
            link = dst.lower()
            AIRTIME_METRIC.labels(link).set(metric_value)
            link_stats[link] = metric_value

        self._set_nexthop_metric(AIRTIME_METRIC, link_stats)

        vals = link_stats.values()
        if vals:
            AIRTIME_METRIC.labels("sum").set(sum(vals))
            AIRTIME_METRIC.labels("avg").set(sum(vals) / len(vals))
            AIRTIME_METRIC.labels("min").set(min(vals))
            AIRTIME_METRIC.labels("max").set(max(vals))

    async def _collect_mpath_stats(self, dev: str) -> None:
        stdout = await self.run_command("iw dev " + dev + " mpath dump")
        self._parse_mpath_dump(stdout)

    async def _collect_iw_stats(self, dev: str) -> None:
        stdout = await self.run_command("iw dev " + dev + " station dump")
        parse_func = getattr(self, "_parse_" + dev + "_station_dump")
        parse_func(stdout)

    async def _collect_chilli_query_stats(self) -> None:
        stdout = await self.run_command("chilli_query dhcp-list")
        parse_func = self._parse_chilli_query_dhcp_list
        parse_func(stdout)

    async def _collect_channel_stats(self, dev: str) -> None:
        stdout = await self.run_command("iw dev " + dev + " survey dump")
        self._parse_survey_dump(stdout, dev)

    async def _collect_kernel_meshconf_stats(self) -> None:
        for root, _dirs, files in os.walk(
            "/sys/kernel/debug/ieee80211/phy0/netdev:mesh0/mesh_config"
        ):
            for key in files:
                if key not in self._abs_metrics.keys():
                    continue
                with open(root + "/" + key) as f:
                    value = f.read()
                self._abs_metrics[key].set(value)

    def _collect_kernel_mesh_stats(self) -> None:
        for root, _dirs, files in os.walk(
            "/sys/kernel/debug/ieee80211/phy0/netdev:mesh0/mesh_stats"
        ):
            for key in files:
                with open(root + "/" + key) as f:
                    value = f.read()
                self._update_metrics(key, float(value))

    async def _collect_debugfs_sta_stats(self) -> None:
        for root, _dirs, files in os.walk(
            "/sys/kernel/debug/ieee80211/phy0/netdev:mesh0/stations"
        ):
            station_hw_addr = os.path.basename(root)
            link = station_hw_addr.replace(":", "").lower()
            for key in files:
                if key not in self._abs_metrics.keys():
                    continue
                with open(root + "/" + key) as f:
                    value = f.read()
                self._update_metrics(key, float(value), link)

    async def _collect_ifconfig_stats(self, interface: str) -> None:
        cmd = "ifconfig " + interface + " | grep 'bytes' | awk '{print $2, $6}'"
        stdout = await self.run_command(cmd)
        keys = [interface + " rx bytes", interface + " tx bytes"]
        values = stdout.split()
        d = dict(zip(keys, values))
        for key in d:
            # value is formatted as 'bytes:1234'
            value = d[key].split(":")[1]
            self._update_metrics(key, float(value))

    async def _pid_of(self, process_pattern: str) -> Optional[int]:
        cmd = "pgrep -f " + process_pattern
        stdout = await self.run_command(cmd)
        if not stdout.strip().isdigit():
            return None
        return int(stdout.strip())

    async def _collect_coredumps_stats(self) -> None:
        # ls ignores files starts with .
        cmd = "ls -1 /var/lib/systemd/coredump/*.xz | wc -l"
        stdout = await self.run_command(cmd)

        self._update_metrics("coredumps", float(stdout))

    async def _collect_drop_monitor_stats(self) -> None:
        try:
            cnt = int(Path("/var/run/drop_monitor_count").read_text())
        except (FileNotFoundError, ValueError):
            cnt = 0
        self._update_metrics("drop_monitor_action", cnt)

        try:
            cnt = int(Path("/var/run/drop_nexthop_count").read_text())
        except (FileNotFoundError, ValueError):
            cnt = 0
        self._update_metrics("drop_monitor_ping_fail", cnt)

        try:
            cnt = int(Path("/var/run/oops_nexthop_count").read_text())
        except (FileNotFoundError, ValueError):
            cnt = 0
        self._update_metrics("drop_monitor_no_peer", cnt)

    async def _collect_process_stats(self, process_name: str) -> None:
        rss_key = "VmRSS"
        pid = await self._pid_of(process_name)
        if pid:
            try:
                with open("/proc/" + str(pid) + "/status", "r") as status:
                    for l in status.readlines():
                        if not l.startswith(rss_key):
                            continue
                        key, value_str = l.split("\t")

                        key = key[:-1]
                        # value is always in kB
                        value_str = re.sub("[^-.0-9]", "", value_str)
                        value = float(value_str) * 1024.0

                        self._update_metrics(key, value, process_name)
            except IOError as e:
                logging.warning(
                    "could not get stats for process %s: %s", process_name, e
                )
                self._update_metrics(rss_key, 0, process_name)

            try:
                process = psutil.Process(pid)
                uptime = time.time() - process.create_time()

                self._update_metrics("process_uptime", uptime, process_name)
            except psutil.Error as e:
                logging.warning(
                    "could not get stats for process %s: %s", process_name, e
                )
                self._update_metrics("process_uptime", 0, process_name)
        else:
            # no pid or no status file, set defaults
            self._update_metrics(rss_key, 0, process_name)
            self._update_metrics("process_uptime", 0, process_name)

    async def _find_gateway(self) -> None:
        """
        Gateway_ping tool can be used to determine each AP's gateway and hop
        counts to and from gateway.

        example output:
        Gateway IP	    RTT(ms)		Hops-to		Hops-from	Asymm
        172.16.0.242	10.73		1		    1	       	0
        -------
        We may be using IPv6. Check for that by parsing output of:
        /sbin/ip -6 route show fd00:ffff::/96

        example output (when using IPv6):
        fd00:ffff::/96 via fe80::8e59:73ff:fefc:a6ee dev mesh0 proto 98 metric 1024 pref medium

        or (on a gate):
        fd00:ffff::/96 dev tayga proto 98 metric 1024 pref medium
        """
        # Check if we are using IPv6
        stdout = await self.run_command("/sbin/ip -6 route show fd00:ffff::/96")
        fields = stdout.split("\n")[0].split()
        if len(fields) > 0 and fields[0].strip() == "fd00:ffff::/96":
            # We are using IPv6, run gateway_ping6
            gateway_ping_binary = "/usr/local/bin/gateway_ping6"
            if fields[1] == "via":
                # we are not a gateway, set nexthop
                self._set_nexthop_mac(_ipv6_to_mac(fields[2]), "a12s")
            else:
                # we are a gateway, remove nexthop
                self._set_nexthop_mac("", "a12s")
        else:
            # We are using IPv4, so run gateway_ping to find the gate
            gateway_ping_binary = "/usr/local/bin/gateway_ping"
            self._set_nexthop_mac("", "a12s")

        stdout = await self.run_command(gateway_ping_binary)
        lines = stdout.split("\n")
        if len(lines) < 2:
            logging.warning("failed to parse gateway_ping output")
            return

        fields = lines[1].split()
        if len(fields) < 5:
            logging.warning("failed to parse gateway_ping fields")
            return

        if fields[0] == "0.0.0.0" or fields[0] == "::":
            self.gateway = ""
        else:
            self.gateway = fields[0]

        try:
            hops_to = int(fields[2])
            hops_from = int(fields[3])
            asymm = int(fields[4])
        except ValueError:
            logging.warning("failed to parse hop counts from gateway_ping")
            return

        # If one of the hop counts is more than 2x the other, assume it's a
        # transient routing loop and filter it out.
        if hops_to > 2 * hops_from:
            hops_to = hops_from
        if hops_from > 2 * hops_to:
            hops_from = hops_to

        self.gateway_hop_count = hops_to
        HOPS_TO_GATEWAY.set(hops_to)
        HOPS_FROM_GATEWAY.set(hops_from)
        ASYMMETRIC_ROUTE.set(asymm)

    async def _collect_uptime(self) -> None:
        with open("/proc/uptime", "r") as up:
            uptime = up.read()
        # format is "<uptime secs> <idle time secs>\n"
        t = float(uptime.partition(" ")[0])
        UPTIME.set(t)

    def _config_iperf(self) -> None:
        """
        Try to read the following from wifiproperties.json:

        iperf_enabled: "1",
        iperf_interval_mins: "10",
        iperf_schedule: "7-14,18-21"

        In case of failure, assume reasonable defaults.
        """
        wifi_config = wifiproperties.read_wifiproperties_from_magma()

        if "iperf_enabled" in wifi_config:
            self._iperf_enabled = bool(strtobool(wifi_config["iperf_enabled"]))
        else:
            self._iperf_enabled = False

        # Pre-set interval to a valid default in case parsing fails
        interval = 60
        try:
            if "iperf_interval_mins" in wifi_config:
                interval = max(int(wifi_config["iperf_interval_mins"]), 10)
        except ValueError:
            pass
        self._iperf_interval_mins = interval

        if "iperf_schedule" in wifi_config:
            schedule = wifi_config["iperf_schedule"]
        else:
            # if no schedule given, assume service runs continuously
            schedule = "0-24"

        try:
            intervals = [i.split("-") for i in schedule.replace(" ", "").split(",")]
            self._iperf_schedule = [(int(i[0]), int(i[1])) for i in intervals]
        except Exception:
            logging.warning("Miscontructed iperf schedule string: {}".format(schedule))
            # if schedule is unparsable, make no assumptions and fail shut
            self._iperf_enabled = False
            self._iperf_schedule = []

        logging.debug("iperf enabled: %s", self._iperf_enabled)
        logging.debug("iperf interval: %d min", self._iperf_interval_mins)
        logging.debug("iperf schedule: %s", self._iperf_schedule)

    def _parse_iperf(self, stdout: str) -> None:
        """Parse iperf json output"""
        try:
            iperf = json.loads(stdout)
            throughput = float(iperf["end"]["sum_sent"]["bits_per_second"]) / 1.0e6
        except Exception:
            # Something bad happened, probably iperf server busy: abort iperf
            # and retry sooner than the full interval
            random.seed(self.mesh0_ipv4)
            next_try = max(1, 0.2 * random.random() * self._iperf_interval_mins)
            self._next_iperf = datetime.now() + timedelta(minutes=next_try)
            logging.info("iperf aborted.  Will retry in %2.2f minutes", next_try)
            return
        IPERF_TO_GATE_TRAFFIC.set(throughput)
        logging.info("iperf reported %f Mbps to gate", throughput)
        store_last_iperf_result(throughput)

        self._next_iperf = datetime.now() + timedelta(minutes=self._iperf_interval_mins)

    def _iperf_should_run(self) -> bool:

        # we are the gateway, or we don't know the gateway yet
        if not self._iperf_enabled or self.gateway in ("", self.mesh0_ipv4):
            return False

        now = datetime.now()

        if not any(t[0] <= now.hour < t[1] for t in self._iperf_schedule):
            return False

        if now < self._next_iperf:
            return False

        return True

    async def _collect_iperf_stats(self) -> None:
        """
        Run iperf3 to gate every hour and report results

        This only runs on non-gate nodes
        """

        self._config_iperf()

        if not self._iperf_should_run():
            IPERF_TO_GATE_TRAFFIC.set(0)
            return

        cmd = (
            "/usr/bin/iperf3 -c "
            + self.gateway
            + " -p 12346"
            + " -i 10"
            + " -O 2"
            + " --json"
        )

        stdout = await self.run_command(cmd)
        self._parse_iperf(stdout)

    async def _export_iperf_results(self) -> None:
        """Returns the best iperf result from recent runs"""
        results = [value for _time, value in get_iperf_results()] or [0.0]
        last = results[-1]  # Record most recent before shuffling
        results.sort()  # To make min/max/p50 slightly easier to find
        if self.gateway:
            IPERF_TO_GATE_RESULT.labels("max").set(results[-1])
            IPERF_TO_GATE_RESULT.labels("min").set(results[0])
            IPERF_TO_GATE_RESULT.labels("avg").set(sum(results) / len(results))
            IPERF_TO_GATE_RESULT.labels("p50").set(results[len(results) // 2])
            IPERF_TO_GATE_RESULT.labels("count").set(len(results))
            IPERF_TO_GATE_RESULT.labels("last").set(last)
        else:
            try:
                IPERF_TO_GATE_RESULT.remove("max")
                IPERF_TO_GATE_RESULT.remove("min")
                IPERF_TO_GATE_RESULT.remove("avg")
                IPERF_TO_GATE_RESULT.remove("p50")
                IPERF_TO_GATE_RESULT.remove("count")
                IPERF_TO_GATE_RESULT.remove("last")
            except KeyError:
                # Couldn't find the label (i.e. doesn't exist)
                pass

    def _parse_queues(self, stdout: str) -> None:
        """
        Parse tx queue sizes

        00: 0x00000000/348
        01: 0x00000000/0
        02: 0x00000000/0
        03: 0x00000000/0
        04: 0x00000000/0
        05: 0x00000000/0
        06: 0x00000000/0
        07: 0x00000000/0
        08: 0x00000000/0
        09: 0x00000000/0
        10: 0x00000000/0
        11: 0x00000000/0
        12: 0x00000000/0
        13: 0x00000000/0
        14: 0x00000000/0
        15: 0x00000000/0
        """

        try:
            for queue in stdout.split("\n"):
                if not queue:
                    continue
                queue_id = queue.split(":")[0]
                queue_size = int(queue.split("/")[-1])
                TX_QUEUE_SIZE.labels(queue_id).set(queue_size)
        except Exception:
            # Something went bottoms up, no point in even trying for remaining
            # queues; log the response we got so we can maybe debug later
            logging.exception(
                "Could not parse mac80211 queue file. Contents:\n%s\n%s",
                stdout,
                "----------------------------------------",
            )

    async def _collect_queue_stats(self) -> None:
        """Get tx queue sizes for mac80211"""

        file_name = "/sys/kernel/debug/ieee80211/phy0/queues"
        with open(file_name) as f:
            content = f.read()
        self._parse_queues(content)

    def _get_ath10k_debugfs_phy_dir(self, dev: str) -> Optional[str]:
        if dev == "mesh0":
            phy = "phy0"
        elif dev == "wlan_soma":
            phy = "phy1"
        else:
            logging.warning("Unknown device: %s", dev)
            return None

        return "/sys/kernel/debug/ieee80211/" + phy + "/ath10k/"

    def _parse_ath10k_queues(self, stdout: str, dev: str) -> None:
        """Parse the ath10k firmware queue stats

        mode:           push-pull
        type:           bytes
        peers:          528
        tids:           8
        pending:        0 (0 allowed)
        pending_tx_us:  17913740
        """

        try:
            for line in stdout.split("\n"):
                kv = line.split(":", 1)
                if "pending_tx_us" in kv[0].lower():
                    value = float(kv[1].strip()) / 1e6
                    self._update_metrics("txq_busy_rate", value, dev)
        except Exception:
            logging.exception(
                "Could not parse ath10k/firmware queue file. Contents:\n%s\n%s",
                stdout,
                "----------------------------------------",
            )

    def _parse_ath10k_fw_stats(self, stdout: str, dev: str) -> None:
        """Parse the ath10k fw_stats file.  Example:

             ath10k PDEV stats
             =================

           Channel noise floor       -110
              Channel TX power         58
                TX frame count  589379243
                RX frame count 4206646219
                RX clear count 2370998966
                   Cycle count 2986209818
               PHY error count        443
                 RTS bad count          0
                RTS good count          6
                 FCS bad count       7746
               No beacon count       8644
                 MIB int count          0
           [...]
        """

        try:
            for line in stdout.split("\n"):
                kv = line.rsplit(" ", 1)
                if len(kv) != 2:
                    continue

                key = kv[0].strip()
                value = re.sub("[^-.0-9]", "", kv[1])
                if key and value and key in self._delta_metrics.keys():
                    self._update_metrics(key, float(value), dev)

        except Exception:
            logging.exception(
                "Could not parse ath10k/fw_stats file. Contents:\n%s\n%s",
                stdout,
                "----------------------------------------",
            )

    async def _collect_ath10k_queue_stats(self, dev: str) -> None:
        """Get tx queue stats from ath10k/firmware"""

        phydir = self._get_ath10k_debugfs_phy_dir(dev)
        if not phydir:
            return

        file_name = phydir + "queues"
        if not os.path.exists(file_name):
            logging.warning("file not exist: %s", file_name)
            return
        with open(file_name) as f:
            content = f.read()
        self._parse_ath10k_queues(content, dev)

    async def _collect_ath10k_fw_stats(self, dev: str) -> None:
        """Get stats from ath10k fw_stats file"""
        try:
            phydir = self._get_ath10k_debugfs_phy_dir(dev)
            if not phydir:
                return

            file_name = phydir + "fw_stats"
            if not os.path.exists(file_name):
                logging.warning("file not exist: %s", file_name)
                return
            with open(file_name) as f:
                content = f.read()
            self._parse_ath10k_fw_stats(content, dev)
        except OSError as e:
            logging.error("failed to collect ath10k fw stats: %s", e)

    async def _collect_ping_stats(self) -> None:
        """Ping external configured hosts and gateway"""

        def record(host: str, result: Any) -> None:
            if result.error:
                logging.debug("Failed to ping %s with error: %s", host, result.error)
                return
            stats = result.stats
            PING_STATS.labels(host=host, metric="rtt_ms").set(stats.rtt_avg)
            PING_STATS.labels(host=host, metric="loss").set(
                1 - (stats.packets_received / max(1, stats.packets_transmitted))
            )

            logging.debug(
                "Pinged %s with %d packet(s). Average RTT ms: %s",
                result.host_or_ip,
                result.num_packets,
                stats.rtt_avg,
            )

        ext_ping_results = await ping.ping_async(self.external_ping_params)
        for result in ext_ping_results:
            record(result.host_or_ip, result)

        if self.gateway_hop_count and self.gateway:
            # Technically, we already have the rtt from doing the traceroute,
            # but who's counting
            gw_ping_results = await ping.ping_async(
                [ping.PingCommandParams(self.gateway, num_packets=2, timeout_secs=3)]
            )
            for result in gw_ping_results:
                record("gateway", result)
        else:
            # This device is a gateway/we don't know the gateway.
            # Don't populate misleading stats, so remove gateway counters
            try:
                PING_STATS.remove("gateway", "rtt_ms")
                PING_STATS.remove("gateway", "loss")
            except KeyError:
                pass  # Never got a chance to bump

    async def _collect_persistent_stats(self) -> None:
        stdout = await self.run_command("/bin/stat -f /persistent -c %S,%a")

        # 1024,204185
        info = stdout.split(",")
        if len(info) != 2:
            return
        block_size, free_blocks = info
        persistent_free = int(block_size) * int(free_blocks)
        PERSISTENT_FREE.set(persistent_free)

    async def _collect_service_counters(self) -> None:
        root = Path("/run/service_counters/")
        for p in root.iterdir():
            if p.name.endswith("_starts"):
                service = p.name[: -len("_starts")]
                try:
                    counter = int(p.read_text())
                except ValueError:
                    counter = 0
                self._update_metrics("service_counters", counter, service)

    async def _collect_is_system_running(self) -> None:
        stdout = await self.run_command("/bin/systemctl is-system-running")
        # This keeps track of "degraded" systems to make it easier to notice
        # APs in trouble and write alarms
        if stdout.strip() == "running":
            self._update_metrics("is_system_degraded", 0)
        else:
            self._update_metrics("is_system_degraded", 1)

    async def _collect_dns_requests(self) -> None:
        """
        Parse iptables output and log dns counters to ODS:

        Chain LOGGING (2 references)
        pkts bytes target     prot opt in     out     source               destination
         46  3032 RETURN     udp  --  *      *       172.17.0.0/16        0.0.0.0/0            udp dpt:53
        126 10330 RETURN     udp  --  *      *      !172.17.0.0/16        0.0.0.0/0            udp dpt:53
        """
        stdout = await self.run_command(
            "/usr/sbin/iptables -w -t nat -L LOGGING-DNS -nv"
        )
        for line in stdout.split("\n"):
            elems = line.split()
            if len(elems) < 8:
                continue
            try:
                counter = int(elems[0])
            except ValueError:
                counter = 0
            if elems[7] == "!172.17.0.0/16":
                self._update_metrics("dns_requests", counter, "ap")
            elif elems[7] == "172.17.0.0/16":
                self._update_metrics("dns_requests", counter, "client")

    async def _collect_overhead_stats(self) -> None:
        """
        Parse /var/run/traffic_overhead_summary output and log to ODS:

        root@5ce28cf1abce:~# cat /var/run/traffic_overhead_query
        mesh_kvstore        3       753
        mesh_magma_to       0         0
        mesh_magma_from    20      6042
        mesh_graphapi       0         0
        mesh_vpn          820   1229564
        mesh_icmp           2       196
        wlan_kvstore        3       753
        wlan_magma_to       0         0
        wlan_magma_from    20      6042
        wlan_graphapi       0         0
        wlan_vpn          820   1229564
        wlan_icmp           2       196
        ttlexc              0         0
        """
        # I realize it seems dumb to cat a file in a subprocess instead of just
        # reading it. But, this file is a FIFO and the other side can take
        # a while to answer. So, I want to use asyncio and a timeout for this,
        # and there doesn't seem to be support for this in asyncio
        try:
            stdout = await asyncio.wait_for(
                self.run_command("/bin/cat /var/run/traffic_overhead_summary"),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logging.warning("Reading /var/run/traffic_overhead_summary timed out")
            return

        for line in stdout.split("\n"):
            elems = line.split()
            if len(elems) < 3:
                continue

            src = elems[0]
            try:
                pkts = int(elems[1])
                bytes = int(elems[2])
            except ValueError:
                pkts = 0
                bytes = 0

            if src == "ttlexc":
                self._update_metrics("ttl_exceeded", pkts)
            else:
                self._update_metrics("overhead_packets", pkts, src)
                self._update_metrics("overhead_bytes", bytes, src)

    async def _collect_traffic_stats(self) -> None:
        """
        Parse /var/run/mesh_traffic_stats output and log to ODS:

        root@5ce28cf1abce:~# cat /var/run/mesh_traffic_stats
        len_0-63	           1	          42
        len_64-127	        2532	      297242
        len_128-255	          34	        7466
        len_256-511	           0	           0
        len_512-1023          11	        7957
        len_1024-1535         22	       33308
        len_1536-inf           0	           0
        tos_0		          85	       45841
        tos_1		           0	           0
        tos_2		           0	           0
        tos_3		         570	       67260
        tos_4		           0	           0
        tos_5		           0	           0
        tos_6		          27	        6666
        tos_7		        1917	      226206
        proto_tcp          76704       112072574
        proto_udp           1317          106176
        proto_other         2778          254000
        """
        # Read a fifo using asyncio and a timeout of 5 seconds
        try:
            stdout = await asyncio.wait_for(
                self.run_command("/bin/cat /var/run/mesh_traffic_stats"), timeout=5.0
            )
        except asyncio.TimeoutError:
            logging.warning("Reading /var/run/mesh_traffic_stats timed out")
            return

        for line in stdout.split("\n"):
            elems = line.split()
            if len(elems) < 3:
                continue

            key, _, label = elems[0].partition("_")
            if not label:
                continue
            try:
                pkts = int(elems[1])
                bytes = int(elems[2])
            except ValueError:
                pkts = 0
                bytes = 0

            if key == "len":
                self._update_metrics("mesh_packets", pkts, label)
                self._update_metrics("mesh_bytes", bytes, label)
            elif key == "tos":
                self._update_metrics("mesh_qos_packets", pkts, label)
                self._update_metrics("mesh_qos_bytes", bytes, label)
            elif key == "proto":
                self._update_metrics("mesh_protocol_packets", pkts, label)
                self._update_metrics("mesh_protocol_bytes", bytes, label)

    async def _collect_gate_ping_stats(self) -> None:
        """
        Parse /var/run/ping_stats_summary output and log to ODS:

        root@5ce28cf1abae:~# cat /run/ping_stats_summary
        qos_0         4.59    2.84    6.32   16.32    0.00    13
        qos_1         4.56    3.36    6.41   16.41    0.00    14
        qos_2         5.12    3.87    9.57   19.57    0.00    14
        qos_3         7.39    3.57   14.20   24.20    0.00    14
        qos_4         5.55    3.51    7.75   17.75    0.00    14
        qos_5         4.01    3.74    5.50   15.50    0.00    14
        qos_6         3.79    3.10    5.97   15.97    0.00    14
        qos_7         3.90    2.89    8.73   18.73    0.00    13
        qos_all       4.87    3.33    8.40   18.40    0.00   110
        """
        # Read a fifo using asyncio and a timeout of 5 seconds
        try:
            stdout = await asyncio.wait_for(
                self.run_command("/bin/cat /var/run/ping_stats_summary"), timeout=5.0
            )
        except asyncio.TimeoutError:
            logging.warning("Reading /var/run/ping_stats_summary timed out")
            return

        for line in stdout.split("\n"):
            elems = line.split()
            if len(elems) < 7:
                continue

            key, _, prio = elems[0].partition("_")
            if not prio:
                continue

            try:
                avg = float(elems[1])
                p50 = float(elems[2])
                p90 = float(elems[3])
                p99 = float(elems[4])
                loss = float(elems[5])
                valid_cnt = int(elems[6])
            except ValueError:
                avg = 0.0
                p50 = 0.0
                p90 = 0.0
                p99 = 0.0
                loss = 0.0
                valid_cnt = 0

            if valid_cnt > 0:
                self._update_metrics("gate_ping_avg", avg, prio)
                self._update_metrics("gate_ping_p50", p50, prio)
                self._update_metrics("gate_ping_p90", p90, prio)
                self._update_metrics("gate_ping_p99", p99, prio)
                self._update_metrics("gate_ping_loss", loss, prio)
            else:
                self._delete_metrics("gate_ping_avg", prio)
                self._delete_metrics("gate_ping_p50", prio)
                self._delete_metrics("gate_ping_p90", prio)
                self._delete_metrics("gate_ping_p99", prio)
                self._delete_metrics("gate_ping_loss", prio)

    async def _collect_high_res_stats(self) -> None:
        """
        Parse /var/run/mesh_stability_summary output and log to ODS:

        root@5ce28cf1abae:~# cat /var/run/mesh_stability_summary
        route_all_add                  6
        route_all_del                  3
        route_all_change               0
        route_default_add              2
        route_default_del              1
        route_default_change           0
        peer_change                    5

        bitrate_5ce28cf1abe6          293
        signal_5ce28cf1abe6           -19
        """

        # Read a fifo using asyncio and a timeout of 5 seconds
        try:
            stdout = await asyncio.wait_for(
                self.run_command("/bin/cat /var/run/mesh_stability_summary"),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logging.warning("Reading /var/run/mesh_stability_summary timed out")
            return

        bitrate_stats: Dict[str, float] = {}
        signal_stats: Dict[str, float] = {}
        for line in stdout.split("\n"):
            elems = line.split()
            if len(elems) < 2:
                continue

            try:
                val = int(elems[1])
            except ValueError:
                val = 0

            if elems[0].startswith("bitrate_"):
                label = elems[0].split("_")[1]
                bitrate_stats[label] = val
                self._update_metrics("avg_tx_bitrate", val, label)
            elif elems[0].startswith("signal_"):
                label = elems[0].split("_")[1]
                signal_stats[label] = val
                self._update_metrics("avg_signal", val, label)
            else:
                self._update_metrics("mesh_stability", val, elems[0])

        self._update_nexthop_metric("avg_tx_bitrate", bitrate_stats)
        self._update_nexthop_metric("avg_signal", signal_stats)

    async def _collect_rate_limit_ct(self) -> None:
        # Count rate-limiting journal entries in the past 120 seconds.
        cmd = """
            journalctl -q -u rsyslog --no-pager -S "$(date -d @$(( $(date +%s) -120 )) +"%Y-%m-%d %H:%M:%S")" \
            | grep "lost due to rate-limiting" \
            | wc -l
            """
        stdout = await self.run_command(cmd)
        try:
            rate_limits = int(stdout)
            RATE_LIMITING_MSG_CT.set(rate_limits)
        except ValueError:
            logging.exception(
                "Failed to convert rate-limit message into int, instead received: "
                + stdout
            )

    # Iterates through the sessions on a device to obtain the hires throughput
    # and tcp retransmit % values.
    async def _collect_user_experience_stats(self) -> None:
        stdout = await self.run_command("chilli_query -json list")

        # Occasionally, chilli is not fully running and activated, so chilli_query will
        # not produce output. This is generally transient and expected (or permanently
        # expected on devices with XWF disabled)
        if stdout == "":
            logging.warning(
                "Failed to retrieve hi-res throughput results because chilli_query could"
                " not connect; is chilli running?"
            )
            return

        try:
            results = json.loads(stdout)
        except Exception:
            logging.exception(
                "Failed parsing hires throughput results: '" + stdout + "'"
            )
            return

        tcp_pct_retr = []
        tcp_retransmit_pkts = 0
        tcp_sampled_pkts = 0
        in_speed_sum = 0.0
        out_speed_sum = 0.0
        min_in_speed = 0
        min_out_speed = 0
        session_count = 0

        for session in results["sessions"]:
            if "xwfsession" not in session:
                continue
            tcp_retr = session["xwfsession"].get("retransmit_tcp_packets", 0)
            tcp_samp = session["xwfsession"].get("sampled_tcp_packets", 0)
            tcp_retransmit_pkts += tcp_retr
            tcp_sampled_pkts += tcp_samp
            if tcp_samp > 500:
                tcp_pct_retr.append(tcp_retr / tcp_samp)

            if "authorized_traffic_classes" not in session["xwfsession"]:
                continue
            for tc in session["xwfsession"]["authorized_traffic_classes"]:
                if (
                    tc["traffic_class_name"] == "internet"
                    and tc.get("hires_non_zero_intervals_in_window", 0) > 75
                ):
                    input_speed = tc.get("hires_max_in_octets_per_sec", 0)
                    output_speed = tc.get("hires_max_out_octets_per_sec", 0)
                    in_speed_sum += input_speed
                    out_speed_sum += output_speed
                    session_count += 1
                    if min_in_speed == 0 or input_speed < min_in_speed:
                        min_in_speed = input_speed
                    if min_out_speed == 0 or output_speed < min_out_speed:
                        min_out_speed = output_speed
        if session_count > 0:
            AVG_HIRES_IN_SPEED.set(in_speed_sum / session_count)
            AVG_HIRES_OUT_SPEED.set(out_speed_sum / session_count)
            MIN_HIRES_IN_SPEED.set(min_in_speed)
            MIN_HIRES_OUT_SPEED.set(min_out_speed)
        else:
            AVG_HIRES_IN_SPEED.set(0)
            AVG_HIRES_OUT_SPEED.set(0)
            MIN_HIRES_IN_SPEED.set(0)
            MIN_HIRES_OUT_SPEED.set(0)
        length = len(tcp_pct_retr)
        if length > 0:
            tcp_pct_retr.sort()
            TCP_PKT_RETR_PCT_P10.set(100 * tcp_pct_retr[int(length * 0.1)])
            TCP_PKT_RETR_PCT_P50.set(100 * tcp_pct_retr[int(length * 0.5)])
            TCP_PKT_RETR_PCT_P90.set(100 * tcp_pct_retr[int(length * 0.9)])
            TCP_PKT_RETR_PCT_P99.set(100 * tcp_pct_retr[int(length * 0.99)])
        else:
            TCP_PKT_RETR_PCT_P10.set(0)
            TCP_PKT_RETR_PCT_P50.set(0)
            TCP_PKT_RETR_PCT_P90.set(0)
            TCP_PKT_RETR_PCT_P99.set(0)
        if tcp_sampled_pkts > 0:
            TCP_PKT_RETR_PCT.set(100 * tcp_retransmit_pkts / tcp_sampled_pkts)
        else:
            TCP_PKT_RETR_PCT.set(0)

    async def _collect_fbmeshd_stats(self) -> None:
        try:
            stats = meshquery.dump_stats()
        except TTransportException:
            return

        def split_seconds(text: str) -> Tuple[str, str]:
            if text.endswith("_0"):
                return text[:-2], "0"
            if text.endswith("_60"):
                return text[:-3], "60"
            if text.endswith("_600"):
                return text[:-4], "600"
            if text.endswith("_3600"):
                return text[:-5], "3600"
            return text, ""

        for stat in stats:
            key, seconds = split_seconds(stat.key.replace(".", "_"))

            if key in self._abs_metrics:
                self._update_metrics(key, stat.value, seconds)

    async def _collect_tmpfs_stats(self) -> None:
        """
        Parse df output and log to ODS:

        Example:
        Filesystem      1K-blocks        Used   Available Use% Mounted on
        devtmpfs         29293452           0    29293452   0% /dev
        tmpfs            29304732      121856    29182876   1% /dev/shm
        tmpfs            29304732       12876    29291856   1% /run
        /dev/vda3       387570688   248105488   120157424  68% /

        Will set metric to 121856 + 12876 -> 134732.
        """
        value = 0
        output_key = "tmpfs"
        metric_key = "tmpfs_kbs"

        stdout = await self.run_command("df")
        for line in stdout.splitlines():
            if not line:
                continue
            if line.startswith(output_key):
                try:
                    sp = line.split()
                    value += int(sp[2])
                except (IndexError, ValueError) as e:
                    logging.warning("could not parse stats for %s: %s", metric_key, e)
        self._update_metrics(metric_key, value)

    async def _collect_cpu_stats(self) -> None:
        # This tracks average CPU usage between calls to this function.
        cpu_now = psutil.cpu_times()
        time_now = time.time()
        cpu_prev = self._cpu_usage_prev
        time_prev = self._cpu_time_prev or time_now
        time_delta = time_now - time_prev
        if cpu_prev and time_delta > 1.0:
            num_cpus = psutil.cpu_count() or 1
            cpu_delta = (cpu_now.user - cpu_prev.user) + (
                cpu_now.system - cpu_prev.system
            )
            cpu_pct = cpu_delta / time_delta / num_cpus * 100
        else:
            # If this is the first time the function is called, measure the CPU
            # usage a over 1 second period
            cpu_pct = psutil.cpu_percent(interval=1)
        self._cpu_usage_prev = cpu_now
        self._cpu_time_prev = time_now
        CPU_AVG_USAGE_PCT.set(cpu_pct)


def _ipv6_to_mac(ip: str) -> str:
    """
    Convert a link-local ipv6 address to a mac address
    ipv6 address is assumed to be column-separated groups of 2 octets
    returns the mac address *not* separated by colons
    """
    ip_parts = ip.split(":")
    ip_parts = ip_parts[2:]  # first 4 octets are prefix
    ip_parts_pad = (ip_part.zfill(4) for ip_part in ip_parts)  # add padding
    ip_octets = ((ip_part[0:2], ip_part[2:4]) for ip_part in ip_parts_pad)
    mac_parts = [octet for octets in ip_octets for octet in octets]
    del mac_parts[3:5]  # 0xfffe

    # flip second-to-last bit in the first octet
    first_octet = int(mac_parts[0], 16)
    flipped = first_octet ^ 0b00000010
    mac_parts[0] = f"{flipped:x}"

    return "".join(mac_parts)


def _build_mesh0_stats_map(
    out_str: str
) -> Tuple[Dict[str, Dict[str, float]], int, int]:
    """
    See _parse_mesh0_station_dump for input.

    Returns a map {metric_name: {device_mac: value}}
    As well as the station count and number of estab stations
    """
    stats: DefaultDict[str, Dict[str, float]] = defaultdict(dict)
    stations = 0
    estab_stations = 0
    for station in out_str.split("Station"):
        if not station:
            continue
        stations += 1
        station_hw_addr = station.split()[0]
        # Metric's label value
        link = station_hw_addr.replace(":", "").lower()
        for line in station.split("\n"):
            # Parse metric's name and value
            fields = line.lstrip().split(":")
            if len(fields) < 2:
                continue
            key = fields[0]
            value_str = fields[1].split()[0]
            if key == "mesh plink" and value_str == "ESTAB":
                estab_stations += 1
            # Remove unit if it immediately follows the value
            value = re.sub("[^-.0-9]", "", value_str)
            if value:
                stats[key][link] = float(value)

    return stats, stations, estab_stations


def get_iperf_results() -> typing.List[typing.Tuple[float, float]]:
    """Returns a list of results (in sorted order) from previous iperf runs"""
    if not IPERF_RESULT_PATH.exists():
        return []
    try:
        results = json.load(IPERF_RESULT_PATH.open())
    except Exception:
        logging.exception("Failed loading iperf results")
        return []
    now = time.time()
    return [(then, result) for then, result in results if then + 3600 * 24 > now]


def store_last_iperf_result(mbits_per_sec: float) -> None:
    """Stores the last iperf result on the end of the list of iperf results"""
    new_results = get_iperf_results()
    new_results.append((time.time(), mbits_per_sec))
    json.dump(new_results, IPERF_RESULT_PATH.open("w"), indent=2)
