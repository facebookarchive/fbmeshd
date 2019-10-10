/**
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#pragma once

#include <folly/SocketAddress.h>
#include <folly/io/async/AsyncTimeout.h>
#include <folly/io/async/EventBase.h>

#include <fbmeshd/802.11s/Nl80211Handler.h>
#include <fbmeshd/gateway-connectivity-monitor/RouteDampener.h>
#include <fbmeshd/gateway-connectivity-monitor/StatsClient.h>
#include <fbmeshd/routing/Routing.h>

namespace fbmeshd {

class GatewayConnectivityMonitor : public RouteDampener {
 public:
  explicit GatewayConnectivityMonitor(
      folly::EventBase* evb,
      Nl80211Handler& nlHandler,
      const std::string& monitoredInterface,
      std::vector<folly::SocketAddress> monitoredAddresses,
      std::chrono::seconds monitorInterval,
      std::chrono::seconds monitorSocketTimeout,
      unsigned int penalty,
      unsigned int suppressLimit,
      unsigned int reuseLimit,
      std::chrono::seconds halfLife,
      std::chrono::seconds maxSuppressLimit,
      unsigned int robustness,
      uint8_t setRootModeIfGate,
      Routing* routing,
      StatsClient& statsClient);

  GatewayConnectivityMonitor() = delete;
  ~GatewayConnectivityMonitor() override = default;
  GatewayConnectivityMonitor(const GatewayConnectivityMonitor&) = delete;
  GatewayConnectivityMonitor(GatewayConnectivityMonitor&&) = delete;
  GatewayConnectivityMonitor& operator=(const GatewayConnectivityMonitor&) =
      delete;
  GatewayConnectivityMonitor& operator=(GatewayConnectivityMonitor&&) = delete;

 private:
  void setStat(const std::string& path, int value) override;
  void dampen() override;
  void undampen() override;

  bool probeWanConnectivity();
  bool probeWanConnectivityRobustly();

  void checkRoutesAndAdvertise();

  void advertiseDefaultRoute();
  void withdrawDefaultRoute();

 private:
  Nl80211Handler& nlHandler_;

  const std::string monitoredInterface_;
  const std::vector<folly::SocketAddress> monitoredAddresses_;
  const std::chrono::seconds monitorSocketTimeout_;
  const unsigned int robustness_;
  const uint8_t setRootModeIfGate_;
  Routing* routing_{nullptr};

  std::unique_ptr<folly::AsyncTimeout> connectivityCheckTimer_;

  StatsClient& statsClient_;

  bool isGatewayActive_{false};
};

} // namespace fbmeshd
