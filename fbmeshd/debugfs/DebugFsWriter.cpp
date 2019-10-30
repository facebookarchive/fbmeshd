/**
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "fbmeshd/debugfs/DebugFsWriter.h"

#include <fstream>

#include <folly/Format.h>
#include <sys/stat.h>

DEFINE_bool(
    enable_debugfs,
    true,
    "Write debug stats into the directory at --debugfs_dir");
DEFINE_string(
    debugfs_dir,
    "/tmp/fbmeshd_debugfs",
    "Directory to write debug stats files into. It will be created if its "
    "parent exists but it does not.");

namespace fbmeshd {

void DebugFsWriter::writeDebugStat(const std::string& key, bool value) {
  VLOG(8) << folly::sformat("DebugFsWriter::{}(value: {})", __func__, value);
  if (FLAGS_enable_debugfs) {
    writeDebugStat(key, std::string{value ? "true" : "false"});
  }
}

void DebugFsWriter::writeDebugStat(const std::string& key, double value) {
  VLOG(8) << folly::sformat("DebugFsWriter::{}(value: {})", __func__, value);
  if (FLAGS_enable_debugfs) {
    writeDebugStat(key, folly::sformat("{}", value));
  }
}

void DebugFsWriter::writeDebugStat(
    const std::string& key,
    const std::string& value) {
  VLOG(8) << folly::sformat("DebugFsWriter::{}(value: {})", __func__, value);
  if (FLAGS_enable_debugfs) {
    // Make debugfs dir if it doesn't exist (works only if its parent exists)
    mkdir(FLAGS_debugfs_dir.c_str(), 0644);

    // Write the stat to the debug dir
    std::ofstream file;
    file.open(folly::sformat("{}/{}", FLAGS_debugfs_dir, key), std::ios::trunc);
    file << key << " " << value << std::endl;
    file.close();
  }
}

} // namespace fbmeshd
