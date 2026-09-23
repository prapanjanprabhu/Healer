//go:build windows

package dispatcher

import (
	"context"
	"fmt"
	"net"
	"syscall"

	"golang.org/x/sys/windows"
)

// soExclusiveAddrUse is SO_EXCLUSIVEADDRUSE, defined by Microsoft as
// ^SO_REUSEADDR (SO_REUSEADDR is 0x0004). Without it, Windows lets a
// higher-privileged process (this Agent normally runs as LocalSystem) bind
// over a port a lower-privileged process already has open, so a plain
// net.Listen would report an occupied port as free — found by hand while
// verifying this check against a real, currently-running listener.
const soExclusiveAddrUse = -5

// listenTCP probes whether a port is truly free, regardless of which
// account already holds it.
func listenTCP(port int) (net.Listener, error) {
	lc := net.ListenConfig{
		Control: func(_, _ string, c syscall.RawConn) error {
			var sockErr error
			if err := c.Control(func(fd uintptr) {
				sockErr = windows.SetsockoptInt(windows.Handle(fd), windows.SOL_SOCKET, soExclusiveAddrUse, 1)
			}); err != nil {
				return err
			}
			return sockErr
		},
	}
	return lc.Listen(context.Background(), "tcp", fmt.Sprintf(":%d", port))
}
