/**
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#pragma once

extern "C" {
#include <authsae/ampe.h>
#include <authsae/evl_ops.h>
#include <authsae/sae.h>
}

#include <folly/container/F14Map.h>
#include <folly/io/async/EventBase.h>
#include <folly/io/async/TimeoutManager.h>

// Creates the function callback tables for AMPE and SAE
ampe_cb* getAmpeCallbacks();
sae_cb* getSaeCallbacks();

namespace fbmeshd {

// This is a static class that provides certain helpers necessary for
// interfacing with libsae
class AuthsaeCallbackHelpers final {
  // This class is static, remove default copy/move
  AuthsaeCallbackHelpers() = delete;
  AuthsaeCallbackHelpers(const AuthsaeCallbackHelpers&) = delete;
  AuthsaeCallbackHelpers(AuthsaeCallbackHelpers&&) = delete;
  AuthsaeCallbackHelpers& operator=(const AuthsaeCallbackHelpers&) = delete;
  AuthsaeCallbackHelpers& operator=(AuthsaeCallbackHelpers&&) = delete;

 public:
  // Initialise the static event loop pointer
  static void init(folly::EventBase* evb);

  // Methods for controlling timeouts
  //
  // NOTE: The public-facing timeout ID returned/accepted by these methods is
  // abstracted from the timeout IDs used internally by the event loop!
  static int64_t addTimeoutToEventBase(
      std::chrono::milliseconds interval,
      timercb proc,
      void* data);
  static void removeTimeoutFromEventBase(int64_t timeoutId);

 private:
  static void verifyInitialized();

  static folly::EventBase* evb_;

  static int timeoutId_;
  static folly::F14FastMap<int64_t, folly::AsyncTimeout*> timeouts_;
};

} // namespace fbmeshd
