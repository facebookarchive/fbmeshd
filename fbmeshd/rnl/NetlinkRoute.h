/**
 * Copyright (c) 2014-present, Facebook, Inc.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#pragma once

#include <linux/lwtunnel.h>
#include <linux/mpls.h>
#include <linux/rtnetlink.h>
#include <net/if_arp.h>
#include <netinet/ether.h>
#include <sys/socket.h>
#include <sys/types.h>

#include <fbzmq/async/ZmqEventLoop.h>
#include <fbzmq/async/ZmqTimeout.h>
#include <fbzmq/zmq/Zmq.h>
#include <folly/IPAddress.h>

#include <fbmeshd/rnl/NetlinkMessage.h>
#include <fbmeshd/rnl/NetlinkTypes.h>

#ifndef MPLS_IPTUNNEL_DST
#define MPLS_IPTUNNEL_DST 1
#endif

namespace rnl {

constexpr uint16_t kMaxLabels{16};
constexpr uint32_t kLabelBosShift{8};
constexpr uint32_t kLabelShift{12};
constexpr uint32_t kLabelMask{0xFFFFF000};
constexpr uint32_t kLabelSizeBits{20};

class NetlinkRouteMessage final : public NetlinkMessage {
 public:
  NetlinkRouteMessage();

  // initiallize route message with default params
  void init(int type, uint32_t flags, const rnl::Route& route);

  friend std::ostream&
  operator<<(std::ostream& out, NetlinkRouteMessage const& msg) {
    out << "\nMessage type:     " << msg.msghdr_->nlmsg_type
        << "\nMessage length:   " << msg.msghdr_->nlmsg_len
        << "\nMessage flags:    " << std::hex << msg.msghdr_->nlmsg_flags
        << "\nMessage sequence: " << msg.msghdr_->nlmsg_seq
        << "\nMessage pid:      " << msg.msghdr_->nlmsg_pid << std::endl;
    return out;
  }

  // add a unicast route
  ResultCode addRoute(const rnl::Route& route);

  // delete a route
  ResultCode deleteRoute(const rnl::Route& route);

  // add label route
  ResultCode addLabelRoute(const rnl::Route& route);

  // delete label route
  ResultCode deleteLabelRoute(const rnl::Route& route);

  // encode MPLS label, returns in network order
  uint32_t encodeLabel(uint32_t label, bool bos) const;

  // process netlink route message
  rnl::Route parseMessage(const struct nlmsghdr* nlmsg) const;

 private:
  // print ancillary data
  void showRtmMsg(const struct rtmsg* const hdr) const;

  // print route attribute
  void showRouteAttribute(const struct rtattr* const hdr) const;

  // print multi path attributes
  void showMultiPathAttribues(const struct rtattr* const rta) const;

  // parse IP address
  folly::Expected<folly::IPAddress, folly::IPAddressFormatError> parseIp(
      const struct rtattr* ipAttr, unsigned char family) const;

  // process netlink next hops
  std::vector<rnl::NextHop> parseNextHops(
      const struct rtattr* routeAttrMultipath, unsigned char family) const;

  // parse NextHop Attributes
  void parseNextHopAttribute(
      const struct rtattr* routeAttr,
      unsigned char family,
      rnl::NextHopBuilder& nhBuilder) const;

  // parse MPLS labels
  folly::Optional<std::vector<int32_t>> parseMplsLabels(
      const struct rtattr* routeAttr) const;

  // set mpls action based on nexthop fields
  void setMplsAction(
      rnl::NextHopBuilder& nhBuilder, unsigned char family) const;

  // pointer to route message header
  struct rtmsg* rtmsg_{nullptr};

  // add set of nexthops
  ResultCode addNextHops(const rnl::Route& route);

  // Add ECMP paths
  ResultCode addMultiPathNexthop(
      std::array<char, kMaxNlPayloadSize>& nhop,
      const rnl::Route& route) const;

  // Add label encap
  ResultCode addLabelNexthop(
      struct rtattr* rta,
      struct rtnexthop* rtnh,
      const rnl::NextHop& path) const;

  // swap or PHP
  ResultCode addSwapOrPHPNexthop(
      struct rtattr* rta,
      struct rtnexthop* rtnh,
      const rnl::NextHop& path) const;

  // POP - sends to lo I/F
  ResultCode addPopNexthop(
      struct rtattr* rta,
      struct rtnexthop* rtnh,
      const rnl::NextHop& path) const;

  // POP - sends to lo I/F
  ResultCode addIpNexthop(
      struct rtattr* rta,
      struct rtnexthop* rtnh,
      const rnl::NextHop& path,
      const rnl::Route& route) const;

  // pointer to the netlink message header
  struct nlmsghdr* msghdr_{nullptr};

  // for via nexthop
  struct NextHop {
    uint16_t addrFamily;
    char ip[16];
  } __attribute__((__packed__));

  struct NextHopV4 {
    uint16_t addrFamily;
    char ip[4];
  } __attribute__((__packed__));
};

class NetlinkLinkMessage final : public NetlinkMessage {
 public:
  NetlinkLinkMessage();

  // initiallize link message with default params
  void init(int type, uint32_t flags);

  // parse Netlink Link message
  rnl::Link parseMessage(const struct nlmsghdr* nlh) const;

 private:
  // pointer to link message header
  struct ifinfomsg* ifinfomsg_{nullptr};

  // pointer to the netlink message header
  struct nlmsghdr* msghdr_{nullptr};
};

class NetlinkAddrMessage final : public NetlinkMessage {
 public:
  NetlinkAddrMessage();

  // initiallize address message with default params
  void init(int type);

  // parse Netlink Address message
  rnl::IfAddress parseMessage(const struct nlmsghdr* nlh) const;

  // create netlink message to add/delete interface address
  // type - RTM_NEWADDR or RTM_DELADDR
  ResultCode addOrDeleteIfAddress(
      const rnl::IfAddress& ifAddr, const int type);

 private:
  // pointer to interface message header
  struct ifaddrmsg* ifaddrmsg_{nullptr};

  // pointer to the netlink message header
  struct nlmsghdr* msghdr_{nullptr};
};

class NetlinkNeighborMessage final : public NetlinkMessage {
 public:
  NetlinkNeighborMessage();

  // initiallize neighbor message with default params
  void init(int type, uint32_t flags);

  // parse Netlink Neighbor message
  rnl::Neighbor parseMessage(const struct nlmsghdr* nlh) const;

 private:
  // pointer to neighbor message header
  struct ndmsg* ndmsg_{nullptr};

  // pointer to the netlink message header
  struct nlmsghdr* msghdr_{nullptr};
};

} // namespace rnl
