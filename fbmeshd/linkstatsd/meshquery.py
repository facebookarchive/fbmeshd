#!/usr/bin/env python3
# Copyright (c) 2017-present, Facebook, Inc. All rights reserved


from contextlib import contextmanager
from typing import Generator, List, Optional, cast

from fbmeshd import MeshService
from fbmeshd.ttypes import MpathEntry, PeerMetrics, StatCounter
from thrift.protocol import TBinaryProtocol
from thrift.transport import TSocket, TTransport


MESH_SERVICE_HOST = "localhost"
MESH_SERVICE_PORT = 30303
MESH_SERVICE_TIMEOUT_MS = 5000


@contextmanager
def mesh_client() -> Generator[MeshService.Client, None, None]:
    """
    A context manager that can be used to safely open a connection
    to a MeshService, yield a ready-to-use client object, and properly
    clean up afterward.
    """
    transport = TSocket.TSocket(MESH_SERVICE_HOST, MESH_SERVICE_PORT)
    transport.setTimeout(MESH_SERVICE_TIMEOUT_MS)
    transport = TTransport.TBufferedTransport(transport)
    protocol = TBinaryProtocol.TBinaryProtocol(transport)
    client = MeshService.Client(protocol)
    transport.open()
    try:
        yield client
    finally:
        transport.close()


def peers(interface_name: str) -> List[str]:
    """Information about the peers in the mesh"""
    with mesh_client() as client:
        # pyre-fixme[22]: The cast is redundant.
        return cast(List[str], client.getPeers(interface_name))


def peer_count(interface_name: str) -> int:
    """Number of peers in the mesh"""
    with mesh_client() as client:
        return len(client.getPeers(interface_name))


def metrics(interface_name: str) -> PeerMetrics:
    """Information about the metric to peers in the mesh"""
    with mesh_client() as client:
        return client.getMetrics(interface_name)


def center_freq1(interface_name: str) -> int:
    with mesh_client() as client:
        mesh = client.getMesh(interface_name)
        # pyre-fixme[22]: The cast is redundant.
        return cast(int, mesh.centerFreq1)


def center_freq2(interface_name: str) -> Optional[int]:
    with mesh_client() as client:
        mesh = client.getMesh(interface_name)
        if mesh.centerFreq2:
            return cast(int, mesh.centerFreq2)
        else:
            return None


def freq(interface_name: str) -> int:
    with mesh_client() as client:
        mesh = client.getMesh(interface_name)
        # pyre-fixme[22]: The cast is redundant.
        return cast(int, mesh.frequency)


def tx_power(interface_name: str) -> Optional[int]:
    with mesh_client() as client:
        mesh = client.getMesh(interface_name)
        if mesh.txPower:
            # pyre-fixme[22]: The cast is redundant.
            # pyre-fixme[6]: Expected `int` for 1st param but got `Optional[int]`.
            return cast(int, mesh.txPower // 100)
        else:
            return None


def channel_width(interface_name: str) -> str:
    def prettyName(width: int) -> str:
        if width == 0:
            return "NOHT"
        elif width == 1:
            return "20"
        elif width == 2:
            return "40"
        elif width == 3:
            return "80"
        elif width == 4:
            return "80+80"
        elif width == 5:
            return "160"
        else:
            return "Unknown width (contact the development team)"

    with mesh_client() as client:
        mesh = client.getMesh(interface_name)
        return prettyName(mesh.channelWidth)


def dump_stats() -> List[StatCounter]:
    with mesh_client() as client:
        # pyre-fixme[22]: The cast is redundant.
        return cast(List[StatCounter], client.dumpStats())


def dump_mpaths() -> List[MpathEntry]:
    """Dump mpath table"""
    with mesh_client() as client:
        # pyre-fixme[22]: The cast is redundant.
        return cast(List[MpathEntry], client.dumpMpath())
