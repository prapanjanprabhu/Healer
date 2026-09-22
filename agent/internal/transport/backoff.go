package transport

import (
	"math/rand"
	"time"
)

// backoff produces exponentially increasing delays between reconnect
// attempts, capped at max, with jitter so many agents reconnecting after a
// shared outage don't all retry in lockstep.
type backoff struct {
	base    time.Duration
	max     time.Duration
	current time.Duration
}

func newBackoff(base, max time.Duration) *backoff {
	return &backoff{base: base, max: max, current: base}
}

// Next returns the delay to wait before the next attempt, then doubles the
// internal delay (capped at max) for the attempt after that.
func (b *backoff) Next() time.Duration {
	delay := b.current
	b.current *= 2
	if b.current > b.max {
		b.current = b.max
	}
	jitter := time.Duration(rand.Int63n(int64(delay)/4 + 1)) //nolint:gosec // jitter, not security-sensitive
	return delay + jitter
}

// Reset returns the backoff to its base delay — called after a successful
// connection, so a brief blip doesn't leave later reconnects waiting
// longer than necessary.
func (b *backoff) Reset() {
	b.current = b.base
}
