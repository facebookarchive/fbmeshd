/**
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#pragma once

#include <string>

#include <glog/logging.h>

DECLARE_bool(enable_debugfs);
DECLARE_string(debugfs_dir);

namespace fbmeshd {

// This class is intended as a utility class for writing stats to a directory in
// the style of debugfs
class DebugFsWriter final {
 public:
  DebugFsWriter();
  ~DebugFsWriter() = default;
  DebugFsWriter(const DebugFsWriter&) = delete;
  DebugFsWriter& operator=(const DebugFsWriter&) = delete;
  DebugFsWriter(DebugFsWriter&&) = delete;
  DebugFsWriter& operator=(DebugFsWriter&&) = delete;

  static void writeDebugStat(const std::string& key, double value);
  static void writeDebugStat(const std::string& key, const std::string& value);
};

} // namespace fbmeshd
