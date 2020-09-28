"""
Copyright (c) 2004-present, Facebook, Inc.
All rights reserved.
"""
# @lint-ignore-every MYPY

import argparse
import logging

from magma.common.sdwatchdog import SDWatchdog
from magma.common.service import MagmaService
from wifi.protos.mconfig import wifi_mconfigs_pb2

from .collector import LinkstatsCollector
from .state_manager import NetworkStateManager


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        "Linkstatsd for gathering key/value metrics and status metadata"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug output")
    return parser


def main():
    """
    Main co-routine for linkstatsd
    :return: None
    """
    parser = create_parser()
    args = parser.parse_args()

    # set up logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s %(levelname)s %(filename)s:%(lineno)d] %(message)s",
    )

    # Get service config
    service = MagmaService("linkstatsd", wifi_mconfigs_pb2.Linkstatsd())

    # Create stats collector
    collector = LinkstatsCollector(service.loop, service.config, service.mconfig)

    # Create network state manager
    state_mgr = NetworkStateManager(service.loop, service.config, service.mconfig)

    # Start state manager's state-updating loop
    state_mgr.start()

    # Register callback function to sync state with the cloud
    service.register_get_status_callback(state_mgr.get_state)

    # Start collector loop
    collector.start_collector()

    if SDWatchdog.has_notify():
        # Create systemd watchdog
        sdwatchdog = SDWatchdog([collector, state_mgr], update_status=True)
        # Start watchdog loop
        service.loop.create_task(sdwatchdog.run())

    # Run the service loop
    service.run()

    # Cleanup the service
    service.close()


if __name__ == "__main__":
    main()
