/**
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#pragma once

#include <string>

#include <folly/container/F14Map.h>
#include <folly/stats/MultiLevelTimeSeries.h>

namespace fbmeshd {

enum StatsType {
  SUM = 0,
  AVG = 1,
};

// This class is heavily inspired by fbzmq::StatsClient, the data structure
// previously used here. In the process of removing dependency on fbzmq, this
// slimmed down alternative was written in its place.
class StatsClient final {
 public:
  StatsClient();
  ~StatsClient() = default;
  StatsClient(const StatsClient&) = delete;
  StatsClient& operator=(const StatsClient&) = delete;
  StatsClient(StatsClient&&) = delete;
  StatsClient& operator=(StatsClient&&) = delete;

  void incrementSumStat(const std::string& stat);
  void setAvgStat(const std::string& stat, int value);

  const std::unordered_map<std::string, int64_t> getStats();

 private:
  folly::F14FastMap<
      std::string,
      folly::MultiLevelTimeSeries<int64_t>>
      stats_;
  folly::F14FastMap<std::string, StatsType> types_;

  void addStatValue(std::string const& key, int64_t value, StatsType type);
};

} // namespace fbmeshd
