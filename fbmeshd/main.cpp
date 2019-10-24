/**
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include <signal.h>
#ifdef ENABLE_SYSTEMD_NOTIFY
#include <systemd/sd-daemon.h> // @manual
#endif

#include <chrono>
#include <thread>

#include <fbzmq/async/ZmqEventLoop.h>
#include <folly/SocketAddress.h>
#include <folly/init/Init.h>
#include <folly/io/async/EventBase.h>
#include <thrift/lib/cpp2/server/ThriftServer.h>

#include <fbmeshd/802.11s/AuthsaeCallbackHelpers.h>
#include <fbmeshd/802.11s/Nl80211Handler.h>
#include <fbmeshd/FollySignalHandler.h>
#include <fbmeshd/MeshServiceHandler.h>
#include <fbmeshd/SignalHandler.h>
#include <fbmeshd/common/Constants.h>
#include <fbmeshd/common/Util.h>
#include <fbmeshd/gateway-connectivity-monitor/GatewayConnectivityMonitor.h>
#include <fbmeshd/gateway-connectivity-monitor/RouteDampener.h>
#include <fbmeshd/notifier/Notifier.h>
#include <fbmeshd/route-update-monitor/RouteUpdateMonitor.h>
#include <fbmeshd/routing/MetricManager80211s.h>
#include <fbmeshd/routing/PeriodicPinger.h>
#include <fbmeshd/routing/Routing.h>
#include <fbmeshd/routing/SyncRoutes80211s.h>
#include <fbmeshd/routing/UDPRoutingPacketTransport.h>

using namespace fbmeshd;

using namespace std::chrono_literals;

DEFINE_int32(fbmeshd_service_port, 30303, "fbmeshd thrift service port");

DEFINE_string(node_name, "node1", "The name of current node");

DEFINE_string(mesh_ifname, "mesh0", "Mesh interface name");

DEFINE_bool(
    enable_userspace_mesh_peering,
    true,
    "If set, mesh peering management handshake will be done in userspace");

// Gateway Connectivity Monitor configs
DEFINE_string(
    gateway_connectivity_monitor_interface,
    "eth0",
    "The interface that the gateway connectivity monitor runs on");
DEFINE_string(
    gateway_connectivity_monitor_addresses,
    "8.8.4.4:443,1.1.1.1:443",
    "A comma-separated list of addresses that the gateway connectivity monitor "
    "connects to to check WAN connectivity (host:port)");
DEFINE_uint32(
    gateway_connectivity_monitor_interval_s,
    1,
    "Interval in seconds to check for connectivity by the gateway "
    "connectivity monitor");
DEFINE_uint32(
    gateway_connectivity_monitor_socket_timeout_s,
    5,
    "How long to wait until timing out the socket when checking for "
    "connectivity by the gateway connectivity monitor");
DEFINE_uint32(
    gateway_connectivity_monitor_robustness,
    fbmeshd::Constants::kDefaultRobustness,
    "The number of times to attempt to connect to the monitor address before "
    "declaring connectivity down");
DEFINE_uint32(
    gateway_connectivity_monitor_set_root_mode,
    0,
    "The value for root mode that should be set if we are a gate");

DEFINE_uint32(
    route_dampener_penalty,
    fbmeshd::Constants::kDefaultPenalty,
    "The route dampener penalty assigned to default route flaps.");

DEFINE_uint32(
    route_dampener_suppress_limit,
    fbmeshd::Constants::kDefaultSuppressLimit,
    "The route dampener limit which when reached will suppress the advertisement"
    " of a default route.");

DEFINE_uint32(
    route_dampener_reuse_limit,
    fbmeshd::Constants::kDefaultReuseLimit,
    "The route dampener limit which when passed on the way down will unsuppress"
    " a suppressed default route.");

DEFINE_uint32(
    route_dampener_halflife,
    fbmeshd::Constants::kDefaultHalfLife.count(),
    "The route dampener halflife in seconds in which the history penalty value"
    " will be reduced by half.");

DEFINE_uint32(
    route_dampener_max_suppress_limit,
    fbmeshd::Constants::kDefaultMaxSuppressLimit.count(),
    "The route dampener maximum time a default route can be suppressed before"
    " it will be automatically unsupressed.");

DEFINE_uint32(routing_ttl, 32, "TTL for routing elements");
DEFINE_int32(routing_tos, 192, "ToS value for routing messages");
DEFINE_uint32(
    routing_active_path_timeout_ms,
    30000,
    "Routing active path timeout (ms)");
DEFINE_uint32(
    routing_root_pann_interval_ms,
    5000,
    "Routing PANN interval (ms)");
DEFINE_uint32(
    routing_metric_manager_ewma_factor_log2,
    7,
    "Routing metric manager EWMA log2 factor (e.g. value of 7 here implies"
    " factor of 2^7=128)");
DEFINE_double(
    routing_metric_manager_rssi_weight,
    0.0,
    "Weight of the RSSI based metric (vs. bitrate) in the combined metric");

DEFINE_bool(
    version,
    false,
    "Print version of code this fbmeshd executable was built from and exit");

// TODO: The following flags are deprecated and should not be used.
//
// They will be removed in a future version of fbmeshd, at which time using them
// will result in fbmeshd not starting (as they will not be parsed).
// TODO T54087050
DEFINE_bool(enable_watchdog, false, "DEPRECATED on 2019-09-16, do not use");
DEFINE_int32(watchdog_interval_s, 0, "DEPRECATED on 2019-09-16, do not use");
DEFINE_int32(watchdog_threshold_s, 0, "DEPRECATED on 2019-09-16, do not use");
DEFINE_int32(memory_limit_mb, 0, "DEPRECATED on 2019-09-16, do not use");

namespace {

// NOTE: This must be updated (monotonically increment) with any fbmeshd changes
// that are open-sourced. It is used to allow an end user of an fbmeshd
// executable to identify what code version it was built from.
// TODO T56294978: Find a way to embed this without having to manually touch it
constexpr uint32_t kFbmeshdVersion{1};

constexpr folly::StringPiece kHostName{"localhost"};

constexpr auto kMetricManagerInterval{3s};
constexpr auto kMetricManagerHysteresisFactorLog2{2};
constexpr auto kMetricManagerBaseBitrate{60};
constexpr auto kPeriodicPingerInterval{10s};
constexpr auto kWatchdogNotifyInterval{3s};

} // namespace

int main(int argc, char* argv[]) {
  folly::init(&argc, &argv);

  // Set stdout to be line-buffered, to assist with integration testing that
  // depends on log output
  setvbuf(stdout, nullptr /*buffer*/, _IOLBF, 0);

  if (FLAGS_version) {
    LOG(INFO) << folly::sformat("fbmeshd version: {}", kFbmeshdVersion);
    return 0;
  }

  LOG(INFO) << "Starting fbmesh daemon...";

  std::vector<std::thread> allThreads{};

  fbzmq::ZmqEventLoop evl;

  SignalHandler signalHandler{evl};
  signalHandler.registerSignalHandler(SIGABRT);
  signalHandler.registerSignalHandler(SIGINT);
  signalHandler.registerSignalHandler(SIGTERM);

  folly::EventBase routingEventLoop;

  FollySignalHandler follySignalHandler{routingEventLoop, evl};
  follySignalHandler.registerSignalHandler(SIGABRT);
  follySignalHandler.registerSignalHandler(SIGINT);
  follySignalHandler.registerSignalHandler(SIGTERM);

  LOG(INFO) << "Creating watchdog notifier...";
  std::unique_ptr<Notifier> notifier =
      std::make_unique<Notifier>(&routingEventLoop, kWatchdogNotifyInterval);

  AuthsaeCallbackHelpers::init(evl);

  Nl80211Handler nlHandler{
      evl, FLAGS_mesh_ifname, FLAGS_enable_userspace_mesh_peering};
  auto returnValue = nlHandler.joinMeshes();
  if (returnValue != R_SUCCESS) {
    return returnValue;
  }

  LOG(INFO) << "Creating RouteUpdateMonitor...";
  RouteUpdateMonitor routeMonitor{&routingEventLoop, nlHandler};

  LOG(INFO) << "Creating MetricManager80211s...";
  std::unique_ptr<MetricManager80211s> metricManager80211s =
      std::make_unique<MetricManager80211s>(
          &routingEventLoop,
          kMetricManagerInterval,
          nlHandler,
          FLAGS_routing_metric_manager_ewma_factor_log2,
          kMetricManagerHysteresisFactorLog2,
          kMetricManagerBaseBitrate,
          FLAGS_routing_metric_manager_rssi_weight);

  LOG(INFO) << "Creating PeriodicPinger...";
  std::unique_ptr<PeriodicPinger> periodicPinger =
      std::make_unique<PeriodicPinger>(
          &routingEventLoop,
          folly::IPAddressV6{folly::sformat("ff02::1%{}", FLAGS_mesh_ifname)},
          folly::IPAddressV6{
              folly::IPAddressV6::LinkLocalTag::LINK_LOCAL,
              nlHandler.lookupMeshNetif().maybeMacAddress.value()},
          kPeriodicPingerInterval,
          FLAGS_mesh_ifname);

  std::unique_ptr<Routing> routing = std::make_unique<Routing>(
      &routingEventLoop,
      metricManager80211s.get(),
      nlHandler.lookupMeshNetif().maybeMacAddress.value(),
      FLAGS_routing_ttl,
      std::chrono::milliseconds{FLAGS_routing_active_path_timeout_ms},
      std::chrono::milliseconds{FLAGS_routing_root_pann_interval_ms});
  std::unique_ptr<UDPRoutingPacketTransport> routingPacketTransport =
      std::make_unique<UDPRoutingPacketTransport>(
          &routingEventLoop, FLAGS_mesh_ifname, 6668, FLAGS_routing_tos);

  routing->setSendPacketCallback(
      [&routingPacketTransport](
          folly::MacAddress da, std::unique_ptr<folly::IOBuf> buf) {
        routingPacketTransport->sendPacket(da, std::move(buf));
      });

  routingPacketTransport->setReceivePacketCallback(
      [&routing](folly::MacAddress sa, std::unique_ptr<folly::IOBuf> buf) {
        routing->receivePacket(sa, std::move(buf));
      });

  LOG(INFO) << "Creating NetlinkProtocolSocket...";
  // set up NetlinkProtocolSocket in a new thread to program the linux kernel
  auto nlProtocolSocketEventLoop = std::make_unique<fbzmq::ZmqEventLoop>();
  std::unique_ptr<rnl::NetlinkProtocolSocket> nlProtocolSocket;
  nlProtocolSocket = std::make_unique<rnl::NetlinkProtocolSocket>(
      nlProtocolSocketEventLoop.get());
  allThreads.emplace_back(
      std::thread([&nlProtocolSocket, &nlProtocolSocketEventLoop]() {
        LOG(INFO) << "Starting NetlinkProtolSocketEvl thread...";
        folly::setThreadName("NetlinkProtolSocketEvl");
        nlProtocolSocket->init();
        nlProtocolSocketEventLoop->run();
        LOG(INFO) << "NetlinkProtolSocketEvl thread stopped.";
      }));
  nlProtocolSocketEventLoop->waitUntilRunning();

  LOG(INFO) << "Creating NetlinkSocket...";
  std::unique_ptr<rnl::NetlinkSocket> nlSocket =
      std::make_unique<rnl::NetlinkSocket>(
          &evl, nullptr, std::move(nlProtocolSocket));

  LOG(INFO) << "Creating SyncRoutes80211s...";
  std::unique_ptr<SyncRoutes80211s> syncRoutes80211s =
      std::make_unique<SyncRoutes80211s>(
          &routingEventLoop,
          routing.get(),
          nlSocket.get(),
          nlHandler.lookupMeshNetif().maybeMacAddress.value(),
          FLAGS_mesh_ifname);

  static constexpr auto routingId{"Routing"};
  allThreads.emplace_back(std::thread([&routingEventLoop]() noexcept {
    LOG(INFO) << "Starting Routing thread...";
    folly::setThreadName(routingId);
    routingEventLoop.loopForever();
    LOG(INFO) << "Routing thread stopped.";
  }));

  auto gatewayConnectivityMonitorAddresses{parseCsvFlag<folly::SocketAddress>(
      FLAGS_gateway_connectivity_monitor_addresses, [](const std::string& str) {
        folly::SocketAddress address;
        address.setFromIpPort(str);
        return address;
      })};

  StatsClient statsClient{};

  LOG(INFO) << "Creating GatewayConnectivityMonitor...";
  folly::EventBase gcmEventLoop;
  GatewayConnectivityMonitor gatewayConnectivityMonitor{
      &gcmEventLoop,
      nlHandler,
      FLAGS_gateway_connectivity_monitor_interface,
      std::move(gatewayConnectivityMonitorAddresses),
      std::chrono::seconds{FLAGS_gateway_connectivity_monitor_interval_s},
      std::chrono::seconds{FLAGS_gateway_connectivity_monitor_socket_timeout_s},
      FLAGS_route_dampener_penalty,
      FLAGS_route_dampener_suppress_limit,
      FLAGS_route_dampener_reuse_limit,
      std::chrono::seconds{FLAGS_route_dampener_halflife},
      std::chrono::seconds{FLAGS_route_dampener_max_suppress_limit},
      FLAGS_gateway_connectivity_monitor_robustness,
      static_cast<uint8_t>(FLAGS_gateway_connectivity_monitor_set_root_mode),
      routing.get(),
      statsClient};

  static constexpr auto gcmId{"GatewayConnectivityMonitor"};
  allThreads.emplace_back(std::thread([&gcmEventLoop]() noexcept {
    LOG(INFO) << "Starting GatewayConnectivityMonitor thread...";
    folly::setThreadName(gcmId);
    gcmEventLoop.loopForever();
    LOG(INFO) << "GatewayConnectivityMonitor thread stopped.";
  }));

  // create fbmeshd thrift server
  LOG(INFO) << "Starting thrift server...";
  auto server = std::make_unique<apache::thrift::ThriftServer>();
  allThreads.emplace_back(std::thread(
      [&routingEventLoop, &server, &nlHandler, &routing, &statsClient]() {
        server->setInterface(std::make_unique<MeshServiceHandler>(
            routingEventLoop, nlHandler, routing.get(), statsClient));

        folly::EventBase internalEvb;
        server->getEventBaseManager()->setEventBase(&internalEvb, false);

        server->setPort(FLAGS_fbmeshd_service_port);

        LOG(INFO) << "Starting thrift server thread...";
        server->serve();
        LOG(INFO) << "Stopped thrift server thread.";
      }));

#ifdef ENABLE_SYSTEMD_NOTIFY
  // Notify systemd that this service is ready
  sd_notify(0, "READY=1");
#endif

  evl.run();

#ifdef ENABLE_SYSTEMD_NOTIFY
  sd_notify(0, "STOPPING=1");
#endif

  LOG(INFO) << "Leaving mesh...";
  nlHandler.leaveMeshes();

  LOG(INFO) << "Stopping thrift server thread...";
  server->stop();

  nlProtocolSocket.reset();
  if (nlProtocolSocketEventLoop) {
    nlProtocolSocketEventLoop->stop();
    nlProtocolSocketEventLoop->waitUntilStopped();
  }

  routing->resetSendPacketCallback();
  routingEventLoop.terminateLoopSoon();

  gcmEventLoop.terminateLoopSoon();

  // Wait for all threads to finish
  for (auto& t : allThreads) {
    t.join();
  }

  LOG(INFO) << "Stopping fbmesh daemon...";
  return 0;
}
