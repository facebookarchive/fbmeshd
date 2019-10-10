#
# Copyright (c) 2014-present, Facebook, Inc.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
#

cmake_minimum_required (VERSION 3.9)
project (fbmeshd)
enable_testing()

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -Wextra")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wno-noexcept-type")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wno-maybe-uninitialized")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wno-deprecated-declarations")

# Enable LTO by default
option(BUILD_WITH_LTO "BUILD_WITH_LTO" ON)
if (BUILD_WITH_LTO)
  set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
  set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -flto")
endif()

include_directories(${CMAKE_SOURCE_DIR})

find_library(NL3 nl-3)
find_library(NLROUTE3 nl-route-3)
find_library(FBZMQ fbzmq)
find_library(FOLLY folly PATHS)
find_library(THRIFT thrift PATHS)
find_library(THRIFTCPP2 thriftcpp2 PATHS)
find_library(GLOG glog)
find_library(GFLAGS gflags)
find_library(SODIUM sodium)
find_library(ZMQ zmq)
find_library(THRIFTPROTOCOL thriftprotocol PATHS)
find_library(PROTOCOL protocol PATHS)
find_library(TRANSPORT transport PATHS)
find_library(ASYNC async PATHS)
find_library(CONCURRENCY concurrency PATHS)

find_path(LIBNL3-HEADERS libnl3/netlink/netlink.h)

# Include Thrift
set(
  THRIFT_GENERATE_THRIFT_INCLUDE_DIRECTORIES
  ${CMAKE_SOURCE_DIR}
  CACHE PATH "thrift include directory"
)
find_program(THRIFT1 thrift1)
# Next two lines will need to be removed on modern thrift, a la D16356056
find_path(THRIFT_COMPILER_INCLUDE thrift/templates)
set(THRIFT_TEMPLATES ${THRIFT_COMPILER_INCLUDE}/thrift/templates)
include(${CMAKE_SOURCE_DIR}/ThriftLibrary.cmake)

set(THRIFT_DIR ${CMAKE_BINARY_DIR}/thrift-out)
include_directories(${THRIFT_DIR})

file(MAKE_DIRECTORY ${THRIFT_DIR}/fbmeshd/if)

thrift_object(
  "fbmeshd" #file_name
  "MeshService" #services
  "cpp2" #language
  "json,optionals" #options
  "${CMAKE_SOURCE_DIR}/fbmeshd/if" #file_path
  "${THRIFT_DIR}/fbmeshd/if" #output_path
  "fbmeshd/if" #include_prefix
)

option(ENABLE_SYSTEMD_NOTIFY "ENABLE_SYSTEMD_NOTIFY" ON)

if(ENABLE_SYSTEMD_NOTIFY)
  add_definitions(-DENABLE_SYSTEMD_NOTIFY)
  find_library(SYSTEMD_LIBRARY NAMES systemd)
else()
  set(SYSTEMD_LIBRARY "")
endif()

# authsae requires the LINUX flag to use the appropriate includes
add_definitions(-DLINUX)
find_library(SAE_LIBRARY NAMES sae)

add_executable(fbmeshd
    fbmeshd/main.cpp
    fbmeshd/802.11s/AuthsaeCallbackHelpers.cpp
    fbmeshd/802.11s/AuthsaeConfigHelpers.cpp
    fbmeshd/802.11s/NetInterface.cpp
    fbmeshd/802.11s/Nl80211Handler.cpp
    fbmeshd/common/Constants.cpp
    fbmeshd/gateway-connectivity-monitor/GatewayConnectivityMonitor.cpp
    fbmeshd/gateway-connectivity-monitor/RouteDampener.cpp
    fbmeshd/gateway-connectivity-monitor/Socket.cpp
    fbmeshd/gateway-connectivity-monitor/StatsClient.cpp
    fbmeshd/nl/GenericNetlinkFamily.cpp
    fbmeshd/notifier/Notifier.cpp
    fbmeshd/rnl/NetlinkMessage.cpp
    fbmeshd/rnl/NetlinkRoute.cpp
    fbmeshd/rnl/NetlinkSocket.cpp
    fbmeshd/rnl/NetlinkTypes.cpp
    fbmeshd/route-update-monitor/RouteUpdateMonitor.cpp
    fbmeshd/routing/MetricManager80211s.cpp
    fbmeshd/routing/PeriodicPinger.cpp
    fbmeshd/routing/Routing.cpp
    fbmeshd/routing/SyncRoutes80211s.cpp
    fbmeshd/routing/UDPRoutingPacketTransport.cpp
    $<TARGET_OBJECTS:fbmeshd-cpp2-obj>
)

# override with -DCMAKE_BUILD_TYPE=Release
SET(CMAKE_BUILD_TYPE Debug)

target_include_directories(fbmeshd
  PRIVATE
  ${LIBNL3-HEADERS}/libnl3
)

target_link_libraries(fbmeshd
  ${FBZMQ}
  ${THRIFT}
  ${THRIFTCPP2}
  ${GLOG}
  ${GFLAGS}
  ${SODIUM}
  ${ZMQ}
  ${THRIFTPROTOCOL}
  ${PROTOCOL}
  ${TRANSPORT}
  ${ASYNC}
  ${CONCURRENCY}
  ${NL3}
  ${NLROUTE3}
  ${SAE_LIBRARY}
  -lboost_program_options
  -lpthread
  -lcrypto
  -lnl-genl-3
  ${SYSTEMD_LIBRARY}
)
install(TARGETS fbmeshd
        RUNTIME DESTINATION sbin)

# install the fbmeshd startup script
install(PROGRAMS
  ${CMAKE_CURRENT_SOURCE_DIR}/fbmeshd/scripts/run_fbmeshd.sh
  DESTINATION sbin
)

# ========================================================================
option(BUILD_TESTS "BUILD_TESTS" ON)

if(BUILD_TESTS)

  # add google test (only used by unit tests)
  find_package(GTest REQUIRED)
  include_directories(${GTEST_INCLUDE_DIRS})
  set(LIBS ${LIBS} ${GTEST_LIBRARIES})

  project (UnitTests)

  include_directories(${CMAKE_SOURCE_DIR}/../..)

  add_executable(Nl80211HandlerTest
      fbmeshd/802.11s/AuthsaeCallbackHelpers.cpp
      fbmeshd/802.11s/AuthsaeConfigHelpers.cpp
      fbmeshd/802.11s/NetInterface.cpp
      fbmeshd/802.11s/Nl80211Handler.cpp
      fbmeshd/common/Constants.cpp
      fbmeshd/nl/GenericNetlinkFamily.cpp
      fbmeshd/tests/Nl80211HandlerTest.cpp
  )
  target_link_libraries(Nl80211HandlerTest ${LIBS})
  add_test(unittest-Nl80211Handler Nl80211HandlerTest)

  install(TARGETS Nl80211HandlerTest
          RUNTIME DESTINATION bin)

endif()
