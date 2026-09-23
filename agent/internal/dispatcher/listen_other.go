//go:build !windows

package dispatcher

import (
	"fmt"
	"net"
)

func listenTCP(port int) (net.Listener, error) {
	return net.Listen("tcp", fmt.Sprintf(":%d", port))
}
