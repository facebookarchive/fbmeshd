/**
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

#include "RouteDampener.h"

#include <stdexcept>

using namespace fbmeshd;

RouteDampener::RouteDampener(
    folly::EventBase* evb,
    unsigned int penalty,
    unsigned int suppressLimit,
    unsigned int reuseLimit,
    std::chrono::seconds halfLife,
    std::chrono::seconds maxSuppressLimit)
    : evb_{evb},
      halfLifeTimer_{folly::AsyncTimeout::make(
          *evb_,
          [this]() mutable noexcept {
            halfLifeTimerExpired();
            halfLifeTimer_->scheduleTimeout(halfLife_);
          })},
      maxSuppressLimitTimer_{folly::AsyncTimeout::make(
          *evb_,
          [this]() mutable noexcept { maxSuppressLimitTimerExpired(); })},
      penalty_{penalty},
      suppressLimit_{suppressLimit},
      reuseLimit_{reuseLimit},
      halfLife_{halfLife},
      maxSuppressLimit_{maxSuppressLimit} {
  if (!isValid()) {
    throw std::range_error(
        "route dampener values are not logically consistent");
  }
}

bool RouteDampener::isValid() const {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  const unsigned int maxPenalty{reuseLimit_ *
                                (1 << (maxSuppressLimit_ / halfLife_))};
  return penalty_ <= maxPenalty;
}

unsigned int RouteDampener::getHistory() const {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  return history_;
}

void RouteDampener::setHistory(unsigned int newHistory) {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  history_ = newHistory;
  setRdStat("default_route_history", history_);
  LOG(INFO) << "route dampener history set to " << history_;
}

void RouteDampener::flap() {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  evb_->runImmediatelyOrRunInEventBaseThreadAndWait([this]() {
    setHistory(history_ + penalty_);

    LOG(INFO) << "route dampener received flap";

    if (!dampened_ && history_ >= suppressLimit_) {
      LOG(INFO) << "route dampener dampening route ";
      dampened_ = true;
      setRdStat("default_route_dampened", 1);
      startHalfLifeTimer();
      startMaxSuppressLimitTimer();
      dampen();
    }
  });
}

bool RouteDampener::isDampened() const {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  return dampened_;
}

void RouteDampener::undampenImpl() {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  CHECK(dampened_);

  dampened_ = false;
  stopMaxSuppressLimitTimer();
  undampen();
  setRdStat("default_route_dampened", 0);
}

void RouteDampener::halfLifeTimerExpired() {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  setHistory(history_ / 2);

  LOG(INFO) << "route dampener half life timer expired";

  if (history_ <= (reuseLimit_ / 2)) {
    LOG(INFO) << "route dampener reseting history";
    setHistory(0);
    stopHalfLifeTimer();
  }

  if (dampened_ && history_ <= reuseLimit_) {
    undampenImpl();
  }
  userHalfLifeTimerExpired();
}

void RouteDampener::maxSuppressLimitTimerExpired() {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  LOG(INFO) << "route dampener max suppress limit timer expired";
  if (dampened_) {
    setHistory(0);
    stopHalfLifeTimer();
    undampenImpl();
  }
  userSuppressLimitTimerExpired();
}

void RouteDampener::startHalfLifeTimer() {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  DCHECK_NOTNULL(halfLifeTimer_.get());
  halfLifeTimer_->scheduleTimeout(halfLife_);
}

void RouteDampener::startMaxSuppressLimitTimer() {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  DCHECK_NOTNULL(maxSuppressLimitTimer_.get());
  maxSuppressLimitTimer_->scheduleTimeout(maxSuppressLimit_);
}

void RouteDampener::stopMaxSuppressLimitTimer() {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  DCHECK_NOTNULL(maxSuppressLimitTimer_.get());
  if (maxSuppressLimitTimer_->isScheduled()) {
    maxSuppressLimitTimer_->cancelTimeout();
  }
}

void RouteDampener::stopHalfLifeTimer() {
  VLOG(8) << folly::sformat("RouteDampener::{}()", __func__);
  DCHECK_NOTNULL(halfLifeTimer_.get());
  if (halfLifeTimer_->isScheduled()) {
    halfLifeTimer_->cancelTimeout();
  }
}
