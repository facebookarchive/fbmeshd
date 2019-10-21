/**
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "StatsClient.h"

#include <chrono>

#include <glog/logging.h>

#include <folly/Format.h>
#include <folly/stats/MultiLevelTimeSeries.h>

namespace fbmeshd {

// Number of buckets to use for folly::BucketedTimeSeries
static const uint64_t kTsBuckets{60};

// Statically defined levels for multi level timeseries.
static const std::vector<std::chrono::seconds> kLevelDurations = {
    std::chrono::seconds(60), // One minute
    std::chrono::seconds(600), // Ten minutes
    std::chrono::seconds(3600), // One hour
    std::chrono::seconds(0), // All time
};

StatsClient::StatsClient() : stats_{{}}, types_{{}} {}

void StatsClient::addStatValue(
    std::string const& key,
    int64_t value,
    StatsType type) {
  VLOG(8) << folly::sformat("StatsClient::{}()", __func__);

  auto it = stats_.find(key);
  if (it == stats_.end()) {
    VLOG(8) << folly::sformat("Initializing stats entry for {}...", key);

    // `stats_` is std::string -> folly::MultiLevelTimeSeries, and the
    // `emplace` function will create a new mapping on the fly, using
    // the parameters to std::forward_as_tuple as constructor parameters
    std::tie(it, std::ignore) = stats_.emplace(
        std::piecewise_construct,
        std::forward_as_tuple(key),
        std::forward_as_tuple(
            kTsBuckets, kLevelDurations.size(), kLevelDurations.data()));
  }

  types_.emplace(key, type);

  // Add the new value using the current time
  auto ts = std::chrono::duration_cast<std::chrono::seconds>(
      std::chrono::steady_clock::now().time_since_epoch());
  it->second.addValue(ts, value);
}

void StatsClient::incrementSumStat(const std::string& stat) {
  VLOG(8) << folly::sformat("StatsClient::{}() sum: {}", __func__, stat);
  addStatValue(stat, 1, StatsType::SUM);
}

void StatsClient::setAvgStat(const std::string& stat, int value) {
  VLOG(8) << folly::sformat("StatsClient::{}() avg: {}", __func__, stat);
  addStatValue(stat, value, StatsType::AVG);
}

const std::unordered_map<std::string, int64_t> StatsClient::getStats() {
  VLOG(8) << folly::sformat("StatsClient::{}()", __func__);
  std::unordered_map<std::string, int64_t> counters;

  for (auto& kv : stats_) {
    const std::string& key_ = kv.first;

    // Update the time series to reference against the current time
    auto ts = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::steady_clock::now().time_since_epoch());
    kv.second.update(ts);

    // For each duration, calculate the stats for it
    for (size_t i = 0; i < kLevelDurations.size(); i++) {
      auto const& level = kv.second.getLevel(i);
      auto const interval = level.duration().count();

      // Put the data together for the StatCounter thrift object,
      // which is the std::string and the associated value
      //
      // Example: fbmeshd_probe_wan_connectivity_success_sum_60 -> 59
      // Interpretation: In the last 60 seconds, the key
      //   fbmeshd_probe_wan_connectivity_success was successful 59 times.
      auto type = types_.find(key_)->second;
      if (type == StatsType::SUM) {
        auto key = folly::sformat("{}.sum.{}", key_, interval);
        counters[key] = level.sum();
      } else if (type == StatsType::AVG) {
        auto key = folly::sformat("{}.avg.{}", key_, interval);
        counters[key] = level.avg();
      } else {
        VLOG(5) << "Unsupported export type.";
      }
    }
  }

  return counters;
}

} // namespace fbmeshd
